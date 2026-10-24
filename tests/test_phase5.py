"""Phase 5: re-review after change requests (S3.10), parallel builds (S3.8), interview guide (S7.2, S7.7),
adopt (S2.7), calibration (S10), Prover hook (S5.6)."""
import unittest
from pathlib import Path

import json
import threading

from sparkwright.core import checks
from sparkwright.runner import parallel, review
from sparkwright.runner.build import Build, BuildError
from sparkwright.runner.providers import FakeProvider
from sparkwright.runner.router import Router
from helpers import TempRepo, commit, git, git_init, run_cli, spec, write
from test_build import CODE, GOOD_TESTS, PY, project, ws

DOUBLE_TESTS = ("# sparkwright: C1.1.1.T2\nimport unittest\nfrom other import double\n\n"
                "class D(unittest.TestCase):\n    def test_double(self):\n        self.assertEqual(double(2), 4)\n"
                "        self.assertEqual(double(-3), -6)\n        self.assertEqual(double(0), 0)\n")
DOUBLE = "def double(x):\n    return x * 2\n"


def multi_project(r: Path) -> None:
    write(r, "specs/evidence/E1.md", "---\nid: E1\ntitle: t\ntype: evidence\nstatus: draft\n---\nNeeds.\n")
    write(r, "specs/vision.md", spec("VISION", "vision", "- **V1** [E1] Values stay in range.\n"))
    write(r, "specs/system.md", spec("SYSTEM", "system", "- **S1.1** [V1] The library shall do maths.\n"))
    write(r, "specs/components/C1.md", spec("C1", "component",
          "- **C1.1.1** [S1.1] clamp and double.\n\n## Tasks\n\n"
          "- **C1.1.1.T1** [C1.1.1] Implement clamp in calc.py.\n\n```yaml\nfiles: [\"calc.py\"]\n```\n\n"
          "- **C1.1.1.T2** [C1.1.1] Implement double in other.py.\n\n```yaml\nfiles: [\"other.py\"]\n```\n\n"
          "- **C1.1.1.T3** [C1.1.1] Tidy every module.\n\n```yaml\nfiles: [\"*.py\"]\n```\n"))
    write(r, "calc.py", "")
    write(r, "other.py", "")
    write(r, "tests/__init__.py", "")
    write(r, ".sparkwright/config.yaml",
          f"checks:\n  test: \"{PY} -m unittest discover -s tests -t .\"\ntrailers: warn\n"
          "approvers:\n  - {name: Srikanth, email: t@example.com}\nmutation: {min: 0.5, time_budget_s: 120}\n"
          "test_globs: [\"tests/*\"]\n")
    write(r, ".gitignore", ".sparkwright/ledger.json\n.sparkwright/runs/\n.sparkwright/worktrees/\n__pycache__/\n")
    git_init(r)
    commit(r, "start")
    for t in ("C1.1.1.T1", "C1.1.1.T2", "C1.1.1.T3"):
        run_cli(r, "approve", t, "--as", "Srikanth")
    commit(r, "approve tasks")


def host_review(r: Path, target: str) -> review.ReviewResult:
    prep = review.prepare(r, target)
    for name in prep.personas:
        (prep.run_dir / f"{name}.json").write_text("[]")
    return review.collect(r, prep.run_id, {"gates": {}})


class TestReReviewAfterChange(unittest.TestCase):
    # sparkwright: S3.10
    def test_applied_cr_puts_target_in_review_and_requires_review_before_reapproval(self):
        with TempRepo() as r:
            project(r)
            run_cli(r, "approve", "SYSTEM", "--as", "Srikanth")
            run_cli(r, "approve", "C1", "--as", "Srikanth")
            run_cli(r, "change", "new", "C1.1.1", "--reason", "define lo > hi")
            run_cli(r, "approve", "CR1", "--as", "Srikanth")
            code, out = run_cli(r, "change", "apply", "CR1")
            self.assertEqual(code, 0, out)
            nodes = checks.run(r).nodes
            self.assertEqual(nodes["C1.1.1"].status, "in-review")
            self.assertEqual(nodes["C1.1.1.T1"].status, "changed")
            p = r / "specs/components/C1.md"
            p.write_text(p.read_text().replace("limited to [lo, hi].", "limited to [lo, hi]; lo > hi raises ValueError."))
            code, out = run_cli(r, "approve", "C1.1.1", "--as", "Srikanth", "--cr", "CR1")
            self.assertEqual(code, 1)
            self.assertEqual(out["data"]["needs_review"], ["C1.1.1"])
            res = host_review(r, "C1")
            self.assertFalse(res.gate.startswith("FAIL"), res.gate)
            # editing after the review voids it: the review must have seen this exact text
            p.write_text(p.read_text().replace("raises ValueError.", "raises ValueError naming lo."))
            self.assertEqual(run_cli(r, "approve", "C1.1.1", "--as", "Srikanth", "--cr", "CR1")[0], 1)
            host_review(r, "C1")
            code, out = run_cli(r, "approve", "C1.1.1", "--as", "Srikanth", "--cr", "CR1")
            self.assertEqual(code, 0, out)
            self.assertEqual(checks.run(r).nodes["C1.1.1"].status, "approved")

    def test_failed_review_does_not_count(self):
        with TempRepo() as r:
            project(r)
            prep = review.prepare(r, "C1")
            (prep.run_dir / f"{prep.personas[0]}.json").write_text("[]")  # only one Inspector: FAIL
            res = review.collect(r, prep.run_id, {"gates": {}})
            self.assertTrue(res.gate.startswith("FAIL"))
            self.assertNotIn('"reviewed"', (r / "specs/events.jsonl").read_text() if (r / "specs/events.jsonl").exists() else "")


