"""Tests for uniqueness hashing, the adaptive engine, and LLM validation."""
import unittest

from sproutlings import adaptive, config
from sproutlings.uniqueness import canonical_hash
from sproutlings.llm import (build_prompt, parse_sheet_json,
                             LLMValidationError)


class TestUniqueness(unittest.TestCase):
    def test_identical_content_same_hash(self):
        c = {"sheets": [{"topic": "Fractions", "problems": []}]}
        self.assertEqual(canonical_hash(c), canonical_hash(dict(c)))

    def test_whitespace_and_case_normalized(self):
        a = {"sheets": [{"topic": "Skip   Counting"}]}
        b = {"sheets": [{"topic": "skip counting"}]}
        self.assertEqual(canonical_hash(a), canonical_hash(b))

    def test_volatile_keys_ignored(self):
        a = {"topic": "x", "seed": 1, "generated_at": "now", "model": "a"}
        b = {"topic": "x", "seed": 2, "generated_at": "later", "model": "b"}
        self.assertEqual(canonical_hash(a), canonical_hash(b))

    def test_real_difference_changes_hash(self):
        a = {"sheets": [{"problems": [{"prompt": "2 + 2", "answer": "4"}]}]}
        b = {"sheets": [{"problems": [{"prompt": "2 + 3", "answer": "5"}]}]}
        self.assertNotEqual(canonical_hash(a), canonical_hash(b))

    def test_key_order_irrelevant(self):
        self.assertEqual(canonical_hash({"a": 1, "b": 2}),
                         canonical_hash({"b": 2, "a": 1}))


class TestAdaptive(unittest.TestCase):
    def test_weights_sum_to_one_and_favor_weakness(self):
        scores = {"Mathematics": 0.95, "Literature": 0.40}
        w = adaptive.weakness_weights(scores, ["Mathematics", "Literature"])
        self.assertAlmostEqual(sum(w.values()), 1.0)
        self.assertGreater(w["Literature"], w["Mathematics"])

    def test_unknown_field_gets_moderate_weight(self):
        w = adaptive.weakness_weights({}, ["Drawing"])
        self.assertAlmostEqual(w["Drawing"], 1.0)

    def test_strong_field_keeps_floor(self):
        w = adaptive.weakness_weights(
            {"Mathematics": 1.0, "Literature": 0.0},
            ["Mathematics", "Literature"])
        self.assertGreater(w["Mathematics"], 0.0)

    def test_allocation_exact_and_minimum_one(self):
        w = adaptive.weakness_weights(
            {"Mathematics": 0.9, "Literature": 0.2, "Memorization": 0.5},
            ["Mathematics", "Literature", "Memorization"])
        alloc = adaptive.allocate_questions(20, w)
        self.assertEqual(sum(alloc.values()), 20)
        self.assertTrue(all(v >= 1 for v in alloc.values()))
        self.assertGreater(alloc["Literature"], alloc["Mathematics"])

    def test_allocation_rejects_too_few_questions(self):
        w = adaptive.weakness_weights({}, ["A1", "A2", "A3"])
        with self.assertRaises(ValueError):
            adaptive.allocate_questions(2, w)

    def test_level_stepping(self):
        self.assertEqual(adaptive.suggest_level("Medium", 0.95), "Semi hard")
        self.assertEqual(adaptive.suggest_level("Medium", 0.40), "Moderate")
        self.assertEqual(adaptive.suggest_level("Medium", 0.75), "Medium")
        self.assertEqual(adaptive.suggest_level("EXTREME", 0.99), "EXTREME")
        self.assertEqual(adaptive.suggest_level("Easy", 0.10), "Easy")
        self.assertEqual(adaptive.suggest_level("Medium", None), "Medium")

    def test_focus_hints_weakest_first(self):
        hints = adaptive.focus_hints({"Literature": 0.5, "Drawing": 0.95})
        self.assertIn("Literature", hints[0])
        self.assertIn("weak", hints[0])


class TestLLMValidation(unittest.TestCase):
    GOOD = ('{"title": "T", "topic": "Cursive a-e", "instructions": "Trace",'
            ' "problems": [{"prompt": "aaa", "answer": "round letters"},'
            ' {"prompt": "bbb", "answer": "tall stems"}]}')

    def test_parses_clean_json(self):
        sheet = parse_sheet_json(self.GOOD, expected_problems=2)
        self.assertEqual(sheet["topic"], "Cursive a-e")
        self.assertEqual(len(sheet["problems"]), 2)

    def test_strips_think_blocks_and_fences(self):
        raw = "<think>pondering...</think>\n```json\n" + self.GOOD + "\n```"
        sheet = parse_sheet_json(raw, expected_problems=2)
        self.assertEqual(sheet["title"], "T")

    def test_rejects_prose(self):
        with self.assertRaises(LLMValidationError):
            parse_sheet_json("Sure! Here's a worksheet idea...", 2)

    def test_rejects_missing_answer(self):
        bad = ('{"title":"T","topic":"x","instructions":"y",'
               '"problems":[{"prompt":"p","answer":"  "}]}')
        with self.assertRaises(LLMValidationError):
            parse_sheet_json(bad, 1)

    def test_rejects_severe_undercount(self):
        with self.assertRaises(LLMValidationError):
            parse_sheet_json(self.GOOD, expected_problems=12)

    def test_prompt_includes_constraints(self):
        p = build_prompt("Literature", "2", "Medium", 6,
                         avoid_topics=["The Lost Kite"],
                         focus_hints=["Literature: recent test average 55%"],
                         child_age=6, seed=99)
        for needle in ("Literature", "Grade: 2", "Medium", "exactly 6",
                       "The Lost Kite", "55%", "6 years old", "/no_think"):
            self.assertIn(needle, p)

    def test_prompt_rejects_math(self):
        with self.assertRaises(ValueError):
            build_prompt("Mathematics", "2", "Easy", 5, [], [], 6, 1)


if __name__ == "__main__":
    unittest.main()
