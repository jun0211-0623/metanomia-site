#!/usr/bin/env python3
"""Generate static, bilingual Crypto News detail pages from the approved manifests."""
from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://metanomia-site.vercel.app"


def clean(value: object) -> str:
    return str(value or "").strip()


def excerpt(value: str, limit: int = 155) -> str:
    value = re.sub(r"\s+", " ", clean(value))
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def paragraphs(value: str) -> str:
    chunks = [part.strip() for part in re.split(r"\r?\n\s*\r?\n|\r\n|\n", clean(value)) if part.strip()]
    return "\n".join("          <p>" + html.escape(part) + "</p>" for part in chunks)


def format_date(value: str, lang: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return value
    if lang == "ko":
        return f"{parsed.year}년 {parsed.month}월 {parsed.day}일"
    months = (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    )
    return f"{months[parsed.month - 1]} {parsed.day}, {parsed.year}"


def static_name(item: dict, lang: str) -> str:
    suffix = ".ko.html" if lang == "ko" else ".html"
    return "crypto-news-" + clean(item["slug"]) + suffix


def source_rows(item: dict, lang: str) -> str:
    rows = []
    for source in item.get("sources") or []:
        title = clean(source.get("title"))
        url = clean(source.get("url"))
        if not title or not re.match(r"^https?://", url):
            continue
        rows.append(
            '            <li class="crypto-news-sources__item"><a class="crypto-news-sources__link" '
            'href="' + html.escape(url, quote=True) + '" target="_blank" rel="noopener noreferrer">'
            + html.escape(title) + "</a></li>"
        )
    if rows:
        return "\n".join(rows)
    fallback = "출처 정보 준비 중" if lang == "ko" else "Sources to follow"
    return '            <li class="crypto-news-sources__empty">' + fallback + "</li>"


def navigation(items: list[dict], index: int, lang: str) -> str:
    previous = items[index + 1] if index + 1 < len(items) else None
    following = items[index - 1] if index > 0 else None
    previous_label = "이전 뉴스" if lang == "ko" else "Previous News"
    next_label = "다음 뉴스" if lang == "ko" else "Next News"
    aria = "이전 및 다음 뉴스" if lang == "ko" else "Previous and next news"

    def link(item: dict | None, kind: str, label: str) -> str:
        if not item:
            return ""
        arrow = "← " if kind == "previous" else ""
        tail = " →" if kind == "next" else ""
        return (
            '          <a class="crypto-news-pagination__link crypto-news-pagination__link--' + kind
            + '" href="' + static_name(item, lang) + '" aria-label="' + html.escape(label + ": " + clean(item["title"]), quote=True) + '">\n'
            + '            <span class="crypto-news-pagination__label">' + arrow + label + tail + "</span>\n"
            + '            <strong class="crypto-news-pagination__title">' + html.escape(clean(item["title"])) + "</strong>\n"
            + "          </a>"
        )

    return (
        '        <nav class="crypto-news-pagination" aria-label="' + aria + '">\n'
        + link(previous, "previous", previous_label) + "\n"
        + link(following, "next", next_label) + "\n"
        + "        </nav>"
    )


def detail_main(item: dict, items: list[dict], index: int, lang: str) -> str:
    is_ko = lang == "ko"
    thought_label = "메타노미아 생각" if is_ko else "Metanomia View"
    sources_label = "출처" if is_ko else "Sources"
    title = html.escape(clean(item["title"]))
    return f'''<main class="crypto-news-article" id="main-content">
    <div class="container">
      <article class="crypto-news-article__inner">
        <header class="crypto-news-article__header">
          <time class="crypto-news-article__date" datetime="{html.escape(clean(item["date_kst"]), quote=True)}">{format_date(clean(item["date_kst"]), lang)}</time>
          <h1 class="crypto-news-article__title">{title}</h1>
        </header>
        <div class="crypto-news-article__body">
{paragraphs(clean(item["content"]))}
        </div>
        <section class="crypto-news-thought" aria-labelledby="metanomiaThought">
          <h2 class="crypto-news-thought__label" id="metanomiaThought">{thought_label}</h2>
          <div class="crypto-news-thought__body">
{paragraphs(clean(item.get("metanomia_thought")))}
          </div>
        </section>
        <section class="crypto-news-sources" aria-labelledby="newsSources">
          <h2 class="crypto-news-sources__title" id="newsSources">{sources_label}</h2>
          <ul class="crypto-news-sources__list">
{source_rows(item, lang)}
          </ul>
        </section>
{navigation(items, index, lang)}
      </article>
    </div>
  </main>'''


def set_meta(page: str, item: dict, lang: str, counterpart: str) -> str:
    filename = static_name(item, lang)
    canonical = SITE + "/" + filename
    title_suffix = " | 메타노미아 크립토 뉴스" if lang == "ko" else " | Metanomia Crypto News"
    page_title = clean(item["title"]) + title_suffix
    description = excerpt(clean(item["content"]))
    locale = "ko_KR" if lang == "ko" else "en_US"
    counterpart_url = SITE + "/" + counterpart

    replacements = [
        (r"<title>.*?</title>", "<title>" + html.escape(page_title) + "</title>"),
        (r'<meta name="robots" content="[^"]*" />', '<meta name="robots" content="index, follow" />'),
        (r'<meta name="description" content="[^"]*" />', '<meta name="description" content="' + html.escape(description, quote=True) + '" />'),
        (r'<link rel="canonical" href="[^"]*" />', '<link rel="canonical" href="' + canonical + '" />'),
        (r'<meta property="og:locale" content="[^"]*" />', '<meta property="og:locale" content="' + locale + '" />'),
        (r'<meta property="og:title" content="[^"]*" />', '<meta property="og:title" content="' + html.escape(page_title, quote=True) + '" />'),
        (r'<meta property="og:description" content="[^"]*" />', '<meta property="og:description" content="' + html.escape(description, quote=True) + '" />'),
        (r'<meta property="og:url" content="[^"]*" />', '<meta property="og:url" content="' + canonical + '" />'),
        (r'<meta name="twitter:title" content="[^"]*" />', '<meta name="twitter:title" content="' + html.escape(page_title, quote=True) + '" />'),
        (r'<meta name="twitter:description" content="[^"]*" />', '<meta name="twitter:description" content="' + html.escape(description, quote=True) + '" />'),
    ]
    for pattern, replacement in replacements:
        page = re.sub(pattern, replacement, page, count=1, flags=re.S)

    language_links = (
        '  <link rel="alternate" hreflang="ko" href="' + (canonical if lang == "ko" else counterpart_url) + '" />\n'
        '  <link rel="alternate" hreflang="en" href="' + (canonical if lang == "en" else counterpart_url) + '" />\n'
        '  <link rel="alternate" hreflang="x-default" href="' + (canonical if lang == "en" else counterpart_url) + '" />\n'
    )
    page = page.replace('  <link rel="icon" href="favicon.svg"', language_links + '  <link rel="icon" href="favicon.svg"', 1)

    schema = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": clean(item["title"]),
        "description": description,
        "datePublished": clean(item["date_kst"]),
        "dateModified": clean(item["date_kst"]),
        "inLanguage": lang,
        "mainEntityOfPage": canonical,
        "url": canonical,
        "image": SITE + "/images/brand/og-default.png",
        "publisher": {
            "@type": "Organization",
            "name": "Metanomia",
            "url": SITE,
            "logo": {"@type": "ImageObject", "url": SITE + "/favicon-180.png"},
        },
    }
    page = page.replace("</head>", '  <script type="application/ld+json">' + json.dumps(schema, ensure_ascii=False) + "</script>\n</head>", 1)
    return page


