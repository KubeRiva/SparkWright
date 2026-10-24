"""End-to-end tests for the build workflow (SYSTEM S3.3-S3.6, S5.1-S5.5)."""
import json
import sys
import unittest
from pathlib import Path

from sparkwright.core import checks
from sparkwright.runner.build import Build, BuildError
from sparkwright.runner.providers import FakeProvider
from sparkwright.runner.router import Router
from helpers import TempRepo, commit, git, git_init, run_cli, spec, write

PY = sys.executable
GOOD_TESTS = (
    "# sparkwright: C1.1.1.T1\nimport unittest\nfrom calc import clamp\n\n"
    "class T(unittest.TestCase):\n"
    "    def test_inside(self):\n        self.assertEqual(clamp(5, 0, 10), 5)\n"
    "    def test_low(self):\n        self.assertEqual(clamp(-3, 0, 10), 0)\n"
    "    def test_high(self):\n        self.assertEqual(clamp(42, 0, 10), 10)\n"
    "    def test_edges(self):\n        self.assertEqual(clamp(0, 0, 10), 0)\n        self.assertEqual(clamp(10, 0, 10), 10)\n"
    "        self.assertEqual(clamp(1, 0, 10), 1)\n        self.assertEqual(clamp(9, 0, 10), 9)\n"
)
WEAK_TESTS = ("# sparkwright: C1.1.1.T1\nimport unittest\nfrom calc import clamp\n\n"
              "class T(unittest.TestCase):\n    def test_runs(self):\n        self.assertIsNotNone(clamp(5, 0, 10))\n")
CODE = "def clamp(x, lo, hi):\n    if x < lo:\n        return lo\n    if x > hi:\n        return hi\n    return x\n"


def project(r: Path, extra_yaml: str = "", risk: str = "") -> None:
    write(r, "specs/evidence/E1.md", "---\nid: E1\ntitle: t\ntype: evidence\nstatus: draft\n---\nUsers need clamping.\n")
    write(r, "specs/vision.md", spec("VISION", "vision", "- **V1** [E1] Values stay in range.\n"))
    write(r, "specs/system.md", spec("SYSTEM", "system", "- **S1.1** [V1] The library shall clamp numbers.\n"))
    comp = spec("C1", "component",
          "- **C1.1.1** [S1.1] clamp(x, lo, hi) returns x limited to [lo, hi].\n\n"
          "## Tasks\n\n- **C1.1.1.T1** [C1.1.1] Implement clamp in calc.py.\n\n```yaml\nfiles: [\"calc.py\"]\n" + extra_yaml + "```\n")
    if risk:
        comp = comp.replace("risk: low", f"risk: {risk}", 1)
    write(r, "specs/components/C1.md", comp)
    write(r, "calc.py", "")
    write(r, "tests/__init__.py", "")
    write(r, ".sparkwright/config.yaml",
          f"checks:\n  test: \"{PY} -m unittest discover -s tests -t .\"\ntrailers: warn\n"
          "approvers:\n  - {name: Srikanth, email: t@example.com}\nmutation: {min: 0.8, time_budget_s: 120}\n"
          "test_globs: [\"tests/*\"]\n")
    write(r, ".gitignore", ".sparkwright/ledger.json\n.sparkwright/runs/\n.sparkwright/worktrees/\n__pycache__/\n")
    git_init(r)
    commit(r, "start")
    run_cli(r, "approve", "C1.1.1.T1", "--as", "Srikanth")
    commit(r, "approve task")


def ws(b: Build) -> Path:
    return Path(b.state.workspace)


