"""D007: hardening from the R007 system review — protected files, signing, secret scrubbing,
review-finding decisions, stronger approval locks, append-only per commit, call cap."""
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from sparkwright.core import checks
from sparkwright.runner import verify
from sparkwright.runner.personas import load_all
from sparkwright.runner.router import BudgetExceeded, Router
from helpers import TempRepo, basic_repo, commit, git, git_init, run_cli, spec, write

CFG = "approvers:\n  - {name: Srikanth, email: t@example.com}\ntrailers: off\n"


def repo(r: Path, extra_cfg: str = "") -> None:
    basic_repo(r)
    write(r, ".sparkwright/config.yaml", CFG + extra_cfg)
    git_init(r)
    commit(r, "start")


def codes(r: Path) -> dict:
    res = checks.run(r)
    out = {}
    for f in res.findings:
        out.setdefault(f.code, []).append(f)
    return out


def as_other(r: Path, message: str, role: str | None = None) -> str:
    git(r, "add", "-A")
    body = message + (f"\n\nSparkWright-Role: {role}" if role else "")
    git(r, "-c", "user.email=intruder@example.com", "-c", "user.name=X", "commit", "-q", "-m", body)
    return git(r, "rev-parse", "HEAD")


class TestSecretScrub(unittest.TestCase):
    def test_secrets_removed_and_keep_env_respected(self):
        env = {"PATH": "/bin", "ANTHROPIC_API_KEY": "x", "GITHUB_TOKEN": "y", "MY_PASSWORD": "z",
               "AWS_REGION": "eu", "HOME": "/h", "DB_SECRET": "s"}
        out = verify.scrub(env, keep=["DB_SECRET"])
        self.assertEqual(out["PATH"], "/bin")
        self.assertEqual(out["HOME"], "/h")
        self.assertEqual(out["DB_SECRET"], "s")
        for k in ("ANTHROPIC_API_KEY", "GITHUB_TOKEN", "MY_PASSWORD", "AWS_REGION"):
            self.assertNotIn(k, out)

    def test_command_env_never_passes_parent_secrets(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "k", "SAFE_VAR": "1"}):
            out = verify.command_env({}, None, [])
        self.assertNotIn("OPENAI_API_KEY", out)
        self.assertEqual(out["SAFE_VAR"], "1")


class TestCallCap(unittest.TestCase):
    def test_unpriced_tier_stops_at_call_limit(self):
        persona = next(iter(load_all().values()))
        router = Router({"roles": {}, "budgets": {"max_calls_per_run": 3}, "models": {"fast": {}, "mid": {}, "top": {}}})
        router.calls = 3
        with self.assertRaises(BudgetExceeded):
            router.call(persona, "hi")


class TestStrongerLock(unittest.TestCase):
    def test_changing_parent_links_after_approval_needs_a_change_request(self):
        with TempRepo() as r:
            repo(r)
            write(r, "specs/vision.md", spec("VISION", "vision",
                  "- **V1** [E1] When asked, the system shall trace.\n- **V2** [E1] It shall log.\n"))
            commit(r, "v2")
            code, out = run_cli(r, "approve", "SYSTEM", "--as", "Srikanth")
            self.assertEqual(code, 0, out)
            p = r / "specs/system.md"
            p.write_text(p.read_text().replace("[V1]", "[V2]"))
            found = codes(r)
            self.assertIn("approval.hash-mismatch", found)
            self.assertIn("parent links", found["approval.hash-mismatch"][0].message)

    def test_acceptance_criteria_are_locked_for_task_files(self):
        with TempRepo() as r:
            repo(r)
            write(r, "specs/tasks/T.md", "---\nid: C9.1.1.T1\ntitle: t\ntype: task\nstatus: draft\nrisk: low\n---\n\n"
                  "- **C9.1.1.T1** [S1.1] Do it.\n\n## Acceptance criteria\n\n- returns 1\n")
            commit(r, "task")
            from sparkwright.core import store
            req = store.load(r).requirements["C9.1.1.T1"]
            self.assertEqual(req.criteria, "- returns 1")
            before = req.hash2
            (r / "specs/tasks/T.md").write_text((r / "specs/tasks/T.md").read_text().replace("returns 1", "returns 2"))
            after = store.load(r).requirements["C9.1.1.T1"]
            self.assertEqual(req.hash, after.hash)
            self.assertNotEqual(before, after.hash2)

    def test_legacy_approval_is_refreshed_without_change_request(self):
        with TempRepo() as r:
            repo(r)
            run_cli(r, "approve", "SYSTEM", "--as", "Srikanth")
            p = r / "specs/approvals.jsonl"
            lines = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
            for d in lines:
                d.pop("hash2", None)
            p.write_text("".join(json.dumps(d, sort_keys=True) + "\n" for d in lines))
            commit(r, "legacy approvals")
            self.assertIn("approval.legacy-lock", codes(r))
            code, out = run_cli(r, "approve", "S1.1", "--as", "Srikanth")
            self.assertEqual(code, 0, out)
            last = json.loads(p.read_text().splitlines()[-1])
            self.assertEqual(last["id"], "S1.1")
            self.assertIn("hash2", last)


