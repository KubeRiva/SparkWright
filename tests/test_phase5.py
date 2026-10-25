"""Phase 5: re-review after change requests (S3.10), parallel builds (S3.8), interview guide (S7.2, S7.7),
adopt (S2.7), calibration (S10), Prover hook (S5.6)."""
import unittest
from pathlib import Path

import json
import threading

from sparkwright.core import checks
from sparkwright.runner import parallel, review
from sparkwright.runner.build import Build, BuildError
from sparkwright.runner.providers import FakeProvider
from sparkwright.runner.router import Router
from helpers import TempRepo, commit, git, git_init, run_cli, spec, write
from test_build import CODE, GOOD_TESTS, PY, project, ws

DOUBLE_TESTS = ("# sparkwright: C1.1.1.T2\nimport unittest\nfrom other import double\n\n"
                "class D(unittest.TestCase):\n    def test_double(self):\n        self.assertEqual(double(2), 4)\n"
                "        self.assertEqual(double(-3), -6)\n        self.assertEqual(double(0), 0)\n")
DOUBLE = "def double(x):\n    return x * 2\n"


def multi_project(r: Path) -> None:
    write(r, "specs/evidence/E1.md", "---\nid: E1\ntitle: t\ntype: evidence\nstatus: draft\n---\nNeeds.\n")
    write(r, "specs/vision.md", spec("VISION", "vision", "- **V1** [E1] Values stay in range.\n"))
    write(r, "specs/system.md", spec("SYSTEM", "system", "- **S1.1** [V1] The library shall do maths.\n"))
    write(r, "specs/components/C1.md", spec("C1", "component",
          "- **C1.1.1** [S1.1] clamp and double.\n\n## Tasks\n\n"
          "- **C1.1.1.T1** [C1.1.1] Implement clamp in calc.py.\n\n```yaml\nfiles: [\"calc.py\"]\n```\n\n"
          "- **C1.1.1.T2** [C1.1.1] Implement double in other.py.\n\n```yaml\nfiles: [\"other.py\"]\n```\n\n"
          "- **C1.1.1.T3** [C1.1.1] Tidy every module.\n\n```yaml\nfiles: [\"*.py\"]\n```\n"))
    write(r, "calc.py", "")
    write(r, "other.py", "")
    write(r, "tests/__init__.py", "")
    write(r, ".sparkwright/config.yaml",
          f"checks:\n  test: \"{PY} -m unittest discover -s tests -t .\"\ntrailers: warn\n"
          "approvers:\n  - {name: Srikanth, email: t@example.com}\nmutation: {min: 0.5, time_budget_s: 120}\n"
          "test_globs: [\"tests/*\"]\n")
    write(r, ".gitignore", ".sparkwright/ledger.json\n.sparkwright/runs/\n.sparkwright/worktrees/\n__pycache__/\n")
    git_init(r)
    commit(r, "start")
    for t in ("C1.1.1.T1", "C1.1.1.T2", "C1.1.1.T3"):
        run_cli(r, "approve", t, "--as", "Srikanth")
    commit(r, "approve tasks")


def host_review(r: Path, target: str) -> review.ReviewResult:
    prep = review.prepare(r, target)
    for name in prep.personas:
        (prep.run_dir / f"{name}.json").write_text("[]")
    return review.collect(r, prep.run_id, {"gates": {}})


