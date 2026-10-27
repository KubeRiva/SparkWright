"""D009: fixes for the R008 review findings."""
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from sparkwright.core import checks
from sparkwright.runner import interview, verify
from sparkwright.runner.build import Build
from helpers import TempRepo, basic_repo, commit, git, git_init, run_cli, spec, write
from test_build import PY, project, ws

TXT_TESTS = ("# sparkwright: C1.1.1.T1\nimport unittest\nfrom pathlib import Path\n\n"
             "class T(unittest.TestCase):\n    def test_answer(self):\n"
             "        self.assertEqual(Path('calc.txt').read_text().strip(), '42')\n")


def txt_project(r: Path, extra_cfg: str = "") -> None:
    write(r, "specs/evidence/E1.md", "---\nid: E1\ntitle: t\ntype: evidence\nstatus: draft\n---\nNeeds an answer.\n")
    write(r, "specs/vision.md", spec("VISION", "vision", "- **V1** [E1] Users get the answer.\n"))
    write(r, "specs/system.md", spec("SYSTEM", "system", "- **S1.1** [V1] The file shall hold the answer.\n"))
    write(r, "specs/components/C1.md", spec("C1", "component",
          "- **C1.1.1** [S1.1] calc.txt holds 42.\n\n## Tasks\n\n- **C1.1.1.T1** [C1.1.1] Write the answer.\n\n"
          "```yaml\nfiles: [\"calc.txt\"]\n```\n"))
    write(r, "calc.txt", "")
    write(r, "tests/__init__.py", "")
    write(r, ".sparkwright/config.yaml",
          f"checks:\n  test: \"{PY} -m unittest discover -s tests -t .\"\ntrailers: warn\n"
          "approvers:\n  - {name: Srikanth, email: t@example.com}\n"
          + (extra_cfg or "mutation: {min: 0.8, time_budget_s: 120}\n") + "test_globs: [\"tests/*\"]\n")
    write(r, ".gitignore", ".sparkwright/ledger.json\n.sparkwright/runs/\n.sparkwright/worktrees/\n__pycache__/\n")
    git_init(r)
    commit(r, "start")
    run_cli(r, "approve", "C1.1.1.T1", "--as", "Srikanth")
    commit(r, "approve task")


class TestMutationNotRun(unittest.TestCase):
    def _run(self, r):
        b = Build(r, "C1.1.1.T1")
        b.advance()
        write(ws(b), "tests/test_calc.py", TXT_TESTS)
        b.submit("test-author", "{}")
        write(ws(b), "calc.txt", "42\n")
        return b, b.submit("builder", "{}")

    def test_no_mutants_on_changed_source_blocks(self):
        with TempRepo() as r:
            txt_project(r)
            b, ins = self._run(r)
            self.assertEqual(b.state.phase, "blocked", ins)
            self.assertIn("allow_not_run", b.state.reason if hasattr(b.state, "reason") else json.dumps(ins))

    def test_allowed_not_run_is_recorded(self):
        with TempRepo() as r:
            txt_project(r, "mutation: {min: 0.8, time_budget_s: 120, allow_not_run: true}\n")
            b, ins = self._run(r)
            self.assertNotEqual(b.state.phase, "blocked", ins)
            self.assertEqual(b.state.result.get("mutation"), "not-run")
            self.assertTrue(any(f.code == "config.weakened" for f in checks.run(r).findings))


class TestConfigAndTrust(unittest.TestCase):
    def test_weakening_values_warn(self):
        cfg = {"drift_exclude": ["**"], "trailers": "off", "require_signed": False, "test_globs": ["tests/*"]}
        msgs = checks.weakened_config(cfg)
        self.assertEqual(len(msgs), 3)

    def test_status_reports_identity_strength(self):
        with TempRepo() as r:
            basic_repo(r)
            write(r, ".sparkwright/config.yaml", "approvers:\n  - {name: Srikanth, email: t@example.com}\ntrailers: off\n")
            git_init(r)
            commit(r, "start")
            code, out = run_cli(r, "status")
            self.assertIn("advisory", out["data"]["approver_identity"])

    def test_protected_change_without_approvers_is_an_error(self):
        with TempRepo() as r:
            write(r, "specs/vision.md", spec("VISION", "vision", "- **V1** [A1] It shall trace.\n"))
            write(r, ".sparkwright/config.yaml", "trailers: off\n")
            git_init(r)
            commit(r, "start")
            write(r, ".github/workflows/ci.yml", "on: push\n")
            commit(r, "ci")
            f = [f for f in checks.run(r).findings if f.code == "protected.no-approvers"]
            self.assertTrue(f and f[0].severity == "error")


class TestSandbox(unittest.TestCase):
    def test_home_is_isolated_by_default(self):
        with mock.patch.dict(os.environ, {"HOME": "/home/real"}):
            env = verify.command_env({}, "/tmp/x", [], {})
        self.assertNotEqual(env["HOME"], "/home/real")
        self.assertIn("sparkwright-home-", env["HOME"])

    def test_home_isolation_can_be_turned_off(self):
        with mock.patch.dict(os.environ, {"HOME": "/home/real"}):
            env = verify.command_env({}, "/tmp/x", [], {"isolate_home": False})
        self.assertEqual(env["HOME"], "/home/real")

    def test_network_off_wraps_or_refuses(self):
        env = verify.command_env({}, "/tmp/x", [], {"network": False})
        try:
            argv = verify.sandboxed(["python", "-V"], env)
            self.assertEqual(argv[:2], ["unshare", "-rn"])
        except OSError as exc:
            self.assertIn("cannot cut network", str(exc))


