from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "publish_codex_news", Path(__file__).resolve().parents[1] / "scripts/publish-codex-news.py"
)
assert SPEC and SPEC.loader
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


def git(repository: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repository, capture_output=True, check=True)
    return result.stdout.decode("utf-8").strip()


class PublishCodexNewsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="codex-news-publish-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.origin = self.root / "origin.git"
        self.source = self.root / "source"
        self.worktree = self.root / "worktree"
        self.origin.mkdir()
        self.source.mkdir()
        git(self.origin, "init", "--bare")
        git(self.source, "init", "-b", "main")
        git(self.source, "config", "user.name", "Local Test Author")
        git(self.source, "config", "user.email", "test@example.invalid")
        git(self.source, "config", "core.autocrlf", "false")
        git(self.source, "remote", "add", "origin", self.origin.as_posix())
        for path, content in {
            "data/crypto-news.json": '{"items":[]}\n',
            "data/crypto-news.en.json": '{"items":[]}\n',
            "sitemap.xml": "original sitemap\n",
            "README.md": "unrelated original\n",
        }.items():
            target = self.source / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.encode())
        git(self.source, "add", ".")
        git(self.source, "commit", "-m", "test baseline")
        git(self.source, "push", "origin", "main")
        self.base = git(self.source, "rev-parse", "HEAD")
        git(self.source, "worktree", "add", "--detach", str(self.worktree), "HEAD")
        self.origin_patch = patch.object(publisher, "ORIGIN_URL", self.origin.as_posix())
        self.origin_patch.start()
        self.addCleanup(self.origin_patch.stop)
        (self.worktree / "data/crypto-news.en.json").write_bytes(b'{"items":[],"translated":true}\n')

    def attempt(self, *, validator=None):
        with patch.object(publisher, "validate_pages", side_effect=validator), redirect_stdout(io.StringIO()):
            return publisher.publish(self.worktree, self.base)

    def assert_unpublished(self) -> None:
        self.assertEqual(git(self.worktree, "rev-parse", "HEAD"), self.base)
        self.assertEqual(git(self.origin, "rev-parse", "main"), self.base)

    def advance_remote(self) -> str:
        (self.source / "README.md").write_bytes(b"other publisher changed main\n")
        git(self.source, "add", "README.md")
        git(self.source, "commit", "-m", "concurrent publisher")
        git(self.source, "push", "origin", "main")
        return git(self.source, "rev-parse", "HEAD")

    def test_detached_worktree_publishes_only_allowed_outputs_and_preserves_author(self):
        def build(repository):
            (repository / "sitemap.xml").write_bytes(b"rebuilt sitemap\n")
            (repository / ".newsroom").mkdir()
            (repository / ".newsroom/translation-state.json").write_bytes(b"{}\n")
        commit = self.attempt(validator=build)
        self.assertEqual(git(self.origin, "rev-parse", "main"), commit)
        self.assertEqual(git(self.worktree, "branch", "--show-current"), "")
        self.assertEqual(git(self.worktree, "log", "-1", "--format=%an"), "Local Test Author")
        self.assertEqual(git(self.worktree, "log", "-1", "--format=%s"), publisher.COMMIT_MESSAGE)
        self.assertEqual(git(self.source, "status", "--porcelain"), "")
        self.assertEqual(git(self.source, "rev-parse", "HEAD"), self.base)

    def test_unrelated_dirty_and_staged_files_are_rejected(self):
        for staged in (False, True):
            with self.subTest(staged=staged):
                (self.worktree / "README.md").write_bytes(b"keep user change\n")
                if staged:
                    git(self.worktree, "add", "README.md")
                with self.assertRaisesRegex(publisher.PublishError, "Unrelated"):
                    self.attempt()
                self.assert_unpublished()

    def test_korean_byte_change_is_rejected_including_line_endings(self):
        (self.worktree / "data/crypto-news.json").write_bytes(b'{"items":[]}\r\n')
        with self.assertRaisesRegex(publisher.PublishError, "Korean manifest bytes"):
            self.attempt()
        self.assert_unpublished()

    def test_validation_failure_cannot_commit_or_push(self):
        with self.assertRaisesRegex(publisher.PublishError, "validation failed"):
            self.attempt(validator=publisher.PublishError("validation failed"))
        self.assert_unpublished()

    def test_unrelated_output_created_during_validation_is_rejected(self):
        def build(repository):
            (repository / "unexpected.txt").write_bytes(b"unexpected output")
        with self.assertRaisesRegex(publisher.PublishError, "Unrelated"):
            self.attempt(validator=build)
        self.assert_unpublished()

    def test_remote_advance_before_validation_is_rejected(self):
        remote = self.advance_remote()
        with self.assertRaisesRegex(publisher.PublishError, "origin/main changed"):
            self.attempt()
        self.assertEqual(git(self.worktree, "rev-parse", "HEAD"), self.base)
        self.assertEqual(git(self.origin, "rev-parse", "main"), remote)

    def test_remote_advance_during_validation_is_rejected(self):
        with self.assertRaisesRegex(publisher.PublishError, "origin/main changed"):
            self.attempt(validator=lambda _: self.advance_remote())
        self.assertEqual(git(self.worktree, "rev-parse", "HEAD"), self.base)

    def test_deletion_is_rejected(self):
        (self.worktree / "sitemap.xml").unlink()
        with self.assertRaisesRegex(publisher.PublishError, "Only additions"):
            self.attempt()
        self.assert_unpublished()

    def test_push_destination_override_is_rejected(self):
        git(self.source, "config", "remote.origin.pushurl", "https://example.invalid/other.git")
        with self.assertRaisesRegex(publisher.PublishError, "fetch and push URLs"):
            self.attempt()
        self.assert_unpublished()

    def test_main_checkout_is_rejected(self):
        with self.assertRaisesRegex(publisher.PublishError, "linked temporary worktree"):
            publisher.publish(self.source, self.base)
        self.assert_unpublished()

    def test_same_output_path_changed_after_validation_is_rejected(self):
        original = publisher.check_remote
        calls = 0
        def mutate_after_second_fetch(repository, base_head):
            nonlocal calls
            original(repository, base_head)
            calls += 1
            if calls == 2:
                (repository / "data/crypto-news.en.json").write_bytes(b"changed after validation\n")
        with patch.object(publisher, "check_remote", side_effect=mutate_after_second_fetch):
            with self.assertRaisesRegex(publisher.PublishError, "output bytes changed"):
                self.attempt()
        self.assert_unpublished()

    def test_failed_push_preserves_local_commit(self):
        original = publisher.git
        def fail_push(repository, *args):
            if args[0] == "push":
                raise publisher.PublishError("simulated push rejected")
            return original(repository, *args)
        with patch.object(publisher, "git", side_effect=fail_push):
            with self.assertRaisesRegex(publisher.PublishError, "Local commit preserved"):
                self.attempt()
        self.assertNotEqual(git(self.worktree, "rev-parse", "HEAD"), self.base)
        self.assertEqual(git(self.origin, "rev-parse", "main"), self.base)


if __name__ == "__main__":
    unittest.main()
