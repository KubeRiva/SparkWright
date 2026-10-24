import json
import unittest

from sparkwright.core import checks
from helpers import TempRepo, basic_repo, commit, git_init, run_cli, spec, write


def codes(res, severity="error"):
    return sorted({f.code for f in res.findings if f.severity == severity})


class TestReferencesAndCoverage(unittest.TestCase):
    def test_basic_repo_passes(self):
        with TempRepo() as r:
            basic_repo(r)
            res = checks.run(r)
            self.assertTrue(res.ok, res.findings)
            self.assertIn("coverage.level-not-started", codes(res, "info"))

    # sparkwright: S2.3
    def test_unknown_and_wrong_level_refs(self):
        with TempRepo() as r:
            basic_repo(r)
            write(r, "specs/system.md", spec("SYSTEM", "system", "- **S1.1** [V9] a\n- **S1.2** [E1] b\n- **S1.3** [V1] c\n"))
            res = checks.run(r)
            self.assertIn("ref.unknown", codes(res))
            self.assertIn("ref.wrong-level", codes(res))

    # sparkwright: S1.4
    def test_vision_without_evidence(self):
        with TempRepo() as r:
            basic_repo(r)
            write(r, "specs/evidence/E2.md", "---\nid: E2\ntitle: t\ntype: evidence\nstatus: draft\nsimulated: true\n---\n")
            write(r, "specs/vision.md", spec("VISION", "vision", "- **V1** [E2] Simulated only.\n- **A1** [] Belief.\n- **V2** [A1] Assumed.\n"))
            write(r, "specs/system.md", spec("SYSTEM", "system", "- **S1.1** [V1, V2] x\n"))
            res = checks.run(r)
            bad = [f for f in res.findings if f.code == "vision.no-evidence"]
            self.assertEqual([f.id for f in bad], ["V1"])

    def test_parent_without_children_when_level_started(self):
        with TempRepo() as r:
            basic_repo(r)
            write(r, "specs/vision.md", spec("VISION", "vision", "- **V1** [E1] a\n- **V2** [E1] b\n"))
            res = checks.run(r)
            self.assertEqual([f.id for f in res.findings if f.code == "coverage.no-children"], ["V2"])

    def test_task_scope_and_missing_test(self):
        with TempRepo() as r:
            basic_repo(r)
            write(r, "specs/components/C1.md", spec("C1", "component", "- **C1.1.1** [S1.1] comp\n- **C1.1.2** [S1.1] comp2\n"))
            write(r, "specs/tasks/T.md", spec("C1.1.1.T1", "task", "- **C1.1.1.T1** [C1.1.1] t\n- **C1.1.2.T1** [C1.1.1] wrong scope\n", status="building"))
            res = checks.run(r)
            self.assertIn("ref.task-scope", codes(res))
            self.assertIn("approval.unconfirmed", codes(res))  # front matter alone cannot make a task 'building'
            run_cli(r, "approve", "C1.1.1.T1", "--as", "Srikanth")
            run_cli(r, "approve", "C1.1.2.T1", "--as", "Srikanth")
            res = checks.run(r)
            self.assertNotIn("task.no-test", codes(res))  # approved tasks have no tests yet
            from sparkwright.core import events
            events.append(r, [events.make("C1.1.1.T1", "done"), events.make("C1.1.2.T1", "done")])
            res = checks.run(r)
            self.assertIn("task.no-test", codes(res))
            write(r, "tests/test_t.py", "# sparkwright: C1.1.1.T1\n# sparkwright: C1.1.2.T1\n")
            res = checks.run(r)
            self.assertNotIn("task.no-test", codes(res))

    def test_duplicate_ids(self):
        with TempRepo() as r:
            basic_repo(r)
            write(r, "specs/system.md", spec("SYSTEM", "system", "- **S1.1** [V1] a\n- **S1.1** [V1] b\n"))
            self.assertIn("grammar.duplicate-id", codes(checks.run(r)))

    def test_config_gate_override_rejected(self):
        with TempRepo() as r:
            basic_repo(r)
            write(r, ".sparkwright/config.yaml", "gates:\n  system: auto\n")
            self.assertIn("config.invalid", codes(checks.run(r)))