class TestNames(unittest.TestCase):
    def test_full_names_left_in_a_transcript_are_flagged(self):
        text = "Interviewer: Who helps you?\nOwner: My coach Jane Porter checks my games."
        self.assertEqual(interview.unredacted_names(text), ["Jane Porter"])
        with self.assertRaises(interview.InterviewError):
            interview._guard_names(text, keep_names=False)
        interview._guard_names(text, keep_names=True)
        self.assertEqual(interview.unredacted_names(interview.redact(text, ["Jane Porter"])), [])


class TestStrictGuard(unittest.TestCase):
    def _root(self, r, strict):
        write(r, ".sparkwright/config.yaml", f"guard: {{strict: {'true' if strict else 'false'}}}\n")
        from sparkwright.adapters import guard
        guard._CFG.clear()
        return guard

    def test_strict_blocks_code_outside_a_build(self):
        with TempRepo() as r:
            guard = self._root(r, True)
            d, why = guard.decide("claude-code", r, "Write", {"file_path": str(r / "src/app.py")})
            self.assertEqual(d, "deny")
            self.assertIn("strict mode", why)

    def test_strict_allows_specs_docs_and_build_workspaces(self):
        with TempRepo() as r:
            guard = self._root(r, True)
            for path in ("specs/components/C1.md", "README.md", ".sparkwright/worktrees/C1.1.1.T1/src/app.py"):
                d, _ = guard.decide("claude-code", r, "Write", {"file_path": str(r / path)})
                self.assertIsNone(d, path)

    def test_strict_asks_before_untraced_commits(self):
        with TempRepo() as r:
            guard = self._root(r, True)
            d, _ = guard.decide("claude-code", r, "Bash", {"command": "git commit -am 'quick fix'"})
            self.assertEqual(d, "ask")

    def test_default_is_not_strict(self):
        with TempRepo() as r:
            guard = self._root(r, False)
            d, _ = guard.decide("claude-code", r, "Write", {"file_path": str(r / "src/app.py")})
            self.assertIsNone(d)


if __name__ == "__main__":
    unittest.main()


class TestR009(unittest.TestCase):
    def test_glob_rules(self):
        from sparkwright.core.globs import match
        self.assertTrue(match("tests/a.py", ["tests/**/*"]))
        self.assertTrue(match("tests/x/a.py", ["tests/**/*"]))
        self.assertTrue(match("test_a.py", ["**/test_*.py"]))
        self.assertTrue(match("src", ["src/**"]))
        self.assertFalse(match("lib/a.py", ["tests/**/*"]))

    def test_runner_approval_of_a_requirement_never_counts(self):
        from sparkwright.core.approvals import Approval, latest
        got = latest([Approval("S1.1", "h", "x", "runner", None, "t"), Approval("test:t.py", "h", "x", "runner", None, "t")])
        self.assertNotIn("S1.1", got)
        self.assertIn("test:t.py", got)

    def test_new_approvals_carry_the_hash_scheme_version(self):
        with TempRepo() as r:
            basic_repo(r)
            write(r, ".sparkwright/config.yaml", "approvers:\n  - {name: Srikanth, email: t@example.com}\n")
            git_init(r)
            commit(r, "start")
            run_cli(r, "approve", "SYSTEM", "--as", "Srikanth")
            line = json.loads((r / "specs/approvals.jsonl").read_text().splitlines()[-1])
            self.assertEqual(line.get("v"), 2)


class TestFreshInit(unittest.TestCase):
    def test_check_passes_right_after_init(self):
        with TempRepo() as r:
            git_init(r)
            write(r, "README.md", "x\n")
            commit(r, "start")
            self.assertEqual(run_cli(r, "init")[0], 0)
            commit(r, "init")
            res = checks.run(r)
            self.assertTrue(res.ok, [(f.code, f.message) for f in res.findings if f.severity == "error"])

    def test_requirement_lines_in_html_comments_are_ignored(self):
        from sparkwright.core.grammar import parse_body
        reqs, issues = parse_body("<!-- example:\n- **V1** [E1] x\n-->\n- **V2** [A1] real\n", "v.md")
        self.assertEqual([r.id for r in reqs], ["V2"])


class TestUnapprovedEvidence(unittest.TestCase):
    def test_approved_vision_citing_unapproved_evidence_warns(self):
        with TempRepo() as r:
            basic_repo(r)
            write(r, ".sparkwright/config.yaml", "approvers:\n  - {name: Srikanth, email: t@example.com}\ntrailers: off\n")
            git_init(r)
            commit(r, "start")
            run_cli(r, "approve", "VISION", "--as", "Srikanth")
            found = [f for f in checks.run(r).findings if f.code == "vision.unapproved-evidence"]
            self.assertEqual(len(found), 1)
            run_cli(r, "approve", "E1", "--as", "Srikanth")
            self.assertFalse([f for f in checks.run(r).findings if f.code == "vision.unapproved-evidence"])


class TestLogLineEndings(unittest.TestCase):
    def test_logs_are_written_with_lf(self):
        with TempRepo() as r:
            basic_repo(r)
            write(r, ".sparkwright/config.yaml", "approvers:\n  - {name: Srikanth, email: t@example.com}\n")
            git_init(r)
            commit(r, "start")
            run_cli(r, "approve", "SYSTEM", "--as", "Srikanth")
            self.assertNotIn(b"\r\n", (r / "specs/approvals.jsonl").read_bytes())
