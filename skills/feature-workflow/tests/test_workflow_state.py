from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "workflow_state.py"


class WorkflowStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo = Path(self.tempdir.name)
        self.exec_cmd("git", "init", "-b", "main")
        self.exec_cmd("git", "config", "user.name", "Test User")
        self.exec_cmd("git", "config", "user.email", "test@example.com")
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        self.exec_cmd("git", "add", "README.md")
        self.exec_cmd("git", "commit", "-m", "base")
        self.exec_cmd("git", "branch", "origin/main")
        self.exec_cmd("git", "switch", "-c", "feature")
        self.state_dir = self.repo / ".git" / "feature-workflow-test"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def exec_cmd(self, *command: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=self.repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=check,
        )

    def workflow(self, command: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self.exec_cmd(
            sys.executable,
            str(SCRIPT),
            command,
            "--slug",
            "account-export",
            "--state-dir",
            str(self.state_dir),
            *args,
            check=check,
        )

    def write_artifact(self, name: str) -> Path:
        path = self.state_dir / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {name}\n", encoding="utf-8")
        return path

    def record(self, name: str, path: Path | None = None) -> None:
        arguments = ["--artifact", name]
        if path:
            arguments.extend(["--path", str(path)])
        self.workflow("record", *arguments)

    def test_head_change_invalidates_head_bound_chain(self) -> None:
        self.workflow(
            "init",
            "--source",
            "issue #123",
            "--base-ref",
            "origin/main",
        )
        self.record("spec", self.write_artifact("spec"))
        self.record("plan-review", self.write_artifact("plan-review"))

        (self.repo / "feature.txt").write_text("implemented\n", encoding="utf-8")
        self.exec_cmd("git", "add", "feature.txt")
        self.exec_cmd("git", "commit", "-m", "implement")
        self.record("implementation")
        self.record("verification", self.write_artifact("verification"))
        self.record("reconstruction", self.write_artifact("reconstruction"))
        self.record("intent-comparison", self.write_artifact("intent-comparison"))
        self.record("candidate")
        self.record("reviewer-map", self.write_artifact("reviewer-map"))
        self.record("approval", self.write_artifact("approval"))

        current = json.loads(self.workflow("status", "--json").stdout)
        self.assertEqual(current["next_artifact"], "published")
        self.assertEqual(current["artifacts"]["candidate"]["status"], "current")

        (self.repo / "feature.txt").write_text("changed after approval\n", encoding="utf-8")
        self.exec_cmd("git", "add", "feature.txt")
        self.exec_cmd("git", "commit", "-m", "change")

        stale = json.loads(self.workflow("status", "--json").stdout)
        self.assertEqual(stale["next_artifact"], "implementation")
        self.assertEqual(stale["artifacts"]["spec"]["status"], "current")
        self.assertEqual(stale["artifacts"]["implementation"]["status"], "stale")
        self.assertIn("HEAD changed", stale["artifacts"]["approval"]["reasons"])

    def test_changed_spec_invalidates_consumers_without_deleting_evidence(self) -> None:
        self.workflow(
            "init",
            "--source",
            "feature idea",
            "--base-ref",
            "origin/main",
        )
        spec = self.write_artifact("spec")
        self.record("spec", spec)
        self.record("plan-review", self.write_artifact("plan-review"))

        spec.write_text("# revised spec\n", encoding="utf-8")
        report = json.loads(self.workflow("status", "--json").stdout)
        self.assertEqual(report["artifacts"]["spec"]["status"], "stale")
        self.assertEqual(report["artifacts"]["plan-review"]["status"], "stale")
        self.assertTrue(spec.exists())

    def test_explicit_invalidation_marks_recorded_downstream_artifacts(self) -> None:
        self.workflow(
            "init",
            "--source",
            "feature idea",
            "--base-ref",
            "origin/main",
        )
        self.record("spec", self.write_artifact("spec"))
        self.record("plan-review", self.write_artifact("plan-review"))
        self.record("implementation")

        result = json.loads(
            self.workflow(
                "invalidate",
                "--from",
                "implementation",
                "--reason",
                "review changes requested",
            ).stdout
        )
        self.assertEqual(result["affected"], ["implementation"])
        report = json.loads(self.workflow("status", "--json").stdout)
        self.assertIn(
            "review changes requested",
            report["artifacts"]["implementation"]["reasons"],
        )

    def test_replacing_optional_deep_review_invalidates_candidate(self) -> None:
        self.workflow(
            "init",
            "--source",
            "feature idea",
            "--base-ref",
            "origin/main",
        )
        self.record("spec", self.write_artifact("spec"))
        self.record("plan-review", self.write_artifact("plan-review"))
        self.record("implementation")
        self.record("verification", self.write_artifact("verification"))
        self.record("reconstruction", self.write_artifact("reconstruction"))
        self.record("intent-comparison", self.write_artifact("intent-comparison"))
        deep_review = self.write_artifact("deep-review")
        self.record("deep-review", deep_review)
        self.record("candidate")

        deep_review.write_text("# revised deep review\n", encoding="utf-8")
        self.record("deep-review", deep_review)

        report = json.loads(self.workflow("status", "--json").stdout)
        self.assertEqual(report["artifacts"]["deep-review"]["status"], "current")
        self.assertEqual(report["artifacts"]["candidate"]["status"], "stale")
        self.assertIn(
            "dependency deep-review was replaced",
            report["artifacts"]["candidate"]["reasons"],
        )


if __name__ == "__main__":
    unittest.main()
