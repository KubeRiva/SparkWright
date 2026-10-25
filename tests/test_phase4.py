"""Phase 4: property tests (S5.4), risk tiers (S6.2), descend (S3.1)."""
import unittest
from pathlib import Path

from sparkwright.runner import descend
from sparkwright.runner.build import Build
from sparkwright.runner.providers import FakeProvider
from sparkwright.runner.router import Router
from helpers import TempRepo, commit, git, run_cli, write
from test_build import CODE, GOOD_TESTS, project, ws

PROPS = ("# sparkwright: C1.1.1.T1\nimport unittest\nfrom calc import clamp\n\n"
         "class P(unittest.TestCase):\n    def test_result_in_range(self):\n"
         "        \"\"\"invariant: lo <= clamp(x, lo, hi) <= hi\"\"\"\n"
         "        for x in range(-50, 50, 7):\n            self.assertTrue(0 <= clamp(x, 0, 10) <= 10)\n")


def project_with_invariants(r: Path) -> None:
    project(r, extra_yaml='invariants: ["lo <= clamp(x, lo, hi) <= hi"]\n')


class TestPropertyTester(unittest.TestCase):
    # sparkwright: S5.4
    def test_property_tester_runs_only_when_invariants_declared(self):
        with TempRepo() as r:
            project_with_invariants(r)
            b = Build(r, "C1.1.1.T1")
            b.advance()
            write(ws(b), "tests/test_calc.py", GOOD_TESTS)
            ins = b.submit("test-author", '{"status": "ok"}')
            self.assertEqual(ins["step"], "property-tester", ins)
            self.assertIn("INVARIANTS TO TEST", (r / ins["prompt"]).read_text())
            # it may add tests but not rewrite the Test Author's, nor write source
            write(ws(b), "tests/test_calc_props.py", PROPS)
            write(ws(b), "tests/test_calc.py", "import unittest\n")
            write(ws(b), "calc.py", "def clamp(x, lo, hi): return x\n")
            ins = b.submit("property-tester", '{"status": "ok"}')
            self.assertEqual(ins["step"], "builder", ins)
            self.assertEqual((ws(b) / "tests/test_calc.py").read_text(), GOOD_TESTS)
            self.assertEqual((ws(b) / "calc.py").read_text(), "")
            write(ws(b), "calc.py", CODE)
            ins = b.submit("builder", '{"status": "ok"}')
            self.assertEqual(ins["step"], "code-reviewer", ins)
            ins = b.submit("code-reviewer", "[]")
            self.assertEqual(ins["step"], "ready", ins)
            self.assertIn("C1.1.1.T1: property tests (red)", git(ws(b), "log", "--format=%s"))

    def test_no_property_tests_written_goes_back_then_blocks(self):
        with TempRepo() as r:
            project_with_invariants(r)
            b = Build(r, "C1.1.1.T1")
            b.advance()
            write(ws(b), "tests/test_calc.py", GOOD_TESTS)
            b.submit("test-author", '{"status": "ok"}')
            ins = b.submit("property-tester", '{"status": "ok"}')
            self.assertEqual(ins["step"], "property-tester")
            self.assertIn("No property test files", (r / ins["prompt"]).read_text())

    def test_no_invariants_skips_property_tester(self):
        with TempRepo() as r:
            project(r)
            b = Build(r, "C1.1.1.T1")
            b.advance()
            write(ws(b), "tests/test_calc.py", GOOD_TESTS)
            self.assertEqual(b.submit("test-author", '{"status": "ok"}')["step"], "builder")


