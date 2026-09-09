#!/usr/bin/env python3
"""Verify an extracted fixed-commit repository and prepare a GitHub Git-data plan.

This program never contacts GitHub or publishes. The caller must obtain base_sha
and its tree from the same authenticated commit response. A complete recursive
tree is required; its object ID is independently rebuilt from every file.
Baseline and plan JSON must live outside the extracted repository. A plan is
valid only for its one base commit and must be uploaded using a single-parent
commit and a non-force ref update, followed by read-back verification.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any

REPOSITORY = "jun0211-0623/metanomia-site"
BRANCH = "main"
KO_PATH = "data/crypto-news.json"
FIXED_OUTPUTS = {"data/crypto-news.en.json", ".newsroom/translation-state.json", "sitemap.xml"}
BASE_KIND = "metanomia-cloud-news-baseline"
PLAN_KIND = "metanomia-cloud-news-publish-plan"
SHA1_RE = re.compile(r"[0-9a-f]{40}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
SLUG_RE = re.compile(r"20\d{2}-\d{2}-\d{2}-crypto-news-[0-9a-f]{10}\Z")
FILE_FIELDS = {"path", "mode", "type", "sha", "size", "sha256"}
BASE_FIELDS = {"schema_version", "kind", "repository", "branch", "base_sha", "base_tree_sha",
               "ko_blob_sha", "sitemap_outside_news_hash", "files", "baseline_hash"}


class PlanError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def checksum(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def object_sha(kind: str, data: bytes) -> str:
    return hashlib.sha1(f"{kind} {len(data)}\0".encode("ascii") + data).hexdigest()


def sitemap_outside_news_hash(content: bytes) -> str:
    start = b"<!-- GENERATED CRYPTO NEWS START -->"
    end = b"<!-- GENERATED CRYPTO NEWS END -->"
    if content.count(start) != content.count(end) or content.count(start) > 1:
        raise PlanError("Sitemap generated-news markers are malformed.")
    stripped = re.sub(re.escape(start) + rb"[\s\S]*?" + re.escape(end), b"", content)
    # The builder inserts surrounding whitespace; non-news XML remains fixed.
    stripped = re.sub(rb">\s+<", b"><", stripped).strip()
    return hashlib.sha256(stripped).hexdigest()


def require_sha(value: Any, name: str, *, sha256: bool = False) -> str:
    pattern = SHA256_RE if sha256 else SHA1_RE
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise PlanError(f"Invalid {name} hash.")
    return value


def safe_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise PlanError(f"Unsafe repository path: {value!r}")
    parts = value.split("/")
    if any(part in {"", ".", ".."} or part.casefold() == ".git" for part in parts):
        raise PlanError(f"Unsafe repository path: {value!r}")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise PlanError(f"Unsafe repository path: {value!r}")
    return value


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for name, value in pairs:
        if name in result:
            raise PlanError(f"Duplicate JSON key: {name}")
        result[name] = value
    return result


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except (OSError, UnicodeError, ValueError) as exc:
        raise PlanError(f"Cannot read JSON {path}: {exc}") from exc


def tree_hashes(files: list[dict[str, Any]]) -> dict[str, str]:
    """Rebuild Git trees, including Git's directory-aware byte ordering."""
    root: dict[str, Any] = {}
    seen = set()
    for item in files:
        path = safe_path(item["path"])
        if path.casefold() in seen:
            raise PlanError(f"Duplicate or case-colliding path: {path}")
        seen.add(path.casefold())
        if item.get("type") != "blob" or item.get("mode") not in {"100644", "100755"}:
            raise PlanError(f"Only regular Git blobs are supported: {path}")
        require_sha(item.get("sha"), f"blob {path}")
        parts = path.split("/")
        node = root
        for part in parts[:-1]:
            if any(name.casefold() == part.casefold() and name != part for name in node):
                raise PlanError(f"Case-colliding directory: {path}")
            existing = node.setdefault(part, {})
            if not isinstance(existing, dict):
                raise PlanError(f"File/directory collision: {path}")
            node = existing
        if any(name.casefold() == parts[-1].casefold() for name in node):
            raise PlanError(f"File/directory collision: {path}")
        node[parts[-1]] = (item["mode"], item["sha"])

    hashes = {}

    def visit(node: dict[str, Any], prefix: str) -> str:
        entries = []
        for name, value in node.items():
            encoded = name.encode("utf-8")
            if isinstance(value, dict):
                relative = prefix + name
                sha = visit(value, relative + "/")
                hashes[relative] = sha
                entries.append((encoded + b"/", b"40000 " + encoded + b"\0" + bytes.fromhex(sha)))
            else:
                mode, sha = value
                entries.append((encoded, mode.encode("ascii") + b" " + encoded + b"\0" + bytes.fromhex(sha)))
        data = b"".join(entry for _key, entry in sorted(entries))
        return object_sha("tree", data)

    hashes[""] = visit(root, "")
    return hashes


