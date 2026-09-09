from __future__ import annotations

import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SPEC = importlib.util.spec_from_file_location("cloud_content_planner_test", SCRIPTS / "cloud-content-publish-plan.py")
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)


def tree_for(repository):
    files = list(planner.git.scan_files(repository).values())
    hashes = planner.git.tree_hashes(files)
    entries = [{k: v[k] for k in ("path", "mode", "type", "sha", "size")} for v in files]
    entries.extend({"path": p, "mode": "040000", "type": "tree", "sha": sha} for p, sha in hashes.items() if p)
    return {"sha": hashes[""], "truncated": False, "tree": entries}


def page(path, title, body, lang="en", script="window.fixture = 1;"):
    en_path = path[3:] if path.startswith("ko/") else path
    en_url = planner.output_url(en_path)
    ko_url = "/ko" + en_url if en_url != "/" else "/ko"
    canonical = ko_url if lang == "ko" else en_url
    return (f'<!doctype html><html lang="{lang}"><head><title>{title} | Metanomia</title>'
            f'<meta name="description" content="{title} description">'
            f'<link rel="canonical" href="https://metanomia-site.vercel.app{canonical}">'
            f'<link rel="alternate" hreflang="en" href="https://metanomia-site.vercel.app{en_url}">'
            f'<link rel="alternate" hreflang="ko" href="https://metanomia-site.vercel.app{ko_url}">'
            f'<script>{script}</script></head><body><h1>{title}</h1><p>{body}</p></body></html>').encode()


class CloudContentPublishPlanTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="cloud-content-plan-test-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo = self.root / "repository"
        self.repo.mkdir()
        self.base_path = self.root / "baseline.json"
        self.output = self.root / "plan.json"
        self.observations = None
        self.write("data/crypto-news.json", b'{"items":[]}\n')
        self.write("README.md", b"Protected documentation\n")
        self.write("search-index.json", json.dumps([
            {"lang": "ko", "type": "Page", "title": "한글 원문", "sub": "보존", "meta": "", "url": "/ko/about"},
            {"lang": "en", "type": "Page", "title": "About old", "sub": "old", "meta": "keep", "url": "/about"},
            {"lang": "en", "type": "Page", "title": "Contact", "sub": "keep", "meta": "", "url": "/contact"},
        ], ensure_ascii=False).encode())
        self.write("sitemap.xml", ("<?xml version=\"1.0\"?><urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\" "
            "xmlns:xhtml=\"http://www.w3.org/1999/xhtml\"><url><loc>https://metanomia-site.vercel.app/ko/about</loc></url>"
            "<url><loc>https://metanomia-site.vercel.app/about</loc></url></urlset>\n").encode())
        for path in ("content-translation.py", "audit-site.py"):
            if path == "content-translation.py":
                self.write("scripts/" + path, (SCRIPTS / path).read_bytes())
            else:
                self.write("scripts/" + path, b"print('Synthetic audit fixture; real audit exercised separately')\n")
        for stem in ("about", "contact"):
            self.write(f"ko/{stem}.html", page(f"ko/{stem}.html", "소개", "기존 한글", "ko"))
            self.write(f"{stem}.html", page(f"{stem}.html", stem.title() + " old", "Old English"))
        self.media = {"channelId": "UCfixture", "programs": {"weekly": {
            "playlistId": "PLfixture", "type": "주간 뉴스", "name": "이번 주"}}, "items": [
            {"id": "one", "program": "weekly", "type": "뉴스", "title": "제목 하나", "url": "https://example.com/watch/one", "date": "2026-09-09", "count": 4},
            {"id": "two", "program": "weekly", "type": "뉴스", "title": "제목 둘", "url": "https://example.com/watch/two", "date": "2026-09-08", "count": 3}]}
        self.write_json("data/media-videos.ko.json", self.media)
        self.write_json("data/media-videos.en.json", self.translated_media())
        planner.content.bootstrap(self.repo, "a" * 40)
        # A remote Korean commit changed two existing sources and added one new page.
        self.write("ko/about.html", page("ko/about.html", "소개 새 글", "변경된 한글", "ko"))
        self.media["items"][0]["title"] = "변경된 제목 하나"
        self.write_json("data/media-videos.ko.json", self.media)
        self.write("ko/new.html", page("ko/new.html", "새 페이지", "새로운 내용", "ko"))
        self.capture()

    def write(self, path, data):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def write_json(self, path, value):
        return self.write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())

    def capture(self):
        self.tree = tree_for(self.repo)
        self.baseline = planner.snapshot(self.repo, "b" * 40, self.tree, self.base_path, self.observations)

    def translated_media(self):
        translated = copy.deepcopy(self.media)
        translated["programs"]["weekly"].update(type="Weekly News", name="This Week")
        for item in translated["items"]:
            prefix = "Revised" if item["title"].startswith("변경") else "Translated"
            item.update(type="News", title=prefix + " title " + item["id"])
        return translated

    def review(self, *sources):
        report = planner.content.status(self.repo, self.observations)
        pending = {i["source_path"]: i for i in report["pending"]}
        records = []
        for source in sources:
            item = pending[source]
            records.append({"source_path": source, "source_hash": item["source_hash"], "decision": "translated",
                "outputs": [{"path": target, "sha": planner.content.optional_sha(self.repo, target)} for target in item["output_paths"]],
                "reviewed_at": "2026-09-09T12:00:00+09:00"})
        planner.content.record_reviewed(self.repo, {"schema_version": "1.0",
            "source_snapshot_hash": report["source_snapshot_hash"], "state_snapshot_hash": report["state_snapshot_hash"],
            "records": records}, self.observations)

    def translate_about(self):
        self.write("about.html", page("about.html", "About revised", "Faithful revised English"))
        self.review("ko/about.html")

    def prepare(self):
        return planner.prepare(self.repo, self.baseline, self.output, self.observations)

    def external_fixture(self, translate=False):
        url = "https://documents.example.org/source-report.pdf"
        self.observations = {"schema_version": "1.0", "observations": {url: "a" * 64}}
        self.write("ko/new.html", page("ko/new.html", "새 보고서", f'<a href="{url}">보고서 전문</a>', "ko"))
        self.capture()
        pair = next(i for i in self.baseline["scope_pairs"] if i["source_path"] == "ko/new.html")
        translated_pdf = pair["output_paths"][1]
        if translate:
            self.write(translated_pdf, b"%PDF-1.7\n% synthetic test fixture, not an actual publication\n%%EOF\n")
            self.write("new.html", page("new.html", "New report", f'<a href="/{translated_pdf}">Complete English report</a>'))
            self.review("ko/new.html")
        return url, translated_pdf

    def local_pdf_fixture(self, english_link=True):
        source_pdf = "pdfs/report_KOR.pdf"
        english_pdf = planner.content.target_for(source_pdf)
        self.write(source_pdf, b"%PDF-1.7\n% Synthetic Korean report fixture\n%%EOF\n")
        self.write("ko/new.html", page("ko/new.html", "새 보고서", f'<a href="/{source_pdf}">보고서 전문</a>', "ko"))
        self.capture()
        self.write(english_pdf, b"%PDF-1.7\n% Synthetic translated English report fixture\n%%EOF\n")
        linked_pdf = english_pdf if english_link else source_pdf
        self.write("new.html", page("new.html", "New report", f'<a href="/{linked_pdf}">Read the complete report</a>'))
        return source_pdf, english_pdf

    def local_image_fixture(self, english_link=True, target_bytes=None):
        source_image = "images/diagram_ko.png"
        english_image = planner.content.target_for(source_image)
        self.write(source_image, b"\x89PNG\r\n\x1a\nSynthetic Korean diagram test fixture")
        self.write("ko/new.html", page("ko/new.html", "새 보고서", f'<img src="/{source_image}" alt="도표">', "ko"))
        self.capture()
        if target_bytes is not None:
            self.write(english_image, target_bytes)
        linked_image = english_image if english_link else source_image
        self.write("new.html", page("new.html", "New report", f'<img src="/{linked_image}" alt="Diagram">'))
        return source_image, english_image

    def review_reused_image(self, source):
        report = planner.content.status(self.repo, self.observations)
        item = next(i for i in report["pending"] if i["source_path"] == source)
        planner.content.record_reviewed(self.repo, {"schema_version": "1.0",
            "source_snapshot_hash": report["source_snapshot_hash"], "state_snapshot_hash": report["state_snapshot_hash"],
            "records": [{"source_path": source, "source_hash": item["source_hash"], "decision": "reused",
                         "outputs": [], "reviewed_at": "2026-09-09T12:00:00+09:00"}]}, self.observations)

    def blocked(self, pattern):
        with self.assertRaisesRegex((planner.Error, planner.content.ContentError, ValueError), pattern):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_noop_does_not_write_shared_files_or_state(self):
        before = planner.git.scan_files(self.repo)
        result = self.prepare()
        self.assertEqual(result["files"], [])
        self.assertEqual(result["base_tree_sha"], result["candidate_tree_sha"])
        self.assertEqual(before, planner.git.scan_files(self.repo))
        self.assertEqual(result["plan_hash"], planner.git.checksum({k: v for k, v in result.items() if k != "plan_hash"}))

    def test_noop_without_installed_state_remains_read_only(self):
        (self.repo / planner.STATE).unlink()
        self.capture()
        result = self.prepare()
        self.assertEqual(result["files"], [])
        self.assertFalse((self.repo / planner.STATE).exists())

    def test_valid_html_and_state_with_partial_pending(self):
        before_ko = (self.repo / "ko/about.html").read_bytes()
        index_before = json.loads((self.repo / "search-index.json").read_text(encoding="utf-8"))
        self.translate_about()
        result = self.prepare()
        paths = {i["path"] for i in result["files"]}
        self.assertEqual(paths, {"about.html", planner.STATE, "search-index.json"})
        self.assertEqual((self.repo / "ko/about.html").read_bytes(), before_ko)
        after = planner.content.status(self.repo)
        self.assertEqual(after["pending_count"], 2)
        self.assertNotIn("ko/about.html", {i["source_path"] for i in after["pending"]})
        index_after = json.loads((self.repo / "search-index.json").read_text(encoding="utf-8"))
        self.assertEqual(index_after[0], index_before[0])
        self.assertEqual(index_after[2], index_before[2])
        self.assertEqual(index_after[1]["meta"], "keep")
        self.assertEqual(index_after[1]["title"], "About revised")
        for item in result["files"]:
            raw = base64.b64decode(item["content"], validate=True)
            self.assertEqual(raw, (self.repo / item["path"]).read_bytes())
            self.assertEqual(planner.git.object_sha("blob", raw), item["sha"])
        self.assertEqual(result["candidate_tree_sha"], tree_for(self.repo)["sha"])

    def test_new_page_gets_only_english_index_and_additive_sitemap(self):
        original = (self.repo / "sitemap.xml").read_text()
        self.write("new.html", page("new.html", "New page", "Complete English content"))
        self.review("ko/new.html")
        result = self.prepare()
        self.assertEqual({i["path"] for i in result["files"]}, {"new.html", planner.STATE, "search-index.json", "sitemap.xml"})
        generated = (self.repo / "sitemap.xml").read_text()
        self.assertTrue(generated.startswith(original.split("</urlset>")[0]))
        xml = ET.fromstring(generated)
        locs = [i.text for i in xml.findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url/{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
        self.assertEqual(locs, ["https://metanomia-site.vercel.app/ko/about", "https://metanomia-site.vercel.app/about", "https://metanomia-site.vercel.app/new"])

    def test_korean_source_and_crypto_changes_block_before_validators(self):
        for path in ("ko/about.html", "data/media-videos.ko.json", "data/crypto-news.json"):
            with self.subTest(path=path):
                original = (self.repo / path).read_bytes()
                self.write(path, original + b" ")
                with patch.object(planner.subprocess, "run") as run:
                    self.blocked("Forbidden")
                    run.assert_not_called()
                self.write(path, original)

    def test_deletion_is_blocked(self):
        (self.repo / "contact.html").unlink()
        self.blocked("Deleting")

    @unittest.skipIf(os.name == "nt", "POSIX modes exercised on Linux")
    def test_mode_change_is_blocked(self):
        (self.repo / "about.html").chmod(0o755)
        self.blocked("mode")

    def test_unrelated_files_and_scripts_are_blocked(self):
        for path in ("README.md", "scripts/new.py", ".github/workflows/new.yml", "js/new.js"):
            with self.subTest(path=path):
                target = self.repo / path
                original = target.read_bytes() if target.exists() else None
                self.write(path, b"unrelated change")
                with patch.object(planner.subprocess, "run") as run:
                    self.blocked("Forbidden")
                    run.assert_not_called()
                if original is None: target.unlink()
                else: self.write(path, original)

    def test_existing_nonpending_english_cannot_be_changed(self):
        self.write("contact.html", page("contact.html", "Unrequested edit", "Unrelated"))
        self.blocked("Forbidden")

    def test_authored_search_and_sitemap_are_blocked(self):
        for path in ("search-index.json", "sitemap.xml"):
            with self.subTest(path=path):
                original = (self.repo / path).read_bytes()
                self.write(path, original + b" ")
                self.blocked("must be generated")
                self.write(path, original)

    def test_changed_english_without_review_is_blocked(self):
        self.write("about.html", page("about.html", "Unreviewed", "Unreviewed"))
        self.blocked("not recorded as reviewed")

    def test_state_corruption_and_orphan_record_changes_block(self):
        self.write_json(planner.STATE, {"schema_version": "1.0", "items": {}})
        self.blocked("state fields")

    def test_state_installation_metadata_cannot_change(self):
        self.translate_about()
        state = planner.content.read_json(self.repo / planner.STATE)
        state["baseline_ref"] = "c" * 40
        self.write_json(planner.STATE, state)
        self.blocked("installation metadata")

    def test_state_existing_nonpending_record_cannot_change(self):
        state = planner.content.read_json(self.repo / planner.STATE)
        state["items"]["ko/contact.html"].update(review_status="reviewed", reviewed_at="2026-09-09T12:00:00+09:00")
        self.write_json(planner.STATE, state)
        self.blocked("Only completed pending")

    def test_state_records_cannot_be_deleted(self):
        state = planner.content.read_json(self.repo / planner.STATE)
        del state["items"]["ko/contact.html"]
        self.write_json(planner.STATE, state)
        self.blocked("cannot be deleted")

    def test_corrupt_actual_output_hash_is_not_accepted(self):
        self.translate_about()
        state = planner.content.read_json(self.repo / planner.STATE)
        state["items"]["ko/about.html"]["outputs"][0]["sha"] = "f" * 40
        self.write_json(planner.STATE, state)
        self.blocked("Only completed pending|not recorded")

    def test_valid_json_translates_text_not_identifiers(self):
        self.write_json("data/media-videos.en.json", self.translated_media())
        self.review("data/media-videos.ko.json")
        result = self.prepare()
        self.assertEqual({i["path"] for i in result["files"]}, {"data/media-videos.en.json", planner.STATE})

    def test_json_identifier_url_number_order_schema_and_type_changes_block(self):
        mutations = {
            "channel": lambda x: x.update(channelId="another"),
            "playlist": lambda x: x["programs"]["weekly"].update(playlistId="another"),
            "id": lambda x: x["items"][0].update(id="another"),
            "url": lambda x: x["items"][0].update(url="https://other.example"),
            "number": lambda x: x["items"][0].update(count=5),
            "date": lambda x: x["items"][0].update(date="2026-09-10"),
            "order": lambda x: x["items"].reverse(),
            "delete": lambda x: x["items"].pop(),
            "key": lambda x: x.update(extra="new"),
            "type": lambda x: x["items"][0].update(count="4"),
            "empty": lambda x: x["items"][0].update(title=""),
        }
        state_bytes = (self.repo / planner.STATE).read_bytes()
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                translated = self.translated_media()
                mutate(translated)
                self.write_json("data/media-videos.en.json", translated)
                self.review("data/media-videos.ko.json")
                self.blocked("JSON")
                self.write(planner.STATE, state_bytes)

    def test_script_handlers_active_content_addition_and_unclosed_script_block(self):
        examples = [
            page("about.html", "About revised", "Body", script="window.evil = 1;"),
            page("about.html", "About revised", '<img src="x" onerror="evil()">'),
            page("about.html", "About revised", '<iframe srcdoc="evil"></iframe>'),
            page("about.html", "About revised", '<iframe src="https://evil.example"></iframe>'),
            page("about.html", "About revised", '<meta http-equiv="refresh" content="0;url=https://evil.example">'),
            page("about.html", "About revised", "Body") + b"<script>unfinished",
        ]
        state_bytes = (self.repo / planner.STATE).read_bytes()
        for raw in examples:
            with self.subTest(raw=raw[-100:]):
                self.write("about.html", raw)
                self.review("ko/about.html")
                self.blocked("Executable|Unclosed")
                self.write(planner.STATE, state_bytes)

    def test_canonical_wrong_host_path_and_language_links_block(self):
        originals = page("about.html", "About revised", "Body")
        edits = [
            originals.replace(b'https://metanomia-site.vercel.app/about', b'https://evil.example/about', 1),
            originals.replace(b'rel="canonical" href="https://metanomia-site.vercel.app/about"', b'rel="canonical" href="https://metanomia-site.vercel.app/wrong"'),
            originals.replace(b'hreflang="ko" href="https://metanomia-site.vercel.app/ko/about"', b'hreflang="ko" href="https://evil.example/ko/about"'),
            originals.replace(b'<link rel="alternate" hreflang="en" href="https://metanomia-site.vercel.app/about">', b''),
        ]
        state_bytes = (self.repo / planner.STATE).read_bytes()
        for raw in edits:
            with self.subTest(raw=raw[100:300]):
                self.write("about.html", raw)
                self.review("ko/about.html")
                self.blocked("URL|alternate")
                self.write(planner.STATE, state_bytes)

    def test_validator_failure_does_not_emit_plan(self):
        with patch.object(planner.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, b"", b"fixture failure")):
            self.blocked("Validation failed")

    def test_validator_mutation_blocks_plan(self):
        def mutate(command, **kwargs):
            self.write("README.md", b"changed by validator")
            return subprocess.CompletedProcess(command, 0, b"ok", b"")
        with patch.object(planner.subprocess, "run", side_effect=mutate):
            self.blocked("changed during validation")

    def test_baseline_corruption_is_rejected(self):
        self.baseline["scope_pairs"][0]["source_sha"] = "0" * 40
        self.blocked("checksum")

    def test_external_output_requirement(self):
        with self.assertRaisesRegex(planner.Error, "outside"):
            planner.prepare(self.repo, self.baseline, self.repo / "plan.json")

    def test_external_pdf_snapshot_requires_fresh_before_publication_observation(self):
        self.external_fixture()
        with self.assertRaisesRegex(planner.Error, "Fresh external PDF"):
            planner.prepare(self.repo, self.baseline, self.output)

    def test_external_pdf_stable_observation_noop(self):
        self.external_fixture()
        self.assertEqual(self.prepare()["files"], [])

    def test_external_pdf_change_or_inaccessibility_blocks(self):
        url, _ = self.external_fixture(translate=True)
        for observations in ({"schema_version": "1.0", "observations": {url: "b" * 64}},
                             {"schema_version": "1.0", "observations": {}, "errors": {url: "temporarily unavailable"}}):
            with self.subTest(observations=observations):
                self.observations = observations
                self.blocked("External PDF bytes or accessibility")

    def test_external_pdf_html_owned_output_and_state_are_allowed(self):
        _, pdf = self.external_fixture(translate=True)
        result = self.prepare()
        self.assertEqual({i["path"] for i in result["files"]}, {"new.html", pdf, planner.STATE, "search-index.json", "sitemap.xml"})

    def test_external_pdf_wrong_observation_state_is_blocked(self):
        url, _ = self.external_fixture(translate=True)
        state = planner.content.read_json(self.repo / planner.STATE)
        state["external_dependencies"][url] = "b" * 64
        self.write_json(planner.STATE, state)
        self.blocked("External PDF state")

    def test_unowned_external_pdf_output_is_blocked(self):
        self.external_fixture()
        self.write("pdfs/translated/other/document-1.en.pdf", b"%PDF-1.7 fake")
        self.blocked("Forbidden")

    def test_unbound_external_observation_cannot_be_added_after_snapshot(self):
        self.observations = {"schema_version": "1.0", "observations": {}}
        self.blocked("bound by the initial snapshot")

    def test_static_crypto_landing_is_distinct_from_generated_news(self):
        self.write("ko/crypto-news.html", page("ko/crypto-news.html", "뉴스 목록", "목록 안내", "ko"))
        self.capture()
        self.write("crypto-news.html", page("crypto-news.html", "Crypto news", "News archive"))
        self.review("ko/crypto-news.html")
        self.assertIn("crypto-news.html", {i["path"] for i in self.prepare()["files"]})

    def test_changed_files_after_packing_block_the_plan(self):
        self.translate_about()
        original_scan = planner.git.scan_files
        count = 0
        def race(repository, modes=None):
            nonlocal count
            count += 1
            if count == 4:
                self.write("README.md", b"racing mutation")
            return original_scan(repository, modes)
        with patch.object(planner.git, "scan_files", side_effect=race):
            self.blocked("while packing")

    def test_local_pdf_unfinished_dependency_blocks_reviewed_html(self):
        source_pdf, english_pdf = self.local_pdf_fixture()
        # The English PDF already exists, but has not passed explicit review.
        self.review("ko/new.html")
        self.blocked("not recorded as reviewed|unfinished local PDF")

    def test_local_pdf_untranslated_and_missing_output_blocks_reviewed_html(self):
        source_pdf, english_pdf = self.local_pdf_fixture()
        (self.repo / english_pdf).unlink()
        self.review("ko/new.html")
        self.blocked("unfinished local PDF")

    def test_local_pdf_and_html_complete_in_same_batch(self):
        source_pdf, english_pdf = self.local_pdf_fixture()
        self.review(source_pdf, "ko/new.html")
        result = self.prepare()
        self.assertEqual({i["path"] for i in result["files"]}, {"new.html", english_pdf, planner.STATE, "search-index.json", "sitemap.xml"})

    def test_local_pdf_reviewed_but_english_page_links_korean_blocks(self):
        source_pdf, english_pdf = self.local_pdf_fixture(english_link=False)
        self.review(source_pdf, "ko/new.html")
        self.blocked("must link its translated local PDF")

    def test_local_pdf_already_synchronized_can_support_completed_html(self):
        source_pdf, english_pdf = self.local_pdf_fixture()
        self.review(source_pdf)
        # This represents a pre-existing synchronized PDF at a newer remote base.
        self.capture()
        self.review("ko/new.html")
        result = self.prepare()
        self.assertNotIn(english_pdf, {i["path"] for i in result["files"]})
        self.assertIn(planner.STATE, {i["path"] for i in result["files"]})

    def test_local_image_unreviewed_blocks_completed_html(self):
        source_image, _ = self.local_image_fixture(english_link=False)
        self.review("ko/new.html")
        self.blocked("unfinished local image")

    def test_local_image_translated_and_html_complete_together(self):
        source_image, english_image = self.local_image_fixture(target_bytes=b"\x89PNG\r\n\x1a\nSynthetic English diagram")
        self.review(source_image, "ko/new.html")
        self.assertIn(english_image, {i["path"] for i in self.prepare()["files"]})

    def test_translated_image_requires_english_target_link(self):
        source_image, _ = self.local_image_fixture(english_link=False, target_bytes=b"\x89PNG\r\n\x1a\nSynthetic English diagram")
        self.review(source_image, "ko/new.html")
        self.blocked("must link its translated local image")

    def test_reviewed_reused_image_accepts_original_source_link(self):
        source_image, _ = self.local_image_fixture(english_link=False)
        self.review_reused_image(source_image)
        self.review("ko/new.html")
        self.assertIn("new.html", {i["path"] for i in self.prepare()["files"]})

    def test_reviewed_reused_image_accepts_byte_identical_english_copy(self):
        source_image, english_image = self.local_image_fixture()
        self.write(english_image, (self.repo / source_image).read_bytes())
        self.review_reused_image(source_image)
        self.review("ko/new.html")
        self.assertIn(english_image, {i["path"] for i in self.prepare()["files"]})

    def test_reviewed_reused_image_rejects_different_english_copy(self):
        source_image, _ = self.local_image_fixture(target_bytes=b"different image bytes")
        self.review_reused_image(source_image)
        self.review("ko/new.html")
        self.blocked("byte-identical English copy")

    def test_reviewed_reused_image_rejects_missing_english_copy_link(self):
        source_image, _ = self.local_image_fixture()
        self.review_reused_image(source_image)
        self.review("ko/new.html")
        self.blocked("byte-identical English copy")

    def test_unchanged_baseline_preserved_image_needs_no_new_semantic_review(self):
        source_image, _ = self.local_image_fixture(english_link=False)
        self.review_reused_image(source_image)
        state = planner.content.read_json(self.repo / planner.STATE)
        state["items"][source_image].update(review_status="baseline_preserved", reviewed_at=None)
        self.write_json(planner.STATE, state)
        self.capture()
        self.review("ko/new.html")
        self.prepare()
        self.assertEqual(planner.content.read_json(self.repo / planner.STATE)["items"][source_image]["review_status"], "baseline_preserved")

    def test_changed_baseline_preserved_image_becomes_pending_before_html_completion(self):
        source_image, _ = self.local_image_fixture(english_link=False)
        self.review_reused_image(source_image)
        state = planner.content.read_json(self.repo / planner.STATE)
        state["items"][source_image].update(review_status="baseline_preserved", reviewed_at=None)
        self.write_json(planner.STATE, state)
        self.write(source_image, b"\x89PNG\r\n\x1a\nChanged Korean diagram")
        self.capture()
        self.review("ko/new.html")
        self.blocked("unfinished local image")


if __name__ == "__main__":
    unittest.main()
