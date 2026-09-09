from __future__ import annotations

import base64
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "cloud_news_plan", Path(__file__).resolve().parents[1] / "scripts/cloud-news-publish-plan.py")
assert SPEC and SPEC.loader
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)

SLUG = "2026-09-09-crypto-news-0123456789"
SWISS = "2026-09-08-crypto-news-8c5a7fe969"


def github_tree(repository: Path) -> dict:
    files = list(planner.scan_files(repository).values())
    hashes = planner.tree_hashes(files)
    entries = [{key: item[key] for key in ("path", "mode", "type", "sha", "size")} for item in files]
    entries.extend({"path": path, "mode": "040000", "type": "tree", "sha": sha}
                   for path, sha in hashes.items() if path)
    return {"sha": hashes[""], "truncated": False, "tree": entries}


class CloudNewsPublishPlanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cloud-news-plan-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repository"
        self.repo.mkdir()
        self.base_path = self.root / "baseline.json"
        self.plan_path = self.root / "plan.json"
        self.base_sha = "b" * 40
        self.write("data/crypto-news.json", json.dumps({"items": [{"slug": SLUG}]}, ensure_ascii=False).encode())
        self.write("data/crypto-news.en.json", b'{"items":[]}\n')
        self.write(".newsroom/translation-state.json", b'{"items":{}}\n')
        self.write("sitemap.xml", b"<urlset></urlset>\n")
        self.write("images/binary.dat", bytes(range(256)))
        self.write("scripts/validator.py", b"print('unchanged validator')\n")
        self.write("ko/crypto-news-" + SLUG + ".html", b"Korean approved content\n")
        self.tree = github_tree(self.repo)
        self.baseline = planner.snapshot(self.repo, self.base_sha, self.tree, self.base_path)

    def write(self, path, content):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target

    def receipt(self, repository):
        return {"snapshot_hashes": {key: "a" * 64 for key in (
            "source_snapshot_hash", "english_snapshot_hash", "state_snapshot_hash")},
            "commands": [], "validated_repository_hash": planner.checksum(planner.scan_files(repository))}

    def prepare(self, validator=None):
        with patch.object(planner, "validate_pages", side_effect=validator or self.receipt):
            return planner.prepare(self.repo, self.baseline, self.plan_path)

    def assert_blocked(self, message, validator=None):
        with self.assertRaisesRegex(planner.PlanError, message):
            self.prepare(validator)
        self.assertFalse(self.plan_path.exists())

    def test_snapshot_matches_every_byte_and_object_tree(self):
        baseline = planner.validate_baseline(self.baseline)
        self.assertEqual(baseline["base_tree_sha"], self.tree["sha"])
        self.assertEqual(baseline["ko_blob_sha"], planner.object_sha("blob", (self.repo / planner.KO_PATH).read_bytes()))
        self.assertEqual(len(baseline["files"]), 7)
        binary = next(item for item in baseline["files"] if item["path"] == "images/binary.dat")
        self.assertEqual(binary["sha256"], hashlib.sha256(bytes(range(256))).hexdigest())

    def test_snapshot_missing_extra_changed_and_line_endings_are_rejected(self):
        for kind in ("missing", "extra", "changed", "line_endings"):
            with self.subTest(kind=kind):
                target = self.repo / "scripts/validator.py"
                original = target.read_bytes()
                extra = self.repo / "extra.txt"
                try:
                    if kind == "missing":
                        target.unlink()
                    elif kind == "extra":
                        extra.write_bytes(b"extra")
                    elif kind == "changed":
                        target.write_bytes(b"changed")
                    else:
                        target.write_bytes(original.replace(b"\n", b"\r\n"))
                    with self.assertRaisesRegex(planner.PlanError, "match|differs"):
                        planner.snapshot(self.repo, self.base_sha, self.tree, self.root / "bad.json")
                finally:
                    target.write_bytes(original)
                    extra.unlink(missing_ok=True)

    def test_partial_or_forged_tree_is_rejected(self):
        for kind in ("truncated", "missing_truncated", "root_sha", "subtree_sha", "missing_entry", "duplicate", "size"):
            with self.subTest(kind=kind):
                tree = copy.deepcopy(self.tree)
                if kind == "truncated":
                    tree["truncated"] = True
                elif kind == "missing_truncated":
                    del tree["truncated"]
                elif kind == "root_sha":
                    tree["sha"] = "0" * 40
                elif kind == "subtree_sha":
                    next(item for item in tree["tree"] if item["type"] == "tree")["sha"] = "0" * 40
                elif kind == "missing_entry":
                    tree["tree"].pop()
                elif kind == "duplicate":
                    tree["tree"].append(copy.deepcopy(tree["tree"][0]))
                else:
                    next(item for item in tree["tree"] if item["type"] == "blob")["size"] += 1
                with self.assertRaises(planner.PlanError):
                    planner.snapshot(self.repo, self.base_sha, tree, self.root / "bad.json")

    def test_unsafe_paths_modes_and_case_collisions_are_rejected(self):
        for path in ("../x", "/x", "x//y", "x\\y", "C:/x", ".git/config", "x/../y", "x\ny"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(planner.PlanError, "Unsafe"):
                    planner.safe_path(path)
        for mode, kind in (("120000", "blob"), ("160000", "commit"), ("040000", "blob")):
            tree = copy.deepcopy(self.tree)
            tree["tree"][0].update(mode=mode, type=kind)
            with self.assertRaises(planner.PlanError):
                planner.parse_tree(tree)
        with self.assertRaisesRegex(planner.PlanError, "Case-colliding"):
            planner.tree_hashes([
                {"path": "Data/a", "mode": "100644", "type": "blob", "sha": "a" * 40},
                {"path": "data/b", "mode": "100644", "type": "blob", "sha": "b" * 40},
            ])

    def test_root_git_worktree_metadata_is_ignored(self):
        self.write(".git", b"gitdir: unrelated metadata\n")
        again = planner.snapshot(self.repo, self.base_sha, self.tree, self.root / "again.json")
        self.assertEqual(again, self.baseline)

    @unittest.skipIf(os.name == "nt", "POSIX mode/symlink behavior is exercised on Linux")
    def test_filesystem_symlinks_and_mode_changes_are_rejected(self):
        target = self.repo / "images/binary.dat"
        target.unlink()
        target.symlink_to(self.repo / "sitemap.xml")
        with self.assertRaisesRegex(planner.PlanError, "regular"):
            planner.snapshot(self.repo, self.base_sha, self.tree, self.root / "bad.json")
        target.unlink()
        target.write_bytes(bytes(range(256)))
        target.chmod(0o755)
        with self.assertRaisesRegex(planner.PlanError, "differs"):
            planner.snapshot(self.repo, self.base_sha, self.tree, self.root / "bad.json")

    def test_noop_plan_has_empty_changes_and_same_full_tree(self):
        plan = self.prepare()
        self.assertEqual(plan["files"], [])
        self.assertEqual(plan["candidate_tree_sha"], plan["base_tree_sha"])
        self.assertEqual(plan["plan_hash"], planner.checksum({key: value for key, value in plan.items() if key != "plan_hash"}))

    def test_plan_contains_only_allowed_bytes_and_full_candidate_tree(self):
        translated = "Faithful translation, 한국어 sources preserved.\n".encode("utf-8")
        self.write("data/crypto-news.en.json", translated)
        self.write("crypto-news-" + SLUG + ".html", b"English static page\n")
        self.write("ko/crypto-news-" + SLUG + ".html", b"Korean approved content, bilingual links\n")
        plan = self.prepare()
        self.assertEqual(len(plan["files"]), 3)
        for item in plan["files"]:
            content = base64.b64decode(item["content"], validate=True)
            self.assertEqual(content, (self.repo / item["path"]).read_bytes())
            self.assertEqual(item["sha"], planner.object_sha("blob", content))
            self.assertEqual(item["mode"], "100644")
        self.assertEqual(plan["candidate_tree_sha"], github_tree(self.repo)["sha"])
        self.assertEqual(plan["ko_blob_sha"], self.baseline["ko_blob_sha"])

    def test_korean_bytes_cannot_change(self):
        original = (self.repo / planner.KO_PATH).read_bytes()
        self.write(planner.KO_PATH, original + b"\n")
        self.assert_blocked("Korean manifest")

    def test_deleted_unrelated_and_deleted_swiss_outputs_are_blocked_before_validation(self):
        for path in ("scripts/new.py", "README.md", f"crypto-news-{SWISS}.html", f"ko/crypto-news-{SWISS}.html"):
            with self.subTest(path=path):
                target = self.write(path, b"must not publish")
                with patch.object(planner, "validate_pages") as validator:
                    with self.assertRaisesRegex(planner.PlanError, "Forbidden"):
                        planner.prepare(self.repo, self.baseline, self.plan_path)
                    validator.assert_not_called()
                target.unlink()
        (self.repo / "sitemap.xml").unlink()
        self.assert_blocked("Deletion")

    def test_modified_validator_is_never_executed(self):
        self.write("scripts/validator.py", b"changed validator")
        with patch.object(planner, "validate_pages") as validator:
            with self.assertRaisesRegex(planner.PlanError, "Forbidden"):
                planner.prepare(self.repo, self.baseline, self.plan_path)
            validator.assert_not_called()

    def test_sitemap_non_news_sections_and_swiss_link_cannot_change(self):
        self.write("sitemap.xml", f"<urlset><url><loc>https://metanomia-site.vercel.app/crypto-news-{SWISS}</loc></url></urlset>\n".encode())
        self.assert_blocked("Sitemap outside")
        self.write("sitemap.xml", b"<urlset>\n<!-- GENERATED CRYPTO NEWS START -->\n<!-- GENERATED CRYPTO NEWS END -->\n</urlset>\n")
        self.assertEqual(len(self.prepare()["files"]), 1)

    def test_sitemap_ambiguous_generated_markers_are_rejected(self):
        for content in (b"<!-- GENERATED CRYPTO NEWS START -->", b"<!-- GENERATED CRYPTO NEWS END -->"):
            with self.assertRaisesRegex(planner.PlanError, "markers"):
                planner.sitemap_outside_news_hash(content)

    def test_baseline_corruption_and_wrong_target_are_rejected(self):
        for key, value in (("base_sha", "invalid"), ("repository", "other/repository"),
                           ("branch", "other"), ("baseline_hash", "0" * 64)):
            changed = copy.deepcopy(self.baseline)
            changed[key] = value
            with self.assertRaises(planner.PlanError):
                planner.validate_baseline(changed)

    def test_outputs_must_be_external_and_baseline_cannot_be_overwritten(self):
        with self.assertRaisesRegex(planner.PlanError, "outside"):
            planner.snapshot(self.repo, self.base_sha, self.tree, self.repo / "baseline.json")
        with self.assertRaisesRegex(planner.PlanError, "outside"):
            planner.prepare(self.repo, self.baseline, self.repo / "plan.json")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(planner.main(["prepare", "--repository", str(self.repo), "--baseline",
                                           str(self.base_path), "--output", str(self.base_path)]), 1)

    def test_validation_failure_does_not_emit_plan(self):
        self.assert_blocked("validation failed", validator=lambda _: (_ for _ in ()).throw(
            planner.PlanError("validation failed")))

    def test_change_during_and_after_validation_blocks_plan(self):
        def mutate_after_receipt(repository):
            receipt = self.receipt(repository)
            self.write("data/crypto-news.en.json", b"tampered after validation")
            return receipt
        self.assert_blocked("after validation", mutate_after_receipt)

    def test_change_between_plan_reads_is_blocked(self):
        original_scan = planner.scan_files
        calls = 0
        def changing_scan(repository, modes=None):
            nonlocal calls
            calls += 1
            result = original_scan(repository, modes)
            if calls == 4:
                self.write("data/crypto-news.en.json", b"tampered during packing")
            return result
        with patch.object(planner, "scan_files", side_effect=changing_scan):
            self.assert_blocked("after validation")

    def test_validation_runs_expected_commands_and_detects_writes(self):
        report = {"needs_work": False, **{key: "a" * 64 for key in (
            "source_snapshot_hash", "english_snapshot_hash", "state_snapshot_hash")}}
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            stdout = json.dumps(report).encode() if command[-1] == "status" else b"validated\n"
            return subprocess.CompletedProcess(command, 0, stdout, b"")
        with patch.object(planner.subprocess, "run", side_effect=run):
            receipt = planner.validate_pages(self.repo)
        self.assertEqual(len(commands), 5)
        self.assertTrue(all(command[1] == "-B" for command in commands))
        self.assertIn("validated_repository_hash", receipt)
        def writing_run(command, **kwargs):
            result = run(command, **kwargs)
            if command[-1] == "verify":
                self.write("data/crypto-news.en.json", b"unexpected validator write")
            return result
        with patch.object(planner.subprocess, "run", side_effect=writing_run):
            with self.assertRaisesRegex(planner.PlanError, "read-only validation"):
                planner.validate_pages(self.repo)

    def test_git_tree_hash_matches_real_git_unicode_and_directory_ordering(self):
        for path in ("한국어 문서/이름.txt", "a.txt", "a/z.txt", "a0.txt"):
            self.write(path, path.encode())
        subprocess.run(["git", "init", "--quiet"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "-c", "core.autocrlf=false", "add", "--all"], cwd=self.repo, check=True, capture_output=True)
        result = subprocess.run(["git", "write-tree"], cwd=self.repo, check=True, capture_output=True)
        self.assertEqual(result.stdout.decode().strip(), github_tree(self.repo)["sha"])


if __name__ == "__main__":
    unittest.main()
