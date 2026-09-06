from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "translate-news.py"
SPEC = importlib.util.spec_from_file_location("translate_news", SCRIPT_PATH)
assert SPEC and SPEC.loader
translator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(translator)


class TranslateNewsSelectionTests(unittest.TestCase):
    def test_required_existing_slug_is_retranslated(self) -> None:
        ko = [{"slug": "same"}, {"slug": "new"}]
        en = [{"slug": "same", "title": "stale"}]
        done, pending = translator.select_pending(ko, en, required={"same"})
        self.assertEqual(set(done), {"same"})
        self.assertEqual([item["slug"] for item in pending], ["same", "new"])

    def test_unchanged_existing_slug_is_not_retranslated(self) -> None:
        ko = [{"slug": "same"}]
        en = [{"slug": "same", "title": "current"}]
        _done, pending = translator.select_pending(ko, en)
        self.assertEqual(pending, [])

    def test_english_only_slug_cannot_be_deleted(self) -> None:
        with self.assertRaisesRegex(ValueError, "automatic deletion is forbidden"):
            translator.assert_no_english_only_slugs(
                [{"slug": "korean"}],
                [{"slug": "korean"}, {"slug": "english-only"}],
            )

    def test_required_slug_file_rejects_unknown_or_invalid_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "metadata.json"
            path.write_text(json.dumps({"changed_slugs": ["unknown"]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown slug"):
                translator.required_slugs(path, ["known"])
            path.write_text(json.dumps({"changed_slugs": "known"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "string array"):
                translator.required_slugs(path, ["known"])


if __name__ == "__main__":
    unittest.main()
