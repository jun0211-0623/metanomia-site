#!/usr/bin/env python3
"""Discover published Korean content and record explicitly reviewed English work.

No model, network, commit, or publication operations are performed. Existing
pairs may be preserved once at installation, without claiming semantic review.
English authorship happens before record-reviewed; the publication planner must
bind those edits to its complete pre-authoring snapshot. Source/state hashes
are checked here, and each authored output is checked against its actual bytes.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any
from urllib.parse import unquote, urlsplit

STATE_PATH = ".newsroom/content-translation-state.json"
GENERATED_NEWS = re.compile(r"ko/crypto-news-20\d{2}-\d{2}-\d{2}-crypto-news-[0-9a-f]{10}\.html\Z")
SHA1 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".svg", ".ico"}
ASSET_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}
SITE_HOSTS = {"metanomia.org", "www.metanomia.org", "metanomia-site.vercel.app"}
RECORD_FIELDS = {"kind", "source_sha", "source_hash", "outputs", "review_status",
                 "asset_disposition", "reviewed_at", "external_sources"}


class ContentError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def blob_sha(content: bytes) -> str:
    return hashlib.sha1(f"blob {len(content)}\0".encode("ascii") + content).hexdigest()


def safe_path(path: Any) -> str:
    if not isinstance(path, str) or not path or "\\" in path or ":" in path:
        raise ContentError(f"Unsafe path: {path!r}")
    if any(part in {"", ".", ".."} or part.casefold() == ".git" for part in path.split("/")):
        raise ContentError(f"Unsafe path: {path!r}")
    if any(ord(character) < 32 or ord(character) == 127 for character in path):
        raise ContentError(f"Unsafe path: {path!r}")
    return path


def require_hash(value: Any, label: str, sha1: bool = False) -> str:
    if not isinstance(value, str) or not (SHA1 if sha1 else SHA256).fullmatch(value):
        raise ContentError(f"Invalid {label} hash.")
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContentError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ContentError(f"Cannot read JSON {path}: {exc}") from exc


def file_bytes(repository: Path, relative: str) -> bytes:
    safe_path(relative)
    path = repository / relative
    for ancestor in (path, *path.parents):
        if ancestor == repository:
            break
        if ancestor.is_symlink():
            raise ContentError(f"Symlink source or output is forbidden: {relative}")
    if not path.is_file():
        raise ContentError(f"Required regular file is missing: {relative}")
    return path.read_bytes()


def optional_sha(repository: Path, path: str) -> str | None:
    if (repository / path).is_symlink():
        raise ContentError(f"Symlink source or output is forbidden: {path}")
    return blob_sha(file_bytes(repository, path)) if (repository / path).exists() else None


def target_for(source: str) -> str:
    source = safe_path(source)
    if source.startswith("ko/") and source.endswith(".html"):
        return source[3:]
    if source.startswith("data/") and source.endswith(".ko.json"):
        return source[:-8] + ".en.json"
    path = PurePosixPath(source[3:] if source.startswith("ko/") else source)
    if path.suffix.lower() not in ASSET_EXTENSIONS:
        raise ContentError(f"Unsupported translation source: {source}")
    name = path.name
    # Match the same deterministic rule used by the remote publication guard.
    markers = list(re.finditer(r"(?<![^._-])(KOR|ko)(?=[._-]|$)", name))
    if len(markers) > 1:
        raise ContentError(f"Ambiguous language markers in asset: {source}")
    if markers:
        marker = markers[0]
        name = name[:marker.start()] + ("ENG" if marker.group() == "KOR" else "en") + name[marker.end():]
    else:
        name = path.stem + ".en" + path.suffix
    target = str(path.with_name(name))
    if target == source:
        raise ContentError(f"Asset target must not replace its source: {source}")
    return safe_path(target)


class References(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls: set[str] = set()
        self.lang = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "html":
            self.lang = attributes.get("lang")
        for name in ("href", "src", "poster"):
            value = attributes.get(name)
            if value:
                self.urls.add(value)
        if attributes.get("srcset"):
            for candidate in attributes["srcset"].split(","):
                if candidate.strip():
                    self.urls.add(candidate.strip().split()[0])


def references(content: bytes) -> References:
    parsed = References()
    try:
        parsed.feed(content.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ContentError(f"Invalid HTML: {exc}") from exc
    return parsed


def local_reference(source: str, url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme and parts.scheme not in {"http", "https"}:
        return None
    if parts.netloc and parts.hostname not in SITE_HOSTS:
        return None
    decoded = unquote(parts.path)
    if not decoded:
        return None
    if decoded.startswith("/"):
        return safe_path(decoded[1:])
    # Navigation may use ../, but asset discovery must never escape the repo.
    stack = list(PurePosixPath(source).parent.parts)
    for part in decoded.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if not stack:
                raise ContentError(f"Asset URL escapes repository: {url}")
            stack.pop()
        else:
            stack.append(part)
    return safe_path("/".join(stack))


def public_external_pdf(url: str) -> bool:
    """Only declared public HTTP(S) PDF URLs, with no credential-bearing URL."""
    try:
        if any(character.isspace() or ord(character) < 32 or ord(character) == 127 or character == "\\" for character in url):
            return False
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme not in {"http", "https"} or not host or parts.username or parts.password or parts.port is not None:
            return False
        if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z][a-z0-9-]*", host):
            return False
        if host in SITE_HOSTS or host.split(".")[-1] in {"localhost", "local", "internal", "invalid", "test", "example"}:
            return False
        return PurePosixPath(unquote(parts.path)).suffix.lower() == ".pdf"
    except ValueError:
        return False


def external_targets(source: str, urls: list[str]) -> list[str]:
    if not source.startswith("ko/") or not source.endswith(".html"):
        if urls:
            raise ContentError("Only a Korean HTML page can own external PDF translations.")
        return []
    prefix = source[3:-5]
    return [safe_path(f"pdfs/translated/{prefix}/document-{index}.en.pdf") for index in range(1, len(urls) + 1)]


def normalize_observations(value: Any, urls: set[str], saved: dict[str, Any]) -> dict[str, str | None]:
    if value is None:
        return {url: saved.get(url) for url in sorted(urls)}
    if not isinstance(value, dict) or not {"schema_version", "observations"} <= set(value) or set(value) - {"schema_version", "observations", "errors"}:
        raise ContentError("Invalid external PDF observations fields.")
    if value["schema_version"] != "1.0" or not isinstance(value["observations"], dict) or not isinstance(value.get("errors", {}), dict):
        raise ContentError("Invalid external PDF observations schema.")
    if (set(value["observations"]) | set(value.get("errors", {}))) - urls:
        raise ContentError("External observations include a PDF URL not declared by Korean HTML.")
    if set(value["observations"]) & set(value.get("errors", {})):
        raise ContentError("An external PDF cannot be both observed and failed.")
    for url, observed in value["observations"].items():
        require_hash(observed, "external PDF bytes")
    if any(not isinstance(error, str) for error in value.get("errors", {}).values()):
        raise ContentError("External PDF errors must be strings.")
    return {url: value["observations"].get(url) for url in sorted(urls)}


def discover(repository: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    records: dict[str, dict[str, Any]] = {}
    external: list[dict[str, Any]] = []
    sources = sorted(path.relative_to(repository).as_posix() for path in (repository / "ko").rglob("*.html"))
    sources = [path for path in sources if not GENERATED_NEWS.fullmatch(path) and path != "ko/crypto-news-detail.html"]
    sources += sorted(path.relative_to(repository).as_posix() for path in (repository / "data").rglob("*.ko.json") if path.relative_to(repository).as_posix() != "data/crypto-news.ko.json")
    for source in sources:
        content = file_bytes(repository, source)
        kind = "html" if source.endswith(".html") else "json"
        own_sha = blob_sha(content)
        dependencies = []
        if kind == "json":
            read_json(repository / source)
        else:
            for url in sorted(references(content).urls):
                extension = PurePosixPath(unquote(urlsplit(url).path)).suffix.lower()
                if extension not in ASSET_EXTENSIONS:
                    continue
                local = local_reference(source, url)
                if local is None:
                    external.append({"source_path": source, "url": url,
                                     "kind": "pdf" if extension == ".pdf" else "image",
                                     "status": "requires_external_verification"})
                    continue
                asset_sha = optional_sha(repository, local)
                asset_kind = "pdf" if extension == ".pdf" else "image"
                dependencies.append({"path": local, "sha": asset_sha, "kind": asset_kind})
                if local not in records:
                    records[local] = {"kind": asset_kind, "source_path": local, "source_sha": asset_sha,
                                      "source_hash": digest({"path": local, "sha": asset_sha}),
                                      "target_path": target_for(local), "dependencies": [], "referenced_by": [], "external_sources": []}
                records[local]["referenced_by"].append(source)
        dependencies = sorted({item["path"]: item for item in dependencies}.values(), key=lambda item: item["path"])
        records[source] = {"kind": kind, "source_path": source, "source_sha": own_sha,
                           "source_hash": digest({"path": source, "sha": own_sha, "dependencies": dependencies}),
                           "target_path": target_for(source), "dependencies": dependencies, "referenced_by": [],
                           "external_sources": sorted({item["url"] for item in external if item["source_path"] == source and public_external_pdf(item["url"])})}
    targets = {}
    for source, record in records.items():
        record["output_paths"] = [record["target_path"], *external_targets(source, record["external_sources"])]
        for target in record["output_paths"]:
            if target in records or target.casefold() in targets:
                raise ContentError(f"Ambiguous or source-overwriting English target: {target}")
            targets[target.casefold()] = source
        record["referenced_by"] = sorted(set(record["referenced_by"]))
    return dict(sorted(records.items())), external


def empty_state() -> dict[str, Any]:
    return {"schema_version": "1.0", "baseline_ref": None, "external_dependencies": {}, "items": {}}


def validate_state(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "baseline_ref", "external_dependencies", "items"}:
        raise ContentError("Invalid content translation state fields.")
    if raw["schema_version"] != "1.0" or not isinstance(raw["items"], dict):
        raise ContentError("Invalid content translation state schema.")
    if raw["baseline_ref"] is not None:
        require_hash(raw["baseline_ref"], "baseline commit", sha1=True)
    if not isinstance(raw["external_dependencies"], dict):
        raise ContentError("Invalid state external dependencies.")
    for url, observed in raw["external_dependencies"].items():
        if not isinstance(url, str) or not public_external_pdf(url):
            raise ContentError("State contains an unsafe external PDF URL.")
        if observed is not None:
            require_hash(observed, "state external PDF bytes")
    for path, record in raw["items"].items():
        safe_path(path)
        if not isinstance(record, dict) or set(record) != RECORD_FIELDS:
            raise ContentError(f"Invalid state record fields: {path}")
        if record["kind"] not in {"html", "json", "pdf", "image"}:
            raise ContentError(f"Invalid state source kind: {path}")
        expected_kind = ("html" if path.startswith("ko/") and path.endswith(".html") else
                         "json" if path.startswith("data/") and path.endswith(".ko.json") else
                         "pdf" if PurePosixPath(path).suffix.lower() == ".pdf" else
                         "image" if PurePosixPath(path).suffix.lower() in IMAGE_EXTENSIONS else None)
        if expected_kind != record["kind"]:
            raise ContentError(f"State source kind disagrees with its path: {path}")
        require_hash(record["source_sha"], "source Git blob", sha1=True)
        require_hash(record["source_hash"], "source snapshot")
        if record["review_status"] not in {"baseline_preserved", "reviewed"}:
            raise ContentError(f"Invalid review status: {path}")
        disposition = record["asset_disposition"]
        if disposition not in {"not_applicable", "translated", "reused"}:
            raise ContentError(f"Invalid asset disposition: {path}")
        if disposition == "reused" and record["kind"] != "image":
            raise ContentError("Only nonlinguistic images may be recorded as reused.")
        if (record["kind"] in {"html", "json"}) != (disposition == "not_applicable"):
            raise ContentError(f"Invalid asset disposition for source kind: {path}")
        if not isinstance(record["outputs"], list):
            raise ContentError("State outputs must be an array.")
        urls = record["external_sources"]
        if not isinstance(urls, list) or not all(isinstance(url, str) and public_external_pdf(url) for url in urls) or urls != sorted(set(urls)):
            raise ContentError("Invalid state external PDF source list.")
        extra_outputs = external_targets(path, urls)
        expected = [] if disposition == "reused" else [target_for(path)]
        if record["review_status"] == "reviewed":
            expected.extend(extra_outputs)
        output_paths = []
        for output in record["outputs"]:
            if not isinstance(output, dict) or set(output) != {"path", "sha"}:
                raise ContentError("Invalid state output fields.")
            output_paths.append(safe_path(output["path"]))
            require_hash(output["sha"], "output Git blob", sha1=True)
        if output_paths != expected:
            raise ContentError(f"State outputs are not the exact English counterpart: {path}")
        if record["review_status"] == "reviewed":
            require_time(record["reviewed_at"])
        elif record["reviewed_at"] is not None:
            raise ContentError("A baseline-preserved pair is not a completed semantic review.")
    return raw


def require_time(value: Any) -> str:
    if not isinstance(value, str):
        raise ContentError("Reviewed time must be an explicit ISO timestamp.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ContentError("Invalid reviewed time.") from exc
    if parsed.tzinfo is None:
        raise ContentError("Reviewed time must include a time zone.")
    return value


def status(repository: Path, external_observations: Any = None) -> dict[str, Any]:
    repository = repository.resolve()
    records, external = discover(repository)
    state_file = repository / STATE_PATH
    if state_file.is_symlink() or state_file.parent.is_symlink():
        raise ContentError("Translation state cannot use a symlink.")
    raw_state = read_json(state_file) if state_file.exists() else None
    state = validate_state(raw_state) if raw_state is not None else empty_state()
    external_urls = {url for item in records.values() for url in item["external_sources"]}
    observed = normalize_observations(external_observations, external_urls, state["external_dependencies"])
    for item in records.values():
        item["blocked_external_references"] = [reference for reference in external if reference["source_path"] == item["source_path"] and reference["kind"] == "pdf" and not public_external_pdf(reference["url"])]
        if item["external_sources"]:
            item["external_dependencies"] = {url: observed[url] for url in item["external_sources"]}
            item["source_hash"] = digest({"path": item["source_path"], "sha": item["source_sha"],
                                          "dependencies": item["dependencies"],
                                          "external_dependencies": item["external_dependencies"]})
    pending, scope_pairs, english = [], [], {}
    baseline_count = reviewed_count = 0
    for source, item in records.items():
        target = item["target_path"]
        actual_target = optional_sha(repository, target)
        for output in item["output_paths"]:
            english[output] = optional_sha(repository, output)
        saved = state["items"].get(source)
        paths = [target]
        reasons = []
        if item["source_sha"] is None:
            reasons.append("missing_source_asset")
        if external_observations is not None and any(observed[url] is None for url in item["external_sources"]):
            reasons.append("external_source_unavailable")
        if saved is None:
            reasons.append("missing_state")
            if actual_target is None and item["kind"] != "image":
                reasons.append("missing_english")
        else:
            if saved["source_hash"] != item["source_hash"] or saved["source_sha"] != item["source_sha"]:
                reasons.append("source_changed")
            if saved["asset_disposition"] == "reused":
                paths = []
            elif any(optional_sha(repository, output["path"]) is None for output in saved["outputs"]):
                reasons.append("missing_english")
            elif any(output["sha"] != optional_sha(repository, output["path"]) for output in saved["outputs"]):
                reasons.append("output_changed")
            if saved["review_status"] == "baseline_preserved":
                baseline_count += 1
            else:
                reviewed_count += 1
        # Changed/reused images may be newly translated, so publication scope
        # always retains the deterministic target even when no output is needed.
        pair = {"source_path": source, "source_sha": item["source_sha"], "output_paths": item["output_paths"]}
        if item["source_sha"] is not None:
            scope_pairs.append(pair)
        if reasons:
            pending.append({**item, "reason": reasons[0], "reasons": reasons,
                            "existing_english_sha": actual_target,
                            "external_references": [reference for reference in external if reference["source_path"] == source]})
    source_snapshot = digest(records)
    orphaned = sorted(set(state["items"]) - set(records))
    return {"schema_version": "1.0", "snapshot_hash": source_snapshot, "source_snapshot_hash": source_snapshot,
            "english_snapshot_hash": digest(english), "state_snapshot_hash": digest(raw_state),
            "pending_count": len(pending), "needs_work": bool(pending), "pending": pending,
            "scope_pairs": scope_pairs, "sources": list(records.values()), "external_references": external,
            "external_dependencies": observed,
            "orphaned_state_sources": orphaned, "baseline_preserved_count": baseline_count,
            "reviewed_count": reviewed_count,
            "coverage_note": "Git-published HTML, language JSON and linked local PDF/image assets only; external media/audio/video are not translated here."}


def atomic_state(repository: Path, value: Any) -> None:
    validate_state(value)
    target = repository / STATE_PATH
    if target.is_symlink() or target.parent.is_symlink():
        raise ContentError("Translation state cannot use a symlink.")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".content-translation-", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def bootstrap(repository: Path, baseline_ref: str, external_observations: Any = None) -> dict[str, Any]:
    repository = repository.resolve()
    require_hash(baseline_ref, "installation baseline commit", sha1=True)
    if (repository / STATE_PATH).exists():
        raise ContentError("Bootstrap is installation-only; existing state must not be overwritten or reseeded.")
    report = status(repository, external_observations)
    state = empty_state()
    state["baseline_ref"] = baseline_ref
    state["external_dependencies"] = report["external_dependencies"]
    preserved, skipped = [], []
    for item in report["sources"]:
        source, target = item["source_path"], item["target_path"]
        target_sha = optional_sha(repository, target)
        reuse = item["kind"] == "image" and target_sha is None
        if item["source_sha"] is None or (target_sha is None and not reuse):
            skipped.append(source)
            continue
        state["items"][source] = {
            "kind": item["kind"], "source_sha": item["source_sha"], "source_hash": item["source_hash"],
            "outputs": [] if reuse else [{"path": target, "sha": target_sha}],
            "review_status": "baseline_preserved",
            "asset_disposition": "reused" if reuse else ("translated" if item["kind"] in {"pdf", "image"} else "not_applicable"),
            "reviewed_at": None, "external_sources": item["external_sources"]}
        preserved.append(source)
    latest = status(repository, external_observations)
    if latest["source_snapshot_hash"] != report["source_snapshot_hash"]:
        raise ContentError("Sources changed during installation baseline capture.")
    if latest["english_snapshot_hash"] != report["english_snapshot_hash"]:
        raise ContentError("English outputs changed during installation baseline capture.")
    if latest["state_snapshot_hash"] != report["state_snapshot_hash"] or (repository / STATE_PATH).exists():
        raise ContentError("State changed during installation baseline capture.")
    atomic_state(repository, state)
    return {"baseline_ref": baseline_ref, "preserved_count": len(preserved), "preserved": preserved,
            "skipped": skipped, "semantic_review_claimed": False}


def record_reviewed(repository: Path, bundle: Any, external_observations: Any = None) -> dict[str, Any]:
    repository = repository.resolve()
    required = {"schema_version", "source_snapshot_hash", "state_snapshot_hash", "records"}
    if not isinstance(bundle, dict) or not required <= set(bundle) or set(bundle) - required - {"english_snapshot_hash"}:
        raise ContentError("Invalid reviewed bundle fields.")
    if bundle["schema_version"] != "1.0" or not isinstance(bundle["records"], list):
        raise ContentError("Invalid reviewed bundle schema.")
    report = status(repository, external_observations)
    for field in ("source_snapshot_hash", "state_snapshot_hash"):
        require_hash(bundle[field], field)
        if bundle[field] != report[field]:
            raise ContentError(f"Stale {field}; review the current snapshot.")
    if "english_snapshot_hash" in bundle:
        # English is already authored here. This before-authoring digest must
        # be bound by the caller's complete publication baseline, not compared
        # with the newly authored bytes and falsely rejected as stale.
        require_hash(bundle["english_snapshot_hash"], "before-authoring English snapshot")
    state_path = repository / STATE_PATH
    state = validate_state(read_json(state_path)) if state_path.exists() else empty_state()
    state["external_dependencies"] = report["external_dependencies"]
    pending = {item["source_path"]: item for item in report["pending"]}
    seen = set()
    for record in bundle["records"]:
        fields = {"source_path", "source_hash", "decision", "outputs", "reviewed_at"}
        if not isinstance(record, dict) or set(record) != fields:
            raise ContentError("Invalid reviewed record fields.")
        source = safe_path(record["source_path"])
        if source in seen or source not in pending:
            raise ContentError(f"Duplicate or non-pending reviewed source: {source}")
        seen.add(source)
        item = pending[source]
        if item["source_sha"] is None or record["source_hash"] != item["source_hash"]:
            raise ContentError(f"Reviewed source hash mismatch: {source}")
        if any(report["external_dependencies"][url] is None for url in item["external_sources"]):
            raise ContentError("External source PDF bytes must be observed before recording its English translation.")
        if item["blocked_external_references"]:
            raise ContentError("A declared external PDF URL is unsupported; automatic complete translation must be held for review.")
        require_time(record["reviewed_at"])
        decision = record["decision"]
        if decision not in {"translated", "reused"} or (decision == "reused" and item["kind"] != "image"):
            raise ContentError("Only an explicitly reviewed nonlinguistic image can be reused.")
        outputs = record["outputs"]
        expected_paths = [] if decision == "reused" else item["output_paths"]
        if not isinstance(outputs, list) or not all(isinstance(output, dict) for output in outputs) or [output.get("path") for output in outputs] != expected_paths:
            raise ContentError(f"Wrong English output paths: {source}")
        for output in outputs:
            if set(output) != {"path", "sha"}:
                raise ContentError("Invalid reviewed output fields.")
            require_hash(output["sha"], "reviewed output Git blob", sha1=True)
            content = file_bytes(repository, output["path"])
            if blob_sha(content) != output["sha"]:
                raise ContentError(f"Reviewed output bytes changed: {output['path']}")
            is_html = output["path"] == item["target_path"] and item["kind"] == "html"
            if is_html and references(content).lang not in {"en", "en-US", "en-GB"}:
                raise ContentError("English HTML must declare an English document language.")
            if is_html and item["external_sources"]:
                linked = {local_reference(output["path"], url) for url in references(content).urls}
                if not set(external_targets(source, item["external_sources"])) <= linked:
                    raise ContentError("English HTML must link each translated external PDF output.")
            if item["kind"] == "json":
                read_json(repository / output["path"])
            if output["path"].lower().endswith(".pdf") and not content.startswith(b"%PDF-"):
                raise ContentError("Translated PDF output is not a PDF file.")
        state["items"][source] = {"kind": item["kind"], "source_sha": item["source_sha"],
                                  "source_hash": item["source_hash"], "outputs": outputs,
                                  "review_status": "reviewed", "reviewed_at": record["reviewed_at"], "external_sources": item["external_sources"],
                                  "asset_disposition": decision if item["kind"] in {"pdf", "image"} else "not_applicable"}
    latest = status(repository, external_observations)
    for field in ("source_snapshot_hash", "english_snapshot_hash", "state_snapshot_hash"):
        if latest[field] != report[field]:
            raise ContentError("Source, English output, or state changed during review recording.")
    if seen:
        atomic_state(repository, state)
    return {"recorded_count": len(seen), "recorded": sorted(seen), "pending_count": status(repository, external_observations)["pending_count"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    commands = parser.add_subparsers(dest="command", required=True)
    query = commands.add_parser("status")
    query.add_argument("--output", type=Path)
    install = commands.add_parser("bootstrap")
    install.add_argument("--baseline-ref", required=True)
    reviewed = commands.add_parser("record-reviewed")
    reviewed.add_argument("--bundle", type=Path, required=True)
    for command in (query, install, reviewed):
        command.add_argument("--repository", type=Path, default=argparse.SUPPRESS)
        command.add_argument("--external-observations", type=Path)
    args = parser.parse_args(argv)
    try:
        repository = args.repository.resolve()
        observations = None
        if args.external_observations:
            observation_path = args.external_observations.resolve()
            if observation_path == repository or repository in observation_path.parents or args.external_observations.is_symlink():
                raise ContentError("External observations must be an outside-repository JSON file.")
            observations = read_json(observation_path)
        if args.command == "status":
            result = status(repository, observations)
            if args.output:
                destination = args.output.resolve()
                if destination == repository or repository in destination.parents or args.output.is_symlink():
                    raise ContentError("Status output must be outside the repository.")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        elif args.command == "bootstrap":
            result = bootstrap(repository, args.baseline_ref, observations)
        else:
            result = record_reviewed(repository, read_json(args.bundle), observations)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (ContentError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Content translation blocked: {exc}", file=__import__('sys').stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