class TestApprovals(unittest.TestCase):
    # sparkwright: S2.4
    def test_approve_then_edit_fails_until_change_request(self):
        with TempRepo() as r:
            basic_repo(r)
            code, out = run_cli(r, "approve", "SYSTEM", "--as", "Srikanth")
            self.assertEqual(code, 0)
            self.assertEqual(out["data"]["approved"], ["S1.1"])
            self.assertIn("status: approved", (r / "specs/system.md").read_text())
            self.assertTrue(checks.run(r).ok)
            write(r, "specs/system.md", spec("SYSTEM", "system", "- **S1.1** [V1] The parser shall parse fast.\n", status="approved"))
            self.assertIn("approval.hash-mismatch", codes(checks.run(r)))
            code, out = run_cli(r, "approve", "SYSTEM", "--as", "Srikanth")
            self.assertEqual(code, 1)
            self.assertEqual(out["data"]["needs_change_request"], ["S1.1"])
            code, out = run_cli(r, "approve", "SYSTEM", "--as", "Srikanth", "--cr", "CR999")
            self.assertEqual(code, 1, "an unknown change request must be refused")
            write(r, "specs/changes/CR1.md", "---\nid: CR1\ntitle: faster parsing\ntype: change\nstatus: approved\n"
                  "target: S1.1\n---\n")
            code, out = run_cli(r, "approve", "SYSTEM", "--as", "Srikanth", "--cr", "CR1")
            self.assertEqual(code, 1, "the change request must be applied first")
            self.assertEqual(run_cli(r, "change", "apply", "CR1")[0], 0)
            code, out = run_cli(r, "approve", "SYSTEM", "--as", "Srikanth", "--cr", "CR1")
            self.assertEqual(out["data"].get("needs_review"), ["S1.1"], "S3.10: review before re-approval")
            from test_phase5 import host_review
            host_review(r, "SYSTEM")
            code, out = run_cli(r, "approve", "SYSTEM", "--as", "Srikanth", "--cr", "CR1")
            self.assertEqual(code, 0, out)
            self.assertTrue(checks.run(r).ok)

    def test_forged_status_is_caught(self):
        with TempRepo() as r:
            basic_repo(r)
            write(r, "specs/system.md", spec("SYSTEM", "system", "- **S1.1** [V1] x\n", status="approved"))
            self.assertIn("approval.unconfirmed", codes(checks.run(r)))

    def test_locked_test_change_detected(self):
        with TempRepo() as r:
            basic_repo(r)
            write(r, "tests/test_a.py", "assert True\n")
            code, _ = run_cli(r, "approve", "tests/test_a.py", "--test", "--as", "Srikanth")
            self.assertEqual(code, 0)
            self.assertTrue(checks.run(r).ok)
            write(r, "tests/test_a.py", "assert 1\n")
            self.assertIn("approval.locked-test-changed", codes(checks.run(r)))


class TestCommits(unittest.TestCase):
    def _task_repo(self, r):
        basic_repo(r)
        write(r, "specs/components/C1.md", spec("C1", "component", "- **C1.1.1** [S1.1] comp\n"))
        write(r, "specs/tasks/T.md", spec("C1.1.1.T1", "task",
              "- **C1.1.1.T1** [C1.1.1] t\n\n```yaml\nfiles: [\"src/a/**\"]\n```\n"))
        write(r, "tests/test_t.py", "# sparkwright: C1.1.1.T1\n")
        git_init(r)
        base = commit(r, "initial")
        write(r, ".sparkwright/config.yaml", f"baseline: {base}\napprovers:\n  - {{name: Srikanth, email: t@example.com}}\n")
        run_cli(r, "approve", "C1.1.1.T1", "--as", "Srikanth")
        # mark task file approved after approval exists
        p = r / "specs/tasks/T.md"
        p.write_text(p.read_text().replace("status: draft", "status: approved"))
        commit(r, "setup\n\nSparkWright-Task: C1.1.1.T1")
        return base

    # sparkwright: S2.6
    def test_trailers_drift_and_roles(self):
        with TempRepo() as r:
            self._task_repo(r)
            res = checks.run(r)
            self.assertTrue(res.ok, [f for f in res.findings if f.severity == "error"])
            write(r, "src/a/x.py", "x = 1\n")
            commit(r, "in scope\n\nFiles:\n- src/a/x.py\n\nSparkWright-Task: C1.1.1.T1\nSparkWright-Role: builder")
            self.assertTrue(checks.run(r).ok)
            write(r, "src/b/y.py", "y = 1\n")
            commit(r, "no trailer, out of scope")
            got = codes(checks.run(r))
            self.assertIn("commit.no-trailer", got)
            self.assertIn("drift.untracked-file", got)

    # sparkwright: S6.5
    def test_builder_touching_specs_is_a_violation(self):
        with TempRepo() as r:
            self._task_repo(r)
            write(r, "specs/system.md", spec("SYSTEM", "system", "- **S1.1** [V1] The parser shall parse.\n"))
            write(r, "specs/notes.md", "---\nid: D1\ntitle: t\ntype: decision\nstatus: draft\n---\n")
            commit(r, "sneaky\n\nSparkWright-Task: C1.1.1.T1\nSparkWright-Role: builder")
            self.assertIn("role.path-violation", codes(checks.run(r)))


class TestDeterminismAndCli(unittest.TestCase):
    # sparkwright: S11.2
    def test_ledger_is_deterministic(self):
        with TempRepo() as r:
            basic_repo(r)
            checks.run(r)
            a = (r / ".sparkwright/ledger.json").read_text()
            checks.run(r)
            self.assertEqual(a, (r / ".sparkwright/ledger.json").read_text())
            self.assertEqual(json.loads(a)["S1.1"]["refs"], ["V1"])

    # sparkwright: S11.6
    def test_json_envelope_and_trace(self):
        with TempRepo() as r:
            basic_repo(r)
            code, out = run_cli(r, "trace", "S1.1")
            self.assertEqual(code, 0)
            self.assertEqual(set(out), {"ok", "command", "data"})
            self.assertEqual(out["data"]["up"], [["S1.1", "V1", "E1"]])
            code, out = run_cli(r, "check")
            self.assertTrue(out["ok"])

    def test_init_creates_layout(self):
        with TempRepo() as r:
            code, out = run_cli(r, "init")
            self.assertEqual(code, 0)
            self.assertTrue((r / "specs/constitution.md").exists())
            self.assertTrue((r / ".sparkwright/config.yaml").exists())
            self.assertIn(".sparkwright/ledger.json", (r / ".gitignore").read_text())


if __name__ == "__main__":
    unittest.main()
