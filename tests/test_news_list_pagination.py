import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NewsListPaginationTests(unittest.TestCase):
    def test_list_pages_include_bilingual_pagination_mounts_and_fresh_assets(self) -> None:
        pages = (
            (ROOT / "ko/crypto-news.html", "뉴스 목록 페이지"),
            (ROOT / "crypto-news.html", "News list pages"),
        )

        for page, label in pages:
            source = page.read_text(encoding="utf-8")
            self.assertIn("data-crypto-news-pagination", source)
            self.assertIn(f'aria-label="{label}"', source)
            self.assertIn('/style.css?v=20261012-1', source)
            self.assertIn('/js/crypto-news.js?v=20261012-1', source)

    def test_client_list_uses_twenty_items_and_page_query_navigation(self) -> None:
        source = (ROOT / "js/crypto-news.js").read_text(encoding="utf-8")

        self.assertRegex(source, r"var PAGE_SIZE = 20;")
        self.assertIn("items.slice(start, start + PAGE_SIZE)", source)
        self.assertIn("url.searchParams.set('page', String(page))", source)
        self.assertIn("window.history.pushState", source)
        self.assertIn("window.addEventListener('popstate'", source)
        self.assertIn("updateListLanguageLinks(currentPage)", source)

    def test_pagination_styles_cover_desktop_and_mobile(self) -> None:
        source = (ROOT / "style.css").read_text(encoding="utf-8")

        self.assertIn(".crypto-news-list-pagination {", source)
        self.assertIn(".crypto-news-list-pagination__pages {", source)
        self.assertRegex(
            source,
            re.compile(
                r"@media \(max-width: 740px\) \{[\s\S]*?"
                r"\.crypto-news-list-pagination \{[\s\S]*?grid-template-columns: 1fr 1fr;"
            ),
        )


if __name__ == "__main__":
    unittest.main()
