"""Regression tests for the independent code review of 2026-10-24 (see specs/reviews/2026-10-24-code-review.md)."""
import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout

from sparkwright.adapters import claude_code
from sparkwright.cli import main
from sparkwright.core import checks
from sparkwright.runner import interview, mutate
from sparkwright.runner.providers import FakeProvider
from sparkwright.runner.review import Finding, merge, prepare, run_review, ReviewError, collect
from sparkwright.runner.router import ConfigError, Router
from sparkwright.runner.runlog import RunLog
from helpers import TempRepo, basic_repo, commit, git, git_init, run_cli, spec, write

codes = lambda res: {f.code for f in res.findings if f.severity == "error"}


def fake_router(fake, **cfg):
    base = {"roles": {}, "budgets": {}, "gates": {}, "models": {}}
    base.update(cfg)
    return Router(base, {"fast": fake, "mid": fake, "top": fake})


class TestHigh(unittest.TestCase):
    def test_f1_abstaining_personas_do_not_satisfy_minimum(self):
        with TempRepo() as r:
            basic_repo(r)
            write(r, "specs/components/C1.md", spec("C1", "component", "- **C1.1.1** [S1.1] c\n"))
            res = run_review(r, "C1", fake_router(FakeProvider(default="I refuse.")), write=False)
            self.assertEqual(res.ran, [])
            self.assertTrue(res.gate.startswith("FAIL"))

    def test_f2_merge_mixed_findings_does_not_crash(self):
        out = merge({"a": [Finding("high", [], "no ids here at all", "x")],
                     "b": [Finding("high", ["S1.2"], "something else entirely", "y")]})
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].ids, ["S1.2"])

    def test_f3_unknown_baseline_is_an_error(self):
        with TempRepo() as r:
            basic_repo(r)
            git_init(r)
            commit(r, "x")
            write(r, ".sparkwright/config.yaml", "baseline: " + "d" * 40 + "\n")
            self.assertIn("git.log-failed", codes(checks.run(r)))

    def test_f4_non_ascii_paths_are_checked(self):
        with TempRepo() as r:
            basic_repo(r)
            git_init(r)
            base = commit(r, "x")
            write(r, ".sparkwright/config.yaml", f"baseline: {base}\ntrailers: warn\n")
            git(r, "add", "-A"); git(r, "commit", "-q", "-m", "cfg")
            write(r, "specs/café.md", "---\nid: D9\ntitle: t\ntype: decision\nstatus: draft\n---\n")
            commit(r, "sneak\n\nSparkWright-Role: builder")
            self.assertIn("role.path-violation", codes(checks.run(r)))

    def test_f5_builder_cannot_disable_its_guardrails(self):
        with TempRepo() as r:
            basic_repo(r)
            git_init(r)
            base = commit(r, "x")
            write(r, ".sparkwright/config.yaml", f"baseline: {base}\ntrailers: 'off'\nprotected:\n  builder: []\n")
            write(r, "specs/system.md", spec("SYSTEM", "system", "- **S1.1** [V1] changed by builder\n"))
            commit(r, "disable\n\nSparkWright-Role: builder")
            got = checks.run(r)
            violations = [f.file for f in got.findings if f.code == "role.path-violation"]
            self.assertIn(".sparkwright/config.yaml", violations)
            self.assertIn("specs/system.md", violations)

    def _guard(self, root, payload):
        out = subprocess.run([sys.executable, str(root / "plugin/hooks/guard.py")], input=json.dumps(payload),
                             capture_output=True, text=True, env={"CLAUDE_PROJECT_DIR": str(root)})
        return json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"] if out.stdout.strip() else "allow"

    def test_f6_guard_covers_bash_relative_paths_and_claude_settings(self):
        with TempRepo() as r:
            claude_code.generate(r / "plugin")
            basic_repo(r)
            write(r, "tests/test_a.py", "assert True\n")
            run_cli(r, "approve", "tests/test_a.py", "--test", "--as", "Srikanth")
            bash = lambda c: self._guard(r, {"tool_name": "Bash", "tool_input": {"command": c}})
            self.assertEqual(bash("echo '{}' >> specs/approvals.jsonl"), "deny")
            self.assertEqual(bash("sparkwright approve SYSTEM --as Srikanth"), "deny")
            self.assertEqual(bash("python -m sparkwright -C . approve S1.1 --as x"), "deny")
            self.assertEqual(bash("pytest -q"), "allow")
            edit = lambda p: self._guard(r, {"tool_name": "Edit", "tool_input": {"file_path": p}})
            self.assertEqual(edit("tests/test_a.py"), "deny")          # relative path
            self.assertEqual(edit(".claude/settings.json"), "ask")
            manifest = json.loads((r / "plugin/.claude-plugin/plugin.json").read_text())
            self.assertIn("Bash", manifest["hooks"]["PreToolUse"][0]["matcher"])

    def test_f7_run_ids_cannot_escape_runs_folder(self):
        with TempRepo() as r:
            basic_repo(r)
            with self.assertRaises(ValueError):
                RunLog(r, "review", "../../specs/approvals")
            with self.assertRaises(ReviewError):
                collect(r, "../../specs/approvals")
            self.assertFalse((r / "specs/approvals.jsonl").exists())