class TestReReviewAfterChange(unittest.TestCase):
    # sparkwright: S3.10
    def test_applied_cr_puts_target_in_review_and_requires_review_before_reapproval(self):
        with TempRepo() as r:
            project(r)
            run_cli(r, "approve", "SYSTEM", "--as", "Srikanth")
            run_cli(r, "approve", "C1", "--as", "Srikanth")
            run_cli(r, "change", "new", "C1.1.1", "--reason", "define lo > hi")
            run_cli(r, "approve", "CR1", "--as", "Srikanth")
            code, out = run_cli(r, "change", "apply", "CR1")
            self.assertEqual(code, 0, out)
            nodes = checks.run(r).nodes
            self.assertEqual(nodes["C1.1.1"].status, "in-review")
            self.assertEqual(nodes["C1.1.1.T1"].status, "changed")
            p = r / "specs/components/C1.md"
            p.write_text(p.read_text().replace("limited to [lo, hi].", "limited to [lo, hi]; lo > hi raises ValueError."))
            code, out = run_cli(r, "approve", "C1.1.1", "--as", "Srikanth", "--cr", "CR1")
            self.assertEqual(code, 1)
            self.assertEqual(out["data"]["needs_review"], ["C1.1.1"])
            res = host_review(r, "C1")
            self.assertFalse(res.gate.startswith("FAIL"), res.gate)
            # editing after the review voids it: the review must have seen this exact text
            p.write_text(p.read_text().replace("raises ValueError.", "raises ValueError naming lo."))
            self.assertEqual(run_cli(r, "approve", "C1.1.1", "--as", "Srikanth", "--cr", "CR1")[0], 1)
            host_review(r, "C1")
            code, out = run_cli(r, "approve", "C1.1.1", "--as", "Srikanth", "--cr", "CR1")
            self.assertEqual(code, 0, out)
            self.assertEqual(checks.run(r).nodes["C1.1.1"].status, "approved")

    def test_failed_review_does_not_count(self):
        with TempRepo() as r:
            project(r)
            prep = review.prepare(r, "C1")
            (prep.run_dir / f"{prep.personas[0]}.json").write_text("[]")  # only one Inspector: FAIL
            res = review.collect(r, prep.run_id, {"gates": {}})
            self.assertTrue(res.gate.startswith("FAIL"))
            self.assertNotIn('"reviewed"', (r / "specs/events.jsonl").read_text() if (r / "specs/events.jsonl").exists() else "")


class TestParallelBuilds(unittest.TestCase):
    # sparkwright: S3.8
    def test_glob_overlap_is_conservative(self):
        self.assertFalse(parallel.globs_may_intersect(["calc.py"], ["other.py"]))
        self.assertTrue(parallel.globs_may_intersect(["calc.py"], ["*.py"]))
        self.assertTrue(parallel.globs_may_intersect(["src/a/**"], ["src/**"]))
        self.assertTrue(parallel.globs_may_intersect(["src/a/x.py"], ["src/a/*"]))
        self.assertFalse(parallel.globs_may_intersect(["src/a/**"], ["src/b/**"]))

    def test_plan_batches(self):
        with TempRepo() as r:
            multi_project(r)
            self.assertEqual(parallel.plan_batches(r, ["C1.1.1.T1", "C1.1.1.T2", "C1.1.1.T3"]),
                             [["C1.1.1.T1", "C1.1.1.T2"], ["C1.1.1.T3"]])
            code, out = run_cli(r, "build", "C1.1.1.T1", "C1.1.1.T2", "C1.1.1.T3", "--plan")
            self.assertEqual(code, 0)
            self.assertEqual(len(out["data"]["batches"]), 2)

    def test_overlapping_build_refused_while_another_runs(self):
        with TempRepo() as r:
            multi_project(r)
            Build(r, "C1.1.1.T1").advance()
            with self.assertRaises(BuildError) as ctx:
                Build(r, "C1.1.1.T3").advance()
            self.assertIn("C1.1.1.T1", str(ctx.exception))
            self.assertEqual(Build(r, "C1.1.1.T2").advance()["step"], "test-author")  # disjoint files: allowed
            for t in ("C1.1.1.T1", "C1.1.1.T2"):
                code, out = run_cli(r, "build", t, "--abandon")
                self.assertEqual(out["data"]["step"], "blocked")
            self.assertEqual(Build(r, "C1.1.1.T3").advance()["step"], "test-author")

    def test_two_disjoint_tasks_build_concurrently(self):
        with TempRepo() as r:
            multi_project(r)
            # FakeProvider hands out scripted replies in call order, so give each task its own provider
            fakes = {"C1.1.1.T1": FakeProvider(script={
                        "test-author": [json.dumps({"files": {"tests/test_calc.py": GOOD_TESTS}, "status": "ok"})],
                        "builder": [json.dumps({"files": {"calc.py": CODE}, "status": "ok"})], "code-reviewer": ["[]"]}),
                     "C1.1.1.T2": FakeProvider(script={
                        "test-author": [json.dumps({"files": {"tests/test_other.py": DOUBLE_TESTS}, "status": "ok"})],
                        "builder": [json.dumps({"files": {"other.py": DOUBLE}, "status": "ok"})], "code-reviewer": ["[]"]})}
            results = {}

            def go(task):
                f = fakes[task]
                router = Router({"roles": {}, "budgets": {}, "models": {}}, {"fast": f, "mid": f, "top": f})
                results[task] = Build(r, task).run(router)

            threads = [threading.Thread(target=go, args=(t,)) for t in fakes]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual({k: v["step"] for k, v in results.items()},
                             {"C1.1.1.T1": "ready", "C1.1.1.T2": "ready"}, results)

    def test_finish_stops_when_main_changed_the_same_file(self):
        with TempRepo() as r:
            multi_project(r)
            b = Build(r, "C1.1.1.T1")
            b.advance()
            write(r, "calc.py", "# edited on main\n")
            commit(r, "someone edits calc.py on main")
            write(ws(b), "tests/test_calc.py", GOOD_TESTS)
            b.submit("test-author", '{"status": "ok"}')
            write(ws(b), "calc.py", CODE)
            b.submit("builder", '{"status": "ok"}')
            ins = b.submit("code-reviewer", "[]")
            self.assertEqual(ins["step"], "blocked", ins)
            self.assertIn("main branch changed", ins["reason"])


