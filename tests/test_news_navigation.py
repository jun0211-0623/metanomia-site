import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NAV_RE = re.compile(r'<nav class="crypto-news-pagination"[\s\S]*?</nav>')
LINK_RE = re.compile(
    r'<a class="crypto-news-pagination__link crypto-news-pagination__link--(previous|next)" href="([^"]+)"'
)


def clean(value: object) -> str:
    return str(value or "").strip()


def ordered_items(manifest_path: Path) -> list[dict]:
    items = json.loads(manifest_path.read_text(encoding="utf-8")).get("items", [])
    items = [
        item
        for item in items
        if clean(item.get("slug")) and clean(item.get("title")) and clean(item.get("content"))
    ]
    items.sort(key=lambda item: clean(item.get("slug")))
    items.sort(key=lambda item: clean(item.get("date_kst")), reverse=True)
    return items


class NewsNavigationTests(unittest.TestCase):
    def test_static_detail_navigation_matches_news_list_order(self) -> None:
        languages = (
            ("ko", ROOT / "data/crypto-news.json", ROOT / "ko", "/ko/"),
            ("en", ROOT / "data/crypto-news.en.json", ROOT, "/"),
        )

        for language, manifest_path, page_dir, url_prefix in languages:
            items = ordered_items(manifest_path)
            for index, item in enumerate(items):
                slug = clean(item["slug"])
                page_path = page_dir / f"crypto-news-{slug}.html"
                page = page_path.read_text(encoding="utf-8")
                navigation = NAV_RE.search(page)
                self.assertIsNotNone(navigation, f"{language}: navigation missing in {page_path.name}")
                actual = dict(LINK_RE.findall(navigation.group(0)))

                expected = {}
                if index + 1 < len(items):
                    expected["previous"] = url_prefix + "crypto-news-" + clean(items[index + 1]["slug"])
                if index > 0:
                    expected["next"] = url_prefix + "crypto-news-" + clean(items[index - 1]["slug"])

                self.assertEqual(
                    expected,
                    actual,
                    f"{language}: navigation does not match list order for {slug}",
                )


if __name__ == "__main__":
    unittest.main()