class TestParallelBuilds(unittest.TestCase):
    # sparkwright: S3.8
    def test_glob_overlap_is_conservative(self):
        self.assertFalse(parallel.globs_may_intersect(["calc.py"], ["other.py"]))
        self.assertTrue(parallel.globs_may_intersect(["calc.py"], ["*.py"]))
        self.assertTrue(parallel.globs_may_intersect(["src/a/**"], ["src/**"]))
        self.assertTrue(parallel.globs_may_intersect(["src/a/x.py"], ["src/a/*"]))
        self.assertFalse(parallel.globs_may_intersect(["src/a/**"], ["src/b/**"]))

    def test_plan_batches(self):
        with TempRepo() as r:
            multi_project(r)
            self.assertEqual(parallel.plan_batches(r, ["C1.1.1.T1", "C1.1.1.T2", "C1.1.1.T3"]),
                             [["C1.1.1.T1", "C1.1.1.T2"], ["C1.1.1.T3"]])
            code, out = run_cli(r, "build", "C1.1.1.T1", "C1.1.1.T2", "C1.1.1.T3", "--plan")
            self.assertEqual(code, 0)
            self.assertEqual(len(out["data"]["batches"]), 2)

    def test_overlapping_build_refused_while_another_runs(self):
        with TempRepo() as r:
            multi_project(r)
            Build(r, "C1.1.1.T1").advance()
            with self.assertRaises(BuildError) as ctx:
                Build(r, "C1.1.1.T3").advance()
            self.assertIn("C1.1.1.T1", str(ctx.exception))
            self.assertEqual(Build(r, "C1.1.1.T2").advance()["step"], "test-author")  # disjoint files: allowed
            for t in ("C1.1.1.T1", "C1.1.1.T2"):
                code, out = run_cli(r, "build", t, "--abandon")
                self.assertEqual(out["data"]["step"], "blocked")
            self.assertEqual(Build(r, "C1.1.1.T3").advance()["step"], "test-author")

    def test_two_disjoint_tasks_build_concurrently(self):
        with TempRepo() as r:
            multi_project(r)
            # FakeProvider hands out scripted replies in call order, so give each task its own provider
            fakes = {"C1.1.1.T1": FakeProvider(script={
                        "test-author": [json.dumps({"files": {"tests/test_calc.py": GOOD_TESTS}, "status": "ok"})],
                        "builder": [json.dumps({"files": {"calc.py": CODE}, "status": "ok"})], "code-reviewer": ["[]"]}),
                     "C1.1.1.T2": FakeProvider(script={
                        "test-author": [json.dumps({"files": {"tests/test_other.py": DOUBLE_TESTS}, "status": "ok"})],
                        "builder": [json.dumps({"files": {"other.py": DOUBLE}, "status": "ok"})], "code-reviewer": ["[]"]})}
            results = {}

            def go(task):
                f = fakes[task]
                router = Router({"roles": {}, "budgets": {}, "models": {}}, {"fast": f, "mid": f, "top": f})
                results[task] = Build(r, task).run(router)

            threads = [threading.Thread(target=go, args=(t,)) for t in fakes]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual({k: v["step"] for k, v in results.items()},
                             {"C1.1.1.T1": "ready", "C1.1.1.T2": "ready"}, results)

    def test_finish_stops_when_main_changed_the_same_file(self):
        with TempRepo() as r:
            multi_project(r)
            b = Build(r, "C1.1.1.T1")
            b.advance()
            write(r, "calc.py", "# edited on main\n")
            commit(r, "someone edits calc.py on main")
            write(ws(b), "tests/test_calc.py", GOOD_TESTS)
            b.submit("test-author", '{"status": "ok"}')
            write(ws(b), "calc.py", CODE)
            b.submit("builder", '{"status": "ok"}')
            ins = b.submit("code-reviewer", "[]")
            self.assertEqual(ins["step"], "blocked", ins)
            self.assertIn("main branch changed", ins["reason"])


if __name__ == "__main__":
    unittest.main()
