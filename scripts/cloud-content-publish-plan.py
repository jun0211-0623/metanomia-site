#!/usr/bin/env python3
"""Prepare an immutable, exact-scope English content publication. No network."""
from __future__ import annotations
import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from html.parser import HTMLParser
from urllib.parse import urlsplit
from xml.sax.saxutils import escape as xml_escape
import xml.etree.ElementTree as ET


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


git = module("content_plan_git", "cloud-news-publish-plan.py")
content = module("content_plan_translation", "content-translation.py")
Error = git.PlanError
STATE = ".newsroom/content-translation-state.json"
SHARED = {STATE, "search-index.json", "sitemap.xml"}
KIND = "metanomia-cloud-content-baseline"
PLAN = "metanomia-cloud-content-publish-plan"
TEXT_FIELDS = {"title", "name", "description", "summary", "content", "metanomia_thought",
               "label", "caption", "alt", "excerpt", "body", "subtitle", "heading", "tagline"}


def validate_json_translation(source, translated, path=()):
    """Fail closed: identical shape/order/identifiers; only named text scalars vary."""
    if type(source) is not type(translated):
        raise Error(f"JSON type changed outside translation scope: {path}")
    if isinstance(source, dict):
        if set(source) != set(translated):
            raise Error(f"JSON schema keys changed outside translation scope: {path}")
        for key in source:
            validate_json_translation(source[key], translated[key], path + (key,))
    elif isinstance(source, list):
        if len(source) != len(translated):
            raise Error(f"JSON list length changed outside translation scope: {path}")
        for index, (left, right) in enumerate(zip(source, translated)):
            validate_json_translation(left, right, path + (index,))
    elif isinstance(source, str):
        field = path[-1] if path else None
        is_text = field in TEXT_FIELDS or (field == "type" and path and path[0] in {"programs", "items"})
        is_link = bool(re.match(r"^(?:https?:|//|/|mailto:|tel:)", source.strip(), re.I))
        if is_text and not is_link:
            if source.strip() and not translated.strip():
                raise Error(f"Translated JSON text is empty: {path}")
        elif source != translated:
            raise Error(f"JSON identifier or nonlanguage value changed: {path}")
    elif source != translated:
        raise Error(f"JSON numeric or nonlanguage value changed: {path}")


def status(repo, external_observations=None):
    return content.status(repo, external_observations=external_observations)


def pairs(report):
    result = report["scope_pairs"]
    if not isinstance(result, list):
        raise Error("Missing exact scope pairs.")
    return result


def snapshot(repo, sha, tree, output, external_observations=None):
    repo = repo.resolve(strict=True)
    output = git.outside_output(repo, output)
    original = git.snapshot(repo, sha, tree, output)
    report = status(repo, external_observations)
    scope = pairs(report)
    script_hashes = {p: git.checksum(parse_page((repo / p).read_bytes()).executable())
                     for pair in scope for p in pair["output_paths"]
                     if p.endswith(".html") and (repo / p).is_file()}
    value = {"schema_version": "1.0", "kind": KIND, "git_baseline": original,
             "content_status": report, "scope_pairs": scope, "english_script_hashes": script_hashes,
             "original_state": content.read_json(repo / STATE) if (repo / STATE).is_file() else None,
             "external_observations": external_observations}
    value["baseline_hash"] = git.checksum(value)
    git.write_json(output, value)
    return value


def validate_baseline(value):
    if not isinstance(value, dict) or set(value) != {
            "schema_version", "kind", "git_baseline", "content_status", "scope_pairs", "baseline_hash",
            "english_script_hashes", "original_state", "external_observations"}:
        raise Error("Invalid content baseline fields.")
    if value["schema_version"] != "1.0" or value["kind"] != KIND:
        raise Error("Invalid content baseline schema.")
    if value["baseline_hash"] != git.checksum({k: v for k, v in value.items() if k != "baseline_hash"}):
        raise Error("Content baseline checksum mismatch.")
    original = git.validate_baseline(value["git_baseline"])
    files = {i["path"]: i for i in original["files"]}
    if value["scope_pairs"] != pairs(value["content_status"]):
        raise Error("Baseline scopes differ from discovery.")
    for pair in value["scope_pairs"]:
        if set(pair) != {"source_path", "source_sha", "output_paths"}:
            raise Error("Invalid scope pair fields.")
        source = git.safe_path(pair["source_path"])
        if source not in files or pair["source_sha"] != files[source]["sha"]:
            raise Error("Scope source is not a baseline Git blob.")
        for target in pair["output_paths"]:
            git.safe_path(target)
    return value


def pending_map(value):
    return {i["source_path"]: i for i in value["content_status"]["pending"]}


def allowed(value):
    pending = pending_map(value)
    return SHARED | {p for i in value["scope_pairs"] if i["source_path"] in pending for p in i["output_paths"]}