def build_language(lang: str) -> list[str]:
    is_ko = lang == "ko"
    manifest = ROOT / ("data/crypto-news.json" if is_ko else "data/crypto-news.en.json")
    template = ROOT / ("crypto-news-detail.ko.html" if is_ko else "crypto-news-detail.html")
    items = json.loads(manifest.read_text(encoding="utf-8")).get("items", [])
    items = sorted(
        [item for item in items if clean(item.get("slug")) and clean(item.get("title")) and clean(item.get("content"))],
        key=lambda item: (clean(item.get("date_kst")), clean(item.get("slug"))),
        reverse=True,
    )
    other_items = json.loads((ROOT / ("data/crypto-news.en.json" if is_ko else "data/crypto-news.json")).read_text(encoding="utf-8")).get("items", [])
    counterpart_by_slug = {clean(item.get("slug")): item for item in other_items}
    base = template.read_text(encoding="utf-8")
    written = []

    for index, item in enumerate(items):
        counterpart_item = counterpart_by_slug.get(clean(item["slug"]))
        counterpart = static_name(counterpart_item or item, "en" if is_ko else "ko")
        page = set_meta(base, item, lang, counterpart)
        page, replaced = re.subn(
            r'<main class="crypto-news-article"[^>]*>[\s\S]*?</main>',
            detail_main(item, items, index, lang),
            page,
            count=1,
        )
        if replaced != 1:
            raise RuntimeError(f"Could not replace the news article body in {template.name}")
        page = re.sub(r'\s*<script src="js/crypto-news\.js" defer></script>', "", page)
        generic_counterpart = "crypto-news-detail.html" if is_ko else "crypto-news-detail.ko.html"
        page = page.replace(generic_counterpart, counterpart)
        output = ROOT / static_name(item, lang)
        output.write_text(page, encoding="utf-8", newline="\n")
        written.append(output.name)
    return written


