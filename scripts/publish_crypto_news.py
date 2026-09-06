#!/usr/bin/env python3
"""Validate a Google Sheet publish payload and safely upsert the public manifest.

The script is intentionally independent from Google APIs.  A spreadsheet-bound
Apps Script serializes the review sheet and dispatches a GitHub Actions run;
this module treats that payload as untrusted input and builds the only file the
publisher is allowed to commit: ``data/crypto-news.json``.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import gzip
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit


KST = timezone(timedelta(hours=9), name="KST")
PAYLOAD_SCHEMA_VERSION = "1.0"
MANIFEST_SCHEMA_VERSION = "1.0"
TARGET_BRANCH = "main"
MAX_RAW_PAYLOAD_BYTES = 750_000
MAX_COMPRESSED_PAYLOAD_BYTES = 45_000
MAX_ENCODED_PAYLOAD_CHARS = 60_000
MAX_ITEMS = 8
MAX_SOURCES = 20
MAX_PAYLOAD_AGE = timedelta(minutes=30)
MAX_REVIEW_AGE = timedelta(days=7)
MAX_CLOCK_SKEW = timedelta(minutes=2)
DISCOVERY_ONLY_DOMAINS = {"coinness.com"}
TRACKING_QUERY_KEYS = {"fbclid", "gclid"}

PUBLISH_ID_RE = re.compile(r"^\d{8}-[0-9a-f]{24}$")
SOURCE_ITEM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SPREADSHEET_ID_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
PUBLIC_ID_RE = re.compile(r"^crypto-news-[0-9a-f]{16}$")
PUBLIC_SLUG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-crypto-news-[0-9a-f]{10}$")

PAYLOAD_FIELDS = {
    "schema_version",
    "publish_id",
    "created_at_kst",
    "production",
    "target_branch",
    "spreadsheet_id",
    "sheet_name",
    "date_kst",
    "expected_item_count",
    "items",
}
ITEM_FIELDS = {
    "source_item_id",
    "date_kst",
    "title",
    "content",
    "metanomia_thought",
    "decision",
    "reviewer",
    "reviewed_at_kst",
    "notes",
    "sources",
}
SOURCE_FIELDS = {"title", "publisher", "url"}
MANIFEST_FIELDS = {"schema_version", "generated_at_kst", "items"}
PUBLIC_ITEM_FIELDS = {
    "id",
    "slug",
    "date_kst",
    "title",
    "content",
    "metanomia_thought",
    "sources",
}
PUBLIC_SOURCE_FIELDS = {"title", "url"}
ENGLISH_ITEM_FIELDS = {
    "slug",
    "date_kst",
    "title",
    "content",
    "metanomia_thought",
    "sources",
}
ALLOWED_PUBLICATION_PATHS = {
    "data/crypto-news.json",
    "data/crypto-news.en.json",
    "sitemap.xml",
}
ALLOWED_PUBLICATION_PAGE_RE = re.compile(
    r"^(?:ko/)?crypto-news-20\d{2}-\d{2}-\d{2}-crypto-news-[0-9a-f]{10}\.html$"
)


class PublishValidationError(ValueError):
    """Raised when publication must stop without changing the website."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def require_exact_fields(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PublishValidationError(f"{label} must be a JSON object.")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise PublishValidationError(
            f"{label} fields do not match the contract (missing={missing}, extra={extra})."
        )
    return value


