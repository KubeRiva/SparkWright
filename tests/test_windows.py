"""Cross-platform behaviour needed on Windows hosts."""
import sys
import unittest
from unittest import mock

from sparkwright.runner import verify
from helpers import TempRepo, write


class TestCommandSplitting(unittest.TestCase):
    def test_windows_keeps_backslashes_and_drops_quotes(self):
        with mock.patch.object(verify.os, "name", "nt"):
            parts = verify.split_cmd(r'"C:\Program Files\Python\python.exe" -m pytest -q tests\unit')
        self.assertEqual(parts, [r"C:\Program Files\Python\python.exe", "-m", "pytest", "-q", r"tests\unit"])

    def test_posix_split(self):
        with mock.patch.object(verify.os, "name", "posix"):
            self.assertEqual(verify.split_cmd("uv run pytest -q 'a b'"), ["uv", "run", "pytest", "-q", "a b"])


class TestCommandEnv(unittest.TestCase):
    def test_repo_placeholder_and_utf8(self):
        with TempRepo() as r:
            env = verify.command_env({"UV_PROJECT_ENVIRONMENT": "{repo}/.venv-sparkwright"}, r)
            self.assertEqual(env["UV_PROJECT_ENVIRONMENT"], f"{r.resolve()}/.venv-sparkwright")
            self.assertEqual(env["PYTHONIOENCODING"], "utf-8")

    def test_checks_receive_env_and_survive_non_ascii_output(self):
        with TempRepo() as r:
            cmd = f'{sys.executable} -c "import os; print(os.environ[\'SW_PROBE\'] + \' \\u2713 caf\\u00e9\')"'
            res = verify.run_checks(r, {"probe": cmd}, env=verify.command_env({"SW_PROBE": "ok"}, r))[0]
            self.assertTrue(res.ok, res.output)
            self.assertIn("ok", res.output)


if __name__ == "__main__":
    unittest.main()
