#!/usr/bin/env python3
"""Apply repeatable metadata, performance, and accessibility improvements to static pages."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://metanomia-site.vercel.app"


def attr(tag: str, name: str) -> str:
    match = re.search(rf'\b{name}="([^"]*)"', tag, re.I)
    return match.group(1) if match else ""


def add_image_hints(text: str, is_home: bool) -> str:
    lead_seen = False

    def update(match: re.Match[str]) -> str:
        nonlocal lead_seen
        tag = match.group(0)
        classes = attr(tag, "class")
        if "brand__logo" in classes:
            return tag
        tag = re.sub(r'\s(?:loading|decoding|fetchpriority)="[^"]*"', "", tag, flags=re.I)
        base = tag[:-1].rstrip().rstrip("/").rstrip()
        if is_home and "lead__img" in classes and not lead_seen:
            lead_seen = True
            return base + ' loading="eager" decoding="async" fetchpriority="high">'
        if "lead__img" in classes:
            lead_seen = True
        return base + ' loading="lazy" decoding="async">'

    return re.sub(r'<img\b[^>]*>', update, text, flags=re.I)


def add_home_schema(text: str, lang: str) -> str:
    marker = '"@type": "WebSite"'
    if marker in text:
        return text
    name = "메타노미아" if lang == "ko" else "Metanomia"
    description = (
        "화폐·금융 질서와 크립토 생태계의 변화를 탐구하는 연구 공동체"
        if lang == "ko"
        else "A research community exploring monetary and financial order and the crypto ecosystem"
    )
    payload = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": SITE + "/#organization",
                "name": "Metanomia",
                "url": SITE + "/",
                "logo": SITE + "/images/brand/metanomia-lockup-meta-path-dark.svg",
                "sameAs": ["https://www.youtube.com/@metanomia_research"],
            },
            {
                "@type": "WebSite",
                "@id": SITE + "/#website",
                "url": SITE + ("/ko" if lang == "ko" else "/"),
                "name": name,
                "description": description,
                "publisher": {"@id": SITE + "/#organization"},
                "inLanguage": lang,
            },
        ],
    }
    script = '\n  <script type="application/ld+json">' + json.dumps(payload, ensure_ascii=False) + "</script>\n"
    return text.replace("</head>", script + "</head>", 1)


def text_content(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def add_article_schema(text: str, path: Path, lang: str) -> str:
    if '"@type": "Article"' in text or '"@type":"Article"' in text:
        return text
    title_match = re.search(r'<h1[^>]*class="article__title"[^>]*>(.*?)</h1>', text, re.S | re.I)
    desc_match = re.search(r'<meta name="description" content="([^"]*)"', text, re.I)
    canonical_match = re.search(r'<link rel="canonical" href="([^"]*)"', text, re.I)
    image_match = re.search(r'<div class="article__hero">\s*<img[^>]+src="([^"]+)"', text, re.S | re.I)
    date_match = re.search(r'<span class="article__meta"><span>([^<]+)</span>', text, re.I)
    author_match = re.search(r'<div class="article__author-name">(.*?)</div>', text, re.S | re.I)
    if not (title_match and canonical_match):
        return text
    image_url = ""
    if image_match:
        source = image_match.group(1)
        if source.startswith("/"):
            image_url = SITE + source
        else:
            image_url = SITE + "/" + (path.parent / source).resolve().relative_to(ROOT).as_posix()
    payload: dict[str, object] = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": text_content(title_match.group(1)),
        "description": html.unescape(desc_match.group(1)) if desc_match else "",
        "url": canonical_match.group(1),
        "mainEntityOfPage": canonical_match.group(1),
        "publisher": {"@type": "Organization", "name": "Metanomia", "url": SITE + "/"},
        "inLanguage": lang,
    }
    if image_url:
        payload["image"] = image_url
    if date_match:
        payload["datePublished"] = text_content(date_match.group(1))
    if author_match:
        names = [name.strip() for name in re.split(r"[·,]", text_content(author_match.group(1))) if name.strip()]
        payload["author"] = [{"@type": "Person", "name": name} for name in names]
    script = '\n  <script type="application/ld+json">' + json.dumps(payload, ensure_ascii=False) + "</script>\n"
    return text.replace("</head>", script + "</head>", 1)


def process(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text
    lang_match = re.search(r'<html[^>]+lang="([^"]+)"', text, re.I)
    lang = lang_match.group(1).lower() if lang_match else ("ko" if "ko" in path.relative_to(ROOT).parts else "en")
    is_home = path.name == "index.html" and path.parent in {ROOT, ROOT / "ko"}

    if 'name="theme-color"' not in text:
        text = text.replace('<meta charset="UTF-8" />', '<meta charset="UTF-8" />\n  <meta name="theme-color" content="#000000" />', 1)

    if 'name="description"' not in text:
        title_match = re.search(r'<title>(.*?)</title>', text, re.S | re.I)
        title = text_content(title_match.group(1)) if title_match else "Metanomia"
        description = (
            f"{title} 페이지로 이동합니다."
            if lang == "ko"
            else f"Continue to the current {title} page."
        )
        text = text.replace(
            '<meta name="theme-color" content="#000000" />',
            '<meta name="theme-color" content="#000000" />\n  '
            + '<meta name="description" content="'
            + html.escape(description, quote=True)
            + '" />',
            1,
        )

    search_pattern = re.compile(r'<a class="nav__search" href="#"([^>]*)>(.*?)</a>', re.S | re.I)
    text = search_pattern.sub(r'<button type="button" class="nav__search"\1>\2</button>', text)

    if is_home:
        text = re.sub(r'<h1 class="lead__title([^>]*)>(.*?)</h1>', r'<h2 class="lead__title\1>\2</h2>', text, flags=re.S)
        main_match = re.search(r'<main([^>]*)>', text, re.I)
        label = "메타노미아 연구 보고서" if lang == "ko" else "Metanomia research reports"
        if not main_match:
            text = text.replace('</header>', '</header>\n\n  <main id="main-content">\n    <h1 class="sr-only">' + label + '</h1>', 1)
            text = text.replace('<footer', '  </main>\n\n  <footer', 1)
        elif 'class="sr-only"' not in text[main_match.end():main_match.end() + 300]:
            text = text[:main_match.end()] + f'\n    <h1 class="sr-only">{label}</h1>' + text[main_match.end():]
        text = add_home_schema(text, lang)

    target_match = re.search(r'<main\b([^>]*)>', text, re.I)
    if not target_match:
        target_match = re.search(r'<article\b([^>]*)>', text, re.I)
    if target_match:
        tag = target_match.group(0)
        if not re.search(r'\bid=', tag, re.I):
            updated_tag = tag[:-1] + ' id="main-content">'
            text = text[:target_match.start()] + updated_tag + text[target_match.end():]
        if 'class="skip-link"' not in text:
            label = "본문으로 건너뛰기" if lang == "ko" else "Skip to main content"
            text = text.replace("<body>", f'<body>\n  <a class="skip-link" href="#main-content">{label}</a>', 1)

    text = add_image_hints(text, is_home)
    if path.parent in {ROOT / "articles", ROOT / "ko" / "articles"}:
        text = add_article_schema(text, path, lang)

    if text != original:
        path.write_text(text, encoding="utf-8", newline="\n")
        return True
    return False


def main() -> None:
    changed = 0
    for path in sorted(ROOT.rglob("*.html")):
        if any(part in {".git", "node_modules"} for part in path.parts):
            continue
        changed += int(process(path))
    print(f"Prepared {changed} HTML files")


if __name__ == "__main__":
    main()