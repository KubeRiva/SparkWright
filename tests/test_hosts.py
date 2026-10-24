"""Host adapters beyond Claude Code: Codex and Gemini CLI (SYSTEM S8.1-S8.4)."""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from sparkwright.adapters import codex, gemini, guard
from sparkwright.core.frontmatter import split
from helpers import TempRepo, git_init, run_cli, write
from test_build import project

PATCH = """*** Begin Patch
*** Update File: src/app.py
@@
-x = 1
+x = 2
*** Add File: specs/approvals.jsonl
+{}
*** End Patch"""


def hook(host, root, payload):
    buf = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps({"cwd": str(root), **payload}))), redirect_stdout(buf):
        guard.main(host)
    return json.loads(buf.getvalue()) if buf.getvalue().strip() else None


class TestCodexAdapter(unittest.TestCase):
    # sparkwright: S8.3
    def test_generate(self):
        with TempRepo() as r:
            files = codex.generate(r)
            self.assertIn(".codex/hooks.json", files)
            hooks = json.loads((r / ".codex/hooks.json").read_text())
            self.assertEqual(hooks["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "sparkwright guard --host codex")
            skill = (r / ".agents/skills/sparkwright-review/SKILL.md").read_text()
            self.assertIn("sparkwright_<persona>", skill)
            self.assertNotIn("{{", skill)
            self.assertNotIn("Agent tool", skill)
            agent = (r / ".codex/agents/sparkwright_coverage_auditor.toml").read_text()
            try:
                import tomllib
            except ImportError:  # Python 3.10
                tomllib = None
            if tomllib:
                d = tomllib.loads(agent)
                self.assertEqual(d["name"], "sparkwright_coverage_auditor")
                self.assertIn("Do not create, edit or delete", d["developer_instructions"])
            else:
                self.assertTrue(agent.startswith('name = "sparkwright_coverage_auditor"'))

    # sparkwright: S8.4
    def test_guard_reads_apply_patch_paths(self):
        with TempRepo() as r:
            git_init(r)
            out = hook("codex", r, {"tool_name": "apply_patch", "tool_input": {"command": PATCH}})
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
            ok = hook("codex", r, {"tool_name": "apply_patch", "tool_input": {"command": PATCH.split("*** Add File")[0]}})
            self.assertIsNone(ok)
            gated = hook("codex", r, {"tool_name": "Bash", "tool_input": {"command": ["bash", "-lc", "echo x > AGENTS.md"]}})
            self.assertEqual(gated["hookSpecificOutput"]["permissionDecision"], "deny")  # Codex has no "ask"
            self.assertIn("Ask the user", gated["hookSpecificOutput"]["permissionDecisionReason"])


class TestGeminiAdapter(unittest.TestCase):
    # sparkwright: S8.3
    def test_generate(self):
        with TempRepo() as r:
            gemini.generate(r / "ext")
            manifest = json.loads((r / "ext/gemini-extension.json").read_text())
            self.assertEqual(manifest["contextFileName"], "GEMINI.md")
            hooks = json.loads((r / "ext/hooks/hooks.json").read_text())
            self.assertIn("write_file", hooks["hooks"]["BeforeTool"][0]["matcher"])
            meta, body, _ = split((r / "ext/agents/sparkwright-newcomer.md").read_text())
            self.assertEqual(meta["name"], "sparkwright-newcomer")
            self.assertNotIn("write_file", meta["tools"])
            meta, _, _ = split((r / "ext/agents/sparkwright-builder.md").read_text())
            self.assertIn("write_file", meta["tools"])
            skill = (r / "ext/skills/sparkwright-build/SKILL.md").read_text()
            self.assertIn("@sparkwright-<data.persona>", skill)

    def test_guard(self):
        with TempRepo() as r:
            git_init(r)
            out = hook("gemini", r, {"tool_name": "write_file", "tool_input": {"file_path": str(r / "specs/events.jsonl")}})
            self.assertEqual(out["decision"], "deny")
            out = hook("gemini", r, {"tool_name": "run_shell_command", "tool_input": {"command": "sparkwright approve S1.1 --as me"}})
            self.assertEqual(out["decision"], "deny")
            self.assertIsNone(hook("gemini", r, {"tool_name": "replace", "tool_input": {"file_path": str(r / "src/x.py")}}))

    def test_cli(self):
        with TempRepo() as r:
            project(r)
            code, out = run_cli(r, "adapt", "gemini")
            self.assertEqual(code, 0, out)
            self.assertTrue((r / "adapters/gemini/gemini-extension.json").exists())
            code, out = run_cli(r, "adapt", "codex", "--out", "dist/codex")
            self.assertTrue((r / "dist/codex/.codex/hooks.json").exists())


if __name__ == "__main__":
    unittest.main()
