"""Tests for SYSTEM v0.3 core changes (decisions D002-D004)."""
import json
import unittest

from sparkwright.core import checks, events, ids
from sparkwright.core.store import load
from helpers import TempRepo, basic_repo, commit, git, git_init, run_cli, spec, write

codes = lambda res, sev="error": {f.code for f in res.findings if f.severity == sev}


def approver_repo(r, email="t@example.com"):
    basic_repo(r)
    git_init(r)
    base = commit(r, "start")
    write(r, ".sparkwright/config.yaml", f"baseline: {base}\ntrailers: off\napprovers:\n  - {{name: Srikanth, email: {email}}}\n")
    return base


class TestIds(unittest.TestCase):
    # sparkwright: S1.2
    def test_leading_zeros_are_not_significant(self):
        self.assertEqual(ids.canonical("E01"), "E1")
        self.assertEqual(ids.canonical("C02.3.01.T04"), "C2.3.1.T4")
        with TempRepo() as r:
            basic_repo(r)
            write(r, "specs/vision.md", spec("VISION", "vision", "- **V01** [E001] padded\n"))
            write(r, "specs/system.md", spec("SYSTEM", "system", "- **S1.1** [V1] x\n- **S01.01** [V1] dup\n"))
            res = checks.run(r)
            self.assertIn("grammar.duplicate-id", codes(res))
            self.assertIn("V1", res.nodes["S1.1"].refs)

    def test_task_extras_are_part_of_the_hash(self):
        with TempRepo() as r:
            basic_repo(r)
            write(r, "specs/components/C1.md", spec("C1", "component", "- **C1.1.1** [S1.1] c\n"))
            task = "- **C1.1.1.T1** [C1.1.1] t\n\n```yaml\nfiles: [\"src/a/**\"]\n```\n"
            write(r, "specs/tasks/T.md", spec("C1.1.1.T1", "task", task))
            run_cli(r, "approve", "C1.1.1.T1", "--as", "Srikanth")
            write(r, "specs/tasks/T.md", spec("C1.1.1.T1", "task", task.replace("src/a/**", "src/**")))
            self.assertIn("approval.hash-mismatch", codes(checks.run(r)))


class TestDerivedStatus(unittest.TestCase):
    # sparkwright: S2.8
    def test_status_comes_from_approvals_and_events(self):
        with TempRepo() as r:
            basic_repo(r)
            write(r, "specs/system.md", spec("SYSTEM", "system", "- **S1.1** [V1] a\n- **S1.2** [V1] b\n", status="in-review"))
            run_cli(r, "approve", "S1.1", "--as", "Srikanth")
            res = checks.run(r)
            self.assertEqual(res.nodes["S1.1"].status, "approved")
            self.assertEqual(res.nodes["S1.2"].status, "in-review")
            events.append(r, [events.make("S1.1", "changed", reason="CR1")])
            self.assertEqual(checks.run(r).nodes["S1.1"].status, "changed")


class TestApproverVerification(unittest.TestCase):
    # sparkwright: S6.3
    def test_allowlisted_author_passes_and_others_fail(self):
        with TempRepo() as r:
            approver_repo(r)
            run_cli(r, "approve", "S1.1", "--as", "Srikanth")
            self.assertIn("approval.pending", codes(checks.run(r), "warning"))
            commit(r, "approve")
            self.assertTrue(checks.run(r).ok, [f for f in checks.run(r).findings if f.severity == "error"])
        with TempRepo() as r:
            approver_repo(r, email="someone-else@example.com")
            run_cli(r, "approve", "S1.1", "--as", "Srikanth")
            commit(r, "forged approval")
            self.assertIn("approval.unverified-approver", codes(checks.run(r)))

    def test_name_must_match_committer(self):
        with TempRepo() as r:
            approver_repo(r)
            run_cli(r, "approve", "S1.1", "--as", "Somebody Else")
            commit(r, "approve")
            self.assertIn("approval.unverified-approver", codes(checks.run(r)))

    # sparkwright: S6.9
    def test_logs_are_append_only(self):
        with TempRepo() as r:
            approver_repo(r)
            run_cli(r, "approve", "S1.1", "--as", "Srikanth")
            commit(r, "approve")
            (r / "specs/approvals.jsonl").write_text("")
            self.assertIn("log.not-append-only", codes(checks.run(r)))

    def test_init_lists_git_user_as_approver(self):
        with TempRepo() as r:
            git_init(r)
            write(r, "README.md", "x")
            commit(r, "start")
            run_cli(r, "init")
            cfg = (r / ".sparkwright/config.yaml").read_text()
            self.assertIn("t@example.com", cfg)
            self.assertIn("baseline: ", cfg)


class TestRenames(unittest.TestCase):
    # sparkwright: S2.9
    def test_approved_rename_maps_old_ids(self):
        with TempRepo() as r:
            basic_repo(r)
            write(r, "specs/components/C1.md", spec("C1", "component", "- **C1.1.1** [S1.1] c\n- **C1.2.1** [S1.1] moved here\n"))
            write(r, "specs/tasks/T.md", spec("C1.2.1.T1", "task", "- **C1.2.1.T1** [C1.2.1] t\n"))
            write(r, "tests/test_t.py", "# sparkwright: C1.1.1.T1\n")
            write(r, "specs/changes/CR1.md", "---\nid: CR1\ntitle: move\ntype: change\nstatus: approved\nrenames: {C1.1.1.T1: C1.2.1.T1}\n---\n")
            res = checks.run(r)
            self.assertEqual(res.nodes["C1.2.1.T1"].tests, ["tests/test_t.py"])


class TestSpecOnlyCommits(unittest.TestCase):
    # sparkwright: S2.3
    def test_spec_only_commits_need_no_task_trailer(self):
        with TempRepo() as r:
            approver_repo(r)
            commit(r, "config")
            write(r, "specs/system.md", spec("SYSTEM", "system", "- **S1.1** [V1] The parser shall parse.\n- **S1.2** [V1] more\n"))
            commit(r, "spec change")
            write(r, ".sparkwright/config.yaml", (r / ".sparkwright/config.yaml").read_text().replace("trailers: off", "trailers: required"))
            commit(r, "require trailers")
            self.assertNotIn("commit.no-trailer", codes(checks.run(r)))
            write(r, "src/x.py", "x = 1\n")
            commit(r, "code without trailer")
            self.assertIn("commit.no-trailer", codes(checks.run(r)))


class TestCommitMessages(unittest.TestCase):
    # sparkwright: S9.2
    def test_agent_commits_must_list_changed_files(self):
        with TempRepo() as r:
            approver_repo(r)
            commit(r, "config")
            write(r, "src/a.py", "x = 1\n")
            commit(r, "build\n\nFiles:\n- src/a.py\n\nSparkWright-Role: builder")
            self.assertNotIn("commit.unlisted-file", codes(checks.run(r)))
            write(r, "src/b.py", "y = 1\n")
            commit(r, "sneaky\n\nSparkWright-Role: builder")
            self.assertIn("commit.unlisted-file", codes(checks.run(r)))


if __name__ == "__main__":
    unittest.main()