def require_nonempty_string(value: Any, label: str, *, max_length: int = 200_000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PublishValidationError(f"{label} must be a non-empty string.")
    text = value.strip()
    if len(text) > max_length:
        raise PublishValidationError(f"{label} is too long.")
    return text


def parse_date(value: Any, label: str = "date_kst") -> date:
    text = require_nonempty_string(value, label, max_length=10)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise PublishValidationError(f"{label} must use YYYY-MM-DD.") from exc
    if parsed.isoformat() != text:
        raise PublishValidationError(f"{label} must use YYYY-MM-DD.")
    return parsed


def parse_kst_timestamp(value: Any, label: str) -> datetime:
    text = require_nonempty_string(value, label, max_length=40)
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) KST", text)
    try:
        if match:
            parsed = datetime.strptime(
                f"{match.group(1)} {match.group(2)}", "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=KST)
        else:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PublishValidationError(
            f"{label} must be a valid KST timestamp or timezone-aware ISO timestamp."
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(hours=9):
        raise PublishValidationError(f"{label} must explicitly use KST (+09:00).")
    return parsed.astimezone(KST)


def current_kst() -> datetime:
    return datetime.now(KST)


def validate_https_url(value: Any, label: str) -> str:
    url = require_nonempty_string(value, label, max_length=4_000)
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError as exc:
        raise PublishValidationError(f"{label} is not a valid HTTPS URL.") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise PublishValidationError(f"{label} must be an HTTPS URL with a real host.")
    hostname = parsed.hostname.lower().rstrip(".")
    if any(hostname == domain or hostname.endswith(f".{domain}") for domain in DISCOVERY_ONLY_DOMAINS):
        raise PublishValidationError(f"{label} uses discovery-only source host {hostname}.")
    return url


def semantic_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"publish_id", "created_at_kst"}
    }


def expected_publish_id(payload: dict[str, Any]) -> str:
    report_date = require_nonempty_string(payload.get("date_kst"), "date_kst", max_length=10)
    digest = hashlib.sha256(canonical_json(semantic_payload(payload)).encode("utf-8")).hexdigest()
    return f"{report_date.replace('-', '')}-{digest[:24]}"


def validate_payload(
    payload: Any,
    *,
    now_kst: datetime | None = None,
    enforce_current_time: bool = True,
) -> dict[str, Any]:
    data = require_exact_fields(payload, PAYLOAD_FIELDS, "payload")
    if data["schema_version"] != PAYLOAD_SCHEMA_VERSION:
        raise PublishValidationError(f"payload.schema_version must be {PAYLOAD_SCHEMA_VERSION}.")
    if data["production"] is not True or data["target_branch"] != TARGET_BRANCH:
        raise PublishValidationError("Production must be explicitly true and target_branch must be main.")
    report_date = parse_date(data["date_kst"])
    if data["sheet_name"] != report_date.isoformat():
        raise PublishValidationError("sheet_name must exactly match date_kst.")
    if not isinstance(data["spreadsheet_id"], str) or not SPREADSHEET_ID_RE.fullmatch(
        data["spreadsheet_id"]
    ):
        raise PublishValidationError("spreadsheet_id is invalid.")
    created_at = parse_kst_timestamp(data["created_at_kst"], "created_at_kst")
    if enforce_current_time:
        now = (now_kst or current_kst()).astimezone(KST)
        if created_at > now + MAX_CLOCK_SKEW:
            raise PublishValidationError("created_at_kst is too far in the future.")
        if created_at < now - MAX_PAYLOAD_AGE:
            raise PublishValidationError("created_at_kst is stale; create a fresh Sheet payload.")

    publish_id = data["publish_id"]
    if not isinstance(publish_id, str) or not PUBLISH_ID_RE.fullmatch(publish_id):
        raise PublishValidationError("publish_id is invalid.")
    if publish_id != expected_publish_id(data):
        raise PublishValidationError("publish_id does not match the canonical payload digest.")

    items = data["items"]
    if not isinstance(items, list) or not (1 <= len(items) <= MAX_ITEMS):
        raise PublishValidationError(f"items must contain between 1 and {MAX_ITEMS} entries.")
    if type(data["expected_item_count"]) is not int:
        raise PublishValidationError("expected_item_count must be an integer, not a boolean.")
    if data["expected_item_count"] != len(items):
        raise PublishValidationError("expected_item_count does not match items length.")

    seen_source_item_ids: set[str] = set()
    approved_count = 0
    for index, raw_item in enumerate(items, start=1):
        item = require_exact_fields(raw_item, ITEM_FIELDS, f"item {index}")
        source_item_id = item["source_item_id"]
        if not isinstance(source_item_id, str) or not SOURCE_ITEM_ID_RE.fullmatch(source_item_id):
            raise PublishValidationError(f"item {index}.source_item_id is invalid.")
        if source_item_id in seen_source_item_ids:
            raise PublishValidationError(f"Duplicate source_item_id: {source_item_id}.")
        seen_source_item_ids.add(source_item_id)
        if item["date_kst"] != report_date.isoformat():
            raise PublishValidationError(f"item {index}.date_kst does not match payload date.")

        decision = item["decision"]
        if decision not in {"approved", "rejected"}:
            raise PublishValidationError(
                f"item {index}.decision must be approved or rejected; pending reviews cannot publish."
            )
        approved_count += decision == "approved"
        require_nonempty_string(item["title"], f"item {index}.title")
        require_nonempty_string(item["content"], f"item {index}.content")
        require_nonempty_string(item["metanomia_thought"], f"item {index}.metanomia_thought")
        require_nonempty_string(item["reviewer"], f"item {index}.reviewer", max_length=200)
        reviewed_at = parse_kst_timestamp(
            item["reviewed_at_kst"], f"item {index}.reviewed_at_kst"
        )
        if reviewed_at > created_at + MAX_CLOCK_SKEW:
            raise PublishValidationError(
                f"item {index}.reviewed_at_kst is later than the payload creation time."
            )
        if reviewed_at < created_at - MAX_REVIEW_AGE:
            raise PublishValidationError(f"item {index}.reviewed_at_kst is stale.")
        if not isinstance(item["notes"], str):
            raise PublishValidationError(f"item {index}.notes must be a string.")

        sources = item["sources"]
        if not isinstance(sources, list) or not (1 <= len(sources) <= MAX_SOURCES):
            raise PublishValidationError(
                f"item {index}.sources must contain between 1 and {MAX_SOURCES} entries."
            )
        seen_urls: set[str] = set()
        for source_index, raw_source in enumerate(sources, start=1):
            source = require_exact_fields(
                raw_source, SOURCE_FIELDS, f"item {index}.source {source_index}"
            )
            require_nonempty_string(
                source["title"], f"item {index}.source {source_index}.title", max_length=2_000
            )
            require_nonempty_string(
                source["publisher"],
                f"item {index}.source {source_index}.publisher",
                max_length=500,
            )
            url = validate_https_url(source["url"], f"item {index}.source {source_index}.url")
            if url in seen_urls:
                raise PublishValidationError(f"item {index} contains duplicate source URL {url}.")
            seen_urls.add(url)

    if approved_count == 0:
        raise PublishValidationError("At least one item must be approved; refusing to empty the site.")
    return data


