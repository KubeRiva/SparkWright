import json
import subprocess
import sys
import unittest

from sparkwright.adapters import agents_md, claude_code
from sparkwright.adapters.neutral import load_skills
from sparkwright.runner.review import collect, prepare
from helpers import TempRepo, basic_repo, run_cli, write

FIND = lambda sev, text: json.dumps([{"severity": sev, "ids": ["S1.1"], "finding": text, "fix": "x"}])


class TestNeutralSkills(unittest.TestCase):
    # sparkwright: S8.3
    def test_skills_render_without_unfilled_slots(self):
        skills = load_skills()
        self.assertEqual({s.name for s in skills}, {"sparkwright-review", "sparkwright-interview", "sparkwright-check", "sparkwright-mutate"})
        for s in skills:
            self.assertNotIn("{{", s.render(run_agents="X"))


class TestClaudeCodeAdapter(unittest.TestCase):
    # sparkwright: S8.4
    def test_generate_plugin(self):
        with TempRepo() as r:
            files = claude_code.generate(r / "plugin")
            manifest = json.loads((r / "plugin/.claude-plugin/plugin.json").read_text())
            self.assertEqual(manifest["name"], "sparkwright")
            for path in manifest["agents"]:
                agent = (r / "plugin" / path).read_text()
                self.assertIn("omitClaudeMd: true", agent)
                self.assertIn("tools: [Read, Grep, Glob]", agent)
            skill = (r / "plugin/skills/sparkwright-review/SKILL.md").read_text()
            self.assertIn("sparkwright:sparkwright-<persona>", skill)
            self.assertIn("hooks/guard.py", files)

    def _guard(self, root, rel):
        payload = json.dumps({"tool_input": {"file_path": str(root / rel)}, "cwd": str(root)})
        out = subprocess.run([sys.executable, str(root / "plugin/hooks/guard.py")], input=payload,
                             capture_output=True, text=True, env={"CLAUDE_PROJECT_DIR": str(root)})
        return json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"] if out.stdout.strip() else "allow"

    # sparkwright: S6.5
    def test_guard_hook(self):
        with TempRepo() as r:
            claude_code.generate(r / "plugin")
            basic_repo(r)
            write(r, "tests/test_a.py", "assert True\n")
            run_cli(r, "approve", "tests/test_a.py", "--test", "--as", "Srikanth")
            self.assertEqual(self._guard(r, "specs/approvals.jsonl"), "deny")
            self.assertEqual(self._guard(r, "tests/test_a.py"), "deny")
            self.assertEqual(self._guard(r, "specs/constitution.md"), "ask")
            self.assertEqual(self._guard(r, "src/app.py"), "allow")


class TestHostAgentReview(unittest.TestCase):
    # sparkwright: S8.2
    def test_prepare_then_collect(self):
        with TempRepo() as r:
            basic_repo(r)
            prep = prepare(r, "SYSTEM")
            self.assertTrue(prep.context_path.read_text().startswith("=== ARTIFACT"))
            (prep.run_dir / "coverage-auditor.json").write_text(FIND("medium", "S1.1 misses error handling"))
            (prep.run_dir / "newcomer.json").write_text("Here you go: " + FIND("low", "Term 'parse' undefined"))
            res = collect(r, prep.run_id)
            self.assertEqual(sorted(res.ran), ["coverage-auditor", "newcomer"])
            self.assertIn("contradiction-hunter", res.abstained)
            self.assertIn("HUMAN", res.gate)
            self.assertTrue(res.path.exists())

    def test_collect_fails_gate_with_fewer_than_two(self):
        with TempRepo() as r:
            basic_repo(r)
            prep = prepare(r, "SYSTEM")
            (prep.run_dir / "newcomer.json").write_text("[]")
            self.assertIn("FAIL", collect(r, prep.run_id).gate)


class TestAgentsMd(unittest.TestCase):
    def test_write_is_idempotent_and_preserves_user_text(self):
        with TempRepo() as r:
            write(r, "AGENTS.md", "# My project\n\nOwn rules.\n")
            agents_md.write(r)
            agents_md.write(r)
            text = (r / "AGENTS.md").read_text()
            self.assertEqual(text.count(agents_md.START), 1)
            self.assertIn("Own rules.", text)
            self.assertIn("sparkwright check", text)


if __name__ == "__main__":
    unittest.main()
