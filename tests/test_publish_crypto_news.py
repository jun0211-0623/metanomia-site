from __future__ import annotations

import base64
import gzip
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "publish_crypto_news.py"
SPEC = importlib.util.spec_from_file_location("publish_crypto_news", SCRIPT_PATH)
assert SPEC and SPEC.loader
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


def source(url: str = "https://regulator.example/releases/one") -> dict[str, str]:
    return {
        "title": "Official release",
        "publisher": "Example Regulator",
        "url": url,
    }


def kst_timestamp(*, minutes: int = 0) -> str:
    value = publisher.current_kst().replace(microsecond=0) + timedelta(minutes=minutes)
    return value.isoformat(timespec="seconds")


def item(
    source_item_id: str = "2026-09-06-01-example",
    *,
    decision: str = "approved",
    url: str = "https://regulator.example/releases/one",
) -> dict[str, object]:
    return {
        "source_item_id": source_item_id,
        "date_kst": "2026-09-06",
        "title": "검증된 기사 제목",
        "content": "검증된 기사 본문이다.",
        "metanomia_thought": "검증된 메타노미아 생각입니다.",
        "decision": decision,
        "reviewer": "검토자",
        "reviewed_at_kst": kst_timestamp(minutes=-1),
        "notes": "",
        "sources": [source(url)],
    }


def payload(items: list[dict[str, object]] | None = None) -> dict[str, object]:
    values = items if items is not None else [item()]
    result: dict[str, object] = {
        "schema_version": "1.0",
        "publish_id": "20260906-" + "0" * 24,
        "created_at_kst": kst_timestamp(),
        "production": True,
        "target_branch": "main",
        "spreadsheet_id": "1eBkr1EGZ_jLurI5i5Xm7XwCEJFshwHmNzehWtY1MKdk",
        "sheet_name": "2026-09-06",
        "date_kst": "2026-09-06",
        "expected_item_count": len(values),
        "items": values,
    }
    result["publish_id"] = publisher.expected_publish_id(result)
    return result


def manifest(items: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "generated_at_kst": "2026-09-04T10:26:00+09:00",
        "items": items or [],
    }


def english_manifest(items: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "generated_at_kst": "2026-09-04T10:26:00+09:00",
        "items": [
            {key: value for key, value in entry.items() if key != "id"}
            for entry in items
        ],
    }


def same_day_supplement() -> tuple[dict[str, object], dict[str, object]]:
    """Reproduce the September 8 batch: three public articles and two new reviews."""
    report_date = "2026-09-08"
    existing = [
        publisher.public_record(
            report_date,
            {
                **item(f"{report_date}-existing-{index}", url=f"https://archive.example/{index}"),
                "date_kst": report_date,
                "title": f"기존 공개 기사 {index}",
            },
        )
        for index in range(1, 4)
    ]
    reviewed = payload(
        [
            {
                **item(
                    "2026-09-08-01-chf-stablecoin-sandbox-test",
                    url="https://www.ubs.com/global/de/media/display-page-ndp/en-20260908-stablecoin-sandbox.html",
                ),
                "date_kst": report_date,
            },
            {
                **item(
                    "2026-09-08-02-dfsa-blockchain-scam-alert",
                    decision="rejected",
                    url="https://www.dfsa.ae/alerts/dfsa-impersonated-blockchain-settlement-scam",
                ),
                "date_kst": report_date,
            },
        ]
    )
    reviewed["sheet_name"] = reviewed["date_kst"] = report_date
    reviewed["publish_id"] = publisher.expected_publish_id(reviewed)
    return reviewed, manifest(existing)