class TestRiskTiers(unittest.TestCase):
    # sparkwright: S6.2
    def test_high_risk_task_gets_security_review_step(self):
        with TempRepo() as r:
            project(r, risk="high")
            b = Build(r, "C1.1.1.T1")
            b.advance()
            write(ws(b), "tests/test_calc.py", GOOD_TESTS)
            b.submit("test-author", '{"status": "ok"}')
            write(ws(b), "calc.py", CODE)
            b.submit("builder", '{"status": "ok"}')
            ins = b.submit("code-reviewer", "[]")
            self.assertEqual(ins["step"], "security-reviewer", ins)
            self.assertIn("=== DIFF ===", (r / ins["prompt"]).read_text())
            bad = '[{"severity": "high", "ids": [], "finding": "secret logged", "fix": "remove"}]'
            ins = b.submit("security-reviewer", bad)
            self.assertEqual(ins["step"], "builder")
            self.assertIn("secret logged", (r / ins["prompt"]).read_text())
            write(ws(b), "calc.py", "# no logging of inputs\n" + CODE)
            b.submit("builder", '{"status": "ok"}')
            b.submit("code-reviewer", "[]")
            ins = b.submit("security-reviewer", "[]")
            self.assertEqual(ins["step"], "ready", ins)
            self.assertIn("C1.1.1.T1: security review", git(ws(b), "log", "--format=%s"))

    def test_low_risk_task_skips_security_review(self):
        with TempRepo() as r:
            project(r)
            b = Build(r, "C1.1.1.T1")
            b.advance()
            write(ws(b), "tests/test_calc.py", GOOD_TESTS)
            b.submit("test-author", '{"status": "ok"}')
            write(ws(b), "calc.py", CODE)
            b.submit("builder", '{"status": "ok"}')
            self.assertEqual(b.submit("code-reviewer", "[]")["step"], "ready")

    def test_high_risk_review_adds_security_reviewer_and_human_gate(self):
        from sparkwright.runner import review
        with TempRepo() as r:
            project(r, risk="high")
            prep = review.prepare(r, "C1")
            self.assertIn("security-reviewer", prep.personas)
            for name in prep.personas:
                (prep.run_dir / f"{name}.json").write_text("[]")
            res = review.collect(r, prep.run_id, {"gates": {"component": "auto"}}, write=False)
            self.assertTrue(res.gate.startswith("HUMAN"), res.gate)

    def test_changing_risk_needs_human_reapproval(self):
        with TempRepo() as r:
            project(r)
            p = r / "specs/components/C1.md"
            p.write_text(p.read_text().replace("risk: low", "risk: high"))
            commit(r, "raise risk")
            _, out = run_cli(r, "check")
            codes = [f["code"] for f in out["data"]["findings"]]
            self.assertIn("approval.risk-changed", codes)
            code, out = run_cli(r, "approve", "C1.1.1.T1", "--as", "Srikanth")
            self.assertEqual(code, 0, out)
            commit(r, "re-approve at high risk")
            _, out = run_cli(r, "check")
            self.assertNotIn("approval.risk-changed", [f["code"] for f in out["data"]["findings"]])


COMPONENT = """---
id: C9
title: Range reporting
type: component
status: approved
risk: low
---

## Responsibility

Report clamped values.

## Requirements

- **C2.1.1** [S1.1] When clamp(x, lo, hi) is called with lo > hi, the library shall raise ValueError.
- **C2.1.2** [S1.1] When clamp returns, the result shall be within [lo, hi].
"""
TASKS = """- **C1.1.1.T2** [C1.1.1] Reject lo > hi with ValueError in calc.clamp.

```yaml
files: ["calc.py"]
invariants: []
```

> Open question: should NaN be rejected too?
"""


def approved_parents(r: Path) -> None:
    project(r)
    for target in ("SYSTEM", "C1"):
        code, out = run_cli(r, "approve", target, "--as", "Srikanth")
        assert code == 0, out
    commit(r, "approve parents")


