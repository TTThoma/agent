from __future__ import annotations

import fcntl
import importlib.util
import json
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "workflow_state.py"
RULES = {
    "default_tier": "t1",
    "must_read_budget": 400,
    "rules": [
        {"glob": "core/**", "tier": "t2"},
        {"glob": "tests/fixtures/**", "tier": "t0", "skip_read": True},
    ],
}


class RepoCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo = Path(self.tempdir.name)
        self.exec_cmd("git", "init", "-b", "main")
        self.exec_cmd("git", "config", "user.name", "Test User")
        self.exec_cmd("git", "config", "user.email", "test@example.com")
        self.commit("README.md", "base\n", "base")
        self.exec_cmd("git", "branch", "origin/main")
        self.exec_cmd("git", "switch", "-c", "feature")
        self.state_dir = self.repo / ".git" / "feature-workflow-test"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def exec_cmd(self, *command: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command, cwd=self.repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check
        )

    def workflow(self, command: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self.exec_cmd(
            sys.executable, str(SCRIPT), command, "--slug", "account-export",
            "--state-dir", str(self.state_dir), *args, check=check,
        )

    def commit(self, name: str, content: str, message: str = "change") -> None:
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.exec_cmd("git", "add", name)
        self.exec_cmd("git", "commit", "-m", message)

    def write_artifact(self, name: str) -> Path:
        path = self.state_dir / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {name}\n", encoding="utf-8")
        return path

    def write_rules(self, **overrides: object) -> Path:
        path = self.state_dir / "tiers.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**RULES, **overrides}), encoding="utf-8")
        return path

    def record(self, name: str, *extra: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        arguments = ["--artifact", name]
        if name in {"brief", "verification", "cold-read", "packet", "approval"}:
            arguments.extend(["--path", str(self.write_artifact(name))])
        if name == "approval" and not extra:
            extra = ("--approver", "maintainer")
        return self.workflow("record", *arguments, *extra, check=check)

    def status(self) -> dict:
        return json.loads(self.workflow("status", "--json").stdout)

    def head(self) -> str:
        return self.exec_cmd("git", "rev-parse", "HEAD").stdout.strip()

    def advance_base(self) -> None:
        self.exec_cmd("git", "branch", "-f", "origin/main", "HEAD")

    def commit_base_rules(self, **overrides: object) -> None:
        self.commit(".feature-workflow/tiers.json", json.dumps({**RULES, **overrides}), "rules")
        self.advance_base()

    def init(self, tier: str = "t2", *extra: str) -> None:
        self.workflow("init", "--source", "issue #42", "--base-ref", "origin/main", "--tier", tier, *extra)

    def build_t2_through_approval(self) -> None:
        self.init("t2")
        self.record("brief")
        self.commit("feature.txt", "implemented\n", "implement")
        for name in ("build", "verification", "cold-read", "packet", "approval"):
            self.record(name)


class WorkflowStateTest(RepoCase):
    def test_t2_full_chain_enforces_dependencies(self) -> None:
        self.init("t2")
        self.record("brief")
        self.commit("feature.txt", "implemented\n", "implement")
        self.record("build")
        self.record("verification")
        refused = self.record("packet", check=False)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("cold-read", refused.stderr)
        self.record("cold-read")
        self.record("packet")
        self.assertIn("--approver", self.workflow("record", "--artifact", "approval", "--path",
                                                  str(self.write_artifact("approval")), check=False).stderr)
        self.record("approval", "--approver", "alice", "--evidence-url", "https://example.test/pr/1#c1")
        wrong = self.record("published", "--remote-sha", "0" * 40, check=False)
        self.assertIn("does not match HEAD", wrong.stderr)
        self.record("published", "--url", "https://example.test/pr/1", "--remote-sha", self.head())
        report = self.status()
        self.assertTrue(report["complete"])
        self.assertIsNone(report["next_artifact"])
        self.assertEqual(report["path_floor"], "t2")
        state = json.loads((self.state_dir / "state.json").read_text())
        self.assertEqual(state["schema_version"], 2)
        self.assertEqual(state["artifacts"]["approval"]["approver"], "alice")
        self.assertEqual(state["artifacts"]["published"]["remote_sha"], self.head())

    def test_t1_records_packet_without_cold_read(self) -> None:
        self.init("t1", "--rules", str(self.write_rules()))
        self.record("brief")
        self.commit("feature.txt", "implemented\n", "implement")
        for name in ("build", "verification", "packet"):
            self.record(name)
        report = self.status()
        self.assertEqual(report["artifacts"]["cold-read"]["status"], "absent")
        self.assertFalse(report["artifacts"]["cold-read"]["required"])
        self.assertEqual(report["artifacts"]["packet"]["status"], "current")
        self.assertEqual(report["next_artifact"], "approval")

    def test_new_patch_makes_verification_and_approval_stale(self) -> None:
        self.build_t2_through_approval()
        self.assertEqual(self.status()["next_artifact"], "published")
        self.commit("feature.txt", "changed after approval\n")
        report = self.status()
        self.assertEqual(report["next_artifact"], "build")
        self.assertEqual(report["artifacts"]["brief"]["status"], "current")
        self.assertEqual(report["artifacts"]["verification"]["status"], "stale")
        self.assertIn("HEAD changed", report["artifacts"]["verification"]["reasons"])
        self.assertEqual(report["artifacts"]["approval"]["status"], "stale")
        self.assertIn("patch changed", report["artifacts"]["approval"]["reasons"])

    def test_patch_identical_rebase_keeps_approval(self) -> None:
        self.build_t2_through_approval()
        self.exec_cmd("git", "switch", "origin/main")
        self.commit("unrelated.txt", "upstream\n", "upstream")
        self.exec_cmd("git", "switch", "feature")
        self.exec_cmd("git", "rebase", "origin/main")

        report = self.status()
        self.assertEqual(report["artifacts"]["verification"]["status"], "stale")
        self.assertIn("base SHA changed", report["artifacts"]["verification"]["reasons"])
        for name in ("cold-read", "packet", "approval"):
            self.assertEqual(report["artifacts"][name]["status"], "current", name)
            self.assertEqual(report["artifacts"][name]["notes"], ["rebased; patch identical"])
        self.assertEqual(report["next_artifact"], "build")
        self.assertIn("dependencies are not current", self.record("published", check=False).stderr)

        self.record("build")
        self.record("verification")
        report = self.status()
        self.assertEqual(report["next_artifact"], "published")
        self.assertEqual(report["artifacts"]["approval"]["status"], "current")
        self.record("published")
        self.assertTrue(self.status()["complete"])

    def test_tier_below_path_floor_blocks_packet_until_raised(self) -> None:
        self.init("t1", "--rules", str(self.write_rules()))
        self.record("brief")
        self.commit("core/engine.py", "route = 1\n", "core change")
        self.record("build")
        self.record("verification")
        report = self.status()
        self.assertEqual(report["path_floor"], "t2")
        self.assertEqual([gate["gate"] for gate in report["gates"]], ["tier below path floor"])
        refused = self.record("packet", check=False)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("tier below path floor", refused.stderr)

        raised = json.loads(self.workflow("set-tier", "--tier", "t2").stdout)
        self.assertEqual(raised["gates"], [])
        self.assertEqual(raised["artifacts"]["build"]["status"], "stale")
        for name in ("build", "verification", "cold-read", "packet"):
            self.record(name)
        self.assertEqual(self.status()["next_artifact"], "approval")

    def test_must_read_budget_requires_split(self) -> None:
        self.init("t2", "--rules", str(self.write_rules(must_read_budget=5)))
        self.record("brief")
        self.commit("core/big.py", "".join(f"line{i}\n" for i in range(10)), "big core change")
        for name in ("build", "verification", "cold-read"):
            self.record(name)
        report = self.status()
        self.assertEqual(report["must_read_lines"], 10)
        self.assertIn("split required", [gate["gate"] for gate in report["gates"]])
        refused = self.record("packet", check=False)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("split the PR", refused.stderr)

    def test_budget_override_accepts_marked_lines_within_budget(self) -> None:
        self.init("t2", "--rules", str(self.write_rules(must_read_budget=5)))
        self.record("brief")
        self.commit("core/big.py", "".join(f"line{i}\n" for i in range(10)), "big core change")
        for name in ("build", "verification", "cold-read"):
            self.record(name)
        self.assertIn("split the PR", self.record("packet", check=False).stderr)
        self.assertIn("both", self.record("packet", "--marked-lines", "4", check=False).stderr)
        blank = self.record("packet", "--marked-lines", "4", "--budget-override-reason", "  ", check=False)
        self.assertIn("both", blank.stderr)
        over = self.record("packet", "--marked-lines", "6", "--budget-override-reason", "money lines", check=False)
        self.assertIn("exceeds budget 5", over.stderr)
        self.record("packet", "--marked-lines", "4", "--budget-override-reason", "only money lines need reading")
        report = self.status()
        self.assertEqual(report["artifacts"]["packet"]["status"], "current")
        self.assertIn("split required", [gate["gate"] for gate in report["gates"]])
        self.assertEqual({key: report["budget_overrides"][0][key] for key in ("must_read_lines", "marked_lines")},
                         {"must_read_lines": 10, "marked_lines": 4})
        self.assertIn("budget override: 4 marked of 10", self.workflow("status").stdout)
        self.record("approval")
        self.assertIn("split the PR", self.record("packet", check=False).stderr)  # per packet revision

    def test_budget_flags_without_split_gate_are_refused(self) -> None:
        self.init("t2", "--rules", str(self.write_rules()))
        self.record("brief")
        self.commit("core/a.py", "a\n", "small")
        for name in ("build", "verification", "cold-read"):
            self.record(name)
        refused = self.record("packet", "--marked-lines", "1", "--budget-override-reason", "x", check=False)
        self.assertIn("no split-required gate", refused.stderr)
        self.record("packet")

    def test_lowering_tier_requires_reason(self) -> None:
        self.init("t2")
        refused = self.workflow("set-tier", "--tier", "t1", check=False)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("--reason", refused.stderr)
        self.workflow("set-tier", "--tier", "t1", "--reason", "conformance suite covers it")
        state = json.loads((self.state_dir / "state.json").read_text())
        self.assertEqual(state["tier"], "t1")
        self.assertEqual(state["tier_changes"][0]["from"], "t2")
        self.assertEqual(state["tier_changes"][0]["reason"], "conformance suite covers it")

    def test_v1_state_file_is_rejected(self) -> None:
        self.state_dir.mkdir(parents=True)
        (self.state_dir / "state.json").write_text(json.dumps({"schema_version": 1, "artifacts": {}}))
        result = self.workflow("status", "--json", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("v1 run ledger", result.stderr)

    def test_classify_reports_files_floor_and_must_read(self) -> None:
        self.init("t2", "--rules", str(self.write_rules()))
        self.commit("core/a.py", "a\nb\nc\n")
        self.commit("tests/fixtures/f.json", "{}\n{}\n")
        self.commit("docs/guide.md", "doc\n")
        result = json.loads(self.workflow("classify").stdout)
        files = {item["path"]: item for item in result["files"]}
        self.assertEqual(set(files), {"core/a.py", "tests/fixtures/f.json", "docs/guide.md"})
        self.assertEqual(set(files["core/a.py"]),
                         {"path", "old_path", "added", "deleted", "binary", "tier", "skip_read", "must_read"})
        self.assertEqual((files["core/a.py"]["tier"], files["core/a.py"]["added"]), ("t2", 3))
        self.assertEqual((files["tests/fixtures/f.json"]["tier"], files["tests/fixtures/f.json"]["skip_read"]),
                         ("t0", True))
        self.assertEqual(files["docs/guide.md"]["tier"], "t1")
        self.assertEqual(result["path_floor"], "t2")
        self.assertEqual(result["must_read_lines"], 3)
        self.assertEqual(result["must_read_budget"], 400)

    def test_classify_without_rules_fails_closed(self) -> None:
        self.init("t1")
        self.commit("core/a.py", "a\nb\n")
        self.commit("tests/test_a.py", "x\ny\nz\n")
        result = json.loads(self.workflow("classify").stdout)
        self.assertEqual(result["path_floor"], "t2")
        self.assertIsNone(result["must_read_budget"])
        self.assertEqual(result["must_read_lines"], 5)
        self.assertEqual({item["tier"] for item in result["files"]}, {"t2"})
        gates = {gate["gate"]: gate["blocks"] for gate in result["gates"]}
        self.assertEqual(gates["no rules file found"], [])
        self.assertIn("tier below path floor", gates)

    def test_rules_override_requires_reason(self) -> None:
        first, second = self.write_rules(), self.state_dir / "other.json"
        second.write_text(json.dumps({**RULES, "must_read_budget": 7}), encoding="utf-8")
        self.init("t2", "--rules", str(first))
        refused = self.workflow("status", "--json", "--rules", str(second), check=False)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("--rules-override-reason", refused.stderr)
        self.assertEqual(self.status()["must_read_budget"], 400)
        self.workflow("status", "--json", "--rules", str(second), "--rules-override-reason", "budget review")
        self.assertEqual(self.status()["must_read_budget"], 7)
        state = json.loads((self.state_dir / "state.json").read_text())
        self.assertEqual(state["rules_path"], str(second.resolve()))
        change = state["rules_changes"][0]
        self.assertEqual((change["path"], change["reason"]), (str(second.resolve()), "budget review"))
        self.assertNotEqual(change["from_sha"], change["to_sha"])
        self.assertEqual(self.workflow("status", "--rules", str(second), check=False).returncode, 0)

    def test_pure_rename_counts_zero_and_floors_at_max_tier(self) -> None:
        self.commit_base_rules()
        self.commit("core/engine.py", "".join(f"line{i}\n" for i in range(10)), "engine")
        self.advance_base()
        self.init("t2")
        (self.repo / "docs").mkdir()
        self.exec_cmd("git", "mv", "core/engine.py", "docs/engine.py")
        self.exec_cmd("git", "commit", "-m", "move")
        result = json.loads(self.workflow("classify").stdout)
        self.assertEqual(len(result["files"]), 1)
        moved = result["files"][0]
        self.assertEqual((moved["old_path"], moved["path"], moved["tier"]), ("core/engine.py", "docs/engine.py", "t2"))
        self.assertEqual((result["path_floor"], result["must_read_lines"]), ("t2", 0))
        self.commit("docs/engine.py", "".join(f"line{i}\n" for i in range(9)) + "edited\n", "edit")
        result = json.loads(self.workflow("classify").stdout)
        self.assertEqual(result["files"][0]["old_path"], "core/engine.py")
        self.assertEqual((result["must_read_added"], result["must_read_deleted"]), (1, 1))

    def test_t2_deletions_count_as_must_read(self) -> None:
        self.commit_base_rules()
        self.commit("core/big.py", "".join(f"line{i}\n" for i in range(10)), "big")
        self.advance_base()
        self.init("t2")
        self.commit("core/big.py", "".join(f"line{i}\n" for i in range(6)), "trim")
        result = json.loads(self.workflow("classify").stdout)
        self.assertEqual((result["must_read_lines"], result["must_read_added"], result["must_read_deleted"]),
                         (4, 0, 4))

    def test_attributes_cannot_hide_t2_lines(self) -> None:
        self.commit_base_rules()
        self.init("t2")
        self.commit(".gitattributes", "core/** -diff\n", "attributes")
        self.commit("core/hidden.py", "".join(f"line{i}\n" for i in range(6)), "hidden")
        result = json.loads(self.workflow("classify").stdout)
        self.assertEqual(result["must_read_lines"], 6)
        first = self.status()["patch_id"]
        self.commit("core/hidden.py", "".join(f"line{i}\n" for i in range(7)), "more hidden")
        self.assertNotEqual(self.status()["patch_id"], first)

    def test_hidden_submodule_bump_is_classified(self) -> None:
        self.commit_base_rules()
        self.exec_cmd("git", "update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},core/vendor")
        self.exec_cmd("git", "commit", "-m", "vendor")
        (self.repo / "core" / "vendor").mkdir(parents=True)
        self.advance_base()
        self.init("t0")
        self.commit(".gitmodules", '[submodule "v"]\n\tpath = core/vendor\n\turl = x\n\tignore = all\n')
        self.exec_cmd("git", "update-index", "--cacheinfo", f"160000,{'2' * 40},core/vendor")
        self.exec_cmd("git", "commit", "-m", "bump")
        result = json.loads(self.workflow("classify").stdout)
        self.assertIn("core/vendor", [item["path"] for item in result["files"]])
        self.assertEqual(result["path_floor"], "t2")

    def test_rename_into_t2_counts_the_whole_file(self) -> None:
        self.commit_base_rules()
        self.commit("tests/fixtures/helper.py", "".join(f"line{i}\n" for i in range(5)), "helper")
        self.advance_base()
        self.init("t2")
        (self.repo / "core").mkdir()
        self.exec_cmd("git", "mv", "tests/fixtures/helper.py", "core/helper.py")
        self.exec_cmd("git", "commit", "-m", "promote")
        result = json.loads(self.workflow("classify").stdout)
        self.assertEqual(result["files"][0]["old_path"], "tests/fixtures/helper.py")
        self.assertEqual((result["path_floor"], result["must_read_lines"]), ("t2", 5))

    def test_rules_found_in_ancestor_from_every_worktree_layout(self) -> None:
        workspace = self.repo / "workspace"  # not a git repository itself
        main = workspace / "backend-main"  # differs from the origin name: the rules file name must come from origin
        main.mkdir(parents=True)
        origin = "git@github.com:example-org/backend.git"
        for command in (("init", "-q", "-b", "main"), ("remote", "add", "origin", origin),
                        ("-c", "user.name=T", "-c", "user.email=t@e", "commit", "-q", "--allow-empty", "-m", "base")):
            subprocess.run(["git", *command], cwd=main, check=True)
        rules = workspace / ".feature-workflow" / "backend.tiers.json"
        rules.parent.mkdir()
        rules.write_text(json.dumps(RULES), encoding="utf-8")
        shadow = main / ".feature-workflow" / "backend.tiers.json"  # branch-controlled: must be skipped
        shadow.parent.mkdir()
        shadow.write_text(json.dumps({"default_tier": "t0", "rules": []}), encoding="utf-8")
        layouts = (workspace / ".worktrees" / "x", workspace / "backend-dev-1",
                   main / ".claude" / "worktrees" / "agent-1")
        for index, tree in enumerate(layouts):
            subprocess.run(["git", "worktree", "add", "-q", "-b", f"w{index}", str(tree)], cwd=main, check=True)
            state_dir = self.repo / f"state-{index}"
            common = ["--slug", "s", "--state-dir", str(state_dir), "--repo", str(tree)]
            for command in (["init", *common, "--source", "x", "--base-ref", "main"], ["status", *common, "--json"]):
                result = subprocess.run([sys.executable, str(SCRIPT), *command], cwd=tree, text=True,
                                        capture_output=True, check=True)
            report = json.loads(result.stdout)
            self.assertEqual(report["rules_path"], str(rules.resolve()), tree)
            self.assertEqual(report["rules_pin"]["path"], str(rules.resolve()))
            self.assertEqual(report["gates"], [])

    def test_in_repo_rules_fallback(self) -> None:
        self.commit_base_rules()
        self.init("t1")
        self.commit("core/engine.py", "route = 1\n", "core change")
        report = self.status()
        self.assertEqual(report["rules_path"], str((self.repo / ".feature-workflow" / "tiers.json").resolve()))
        self.assertEqual(report["path_floor"], "t2")

    def test_changed_rules_block_until_repinned(self) -> None:
        rules = self.write_rules()
        self.init("t2", "--rules", str(rules))
        self.record("brief")
        self.commit("core/engine.py", "route = 1\n", "core change")
        for name in ("build", "verification", "cold-read"):
            self.record(name)
        pinned = self.status()["rules_sha256"]
        rules.write_text(json.dumps({**RULES, "default_tier": "t0"}), encoding="utf-8")
        report = self.status()
        self.assertEqual([gate["gate"] for gate in report["gates"]], ["rules changed since run start"])
        self.assertIn(pinned, report["gates"][0]["detail"])
        self.assertIn(report["rules_sha256"], report["gates"][0]["detail"])
        self.assertIn("rules changed since run start", self.record("packet", check=False).stderr)
        self.assertEqual(self.workflow("set-rules", check=False).returncode, 2)
        self.workflow("set-rules", "--reason", "maintainer tightened docs tiers")
        self.assertEqual(self.status()["gates"], [])
        self.record("packet")
        state = json.loads((self.state_dir / "state.json").read_text())
        change = state["rules_changes"][0]
        self.assertEqual((change["from_sha"], change["to_sha"], change["path"]),
                         (pinned, report["rules_sha256"], str(rules.resolve())))
        self.assertIn("nothing to re-pin", self.workflow("set-rules", "--reason", "again", check=False).stderr)

    def test_deleted_rules_block_packet(self) -> None:
        rules = self.write_rules()
        self.init("t2", "--rules", str(rules))
        self.record("brief")
        self.commit("feature.txt", "implemented\n", "implement")
        for name in ("build", "verification", "cold-read"):
            self.record(name)
        rules.unlink()
        report = self.status()
        self.assertEqual(report["gates"][0]["gate"], "rules changed since run start")
        self.assertIn("no rules", report["gates"][0]["detail"])
        refused = self.record("packet", check=False)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("rules changed since run start", refused.stderr)
        self.assertIn("cannot be re-pinned to no rules",
                      self.workflow("set-rules", "--reason", "drop rules", check=False).stderr)

    def test_unpinned_legacy_run_blocks_until_pinned(self) -> None:
        self.init("t2", "--rules", str(self.write_rules()))
        state_file = self.state_dir / "state.json"
        state = json.loads(state_file.read_text())
        del state["rules_pin"]
        state_file.write_text(json.dumps(state), encoding="utf-8")
        self.assertIn("predates rules pinning", self.status()["gates"][0]["detail"])
        self.workflow("set-rules", "--reason", "pin legacy run")
        self.assertEqual(self.status()["gates"], [])

    def test_newline_in_path_still_matches_globs(self) -> None:
        self.init("t1", "--rules", str(self.write_rules()))
        self.commit("core/sub\ndir/rates.json", "{}\n", "odd path")
        result = json.loads(self.workflow("classify").stdout)
        self.assertEqual((result["files"][0]["tier"], result["path_floor"], result["must_read_lines"]), ("t2", "t2", 1))

    def merge_into_main(self, extra: str | None = None) -> str:
        self.exec_cmd("git", "switch", "-q", "origin/main")
        self.commit("upstream.txt", "upstream\n", "upstream")
        self.exec_cmd("git", "merge", "--no-ff", "--no-commit", "feature")
        if extra:
            (self.repo / "feature.txt").write_text(extra, encoding="utf-8")
            self.exec_cmd("git", "add", "feature.txt")
        self.exec_cmd("git", "commit", "-q", "-m", "merge feature")
        merge = self.head()
        self.exec_cmd("git", "switch", "-q", "feature")
        return merge

    def test_published_after_merge_binds_to_merge_commit(self) -> None:
        self.build_t2_through_approval()
        merge = self.merge_into_main()
        report = self.status()
        self.assertTrue(report["merged"])
        self.assertEqual(report["artifacts"]["build"]["status"], "current")
        self.assertEqual(report["next_artifact"], "published")
        self.assertIn("--remote-sha", self.record("published", check=False).stderr)
        stray = self.exec_cmd("git", "commit-tree", "HEAD^{tree}", "-p", merge, "-m", "stray").stdout.strip()
        self.assertIn("first-parent line", self.record("published", "--remote-sha", stray, check=False).stderr)
        self.record("published", "--url", "https://example.test/pr/1", "--remote-sha", merge)
        self.assertTrue(self.status()["complete"])
        state = json.loads((self.state_dir / "state.json").read_text())
        published = state["artifacts"]["published"]
        self.assertEqual((published["remote_sha"], published["merge_patch_id"]),
                         (merge, state["artifacts"]["approval"]["patch_id"]))

    def test_published_refuses_merge_with_different_patch(self) -> None:
        self.build_t2_through_approval()
        merge = self.merge_into_main(extra="changed in the merge\n")
        refused = self.record("published", "--remote-sha", merge, check=False)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("not the approved patch", refused.stderr)

    def test_published_refuses_branch_commit_under_an_evil_merge(self) -> None:
        self.build_t2_through_approval()
        merge = self.merge_into_main(extra="changed in the merge\n")
        self.assertIn("not the approved patch", self.record("published", "--remote-sha", merge, check=False).stderr)
        refused = self.record("published", "--remote-sha", self.head(), check=False)
        self.assertIn("first-parent line", refused.stderr)

    def test_published_after_fast_forward_of_several_commits(self) -> None:
        self.init("t2")
        self.record("brief")
        self.commit("feature.txt", "one\n", "first")
        self.commit("other.txt", "two\n", "second")
        for name in ("build", "verification", "cold-read", "packet", "approval"):
            self.record(name)
        self.advance_base()
        self.assertTrue(self.status()["merged"])
        self.record("published", "--remote-sha", self.head())
        self.assertTrue(self.status()["complete"])

    def test_unpinned_run_cannot_adopt_in_tree_rules(self) -> None:
        self.init("t0")
        self.commit(".feature-workflow/tiers.json", json.dumps({"default_tier": "t0"}), "self-classify")
        refused = self.workflow("set-rules", "--reason", "x", check=False)
        self.assertIn("cannot adopt the in-tree fallback", refused.stderr)

    def squash_into_main(self, extra: str | None = None) -> str:
        self.exec_cmd("git", "switch", "-q", "origin/main")
        self.commit("upstream.txt", "upstream\n", "upstream")
        self.exec_cmd("git", "merge", "--squash", "feature")
        if extra:
            with (self.repo / "feature.txt").open("a", encoding="utf-8") as handle:
                handle.write(extra)
            self.exec_cmd("git", "add", "feature.txt")
        self.exec_cmd("git", "commit", "-q", "-m", "squash feature")
        squash = self.head()
        self.exec_cmd("git", "switch", "-q", "feature")
        return squash

    def test_published_after_squash_merge(self) -> None:
        self.build_t2_through_approval()
        squash = self.squash_into_main()
        self.exec_cmd("git", "switch", "-q", "--detach", squash)  # HEAD need not stay on the branch
        self.record("published", "--url", "https://example.test/pr/1", "--remote-sha", squash)
        report = self.status()
        self.assertTrue(report["complete"])
        self.assertTrue(report["squashed"])
        published = json.loads((self.state_dir / "state.json").read_text())["artifacts"]["published"]
        self.assertEqual((published["landing"], published["remote_sha"]), ("squash", squash))

    def test_squash_publish_closes_run_and_needs_current_patch(self) -> None:
        self.build_t2_through_approval()
        squash = self.squash_into_main()
        self.commit("evil.txt", "after approval\n", "unreviewed")
        refused = self.record("published", "--remote-sha", squash, check=False)
        self.assertIn("HEAD carries patch", refused.stderr)
        self.exec_cmd("git", "reset", "-q", "--hard", "HEAD~1")
        self.record("published", "--remote-sha", squash)
        self.assertIn("run is closed", self.record("build", check=False).stderr)

    def test_published_refuses_squash_older_than_build_base(self) -> None:
        self.exec_cmd("git", "switch", "-q", "origin/main")
        self.commit("feature.txt", "implemented\n", "early squash")
        early = self.head()
        self.exec_cmd("git", "revert", "--no-edit", "HEAD")
        self.exec_cmd("git", "switch", "-q", "-C", "feature")
        self.build_t2_through_approval()
        refused = self.record("published", "--remote-sha", early, check=False)
        self.assertEqual(refused.returncode, 1)

    def test_published_refuses_squash_with_extra_line(self) -> None:
        self.build_t2_through_approval()
        squash = self.squash_into_main(extra="sneaked in\n")
        refused = self.record("published", "--remote-sha", squash, check=False)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("not the approved patch", refused.stderr)

    def test_published_refuses_squash_not_on_main(self) -> None:
        self.build_t2_through_approval()
        self.exec_cmd("git", "switch", "-q", "--detach", "origin/main")
        self.commit("feature.txt", "implemented\n", "off-main squash")
        stray = self.head()
        self.exec_cmd("git", "switch", "-q", "feature")
        refused = self.record("published", "--remote-sha", stray, check=False)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("not on origin/main's first-parent line", refused.stderr)

    @unittest.skipUnless(subprocess.run(["git", "patch-id", "--verbatim"], input=b"", capture_output=True)
                         .returncode == 0, "git patch-id --verbatim needs git >= 2.40")
    def test_reindent_after_approval_goes_stale(self) -> None:
        self.init("t2")
        self.record("brief")
        self.commit("feature.py", "if x:\n    y()\n", "implement")
        for name in ("build", "verification", "cold-read", "packet", "approval"):
            self.record(name)
        self.commit("feature.py", "if x:\n  y()\n", "reindent")
        self.assertIn("patch changed", self.status()["artifacts"]["approval"]["reasons"])

    def test_changed_brief_invalidates_consumers_and_explicit_invalidation(self) -> None:
        self.init("t2")
        self.record("brief")
        self.record("build")
        source = self.state_dir / "brief.md"
        source.write_text("# shared brief edited by another run\n", encoding="utf-8")
        self.assertEqual(self.status()["artifacts"]["brief"]["status"], "current")
        brief = json.loads((self.state_dir / "state.json").read_text())["artifacts"]["brief"]
        self.assertEqual((brief["source_path"], Path(brief["path"]).name), (str(source.resolve()), "brief.1.md"))
        Path(brief["path"]).write_text("# revised brief\n", encoding="utf-8")
        report = self.status()
        self.assertEqual(report["artifacts"]["brief"]["status"], "stale")
        self.assertEqual(report["artifacts"]["build"]["status"], "stale")
        self.record("brief")
        self.record("build")
        result = json.loads(self.workflow("invalidate", "--from", "build", "--reason", "review changes").stdout)
        self.assertEqual(result["affected"], ["build"])
        self.assertIn("review changes", self.status()["artifacts"]["build"]["reasons"])


STUB = """import json, pathlib, sys
log, command = pathlib.Path(sys.argv[1]), sys.argv[2]
with log.open("a") as handle:
    handle.write(json.dumps(sys.argv[2:]) + "\\n")
if command == "pr-head":
    print(pathlib.Path(sys.argv[3]).read_text().strip())
if command == "move":  # a push lands while approve runs
    pathlib.Path(sys.argv[3]).write_text(sys.argv[4])
sys.exit(3 if command == "fail" else 0)
"""


def load_module():
    spec = importlib.util.spec_from_file_location("workflow_state", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LandingTest(RepoCase):
    """approve and carry against argv-logging stub commands; nothing reaches gh or the network."""

    def setUp(self) -> None:
        super().setUp()
        self.log = self.state_dir / "calls.jsonl"
        self.pr_head_file = self.state_dir / "pr-head"
        stub = self.state_dir / "stub.py"
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_text(STUB, encoding="utf-8")
        prefix = f"{shlex.quote(sys.executable)} {shlex.quote(str(stub))} {shlex.quote(str(self.log))}"
        self.project = {
            "pr_head": f"{prefix} pr-head {shlex.quote(str(self.pr_head_file))} {{pr}}",
            "approval_status": f"{prefix} status {{sha}} {{patch_id}} {{approver}} {{date}}",
            "mark_ready": f"{prefix} ready {{pr}}",
            "merge_mode": "bot",
        }

    def write_project(self, **overrides: object) -> Path:
        path = self.state_dir / "project.json"
        path.write_text(json.dumps({**self.project, **overrides}), encoding="utf-8")
        return path

    def land(self, command: str, *extra: str, check: bool = False) -> subprocess.CompletedProcess[str]:
        return self.workflow(command, "--pr", "7", "--project", str(self.write_project()), *extra, check=check)

    def calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def publish_head(self) -> None:
        self.pr_head_file.write_text(self.head() + "\n", encoding="utf-8")

    def approved_run(self) -> None:
        self.init("t2", "--rules", str(self.write_rules()))
        self.record("brief")
        self.commit("core/engine.py", "route = 1\n", "core")
        self.commit("tests/fixtures/rows.json", "[1]\n", "fixture")
        for name in ("build", "verification", "cold-read", "packet"):
            self.record(name)
        self.publish_head()
        result = self.land("approve", "--approver", "Ann Lee")
        self.assertEqual(result.returncode, 0, result.stderr)

    def rebase_onto_upstream(self) -> None:
        self.exec_cmd("git", "switch", "origin/main")
        self.commit("upstream.txt", "upstream\n", "upstream")
        self.exec_cmd("git", "switch", "feature")
        self.exec_cmd("git", "rebase", "origin/main")

    def test_approve_sets_status_marks_ready_and_records(self) -> None:
        self.approved_run()
        report = self.status()
        self.assertEqual(report["artifacts"]["approval"]["status"], "current")
        self.assertEqual([call[0] for call in self.calls()], ["pr-head", "ready", "pr-head", "status"])
        ready, status = self.calls()[1], self.calls()[3]
        self.assertEqual(status[:4], ["status", self.head(), report["patch_id"], "Ann Lee"])  # one argv element
        self.assertEqual(ready, ["ready", "7"])
        approval = json.loads((self.state_dir / "state.json").read_text())["artifacts"]["approval"]
        self.assertEqual((approval["approver"], approval["patch_id"], approval["pr"]),
                         ("Ann Lee", report["patch_id"], "7"))
        self.assertEqual([item["argv"][3] for item in approval["commands"]], ["ready", "status"])

    def test_approve_refuses_head_mismatch(self) -> None:
        self.init("t2", "--rules", str(self.write_rules()))
        self.record("brief")
        self.commit("core/engine.py", "route = 1\n", "core")
        for name in ("build", "verification", "cold-read", "packet"):
            self.record(name)
        self.publish_head()
        self.commit("core/engine.py", "route = 2\n", "unpushed")
        for name in ("build", "verification", "cold-read", "packet"):
            self.record(name)
        refused = self.land("approve", "--approver", "ann")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("is not the PR head", refused.stderr)
        self.assertEqual([call[0] for call in self.calls()], ["pr-head"])
        self.assertEqual(self.status()["artifacts"]["approval"]["status"], "absent")

    def test_approve_refuses_stale_artifacts(self) -> None:
        self.init("t2", "--rules", str(self.write_rules()))
        self.record("brief")
        self.commit("core/engine.py", "route = 1\n", "core")
        for name in ("build", "verification", "cold-read", "packet"):
            self.record(name)
        self.commit("core/engine.py", "route = 2\n", "after packet")
        self.publish_head()
        refused = self.land("approve", "--approver", "ann")
        self.assertIn("cannot approve", refused.stderr)
        self.assertIn("packet (stale", refused.stderr)
        self.assertEqual(self.calls(), [])

    def test_approve_dry_run_prints_argv_and_changes_nothing(self) -> None:
        self.init("t2", "--rules", str(self.write_rules()))
        self.record("brief")
        self.commit("core/engine.py", "route = 1\n", "core")
        for name in ("build", "verification", "cold-read", "packet"):
            self.record(name)
        self.publish_head()
        del self.project["mark_ready"]  # missing key: the default `gh pr ready {pr}`, printed, never run
        before = (self.state_dir / "state.json").read_text()
        result = self.land("approve", "--approver", "ann", "--dry-run", check=True)
        plan = json.loads(result.stdout)["would_run"]
        patch = self.status()["patch_id"]
        self.assertEqual(plan["mark_ready"], ["gh", "pr", "ready", "7"])
        self.assertEqual(plan["approval_status"][2:6], [str(self.log), "status", self.head(), patch])
        self.assertEqual(plan["pr_head"][3], "pr-head")
        self.assertEqual(self.calls(), [])  # not even the pr_head read
        self.assertEqual((self.state_dir / "state.json").read_text(), before)

    def test_carry_accepts_skip_read_change_after_rebase(self) -> None:
        self.approved_run()
        self.rebase_onto_upstream()
        self.commit("tests/fixtures/rows.json", "[1, 2]\n", "conflict resolution")
        self.publish_head()
        self.assertIn("build (stale", self.land("carry").stderr)  # verification first, on the new head
        self.record("build")
        self.record("verification")
        result = self.land("carry")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(),
                         f"carried approval for PR 7 to {self.head()}: only tests/fixtures/rows.json changed; this will merge")
        self.assertEqual(self.calls()[-1][:3], ["status", self.head(), self.status()["patch_id"]])
        self.assertIn("carry r", self.workflow("status").stdout)
        report = self.status()
        for name in ("cold-read", "packet", "approval"):
            self.assertEqual(report["artifacts"][name]["status"], "current", name)
        self.assertIn("approval carried: only tests/fixtures/rows.json changed",
                      report["artifacts"]["approval"]["notes"])
        self.record("published", "--remote-sha", self.head())
        self.assertTrue(self.status()["complete"])

    def test_carry_refuses_must_read_and_non_skip_changes(self) -> None:
        self.approved_run()
        self.rebase_onto_upstream()
        self.commit("core/engine.py", "route = 1\nfallback = 2\n", "conflict resolution")
        for name in ("build", "verification"):
            self.record(name)
        self.publish_head()
        refused = self.land("carry")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("re-approval needed: must-read changed in core/engine.py", refused.stderr)
        self.exec_cmd("git", "reset", "--hard", "HEAD~1")
        self.commit("notes.txt", "t1, not skip-read\n", "t1 change")
        for name in ("build", "verification"):
            self.record(name)
        self.publish_head()
        self.assertIn("notes.txt changed and not skip-read", self.land("carry").stderr)
        self.assertEqual(self.status()["artifacts"]["approval"]["status"], "stale")
        self.assertEqual([call[0] for call in self.calls()], ["pr-head", "ready", "pr-head", "status"])

    def test_carry_after_identical_rebase_resets_status(self) -> None:
        self.approved_run()
        self.rebase_onto_upstream()
        self.record("build")
        self.record("verification")
        self.publish_head()
        result = self.land("carry", check=True)
        self.assertIn("patch identical, no files changed", result.stdout)
        self.assertEqual(self.calls()[-1][1], self.head())

    def carry_fixture_change(self) -> str:
        """Approve, then carry to a fixture-only change; returns the approved head."""
        self.approved_run()
        approved_head = self.head()
        self.commit("tests/fixtures/rows.json", "[1, 2]\n", "fixture fix")
        self.record("build")
        self.record("verification")
        self.publish_head()
        self.assertEqual(self.land("carry").returncode, 0)
        return approved_head

    def test_reapprove_after_carry_stays_current(self) -> None:
        self.carry_fixture_change()
        self.assertEqual(self.land("approve", "--approver", "ann").returncode, 0)
        report = self.status()
        for name in ("cold-read", "packet", "approval"):
            self.assertEqual(report["artifacts"][name]["status"], "current", name)

    def test_merge_of_approved_patch_publishes_after_carry_is_undone(self) -> None:
        approved_head = self.carry_fixture_change()
        self.exec_cmd("git", "reset", "-q", "--hard", approved_head)
        self.record("build")
        self.record("verification")
        self.exec_cmd("git", "switch", "-q", "origin/main")
        self.exec_cmd("git", "merge", "-q", "--no-ff", "feature", "-m", "merge feature")
        merge = self.head()
        self.exec_cmd("git", "switch", "-q", "feature")
        self.record("published", "--remote-sha", merge)
        self.assertTrue(self.status()["complete"])

    def test_landing_refuses_option_like_pr_and_branch_controlled_config(self) -> None:
        self.init("t2", "--rules", str(self.write_rules()))
        self.record("brief")
        self.commit("core/engine.py", "route = 1\n", "core")
        self.commit(".feature-workflow/project.json", json.dumps(self.project), "config in the branch")
        for name in ("build", "verification", "cold-read", "packet"):
            self.record(name)
        self.publish_head()
        option = self.workflow("approve", "--pr=--undo", "--approver", "ann", check=False)
        self.assertIn("out-of-set values: {pr}='--undo'", option.stderr)
        for approver in ("-x", "a;b", "$(id)"):
            refused = self.workflow("approve", "--pr", "7", f"--approver={approver}", check=False)
            self.assertIn("out-of-set values: {approver}", refused.stderr, approver)
        branch = self.workflow("approve", "--pr", "7", "--approver", "ann", "--dry-run", check=False)
        self.assertIn("this patch changes .feature-workflow/", branch.stderr)
        self.assertEqual(self.calls(), [])

    def test_purpose_is_stored_and_shown(self) -> None:
        self.init("t2", "--purpose", "land bundle A")
        self.assertEqual(self.status()["purpose"], "land bundle A")
        self.assertIn("purpose: land bundle A", self.workflow("status").stdout)
        resumed = self.workflow("init", "--source", "x", "--resume", "--purpose", "land bundles A and C")
        self.assertIn("purpose updated: land bundles A and C", resumed.stderr)
        self.assertEqual(self.status()["purpose"], "land bundles A and C")

    def ready_for_approval(self) -> None:
        self.init("t2", "--rules", str(self.write_rules()))
        self.record("brief")
        self.commit("core/engine.py", "route = 1\n", "core")
        for name in ("build", "verification", "cold-read", "packet"):
            self.record(name)
        self.publish_head()

    def test_approve_stops_when_pr_head_moves_after_mark_ready(self) -> None:
        self.ready_for_approval()
        self.project["mark_ready"] = self.project["mark_ready"].replace(
            "ready {pr}", f"move {shlex.quote(str(self.pr_head_file))} {'b' * 40}")
        refused = self.land("approve", "--approver", "ann")
        self.assertIn("it moved after mark_ready; no approval status set", refused.stderr)
        self.assertNotIn("status", [call[0] for call in self.calls()])
        self.assertEqual(self.status()["artifacts"]["approval"]["status"], "absent")

    def test_failed_approval_status_records_only_an_attempt(self) -> None:
        self.ready_for_approval()
        self.project["approval_status"] = self.project["approval_status"].replace(" status ", " fail ")
        refused = self.land("approve", "--approver", "ann")
        self.assertIn("exited 3", refused.stderr)
        self.assertIn("no approval recorded", refused.stderr)
        state = json.loads((self.state_dir / "state.json").read_text())
        self.assertNotIn("approval", state["artifacts"])
        self.assertEqual(state["approval_attempts"][0]["failed_step"], "approval_status")

    def test_approve_reevaluates_under_the_lock(self) -> None:
        self.ready_for_approval()  # a concurrent writer invalidates the packet while mark_ready runs
        self.project["mark_ready"] = " ".join(shlex.quote(part) for part in (
            sys.executable, str(SCRIPT), "invalidate", "--repo", str(self.repo), "--slug", "account-export",
            "--state-dir", str(self.state_dir), "--from", "packet", "--reason", "concurrent change"))
        refused = self.land("approve", "--approver", "ann")
        self.assertIn("cannot approve", refused.stderr)
        self.assertIn("concurrent change", refused.stderr)
        self.assertNotIn("status", [call[0] for call in self.calls()])

    def test_ledger_writes_wait_for_the_lock(self) -> None:
        self.init("t2")
        with open(self.state_dir / "state.lock", "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            writer = subprocess.Popen([sys.executable, str(SCRIPT), "record", "--slug", "account-export",
                                       "--state-dir", str(self.state_dir), "--artifact", "brief", "--path",
                                       str(self.write_artifact("brief"))], cwd=self.repo,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(1.5)
            self.assertIsNone(writer.poll())
            self.assertEqual(self.status()["artifacts"]["brief"]["status"], "absent")
        self.assertEqual(writer.wait(timeout=30), 0)
        self.assertEqual(self.status()["artifacts"]["brief"]["status"], "current")

    def test_closed_run_and_unrecorded_pr_refuse(self) -> None:
        self.ready_for_approval()
        self.record("approval")  # by hand: no PR recorded
        self.assertIn("approve with --pr first", self.land("carry").stderr)
        state_file = self.state_dir / "state.json"
        state = json.loads(state_file.read_text())
        state["artifacts"]["published"] = {"landing": "squash"}
        state_file.write_text(json.dumps(state))
        for command, extra in (("approve", ("--approver", "ann")), ("carry", ())):
            self.assertIn("run is closed", self.land(command, *extra).stderr)

    def test_project_loader_defaults_and_validation(self) -> None:
        module = load_module()
        missing = module.load_project(module.find_project(self.repo, None))
        self.assertEqual((missing["path"], missing["approval_status"], missing["mark_ready"]),
                         (None, None, "gh pr ready {pr}"))
        partial = module.load_project(self.write_project(required_checks=["ci"], mark_ready=None))
        self.assertEqual((partial["mark_ready"], partial["required_checks"], partial["retrigger"]),
                         (None, ["ci"], None))
        self.assertTrue(partial["pr_head"].endswith("{pr}"))
        for bad in ({"mark_ready": "gh pr ready {PR}"}, {"merge_mode": "auto"}, {"retriger": "x"},
                    {"required_checks": "ci"}, {"approval_status": "  "}, {"pr_head": 'gh "x'},
                    {"approval_status": "bash -c 'gh api x'"}, {"mark_ready": "/bin/sh -ec 'gh pr ready {pr}'"}):
            with self.assertRaises(module.WorkflowError, msg=bad):
                module.load_project(self.write_project(**bad))
        self.assertEqual(module.render("echo {approver} --jq '{a: .b}'", {"approver": "a b; rm"}),
                         ["echo", "a b; rm", "--jq", "{a: .b}"])
        (self.repo / ".feature-workflow").mkdir()
        (self.repo / ".feature-workflow" / "project.json").symlink_to(self.write_project())
        with self.assertRaisesRegex(module.WorkflowError, "symlink"):
            module.find_project(self.repo, None)


if __name__ == "__main__":
    unittest.main()