def parse_tree(raw: Any) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(raw, dict) or raw.get("truncated") is not False or not isinstance(raw.get("tree"), list):
        raise PlanError("A complete GitHub recursive tree with truncated=false is required.")
    root_sha = require_sha(raw.get("sha"), "base tree")
    files, directories, seen = [], {}, set()
    for item in raw["tree"]:
        if not isinstance(item, dict):
            raise PlanError("Invalid recursive tree entry.")
        path = safe_path(item.get("path"))
        if path.casefold() in seen:
            raise PlanError(f"Duplicate or case-colliding tree path: {path}")
        seen.add(path.casefold())
        sha = require_sha(item.get("sha"), f"tree entry {path}")
        if item.get("type") == "tree" and item.get("mode") == "040000":
            directories[path] = sha
        elif item.get("type") == "blob" and item.get("mode") in {"100644", "100755"}:
            size = item.get("size")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise PlanError(f"Invalid blob size: {path}")
            files.append({"path": path, "mode": item["mode"], "type": "blob", "sha": sha, "size": size})
        else:
            raise PlanError(f"Symlinks, gitlinks, and unsupported tree entries are forbidden: {path}")
    rebuilt = tree_hashes(files)
    if rebuilt != {"": root_sha, **directories}:
        raise PlanError("Recursive tree is incomplete or its object hashes do not match.")
    return root_sha, sorted(files, key=lambda item: item["path"])