def validate_manifest(manifest: Any) -> dict[str, Any]:
    data = require_exact_fields(manifest, MANIFEST_FIELDS, "manifest")
    if data["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise PublishValidationError(f"manifest.schema_version must be {MANIFEST_SCHEMA_VERSION}.")
    parse_kst_timestamp(data["generated_at_kst"], "manifest.generated_at_kst")
    items = data["items"]
    if not isinstance(items, list):
        raise PublishValidationError("manifest.items must be an array.")

    seen_ids: set[str] = set()
    seen_slugs: set[str] = set()
    for index, raw_item in enumerate(items, start=1):
        item = require_exact_fields(raw_item, PUBLIC_ITEM_FIELDS, f"manifest item {index}")
        if not isinstance(item["id"], str) or not PUBLIC_ID_RE.fullmatch(item["id"]):
            raise PublishValidationError(f"manifest item {index}.id is invalid.")
        if not isinstance(item["slug"], str) or not PUBLIC_SLUG_RE.fullmatch(item["slug"]):
            raise PublishValidationError(f"manifest item {index}.slug is invalid.")
        if item["id"] in seen_ids or item["slug"] in seen_slugs:
            raise PublishValidationError("manifest contains a duplicate id or slug.")
        seen_ids.add(item["id"])
        seen_slugs.add(item["slug"])
        parse_date(item["date_kst"], f"manifest item {index}.date_kst")
        for field in ("title", "content", "metanomia_thought"):
            require_nonempty_string(item[field], f"manifest item {index}.{field}")
        sources = item["sources"]
        if not isinstance(sources, list) or not sources:
            raise PublishValidationError(f"manifest item {index}.sources is empty.")
        for source_index, raw_source in enumerate(sources, start=1):
            source = require_exact_fields(
                raw_source, PUBLIC_SOURCE_FIELDS, f"manifest item {index}.source {source_index}"
            )
            require_nonempty_string(
                source["title"], f"manifest item {index}.source {source_index}.title"
            )
            validate_https_url(source["url"], f"manifest item {index}.source {source_index}.url")
    return data


def validate_english_manifest(manifest: Any) -> dict[str, Any]:
    data = require_exact_fields(manifest, MANIFEST_FIELDS, "English manifest")
    if data["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise PublishValidationError(
            f"English manifest.schema_version must be {MANIFEST_SCHEMA_VERSION}."
        )
    parse_kst_timestamp(data["generated_at_kst"], "English manifest.generated_at_kst")
    if not isinstance(data["items"], list):
        raise PublishValidationError("English manifest.items must be an array.")
    seen_slugs: set[str] = set()
    for index, raw_item in enumerate(data["items"], start=1):
        item = require_exact_fields(raw_item, ENGLISH_ITEM_FIELDS, f"English item {index}")
        slug = item["slug"]
        if not isinstance(slug, str) or not PUBLIC_SLUG_RE.fullmatch(slug):
            raise PublishValidationError(f"English item {index}.slug is invalid.")
        if slug in seen_slugs:
            raise PublishValidationError("English manifest contains a duplicate slug.")
        seen_slugs.add(slug)
        parse_date(item["date_kst"], f"English item {index}.date_kst")
        for field in ("title", "content", "metanomia_thought"):
            require_nonempty_string(item[field], f"English item {index}.{field}")
        sources = item["sources"]
        if not isinstance(sources, list) or not sources:
            raise PublishValidationError(f"English item {index}.sources is empty.")
        for source_index, raw_source in enumerate(sources, start=1):
            source = require_exact_fields(
                raw_source,
                PUBLIC_SOURCE_FIELDS,
                f"English item {index}.source {source_index}",
            )
            require_nonempty_string(
                source["title"], f"English item {index}.source {source_index}.title"
            )
            validate_https_url(
                source["url"], f"English item {index}.source {source_index}.url"
            )
    return data


def normalize_url(url: str) -> str:
    """Return a canonical source fingerprint while preserving semantic query keys."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    port = f":{parsed.port}" if parsed.port and parsed.port != 443 else ""
    path = parsed.path.rstrip("/") or "/"
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_KEYS
    ]
    query.sort()
    suffix = f"?{urlencode(query, doseq=True)}" if query else ""
    return f"{host}{port}{path}{suffix}"


def legacy_public_identity(report_date: str, item: dict[str, Any]) -> tuple[str, str]:
    """Compute the pre-cloud URL-derived id/slug for backwards compatibility."""
    parsed = urlsplit(item["sources"][0]["url"])
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    fingerprint = f"{host}{parsed.path.rstrip('/')}"
    digest = hashlib.sha256(f"{report_date}\0{fingerprint}".encode("utf-8")).hexdigest()
    return f"crypto-news-{digest[:16]}", f"{report_date}-crypto-news-{digest[:10]}"


def public_record(report_date: str, item: dict[str, Any]) -> dict[str, Any]:
    # source_item_id is immutable in the review data, so correcting a URL or title
    # cannot silently change the public permalink.
    identity = f"source-item-v1\0{item['source_item_id']}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return {
        "id": f"crypto-news-{digest[:16]}",
        "slug": f"{report_date}-crypto-news-{digest[:10]}",
        "date_kst": report_date,
        "title": item["title"].strip(),
        "content": item["content"].strip(),
        "metanomia_thought": item["metanomia_thought"].strip(),
        # publisher stays in the review payload; the current public schema deliberately
        # exposes only source title and URL.
        "sources": [
            {"title": source["title"].strip(), "url": source["url"].strip()}
            for source in item["sources"]
        ],
    }


def upsert_manifest(payload: Any, current_manifest: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    data = validate_payload(payload)
    current = validate_manifest(current_manifest)
    report_date = data["date_kst"]

    existing_by_id = {item["id"]: item for item in current["items"]}
    candidates: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    candidate_primary_fingerprints: set[str] = set()
    for item in data["items"]:
        record = public_record(report_date, item)
        legacy_id, legacy_slug = legacy_public_identity(report_date, item)
        if record["id"] not in existing_by_id and legacy_id in existing_by_id:
            # Existing URL-derived records keep their permalink. New records use the
            # stable source_item_id scheme above.
            record["id"] = legacy_id
            record["slug"] = legacy_slug
        prior_candidate = candidates.get(record["id"])
        if prior_candidate and (
            prior_candidate[0]["decision"] == "approved" or item["decision"] == "approved"
        ):
            raise PublishValidationError(
                "Two sheet items resolve to the same public id; source_item_id values must be unique."
            )
        candidates[record["id"]] = (item, record)
        if item["decision"] == "approved":
            primary_fingerprint = normalize_url(item["sources"][0]["url"])
            if primary_fingerprint in candidate_primary_fingerprints:
                raise PublishValidationError(
                    "Two approved sheet items use the same canonical primary source URL."
                )
            candidate_primary_fingerprints.add(primary_fingerprint)

    existing_primary_fingerprints: dict[str, list[dict[str, Any]]] = {}
    for existing in current["items"]:
        fingerprint = normalize_url(existing["sources"][0]["url"])
        existing_primary_fingerprints.setdefault(fingerprint, []).append(existing)

    for public_id, (item, _record) in candidates.items():
        if item["decision"] != "approved":
            continue
        existing_same_id = existing_by_id.get(public_id)
        if existing_same_id and existing_same_id["date_kst"] != report_date:
            raise PublishValidationError(
                f"source_item_id collides with existing article {public_id} on another date."
            )
        fingerprint = normalize_url(item["sources"][0]["url"])
        cross_date_matches = [
            existing
            for existing in existing_primary_fingerprints.get(fingerprint, [])
            if existing["id"] != public_id and existing["date_kst"] != report_date
        ]
        if cross_date_matches:
            raise PublishValidationError(
                "The canonical primary source URL is already published on another date."
            )
    for existing in current["items"]:
        if existing["date_kst"] != report_date:
            continue
        candidate = candidates.get(existing["id"])
        if candidate is None:
            raise PublishValidationError(
                f"Existing public article {existing['id']} is absent from the sheet payload; "
                "automatic deletion is forbidden."
            )
        if candidate[0]["decision"] != "approved":
            raise PublishValidationError(
                f"Existing public article {existing['id']} is now rejected; automatic deletion is forbidden."
            )

    next_by_id = dict(existing_by_id)
    approved_count = 0
    added_count = 0
    updated_count = 0
    changed_slugs: list[str] = []
    for item, record in candidates.values():
        if item["decision"] != "approved":
            continue
        approved_count += 1
        previous = next_by_id.get(record["id"])
        if previous is None:
            added_count += 1
            changed_slugs.append(record["slug"])
        elif previous != record:
            updated_count += 1
            changed_slugs.append(record["slug"])
        next_by_id[record["id"]] = record

    reviewed_times = [
        parse_kst_timestamp(item["reviewed_at_kst"], "reviewed_at_kst")
        for item in data["items"]
        if item["decision"] == "approved"
    ]
    current_generated = parse_kst_timestamp(current["generated_at_kst"], "generated_at_kst")
    generated_at = (
        max([current_generated, *reviewed_times]).isoformat(timespec="seconds")
        if added_count or updated_count
        else current["generated_at_kst"]
    )
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at_kst": generated_at,
        "items": sorted(
            next_by_id.values(),
            key=lambda entry: (entry["date_kst"], entry["id"]),
            reverse=True,
        ),
    }
    validate_manifest(manifest)
    metadata = {
        "publish_id": data["publish_id"],
        "date_kst": report_date,
        "approved_count": approved_count,
        "added_count": added_count,
        "updated_count": updated_count,
        "changed_slugs": changed_slugs,
        "item_count": len(manifest["items"]),
    }
    return manifest, metadata


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublishValidationError(f"Could not read {label}: {exc}") from exc


def append_github_outputs(path: Path, metadata: dict[str, Any]) -> None:
    safe_fields = ("publish_id", "date_kst", "approved_count", "added_count", "updated_count", "item_count")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for key in safe_fields:
            value = str(metadata[key])
            if "\n" in value or "\r" in value:
                raise PublishValidationError(f"Unsafe GitHub output value for {key}.")
            handle.write(f"{key}={value}\n")


def run_git(repository: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repository,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PublishValidationError(f"Git command failed safely: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown Git error").strip()
        raise PublishValidationError(f"Git command failed safely: {detail[:1000]}")
    return result.stdout.strip()


def validate_publish_id(publish_id: str) -> str:
    if not PUBLISH_ID_RE.fullmatch(publish_id):
        raise PublishValidationError("publish_id is invalid.")
    return publish_id


def publication_path_allowed(path: str) -> bool:
    return path in ALLOWED_PUBLICATION_PATHS or bool(ALLOWED_PUBLICATION_PAGE_RE.fullmatch(path))


def parse_safe_name_status(output: str, label: str) -> list[str]:
    paths: list[str] = []
    for line in output.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 2 or parts[0] not in {"A", "M"}:
            raise PublishValidationError(
                f"{label} contains a deletion, rename, copy, type change, or invalid status: {line}."
            )
        paths.append(parts[1])
    return paths


def changed_worktree_paths(repository: Path) -> list[str]:
    tracked = parse_safe_name_status(
        run_git(repository, ["diff", "--name-status", "HEAD", "--"]), "worktree"
    )
    untracked = run_git(repository, ["ls-files", "--others", "--exclude-standard"]).splitlines()
    return sorted(set(path for path in [*tracked, *untracked] if path))


def find_applied_publish_id(repository: Path, publish_id: str) -> str | None:
    """Find a replay only on the production branch's first-parent history."""
    validate_publish_id(publish_id)
    marker = f"[publish_id:{publish_id}]"
    found = run_git(
        repository,
        [
            "log",
            "origin/main",
            "--first-parent",
            "--format=%H",
            "--fixed-strings",
            f"--grep={marker}",
            "-n",
            "1",
        ],
    )
    if not found:
        return None
    if not re.fullmatch(r"[0-9a-fA-F]{40}", found):
        raise PublishValidationError("Existing publish marker resolved to an invalid commit.")
    files = parse_safe_name_status(
        run_git(repository, ["diff-tree", "--no-commit-id", "--name-status", "-r", found]),
        "existing publish commit",
    )
    if not files or any(not publication_path_allowed(path) for path in files):
        raise PublishValidationError(
            "Existing publish marker belongs to a commit outside the publication allowlist."
        )
    return found


def git_preflight(repository: Path, branch: str, remote: str) -> str:
    if branch != TARGET_BRANCH or remote != "origin":
        raise PublishValidationError("Cloud publisher only permits origin/main.")
    top = Path(run_git(repository, ["rev-parse", "--show-toplevel"])).resolve()
    if top != repository.resolve():
        raise PublishValidationError("Repository path is not the Git top level.")
    if run_git(repository, ["branch", "--show-current"]) != branch:
        raise PublishValidationError("The checked-out branch is not main.")
    if run_git(repository, ["status", "--porcelain=v1", "--untracked-files=all"]):
        raise PublishValidationError("The website worktree is not clean.")
    head = run_git(repository, ["rev-parse", "HEAD"])
    remote_head = run_git(repository, ["rev-parse", "--verify", f"refs/remotes/{remote}/{branch}"])
    if head != remote_head:
        raise PublishValidationError("HEAD is not exactly synchronized with origin/main.")
    return head


def guard_worktree(repository: Path) -> list[str]:
    changed = changed_worktree_paths(repository)
    rejected = [path for path in changed if not publication_path_allowed(path)]
    if rejected:
        raise PublishValidationError(
            f"Files outside the publication allowlist changed: {', '.join(rejected)}."
        )
    return changed


def guard_staged(repository: Path) -> list[str]:
    staged = parse_safe_name_status(
        run_git(repository, ["diff", "--cached", "--name-status", "--"]), "staged changes"
    )
    if not staged or any(not publication_path_allowed(path) for path in staged):
        raise PublishValidationError("The index is empty or contains a file outside the publication allowlist.")
    return staged


def guard_commit(repository: Path, expected_parent: str, publish_id: str) -> None:
    validate_publish_id(publish_id)
    if not re.fullmatch(r"[0-9a-fA-F]{40}", expected_parent):
        raise PublishValidationError("expected_parent is invalid.")
    parent = run_git(repository, ["rev-parse", "HEAD^"])
    files = parse_safe_name_status(
        run_git(repository, ["diff-tree", "--no-commit-id", "--name-status", "-r", "HEAD"]),
        "new commit",
    )
    subject = run_git(repository, ["log", "-1", "--pretty=%s"])
    if parent != expected_parent or not files or any(
        not publication_path_allowed(path) for path in files
    ):
        raise PublishValidationError("The new commit parent or publication file allowlist is invalid.")
    if f"[publish_id:{publish_id}]" not in subject:
        raise PublishValidationError("The new commit does not contain the expected publish_id marker.")


def command_decode(args: argparse.Namespace) -> None:
    encoded = os.environ.get("PUBLISH_PAYLOAD_GZIP_BASE64", "")
    expected_digest = os.environ.get("PUBLISH_PAYLOAD_SHA256", "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        raise PublishValidationError("PUBLISH_PAYLOAD_SHA256 is missing or invalid.")
    if not encoded or len(encoded) > MAX_ENCODED_PAYLOAD_CHARS:
        raise PublishValidationError("Compressed payload input is empty or exceeds 60,000 characters.")
    try:
        compressed = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PublishValidationError("PUBLISH_PAYLOAD_GZIP_BASE64 is invalid.") from exc
    if not compressed or len(compressed) > MAX_COMPRESSED_PAYLOAD_BYTES:
        raise PublishValidationError("Compressed payload is empty or exceeds 45,000 bytes.")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as stream:
            raw = stream.read(MAX_RAW_PAYLOAD_BYTES + 1)
    except (OSError, EOFError) as exc:
        raise PublishValidationError("Compressed payload is not valid gzip data.") from exc
    if not raw or len(raw) > MAX_RAW_PAYLOAD_BYTES:
        raise PublishValidationError("Uncompressed payload is empty or exceeds 750,000 bytes.")
    actual_digest = hashlib.sha256(raw).hexdigest()
    if actual_digest != expected_digest:
        raise PublishValidationError("Payload SHA-256 does not match.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublishValidationError("Decoded payload is not valid UTF-8 JSON.") from exc
    # A structurally valid old payload may be a legitimate replay. Freshness is
    # enforced later by prepare only when the publish id is not already applied.
    validate_payload(value, enforce_current_time=False)
    atomic_write_json(args.output, value)
    if getattr(args, "github_output", None):
        with args.github_output.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"publish_id={value['publish_id']}\n")
            handle.write(f"date_kst={value['date_kst']}\n")


def command_prepare(args: argparse.Namespace) -> None:
    payload = load_json(args.payload, "payload")
    manifest = load_json(args.manifest, "current manifest")
    next_manifest, metadata = upsert_manifest(payload, manifest)
    atomic_write_json(args.output, next_manifest)
    if args.metadata_output:
        atomic_write_json(args.metadata_output, metadata)
    if args.github_output:
        append_github_outputs(args.github_output, metadata)


def command_install(args: argparse.Namespace) -> None:
    manifest = load_json(args.source, "prepared manifest")
    validate_manifest(manifest)
    atomic_write_json(args.target, manifest)


def verify_static_pages(repository: Path) -> None:
    korean = validate_manifest(load_json(repository / "data/crypto-news.json", "public manifest"))
    english = validate_english_manifest(
        load_json(repository / "data/crypto-news.en.json", "English public manifest")
    )
    korean_by_slug = {item["slug"]: item for item in korean["items"]}
    english_by_slug = {item["slug"]: item for item in english["items"]}
    if list(korean_by_slug) != list(english_by_slug):
        raise PublishValidationError(
            "Korean and English manifest slug order differs; simultaneous publication is required."
        )
    if korean["generated_at_kst"] != english["generated_at_kst"]:
        raise PublishValidationError("Korean and English manifest generation timestamps differ.")
    for slug, korean_item in korean_by_slug.items():
        english_item = english_by_slug[slug]
        if (
            korean_item["date_kst"] != english_item["date_kst"]
            or korean_item["sources"] != english_item["sources"]
        ):
            raise PublishValidationError(
                f"English item {slug} does not preserve the Korean date and sources."
            )
    missing: list[str] = []
    for slug in korean_by_slug:
        korean_path = repository / "ko" / f"crypto-news-{slug}.html"
        english_path = repository / f"crypto-news-{slug}.html"
        if not korean_path.is_file():
            missing.append(korean_path.relative_to(repository).as_posix())
        if not english_path.is_file():
            missing.append(english_path.relative_to(repository).as_posix())
    if missing:
        preview = ", ".join(missing[:5])
        suffix = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
        raise PublishValidationError(f"Bilingual static article pages are missing: {preview}{suffix}.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    decode = sub.add_parser("decode", help="Decode and integrity-check the dispatch payload.")
    decode.add_argument("--output", type=Path, required=True)
    decode.add_argument("--github-output", type=Path)
    decode.set_defaults(func=command_decode)

    prepare = sub.add_parser("prepare", help="Validate payload and build the next manifest.")
    prepare.add_argument("--payload", type=Path, required=True)
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--metadata-output", type=Path)
    prepare.add_argument("--github-output", type=Path)
    prepare.set_defaults(func=command_prepare)

    install = sub.add_parser("install", help="Atomically install a validated prepared manifest.")
    install.add_argument("--source", type=Path, required=True)
    install.add_argument("--target", type=Path, required=True)
    install.set_defaults(func=command_install)

    static_pages = sub.add_parser(
        "verify-static-pages", help="Require synchronized Korean and English manifests and pages."
    )
    static_pages.add_argument("--repository", type=Path, required=True)
    static_pages.set_defaults(
        func=lambda args: verify_static_pages(args.repository.resolve())
    )

    applied = sub.add_parser("check-applied", help="Detect an idempotent production replay.")
    applied.add_argument("--repository", type=Path, required=True)
    applied.add_argument("--publish-id", required=True)
    applied.add_argument("--github-output", type=Path)

    def do_check_applied(args: argparse.Namespace) -> None:
        commit_sha = find_applied_publish_id(args.repository.resolve(), args.publish_id)
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(f"already_applied={'true' if commit_sha else 'false'}\n")
                handle.write(f"commit_sha={commit_sha or ''}\n")

    applied.set_defaults(func=do_check_applied)

    preflight = sub.add_parser("git-preflight", help="Require a clean, synchronized main branch.")
    preflight.add_argument("--repository", type=Path, required=True)
    preflight.add_argument("--branch", required=True)
    preflight.add_argument("--remote", required=True)
    preflight.add_argument("--github-output", type=Path)

    def do_preflight(args: argparse.Namespace) -> None:
        head = git_preflight(args.repository.resolve(), args.branch, args.remote)
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(f"base_head={head}\n")

    preflight.set_defaults(func=do_preflight)

    worktree = sub.add_parser("guard-worktree", help="Allow only publication outputs to change.")
    worktree.add_argument("--repository", type=Path, required=True)
    worktree.add_argument("--github-output", type=Path)

    def do_guard_worktree(args: argparse.Namespace) -> None:
        changed = guard_worktree(args.repository.resolve())
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(f"has_changes={'true' if changed else 'false'}\n")
                handle.write(f"change_count={len(changed)}\n")

    worktree.set_defaults(func=do_guard_worktree)

    staged = sub.add_parser("guard-staged", help="Allow only the manifest in the Git index.")
    staged.add_argument("--repository", type=Path, required=True)
    staged.set_defaults(func=lambda args: guard_staged(args.repository.resolve()))

    commit = sub.add_parser("guard-commit", help="Verify the exact commit before push.")
    commit.add_argument("--repository", type=Path, required=True)
    commit.add_argument("--expected-parent", required=True)
    commit.add_argument("--publish-id", required=True)
    commit.set_defaults(
        func=lambda args: guard_commit(
            args.repository.resolve(), args.expected_parent, args.publish_id
        )
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except PublishValidationError as exc:
        print(f"publish blocked: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