def changes(repo, baseline):
    original = {i["path"]: i for i in baseline["git_baseline"]["files"]}
    current = git.scan_files(repo, {p: i["mode"] for p, i in original.items()})
    if set(original) - set(current):
        raise Error("Deleting any existing file is forbidden.")
    protected = {i["source_path"] for i in baseline["scope_pairs"]}
    accepted = allowed(baseline)
    changed = []
    for path, item in current.items():
        previous = original.get(path)
        if previous and item["mode"] != previous["mode"]:
            raise Error("Changing file mode is forbidden.")
        if item != previous:
            if (path not in accepted or path in protected or path.startswith("ko/")
                    or path in {"data/crypto-news.json", "data/crypto-news.en.json", ".newsroom/translation-state.json"}
                    or content.GENERATED_NEWS.fullmatch("ko/" + path) or item["mode"] != "100644"):
                raise Error(f"Forbidden content publication change: {path}")
            changed.append(path)
    return current, sorted(changed)


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lang = ""
        self.title = []
        self.description = ""
        self.in_title = False
        self.scripts = []
        self.in_script = None
        self.script_text = []
        self.has_canonical = False
        self.canonical = ""
        self.alternates = {}
        self.event_handlers = []
        self.active_elements = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "html": self.lang = attrs.get("lang", "")
        if tag == "title": self.in_title = True
        if tag == "meta" and attrs.get("name") == "description": self.description = attrs.get("content", "")
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonical = attrs.get("href", "")
            self.has_canonical = bool(self.canonical)
        if tag == "link" and attrs.get("rel") == "alternate" and attrs.get("hreflang"):
            self.alternates[attrs["hreflang"]] = attrs.get("href", "")
        for key, value in attrs.items():
            if key.lower().startswith("on") or key == "srcdoc" or (value or "").strip().lower().startswith("javascript:"):
                self.event_handlers.append((tag, key, value))
        if tag in {"base", "iframe", "object", "embed", "form"} or (tag == "meta" and attrs.get("http-equiv", "").lower() == "refresh"):
            self.active_elements.append((tag, {k: v for k, v in attrs.items() if k not in {"title", "aria-label"}}))
        if tag == "script":
            self.in_script = attrs
            self.script_text = []

    def handle_data(self, data):
        if self.in_title: self.title.append(data)
        if self.in_script is not None: self.script_text.append(data)

    def handle_endtag(self, tag):
        if tag == "title": self.in_title = False
        if tag == "script" and self.in_script is not None:
            if self.in_script.get("type", "").lower() != "application/ld+json":
                self.scripts.append((self.in_script, "".join(self.script_text)))
            else:
                json.loads("".join(self.script_text))
            self.in_script = None

    def executable(self):
        return {"scripts": self.scripts, "handlers": self.event_handlers, "active_elements": self.active_elements}


def parse_page(raw):
    page = Page()
    page.feed(raw.decode("utf-8"))
    page.close()
    if page.in_script is not None:
        raise Error("Unclosed HTML script element.")
    return page


def validate_site_url(value, expected, label):
    parts = urlsplit(value)
    if (parts.scheme != "https" or parts.hostname not in content.SITE_HOSTS or parts.username is not None
            or parts.password is not None or parts.port not in {None, 443} or parts.query or parts.fragment
            or (parts.path.rstrip("/") or "/") != (expected.rstrip("/") or "/")):
        raise Error(f"Wrong English {label} URL: {value}")


def output_url(path):
    if path == "index.html": return "/"
    return "/" + (path[:-5] if path.endswith(".html") else path)


def shared_outputs(repo, targets):
    """Deterministic English index updates and additive sitemap; never change KO rows."""
    index_path = repo / "search-index.json"
    index = git.read_json(index_path)
    if not isinstance(index, list): raise Error("Search index must be an array.")
    targets = sorted(p for p in targets if p.endswith(".html"))
    for path in targets:
        page = parse_page((repo / path).read_bytes())
        url = output_url(path)
        old = next((i for i in index if i.get("lang") == "en" and i.get("url") == url), None)
        item = dict(old or {"lang": "en", "type": "Report" if path.startswith("articles/") else
                          "People" if path.startswith("people/") else "Series" if path.startswith("series/") else "Page",
                          "meta": "", "url": url})
        item.update(title=" ".join("".join(page.title).split()).split("|")[0].strip(), sub=page.description)
        if old is not None: index[index.index(old)] = item
        else: index.append(item)
    if targets:
        git.write_json(index_path, index)
    sitemap_path = repo / "sitemap.xml"
    raw = sitemap_path.read_text(encoding="utf-8")
    xml = ET.fromstring(raw)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    existing = {urlsplit(i.text or "").path.rstrip("/") or "/" for i in xml.findall("s:url/s:loc", ns)}
    extra = []
    for path in targets:
        en = output_url(path)
        if (en.rstrip("/") or "/") in existing: continue
        ko = "/ko" if en == "/" else "/ko" + en
        base = "https://metanomia-site.vercel.app"
        en_url, ko_url = xml_escape(base + en, {'"': '&quot;'}), xml_escape(base + ko, {'"': '&quot;'})
        extra.append(f'  <url><loc>{en_url}</loc><xhtml:link rel="alternate" hreflang="en" href="{en_url}"/>'
                     f'<xhtml:link rel="alternate" hreflang="ko" href="{ko_url}"/></url>\n')
    if extra:
        if raw.count("</urlset>") != 1: raise Error("Invalid sitemap closing tag.")
        generated = raw.replace("</urlset>", "".join(extra) + "</urlset>")
        ET.fromstring(generated)
        sitemap_path.write_text(generated, encoding="utf-8", newline="\n")