class TestLegacyRefreshNeedsUnchangedLinks(unittest.TestCase):
    def test_refresh_is_refused_when_links_changed_since_approval(self):
        with TempRepo() as r:
            repo(r)
            write(r, "specs/vision.md", spec("VISION", "vision",
                  "- **V1** [E1] When asked, the system shall trace.\n- **V2** [E1] It shall log.\n"))
            commit(r, "v2")
            run_cli(r, "approve", "SYSTEM", "--as", "Srikanth")
            p = r / "specs/approvals.jsonl"
            rows = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
            for d in rows:
                d.pop("hash2", None)
            p.write_text("".join(json.dumps(d, sort_keys=True) + "\n" for d in rows))
            commit(r, "legacy approvals")
            s = r / "specs/system.md"
            s.write_text(s.read_text().replace("[V1]", "[V2]"))
            code, out = run_cli(r, "approve", "S1.1", "--as", "Srikanth")
            self.assertNotEqual(code, 0)
            self.assertEqual(out["data"].get("needs_change_request"), ["S1.1"])


class TestProtectedFiles(unittest.TestCase):
    def test_only_an_approver_may_change_protected_files(self):
        with TempRepo() as r:
            repo(r)
            write(r, "AGENTS.md", "# rules\n")
            commit(r, "approver adds rules")
            self.assertNotIn("protected.non-approver", codes(r))
            write(r, "AGENTS.md", "# rules, loosened\n")
            as_other(r, "edit rules")
            self.assertIn("protected.non-approver", codes(r))


class TestReviewFiles(unittest.TestCase):
    ROW = "| F1 | high | S1.1 | Bad. | Fix. | devils-advocate | {d} |\n"
    HEAD = "| ID | Severity | Requirements | Finding | Suggested fix | Raised by | Decision |\n|---|---|---|---|---|---|---|\n"

    def test_runner_may_add_but_not_edit_reviews(self):
        with TempRepo() as r:
            repo(r)
            write(r, "specs/reviews/r1.md", self.HEAD + self.ROW.format(d="open"))
            commit(r, "add review\n\nspecs/reviews/r1.md\n\nSparkWright-Role: runner")
            self.assertNotIn("role.review-edit", codes(r))
            write(r, "specs/reviews/r1.md", self.HEAD + self.ROW.format(d="rejected"))
            commit(r, "edit review\n\nspecs/reviews/r1.md\n\nSparkWright-Role: runner")
            found = codes(r)
            self.assertIn("role.review-edit", found)
            self.assertIn("review.decision-not-allowed", found)

    def test_only_an_approver_closes_a_high_finding(self):
        with TempRepo() as r:
            repo(r)
            write(r, "specs/reviews/r1.md", self.HEAD + self.ROW.format(d="open"))
            commit(r, "review")
            write(r, "specs/reviews/r1.md", self.HEAD + self.ROW.format(d="deferred"))
            as_other(r, "close it")
            self.assertIn("review.decision-not-allowed", codes(r))

    def test_approver_may_close_a_high_finding(self):
        with TempRepo() as r:
            repo(r)
            write(r, "specs/reviews/r1.md", self.HEAD + self.ROW.format(d="open"))
            commit(r, "review")
            write(r, "specs/reviews/r1.md", self.HEAD + self.ROW.format(d="deferred"))
            commit(r, "decide")
            self.assertNotIn("review.decision-not-allowed", codes(r))


class TestAppendOnlyPerCommit(unittest.TestCase):
    def test_a_commit_that_rewrites_a_log_line_is_caught(self):
        with TempRepo() as r:
            repo(r)
            write(r, "specs/events.jsonl", '{"id": "S1.1", "event": "changed", "time": "2026-01-01T00:00:00Z"}\n')
            commit(r, "event")
            write(r, "specs/events.jsonl", '{"id": "S1.1", "event": "edited", "time": "2026-01-01T00:00:00Z"}\n')
            commit(r, "rewrite")
            self.assertIn("log.not-append-only", codes(r))