GOOD_GUIDE = """## Goal
Learn how parents help children practise chess (tests A1).

## Who to recruit
Parents of children who play chess weekly.

## Consent script
Ask permission to take anonymized notes.

## Warm-up
1. Tell me about your week.

## Core questions
1. Tell me about the last time your child got stuck on a chess puzzle.
   _What happened next?_
2. Walk me through how practice went last weekend.

## Wrap-up
Who else should we talk to?
"""
BAD_GUIDE = GOOD_GUIDE.replace("2. Walk me through how practice went last weekend.",
                               "2. Would you use our app if it gave hints? Don't you think hints help?")


class TestInterviewGuide(unittest.TestCase):
    # sparkwright: S7.2
    def test_host_flow_writes_guide_and_reviews_it(self):
        from sparkwright.runner import guide
        with TempRepo() as r:
            project(r)
            code, out = run_cli(r, "interview", "guide", "--about", "adult club players improving tactics", "--prepare")
            self.assertEqual(code, 0, out)
            d = out["data"]
            self.assertFalse(d["minors"])
            self.assertIn("persona: guide-writer", (r / d["prompt"]).read_text())
            (r / d["result_file"]).write_text(GOOD_GUIDE)
            code, out = run_cli(r, "interview", "guide", d["run_id"])
            self.assertEqual(out["data"]["step"], "question-auditor", out)
            (r / out["data"]["result_file"]).write_text("[]")
            code, out = run_cli(r, "interview", "guide", d["run_id"])
            self.assertEqual(code, 0, out)
            text = (r / out["data"]["guide"]).read_text()
            self.assertIn("type: guide", text)
            self.assertIn("Gate: PASS", text)
            self.assertNotIn("Participants under 18", text)
            self.assertTrue(checks.run(r).ok)
            self.assertEqual(guide.lint(GOOD_GUIDE), [])

    def test_leading_questions_fail_the_gate(self):
        from sparkwright.runner import guide
        with TempRepo() as r:
            project(r)
            prep = guide.prepare(r, "adult club players")
            guide.advance(r, prep["run_id"], writer_reply=BAD_GUIDE)
            out = guide.advance(r, prep["run_id"], auditor_reply="[]")
            self.assertGreaterEqual(out["high"], 1)
            self.assertTrue(out["gate"].startswith("FAIL"))

    # sparkwright: S7.7
    def test_minors_get_parental_consent_section(self):
        from sparkwright.runner import guide
        with TempRepo() as r:
            project(r)
            prep = guide.prepare(r, "kids aged 8-12 learning chess")
            self.assertTrue(prep["minors"])
            guide.advance(r, prep["run_id"], writer_reply=GOOD_GUIDE.replace("Parents of children", "Children"))
            out = guide.advance(r, prep["run_id"], auditor_reply="[]")
            text = (r / out["guide"]).read_text()
            self.assertIn("## Participants under 18 (required)", text)
            self.assertIn("minors: true", text)

    def test_runner_mode(self):
        from sparkwright.runner import guide
        with TempRepo() as r:
            project(r)
            fake = FakeProvider(script={"guide-writer": [GOOD_GUIDE], "question-auditor": ["[]"]})
            router = Router({"roles": {}, "budgets": {}, "models": {}}, {"fast": fake, "mid": fake, "top": fake})
            out = guide.run(r, "adult club players", router)
            self.assertEqual(out["high"], 0)
            self.assertEqual([c[0] for c in fake.calls], ["guide-writer", "question-auditor"])


