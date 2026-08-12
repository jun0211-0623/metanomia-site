#!/usr/bin/env python3
"""Translate data/crypto-news.json into data/crypto-news.en.json.

Only items whose slug is missing from the English file are translated, so a
normal run costs one API call per newly published item. Pass --force to
retranslate everything (e.g. after changing the prompt below).

Requires ANTHROPIC_API_KEY in the environment.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import anthropic

MODEL = "claude-opus-5"

ROOT = Path(__file__).resolve().parent.parent
KO_PATH = ROOT / "data" / "crypto-news.json"
EN_PATH = ROOT / "data" / "crypto-news.en.json"

SYSTEM = """You translate Korean crypto and finance news into English for Metanomia, \
an independent research institute that studies how the order of money is changing.

Rules:
- Translate only what is in the source. Never add facts, figures, names, dates, \
context, or interpretation that the Korean text does not contain. Never drop anything either.
- Write plain, direct English prose. Metanomia's voice is analytical and unhurried, \
not breathless and not promotional.
- Never use em-dashes. Use a colon, parentheses, or a comma instead.
- Keep paragraph breaks exactly as they appear in the source: a blank line in the \
Korean content is a blank line in the English content.
- Render proper nouns the way the organizations themselves write them in English \
(exchanges, protocols, tickers, regulators). Leave tickers uppercase.
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
    args = parser.parse_args()

    ko = load(KO_PATH)
    en = load(EN_PATH)

    done = {} if args.force else {i["slug"]: i for i in en.get("items", []) if i.get("slug")}
    pending = [i for i in ko.get("items", []) if i.get("slug") and i["slug"] not in done]

    if not pending:
        print("nothing to translate")
        return

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
            # Source titles name real external articles, so they stay as published.
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