def validate_records(repo, baseline, changed):
    state = content.read_json(repo / STATE) if (repo / STATE).is_file() else content.empty_state()
    before = baseline["content_status"]
    # State is parsed and actual source/output hashes checked by the translation module.
    after = status(repo, baseline["external_observations"])
    pending_before = pending_map(baseline)
    pending_after = {i["source_path"] for i in after["pending"]}
    completed = set(pending_before) - pending_after
    original_records = (baseline["original_state"] or {}).get("items", {})
    records = state.get("items", {})
    original_state = baseline["original_state"] or content.empty_state()
    fixed_fields = set(state) - {"items", "external_dependencies"}
    if {k: state[k] for k in fixed_fields} != {k: original_state[k] for k in set(original_state) - {"items", "external_dependencies"}}:
        raise Error("Translation state installation metadata cannot change.")
    if STATE in changed and state.get("external_dependencies", {}) != before.get("external_dependencies", {}):
        raise Error("External PDF state must exactly match the current observed dependencies.")
    if not isinstance(records, dict) or set(original_records) - set(records):
        raise Error("Content state records cannot be deleted.")
    for source, record in records.items():
        if record != original_records.get(source):
            if source not in completed or record.get("review_status") != "reviewed":
                raise Error("Only completed pending items may update translation state.")
    owners = {target: pair["source_path"] for pair in baseline["scope_pairs"] for target in pair["output_paths"]}
    for target in set(changed) - SHARED:
        if owners.get(target) not in completed:
            raise Error(f"Changed English output is not recorded as reviewed: {target}")
    for source in completed:
        item = pending_before[source]
        if item["kind"] != "html":
            continue
        local_assets = [dependency for dependency in item.get("dependencies", []) if dependency["kind"] in {"pdf", "image"}]
        if not local_assets:
            continue
        english_page = item["target_path"]
        english_references = content.references((repo / english_page).read_bytes()).urls
        linked = {content.local_reference(english_page, url) for url in english_references}
        for asset in local_assets:
            asset_path = asset["path"]
            label = "PDF" if asset["kind"] == "pdf" else "image"
            if asset_path in pending_after:
                raise Error(f"Completed English page still has an unfinished local {label} dependency: {source}: {asset_path}")
            translated_asset = content.target_for(asset_path)
            record = records.get(asset_path)
            if not record:
                raise Error(f"Completed English page has an unrecorded local {label} dependency: {source}: {asset_path}")
            if asset["kind"] == "image" and record["asset_disposition"] == "reused":
                same_bytes = (content.optional_sha(repo, translated_asset) is not None
                              and content.optional_sha(repo, translated_asset) == content.optional_sha(repo, asset_path))
                if asset_path not in linked and not (translated_asset in linked and same_bytes):
                    raise Error(f"Completed English page must link its reused source image or byte-identical English copy: {source}: {asset_path}")
            elif translated_asset not in linked:
                raise Error(f"Completed English page must link its translated local {label} dependency: {source}: {asset_path}")
    if STATE in changed and not completed:
        raise Error("State cannot change without a completed pending item.")
    if after.get("source_snapshot_hash", after.get("snapshot_hash")) != before.get("source_snapshot_hash", before.get("snapshot_hash")):
        raise Error("Korean source snapshot changed during translation.")
    return after, completed