def scan_files(repository: Path, expected_modes: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    result = {}
    for directory, directories, names in os.walk(repository, followlinks=False):
        base = Path(directory)
        if base == repository:
            directories[:] = [name for name in directories if name != ".git"]
            names = [name for name in names if name != ".git"]
        for name in directories:
            path = base / name
            safe_path(path.relative_to(repository).as_posix())
            if path.is_symlink():
                raise PlanError(f"Symlink directory is forbidden: {path}")
        for name in names:
            path = base / name
            relative = safe_path(path.relative_to(repository).as_posix())
            information = path.lstat()
            if not stat.S_ISREG(information.st_mode):
                raise PlanError(f"Only regular files are supported: {relative}")
            content = path.read_bytes()
            if os.name == "nt":
                # Windows does not preserve POSIX executable bits on extraction.
                mode = (expected_modes or {}).get(relative, "100644")
            else:
                mode = "100755" if information.st_mode & 0o111 else "100644"
            result[relative] = {"path": relative, "mode": mode, "type": "blob",
                                "sha": object_sha("blob", content), "size": len(content),
                                "sha256": hashlib.sha256(content).hexdigest()}
    tree_hashes(list(result.values()))  # Reject collisions before consuming the snapshot.
    return result


def outside_output(repository: Path, output: Path) -> Path:
    if output.is_symlink():
        raise PlanError("Output cannot be a symlink.")
    destination = output.resolve()
    if destination == repository or repository in destination.parents:
        raise PlanError("Baseline and plan output must be outside the repository.")
    return destination


def write_json(output: Path, value: Any) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".cloud-news-", dir=output.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def snapshot(repository: Path, base_sha: str, raw_tree: Any, output: Path) -> dict[str, Any]:
    repository = repository.resolve(strict=True)
    destination = outside_output(repository, output)
    require_sha(base_sha, "base commit")
    root_sha, tree_files = parse_tree(raw_tree)
    expected = {item["path"]: item for item in tree_files}
    actual = scan_files(repository, {path: item["mode"] for path, item in expected.items()})
    if set(actual) != set(expected):
        raise PlanError("Extracted file paths do not exactly match the complete base tree.")
    for path, item in expected.items():
        if any(actual[path][field] != item[field] for field in ("mode", "type", "sha", "size")):
            raise PlanError(f"Extracted file differs from its base Git blob: {path}")
    if KO_PATH not in actual:
        raise PlanError("The Korean manifest is missing from the base tree.")
    baseline = {"schema_version": "1.0", "kind": BASE_KIND, "repository": REPOSITORY,
                "branch": BRANCH, "base_sha": base_sha, "base_tree_sha": root_sha,
                "ko_blob_sha": actual[KO_PATH]["sha"],
                "sitemap_outside_news_hash": sitemap_outside_news_hash((repository / "sitemap.xml").read_bytes()),
                "files": [actual[path] for path in sorted(actual)]}
    baseline["baseline_hash"] = checksum(baseline)
    write_json(destination, baseline)
    return baseline


def validate_baseline(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != BASE_FIELDS:
        raise PlanError("Invalid baseline fields.")
    if (raw["schema_version"], raw["kind"], raw["repository"], raw["branch"]) != (
            "1.0", BASE_KIND, REPOSITORY, BRANCH):
        raise PlanError("Baseline target/schema mismatch.")
    for field in ("base_sha", "base_tree_sha", "ko_blob_sha"):
        require_sha(raw[field], field)
    require_sha(raw["baseline_hash"], "baseline", sha256=True)
    require_sha(raw["sitemap_outside_news_hash"], "sitemap protected sections", sha256=True)
    if raw["baseline_hash"] != checksum({key: value for key, value in raw.items() if key != "baseline_hash"}):
        raise PlanError("Baseline checksum mismatch.")
    if not isinstance(raw["files"], list):
        raise PlanError("Baseline files must be an array.")
    for item in raw["files"]:
        if not isinstance(item, dict) or set(item) != FILE_FIELDS:
            raise PlanError("Invalid baseline file fields.")
        require_sha(item["sha256"], "file SHA256", sha256=True)
        if not isinstance(item["size"], int) or isinstance(item["size"], bool) or item["size"] < 0:
            raise PlanError("Invalid baseline file size.")
    if tree_hashes(raw["files"])[""] != raw["base_tree_sha"]:
        raise PlanError("Baseline files do not reconstruct its Git tree.")
    by_path = {item["path"]: item for item in raw["files"]}
    if KO_PATH not in by_path or by_path[KO_PATH]["sha"] != raw["ko_blob_sha"]:
        raise PlanError("Baseline Korean blob mismatch.")
    return raw


def allowed_outputs(repository: Path) -> set[str]:
    manifest = read_json(repository / KO_PATH)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("items"), list):
        raise PlanError("Invalid Korean manifest.")
    paths = set(FIXED_OUTPUTS)
    slugs = set()
    for item in manifest["items"]:
        slug = item.get("slug") if isinstance(item, dict) else None
        if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug) or slug in slugs:
            raise PlanError("Invalid or duplicate Korean article slug.")
        slugs.add(slug)
        paths.update({f"crypto-news-{slug}.html", f"ko/crypto-news-{slug}.html"})
    return paths


