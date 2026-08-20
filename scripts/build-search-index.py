#!/usr/bin/env python3
"""Rebuild search-index.json from the pages themselves.

Run from the repository root:  python3 scripts/build-search-index.py
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Pages that get a plain "Page" entry, in the order they should appear.
PAGES = [
    'about.html', 'publications.html', 'media.html', 'members.html',
    'media/weekly-crypto.html', 'media/ask-the-author.html', 'media/crypto-tutoring.html',
    'media/crypto-issues.html', 'media/reading-crypto.html',
    'crypto-news.html', 'contact.html', 'privacy.html', 'terms.html',
]

TYPES = {
    'report': ('Report', '보고서'),
    'people': ('People', '사람'),
    'page': ('Page', '페이지'),
    'series': ('Series', '시리즈'),
}


def read(path):
    with open(os.path.join(ROOT, path), encoding='utf-8') as f:
        return f.read()


def clean(text):
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&ensp;', ' ').replace('&emsp;', ' ').replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&#39;', "'")
    return ' '.join(text.split())


def grab(html, pattern):
    match = re.search(pattern, html, re.S)
    return clean(match.group(1)) if match else ''


def description(html):
    return grab(html, r'<meta name="description" content="([^"]*)"')


def ko_path(path):
    return 'ko/' + path


def to_url(path):
    """Repo-relative html file -> served, extensionless URL."""
    return '/' + path[:-5] if path.endswith('.html') else '/' + path


def to_file(url):
    """Served URL -> repo-relative html file."""
    return url.lstrip('/') + '.html'


def entry(kind, lang, title, sub, meta, path):
    return {
        'lang': lang,
        'type': TYPES[kind][0 if lang == 'en' else 1],
        'title': title,
        'sub': sub,
        'meta': meta,
        'url': to_url(path),
    }


def report_catalog(path):
    """Authors and date for each report, taken from the publications catalog."""
    html = read(path)
    out = {}
    for card in re.finditer(r'<a class="cat-card"(.*?)</a>\s*(?=<a class="cat-card"|</div>)', html, re.S):
        block = card.group(0)
        href = re.search(r'href="([^"]+)"', block)
        if not href:
            continue
        authors = grab(block, r'class="cat-card__authors"[^>]*>(.*?)</')
        date = grab(block, r'class="cat-card__date"[^>]*>(.*?)</')
        out[href.group(1)] = (authors.replace(' · ', ', '), date)
    return out


def build():
    index = []
    catalog = {'en': report_catalog('publications.html'), 'ko': report_catalog('ko/publications.html')}

    # Reports, newest first, mirroring the catalog order.
    for lang, source in (('en', 'publications.html'), ('ko', 'ko/publications.html')):
        for href, (authors, date) in catalog[lang].items():
            report = to_file(href)
            html = read(report)
            index.append(entry(
                'report', lang,
                grab(html, r'class="article__title[^"]*"[^>]*>(.*?)</h1>') or grab(html, r'<h1[^>]*>(.*?)</h1>'),
                grab(html, r'class="article__sub"[^>]*>(.*?)</p>'),
                ' · '.join(part for part in (authors, date) if part),
                report,
            ))

    # Member profiles, alphabetical by file name.
    for name in sorted(os.listdir(os.path.join(ROOT, 'people'))):
        if not name.endswith('.html') or name.endswith('.ko.html'):
            continue
        path = 'people/' + name
        for lang, target in (('en', path), ('ko', ko_path(path))):
            html = read(target)
            org = 'Metanomia' if lang == 'en' else '메타노미아'
            role = grab(html, r'class="profile__role"[^>]*>(.*?)</p>')
            index.append(entry(
                'people', lang,
                grab(html, r'class="profile__name"[^>]*>(.*?)</h1>'),
                '',
                ' · '.join(part for part in (role, org) if part),
                target,
            ))

    # Standalone pages.
    for path in PAGES:
        for lang, target in (('en', path), ('ko', ko_path(path))):
            html = read(target)
            index.append(entry(
                'page', lang,
                grab(html, r'<h1[^>]*>(.*?)</h1>') or grab(html, r'<title>(.*?)</title>').split('|')[0].strip(),
                description(html),
                '',
                target,
            ))

    # Report series.
    for name in sorted(os.listdir(os.path.join(ROOT, 'series'))):
        if not name.endswith('.html') or name.endswith('.ko.html'):
            continue
        path = 'series/' + name
        for lang, target in (('en', path), ('ko', ko_path(path))):
            html = read(target)
            index.append(entry(
                'series', lang,
                grab(html, r'<h1[^>]*class="cat-title[^"]*"[^>]*>(.*?)</h1>'),
                description(html),
                '',
                target,
            ))

    index.sort(key=lambda item: (item['lang'] != 'en', item['type'], item['title']))
    return index


if __name__ == '__main__':
    data = build()
    with open(os.path.join(ROOT, 'search-index.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f'search-index.json: {len(data)} entries '
          f"({sum(1 for i in data if i['lang'] == 'en')} en / {sum(1 for i in data if i['lang'] == 'ko')} ko)")