class PublishCryptoNewsTests(unittest.TestCase):
    def test_upsert_adds_approved_item_and_keeps_publisher_private(self) -> None:
        old = publisher.public_record(
            "2026-09-04",
            {
                **item("2026-09-04-archive", url="https://archive.example/old"),
                "date_kst": "2026-09-04",
            },
        )
        next_manifest, metadata = publisher.upsert_manifest(payload(), manifest([old]))
        self.assertEqual(metadata["approved_count"], 1)
        self.assertEqual(metadata["added_count"], 1)
        self.assertEqual(len(next_manifest["items"]), 2)
        newest = next_manifest["items"][0]
        self.assertEqual(metadata["changed_slugs"], [newest["slug"]])
        self.assertEqual(newest["date_kst"], "2026-09-06")
        self.assertEqual(set(newest["sources"][0]), {"title", "url"})
        self.assertNotIn("publisher", newest["sources"][0])

    def test_upsert_updates_same_stable_public_id(self) -> None:
        original_payload = payload()
        original_record = publisher.public_record("2026-09-06", original_payload["items"][0])
        changed_item = item()
        changed_item["title"] = "수정된 기사 제목"
        changed_payload = payload([changed_item])
        next_manifest, metadata = publisher.upsert_manifest(
            changed_payload, manifest([original_record])
        )
        self.assertEqual(metadata["added_count"], 0)
        self.assertEqual(metadata["updated_count"], 1)
        self.assertEqual(next_manifest["items"][0]["id"], original_record["id"])
        self.assertEqual(next_manifest["items"][0]["title"], "수정된 기사 제목")

    def test_identical_public_record_preserves_generated_at_for_true_noop(self) -> None:
        value = payload()
        public = publisher.public_record("2026-09-06", value["items"][0])
        current = manifest([public])
        next_manifest, metadata = publisher.upsert_manifest(value, current)
        self.assertEqual(metadata["added_count"], 0)
        self.assertEqual(metadata["updated_count"], 0)
        self.assertEqual(next_manifest, current)

    def test_public_identity_is_stable_when_url_changes(self) -> None:
        first = item(url="https://regulator.example/release?id=7&utm_source=email")
        changed = item(url="https://regulator.example/corrected?id=7")
        self.assertEqual(
            publisher.public_record("2026-09-06", first)["id"],
            publisher.public_record("2026-09-06", changed)["id"],
        )
        self.assertEqual(
            publisher.normalize_url("https://www.example.com/a?id=7&utm_source=x&gclid=y"),
            "example.com/a?id=7",
        )

    def test_pending_decision_is_blocked(self) -> None:
        value = payload([item(decision="pending")])
        value["publish_id"] = publisher.expected_publish_id(value)
        with self.assertRaisesRegex(publisher.PublishValidationError, "pending reviews"):
            publisher.validate_payload(value)

    def test_zero_approved_items_is_blocked(self) -> None:
        value = payload([item(decision="rejected")])
        with self.assertRaisesRegex(publisher.PublishValidationError, "At least one"):
            publisher.validate_payload(value)

    def test_reviewer_and_explicit_kst_are_required(self) -> None:
        no_reviewer = item()
        no_reviewer["reviewer"] = ""
        value = payload([no_reviewer])
        with self.assertRaisesRegex(publisher.PublishValidationError, "reviewer"):
            publisher.validate_payload(value)

    def test_stale_future_and_boolean_count_are_blocked(self) -> None:
        stale = payload()
        stale["created_at_kst"] = kst_timestamp(minutes=-31)
        stale["publish_id"] = publisher.expected_publish_id(stale)
        with self.assertRaisesRegex(publisher.PublishValidationError, "stale"):
            publisher.validate_payload(stale)

        future_review = item()
        future_review["reviewed_at_kst"] = kst_timestamp(minutes=10)
        value = payload([future_review])
        with self.assertRaisesRegex(publisher.PublishValidationError, "later than"):
            publisher.validate_payload(value)

        boolean_count = payload()
        boolean_count["expected_item_count"] = True
        boolean_count["publish_id"] = publisher.expected_publish_id(boolean_count)
        with self.assertRaisesRegex(publisher.PublishValidationError, "not a boolean"):
            publisher.validate_payload(boolean_count)

        wrong_zone = item()
        wrong_zone["reviewed_at_kst"] = "2026-09-06T00:10:11+00:00"
        value = payload([wrong_zone])
        with self.assertRaisesRegex(publisher.PublishValidationError, "KST"):
            publisher.validate_payload(value)

    def test_http_and_discovery_only_sources_are_blocked(self) -> None:
        insecure = payload([item(url="http://regulator.example/release")])
        with self.assertRaisesRegex(publisher.PublishValidationError, "HTTPS"):
            publisher.validate_payload(insecure)

        discovery = payload([item(url="https://coinness.com/news/123")])
        with self.assertRaisesRegex(publisher.PublishValidationError, "discovery-only"):
            publisher.validate_payload(discovery)

    def test_duplicate_source_item_and_public_identity_are_blocked(self) -> None:
        duplicate_source_id = payload(
            [
                item("same", url="https://a.example/one"),
                item("same", url="https://b.example/two"),
            ]
        )
        with self.assertRaisesRegex(publisher.PublishValidationError, "Duplicate source_item_id"):
            publisher.validate_payload(duplicate_source_id)

        duplicate_public_id = payload(
            [
                item("one", url="https://a.example/one"),
                item("two", url="https://a.example/one"),
            ]
        )
        with self.assertRaisesRegex(publisher.PublishValidationError, "canonical primary source"):
            publisher.upsert_manifest(duplicate_public_id, manifest())

    def test_cross_date_source_or_source_item_id_collision_is_blocked(self) -> None:
        old_item = item("global-id", url="https://regulator.example/release?utm_source=old&id=7")
        old_item["date_kst"] = "2026-09-05"
        old_record = publisher.public_record("2026-09-05", old_item)

        reused_id = payload([item("global-id", url="https://another.example/release")])
        with self.assertRaisesRegex(publisher.PublishValidationError, "another date"):
            publisher.upsert_manifest(reused_id, manifest([old_record]))

        same_source = payload(
            [item("different-id", url="https://regulator.example/release?id=7&utm_medium=mail")]
        )
        with self.assertRaisesRegex(publisher.PublishValidationError, "already published"):
            publisher.upsert_manifest(same_source, manifest([old_record]))

    def test_rejected_historical_duplicate_does_not_block_other_approval(self) -> None:
        old_item = item("old-id", url="https://regulator.example/already-published")
        old_item["date_kst"] = "2026-09-05"
        old_record = publisher.public_record("2026-09-05", old_item)
        reviewed = payload(
            [
                item(
                    "rejected-duplicate",
                    decision="rejected",
                    url="https://regulator.example/already-published?utm_source=feed",
                ),
                item("new-approved", url="https://regulator.example/new-release"),
            ]
        )
        next_manifest, metadata = publisher.upsert_manifest(reviewed, manifest([old_record]))
        self.assertEqual(metadata["approved_count"], 1)
        self.assertEqual(metadata["added_count"], 1)
        self.assertEqual(len(next_manifest["items"]), 2)

    def test_explicitly_rejected_existing_date_item_cannot_be_deleted(self) -> None:
        approved_payload = payload()
        public = publisher.public_record("2026-09-06", approved_payload["items"][0])

        rejected_payload = payload(
            [
                item(decision="rejected"),
                item("new-approved", url="https://regulator.example/releases/new"),
            ]
        )
        with self.assertRaisesRegex(publisher.PublishValidationError, "automatic deletion"):
            publisher.upsert_manifest(rejected_payload, manifest([public]))

    def test_omitted_existing_date_item_is_preserved(self) -> None:
        public = publisher.public_record("2026-09-06", item())
        different_item = item("different", url="https://regulator.example/releases/different")
        different_payload = payload([different_item])
        next_manifest, metadata = publisher.upsert_manifest(different_payload, manifest([public]))
        self.assertEqual(metadata["added_count"], 1)
        self.assertEqual(metadata["updated_count"], 0)
        self.assertIn(public, next_manifest["items"])
        self.assertEqual(len(next_manifest["items"]), 2)

    def test_same_day_supplement_cannot_duplicate_omitted_article_source(self) -> None:
        existing = publisher.public_record(
            "2026-09-06", item("existing-id", url="https://regulator.example/release?id=7")
        )
        duplicate = payload(
            [item("new-id", url="https://regulator.example/release?id=7&utm_source=feed")]
        )
        with self.assertRaisesRegex(publisher.PublishValidationError, "another article id on this date"):
            publisher.upsert_manifest(duplicate, manifest([existing]))

    def test_partial_same_day_update_preserves_legacy_public_identity(self) -> None:
        legacy_item = item()
        legacy = publisher.public_record("2026-09-06", legacy_item)
        legacy["id"], legacy["slug"] = publisher.legacy_public_identity("2026-09-06", legacy_item)
        omitted = publisher.public_record(
            "2026-09-06", item("omitted", url="https://archive.example/omitted")
        )
        legacy_item["title"] = "기존 URL 기반 기사의 수정 제목"
        next_manifest, metadata = publisher.upsert_manifest(
            payload([legacy_item]), manifest([legacy, omitted])
        )
        self.assertEqual(metadata["added_count"], 0)
        self.assertEqual(metadata["updated_count"], 1)
        self.assertEqual(metadata["changed_slugs"], [legacy["slug"]])
        self.assertIn(omitted, next_manifest["items"])
        updated = next(record for record in next_manifest["items"] if record["id"] == legacy["id"])
        self.assertEqual(updated["slug"], legacy["slug"])
        self.assertEqual(updated["title"], legacy_item["title"])

    def test_same_day_two_review_batch_preserves_three_existing_articles(self) -> None:
        reviewed, current = same_day_supplement()
        before = publisher.canonical_json(current).encode("utf-8")
        next_manifest, metadata = publisher.upsert_manifest(reviewed, current)
        self.assertEqual(metadata["approved_count"], 1)
        self.assertEqual(metadata["added_count"], 1)
        self.assertEqual(metadata["updated_count"], 0)
        self.assertEqual(metadata["item_count"], 4)
        next_by_id = {record["id"]: record for record in next_manifest["items"]}
        for existing in current["items"]:
            self.assertEqual(
                publisher.canonical_json(next_by_id[existing["id"]]).encode("utf-8"),
                publisher.canonical_json(existing).encode("utf-8"),
            )
        approved = publisher.public_record("2026-09-08", reviewed["items"][0])
        rejected = publisher.public_record("2026-09-08", reviewed["items"][1])
        self.assertEqual(next_by_id[approved["id"]], approved)
        self.assertNotIn(rejected["id"], next_by_id)
        self.assertEqual(metadata["changed_slugs"], [approved["slug"]])
        self.assertEqual(publisher.canonical_json(current).encode("utf-8"), before)

    def test_repeated_same_day_supplement_is_byte_equivalent_noop(self) -> None:
        reviewed, current = same_day_supplement()
        first, _ = publisher.upsert_manifest(reviewed, current)
        repeated, metadata = publisher.upsert_manifest(reviewed, first)
        self.assertEqual(metadata["added_count"], 0)
        self.assertEqual(metadata["updated_count"], 0)
        self.assertEqual(metadata["changed_slugs"], [])
        self.assertEqual(
            publisher.canonical_json(repeated).encode("utf-8"),
            publisher.canonical_json(first).encode("utf-8"),
        )

    def test_partial_same_day_update_preserves_omitted_article(self) -> None:
        original = publisher.public_record("2026-09-06", item())
        omitted = publisher.public_record(
            "2026-09-06", item("omitted", url="https://archive.example/omitted")
        )
        changed = item()
        changed["title"] = "수정된 기사 제목"
        next_manifest, metadata = publisher.upsert_manifest(
            payload([changed]), manifest([original, omitted])
        )
        self.assertEqual(metadata["added_count"], 0)
        self.assertEqual(metadata["updated_count"], 1)
        self.assertIn(omitted, next_manifest["items"])
        self.assertEqual(len(next_manifest["items"]), 2)
        self.assertEqual(
            next(record for record in next_manifest["items"] if record["id"] == original["id"])["title"],
            "수정된 기사 제목",
        )

    def test_manifest_duplicate_id_or_slug_is_blocked(self) -> None:
        public = publisher.public_record("2026-09-06", item())
        with self.assertRaisesRegex(publisher.PublishValidationError, "duplicate id or slug"):
            publisher.validate_manifest(manifest([public, dict(public)]))

    def test_production_and_publish_digest_are_explicit(self) -> None:
        not_production = payload()
        not_production["production"] = False
        not_production["publish_id"] = publisher.expected_publish_id(not_production)
        with self.assertRaisesRegex(publisher.PublishValidationError, "Production"):
            publisher.validate_payload(not_production)

        bad_digest = payload()
        bad_digest["publish_id"] = "20260906-" + "f" * 24
        with self.assertRaisesRegex(publisher.PublishValidationError, "canonical payload"):
            publisher.validate_payload(bad_digest)

    def test_decode_checks_transport_sha256(self) -> None:
        value = payload()
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        encoded = base64.b64encode(gzip.compress(raw, mtime=0)).decode("ascii")
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "payload.json"
            args = type("Args", (), {"output": output})()
            with patch.dict(
                os.environ,
                {
                    "PUBLISH_PAYLOAD_GZIP_BASE64": encoded,
                    "PUBLISH_PAYLOAD_SHA256": hashlib.sha256(raw).hexdigest(),
                },
                clear=False,
            ):
                publisher.command_decode(args)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), value)

            with patch.dict(
                os.environ,
                {
                    "PUBLISH_PAYLOAD_GZIP_BASE64": encoded,
                    "PUBLISH_PAYLOAD_SHA256": "0" * 64,
                },
                clear=False,
            ):
                with self.assertRaisesRegex(publisher.PublishValidationError, "does not match"):
                    publisher.command_decode(args)

    def test_decode_rejects_oversized_encoded_input(self) -> None:
        args = type("Args", (), {"output": Path("unused.json")})()
        with patch.object(publisher, "MAX_ENCODED_PAYLOAD_CHARS", 10):
            with patch.dict(
                os.environ,
                {
                    "PUBLISH_PAYLOAD_GZIP_BASE64": "A" * 11,
                    "PUBLISH_PAYLOAD_SHA256": "0" * 64,
                },
                clear=False,
            ):
                with self.assertRaisesRegex(publisher.PublishValidationError, "60,000"):
                    publisher.command_decode(args)

    def test_decode_allows_structurally_valid_stale_replay_but_prepare_blocks_it(self) -> None:
        old_item = item()
        old_item["reviewed_at_kst"] = kst_timestamp(minutes=-32)
        value = payload([old_item])
        value["created_at_kst"] = kst_timestamp(minutes=-31)
        value["publish_id"] = publisher.expected_publish_id(value)
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        encoded = base64.b64encode(gzip.compress(raw, mtime=0)).decode("ascii")
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "payload.json"
            args = type("Args", (), {"output": output, "github_output": None})()
            with patch.dict(
                os.environ,
                {
                    "PUBLISH_PAYLOAD_GZIP_BASE64": encoded,
                    "PUBLISH_PAYLOAD_SHA256": hashlib.sha256(raw).hexdigest(),
                },
                clear=False,
            ):
                publisher.command_decode(args)
            with self.assertRaisesRegex(publisher.PublishValidationError, "stale"):
                publisher.upsert_manifest(value, manifest())

    def test_replay_detection_is_scoped_to_origin_main_and_allowlist(self) -> None:
        commit = "a" * 40

        def fake_git(_repository: Path, args: list[str]) -> str:
            if args[0] == "log":
                self.assertEqual(args[1], "origin/main")
                self.assertIn("--first-parent", args)
                return commit
            if args[0] == "diff-tree":
                return (
                    "M\tdata/crypto-news.json\n"
                    "A\tko/crypto-news-2026-09-06-crypto-news-0123456789.html"
                )
            raise AssertionError(args)

        with patch.object(publisher, "run_git", side_effect=fake_git):
            self.assertEqual(
                publisher.find_applied_publish_id(Path("."), payload()["publish_id"]), commit
            )

        with patch.object(
            publisher,
            "run_git",
            side_effect=[commit, "M\tdata/crypto-news.json\nA\tscripts/unexpected.py"],
        ):
            with self.assertRaisesRegex(publisher.PublishValidationError, "allowlist"):
                publisher.find_applied_publish_id(Path("."), payload()["publish_id"])

    def test_no_change_is_a_valid_guard_result(self) -> None:
        with patch.object(publisher, "run_git", return_value=""):
            self.assertEqual(publisher.guard_worktree(Path(".")), [])

    def test_delete_or_rename_is_blocked_even_inside_allowlist(self) -> None:
        with self.assertRaisesRegex(publisher.PublishValidationError, "deletion"):
            publisher.parse_safe_name_status("D\tdata/crypto-news.json", "test")
        with self.assertRaisesRegex(publisher.PublishValidationError, "rename"):
            publisher.parse_safe_name_status(
                "R100\tko/crypto-news-2026-09-06-crypto-news-0123456789.html\t"
                "ko/crypto-news-2026-09-06-crypto-news-abcdef0123.html",
                "test",
            )

    def test_korean_phase_allows_pending_english_but_bilingual_check_does_not(self) -> None:
        public = publisher.public_record("2026-09-06", item())
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            publisher.atomic_write_json(root / "data/crypto-news.json", manifest([public]))
            publisher.atomic_write_json(root / "data/crypto-news.en.json", english_manifest([]))
            with self.assertRaisesRegex(publisher.PublishValidationError, "pages are missing"):
                publisher.verify_korean_pages(root)
            page = root / "ko" / f"crypto-news-{public['slug']}.html"
            page.parent.mkdir(parents=True)
            page.write_text("<!doctype html>", encoding="utf-8")
            publisher.verify_korean_pages(root)
            with self.assertRaisesRegex(publisher.PublishValidationError, "slug order"):
                publisher.verify_static_pages(root)

    def test_korean_phase_rejects_orphaned_or_missing_existing_english_pages(self) -> None:
        public = publisher.public_record("2026-09-06", item())
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            publisher.atomic_write_json(root / "data/crypto-news.json", manifest([]))
            publisher.atomic_write_json(root / "data/crypto-news.en.json", english_manifest([public]))
            with self.assertRaisesRegex(publisher.PublishValidationError, "English-only"):
                publisher.verify_korean_pages(root)
            publisher.atomic_write_json(root / "data/crypto-news.json", manifest([public]))
            page = root / "ko" / f"crypto-news-{public['slug']}.html"
            page.parent.mkdir(parents=True)
            page.write_text("<!doctype html>", encoding="utf-8")
            with self.assertRaisesRegex(publisher.PublishValidationError, "pages are missing"):
                publisher.verify_korean_pages(root)

    def test_every_manifest_slug_requires_a_korean_static_page(self) -> None:
        public = publisher.public_record("2026-09-06", item())
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            publisher.atomic_write_json(root / "data/crypto-news.json", manifest([public]))
            publisher.atomic_write_json(
                root / "data/crypto-news.en.json", english_manifest([public])
            )
            with self.assertRaisesRegex(publisher.PublishValidationError, "pages are missing"):
                publisher.verify_static_pages(root)
            ko_page = root / "ko" / f"crypto-news-{public['slug']}.html"
            en_page = root / f"crypto-news-{public['slug']}.html"
            ko_page.parent.mkdir(parents=True)
            ko_page.write_text("<!doctype html>", encoding="utf-8")
            en_page.write_text("<!doctype html>", encoding="utf-8")
            publisher.verify_static_pages(root)


if __name__ == "__main__":
    unittest.main()