class TestMedium(unittest.TestCase):
    def test_f8_line_numbers_are_exact(self):
        with TempRepo() as r:
            basic_repo(r)
            write(r, "specs/system.md", spec("SYSTEM", "system", "- **S1.1** [V9] x\n"))
            f = [f for f in checks.run(r).findings if f.code == "ref.unknown"][0]
            lines = (r / "specs/system.md").read_text().splitlines()
            self.assertTrue(lines[f.line - 1].startswith("- **S1.1**"))

    def test_f9_approved_evidence_cannot_be_rewritten(self):
        with TempRepo() as r:
            basic_repo(r)
            self.assertEqual(run_cli(r, "approve", "E1", "--as", "Srikanth")[0], 0)
            self.assertTrue(checks.run(r).ok)
            p = r / "specs/evidence/E1.md"
            p.write_text(p.read_text().replace("Quotes.", "Different quotes."))
            self.assertIn("approval.hash-mismatch", codes(checks.run(r)))

    def test_f10_forged_change_request_in_approvals_is_caught(self):
        with TempRepo() as r:
            basic_repo(r)
            from sparkwright.core import approvals
            from sparkwright.core.store import load
            req = load(r).requirements["S1.1"]
            approvals.append(r, [approvals.Approval("S1.1", req.hash, "x", "human", "CR404", approvals.now())])
            self.assertIn("approval.unknown-change-request", codes(checks.run(r)))

    def test_f11_unquoted_trailers_off(self):
        with TempRepo() as r:
            basic_repo(r)
            write(r, ".sparkwright/config.yaml", "trailers: off\n")
            res = checks.run(r)
            self.assertNotIn("config.invalid", codes(res))
            self.assertEqual(res.config["trailers"], "off")

    def test_f13_encoding_bom_and_crlf(self):
        with TempRepo() as r:
            basic_repo(r)
            (r / "specs/bad.md").write_bytes("---\nid: D2\n---\ncaf\xe9".encode("cp1252"))
            self.assertIn("encoding.invalid", codes(checks.run(r)))
            (r / "specs/bad.md").unlink()
            text = (r / "specs/system.md").read_text()
            (r / "specs/system.md").write_bytes(("﻿" + text).replace("\n", "\r\n").encode("utf-8"))
            res = checks.run(r)
            self.assertTrue(res.ok, [f for f in res.findings if f.severity == "error"])
            self.assertIn("S1.1", res.nodes)
            self.assertEqual(run_cli(r, "approve", "SYSTEM", "--as", "Srikanth")[0], 0)
            raw = (r / "specs/system.md").read_bytes()
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))  # line endings preserved (finding 20)

    def test_f14_missing_tier_is_a_clean_error(self):
        with TempRepo() as r:
            basic_repo(r)
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["-C", str(r), "review", "SYSTEM", "--json"])
            out = json.loads(buf.getvalue())
            self.assertEqual(code, 1)
            self.assertIn("no model configured", out["data"]["error"])

    def test_f15_risk_required_for_components(self):
        with TempRepo() as r:
            basic_repo(r)
            write(r, "specs/components/C1.md", "---\nid: C1\ntitle: t\ntype: component\nstatus: draft\n---\n- **C1.1.1** [S1.1] c\n")
            self.assertIn("frontmatter.missing-field", codes(checks.run(r)))

    def test_f16_mutate_includes_new_files_and_reports_bad_command(self):
        with TempRepo() as r:
            write(r, "a.py", "X = 1\n")
            git_init(r)
            base = commit(r, "start")
            write(r, "newmod.py", "def ok(x):\n    return x > 3\n")
            rep = mutate.run(r, base, f"{sys.executable} -c \"import newmod\"", time_budget_s=30)
            self.assertGreater(rep.total, 0)
            self.assertLess(rep.score, 1.0)
            bad = mutate.run(r, base, "definitely-not-a-binary-xyz", time_budget_s=10)
            self.assertFalse(bad.baseline_ok)
            self.assertIn("cannot run test command", bad.message)

    def test_s116_usage_errors_are_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit):
            main(["--json", "trace"])
        self.assertFalse(json.loads(buf.getvalue())["ok"])


class TestLow(unittest.TestCase):
    def test_f19_redaction_keeps_dates_and_order_numbers(self):
        out = interview.redact("On 2026.10.24, Order 1234567, call +1 (555) 123-4567")
        self.assertIn("2026.10.24", out)
        self.assertIn("1234567", out.replace("[phone]", ""))
        self.assertNotIn("555", out)

    def test_f21_corrupt_run_log_line_is_skipped(self):
        with TempRepo() as r:
            log = RunLog(r, "review", "test-run")
            log.append("a", status="done")
            with log.path.open("a") as fh:
                fh.write('{"torn": \n')
            log.append("b", status="done")
            self.assertEqual(set(log.completed()), {"a", "b"})


if __name__ == "__main__":
    unittest.main()
