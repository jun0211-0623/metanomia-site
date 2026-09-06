#!/usr/bin/env python3
"""Translate data/crypto-news.json into data/crypto-news.en.json.

Normally items whose slug is missing from the English file are translated.
``--required-slugs-file`` also retranslates explicitly changed Korean items,
preventing a same-slug English article from becoming stale.

Requires ANTHROPIC_API_KEY in the environment.
"""

import argparse
import json
import os
import sys
from pathlib import Path

MODEL = "claude-opus-5"

ROOT = Path(__file__).resolve().parent.parent
KO_PATH = ROOT / "data" / "crypto-news.json"
EN_PATH = ROOT / "data" / "crypto-news.en.json"

SYSTEM = """You translate Korean crypto and finance news into English for Metanomia, \
an independent research institute that studies how the order of money is changing.

Rules:
- Preserve every fact, number, unit, date, name, attribution, comparison, qualifier, \
scope limit, and expression of uncertainty. Translate only what the source states: \
never add, omit, infer, or generalize anything.
- Preserve every status and scope qualifier in the title and body, including whether \
something is proposed, under consultation, conditional, in beta or a pilot, estimated, \
alleged, externally reported, limited, newly created, not yet supported, or fully launched. \
Never make a tentative or limited development sound final or confirmed.
- Preserve the source's plain-language role descriptors and explanations of unfamiliar \
organizations, products, protocols, legal concepts, and financial terms. Do not remove \
those explanations merely to make the English shorter.
- Preserve who confirmed each claim. Keep official findings, company statements, media \
reports, and external estimates distinct.
- Write plain, direct English prose. Metanomia's voice is analytical and unhurried, \
not breathless and not promotional.
- Never use em-dashes. Use a colon, parentheses, or a comma instead.
- Keep paragraph breaks exactly as they appear in the source: a blank line in the \
Korean content is a blank line in the English content.
- Render proper nouns the way the organizations themselves write them in English \
(exchanges, protocols, tickers, regulators). Leave tickers uppercase.
- Do not infer that a shared interface means shared custody, data control, legal \
responsibility, or fully onchain settlement unless the Korean source states it.
- metanomia_thought is Metanomia's own commentary. Keep its argument intact and its \
register measured; do not sharpen or soften the position."""

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "content": {"type": "string"},
        "metanomia_thought": {"type": "string"},
    },
    "required": ["title", "content", "metanomia_thought"],
    "additionalProperties": False,
}


def load(path):
    if not path.exists():
        return {"schema_version": "1.0", "items": []}
    return json.loads(path.read_text(encoding="utf-8"))


def required_slugs(path, known_slugs):
    if path is None:
        return set()
    metadata = load(path)
    values = metadata.get("changed_slugs") if isinstance(metadata, dict) else None
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ValueError("required slug metadata must contain a changed_slugs string array")
    result = set(values)
    unknown = sorted(result - set(known_slugs))
    if unknown:
        raise ValueError(f"required slug metadata contains unknown slug(s): {', '.join(unknown)}")
    return result


def select_pending(ko_items, en_items, force=False, required=None):
    required = set(required or [])
    done = {} if force else {i["slug"]: i for i in en_items if i.get("slug")}
    pending = [
        item
        for item in ko_items
        if item.get("slug") and (item["slug"] not in done or item["slug"] in required)
    ]
    return done, pending


def assert_no_english_only_slugs(ko_items, en_items):
    ko_slugs = {item.get("slug") for item in ko_items if item.get("slug")}
    en_slugs = {item.get("slug") for item in en_items if item.get("slug")}
    extra = sorted(en_slugs - ko_slugs)
    if extra:
        raise ValueError(
            "English manifest contains slug(s) absent from Korean manifest; "
            f"automatic deletion is forbidden: {', '.join(extra)}"
        )


def translate(client, item):
    source = json.dumps(
        {
            "title": item.get("title", ""),
            "content": item.get("content", ""),
            "metanomia_thought": item.get("metanomia_thought", ""),
        },
        ensure_ascii=False,
        indent=2,
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": f"Translate each field.\n\n{source}"}],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError(f"refused: {item.get('slug')}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError(f"truncated: {item.get('slug')}")

    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="retranslate every item")
    parser.add_argument(
        "--required-slugs-file",
        type=Path,
        help="publisher metadata JSON whose changed_slugs must be retranslated",
    )
    args = parser.parse_args()

    ko = load(KO_PATH)
    en = load(EN_PATH)

    ko_items = ko.get("items", [])
    en_items = en.get("items", [])
    assert_no_english_only_slugs(ko_items, en_items)
    known_slugs = [item.get("slug") for item in ko_items if item.get("slug")]
    required = required_slugs(args.required_slugs_file, known_slugs)
    done, pending = select_pending(
        ko_items, en_items, force=args.force, required=required
    )

    if not pending:
        print("nothing to translate")
        return

    import anthropic

    client = anthropic.Anthropic()
    print(f"translating {len(pending)} item(s) with {MODEL}")

    for item in pending:
        slug = item["slug"]
        fields = translate(client, item)
        done[slug] = {
            "slug": slug,
            "date_kst": item.get("date_kst", ""),
            "title": fields["title"],
            "content": fields["content"],
            "metanomia_thought": fields["metanomia_thought"],
            # Sources are immutable: preserve titles, URLs, entry count, and order exactly.
            "sources": item.get("sources", []),
        }
        print(f"  {slug}")

    order = [i["slug"] for i in ko.get("items", []) if i.get("slug")]
    EN_PATH.write_text(
        json.dumps(
            {
                "schema_version": ko.get("schema_version", "1.0"),
                "generated_at_kst": ko.get("generated_at_kst", ""),
                "items": [done[s] for s in order if s in done],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {EN_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
