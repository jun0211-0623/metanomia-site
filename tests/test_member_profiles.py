import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NEW_PROFILE_SLUGS = {
    "choi-deok-hyun",
    "dk-kwon",
    "do-gyun-kim",
    "june-ho-cho",
    "junseok-kwon",
    "lee-jong-beom",
    "simin-kim",
    "sunwoo-hoon",
}
PHONE_PATTERN = re.compile(
    r'(?:href=["\']tel:|(?:\+?82[- .]?)?01[016789][- .]?\d{3,4}[- .]?\d{4})',
    re.IGNORECASE,
)


class MemberProfileTests(unittest.TestCase):
    def test_new_profiles_exist_in_both_languages(self):
        for slug in NEW_PROFILE_SLUGS:
            self.assertTrue((ROOT / "people" / f"{slug}.html").is_file(), slug)
            self.assertTrue((ROOT / "ko" / "people" / f"{slug}.html").is_file(), slug)

    def test_every_member_card_links_to_a_profile(self):
        for page, prefix in ((ROOT / "members.html", "/people/"), (ROOT / "ko" / "members.html", "/ko/people/")):
            html = page.read_text(encoding="utf-8")
            links = re.findall(r'class="person__profile" href="([^"]+)"', html)
            self.assertEqual(36, len(links), page)
            for link in links:
                self.assertTrue(link.startswith(prefix), link)
                relative = link.removeprefix("/") + ".html"
                self.assertTrue((ROOT / relative).is_file(), link)

    def test_member_pages_do_not_publish_phone_numbers(self):
        pages = [ROOT / "members.html", ROOT / "ko" / "members.html"]
        pages.extend((ROOT / "people").glob("*.html"))
        pages.extend((ROOT / "ko" / "people").glob("*.html"))
        for page in pages:
            html = page.read_text(encoding="utf-8")
            self.assertIsNone(PHONE_PATTERN.search(html), page)

    def test_internal_roster_fields_are_not_labeled_on_profiles(self):
        pages = list((ROOT / "people").glob("*.html")) + list((ROOT / "ko" / "people").glob("*.html"))
        for page in pages:
            html = page.read_text(encoding="utf-8")
            self.assertNotIn("모빅 주소", html, page)
            self.assertNotIn("Mobick address", html, page)


if __name__ == "__main__":
    unittest.main()