class TestSigning(unittest.TestCase):
    def test_unsigned_high_risk_approval_warns_until_signing_is_switched_on(self):
        with TempRepo() as r:
            repo(r)
            p = r / "specs/system.md"
            p.write_text(p.read_text().replace("risk: low", "risk: high"))
            commit(r, "high")
            code, out = run_cli(r, "approve", "SYSTEM", "--as", "Srikanth")
            self.assertEqual(code, 0, out)
            commit(r, "approve")
            found = codes(r)
            self.assertIn("approval.unsigned-unenforced", found)
            self.assertNotIn("approval.unsigned", found)
            start = git(r, "rev-list", "--max-parents=0", "HEAD")
            write(r, ".sparkwright/config.yaml", CFG + f"signing_from: {start}\n")
            commit(r, "turn on signing")
            self.assertIn("approval.unsigned", codes(r))

    def test_signing_off_is_silent(self):
        with TempRepo() as r:
            repo(r, "require_signed: false\n")
            p = r / "specs/system.md"
            p.write_text(p.read_text().replace("risk: low", "risk: high"))
            commit(r, "high")
            run_cli(r, "approve", "SYSTEM", "--as", "Srikanth")
            commit(r, "approve")
            found = codes(r)
            self.assertNotIn("approval.unsigned-unenforced", found)
            self.assertNotIn("approval.unsigned", found)