CART = ('''"""Shopping cart."""


class Cart:
    """Holds line items."""

    def add(self, sku, qty):
        """Add qty of sku."""

    def total(self):
        """Sum of line prices."""
''')
SURVEY = {
    "purpose": "Let shoppers collect items and see a total.",
    "system": [{"title": "Cart", "requirements": ["When a shopper adds items, the system shall keep them in a cart.",
                                                  "When asked, the system shall report the cart total."]}],
    "components": [{"title": "Cart module", "responsibility": "Line items and totals.",
                    "requirements": [
                        {"system": [1, 1], "text": "When add(sku, qty) is called, the cart shall record the line.",
                         "files": ["shop/cart.py"]},
                        {"system": [1, 2], "text": "When total() is called, the cart shall return the sum.",
                         "files": ["shop/cart.py", "nowhere/**"]},
                        {"system": [9, 9], "text": "Invented.", "files": ["shop/cart.py"]}]}],
}


def code_repo(r: Path) -> None:
    write(r, "shop/__init__.py", "")
    write(r, "shop/cart.py", CART)
    write(r, "tests/test_cart.py", "import unittest\n")
    git_init(r)
    commit(r, "existing code")
    run_cli(r, "init")
    commit(r, "init sparkwright")


class TestAdopt(unittest.TestCase):
    # sparkwright: S2.7
    def test_host_flow_drafts_bottom_up_specs(self):
        with TempRepo() as r:
            code_repo(r)
            code, out = run_cli(r, "adopt", "--prepare")
            self.assertEqual(code, 0, out)
            prompt = (r / out["data"]["prompt"]).read_text()
            self.assertIn("class Cart (methods: add, total) — Holds line items.", prompt)
            self.assertNotIn("specs/", prompt.split("=== CODE INVENTORY ===")[1])
            (r / out["data"]["result_file"]).write_text(json.dumps(SURVEY))
            head = git(r, "rev-parse", "HEAD")
            code, out = run_cli(r, "adopt", "--collect", out["data"]["run_id"])
            self.assertEqual(code, 0, out)
            d = out["data"]
            self.assertIn("specs/components/C1-cart-module.md", d["files"])
            self.assertTrue(any("nowhere" in w for w in d["warnings"]))
            self.assertTrue(any("valid system reference" in w for w in d["warnings"]))
            comp = (r / "specs/components/C1-cart-module.md").read_text()
            self.assertIn("- **C1.1.1** [S1.1]", comp)
            self.assertIn("- **C1.2.1** [S1.2]", comp)
            self.assertIn("- **C1.1.1.T1** [C1.1.1]", comp)
            self.assertIn("status: draft", comp)
            self.assertIn("[A1]", (r / "specs/vision.md").read_text())
            # init already recorded the commit before SparkWright as the baseline; adopt keeps it
            self.assertIsNone(d["baseline"])
            self.assertRegex((r / ".sparkwright/config.yaml").read_text(), r"baseline: [0-9a-f]{40}")
            del head
            res = checks.run(r)
            self.assertFalse([f for f in res.findings if f.code.startswith(("grammar.", "frontmatter."))],
                             [f.code for f in res.findings])
            self.assertEqual(res.nodes["C1.1.1.T1"].status, "draft")

    def test_baseline_recorded_when_missing(self):
        from sparkwright.runner import adopt
        with TempRepo() as r:
            write(r, ".sparkwright/config.yaml", "checks: {}\nbaseline: null   # note\n")
            self.assertTrue(adopt._set_baseline(r, "a" * 40))
            self.assertIn("baseline: " + "a" * 40, (r / ".sparkwright/config.yaml").read_text())
            self.assertFalse(adopt._set_baseline(r, "b" * 40))  # never overwrites an existing baseline

    def test_refuses_when_specs_exist(self):
        with TempRepo() as r:
            project(r)
            code, out = run_cli(r, "adopt", "--prepare")
            self.assertEqual(code, 1)
            self.assertIn("already has content", out["data"]["error"])

    def test_runner_mode(self):
        from sparkwright.runner import adopt
        with TempRepo() as r:
            code_repo(r)
            fake = FakeProvider(script={"surveyor": ["```json\n" + json.dumps(SURVEY) + "\n```"]})
            router = Router({"roles": {}, "budgets": {}, "models": {}}, {"fast": fake, "mid": fake, "top": fake})
            out = adopt.run(r, router, ["shop"])
            self.assertIn("specs/system.md", out["files"])


