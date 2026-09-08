from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "codex-news-translation.py"
SPEC = importlib.util.spec_from_file_location("codex_news_translation", SCRIPT_PATH)
assert SPEC and SPEC.loader
translator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(translator)


def article(number=1):
    return {
        "id": f"crypto-news-{number:016x}",
        "slug": f"2026-09-08-crypto-news-{number:010x}",
        "date_kst": "2026-09-08",
        "title": f"검증된 기사 {number}",
        "content": "거래는 9월 5일 시험 범위에서 완료됐다.\n\n금액은 공개하지 않았다.",
        "metanomia_thought": "시험의 범위를 구분해서 읽을 필요가 있습니다.",
        "sources": [
            {"title": "Official release", "url": "https://bank.example/release"},
            {"title": "Independent report", "url": "https://news.example/article"},
        ],
    }


def manifest(items):
    return {"schema_version": "1.0", "generated_at_kst": "2026-09-08T10:00:00+09:00", "items": items}


def english(item):
    return {
        "slug": item["slug"], "date_kst": item["date_kst"],
        "title": "Banks completed a payment trial",
        "content": "The payment was completed on September 5 within the trial.\n\nThe amount was not disclosed.",
        "metanomia_thought": "The scope of the trial needs to remain clear.",
        "sources": copy.deepcopy(item["sources"]),
    }


class CodexNewsTranslationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repository = Path(temp.name)
        self.ko_path = self.repository / translator.KO_RELATIVE
        self.en_path = self.repository / translator.EN_RELATIVE
        self.state_path = self.repository / translator.STATE_RELATIVE
        self.ko = manifest([article()])
        self.save(self.ko_path, self.ko)

    def save(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")

    def files(self):
        return {path.relative_to(self.repository).as_posix(): path.read_bytes()
                for path in self.repository.rglob("*") if path.is_file()}

    def bundle(self):
        report = translator.status(self.repository)
        return {
            "schema_version": "1.0",
            **{field: report[field] for field in translator.SNAPSHOT_FIELDS},
            "translations": [{
                "slug": item["slug"], "source_hash": item["source_hash"],
                "title": "Banks completed a payment trial",
                "content": "The payment was completed on September 5 within the trial.\n\nThe amount was not disclosed.",
                "metanomia_thought": "The scope of the trial needs to remain clear.",
            } for item in report["pending"]],
        }

    def apply(self):
        translator.apply_bundle(self.repository, self.bundle())

    def assert_rejected_without_writes(self, bundle, message):
        before = self.files()
        with self.assertRaisesRegex(translator.ValidationError, message):
            translator.apply_bundle(self.repository, bundle)
        self.assertEqual(self.files(), before)

    def test_missing_english_and_state_are_pending_without_writes(self):
        before = self.files()
        report = translator.status(self.repository)
        self.assertEqual(report["pending_count"], 1)
        self.assertEqual(report["pending"][0]["reasons"], ["missing_english", "missing_state"])
        self.assertTrue(report["needs_sync"])
        self.assertEqual(self.files(), before)

    def test_unchanged_translation_is_byte_preserving_noop(self):
        self.apply()
        self.assertFalse(translator.status(self.repository)["needs_work"])
        before = self.files()
        result = translator.apply_bundle(self.repository, self.bundle())
        self.assertEqual(result["written"], [])
        self.assertEqual(result["translated_count"], 0)
        self.assertEqual(self.files(), before)

    def test_existing_english_without_state_is_not_implicitly_trusted(self):
        self.save(self.en_path, manifest([english(self.ko["items"][0])]))
        self.assertEqual(translator.status(self.repository)["pending"][0]["reasons"], ["missing_state"])

    def test_all_source_fields_and_source_order_trigger_review(self):
        self.apply()
        mutations = [
            ("title", "수정된 제목"), ("content", "수정된 본문"),
            ("metanomia_thought", "수정된 생각입니다."), ("date_kst", "2026-09-07"),
            ("sources", list(reversed(self.ko["items"][0]["sources"]))),
            ("sources", [{"title": "Correction", "url": "https://bank.example/correction"}]),
        ]
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(self.ko)
                changed["items"][0][field] = value
                self.save(self.ko_path, changed)
                pending = translator.status(self.repository)["pending"]
                self.assertEqual(len(pending), 1)
                self.assertIn("source_changed", pending[0]["reasons"])
        self.save(self.ko_path, self.ko)
        self.assertFalse(translator.status(self.repository)["needs_work"])

    def test_english_edit_requires_review_and_explicit_acceptance(self):
        self.apply()
        en = translator.read_json(self.en_path)
        en["items"][0]["content"] = "An independently edited English paragraph."
        self.save(self.en_path, en)
        self.assertEqual(translator.status(self.repository)["pending"][0]["reasons"], ["english_changed"])
        bundle = self.bundle()
        bundle["translations"][0]["content"] = en["items"][0]["content"]
        translator.apply_bundle(self.repository, bundle)
        self.assertFalse(translator.status(self.repository)["needs_work"])
        self.assertEqual(translator.read_json(self.en_path)["items"][0]["content"], en["items"][0]["content"])

    def test_preserves_existing_articles_and_korean_sources_dates_order(self):
        self.apply()
        existing = translator.read_json(self.en_path)["items"][0]
        self.ko["items"].insert(0, article(2))
        self.ko["items"][0]["sources"].reverse()
        self.ko["items"][0]["date_kst"] = "2026-09-07"
        self.ko["generated_at_kst"] = "2026-09-08T11:00:00+09:00"
        self.save(self.ko_path, self.ko)
        original_ko = self.ko_path.read_bytes()
        self.apply()
        en = translator.read_json(self.en_path)
        self.assertEqual(en["items"][1], existing)
        self.assertEqual(self.ko_path.read_bytes(), original_ko)
        self.assertEqual([i["slug"] for i in en["items"]], [i["slug"] for i in self.ko["items"]])
        for original, translated in zip(self.ko["items"], en["items"]):
            self.assertEqual(translated["sources"], original["sources"])
            self.assertEqual(translated["date_kst"], original["date_kst"])
            self.assertEqual(set(translated), translator.publisher.ENGLISH_ITEM_FIELDS)
        self.assertEqual(en["generated_at_kst"], self.ko["generated_at_kst"])

    def test_metadata_only_sync_needs_no_translation(self):
        self.ko["items"].append(article(2))
        self.save(self.ko_path, self.ko)
        self.apply()
        state_before = self.state_path.read_bytes()
        self.ko["items"].reverse()
        self.ko["generated_at_kst"] = "2026-09-08T11:00:00+09:00"
        self.save(self.ko_path, self.ko)
        report = translator.status(self.repository)
        self.assertEqual(report["pending_count"], 0)
        self.assertTrue(report["needs_sync"])
        bundle = self.bundle()
        self.assertEqual(bundle["translations"], [])
        translator.apply_bundle(self.repository, bundle)
        self.assertFalse(translator.status(self.repository)["needs_work"])
        self.assertEqual(self.state_path.read_bytes(), state_before)

    def test_bundle_order_does_not_change_korean_article_order(self):
        self.ko["items"].append(article(2))
        self.save(self.ko_path, self.ko)
        bundle = self.bundle()
        bundle["translations"].reverse()
        translator.apply_bundle(self.repository, bundle)
        self.assertEqual(
            [i["slug"] for i in translator.read_json(self.en_path)["items"]],
            [i["slug"] for i in self.ko["items"]]
        )

    def test_wrong_per_article_hash_rejected_without_writes(self):
        bundle = self.bundle()
        bundle["translations"][0]["source_hash"] = "0" * 64
        self.assert_rejected_without_writes(bundle, "Wrong source_hash")

    def test_source_snapshot_changes_include_metadata_and_new_articles(self):
        for kind in ("metadata", "new_article"):
            with self.subTest(kind=kind):
                bundle = self.bundle()
                changed = copy.deepcopy(self.ko)
                if kind == "metadata":
                    changed["generated_at_kst"] = "2026-09-08T11:00:00+09:00"
                else:
                    changed["items"].append(article(2))
                self.save(self.ko_path, changed)
                self.assert_rejected_without_writes(bundle, "source_snapshot_hash is stale")
                self.save(self.ko_path, self.ko)

    def test_english_or_state_changes_after_status_invalidate_bundle(self):
        for target in ("english", "state"):
            with self.subTest(target=target):
                bundle = self.bundle()
                path = self.en_path if target == "english" else self.state_path
                value = manifest([english(self.ko["items"][0])]) if target == "english" else {
                    "schema_version": "1.0", "items": {}
                }
                self.save(path, value)
                self.assert_rejected_without_writes(bundle, f"{target}_snapshot_hash is stale")
                path.unlink()

    def test_all_pending_validate_before_any_output_write(self):
        self.ko["items"].append(article(2))
        self.save(self.ko_path, self.ko)
        bundle = self.bundle()
        bundle["translations"][1]["content"] = " \n "
        self.assert_rejected_without_writes(bundle, "non-empty")
        self.assertFalse(self.en_path.exists())
        self.assertFalse(self.state_path.exists())

    def test_missing_extra_duplicate_empty_and_invalid_bundle_fields(self):
        for kind in ("missing", "extra", "duplicate", "extra_field", "missing_field",
                     "empty_field", "bad_hash", "top_extra", "top_missing", "wrong_version"):
            with self.subTest(kind=kind):
                bundle = self.bundle()
                if kind == "missing":
                    bundle["translations"] = []
                    error = "missing pending"
                elif kind == "extra":
                    extra = copy.deepcopy(bundle["translations"][0])
                    extra["slug"] = article(2)["slug"]
                    bundle["translations"].append(extra)
                    error = "Unexpected translation slug"
                elif kind == "duplicate":
                    bundle["translations"].append(copy.deepcopy(bundle["translations"][0]))
                    error = "Duplicate translation"
                elif kind == "extra_field":
                    bundle["translations"][0]["sources"] = []
                    error = "fields do not match"
                elif kind == "missing_field":
                    del bundle["translations"][0]["title"]
                    error = "fields do not match"
                elif kind == "empty_field":
                    bundle["translations"][0]["metanomia_thought"] = ""
                    error = "non-empty"
                elif kind == "bad_hash":
                    bundle["translations"][0]["source_hash"] = "not-a-hash"
                    error = "SHA-256"
                elif kind == "top_extra":
                    bundle["anything"] = True
                    error = "fields do not match"
                elif kind == "top_missing":
                    del bundle["source_snapshot_hash"]
                    error = "fields do not match"
                else:
                    bundle["schema_version"] = "2.0"
                    error = "schema_version"
                self.assert_rejected_without_writes(bundle, error)

    def test_reviewed_slug_cannot_be_overwritten_by_bundle(self):
        self.apply()
        bundle = self.bundle()
        bundle["translations"] = [{
            "slug": article()["slug"], "source_hash": translator.source_hash(article()),
            "title": "Replacement", "content": "Replacement", "metanomia_thought": "Replacement"
        }]
        self.assert_rejected_without_writes(bundle, "not pending")

    def test_english_only_slug_is_never_deleted(self):
        bundle = self.bundle()
        self.save(self.en_path, manifest([english(article(2))]))
        before = self.files()
        with self.assertRaisesRegex(translator.ValidationError, "automatic deletion is forbidden"):
            translator.status(self.repository)
        self.assert_rejected_without_writes(bundle, "automatic deletion is forbidden")
        self.assertEqual(before, self.files())

    def test_duplicate_json_keys_and_null_manifests_rejected(self):
        with self.assertRaisesRegex(translator.ValidationError, "duplicate object key"):
            translator.parse_json('{"translations":[],"translations":[]}', "bundle")
        for path in (self.en_path, self.state_path):
            self.save(path, None)
            with self.assertRaisesRegex(translator.ValidationError, "JSON object"):
                translator.status(self.repository)
            path.unlink()

    def test_change_during_validation_stops_before_output_write(self):
        bundle = self.bundle()
        loader = translator.load_snapshot
        calls = 0

        def changed_snapshot(repository):
            nonlocal calls
            calls += 1
            value = loader(repository)
            if calls == 2:
                value["source_snapshot_hash"] = "0" * 64
            return value

        with patch.object(translator, "load_snapshot", side_effect=changed_snapshot):
            self.assert_rejected_without_writes(bundle, "changed during validation")

    def test_output_replacement_failure_restores_english_and_state(self):
        self.apply()
        self.ko["items"][0]["content"] = "원문이 수정되었습니다."
        self.save(self.ko_path, self.ko)
        bundle = self.bundle()
        bundle["translations"][0]["content"] = "The source has been corrected."
        before = self.files()
        replace = translator.os.replace
        calls = 0

        def fail_state(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated state replacement failure")
            return replace(source, destination)

        with patch.object(translator.os, "replace", side_effect=fail_state):
            with self.assertRaisesRegex(OSError, "simulated"):
                translator.apply_bundle(self.repository, bundle)
        self.assertEqual(self.files(), before)

    def test_bootstrap_only_seeds_pairs_unchanged_from_explicit_baseline(self):
        baseline_ko = manifest([article(number) for number in range(1, 5)])
        baseline_en = manifest([english(item) for item in baseline_ko["items"]])
        self.ko = copy.deepcopy(baseline_ko)
        self.ko["items"][1]["title"] = "현재 한국어 제목 수정"
        self.ko["items"].append(article(5))
        current_en = copy.deepcopy(baseline_en)
        current_en["items"][2]["title"] = "Current English title correction"
        baseline_en["items"][3]["sources"].reverse()
        current_en["items"][3]["sources"].reverse()
        self.save(self.ko_path, self.ko)
        self.save(self.en_path, current_en)
        before_ko, before_en = self.ko_path.read_bytes(), self.en_path.read_bytes()
        commit = "a" * 40

        def git_read(repository, args):
            self.assertEqual(repository, self.repository)
            if args[0] == "rev-parse":
                self.assertEqual(args, ["rev-parse", "--verify", "--end-of-options", "baseline^{commit}"])
                return commit
            return json.dumps(baseline_ko if args[1].endswith(":data/crypto-news.json") else baseline_en)

        with patch.object(translator.publisher, "run_git", side_effect=git_read):
            result = translator.bootstrap(self.repository, "baseline")
            self.assertEqual(result["seeded"], [article(1)["slug"]])
            self.assertEqual(result["pending_count"], 4)
            state_before = self.state_path.read_bytes()
            again = translator.bootstrap(self.repository, "baseline")
            self.assertEqual(again["written"], [])
            self.assertEqual(self.state_path.read_bytes(), state_before)
        self.assertEqual(self.ko_path.read_bytes(), before_ko)
        self.assertEqual(self.en_path.read_bytes(), before_en)

    def test_bootstrap_never_overwrites_existing_stale_review_record(self):
        self.apply()
        baseline_en = translator.read_json(self.en_path)
        state = translator.read_json(self.state_path)
        state["items"][article()["slug"]]["source_hash"] = "0" * 64
        self.save(self.state_path, state)
        before = self.files()
        with patch.object(translator.publisher, "run_git", side_effect=[
            "a" * 40, json.dumps(self.ko), json.dumps(baseline_en)
        ]):
            result = translator.bootstrap(self.repository, "baseline")
        self.assertEqual(result["seeded_count"], 0)
        self.assertEqual(result["pending_count"], 1)
        self.assertEqual(self.files(), before)

    def test_verify_requires_review_synced_metadata_and_bilingual_pages(self):
        with self.assertRaisesRegex(translator.ValidationError, "not ready"):
            translator.verify(self.repository)
        self.apply()
        with self.assertRaisesRegex(translator.ValidationError, "pages are missing"):
            translator.verify(self.repository)
        slug = article()["slug"]
        for prefix in (self.repository, self.repository / "ko"):
            prefix.mkdir(exist_ok=True)
            (prefix / f"crypto-news-{slug}.html").write_text("<html></html>", encoding="utf-8")
        self.assertTrue(translator.verify(self.repository)["verified"])
        self.ko["generated_at_kst"] = "2026-09-08T11:00:00+09:00"
        self.save(self.ko_path, self.ko)
        with self.assertRaisesRegex(translator.ValidationError, "not ready"):
            translator.verify(self.repository)

    def test_cli_status_output_apply_and_protected_output_path(self):
        output = self.repository / "temporary-status.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(translator.main([
                "--repository", str(self.repository), "status", "--output", str(output)
            ]), 0)
        self.assertEqual(translator.read_json(output)["pending_count"], 1)
        bundle_path = self.repository / "bundle.json"
        self.save(bundle_path, self.bundle())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(translator.main([
                "--repository", str(self.repository), "apply", "--bundle", str(bundle_path)
            ]), 0)
        self.assertFalse(translator.status(self.repository)["needs_work"])
        before = self.files()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(translator.main([
                "--repository", str(self.repository), "status", "--output", str(self.ko_path)
            ]), 1)
        self.assertEqual(self.files(), before)


if __name__ == "__main__":
    unittest.main()
