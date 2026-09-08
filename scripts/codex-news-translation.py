#!/usr/bin/env python3
"""Validate Codex-authored translations without a model or external API.

Workflow: status --output TEMP, agent translation/review, apply --bundle TEMP,
then build pages, audit the site, and verify. Use an isolated checkout.

Bundle contract (exact fields):
{"schema_version":"1.0", "source_snapshot_hash":"<from status>",
 "english_snapshot_hash":"<from status>", "state_snapshot_hash":"<from status>",
 "translations":[{"slug":"...", "source_hash":"<from pending item>",
 "title":"...", "content":"...", "metanomia_thought":"..."}]}

Include every pending slug exactly once. translations:[] synchronizes only
metadata when no article needs review. All validation precedes output writes.
Hashes prove which files were reviewed, not semantic translation accuracy.

bootstrap --baseline-ref COMMIT explicitly trusts translations at that historical
commit and seeds only pairs still identical to it, never all current Korean text.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "codex_translation_publisher", Path(__file__).with_name("publish_crypto_news.py")
)
assert SPEC and SPEC.loader
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)
ValidationError = publisher.PublishValidationError
KO_RELATIVE = Path("data/crypto-news.json")
EN_RELATIVE = Path("data/crypto-news.en.json")
STATE_RELATIVE = Path(".newsroom/translation-state.json")
CONTENT_FIELDS = ("title", "content", "metanomia_thought")
SOURCE_FIELDS = (*CONTENT_FIELDS, "date_kst", "sources")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
SNAPSHOT_FIELDS = ("source_snapshot_hash", "english_snapshot_hash", "state_snapshot_hash")
BUNDLE_FIELDS = {"schema_version", *SNAPSHOT_FIELDS, "translations"}
TRANSLATION_FIELDS = {"slug", "source_hash", *CONTENT_FIELDS}


def digest(value: Any) -> str:
    return hashlib.sha256(publisher.canonical_json(value).encode("utf-8")).hexdigest()


def source_hash(item: dict[str, Any]) -> str:
    return digest({field: item[field] for field in SOURCE_FIELDS})


def english_hash(item: dict[str, Any]) -> str:
    return digest(item)


def require_hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HASH_RE.fullmatch(value):
        raise ValidationError(f"{label} must be a lowercase SHA-256 hash.")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"JSON contains a duplicate object key: {key}.")
        result[key] = value
    return result


def parse_json(text: str, label: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValidationError(f"Could not parse {label}: {exc}") from exc


def read_json(path: Path) -> Any:
    try:
        return parse_json(path.read_text(encoding="utf-8"), str(path))
    except (OSError, UnicodeError) as exc:
        raise ValidationError(f"Could not read {path}: {exc}") from exc


def validate_state(raw: Any) -> dict[str, Any]:
    state = publisher.require_exact_fields(raw, {"schema_version", "items"}, "state")
    if state["schema_version"] != "1.0" or not isinstance(state["items"], dict):
        raise ValidationError("State must use schema_version 1.0 and an items object.")
    for slug, entry in state["items"].items():
        if not publisher.PUBLIC_SLUG_RE.fullmatch(slug):
            raise ValidationError(f"Invalid state slug: {slug}.")
        publisher.require_exact_fields(entry, {"source_hash", "english_hash"}, f"state {slug}")
        for field in ("source_hash", "english_hash"):
            require_hash(entry[field], f"state {slug}.{field}")
    return state


def assert_no_english_only(korean: dict[str, Any], english: dict[str, Any]) -> None:
    known = {item["slug"] for item in korean["items"]}
    extra = sorted({item["slug"] for item in english["items"]} - known)
    if extra:
        raise ValidationError(
            "English-only slug(s); automatic deletion is forbidden: " + ", ".join(extra)
        )


def load_snapshot(repository: Path) -> dict[str, Any]:
    korean = publisher.validate_manifest(read_json(repository / KO_RELATIVE))
    english_exists = (repository / EN_RELATIVE).exists()
    raw_english = read_json(repository / EN_RELATIVE) if english_exists else None
    english = publisher.validate_english_manifest(raw_english) if english_exists else {
        "schema_version": "1.0", "generated_at_kst": korean["generated_at_kst"], "items": []
    }
    assert_no_english_only(korean, english)
    state_exists = (repository / STATE_RELATIVE).exists()
    raw_state = read_json(repository / STATE_RELATIVE) if state_exists else None
    state = validate_state(raw_state) if state_exists else {"schema_version": "1.0", "items": {}}
    return {
        "korean": korean, "english": english, "state": state,
        "raw_english": raw_english, "raw_state": raw_state,
        "source_snapshot_hash": digest(korean),
        "english_snapshot_hash": digest(raw_english),
        "state_snapshot_hash": digest(raw_state),
    }


def status_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    korean, english, state = (snapshot[key] for key in ("korean", "english", "state"))
    by_slug = {item["slug"]: item for item in english["items"]}
    pending = []
    for item in korean["items"]:
        slug = item["slug"]
        translated = by_slug.get(slug)
        record = state["items"].get(slug)
        item_hash = source_hash(item)
        reasons = []
        if translated is None:
            reasons.append("missing_english")
        if record is None:
            reasons.append("missing_state")
        else:
            if record["source_hash"] != item_hash:
                reasons.append("source_changed")
            if translated is not None and record["english_hash"] != english_hash(translated):
                reasons.append("english_changed")
        if translated is not None and any(
            translated[field] != item[field] for field in ("date_kst", "sources")
        ):
            reasons.append("source_metadata_mismatch")
        if reasons:
            pending.append({
                "slug": slug, "source_hash": item_hash, "reasons": reasons,
                "source": {field: copy.deepcopy(item[field]) for field in SOURCE_FIELDS},
                "existing_english": copy.deepcopy(translated),
            })
    sync_reasons = []
    if snapshot["raw_english"] is None:
        sync_reasons.append("missing_english_manifest")
    if korean["generated_at_kst"] != english["generated_at_kst"]:
        sync_reasons.append("generated_at_kst")
    if [item["slug"] for item in korean["items"]] != list(by_slug):
        sync_reasons.append("slug_order_or_coverage")
    return {
        "schema_version": "1.0",
        **{field: snapshot[field] for field in SNAPSHOT_FIELDS},
        "pending_count": len(pending), "pending": pending,
        "needs_sync": bool(sync_reasons), "sync_reasons": sync_reasons,
        "needs_work": bool(pending or sync_reasons),
    }


def status(repository: Path) -> dict[str, Any]:
    return status_from_snapshot(load_snapshot(repository))


def _assert_unchanged(repository: Path, original: dict[str, Any]) -> None:
    current = load_snapshot(repository)
    for field in SNAPSHOT_FIELDS:
        if current[field] != original[field]:
            raise ValidationError(f"{field} changed during validation; run status and review again.")


def _write_outputs(changes: list[tuple[Path, Any]]) -> list[str]:
    """Stage every output before replacement; restore on ordinary I/O failure.

    English is replaced before state. An interrupted process therefore cannot
    mark old English as reviewed: its hash will remain pending. Isolated
    checkouts are required because two files are not one atomic transaction.
    """
    staged: list[tuple[Path, Path, bytes | None]] = []
    replaced: list[tuple[Path, bytes | None]] = []
    try:
        for path, value in changes:
            original = path.read_bytes() if path.exists() else None
            path.parent.mkdir(parents=True, exist_ok=True)
            handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            temp_path = Path(temp_name)
            staged.append((path, temp_path, original))
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        for path, temp_path, original in staged:
            os.replace(temp_path, path)
            replaced.append((path, original))
    except OSError:
        for path, original in reversed(replaced):
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(original)
        raise
    finally:
        for _path, temp_path, _original in staged:
            temp_path.unlink(missing_ok=True)
    return [str(path) for path, _value in changes]


def apply_bundle(repository: Path, bundle: Any) -> dict[str, Any]:
    snapshot = load_snapshot(repository)
    report = status_from_snapshot(snapshot)
    data = publisher.require_exact_fields(bundle, BUNDLE_FIELDS, "translation bundle")
    if data["schema_version"] != "1.0":
        raise ValidationError("Translation bundle schema_version must be 1.0.")
    for field in SNAPSHOT_FIELDS:
        require_hash(data[field], f"bundle.{field}")
        if data[field] != snapshot[field]:
            raise ValidationError(f"Bundle {field} is stale; run status and review again.")
    if not isinstance(data["translations"], list):
        raise ValidationError("Bundle translations must be an array.")
    pending = {item["slug"]: item for item in report["pending"]}
    translations = {}
    for index, raw in enumerate(data["translations"], start=1):
        item = publisher.require_exact_fields(raw, TRANSLATION_FIELDS, f"translation {index}")
        slug = publisher.require_nonempty_string(item["slug"], f"translation {index}.slug")
        if slug != item["slug"] or not publisher.PUBLIC_SLUG_RE.fullmatch(slug):
            raise ValidationError(f"Invalid translation slug: {item['slug']}.")
        if slug in translations:
            raise ValidationError(f"Duplicate translation slug: {slug}.")
        if slug not in pending:
            raise ValidationError(f"Unexpected translation slug (not pending): {slug}.")
        require_hash(item["source_hash"], f"translation {slug}.source_hash")
        if item["source_hash"] != pending[slug]["source_hash"]:
            raise ValidationError(f"Wrong source_hash for {slug}; review the current Korean article.")
        for field in CONTENT_FIELDS:
            publisher.require_nonempty_string(item[field], f"translation {slug}.{field}")
        translations[slug] = item
    missing = sorted(set(pending) - set(translations))
    if missing:
        raise ValidationError("Bundle is missing pending slug(s): " + ", ".join(missing))

    korean = snapshot["korean"]
    done = {item["slug"]: copy.deepcopy(item) for item in snapshot["english"]["items"]}
    next_state = copy.deepcopy(snapshot["state"])
    for original in korean["items"]:
        slug = original["slug"]
        if slug in translations:
            item = translations[slug]
            done[slug] = {
                "slug": slug, "date_kst": original["date_kst"],
                **{field: item[field] for field in CONTENT_FIELDS},
                "sources": copy.deepcopy(original["sources"]),
            }
            next_state["items"][slug] = {
                "source_hash": source_hash(original), "english_hash": english_hash(done[slug])
            }
    next_english = {
        "schema_version": korean["schema_version"],
        "generated_at_kst": korean["generated_at_kst"],
        "items": [done[item["slug"]] for item in korean["items"]],
    }
    publisher.validate_english_manifest(next_english)
    validate_state(next_state)
    candidate = {**snapshot, "english": next_english, "state": next_state,
                 "raw_english": next_english, "raw_state": next_state}
    if status_from_snapshot(candidate)["needs_work"]:
        raise ValidationError("Candidate English manifest is not fully synchronized and reviewed.")
    _assert_unchanged(repository, snapshot)
    changes = []
    if next_english != snapshot["raw_english"]:
        changes.append((repository / EN_RELATIVE, next_english))
    if next_state != snapshot["raw_state"]:
        changes.append((repository / STATE_RELATIVE, next_state))
    written = _write_outputs(changes)
    return {"translated_count": len(translations), "written": written, "needs_work": False}


def bootstrap(repository: Path, baseline_ref: str) -> dict[str, Any]:
    snapshot = load_snapshot(repository)
    publisher.require_nonempty_string(baseline_ref, "baseline ref", max_length=250)
    commit = publisher.run_git(repository, [
        "rev-parse", "--verify", "--end-of-options", f"{baseline_ref}^{{commit}}"
    ])
    baseline_ko = publisher.validate_manifest(parse_json(publisher.run_git(
        repository, ["show", f"{commit}:{KO_RELATIVE.as_posix()}"]
    ), "baseline Korean manifest"))
    baseline_en = publisher.validate_english_manifest(parse_json(publisher.run_git(
        repository, ["show", f"{commit}:{EN_RELATIVE.as_posix()}"]
    ), "baseline English manifest"))
    assert_no_english_only(baseline_ko, baseline_en)
    ko_by_slug = {item["slug"]: item for item in baseline_ko["items"]}
    en_by_slug = {item["slug"]: item for item in baseline_en["items"]}
    current_en = {item["slug"]: item for item in snapshot["english"]["items"]}
    state = copy.deepcopy(snapshot["state"])
    seeded = []
    skipped = []
    for original in snapshot["korean"]["items"]:
        slug = original["slug"]
        if slug in state["items"]:
            continue  # Never overwrite a review record, including a stale one.
        previous_ko, previous_en = ko_by_slug.get(slug), en_by_slug.get(slug)
        translated = current_en.get(slug)
        if previous_ko is None or previous_en is None or translated is None:
            skipped.append({"slug": slug, "reason": "missing_baseline_or_current_pair"})
        elif source_hash(original) != source_hash(previous_ko):
            skipped.append({"slug": slug, "reason": "source_changed_since_baseline"})
        elif english_hash(translated) != english_hash(previous_en):
            skipped.append({"slug": slug, "reason": "english_changed_since_baseline"})
        elif any(previous_en[field] != previous_ko[field] for field in ("date_kst", "sources")):
            skipped.append({"slug": slug, "reason": "baseline_source_metadata_mismatch"})
        else:
            state["items"][slug] = {
                "source_hash": source_hash(original), "english_hash": english_hash(translated)
            }
            seeded.append(slug)
    validate_state(state)
    _assert_unchanged(repository, snapshot)
    written = _write_outputs([(repository / STATE_RELATIVE, state)]) if seeded else []
    return {"baseline_commit": commit, "seeded_count": len(seeded), "seeded": seeded,
            "skipped": skipped, "written": written, "pending_count": status(repository)["pending_count"]}


def verify(repository: Path) -> dict[str, Any]:
    report = status(repository)
    if report["needs_work"]:
        raise ValidationError(
            f"English translation is not ready: {report['pending_count']} pending article(s), "
            f"sync reasons={report['sync_reasons']}."
        )
    publisher.verify_static_pages(repository)
    return {"verified": True, "pending_count": 0, "needs_sync": False}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repository", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    status_parser = commands.add_parser("status", help="report articles requiring translation or review")
    status_parser.add_argument("--output", type=Path, help="also save status to a temporary JSON file")
    apply_parser = commands.add_parser("apply", help="validate and apply a complete reviewed bundle")
    apply_parser.add_argument("--bundle", type=Path, required=True)
    commands.add_parser("verify", help="verify translation state and bilingual pages after build/audit")
    baseline_parser = commands.add_parser("bootstrap", help="seed unchanged historical translations")
    baseline_parser.add_argument("--baseline-ref", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    repository = args.repository.resolve()
    try:
        if args.command == "status":
            result = status(repository)
            if args.output:
                destination = args.output.resolve()
                if destination in {(repository / path).resolve() for path in (
                    KO_RELATIVE, EN_RELATIVE, STATE_RELATIVE
                )}:
                    raise ValidationError("Status output must not overwrite a manifest or translation state.")
                publisher.atomic_write_json(destination, result)
        elif args.command == "apply":
            result = apply_bundle(repository, read_json(args.bundle))
        elif args.command == "bootstrap":
            result = bootstrap(repository, args.baseline_ref)
        else:
            result = verify(repository)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValidationError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