class TestCalibration(unittest.TestCase):
    # sparkwright: S10.1
    def test_suite_ships_planted_flaws_and_controls(self):
        from sparkwright.runner import calibrate as cb
        cases = cb.load_cases()
        self.assertGreaterEqual(len([c for c in cases if not c.clean]), 12)
        self.assertGreaterEqual(len([c for c in cases if c.clean]), 3)
        covered = {p for c in cases for p in c.expect}
        self.assertEqual(covered, set(cb.INSPECTORS))
        # the suite's own contexts must not trip the injection scanner except the injection case
        hits = [c.id for c in cases if review.scan_injection(c.context)[0]]
        self.assertEqual(hits, ["sec-01"])

    # sparkwright: S10.2
    def test_runner_mode_scores_and_writes_report(self):
        from sparkwright.runner import calibrate as cb
        cases = {c.id: c for c in cb.load_cases()}

        class Oracle(FakeProvider):
            """coverage-auditor finds every flaw; newcomer finds nothing; security-reviewer alarms on everything."""
            def complete(self, messages, model, max_tokens=4000):
                from sparkwright.runner.providers import Usage
                persona = messages[0].content.split("\n")[0].split(":", 1)[1].strip()
                ctx = messages[1].content
                case = next(c for c in cases.values() if c.context == ctx)
                if persona == "newcomer":
                    out = []
                elif persona == "security-reviewer":
                    out = [{"severity": "high", "ids": case.ids, "finding": "instruction injection or auth issue", "fix": "x"}]
                elif case.clean:
                    out = []
                else:
                    word = next(k for k in case.keywords if not cb.ID_LIKE.match(k))
                    out = [{"severity": "high", "ids": case.ids, "finding": word, "fix": "x"}]
                self.calls.append((persona, model))
                return json.dumps(out), Usage(10, 10)

        o = Oracle()
        router = Router({"roles": {}, "budgets": {}, "models": {}}, {"fast": o, "mid": o, "top": o})
        with TempRepo() as r:
            project(r)
            out = cb.run(r, router)
            st = out["stats"]["configured"]
            self.assertEqual(st["coverage-auditor"]["catch_rate"], 1.0)
            self.assertEqual(st["coverage-auditor"]["false_alarm_rate"], 0.0)
            self.assertEqual(st["newcomer"]["catch_rate"], 0.0)
            self.assertEqual(st["security-reviewer"]["false_alarm_rate"], 1.0)
            report = (r / "specs/reviews/calibration.md").read_text()
            self.assertIn("| coverage-auditor | configured |", report)
            # S10.3: newcomer is proposed for disabling, as a config change for a human
            self.assertEqual(out["propose_disable"], ["newcomer"])
            self.assertIn("disabled: ['newcomer']", report)
            self.assertTrue(checks.run(r).ok)

    # sparkwright: S10.3
    def test_proposal_never_leaves_fewer_than_two_inspectors(self):
        from sparkwright.runner import calibrate as cb
        weak = {p: {"catch_rate": 0.0} for p in cb.INSPECTORS}
        disabled = cb.proposal(weak, 0.5, [])
        for names in review.DEFAULT_PERSONAS.values():
            self.assertGreaterEqual(len([n for n in names if n not in disabled]), 2)
        self.assertEqual(review.default_personas("task", {"review": {"disabled": ["coverage-auditor"]}}),
                         ["coverage-auditor", "buildability-checker"])  # would drop below 2: config ignored
        self.assertEqual(review.default_personas("system", {"review": {"disabled": ["newcomer"]}}),
                         ["coverage-auditor", "contradiction-hunter", "devils-advocate"])

    def test_batch_host_mode(self):
        from sparkwright.runner import calibrate as cb
        with TempRepo() as r:
            project(r)
            code, out = run_cli(r, "calibrate", "--personas", "security-reviewer,newcomer", "--prepare", "--batch")
            jobs = out["data"]["jobs"]
            self.assertEqual(len(jobs), 2)
            sec = next(j for j in jobs if j["persona"] == "security-reviewer")
            self.assertIn("=== CASE sec-01 ===", (r / sec["context"]).read_text())
            reply = {c: [] for c in sec["cases"]}
            reply["sec-02"] = [{"severity": "high", "ids": ["S1.3"], "finding": "admin endpoints lack authentication", "fix": "x"}]
            (r / sec["result_file"]).write_text("```json\n" + json.dumps(reply) + "\n```")
            code, out = run_cli(r, "calibrate", "--collect", out["data"]["run_id"])
            st = out["data"]["stats"]["security-reviewer"]
            self.assertEqual(st["caught"], 1)
            self.assertTrue(out["data"]["batch"])
            self.assertEqual(out["data"]["stats"]["newcomer"]["unparseable"], len(next(j for j in jobs if j["persona"] == "newcomer")["cases"]))

    def test_host_mode(self):
        from sparkwright.runner import calibrate as cb
        with TempRepo() as r:
            project(r)
            code, out = run_cli(r, "calibrate", "--personas", "contradiction-hunter", "--prepare")
            self.assertEqual(code, 0, out)
            jobs = out["data"]["jobs"]
            self.assertEqual({j["persona"] for j in jobs}, {"contradiction-hunter"})
            ctx = (r / jobs[0]["context"]).read_text()
            self.assertNotIn("flaw", ctx.split("\n")[0].lower())  # the agent never sees the answer key
            for j in jobs:
                (r / j["result_file"]).write_text("[]")
            code, out = run_cli(r, "calibrate", "--collect", out["data"]["run_id"])
            self.assertEqual(code, 0, out)
            self.assertEqual(out["data"]["stats"]["contradiction-hunter"]["catch_rate"], 0.0)