def update_sitemap(files: list[str]) -> None:
    path = ROOT / "sitemap.xml"
    content = path.read_text(encoding="utf-8")
    content = re.sub(r"\n?\s*<!-- GENERATED CRYPTO NEWS START -->[\s\S]*?<!-- GENERATED CRYPTO NEWS END -->", "", content)
    pairs: dict[str, dict[str, str]] = {}
    for filename in files:
        slug = filename.removeprefix("crypto-news-").removesuffix(".html")
        lang = "ko" if slug.endswith(".ko") else "en"
        slug = slug.removesuffix(".ko")
        pairs.setdefault(slug, {})[lang] = filename
    blocks = ["  <!-- GENERATED CRYPTO NEWS START -->"]
    for slug in sorted(pairs, reverse=True):
        pair = pairs[slug]
        published_date = slug[:10] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", slug[:10]) else date.today().isoformat()
        for lang in ("ko", "en"):
            filename = pair.get(lang)
            if not filename:
                continue
            blocks.extend([
                "  <url>",
                "    <loc>" + SITE + "/" + filename + "</loc>",
                "    <lastmod>" + published_date + "</lastmod>",
                "    <changefreq>weekly</changefreq>",
                "    <priority>0.70</priority>",
                "    <xhtml:link rel=\"alternate\" hreflang=\"ko\" href=\"" + SITE + "/" + pair.get("ko", filename) + "\" />",
                "    <xhtml:link rel=\"alternate\" hreflang=\"en\" href=\"" + SITE + "/" + pair.get("en", filename) + "\" />",
                "  </url>",
            ])
    blocks.append("  <!-- GENERATED CRYPTO NEWS END -->")
    content = content.replace("</urlset>", "\n" + "\n".join(blocks) + "\n</urlset>")
    path.write_text(content, encoding="utf-8", newline="\n")


def main() -> None:
    files = build_language("ko") + build_language("en")
    update_sitemap(files)
    print("Generated", len(files), "Crypto News pages")


if __name__ == "__main__":
    main()
