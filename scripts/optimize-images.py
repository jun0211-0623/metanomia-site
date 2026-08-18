#!/usr/bin/env python3
"""Generate WebP copies of large site images and update textual references."""
from __future__ import annotations

from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIRS = (ROOT / "images" / "reports", ROOT / "images" / "people")
TEXT_GLOBS = ("*.html", "*.css", "*.js", "*.json", "*.xml")
SOURCE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def convert(source: Path) -> Path:
    target = source.with_suffix(".webp")
    with Image.open(source) as image:
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if "transparency" in image.info else "RGB")
        image.save(target, "WEBP", quality=82, method=6)
    return target


def main() -> None:
    replacements: dict[str, str] = {}
    for directory in IMAGE_DIRS:
        for source in sorted(directory.iterdir()):
            if source.suffix.lower() not in SOURCE_SUFFIXES or source.stat().st_size < 100_000:
                continue
            target = convert(source)
            old = source.relative_to(ROOT).as_posix()
            replacements[old] = target.relative_to(ROOT).as_posix()
            print(f"{old}: {source.stat().st_size:,} -> {target.stat().st_size:,}")

    changed = 0
    for pattern in TEXT_GLOBS:
        for path in ROOT.rglob(pattern):
            if any(part in {".git", "node_modules"} for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8")
            updated = text
            for old, new in replacements.items():
                updated = updated.replace(old, new)
            if updated != text:
                path.write_text(updated, encoding="utf-8", newline="\n")
                changed += 1
    print(f"Updated {changed} text files and generated {len(replacements)} WebP images")


if __name__ == "__main__":
    main()