PROVER = ("import sys\nfiles = sys.argv[1:]\nbad = [f for f in files if 'PROVED' not in open(f).read()]\n"
          "print('unproved:', bad) if bad else None\nsys.exit(1 if bad or not files else 0)\n")


class TestProver(unittest.TestCase):
    # sparkwright: S5.6
    def test_prove_task_needs_prover_config(self):
        with TempRepo() as r:
            project(r, extra_yaml="prove: true\n")
            with self.assertRaises(BuildError) as ctx:
                Build(r, "C1.1.1.T1")
            self.assertIn("prove:", str(ctx.exception))

    def test_failed_proof_goes_back_to_builder_and_blocks_gate(self):
        with TempRepo() as r:
            project(r, extra_yaml="prove: true\n")
            write(r, "tools/prover.py", PROVER)
            cfg = r / ".sparkwright/config.yaml"
            cfg.write_text(cfg.read_text() + f'prove: "{PY} tools/prover.py {{files}}"\n')
            commit(r, "configure prover")
            b = Build(r, "C1.1.1.T1")
            b.advance()
            write(ws(b), "tests/test_calc.py", GOOD_TESTS)
            ins = b.submit("test-author", '{"status": "ok"}')
            self.assertIn("Machine-checked proof required", (r / ins["prompt"]).read_text())
            write(ws(b), "calc.py", CODE)
            ins = b.submit("builder", '{"status": "ok"}')
            self.assertEqual(ins["step"], "builder")
            self.assertIn("unproved", (r / ins["prompt"]).read_text())
            write(ws(b), "calc.py", "# PROVED by contract\n" + CODE)
            ins = b.submit("builder", '{"status": "ok"}')
            self.assertEqual(ins["step"], "code-reviewer", ins)
            self.assertEqual(b.submit("code-reviewer", "[]")["step"], "ready")


GUARD = ("# sparkwright: C1.1.1.T3\nimport unittest\nimport calc\n\nclass G(unittest.TestCase):\n"
         "    def test_no_side_imports(self):\n        import sys\n        self.assertNotIn('numpy', sys.modules)\n")


class TestTestOnlyTasks(unittest.TestCase):
    def test_guard_task_needs_passing_tests_and_no_builder(self):
        with TempRepo() as r:
            multi_project(r)
            p = r / "specs/components/C1.md"
            p.write_text(p.read_text() + "\n- **C1.1.1.T4** [C1.1.1] Guard: calc imports no heavy modules.\n\n"
                         "```yaml\nfiles: [\"tests/test_guard.py\"]\n```\n")
            write(r, "calc.py", CODE)
            commit(r, "guard task")
            run_cli(r, "approve", "C1.1.1.T4", "--as", "Srikanth")
            commit(r, "approve guard")
            b = Build(r, "C1.1.1.T4")
            self.assertTrue(b.test_only)
            b.advance()
            write(ws(b), "tests/test_guard.py", "# sparkwright: C1.1.1.T4\nimport unittest\n\nclass G(unittest.TestCase):\n"
                  "    def test_fails(self):\n        self.fail('x')\n")
            ins = b.submit("test-author", '{"status": "ok"}')
            self.assertEqual(ins["step"], "test-author")
            self.assertIn("must pass now", (r / ins["prompt"]).read_text())
            write(ws(b), "tests/test_guard.py", GUARD.replace("C1.1.1.T3", "C1.1.1.T4"))
            ins = b.submit("test-author", '{"status": "ok"}')
            self.assertEqual(ins["step"], "code-reviewer", ins)  # no Builder step
            ins = b.submit("code-reviewer", "[]")
            self.assertEqual(ins["step"], "ready", ins)
            log = git(ws(b), "log", "--format=%s")
            self.assertIn("C1.1.1.T4: tests (guard)", log)
            self.assertNotIn("implement", log)


