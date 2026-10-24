"""The host (Claude Code) build flow through the CLI and the guard, exactly as the sparkwright-build skill drives it."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from sparkwright.core import checks
from helpers import TempRepo, git, run_cli, write
from test_build import CODE, GOOD_TESTS, project


def guard(root: Path, payload: dict) -> str:
    out = subprocess.run([sys.executable, "-m", "sparkwright", "guard"], input=json.dumps(payload), capture_output=True,
                         text=True, env={"CLAUDE_PROJECT_DIR": str(root), "PYTHONPATH": os.environ.get("PYTHONPATH", "")})
    return json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"] if out.stdout.strip() else "allow"


class TestHostFlow(unittest.TestCase):
    # sparkwright: S8.4
    def test_skill_driven_build_end_to_end(self):
        with TempRepo() as r:
            project(r)
            code, out = run_cli(r, "build", "C1.1.1.T1", "--next")
            self.assertEqual(guard(r, {"tool_name": "Bash", "tool_input": {"command": "sparkwright build C1.1.1.T1 --next --json"}}), "allow")
            replies = {"test-author": '{"status": "ok"}', "builder": '{"status": "ok"}', "code-reviewer": "[]"}
            seen = []
            while out["data"]["kind"] == "agent":
                d = out["data"]
                seen.append(d["step"])
                ws = Path(d["workspace"])
                if d["step"] == "test-author":
                    target = ws / "tests/test_calc.py"
                    self.assertEqual(guard(r, {"tool_name": "Write", "tool_input": {"file_path": str(target)}}), "allow")
                    target.write_text(GOOD_TESTS)
                if d["step"] == "builder":
                    self.assertEqual(guard(r, {"tool_name": "Edit", "tool_input": {"file_path": str(ws / "calc.py")}}), "allow")
                    (ws / "calc.py").write_text(CODE)
                result = r / d["result_file"]
                self.assertEqual(guard(r, {"tool_name": "Write", "tool_input": {"file_path": str(result)}}), "allow")
                write(r, d["result_file"], replies[d["step"]])
                self.assertEqual(guard(r, {"tool_name": "Bash", "tool_input": {"command": d["then"] + " --json"}}), "allow")
                code, out = run_cli(r, "build", "C1.1.1.T1", "--done", d["step"], "--result", d["result_file"])
                self.assertEqual(code, 0, out)
            self.assertEqual(seen, ["test-author", "builder", "code-reviewer"])
            self.assertEqual(out["data"]["step"], "ready")
            git(r, "merge", "-q", "--no-ff", "-m", "merge", out["data"]["branch"])
            res = checks.run(r)
            self.assertEqual(res.nodes["C1.1.1.T1"].status, "done")
            self.assertTrue(res.ok, [f for f in res.findings if f.severity == "error"])


if __name__ == "__main__":
    unittest.main()