def check_changes(repository: Path, baseline: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    original = {item["path"]: item for item in baseline["files"]}
    current = scan_files(repository, {path: item["mode"] for path, item in original.items()})
    if current.get(KO_PATH) != original[KO_PATH]:
        raise PlanError("Korean manifest bytes or mode changed from the baseline.")
    if set(original) - set(current):
        raise PlanError("Deletion of any baseline file is forbidden.")
    if sitemap_outside_news_hash((repository / "sitemap.xml").read_bytes()) != baseline["sitemap_outside_news_hash"]:
        raise PlanError("Sitemap outside generated news changed from the baseline.")
    allowed = allowed_outputs(repository)
    changed = []
    for path, item in current.items():
        if path in original and item["mode"] != original[path]["mode"]:
            raise PlanError(f"File mode change is forbidden: {path}")
        if item != original.get(path):
            if path not in allowed or item["mode"] != "100644":
                raise PlanError(f"Forbidden publication change: {path}")
            changed.append(path)
    return current, sorted(changed)


def validate_pages(repository: Path) -> dict[str, Any]:
    commands = [
        ["scripts/build-news-pages.py"],
        ["scripts/codex-news-translation.py", "verify"],
        ["scripts/publish_crypto_news.py", "verify-static-pages", "--repository", "."],
        ["scripts/audit-site.py"],
        ["scripts/codex-news-translation.py", "status"],
    ]
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    logs = []
    status_report = None
    validated_inventory = None
    for args in commands:
        try:
            result = subprocess.run([sys.executable, "-B", *args], cwd=repository, env=environment,
                                    capture_output=True, timeout=180)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PlanError(f"Validation could not run: {args[0]}: {exc}") from exc
        if result.returncode:
            detail = (result.stderr or result.stdout).decode("utf-8", errors="replace")[-2000:]
            raise PlanError(f"Validation failed: {' '.join(args)}: {detail}")
        if args[0] == "scripts/build-news-pages.py":
            validated_inventory = scan_files(repository)
        if args[-1] == "status":
            try:
                status_report = json.loads(result.stdout.decode("utf-8"), object_pairs_hook=unique_object)
            except (UnicodeError, ValueError) as exc:
                raise PlanError("Invalid translation status response.") from exc
        else:
            logs.append({"command": args, "stdout_sha256": hashlib.sha256(result.stdout).hexdigest()})
    if not isinstance(status_report, dict) or status_report.get("needs_work") is not False:
        raise PlanError("Translation status is not fully synchronized.")
    snapshots = {key: require_sha(status_report.get(key), key, sha256=True) for key in (
        "source_snapshot_hash", "english_snapshot_hash", "state_snapshot_hash")}
    if scan_files(repository) != validated_inventory:
        raise PlanError("Repository changed while read-only validation was running.")
    return {"snapshot_hashes": snapshots, "commands": logs,
            "validated_repository_hash": checksum(validated_inventory)}


def prepare(repository: Path, baseline: Any, output: Path) -> dict[str, Any]:
    repository = repository.resolve(strict=True)
    destination = outside_output(repository, output)
    baseline = validate_baseline(baseline)
    check_changes(repository, baseline)  # Reject modified validators before executing them.
    validation = validate_pages(repository)
    current, changed = check_changes(repository, baseline)
    if checksum(scan_files(repository)) != validation["validated_repository_hash"]:
        raise PlanError("Repository changed after validation.")
    files = []
    for path in changed:
        content = (repository / path).read_bytes()
        item = current[path]
        if object_sha("blob", content) != item["sha"] or hashlib.sha256(content).hexdigest() != item["sha256"]:
            raise PlanError(f"Output changed after validation: {path}")
        files.append({**item, "content": base64.b64encode(content).decode("ascii")})
    if scan_files(repository, {item["path"]: item["mode"] for item in baseline["files"]}) != current:
        raise PlanError("Repository bytes changed after validation.")
    plan = {"schema_version": "1.0", "kind": PLAN_KIND, "repository": REPOSITORY,
            "branch": BRANCH, "base_sha": baseline["base_sha"], "base_tree_sha": baseline["base_tree_sha"],
            "ko_blob_sha": baseline["ko_blob_sha"], "baseline_hash": baseline["baseline_hash"],
            "candidate_tree_sha": tree_hashes(list(current.values()))[""],
            "validation": validation, "files": files}
    plan["plan_hash"] = checksum(plan)
    write_json(destination, plan)
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    snap = commands.add_parser("snapshot")
    snap.add_argument("--repository", type=Path, required=True)
    snap.add_argument("--base-sha", required=True)
    snap.add_argument("--tree-file", type=Path, required=True)
    snap.add_argument("--output", type=Path, required=True)
    plan = commands.add_parser("prepare")
    plan.add_argument("--repository", type=Path, required=True)
    plan.add_argument("--baseline", type=Path, required=True)
    plan.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot":
            result = snapshot(args.repository, args.base_sha, read_json(args.tree_file), args.output)
        else:
            if args.baseline.resolve() == args.output.resolve():
                raise PlanError("Plan output must not overwrite the baseline.")
            result = prepare(args.repository, read_json(args.baseline), args.output)
        print(json.dumps({"kind": result["kind"], "base_sha": result["base_sha"],
                          "file_count": len(result["files"]), "output": str(args.output.resolve())}))
        return 0
    except (PlanError, OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        print(f"Cloud publication plan blocked: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