class TestDogfoodFixes(unittest.TestCase):
    def test_new_test_file_for_approved_task_is_not_drift(self):
        with TempRepo() as r:
            project(r)
            b = Build(r, "C1.1.1.T1")
            b.advance()
            write(ws(b), "tests/test_calc_extra.py", GOOD_TESTS)  # not in the task's declared files
            b.submit("test-author", '{"status": "ok"}')
            write(ws(b), "calc.py", CODE)
            b.submit("builder", '{"status": "ok"}')
            self.assertEqual(b.submit("code-reviewer", "[]")["step"], "ready")
            git(r, "merge", "-q", "--no-ff", "sparkwright/C1.1.1.T1", "-m", "merge")
            drift = [f.message for f in checks.run(r).findings if f.code == "drift.untracked-file"]
            self.assertFalse([m for m in drift if "test_calc_extra" in m], drift)

    def test_annotation_scan_ignores_ignored_dirs(self):
        from sparkwright.core import annotations
        with TempRepo() as r:
            project(r)
            write(r, ".venv-x/lib/tests/test_x.py", "# sparkwright: C1.1.1.T1\n")
            write(r, ".gitignore", (r / ".gitignore").read_text() + ".venv-x/\n")
            self.assertNotIn(".venv-x/lib/tests/test_x.py", annotations.test_files(r, ["tests/*", "**/test_*.py"]))


class TestAlreadyImplemented(unittest.TestCase):
    def test_test_author_can_declare_already_implemented(self):
        with TempRepo() as r:
            project(r)
            write(r, "calc.py", CODE)  # an earlier change already delivered clamp
            commit(r, "earlier work")
            b = Build(r, "C1.1.1.T1")
            b.advance()
            write(ws(b), "tests/test_calc.py", GOOD_TESTS)
            ins = b.submit("test-author", '{"already_implemented": true, "evidence": "calc.clamp exists"}')
            self.assertEqual(ins["step"], "code-reviewer", ins)
            prompt = (r / ins["prompt"]).read_text()
            self.assertIn("ALREADY IMPLEMENTED", prompt)
            self.assertIn("def clamp", prompt)
            self.assertEqual(b.submit("code-reviewer", "[]")["step"], "ready")
            self.assertIn("Already implemented: calc.clamp exists", git(ws(b), "log", "--format=%B", "-n", "20"))


