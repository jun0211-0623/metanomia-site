#!/usr/bin/env python3
"""Static integrity audit for the Metanomia site."""
from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.refs: list[tuple[str, str]] = []
        self.images_without_alt = 0
        self.h1_count = 0
        self.has_title = False
        self.has_description = False
        self.has_canonical = False
        self.has_noindex = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"] or "")
        if tag == "img" and "alt" not in values:
            self.images_without_alt += 1
        if tag == "h1":
            self.h1_count += 1
        if tag == "title":
            self.has_title = True
        if tag == "meta" and values.get("name", "").lower() == "description" and values.get("content"):
            self.has_description = True
        if tag == "link" and values.get("rel", "").lower() == "canonical" and values.get("href"):
            self.has_canonical = True
        if tag == "meta" and values.get("name", "").lower() == "robots" and "noindex" in values.get("content", "").lower():
            self.has_noindex = True
        for attribute in ("href", "src"):
            value = values.get(attribute)
            if value:
                self.refs.append((attribute, value))


def resolve_local(page: Path, value: str) -> Path | None:
    if value.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return None
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or value.startswith("/api/"):
        return None
    path = unquote(parts.path)
    if not path:
        return None
    if path.startswith("/"):
        return ROOT / path.lstrip("/")
    return (page.parent / path).resolve()


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    pages = sorted(ROOT.rglob("*.html"))
    for page in pages:
        if any(part in {".git", "node_modules"} for part in page.parts):
            continue
        relative = page.relative_to(ROOT).as_posix()
        source = page.read_text(encoding="utf-8")
        parser = PageParser()
        try:
            parser.feed(source)
        except Exception as exc:
            errors.append(f"{relative}: HTML parse error: {exc}")
            continue
        duplicates = sorted({value for value in parser.ids if parser.ids.count(value) > 1})
        if duplicates:
            errors.append(f"{relative}: duplicate ids: {', '.join(duplicates)}")
        if parser.images_without_alt:
            errors.append(f"{relative}: {parser.images_without_alt} image(s) missing alt")
        if not parser.has_title:
            errors.append(f"{relative}: missing title")
        if not parser.has_description:
            warnings.append(f"{relative}: missing meta description")
        if not parser.has_canonical and not parser.has_noindex:
            warnings.append(f"{relative}: missing canonical URL")
        if '<img' in source and re.search(r'<img[^>]*\s/\s+(?:loading|decoding)=', source):
            errors.append(f"{relative}: malformed image attribute placement")
        for attribute, value in parser.refs:
            target = resolve_local(page, value)
            if target is not None and not target.exists():
                errors.append(f"{relative}: broken {attribute} {value}")

    for home in (ROOT / "index.html", ROOT / "ko.html"):
        parser = PageParser()
        parser.feed(home.read_text(encoding="utf-8"))
        if parser.h1_count != 1:
            errors.append(f"{home.name}: expected one h1, found {parser.h1_count}")

    news_pages = list(ROOT.glob("crypto-news-20*.html"))
    for page in news_pages:
        source = page.read_text(encoding="utf-8")
        if '"@type": "NewsArticle"' not in source:
            errors.append(f"{page.name}: missing NewsArticle JSON-LD")
        if "data-crypto-news-detail" in source:
            errors.append(f"{page.name}: generated page still contains the dynamic news placeholder")
        if "뉴스를 불러오는 중입니다." in source or "Loading news" in source:
            errors.append(f"{page.name}: generated page still contains loading copy")
        if '<article class="crypto-news-article__inner">' not in source:
            errors.append(f"{page.name}: missing static news article body")
        parser = PageParser()
        parser.feed(source)
        if parser.has_noindex:
            errors.append(f"{page.name}: static news page must be indexable")

    print(f"Audited {len(pages)} HTML files and {len(news_pages)} static news pages")
    for message in warnings[:30]:
        print("WARN:", message)
    if len(warnings) > 30:
        print(f"WARN: ... {len(warnings) - 30} more")
    for message in errors:
        print("ERROR:", message)
    print(f"Summary: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