def prepare(repo, baseline, output, external_observations=None):
    repo = repo.resolve(strict=True)
    output = git.outside_output(repo, output)
    baseline = validate_baseline(baseline)
    if baseline["external_observations"] is not None:
        if external_observations is None:
            raise Error("Fresh external PDF observations are required before publication.")
        observed_now = status(repo, external_observations)
        if observed_now.get("external_dependencies") != baseline["content_status"].get("external_dependencies"):
            raise Error("External PDF bytes or accessibility changed after the baseline.")
    elif external_observations is not None:
        raise Error("External PDF observations must be bound by the initial snapshot.")
    current, changed = changes(repo, baseline)
    # The caller may not author shared discovery outputs. Generate them here only.
    original = {i["path"]: i for i in baseline["git_baseline"]["files"]}
    if any(p in changed for p in ("search-index.json", "sitemap.xml")):
        raise Error("Search index and sitemap must be generated by prepare, not authored.")
    after, completed = validate_records(repo, baseline, changed)
    targets = {p for i in baseline["scope_pairs"] if i["source_path"] in completed for p in i["output_paths"]}
    for target in targets:
        source = next(i["source_path"] for i in baseline["scope_pairs"] if target in i["output_paths"])
        if target.endswith(".en.json"):
            validate_json_translation(content.read_json(repo / source), content.read_json(repo / target))
        if not target.endswith(".html") or not (repo / target).exists(): continue
        page = parse_page((repo / target).read_bytes())
        if not page.lang.lower().startswith("en") or not page.title:
            raise Error(f"English page lacks language/title: {target}")
        source_page = parse_page((repo / source).read_bytes())
        expected_script_hash = baseline["english_script_hashes"].get(target, git.checksum(source_page.executable()))
        if git.checksum(page.executable()) != expected_script_hash:
            raise Error(f"Executable script change is outside translation scope: {target}")
        expected = output_url(target).rstrip("/") or "/"
        if source_page.has_canonical or page.has_canonical:
            validate_site_url(page.canonical, expected, "canonical")
        for language, url in page.alternates.items():
            expected_alternate = "/ko" if language == "ko" and expected == "/" else "/ko" + expected if language == "ko" else expected
            if language not in {"ko", "en", "x-default"}:
                raise Error(f"Unexpected alternate language: {target}")
            validate_site_url(url, expected_alternate, "alternate")
        if source_page.alternates and not {"ko", "en"} <= set(page.alternates):
            raise Error(f"English page lost Korean/English alternate links: {target}")
    shared_outputs(repo, targets)
    current, changed = changes(repo, baseline)
    validated = git.checksum(current)
    logs = []
    for command in (["scripts/content-translation.py", "status"], ["scripts/audit-site.py"]):
        result = subprocess.run([sys.executable, "-B", *command], cwd=repo, capture_output=True, timeout=180)
        if result.returncode:
            raise Error(f"Validation failed: {command}: {(result.stderr or result.stdout).decode('utf-8', errors='replace')[-2000:]}")
        logs.append({"command": command, "stdout_sha256": hashlib.sha256(result.stdout).hexdigest()})
    if git.checksum(git.scan_files(repo)) != validated:
        raise Error("Repository changed during validation.")
    files = []
    for path in changed:
        raw = (repo / path).read_bytes()
        if git.object_sha("blob", raw) != current[path]["sha"]: raise Error("Output changed after validation.")
        files.append({**current[path], "content": base64.b64encode(raw).decode("ascii")})
    if git.checksum(git.scan_files(repo, {p: i["mode"] for p, i in current.items()})) != validated:
        raise Error("Repository changed while packing publication files.")
    original_git = baseline["git_baseline"]
    result = {"schema_version": "1.0", "kind": PLAN, "repository": git.REPOSITORY, "branch": git.BRANCH,
              "base_sha": original_git["base_sha"], "base_tree_sha": original_git["base_tree_sha"],
              "baseline_hash": baseline["baseline_hash"], "scope_pairs": baseline["scope_pairs"],
              "candidate_tree_sha": git.tree_hashes(list(current.values()))[""],
              "validation": {"snapshot_hashes": {
                  "source_snapshot_hash": after.get("source_snapshot_hash", after.get("snapshot_hash")),
                  "english_snapshot_hash": after["english_snapshot_hash"], "state_snapshot_hash": after["state_snapshot_hash"]},
                  "commands": logs, "validated_repository_hash": validated}, "files": files}
    result["plan_hash"] = git.checksum(result)
    git.write_json(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--base-sha", required=True)
    snap.add_argument("--tree-file", type=Path, required=True)
    plan = sub.add_parser("prepare")
    plan.add_argument("--baseline", type=Path, required=True)
    for command in (snap, plan):
        command.add_argument("--repository", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--external-observations", type=Path)
    args = parser.parse_args()
    try:
        observations = content.read_json(args.external_observations) if args.external_observations else None
        if args.command == "snapshot": result = snapshot(args.repository, args.base_sha, git.read_json(args.tree_file), args.output, observations)
        else:
            if args.baseline.resolve() == args.output.resolve(): raise Error("Do not overwrite the baseline.")
            result = prepare(args.repository, git.read_json(args.baseline), args.output, observations)
        print(json.dumps({"kind": result["kind"], "file_count": len(result.get("files", [])), "output": str(args.output)}))
    except Exception as exc:
        print(f"Content publication blocked: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