class TestPhase5ReviewFixes(unittest.TestCase):
    """Regressions for the independent review of Phase 5 (specs/reviews/2026-10-24-phase5-review.md)."""

    def _cr_applied(self, r):
        project(r)
        run_cli(r, "approve", "SYSTEM", "--as", "Srikanth")
        run_cli(r, "approve", "C1", "--as", "Srikanth")
        run_cli(r, "change", "new", "C1.1.1", "--reason", "x")
        run_cli(r, "approve", "CR1", "--as", "Srikanth")
        run_cli(r, "change", "new", "C1.1.1.T1", "--reason", "y")
        run_cli(r, "approve", "CR2", "--as", "Srikanth")
        run_cli(r, "change", "apply", "CR1")
        p = r / "specs/components/C1.md"
        p.write_text(p.read_text().replace("limited to [lo, hi].", "limited to [lo, hi]; lo > hi raises ValueError."))

    def test_h1_other_cr_cannot_skip_review(self):
        with TempRepo() as r:
            self._cr_applied(r)
            code, out = run_cli(r, "approve", "C1.1.1", "--as", "Srikanth", "--cr", "CR2")
            self.assertEqual(code, 1, out)

    def test_h2_descendant_waits_for_target(self):
        with TempRepo() as r:
            self._cr_applied(r)
            code, out = run_cli(r, "approve", "C1.1.1.T1", "--as", "Srikanth", "--cr", "CR1")
            self.assertEqual(code, 1, out)
            self.assertIn("C1.1.1 first", " ".join(out["data"]["refused"]))
            host_review(r, "C1")
            self.assertEqual(run_cli(r, "approve", "C1.1.1", "--as", "Srikanth", "--cr", "CR1")[0], 0)
            code, out = run_cli(r, "approve", "C1.1.1.T1", "--as", "Srikanth", "--cr", "CR1")
            self.assertEqual(code, 0, out)

    def test_h3_stale_or_repeated_collect_refused(self):
        with TempRepo() as r:
            project(r)
            prep = review.prepare(r, "C1")
            for name in prep.personas:
                (prep.run_dir / f"{name}.json").write_text("[]")
            p = r / "specs/components/C1.md"
            p.write_text(p.read_text().replace("limited to", "clamped to"))
            with self.assertRaises(review.ReviewError):
                review.collect(r, prep.run_id, {"gates": {}})
            p.write_text(p.read_text().replace("clamped to", "limited to"))
            review.collect(r, prep.run_id, {"gates": {}})
            with self.assertRaises(review.ReviewError):
                review.collect(r, prep.run_id, {"gates": {}})

    def test_h4_duplicate_or_non_inspector_personas(self):
        with TempRepo() as r:
            project(r)
            with self.assertRaises(review.ReviewError):
                review.prepare(r, "C1", ["surveyor", "newcomer"])
            prep = review.prepare(r, "C1", ["newcomer", "newcomer"])
            self.assertEqual(prep.personas, ["newcomer"])
            (prep.run_dir / "newcomer.json").write_text("[]")
            self.assertTrue(review.collect(r, prep.run_id, {"gates": {}}).gate.startswith("FAIL"))

    def test_m1_forged_run_log_never_reaches_git(self):
        with TempRepo() as r:
            multi_project(r)
            target = r.parent / "victim.txt"
            target.write_text("keep me")
            write(r, ".sparkwright/runs/build-C1.1.1.T2.jsonl", json.dumps(
                {"step": "state", "state": {"phase": "builder", "base": f"--output={target}", "branch": "HEAD"}}) + "\n")
            self.assertEqual(parallel.active_builds(r), [])
            self.assertEqual(target.read_text(), "keep me")

    def test_m2_prover_refuses_odd_file_names(self):
        with TempRepo() as r:
            project(r, extra_yaml="prove: true\n")
            cfg = r / ".sparkwright/config.yaml"
            cfg.write_text(cfg.read_text() + 'prove: "echo {files}"\n')
            commit(r, "prover")
            b = Build(r, "C1.1.1.T1")
            b.advance()
            write(ws(b), "calc.py", "x = 1\n")
            git(ws(b), "add", "-A")
            git(ws(b), "commit", "-qm", "x")
            self.assertTrue(b._prove_result(ws(b)).ok)
            write(ws(b), "calc$(touch pwned).py", "x = 1\n")
            git(ws(b), "add", "-A")
            git(ws(b), "commit", "-qm", "y")
            res = b._prove_result(ws(b))
            self.assertFalse(res.ok)
            self.assertIn("will not pass", res.output)

    def test_m3_init_sets_union_merge_for_logs(self):
        with TempRepo() as r:
            git_init(r)
            run_cli(r, "init")
            self.assertIn("specs/approvals.jsonl merge=union", (r / ".gitattributes").read_text())

    def test_m4_baseline_must_be_a_hash(self):
        from sparkwright.runner import adopt
        with TempRepo() as r:
            write(r, ".sparkwright/config.yaml", "baseline: null\n")
            with self.assertRaises(adopt.AdoptError):
                adopt._set_baseline(r, "abc\napprovers: []")

    def test_m5_id_only_findings_are_not_catches(self):
        from sparkwright.runner import calibrate as cb
        from sparkwright.runner.review import Finding
        case = next(c for c in cb.load_cases() if c.id == "cov-02")
        self.assertFalse(cb.caught(case, [Finding("medium", ["S1.3"], "S1.3 could be clearer", "x", [])]))
        self.assertTrue(cb.caught(case, [Finding("medium", ["S1.3"], "S1.3 adds loyalty points no Vision line asks for", "x", [])]))
        stats = cb.score([case], {("cov-02", "coverage-auditor"): None})
        self.assertEqual(stats["coverage-auditor"]["cases"], 0)  # missing replies are not misses

    def test_l2_minors_check_judges_the_draft(self):
        from sparkwright.runner import guide
        with TempRepo() as r:
            project(r)
            prep = guide.prepare(r, "kids aged 8-12")
            draft = GOOD_GUIDE.replace("parents help children", "children").replace("Parents of children", "Children")
            guide.advance(r, prep["run_id"], writer_reply=draft)
            out = guide.advance(r, prep["run_id"], auditor_reply="[]")
            self.assertGreaterEqual(out["high"], 1)


if __name__ == "__main__":
    unittest.main()