class TestBypasses(unittest.TestCase):
    """Bypasses found by the independent review of D007."""
    HEAD = TestReviewFiles.HEAD
    ROW = TestReviewFiles.ROW

    def _open_review(self, r):
        repo(r)
        write(r, "specs/reviews/r1.md", self.HEAD + self.ROW.format(d="open"))
        commit(r, "review")

    def test_renaming_the_finding_id_counts_as_closing(self):
        with TempRepo() as r:
            self._open_review(r)
            write(r, "specs/reviews/r1.md", self.HEAD + self.ROW.format(d="rejected").replace("F1", "F9"))
            as_other(r, "rename")
            self.assertIn("review.decision-not-allowed", codes(r))

    def test_removing_a_row_then_readding_it_closed_is_caught(self):
        with TempRepo() as r:
            self._open_review(r)
            write(r, "specs/reviews/r1.md", self.HEAD)
            as_other(r, "drop")
            self.assertIn("review.decision-not-allowed", codes(r))

    def test_deleting_or_renaming_the_review_file_is_caught(self):
        with TempRepo() as r:
            self._open_review(r)
            git(r, "mv", "specs/reviews/r1.md", "specs/reviews/r2.md")
            write(r, "specs/reviews/r2.md", self.HEAD + self.ROW.format(d="deferred"))
            as_other(r, "move")
            self.assertIn("review.decision-not-allowed", codes(r))

    def test_runner_cannot_add_a_high_finding_already_closed(self):
        with TempRepo() as r:
            repo(r)
            write(r, "specs/reviews/r1.md", self.HEAD + self.ROW.format(d="rejected"))
            commit(r, "add review\n\nspecs/reviews/r1.md\n\nSparkWright-Role: runner")
            self.assertIn("review.decision-not-allowed", codes(r))

    def test_role_trailer_case_does_not_escape(self):
        with TempRepo() as r:
            self._open_review(r)
            write(r, "specs/reviews/r1.md", self.HEAD + self.ROW.format(d="rejected"))
            commit(r, "close\n\nSparkWright-Role: Builder")
            self.assertIn("review.decision-not-allowed", codes(r))

    def test_closing_inside_a_merge_resolution_is_caught(self):
        with TempRepo() as r:
            self._open_review(r)
            base = git(r, "rev-parse", "--abbrev-ref", "HEAD")
            git(r, "checkout", "-q", "-b", "side")
            write(r, "notes.txt", "x\n")
            commit(r, "side work")
            git(r, "checkout", "-q", base)
            write(r, "other.txt", "y\n")
            commit(r, "main work")
            git(r, "merge", "-q", "--no-ff", "--no-commit", "side")
            write(r, "specs/reviews/r1.md", self.HEAD + self.ROW.format(d="rejected"))
            git(r, "add", "-A")
            git(r, "-c", "user.email=intruder@example.com", "commit", "-q", "-m", "merge side")
            self.assertIn("review.decision-not-allowed", codes(r))

    def test_log_without_final_newline_and_union_merges_are_append_only(self):
        with TempRepo() as r:
            repo(r)
            ev = r / "specs/events.jsonl"
            ev.write_text('{"id": "S1.1", "event": "changed", "time": "2026-01-01T00:00:00Z"}')
            commit(r, "no newline")
            ev.write_text(ev.read_text() + '\n{"id": "S1.1", "event": "changed", "time": "2026-01-02T00:00:00Z"}\n')
            commit(r, "append")
            base = git(r, "rev-parse", "--abbrev-ref", "HEAD")
            git(r, "checkout", "-q", "-b", "side")
            ev.write_text(ev.read_text() + '{"id": "S1.1", "event": "changed", "time": "2026-01-03T00:00:00Z"}\n')
            commit(r, "side append")
            git(r, "checkout", "-q", base)
            ev.write_text(ev.read_text() + '{"id": "S1.1", "event": "changed", "time": "2026-01-04T00:00:00Z"}\n')
            commit(r, "main append")
            (r / ".gitattributes").write_text("specs/*.jsonl merge=union\n")
            commit(r, "attrs")
            git(r, "merge", "-q", "--no-edit", "side")
            self.assertNotIn("log.not-append-only", codes(r))

    def test_waived_log_commit_passes(self):
        with TempRepo() as r:
            repo(r)
            write(r, "specs/events.jsonl", '{"id": "S1.1", "event": "changed", "time": "2026-01-01T00:00:00Z"}\n')
            commit(r, "event")
            write(r, "specs/events.jsonl", "")
            bad = commit(r, "revert")
            self.assertIn("log.not-append-only", codes(r))
            write(r, ".sparkwright/config.yaml", CFG + f"log_waivers: [{bad}]\n")
            commit(r, "waive")
            self.assertNotIn("log.not-append-only", codes(r))

    def test_approval_line_without_risk_still_needs_signature_for_high_risk_item(self):
        with TempRepo() as r:
            repo(r)
            p = r / "specs/system.md"
            p.write_text(p.read_text().replace("risk: low", "risk: high"))
            commit(r, "high")
            run_cli(r, "approve", "SYSTEM", "--as", "Srikanth")
            a = r / "specs/approvals.jsonl"
            rows = [json.loads(x) for x in a.read_text().splitlines() if x.strip()]
            for d in rows:
                d.pop("risk", None)
            a.write_text("".join(json.dumps(d) + "\n" for d in rows))
            commit(r, "approve")
            self.assertIn("approval.unsigned-unenforced", codes(r))

    def test_bad_signing_from_is_reported_once(self):
        with TempRepo() as r:
            repo(r, "signing_from: deadbeefdeadbeef\n")
            found = codes(r)
            self.assertEqual(len(found.get("config.signing-from", [])), 1)

    def test_scrub_keeps_harmless_lookalikes(self):
        env = {"GIT_AUTHOR_NAME": "a", "TOKENIZERS_PARALLELISM": "false", "HF_HOME": "/h", "AUTHOR": "b",
               "DATABASE_URL": "pg://", "SSH_AUTH_SOCK": "/s", "SLACK_WEBHOOK_URL": "u", "GH_PAT": "p", "db_secret": "x"}
        out = verify.scrub(env, keep=["DB_SECRET"])
        for k in ("GIT_AUTHOR_NAME", "TOKENIZERS_PARALLELISM", "HF_HOME", "AUTHOR", "db_secret"):
            self.assertIn(k, out)
        for k in ("DATABASE_URL", "SSH_AUTH_SOCK", "SLACK_WEBHOOK_URL", "GH_PAT"):
            self.assertNotIn(k, out)

    def test_zero_price_counts_as_unpriced(self):
        router = Router({"models": {"mid": {"price_per_mtok": {"input": 0, "output": 0}}}})
        self.assertFalse(router._priced("mid"))

    def test_acceptance_heading_variants_are_locked(self):
        with TempRepo() as r:
            repo(r)
            write(r, "specs/tasks/T.md", "---\nid: C9.1.1.T1\ntitle: t\ntype: task\nstatus: draft\nrisk: low\n---\n\n"
                  "- **C9.1.1.T1** [S1.1] Do it.\n\n### Acceptance Criteria\n\n- returns 1\n\n## Notes\n\nx\n")
            from sparkwright.core import store
            self.assertEqual(store.load(r).requirements["C9.1.1.T1"].criteria, "- returns 1")


if __name__ == "__main__":
    unittest.main()