class TestDescend(unittest.TestCase):
    # sparkwright: S3.1
    def test_system_requirement_descends_to_new_component_draft(self):
        with TempRepo() as r:
            approved_parents(r)
            prep = descend.prepare(r, "S1.1")
            text = (r / prep["prompt"]).read_text()
            self.assertIn("persona: architect", text)
            self.assertIn("C2.1.1", text)
            self.assertIn("CHILDREN THAT ALREADY EXIST", text)  # C1.1.1 is a sibling
            (r / prep["result_file"]).write_text(COMPONENT)
            out = descend.collect(r, prep["run_id"])
            self.assertEqual(out["ids"], ["C2.1.1", "C2.1.2"])
            path = r / out["files"][0]
            self.assertTrue(path.name.startswith("C2-range-reporting"))
            body = path.read_text()
            self.assertIn("id: C2", body)
            self.assertIn("status: draft", body)  # the Architect cannot self-approve
            _, chk = run_cli(r, "check")
            self.assertFalse([f for f in chk["data"]["findings"] if f["code"].startswith(("grammar.", "frontmatter."))])
            self.assertEqual(out["next"], "sparkwright review C2")
            with self.assertRaises(descend.DescendError):
                descend.collect(r, prep["run_id"])  # one collect per run

    def test_draft_with_wrong_ids_or_refs_is_rejected(self):
        with TempRepo() as r:
            approved_parents(r)
            prep = descend.prepare(r, "S1.1")
            bad = COMPONENT.replace("C2.1.2** [S1.1]", "C7.1.2** [S1.1]").replace("C2.1.1** [S1.1]", "C2.1.1** [S9.9]")
            with self.assertRaises(descend.DescendError) as ctx:
                descend.collect(r, prep["run_id"], bad)
            msg = str(ctx.exception)
            self.assertIn("C7.1.2", msg)
            self.assertIn("must reference S1.1", msg)
            self.assertFalse(list((r / "specs/components").glob("C2-*")))

    def test_unapproved_parent_is_refused(self):
        with TempRepo() as r:
            project(r)  # SYSTEM not approved
            with self.assertRaises(descend.DescendError):
                descend.prepare(r, "S1.1")
            code, out = run_cli(r, "descend", "S1.1", "--prepare")
            self.assertEqual(code, 1)
            self.assertIn("approved", out["data"]["error"])

    def test_component_requirement_descends_to_task_files(self):
        with TempRepo() as r:
            approved_parents(r)
            code, prep = run_cli(r, "descend", "C1.1.1", "--prepare")
            self.assertEqual(code, 0, prep)
            self.assertIn("C1.1.1.T2", (r / prep["data"]["prompt"]).read_text())
            (r / prep["data"]["result_file"]).write_text(TASKS)
            code, out = run_cli(r, "descend", "--collect", prep["data"]["run_id"])
            self.assertEqual(code, 0, out)
            self.assertEqual(out["data"]["files"], ["specs/tasks/C1.1.1.T2.md"])
            self.assertEqual(out["data"]["open_questions"], ["should NaN be rejected too?"])
            t = (r / "specs/tasks/C1.1.1.T2.md").read_text()
            self.assertIn("type: task", t)
            self.assertIn('files: ["calc.py"]', t)

    def test_lite_component_gets_tasks_appended(self):
        with TempRepo() as r:
            approved_parents(r)
            p = r / "specs/components/C1.md"
            p.write_text(p.read_text().replace("risk: low", "risk: low\nlite: true", 1) + "\n## Notes\n\nKeep last.\n")
            commit(r, "lite")
            prep = descend.prepare(r, "C1.1.1")
            out = descend.collect(r, prep["run_id"], TASKS)
            self.assertEqual(out["files"], ["specs/components/C1.md"])
            text = p.read_text()
            self.assertLess(text.index("C1.1.1.T1"), text.index("C1.1.1.T2"))
            self.assertLess(text.index("C1.1.1.T2"), text.index("## Notes"))
            self.assertNotIn("Open question", text)
            self.assertIn("status: in-review", text)  # approved file now holds drafts
            from sparkwright.core import checks as _checks
            self.assertNotIn("approval.unconfirmed", [f.code for f in _checks.run(r).findings])

    def test_task_draft_must_declare_files(self):
        with TempRepo() as r:
            approved_parents(r)
            prep = descend.prepare(r, "C1.1.1")
            with self.assertRaises(descend.DescendError):
                descend.collect(r, prep["run_id"], "- **C1.1.1.T2** [C1.1.1] Do it.\n")

    def test_runner_mode_calls_architect(self):
        with TempRepo() as r:
            approved_parents(r)
            fake = FakeProvider(script={"architect": ["```markdown\n" + COMPONENT + "```"]})
            router = Router({"roles": {}, "budgets": {}, "models": {}}, {"fast": fake, "mid": fake, "top": fake})
            out = descend.run(r, "S1.1", router)
            self.assertEqual(out["ids"], ["C2.1.1", "C2.1.2"])
            self.assertEqual([c[0] for c in fake.calls], ["architect"])


if __name__ == "__main__":
    unittest.main()


class TestGuardForDescend(unittest.TestCase):
    def test_guard_allows_architect_result_but_not_specs_elsewhere(self):
        from sparkwright.adapters import guard
        with TempRepo() as r:
            project(r)
            root = r.resolve()
            self.assertEqual(guard.decide_path(root, ".sparkwright/runs/20261024-descend-abc123/architect.result.md")[0], None)
            self.assertEqual(guard.decide_path(root, ".sparkwright/runs/20261024-descend-abc123/x.jsonl")[0], "deny")
            self.assertEqual(guard.decide_path(root, ".sparkwright/runs/x/../../specs/approvals.jsonl")[0], "deny")