class TestHostModeBuild(unittest.TestCase):
    # sparkwright: S3.3
    def test_full_build_in_host_mode(self):
        with TempRepo() as r:
            project(r)
            b = Build(r, "C1.1.1.T1")
            ins = b.advance()
            self.assertEqual(ins["step"], "test-author")
            self.assertIn("Implement clamp", (r / ins["prompt"]).read_text())
            # Test Author also tries to write source: must be reverted
            write(ws(b), "tests/test_calc.py", GOOD_TESTS)
            write(ws(b), "calc.py", "def clamp(x, lo, hi): return x\n")
            ins = b.submit("test-author", '{"status": "ok"}')
            self.assertEqual(ins["step"], "builder")
            self.assertEqual((ws(b) / "calc.py").read_text(), "")
            # Builder also tries to edit the tests: must be reverted
            write(ws(b), "calc.py", CODE)
            write(ws(b), "tests/test_calc.py", "import unittest\n")
            ins = b.submit("builder", '{"status": "ok"}')
            self.assertEqual(ins["step"], "code-reviewer", ins)
            self.assertIn("sparkwright: C1.1.1.T1", (ws(b) / "tests/test_calc.py").read_text())
            ins = b.submit("code-reviewer", "[]")
            self.assertEqual(ins["step"], "ready")
            self.assertGreaterEqual(ins["mutation_score"], 0.8)
            log = git(ws(b), "log", "--format=%s")
            self.assertIn("C1.1.1.T1: tests (red)", log)
            self.assertIn("C1.1.1.T1: implement", log)
            self.assertIn("C1.1.1.T1: lock tests", log)
            # merge and check: task becomes done, locked test verified, role rules hold
            git(r, "merge", "-q", "--no-ff", "-m", "merge", ins["branch"])
            res = checks.run(r)
            self.assertEqual(res.nodes["C1.1.1.T1"].status, "done")
            self.assertTrue(res.ok, [f for f in res.findings if f.severity == "error"])

    # sparkwright: S5.2
    def test_red_check_rejects_tests_that_already_pass(self):
        with TempRepo() as r:
            project(r)
            b = Build(r, "C1.1.1.T1")
            b.advance()
            write(ws(b), "tests/test_calc.py", "import unittest\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertTrue(True)\n")
            ins = b.submit("test-author", "{}")
            self.assertEqual(ins["step"], "test-author")
            self.assertIn("pass before any implementation", b.state.feedback)

    # sparkwright: S3.4
    def test_weak_tests_go_back_to_test_author_with_survivors(self):
        with TempRepo() as r:
            project(r)
            b = Build(r, "C1.1.1.T1")
            b.advance()
            write(ws(b), "tests/test_calc.py", WEAK_TESTS)
            b.submit("test-author", "{}")
            write(ws(b), "calc.py", CODE)
            ins = b.submit("builder", "{}")
            self.assertEqual(ins["step"], "test-author")
            self.assertTrue(b.state.frozen)
            self.assertIn("were NOT caught", b.state.feedback)
            write(ws(b), "tests/test_calc.py", GOOD_TESTS)
            ins = b.submit("test-author", "{}")
            self.assertEqual(ins["step"], "code-reviewer", (ins, b.state.feedback))

    # sparkwright: S3.5
    def test_spec_defect_opens_change_request(self):
        with TempRepo() as r:
            project(r)
            b = Build(r, "C1.1.1.T1")
            b.advance()
            write(ws(b), "tests/test_calc.py", GOOD_TESTS)
            b.submit("test-author", "{}")
            ins = b.submit("builder", '{"spec_defect": {"cited_id": "C1.1.1", "reason": "lo > hi is undefined"}}')
            self.assertEqual(ins["step"], "changed")
            cr = (r / ins["change_request"]).read_text()
            self.assertIn("target: C1.1.1", cr)
            self.assertEqual(checks.run(r).nodes["C1.1.1.T1"].status, "changed")

    def test_code_review_high_finding_returns_to_builder_then_blocks(self):
        with TempRepo() as r:
            project(r)
            b = Build(r, "C1.1.1.T1")
            b.advance()
            write(ws(b), "tests/test_calc.py", GOOD_TESTS)
            b.submit("test-author", "{}")
            write(ws(b), "calc.py", CODE)
            ins = b.submit("builder", "{}")
            high = json.dumps([{"severity": "high", "ids": ["C1.1.1.T1"], "finding": "bad", "fix": "fix it"}])
            steps = []
            for n in range(1, 4):  # the builder gets 2 retries; the 3rd high finding blocks
                self.assertEqual(ins["step"], "code-reviewer", (n, ins))
                ins = b.submit("code-reviewer", high)
                steps.append(ins["step"])
                if ins["step"] == "builder":
                    self.assertIn("fix it", b.state.feedback)
                    write(ws(b), "calc.py", CODE + "\n# round %d\n" % n)
                    ins = b.submit("builder", "{}")
            self.assertEqual(steps, ["builder", "builder", "blocked"])
            self.assertEqual(checks.run(r).nodes["C1.1.1.T1"].status, "blocked")

    def test_unapproved_task_cannot_be_built(self):
        with TempRepo() as r:
            project(r)
            write(r, "specs/components/C1.md", (r / "specs/components/C1.md").read_text().replace("Implement clamp", "Implement clamp fast"))
            with self.assertRaises(BuildError):
                Build(r, "C1.1.1.T1").advance()


class TestRunnerModeBuild(unittest.TestCase):
    # sparkwright: S8.2
    def test_runner_mode_with_fake_models(self):
        with TempRepo() as r:
            project(r)
            fake = FakeProvider(script={
                "test-author": [json.dumps({"files": {"tests/test_calc.py": GOOD_TESTS}, "status": "ok"})],
                "builder": [json.dumps({"files": {"calc.py": CODE, "../escape.py": "x"}, "status": "ok"})],
                "code-reviewer": ["[]"],
            })
            router = Router({"roles": {}, "budgets": {}, "models": {}}, {"fast": fake, "mid": fake, "top": fake})
            ins = Build(r, "C1.1.1.T1").run(router)
            self.assertEqual(ins["step"], "ready", ins)
            self.assertFalse((r / ".sparkwright/worktrees/escape.py").exists())
            self.assertEqual([c[0] for c in fake.calls], ["test-author", "builder", "code-reviewer"])


class TestChange(unittest.TestCase):
    # sparkwright: S2.5
    def test_change_new_approve_apply(self):
        with TempRepo() as r:
            project(r)
            run_cli(r, "approve", "SYSTEM", "--as", "Srikanth")
            run_cli(r, "approve", "C1", "--as", "Srikanth")
            code, out = run_cli(r, "change", "new", "C1.1.1", "--reason", "define lo > hi")
            self.assertEqual(code, 0)
            self.assertTrue(checks.run(r).ok)  # quoted lines in the CR are not duplicates
            code, out = run_cli(r, "change", "apply", "CR1")
            self.assertEqual(code, 1)  # not approved yet
            run_cli(r, "approve", "CR1", "--as", "Srikanth")
            code, out = run_cli(r, "change", "apply", "CR1")
            self.assertEqual(code, 0, out)
            self.assertEqual(sorted(out["data"]["marked_changed"]), ["C1.1.1", "C1.1.1.T1"])
            self.assertEqual(checks.run(r).nodes["C1.1.1.T1"].status, "changed")


if __name__ == "__main__":
    unittest.main()
