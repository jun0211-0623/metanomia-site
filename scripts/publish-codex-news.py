#!/usr/bin/env python3
"""Validate and publish prepared Codex English news from the current linked worktree."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys

ORIGIN_URL = "https://github.com/jun0211-0623/metanomia-site.git"
COMMIT_MESSAGE = "chore: sync English crypto news with Codex"
KOREAN_PATH = "data/crypto-news.json"
ALLOWED_PATHS = {"data/crypto-news.en.json", ".newsroom/translation-state.json", "sitemap.xml"}
PAGE_RE = re.compile(r"(?:ko/)?crypto-news-20\d{2}-\d{2}-\d{2}-crypto-news-[0-9a-f]{10}\.html")


class PublishError(RuntimeError):
    pass


def run(repository: Path, command: list[str]) -> bytes:
    env = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"):
        env.pop(key, None)
    env.update(PYTHONDONTWRITEBYTECODE="1", GIT_TERMINAL_PROMPT="0")
    try:
        result = subprocess.run(command, cwd=repository, env=env, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PublishError(f"Command failed: {command[0]}: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).decode("utf-8", errors="replace").strip()
        raise PublishError(f"Command failed: {' '.join(command[:4])}: {detail[-2000:]}")
    return result.stdout


def git(repository: Path, *args: str) -> str:
    return run(repository, ["git", *args]).decode("utf-8", errors="strict").strip()


def allowed(path: str) -> bool:
    return path in ALLOWED_PATHS or PAGE_RE.fullmatch(path) is not None


def check_origin(repository: Path) -> None:
    # Check the effective fetch AND push destinations, including pushurl overrides.
    for options in (("--all",), ("--push", "--all")):
        urls = git(repository, "remote", "get-url", *options, "origin").splitlines()
        if urls != [ORIGIN_URL]:
            raise PublishError("origin fetch and push URLs must both be the approved metanomia-site HTTPS URL.")


def check_base(repository: Path, base_head: str) -> None:
    if git(repository, "rev-parse", "HEAD") != base_head:
        raise PublishError("HEAD changed from --base-head; refusing stale publication.")
    expected = run(repository, ["git", "show", f"{base_head}:{KOREAN_PATH}"])
    korean = repository / KOREAN_PATH
    if korean.is_symlink() or korean.read_bytes() != expected:
        raise PublishError(
            "Korean manifest bytes differ from the approved HEAD. Do not rewrite the original. "
            "Create the temporary worktree with: git -c core.autocrlf=false worktree add --detach <path> origin/main"
        )


def check_remote(repository: Path, base_head: str) -> None:
    check_origin(repository)
    git(repository, "fetch", "--no-tags", "origin", "refs/heads/main:refs/remotes/origin/main")
    if git(repository, "rev-parse", "refs/remotes/origin/main") != base_head:
        raise PublishError("origin/main changed from --base-head; refusing stale publication.")


def guard_worktree(repository: Path) -> list[str]:
    raw = run(repository, ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"])
    paths = []
    for entry in raw.decode("utf-8", errors="strict").split("\0"):
        if not entry:
            continue
        status, path = entry[:2], entry[3:]
        if not allowed(path):
            raise PublishError(f"Unrelated dirty or staged file: {path}")
        if status != "??" and (not status.strip() or any(c not in " AM" for c in status)):
            raise PublishError(f"Only additions and modifications are permitted: {status} {path}")
        target = repository / path
        if target.is_symlink() or not target.is_file():
            raise PublishError(f"Publication output must be a regular file: {path}")
        paths.append(path)
    return sorted(set(paths))


def output_hashes(repository: Path) -> dict[str, str]:
    return {path: hashlib.sha256((repository / path).read_bytes()).hexdigest()
            for path in guard_worktree(repository)}


def changed_paths(repository: Path, args: list[str]) -> list[str]:
    entries = run(repository, ["git", *args, "--name-status", "-z", "--no-renames", "--"]).decode("utf-8").split("\0")
    entries = entries[:-1] if entries[-1] == "" else entries
    if len(entries) % 2:
        raise PublishError("Invalid Git change list.")
    paths = []
    for status, path in zip(entries[::2], entries[1::2]):
        if status not in {"A", "M"} or not allowed(path):
            raise PublishError(f"Forbidden staged or committed change: {status} {path}")
        paths.append(path)
    return sorted(paths)


def validate_pages(repository: Path) -> None:
    commands = [
        ["scripts/build-news-pages.py"],
        ["scripts/codex-news-translation.py", "verify"],
        ["scripts/publish_crypto_news.py", "verify-static-pages", "--repository", "."],
        ["scripts/audit-site.py"],
    ]
    for args in commands:
        run(repository, [sys.executable, "-B", *args])


def publish(repository: Path, base_head: str) -> str | None:
    repository = repository.resolve()
    if not re.fullmatch(r"[0-9a-f]{40}", base_head):
        raise PublishError("--base-head must be a full lowercase Git commit SHA.")
    if Path(git(repository, "rev-parse", "--show-toplevel")).resolve() != repository:
        raise PublishError("Run this command from the temporary worktree root.")
    if not (repository / ".git").is_file():
        raise PublishError("Only a linked temporary worktree is permitted; the main checkout is not supported.")
    check_base(repository, base_head)
    guard_worktree(repository)
    check_remote(repository, base_head)
    validate_pages(repository)
    check_base(repository, base_head)
    verified_hashes = output_hashes(repository)
    paths = sorted(verified_hashes)
    if not paths:
        print("No changes: English news and static pages already match.")
        return None
    if output_hashes(repository) != verified_hashes:
        raise PublishError("Publication output bytes changed after validation.")
    git(repository, "add", "--", *paths)
    staged = changed_paths(repository, ["diff", "--cached"])
    if not staged or staged != paths:
        raise PublishError("The staged outputs do not exactly match the verified publication files.")
    check_remote(repository, base_head)
    check_base(repository, base_head)
    if output_hashes(repository) != verified_hashes:
        raise PublishError("Publication output bytes changed after validation.")
    git(repository, "diff", "--exit-code", "--")
    commit = None
    try:
        git(repository, "commit", "-m", COMMIT_MESSAGE)
        commit = git(repository, "rev-parse", "HEAD")
        if git(repository, "rev-parse", "HEAD^") != base_head:
            raise PublishError("The new commit has an unexpected parent.")
        if changed_paths(repository, ["diff", base_head, "HEAD"]) != staged:
            raise PublishError("The new commit contains unexpected changes.")
        if guard_worktree(repository):
            raise PublishError("Worktree changed while creating the commit.")
        check_origin(repository)
        git(repository, "push", "origin", "HEAD:refs/heads/main")
    except PublishError as exc:
        if commit:
            raise PublishError(f"{exc}\nLocal commit preserved: {commit}\nWorktree preserved: {repository}") from exc
        raise
    print(f"English news published: {commit}")
    return commit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-head", required=True)
    args = parser.parse_args(argv)
    try:
        publish(Path.cwd(), args.base_head)
    except (PublishError, OSError, UnicodeError) as exc:
        print(f"English publication blocked: {exc}", file=sys.stderr)
        print(f"Current worktree and any local commit were preserved: {Path.cwd()}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
