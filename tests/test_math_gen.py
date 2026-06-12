"""Math generator tests.

The crown jewel test re-derives every answer independently from the prompt
text and asserts it matches the stored answer key — proving answers are
correct by construction across thousands of generated problems.
"""
import re
import unittest
from fractions import Fraction

from sproutlings import config
from sproutlings.generators import math_gen


def _solve_from_prompt(prompt: str) -> str | None:
    """Independent solver: parse the rendered prompt and recompute."""
    p = prompt.strip()

    m = re.match(r"Count the shapes.*?:\s*(\S+)$", p)
    if m:
        return str(len(m.group(1)))

    m = re.match(r"^(-?\d+(?:\.\d+)?) ([+−×÷]) (-?\d+(?:\.\d+)?) = ____$", p)
    if m:
        a, op, b = float(m.group(1)), m.group(2), float(m.group(3))
        val = {"+": a + b, "−": a - b, "×": a * b, "÷": a / b}[op]
        if val == int(val):
            return str(int(val))
        return f"{val:g}"

    m = re.match(r"^(\d+)/(\d+) \+ (\d+)/(\d+) = ____", p)
    if m:
        s = Fraction(int(m.group(1)), int(m.group(2))) + \
            Fraction(int(m.group(3)), int(m.group(4)))
        return f"{s.numerator}/{s.denominator}"

    m = re.match(r"^What is (\d+)% of (\d+)\?$", p)
    if m:
        v = int(m.group(1)) * int(m.group(2)) / 100
        return str(int(v)) if v == int(v) else f"{v:g}"

    m = re.match(r"^\((-?\d+)\) ([+−×]) \((-?\d+)\) = ____$", p)
    if m:
        a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
        return str({"+": a + b, "−": a - b, "×": a * b}[op])

    m = re.match(r"^Solve for x:\s+(\d+)x ([+−]) (\d+) = (-?\d+)$", p)
    if m:
        a, sgn, b, c = (int(m.group(1)), m.group(2),
                        int(m.group(3)), int(m.group(4)))
        b = b if sgn == "+" else -b
        x = Fraction(c - b, a)
        assert x.denominator == 1
        return f"x = {x.numerator}"

    m = re.match(r"^(\d+)\^(\d+) = ____$", p)
    if m:
        return str(int(m.group(1)) ** int(m.group(2)))

    m = re.match(r"^If f\(x\) = (-?\d+)x² \+ \((-?\d+)\)x \+ \((-?\d+)\), "
                 r"find f\((-?\d+)\)\.$", p)
    if m:
        a, b, c, x = map(int, m.groups())
        return str(a * x * x + b * x + c)

    m = re.match(r"^Sequence: (.+), …\s+What is term number (\d+)\?$", p)
    if m:
        seq = [int(v) for v in m.group(1).split(", ")]
        d = seq[1] - seq[0]
        n = int(m.group(2))
        return str(seq[0] + (n - 1) * d)

    m = re.match(r"^Solve:\s+x²\s*(.*)= 0$", p)
    if m:
        return "QUADRATIC"   # verified by substitution in the test
    return None


class TestMathCorrectness(unittest.TestCase):
    def test_every_answer_recomputable(self):
        """Across all grades, all levels, several seeds: each stored answer
        must equal an independently recomputed answer."""
        checked = 0
        for grade in config.GRADES:
            for level in config.LEVELS:
                for seed in (1, 42, 999):
                    pkt = math_gen.generate_math_packet(
                        grade, level, seed, sheets=1, problems_per_sheet=8)
                    for prob in pkt.sheets[0].problems:
                        expected = _solve_from_prompt(prob.prompt)
                        self.assertIsNotNone(
                            expected, f"Solver can't parse: {prob.prompt!r}")
                        if expected == "QUADRATIC":
                            self._verify_quadratic(prob)
                        else:
                            self.assertEqual(
                                prob.answer, expected,
                                f"{grade}/{level}: {prob.prompt!r}")
                        checked += 1
        self.assertGreater(checked, 1500)

    def _verify_quadratic(self, prob):
        """Substitute each claimed root back into x² + bx + c."""
        m = re.match(r"^Solve:\s+x²\s*(?:([+−]) (\d+)x\s*)?(?:([+−]) (\d+)\s*)?= 0$",
                     prob.prompt)
        self.assertIsNotNone(m, prob.prompt)
        b = int(m.group(2) or 0) * (1 if m.group(1) == "+" else -1) \
            if m.group(2) else 0
        c = int(m.group(4) or 0) * (1 if m.group(3) == "+" else -1) \
            if m.group(4) else 0
        roots = [int(r) for r in re.findall(r"x = (-?\d+)", prob.answer)]
        self.assertTrue(roots)
        for r in roots:
            self.assertEqual(r * r + b * r + c, 0,
                             f"{prob.prompt} root {r} fails")


class TestMathProperties(unittest.TestCase):
    def test_deterministic_for_same_seed(self):
        a = math_gen.generate_math_packet("3", "Medium", 7).to_dict()
        b = math_gen.generate_math_packet("3", "Medium", 7).to_dict()
        self.assertEqual(a, b)

    def test_different_seeds_differ(self):
        a = math_gen.generate_math_packet("3", "Medium", 7).to_dict()
        b = math_gen.generate_math_packet("3", "Medium", 8).to_dict()
        self.assertNotEqual(a, b)

    def test_no_repeated_prompts_within_sheet(self):
        for seed in range(20):
            pkt = math_gen.generate_math_packet("K", "Easy", seed)
            for sheet in pkt.sheets:
                prompts = [p.prompt for p in sheet.problems]
                self.assertEqual(len(prompts), len(set(prompts)))

    def test_young_grades_never_negative_subtraction(self):
        for seed in range(50):
            pkt = math_gen.generate_math_packet("1", "EXTREME", seed,
                                                sheets=1)
            for prob in pkt.sheets[0].problems:
                if "−" in prob.prompt and "(" not in prob.prompt:
                    self.assertGreaterEqual(int(prob.answer), 0, prob.prompt)

    def test_packet_shape(self):
        pkt = math_gen.generate_math_packet("5", "Hard", 1)
        self.assertEqual(len(pkt.sheets), config.SHEETS_PER_PACKET)
        for s in pkt.sheets:
            self.assertEqual(len(s.problems), config.PROBLEMS_PER_SHEET)
            for p in s.problems:
                self.assertTrue(p.prompt and p.answer)

    def test_invalid_inputs_rejected(self):
        with self.assertRaises(ValueError):
            math_gen.generate_math_packet("13", "Easy", 1)
        with self.assertRaises(ValueError):
            math_gen.generate_math_packet("3", "Impossible", 1)

    def test_test_question_helper(self):
        qs = math_gen.generate_math_questions("7", "Hard", 5, n=9)
        self.assertEqual(len(qs), 9)


if __name__ == "__main__":
    unittest.main()
