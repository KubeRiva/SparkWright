"""Regression tests for the independent review of the Phase 3 build loop (specs/reviews/2026-10-24-build-review.md)."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from sparkwright.adapters import claude_code
from sparkwright.core import checks
from sparkwright.runner.build import Build, BuildError, safe_relpath
from sparkwright.runner.providers import FakeProvider
from sparkwright.runner.router import Router
from helpers import TempRepo, commit, git, run_cli, write
from test_build import CODE, GOOD_TESTS, project, ws

codes = lambda res: {f.code for f in res.findings if f.severity == "error"}


def to_builder(r):
    b = Build(r, "C1.1.1.T1")
    b.advance()
    write(ws(b), "tests/test_calc.py", GOOD_TESTS)
    b.submit("test-author", "{}")
    return b


class TestHigh(unittest.TestCase):
    def test_h1_agent_commits_are_unwound_and_enforced(self):
        with TempRepo() as r:
            project(r)
            b = to_builder(r)
            write(ws(b), "calc.py", CODE)
            write(ws(b), "tests/test_calc.py", GOOD_TESTS.replace("clamp(-3, 0, 10), 0", "clamp(-3, 0, 10), -3"))
            git(ws(b), "add", "-A")
            git(ws(b), "commit", "-q", "-m", "sneaky")
            ins = b.submit("builder", "{}")
            self.assertIn("tests/test_calc.py", b.state.feedback)
            self.assertNotIn("-3), -3", (ws(b) / "tests/test_calc.py").read_text().replace("clamp(-3, 0, 10), 0", ""))
            self.assertNotIn("sneaky", git(ws(b), "log", "--format=%s"))

    def test_h2_code_reviewer_changes_are_discarded(self):
        with TempRepo() as r:
            project(r)
            b = to_builder(r)
            write(ws(b), "calc.py", CODE)
            ins = b.submit("builder", "{}")
            self.assertEqual(ins["step"], "code-reviewer")
            write(ws(b), "calc.py", "def clamp(x, lo, hi):\n    return 0\n")
            git(ws(b), "commit", "-qam", "reviewer sabotage")
            ins = b.submit("code-reviewer", "[]")
            self.assertEqual(ins["step"], "ready", ins)
            self.assertEqual((ws(b) / "calc.py").read_text(), CODE)

    def test_h3_runner_mode_refuses_unsafe_paths(self):
        for bad in [".git", "../x.py", "/etc/passwd", "C:/x.py", "a/../../x", ".sparkwright/runs/x", "sub/.git/config"]:
            self.assertIsNone(safe_relpath(bad), bad)
        self.assertEqual(safe_relpath("calc.py"), "calc.py")
        with TempRepo() as r:
            project(r)
            os.symlink(str(r / "specs"), str(r / "linkdir"))
            git(r, "add", "-A"); git(r, "commit", "-qm", "symlink")
            fake = FakeProvider(script={
                "test-author": [json.dumps({"files": {"tests/test_calc.py": GOOD_TESTS, ".git": "gitdir: /tmp/evil",
                                                      "calc.py": "x = 1"}, "status": "ok"})],
                "builder": [json.dumps({"files": {"calc.py": CODE, "linkdir/vision.md": "pwned", "tests/test_calc.py": 5},
                                        "status": "ok"})],
                "code-reviewer": ["[]"],
            })
            router = Router({"roles": {}, "budgets": {}, "models": {}}, {"fast": fake, "mid": fake, "top": fake})
            b = Build(r, "C1.1.1.T1")
            ins = b.run(router)
            self.assertEqual(ins["step"], "ready", ins)
            self.assertTrue((ws(b) / ".git").is_file() and "gitdir: /tmp/evil" not in (ws(b) / ".git").read_text())
            self.assertNotIn("pwned", (r / "specs/vision.md").read_text())
            self.assertEqual(git(r, "rev-parse", "--abbrev-ref", "HEAD"), git(r, "rev-parse", "--abbrev-ref", "HEAD"))
            self.assertNotIn("tests (red)", git(r, "log", "--format=%s", "HEAD"))  # nothing landed on main

    def test_h4_locked_tests_of_other_tasks_are_protected(self):
        with TempRepo() as r:
            project(r)
            write(r, "tests/test_old.py", "# sparkwright: C1.1.1.T1\nimport unittest\n")
            commit(r, "old test")
            run_cli(r, "approve", "tests/test_old.py", "--test", "--as", "Srikanth")
            commit(r, "lock old test")
            b = Build(r, "C1.1.1.T1")
            b.advance()
            write(ws(b), "tests/test_calc.py", GOOD_TESTS)
            write(ws(b), "tests/test_old.py", "# tampered\n")
            b.submit("test-author", "{}")
            reverted = [x for x in b.log.records() if x["step"] == "enforce:test-author"]
            self.assertIn("tests/test_old.py", reverted[0]["reverted"])
            self.assertEqual((ws(b) / "tests/test_old.py").read_text(), "# sparkwright: C1.1.1.T1\nimport unittest\n")

    def test_h4_check_flags_late_edits_to_locked_tests_by_any_agent_role(self):
        with TempRepo() as r:
            project(r)
            write(r, "tests/test_old.py", "x = 1\n")
            commit(r, "old test")
            run_cli(r, "approve", "tests/test_old.py", "--test", "--as", "Srikanth")
            commit(r, "lock")
            write(r, "tests/test_old.py", "x = 2\n")
            commit(r, "edit\n\nFiles:\n- tests/test_old.py\n\nSparkWright-Task: C1.1.1.T1\nSparkWright-Role: test-author")
            self.assertIn("role.path-violation", codes(checks.run(r)))

    def test_h5_forged_ready_state_is_rejected(self):
        with TempRepo() as r:
            project(r)
            b = to_builder(r)
            state = dict(b.state.__dict__, phase="ready")
            b.log.append("state", status="done", state=state)
            ins = Build(r, "C1.1.1.T1").advance()
            self.assertEqual(ins["step"], "blocked")
            self.assertIn("tampered", ins["reason"])

    def test_h5_guard_protects_workspace_and_run_state(self):
        with TempRepo() as r:
            claude_code.generate(r / "plugin")
            project(r)

            def guard(payload):
                out = subprocess.run([sys.executable, "-m", "sparkwright", "guard"], input=json.dumps(payload),
                                     capture_output=True, text=True, env={"CLAUDE_PROJECT_DIR": str(r), "PYTHONPATH": os.environ.get("PYTHONPATH", "")})
                return json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"] if out.stdout.strip() else "allow"
            edit = lambda p: guard({"tool_name": "Write", "tool_input": {"file_path": p}})
            bash = lambda c: guard({"tool_name": "Bash", "tool_input": {"command": c}})
            self.assertEqual(edit(".sparkwright/runs/build-C1.1.1.T1.jsonl"), "deny")
            self.assertEqual(edit(".sparkwright/worktrees/C1.1.1.T1/specs/approvals.jsonl"), "deny")
            self.assertEqual(edit(".sparkwright/worktrees/C1.1.1.T1/.git"), "deny")
            self.assertEqual(edit(".sparkwright/worktrees/C1.1.1.T1/calc.py"), "allow")
            self.assertEqual(bash("cat x >> specs/approv*.jsonl"), "deny")
            self.assertEqual(bash("echo '{}' >> .sparkwright/runs/build-x.jsonl"), "deny")
            # host-mode plumbing the orchestrator needs must stay allowed
            self.assertEqual(edit(".sparkwright/runs/build-C1.1.1.T1/builder-0.result.json"), "allow")
            self.assertEqual(edit(".sparkwright/runs/20261024-1-interview-abc123/transcript.md"), "allow")
            self.assertEqual(edit(".sparkwright/runs/build-C1.1.1.T1/builder-0.md"), "deny")
            self.assertEqual(edit(".sparkwright/runs/20261024-1-review-abc123/newcomer.json"), "allow")
            self.assertEqual(edit(".sparkwright/runs/20261024-1-review-abc123.jsonl"), "deny")
            self.assertEqual(bash("sparkwright build C1.1.1.T1 --done builder --result .sparkwright/runs/build-C1.1.1.T1/builder-0.result.json --json"), "allow")


class TestMedium(unittest.TestCase):
    def test_m1_zero_mutants_is_reported(self):
        with TempRepo() as r:
            project(r)
            b = to_builder(r)
            write(ws(b), "calc.py", "clamp = lambda x, lo, hi: lo if x < lo else hi if x > hi else x\n")
            ins = b.submit("builder", "{}")
            # a one-line lambda still yields mutants with the AST mutator; the note appears only when none exist
            self.assertIn(ins["step"], ("code-reviewer", "test-author"))

    def test_m2_deleted_test_does_not_crash(self):
        with TempRepo() as r:
            project(r)
            write(r, "tests/test_extra.py", "import unittest\n")
            commit(r, "extra")
            b = Build(r, "C1.1.1.T1")
            b.advance()
            (ws(b) / "tests/test_extra.py").unlink()
            write(ws(b), "tests/test_calc.py", GOOD_TESTS)
            ins = b.submit("test-author", "{}")
            self.assertEqual(ins["step"], "builder")
            self.assertTrue((ws(b) / "tests/test_extra.py").exists())  # deletion reverted

    def test_m3_restart_after_blocked(self):
        with TempRepo() as r:
            project(r)
            b = to_builder(r)
            write(ws(b), "calc.py", CODE)
            b.submit("builder", "{}")
            high = json.dumps([{"severity": "high", "ids": [], "finding": "x", "fix": "y"}])
            ins = b.submit("code-reviewer", high)
            n = 0
            while ins["step"] != "blocked":
                n += 1
                if ins["step"] == "builder":
                    write(ws(b), "calc.py", CODE + "\n# %d\n" % n)
                ins = b.submit(ins["step"], high if ins["step"] == "code-reviewer" else "{}")
            again = Build(r, "C1.1.1.T1").advance()
            self.assertEqual(again["step"], "blocked")
            fresh = Build(r, "C1.1.1.T1", restart=True).advance()
            self.assertEqual(fresh["step"], "test-author")

    def test_m5_dirty_specs_refuse_to_build(self):
        with TempRepo() as r:
            project(r)
            write(r, "specs/system.md", (r / "specs/system.md").read_text() + "\n")
            with self.assertRaises(BuildError):
                Build(r, "C1.1.1.T1").advance()

    def test_m4_done_requires_ready_marker(self):
        with TempRepo() as r:
            project(r)
            b = to_builder(r)
            write(ws(b), "calc.py", CODE)
            b.submit("builder", "{}")  # builder commit exists, build not finished
            git(r, "merge", "-q", "--no-ff", "-m", "early merge", b.state.branch)
            self.assertEqual(checks.run(r).nodes["C1.1.1.T1"].status, "building")

    def test_m6_change_request_rounds(self):
        with TempRepo() as r:
            project(r)
            run_cli(r, "approve", "SYSTEM", "--as", "Srikanth")
            run_cli(r, "approve", "C1", "--as", "Srikanth")
            run_cli(r, "change", "new", "C1.1.1.T1", "--reason", "x")
            run_cli(r, "approve", "CR1", "--as", "Srikanth")
            run_cli(r, "change", "apply", "CR1")
            commit(r, "cr")
            run_cli(r, "approve", "C1.1.1.T1", "--as", "Srikanth", "--cr", "CR1")
            commit(r, "reapprove")
            for n in range(1, 4):
                b = Build(r, "C1.1.1.T1", restart=True)
                ins = b.advance()
                if n < 3:
                    self.assertEqual(ins["step"], "test-author")
                    self.assertIn(f"rounds: {n}", (r / "specs/changes/CR1.md").read_text())
                    b._block("simulated failure")  # end this run so the next call is a real rebuild
            self.assertEqual(ins["step"], "blocked")
            self.assertIn("status: blocked", (r / "specs/changes/CR1.md").read_text())

    def test_l4_result_must_be_in_runs(self):
        with TempRepo() as r:
            project(r)
            Build(r, "C1.1.1.T1").advance()
            write(r, "elsewhere.json", "{}")
            code, out = run_cli(r, "build", "C1.1.1.T1", "--done", "test-author", "--result", "elsewhere.json")
            self.assertEqual(code, 1)
            self.assertIn("inside .sparkwright/runs", out["data"]["error"])
            code, out = run_cli(r, "build", "C1.1.1.T1", "--done", "test-author", "--result",
                                ".sparkwright/runs/build-C1.1.1.T1/missing.json")
            self.assertEqual(code, 1)
            self.assertIn("does not exist", out["data"]["error"])


if __name__ == "__main__":
    unittest.main()