class TestPhase4ReviewFixes(unittest.TestCase):
    """Regressions for the independent review of Phase 4 (specs/reviews/2026-10-24-phase4-review.md)."""

    def test_r1_collect_ignores_tampered_run_log(self):
        import json as _json
        with TempRepo() as r:
            approved_parents(r)
            prep = descend.prepare(r, "C1.1.1")
            log = r / ".sparkwright/runs" / f"{prep['run_id']}.jsonl"
            rec = _json.loads(log.read_text().splitlines()[0])
            rec.update({"owner": "../evil.md", "lite": True, "risk": "low\nstatus: approved"})
            log.write_text(_json.dumps(rec) + "\n")
            out = descend.collect(r, prep["run_id"], TASKS)
            self.assertFalse((r.parent / "evil.md").exists())
            self.assertEqual(out["files"], ["specs/tasks/C1.1.1.T2.md"])
            self.assertIn("status: draft", (r / out["files"][0]).read_text())

    def test_r2_risk_change_on_building_task_needs_reapproval(self):
        from sparkwright.core import events as ev
        with TempRepo() as r:
            project(r, risk="high")
            ev.append(r, [ev.make("C1.1.1.T1", "building", run="x", reason="started")])
            p = r / "specs/components/C1.md"
            p.write_text(p.read_text().replace("risk: high", "risk: low"))
            commit(r, "lower risk")
            _, out = run_cli(r, "check")
            self.assertIn("approval.risk-changed", [f["code"] for f in out["data"]["findings"]])
            with self.assertRaises(Exception):
                Build(r, "C1.1.1.T1").advance()

    def test_r4_lowering_risk_mid_build_keeps_security_review(self):
        with TempRepo() as r:
            project(r, risk="high")
            b = Build(r, "C1.1.1.T1")
            b.advance()
            p = r / "specs/components/C1.md"
            p.write_text(p.read_text().replace("risk: high", "risk: low"))
            b = Build(r, "C1.1.1.T1")
            write(ws(b), "tests/test_calc.py", GOOD_TESTS)
            b.submit("test-author", '{"status": "ok"}')
            write(ws(b), "calc.py", CODE)
            b.submit("builder", '{"status": "ok"}')
            self.assertEqual(b.submit("code-reviewer", "[]")["step"], "security-reviewer")

    def test_r5_r6_trivial_or_sneaky_property_tests_rejected(self):
        with TempRepo() as r:
            project_with_invariants(r)
            b = Build(r, "C1.1.1.T1")
            b.advance()
            write(ws(b), "tests/test_calc.py", GOOD_TESTS)
            b.submit("test-author", '{"status": "ok"}')
            write(ws(b), "tests/conftest.py", "import pytest\n")
            write(ws(b), "tests/test_props.py", "# sparkwright: C1.1.1.T1\nimport unittest\n\n"
                  "@unittest.skip('later')\nclass P(unittest.TestCase):\n    def test_x(self):\n        assert True\n")
            ins = b.submit("property-tester", '{"status": "ok"}')
            self.assertEqual(ins["step"], "property-tester")
            self.assertFalse((ws(b) / "tests/conftest.py").exists())
            self.assertIn("skips", (r / ins["prompt"]).read_text())

    def test_r7_review_collect_recomputes_risk(self):
        import json as _json
        from sparkwright.runner import review
        with TempRepo() as r:
            project(r, risk="high")
            prep = review.prepare(r, "C1")
            log = r / ".sparkwright/runs" / f"{prep.run_id}.jsonl"
            rec = _json.loads(log.read_text().splitlines()[0])
            rec["personas"] = [n for n in rec["personas"] if n != "security-reviewer"]
            rec["risk"] = "low"
            log.write_text(_json.dumps(rec) + "\n")
            for name in rec["personas"]:
                (prep.run_dir / f"{name}.json").write_text("[]")
            res = review.collect(r, prep.run_id, {"gates": {"component": "auto"}}, write=False)
            self.assertTrue(res.gate.startswith("HUMAN"), res.gate)
            self.assertIn("security-reviewer", res.abstained)
            self.assertTrue(any("Security Reviewer produced no review" in f.finding for f in res.findings))

    def test_r8_architect_cannot_lower_risk_or_set_status_or_add_other_levels(self):
        with TempRepo() as r:
            approved_parents(r)  # SYSTEM is risk: low in fixtures; make it high
            p = r / "specs/system.md"
            p.write_text(p.read_text().replace("risk: low", "risk: high", 1))
            commit(r, "system high")
            run_cli(r, "approve", "SYSTEM", "--as", "Srikanth")  # risk change voided the approval
            commit(r, "re-approve at high risk")
            prep = descend.prepare(r, "S1.1")
            out = descend.collect(r, prep["run_id"], COMPONENT.replace("status: approved", "status: approved\nowner: me"))
            body = (r / out["files"][0]).read_text()
            self.assertIn("risk: high", body)
            self.assertIn("status: draft", body)
            self.assertNotIn("owner:", body)
            prep = descend.prepare(r, "S1.1")
            with self.assertRaises(descend.DescendError):
                descend.collect(r, prep["run_id"], COMPONENT.replace("C9", "C3").replace("C2.", "C3.")
                                + "- **S1.9** [V1] Sneaky new system requirement.\n")

    def test_r10_task_line_in_fence_rejected_and_r11_backslash_title_parses(self):
        with TempRepo() as r:
            approved_parents(r)
            prep = descend.prepare(r, "C1.1.1")
            fenced = TASKS + "\n```text\n- **C1.1.1.T3** [C1.1.1] Hidden.\n```\n"
            with self.assertRaises(descend.DescendError):
                descend.collect(r, prep["run_id"], fenced)
            prep = descend.prepare(r, "C1.1.1")
            out = descend.collect(r, prep["run_id"], TASKS.replace("calc.clamp.", "calc\\\\"))
            _, chk = run_cli(r, "check")
            self.assertFalse([f for f in chk["data"]["findings"] if f["code"].startswith("frontmatter.")], out)
