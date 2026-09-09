"""Unit tests for the cloud-only discovery/review state contract (no network)."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/content-translation.py"
SPEC = importlib.util.spec_from_file_location("content_translation", MODULE_PATH)
content = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(content)


class ContentTranslationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repository = Path(self.temporary.name) / "repository"
        self.repository.mkdir()

    def put(self, path, value):
        destination = self.repository / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(value.encode("utf-8") if isinstance(value, str) else value)
        return destination

    def html(self, language="ko", body="본문"):
        return f'<!doctype html><html lang="{language}"><body>{body}</body></html>'

    def page(self, name="report", english=True, body="본문"):
        self.put(f"ko/articles/{name}.html", self.html(body=body))
        if english:
            self.put(f"articles/{name}.html", self.html("en", "Existing English"))

    def status(self):
        return content.status(self.repository)

    def baseline(self):
        return content.bootstrap(self.repository, "a" * 40)

    def bundle(self, report, paths, decisions=None):
        pending = {item["source_path"]: item for item in report["pending"]}
        decisions = decisions or {}
        records = []
        for path in paths:
            item = pending[path]
            decision = decisions.get(path, "translated")
            outputs = [] if decision == "reused" else [{
                "path": target,
                "sha": content.optional_sha(self.repository, target)} for target in item["output_paths"]]
            records.append({"source_path": path, "source_hash": item["source_hash"],
                            "decision": decision, "outputs": outputs,
                            "reviewed_at": "2026-09-09T12:00:00+09:00"})
        return {"schema_version": "1.0", "source_snapshot_hash": report["source_snapshot_hash"],
                "state_snapshot_hash": report["state_snapshot_hash"],
                "english_snapshot_hash": report["english_snapshot_hash"], "records": records}

    def test_git_blob_hash_and_pairing_rules(self):
        self.assertEqual(content.blob_sha(b"test\n"), "9daeafb9864cf43055ae93beb0afd6c7d144bfa4")
        examples = {"ko/index.html": "index.html", "ko/articles/new.html": "articles/new.html",
                    "data/media-videos.ko.json": "data/media-videos.en.json",
                    "pdfs/Report_KOR.pdf": "pdfs/Report_ENG.pdf", "images/chart_ko.svg": "images/chart_en.svg",
                    "images/chart.ko.png": "images/chart.en.png", "images/chart-ko.png": "images/chart-en.png",
                    "pdfs/report.pdf": "pdfs/report.en.pdf", "images/KOREA.png": "images/KOREA.en.png",
                    "ko/images/chart_ko.png": "images/chart_en.png", "ko/pdfs/report.pdf": "pdfs/report.en.pdf"}
        for source, target in examples.items():
            with self.subTest(source=source):
                self.assertEqual(content.target_for(source), target)
        with self.assertRaisesRegex(content.ContentError, "Ambiguous language"):
            content.target_for("pdfs/report_KOR_ko.pdf")

    def observations(self, urls):
        return {"schema_version": "1.0", "observations": {url: "b" * 64 for url in urls}}

    def test_external_pdf_scope_is_html_owned_sorted_and_deterministic(self):
        self.page(body='<a href="https://files.example.org/z.pdf?x=1&amp;y=2">B</a>'
                       '<a href="https://files.example.org/a.pdf">A</a>'
                       '<a href="https://files.example.org/a.pdf">A duplicate</a>')
        report = self.status()
        item = report["pending"][0]
        self.assertEqual(item["external_sources"], ["https://files.example.org/a.pdf", "https://files.example.org/z.pdf?x=1&y=2"])
        self.assertEqual(item["output_paths"], ["articles/report.html",
                         "pdfs/translated/articles/report/document-1.en.pdf", "pdfs/translated/articles/report/document-2.en.pdf"])
        self.assertEqual(report["scope_pairs"][0]["output_paths"], item["output_paths"])

    def test_external_bootstrap_preserves_existing_english_without_forcing_pdf_backfill(self):
        url = "https://files.example.org/report.pdf"
        self.page(body=f'<a href="{url}">Report</a>')
        observed = self.observations([url])
        result = content.bootstrap(self.repository, "a" * 40, observed)
        self.assertEqual(result["preserved_count"], 1)
        report = content.status(self.repository, observed)
        self.assertFalse(report["needs_work"])
        self.assertEqual(content.status(self.repository)["source_snapshot_hash"], report["source_snapshot_hash"])
        self.assertFalse((self.repository / "pdfs/translated/articles/report/document-1.en.pdf").exists())
        state = content.read_json(self.repository / content.STATE_PATH)
        self.assertEqual(state["external_dependencies"], {url: "b" * 64})
        self.assertEqual(state["items"]["ko/articles/report.html"]["external_sources"], [url])
        self.assertEqual(len(state["items"]["ko/articles/report.html"]["outputs"]), 1)

    def test_same_url_external_pdf_bytes_change_triggers_pending(self):
        url = "https://files.example.org/report.pdf"
        self.page(body=f'<a href="{url}">Report</a>')
        observed = self.observations([url])
        content.bootstrap(self.repository, "a" * 40, observed)
        before = content.status(self.repository, observed)
        changed = copy.deepcopy(observed)
        changed["observations"][url] = "c" * 64
        after = content.status(self.repository, changed)
        self.assertTrue(after["needs_work"])
        self.assertEqual(after["pending"][0]["reason"], "source_changed")
        self.assertEqual(before["sources"][0]["source_sha"], after["sources"][0]["source_sha"])
        self.assertNotEqual(before["source_snapshot_hash"], after["source_snapshot_hash"])

    def test_unavailable_external_pdf_reported_and_review_blocked(self):
        url = "https://files.example.org/report.pdf"
        self.page(body=f'<a href="{url}">Report</a>')
        observed = {"schema_version": "1.0", "observations": {}, "errors": {url: "HTTP 403"}}
        report = content.status(self.repository, observed)
        self.assertEqual(report["pending"][0]["reason"], "external_source_unavailable")
        self.assertIsNone(report["external_dependencies"][url])
        self.put("pdfs/translated/articles/report/document-1.en.pdf", b"%PDF-1.7 translation")
        with self.assertRaisesRegex(content.ContentError, "must be observed"):
            content.record_reviewed(self.repository, self.bundle(report, ["ko/articles/report.html"]), observed)

    def test_external_pdf_review_requires_pdf_and_html_link(self):
        url = "https://files.example.org/report.pdf"
        self.page(body=f'<a href="{url}">Report</a>')
        observed = self.observations([url])
        report = content.status(self.repository, observed)
        target = "pdfs/translated/articles/report/document-1.en.pdf"
        self.put(target, b"%PDF-1.7 English document")
        bundle = self.bundle(report, ["ko/articles/report.html"])
        with self.assertRaisesRegex(content.ContentError, "must link each translated"):
            content.record_reviewed(self.repository, bundle, observed)
        self.put("articles/report.html", self.html("en", f'<a href="/{target}">English report</a>'))
        bundle = self.bundle(report, ["ko/articles/report.html"])
        self.assertEqual(content.record_reviewed(self.repository, bundle, observed)["recorded_count"], 1)
        self.assertFalse(content.status(self.repository, observed)["needs_work"])
        self.assertFalse(content.status(self.repository)["needs_work"])
        self.put(target, b"%PDF-1.7 edited after review")
        self.assertEqual(content.status(self.repository, observed)["pending"][0]["reason"], "output_changed")

    def test_external_observation_arbitrary_urls_and_conflicting_result_rejected(self):
        url = "https://files.example.org/report.pdf"
        self.page(body=f'<a href="{url}">Report</a>')
        observed = self.observations(["https://not-declared.example.org/document.pdf"])
        with self.assertRaisesRegex(content.ContentError, "not declared"):
            content.status(self.repository, observed)
        observed = self.observations([url])
        observed["errors"] = {url: "HTTP 403"}
        with self.assertRaisesRegex(content.ContentError, "both observed and failed"):
            content.status(self.repository, observed)

    def test_unsafe_external_pdf_urls_cannot_authorize_output_paths(self):
        urls = ["http://localhost/file.pdf", "http://127.0.0.1/file.pdf", "http://192.168.0.1/file.pdf",
                "http://[::1]/file.pdf", "https://user:password@files.example.org/file.pdf",
                "//files.example.org/file.pdf", "file:///x.pdf", "ftp://files.example.org/file.pdf",
                "https://metanomia.org/pdfs/report.pdf"]
        for url in urls:
            with self.subTest(url=url):
                self.assertFalse(content.public_external_pdf(url))
        self.assertTrue(content.public_external_pdf("https://files.example.org/report%2Epdf?download=1"))

    def test_state_cannot_disguise_html_as_reused_image(self):
        self.page()
        self.baseline()
        state = content.read_json(self.repository / content.STATE_PATH)
        record = state["items"]["ko/articles/report.html"]
        record["kind"] = "image"
        record["asset_disposition"] = "reused"
        record["outputs"] = []
        with self.assertRaisesRegex(content.ContentError, "kind disagrees"):
            content.validate_state(state)

    def test_discover_pages_redirects_and_language_json_excludes_generated_crypto(self):
        self.page()
        self.put("ko/team.html", self.html(body='<meta http-equiv="refresh" content="0;url=people.html">'))
        self.put("ko/crypto-news.html", self.html())
        self.put("ko/crypto-news-detail.html", self.html())
        self.put("ko/crypto-news-2026-09-09-crypto-news-abcdef1234.html", self.html())
        self.put("data/media-videos.ko.json", '{"title":"비디오"}')
        self.put("data/crypto-news.json", "[]")
        self.put("data/crypto-news.ko.json", "[]")
        report = self.status()
        self.assertEqual({item["source_path"] for item in report["sources"]},
                         {"ko/articles/report.html", "ko/team.html", "ko/crypto-news.html", "data/media-videos.ko.json"})
        self.assertEqual(report["pending_count"], 4)
        self.assertEqual(report["snapshot_hash"], report["source_snapshot_hash"])

    def test_new_page_missing_english_remains_discoverable(self):
        self.page(english=False)
        item = self.status()["pending"][0]
        self.assertEqual(item["output_paths"], ["articles/report.html"])
        self.assertIn("missing_english", item["reasons"])
        self.assertEqual(item["source_sha"], content.blob_sha((self.repository / item["source_path"]).read_bytes()))

    def test_bootstrap_preserves_existing_pairs_without_review_claim(self):
        self.page()
        before = (self.repository / "articles/report.html").read_bytes()
        result = self.baseline()
        self.assertFalse(result["semantic_review_claimed"])
        report = self.status()
        self.assertFalse(report["needs_work"])
        self.assertEqual(report["baseline_preserved_count"], 1)
        self.assertEqual(report["reviewed_count"], 0)
        state = content.read_json(self.repository / content.STATE_PATH)
        self.assertEqual(state["items"]["ko/articles/report.html"]["review_status"], "baseline_preserved")
        self.assertIsNone(state["items"]["ko/articles/report.html"]["reviewed_at"])
        self.assertEqual(before, (self.repository / "articles/report.html").read_bytes())

    def test_bootstrap_never_reseeds_existing_state(self):
        self.page()
        self.baseline()
        state = (self.repository / content.STATE_PATH).read_bytes()
        with self.assertRaisesRegex(content.ContentError, "installation-only"):
            self.baseline()
        self.assertEqual(state, (self.repository / content.STATE_PATH).read_bytes())

    def test_bootstrap_missing_english_stays_pending(self):
        self.page(english=False)
        result = self.baseline()
        self.assertEqual(result["preserved_count"], 0)
        self.assertEqual(result["skipped"], ["ko/articles/report.html"])
        self.assertTrue(self.status()["needs_work"])

    def test_source_changed_and_output_drift_detected_independently(self):
        self.page()
        self.baseline()
        original = self.status()
        self.put("articles/report.html", self.html("en", "Independent English edit"))
        drifted = self.status()
        self.assertEqual(drifted["pending"][0]["reason"], "output_changed")
        self.assertEqual(drifted["source_snapshot_hash"], original["source_snapshot_hash"])
        self.assertNotEqual(drifted["english_snapshot_hash"], original["english_snapshot_hash"])
        self.put("ko/articles/report.html", self.html(body="수정된 본문"))
        changed = self.status()["pending"][0]
        self.assertEqual(changed["reason"], "source_changed")
        self.assertIn("output_changed", changed["reasons"])

    def test_missing_english_after_baseline(self):
        self.page()
        self.baseline()
        (self.repository / "articles/report.html").unlink()
        self.assertEqual(self.status()["pending"][0]["reason"], "missing_english")

    def test_local_assets_actual_attributes_dependency_hash_and_external_reporting(self):
        body = ('<a href="../../pdfs/report_KOR.pdf?download=1#p2">PDF</a>'
                '<img src="https://metanomia.org/images/diagram_ko.png">'
                '<img srcset="/images/small.png 1x, /images/large.png 2x">'
                '<a href="https://elsewhere.example.org/report.pdf">external PDF</a>'
                '<p>/pdfs/not-a-link.pdf</p><script>const x="/images/not-a-link.png";</script>')
        self.page(body=body)
        for path in ["pdfs/report_KOR.pdf", "images/diagram_ko.png", "images/small.png", "images/large.png"]:
            self.put(path, b"asset bytes")
        first = self.status()
        self.assertEqual(len(first["sources"]), 5)
        self.assertEqual(first["external_references"], [{"source_path": "ko/articles/report.html",
                         "url": "https://elsewhere.example.org/report.pdf", "kind": "pdf",
                         "status": "requires_external_verification"}])
        self.put("pdfs/report_KOR.pdf", b"changed PDF only")
        second = self.status()
        before = {item["source_path"]: item for item in first["sources"]}
        after = {item["source_path"]: item for item in second["sources"]}
        self.assertEqual(before["ko/articles/report.html"]["source_sha"], after["ko/articles/report.html"]["source_sha"])
        self.assertNotEqual(before["ko/articles/report.html"]["source_hash"], after["ko/articles/report.html"]["source_hash"])
        self.assertNotEqual(first["source_snapshot_hash"], second["source_snapshot_hash"])

    def test_missing_local_asset_reported_without_invalid_scope_sha(self):
        self.page(body='<a href="/pdfs/missing.pdf">PDF</a>')
        report = self.status()
        pending = {item["source_path"]: item for item in report["pending"]}
        self.assertEqual(pending["pdfs/missing.pdf"]["reason"], "missing_source_asset")
        self.assertNotIn("pdfs/missing.pdf", [item["source_path"] for item in report["scope_pairs"]])

    def test_bootstrap_images_reused_but_missing_pdf_not_claimed(self):
        self.page(body='<img src="/images/photo.png"><a href="/pdfs/report.pdf">PDF</a>')
        self.put("images/photo.png", b"image")
        self.put("pdfs/report.pdf", b"%PDF-1.7 Korean")
        self.baseline()
        state = content.read_json(self.repository / content.STATE_PATH)
        self.assertEqual(state["items"]["images/photo.png"]["outputs"], [])
        self.assertEqual(state["items"]["images/photo.png"]["asset_disposition"], "reused")
        self.assertNotIn("pdfs/report.pdf", state["items"])
        self.assertEqual([item["source_path"] for item in self.status()["pending"]], ["pdfs/report.pdf"])

    def test_shared_image_update_marks_page_and_reused_asset_pending(self):
        self.page(body='<img src="/images/photo.png">')
        self.put("images/photo.png", b"first")
        self.baseline()
        self.put("images/photo.png", b"second")
        report = self.status()
        self.assertEqual({item["source_path"] for item in report["pending"]}, {"images/photo.png", "ko/articles/report.html"})
        self.assertTrue(all(item["reason"] == "source_changed" for item in report["pending"]))

    def test_english_authorship_does_not_invalidate_source_snapshot(self):
        self.page(english=False)
        original = self.status()
        self.put("articles/report.html", self.html("en", "Authored translation"))
        bundle = self.bundle(original, ["ko/articles/report.html"])
        result = content.record_reviewed(self.repository, bundle)
        self.assertEqual(result["recorded_count"], 1)
        self.assertFalse(self.status()["needs_work"])
        self.assertEqual(self.status()["reviewed_count"], 1)

    def test_stale_source_bundle_is_rejected_without_state_write(self):
        self.page()
        original = self.status()
        bundle = self.bundle(original, ["ko/articles/report.html"])
        self.put("ko/articles/report.html", self.html(body="new source"))
        with self.assertRaisesRegex(content.ContentError, "Stale source_snapshot_hash"):
            content.record_reviewed(self.repository, bundle)
        self.assertFalse((self.repository / content.STATE_PATH).exists())

    def test_stale_state_bundle_is_rejected(self):
        self.page()
        original = self.status()
        bundle = self.bundle(original, ["ko/articles/report.html"])
        self.baseline()
        with self.assertRaisesRegex(content.ContentError, "Stale state_snapshot_hash"):
            content.record_reviewed(self.repository, bundle)

    def test_wrong_path_or_blob_or_source_hash_rejected(self):
        self.page()
        original = self.status()
        good = self.bundle(original, ["ko/articles/report.html"])
        for field in ("path", "sha", "source_hash"):
            bad = copy.deepcopy(good)
            if field == "source_hash":
                bad["records"][0][field] = "f" * 64
            else:
                bad["records"][0]["outputs"][0][field] = "index.html" if field == "path" else "f" * 40
            with self.subTest(field=field), self.assertRaises(content.ContentError):
                content.record_reviewed(self.repository, bad)
        self.assertFalse((self.repository / content.STATE_PATH).exists())

    def test_duplicate_review_records_and_nonpending_rejected(self):
        self.page()
        original = self.status()
        bundle = self.bundle(original, ["ko/articles/report.html"])
        bundle["records"].append(copy.deepcopy(bundle["records"][0]))
        with self.assertRaisesRegex(content.ContentError, "Duplicate"):
            content.record_reviewed(self.repository, bundle)
        bundle["records"].pop()
        content.record_reviewed(self.repository, bundle)
        refreshed = self.status()
        bundle["state_snapshot_hash"] = refreshed["state_snapshot_hash"]
        with self.assertRaisesRegex(content.ContentError, "non-pending"):
            content.record_reviewed(self.repository, bundle)

    def test_reuse_allowed_only_for_images(self):
        self.page(body='<img src="/images/photo.png"><a href="/pdfs/report.pdf">PDF</a>')
        self.put("images/photo.png", b"image")
        self.put("pdfs/report.pdf", b"%PDF-1.7 source")
        original = self.status()
        bad = self.bundle(original, ["pdfs/report.pdf"], {"pdfs/report.pdf": "reused"})
        with self.assertRaisesRegex(content.ContentError, "nonlinguistic image"):
            content.record_reviewed(self.repository, bad)
        good = self.bundle(original, ["images/photo.png"], {"images/photo.png": "reused"})
        content.record_reviewed(self.repository, good)
        state = content.read_json(self.repository / content.STATE_PATH)
        self.assertEqual(state["items"]["images/photo.png"]["review_status"], "reviewed")
        self.assertFalse((self.repository / "images/photo.en.png").exists())

    def test_pdf_needs_real_pdf_output_and_matching_bytes(self):
        self.page(body='<a href="/pdfs/report_KOR.pdf">PDF</a>')
        self.put("pdfs/report_KOR.pdf", b"%PDF-1.7 source")
        original = self.status()
        self.put("pdfs/report_ENG.pdf", b"English text, not a PDF")
        bad = self.bundle(original, ["pdfs/report_KOR.pdf"])
        with self.assertRaisesRegex(content.ContentError, "not a PDF"):
            content.record_reviewed(self.repository, bad)
        self.put("pdfs/report_ENG.pdf", b"%PDF-1.7 English translation fixture")
        good = self.bundle(original, ["pdfs/report_KOR.pdf"])
        self.assertEqual(content.record_reviewed(self.repository, good)["recorded_count"], 1)

    def test_language_and_timestamp_validation(self):
        self.page()
        original = self.status()
        self.put("articles/report.html", self.html("ko", "not translated"))
        bad = self.bundle(original, ["ko/articles/report.html"])
        with self.assertRaisesRegex(content.ContentError, "document language"):
            content.record_reviewed(self.repository, bad)
        self.put("articles/report.html", self.html("en", "translated"))
        bad = self.bundle(original, ["ko/articles/report.html"])
        bad["records"][0]["reviewed_at"] = "2026-09-09T12:00:00"
        with self.assertRaisesRegex(content.ContentError, "time zone"):
            content.record_reviewed(self.repository, bad)

    def test_json_translation_is_parsed(self):
        self.put("data/media-videos.ko.json", '{"title":"영상"}')
        original = self.status()
        self.put("data/media-videos.en.json", '{"title":"Videos"}')
        self.assertEqual(content.record_reviewed(self.repository,
                         self.bundle(original, ["data/media-videos.ko.json"]))["recorded_count"], 1)

    def test_duplicate_json_keys_rejected(self):
        self.put("data/media-videos.ko.json", '{"title":"a","title":"b"}')
        with self.assertRaisesRegex(content.ContentError, "Duplicate JSON key"):
            self.status()

    def test_removed_source_is_reported_without_deleting_english(self):
        self.page()
        self.baseline()
        (self.repository / "ko/articles/report.html").unlink()
        report = self.status()
        self.assertEqual(report["orphaned_state_sources"], ["ko/articles/report.html"])
        self.assertTrue((self.repository / "articles/report.html").exists())

    def test_unsafe_paths_and_source_collision_rejected(self):
        for path in ["../a.pdf", "/a.pdf", "a//b.pdf", "a\\b.pdf", "C:/a.pdf", ".git/a.pdf", "a\n.pdf"]:
            with self.subTest(path=path), self.assertRaises(content.ContentError):
                content.target_for(path)
        self.page(body='<img src="/images/chart_ko.png"><img src="/images/chart_en.png">')
        self.put("images/chart_ko.png", b"Korean")
        self.put("images/chart_en.png", b"English referenced as source too")
        with self.assertRaisesRegex(content.ContentError, "source-overwriting"):
            self.status()

    def test_relative_asset_escape_rejected(self):
        self.page(body='<a href="../../../outside.pdf">PDF</a>')
        with self.assertRaisesRegex(content.ContentError, "escapes repository"):
            self.status()

    def test_symlink_source_rejected_when_supported(self):
        self.page()
        source = self.repository / "ko/articles/report.html"
        original = source.read_bytes()
        source.unlink()
        target = self.put("outside.html", original)
        try:
            source.symlink_to(target)
        except OSError:
            self.skipTest("Creating symlinks is unavailable in this Windows environment.")
        with self.assertRaisesRegex(content.ContentError, "Symlink"):
            self.status()


if __name__ == "__main__":
    unittest.main()
