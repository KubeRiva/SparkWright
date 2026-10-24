import unittest

from sparkwright.core import ids
from sparkwright.core.frontmatter import FrontMatterError, split
from sparkwright.core.grammar import parse_body, text_hash


class TestIds(unittest.TestCase):
    # sparkwright: S1.2
    def test_kinds(self):
        self.assertEqual(ids.kind_of("V3"), "vision")
        self.assertEqual(ids.kind_of("S11.2"), "system")
        self.assertEqual(ids.kind_of("C2.3.1"), "component")
        self.assertEqual(ids.kind_of("C2.3.1.T4"), "task")
        self.assertEqual(ids.kind_of("CR7"), "change")
        self.assertEqual(ids.kind_of("E01"), "evidence")
        self.assertIsNone(ids.kind_of("T4"))

    def test_natural_sort(self):
        self.assertEqual(sorted(["S1.10", "S1.2", "S2.1"], key=ids.sort_key), ["S1.2", "S1.10", "S2.1"])


class TestFrontMatter(unittest.TestCase):
    # sparkwright: S1.1
    def test_split(self):
        meta, body, line = split("---\nid: X\ntitle: t\n---\nhello\n")
        self.assertEqual(meta["id"], "X")
        self.assertEqual(body, "hello\n")
        self.assertEqual(line, 5)  # '---', id, title, '---', then the body on line 5

    def test_rejects_aliases(self):
        with self.assertRaises(FrontMatterError):
            split("---\na: &x 1\nb: *x\n---\n")

    def test_unclosed(self):
        with self.assertRaises(FrontMatterError):
            split("---\nid: X\n")

    def test_windows_newlines(self):
        meta, body, _ = split("---\r\nid: X\r\n---\r\nbody\r\n")
        self.assertEqual(meta["id"], "X")


class TestGrammar(unittest.TestCase):
    def test_basic_line_and_continuation(self):
        reqs, issues = parse_body("- **S1.1** [V1, V2] The system shall\n  do things.\n", "f.md")
        self.assertEqual(issues, [])
        self.assertEqual(reqs[0].refs, ["V1", "V2"])
        self.assertEqual(reqs[0].text, "The system shall do things.")

    def test_hash_ignores_whitespace(self):
        self.assertEqual(text_hash("a  b\nc"), text_hash(" a b c "))

    def test_malformed_near_miss(self):
        _, issues = parse_body("- **V1 — Title.** text\n", "f.md")
        self.assertEqual(issues[0].code, "grammar.malformed")

    def test_ordinary_bold_bullet_is_not_flagged(self):
        reqs, issues = parse_body("- **Solo builders** who build.\n", "f.md")
        self.assertEqual((reqs, issues), ([], []))

    def test_ignores_code_fences(self):
        reqs, _ = parse_body("```\n- **S1.1** [V1] example\n```\n", "f.md")
        self.assertEqual(reqs, [])

    # sparkwright: S1.8
    def test_task_extras(self):
        body = "- **C1.1.1.T1** [C1.1.1] Do it.\n\n```yaml\nfiles: [\"src/a/**\"]\nprove: true\n```\n"
        reqs, issues = parse_body(body, "f.md")
        self.assertEqual(issues, [])
        self.assertEqual(reqs[0].extras["files"], ["src/a/**"])
        self.assertTrue(reqs[0].extras["prove"])

    def test_bad_extras(self):
        body = "- **C1.1.1.T1** [C1.1.1] Do it.\n```yaml\nfiles: 3\ncolour: red\n```\n"
        _, issues = parse_body(body, "f.md")
        self.assertTrue(all(i.code == "grammar.extras-invalid" for i in issues))
        self.assertEqual(len(issues), 2)

    def test_line_numbers(self):
        reqs, _ = parse_body("intro\n\n- **S1.1** [V1] x\n", "f.md", first_line=10)
        self.assertEqual(reqs[0].line, 12)


if __name__ == "__main__":
    unittest.main()
