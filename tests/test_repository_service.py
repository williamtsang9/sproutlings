"""Repository + service integration tests (real SQLite, mocked LLM)."""
import json
import unittest
from unittest import mock

from sproutlings import service, config
from sproutlings.db import connect
from sproutlings.repository import Repository, DuplicateContentError
from sproutlings.uniqueness import canonical_hash


def fresh_repo(tmp_name=":memory:"):
    return Repository(connect(tmp_name))


def fake_llm_sheet(field, grade, level, n_problems, avoid_topics,
                   focus_hints, child_age, seed):
    """Deterministic stand-in for the local model."""
    return {
        "title": f"{field} sheet (seed {seed})",
        "topic": f"{field.lower()}-topic-{seed % 7}",
        "instructions": "Do the things.",
        "problems": [{"prompt": f"{field} item {seed}-{i}",
                      "answer": f"ans {i}", "work_space": True}
                     for i in range(n_problems)],
    }


class TestRepository(unittest.TestCase):
    def setUp(self):
        self.repo = fresh_repo()
        self.cid = self.repo.add_child("Jon", 6, "1")

    def test_child_crud_and_validation(self):
        child = self.repo.get_child(self.cid)
        self.assertEqual(child["name"], "Jon")
        self.assertEqual(len(self.repo.list_children()), 1)
        with self.assertRaises(ValueError):
            self.repo.add_child("  ", 5, "K")
        with self.assertRaises(ValueError):
            self.repo.add_child("Sam", 5, "Grade 99")
        with self.assertRaises(Exception):      # UNIQUE name
            self.repo.add_child("Jon", 7, "2")

    def test_duplicate_hash_blocked_at_db_level(self):
        content = {"sheets": [{"topic": "t", "problems": []}]}
        h = canonical_hash(content)
        self.repo.save_packet(self.cid, "worksheet", "Mathematics",
                              "1", "Easy", content, h)
        with self.assertRaises(DuplicateContentError):
            self.repo.save_packet(self.cid, "worksheet", "Mathematics",
                                  "1", "Easy", content, h)

    def test_status_lifecycle_and_stats(self):
        content = {"sheets": []}
        pid = self.repo.save_packet(self.cid, "worksheet", "Mathematics",
                                    "1", "Easy", content,
                                    canonical_hash(content))
        self.repo.set_packet_status(pid, "completed")
        stats = self.repo.child_stats(self.cid)
        math_row = next(f for f in stats["fields"]
                        if f["field"] == "Mathematics")
        self.assertEqual(math_row["generated"], 1)
        self.assertEqual(math_row["completed"], 1)
        with self.assertRaises(ValueError):
            self.repo.set_packet_status(pid, "bogus")

    def test_score_recording_and_windowed_average(self):
        content = {"sheets": []}
        pid = self.repo.save_packet(self.cid, "test", None, "1", "Easy",
                                    content, canonical_hash(content))
        self.repo.record_test_scores(pid, self.cid,
                                     {"Mathematics": (8, 10)})
        avgs = self.repo.recent_scores(self.cid)
        self.assertAlmostEqual(avgs["Mathematics"], 0.8)
        with self.assertRaises(ValueError):
            self.repo.record_test_scores(pid, self.cid,
                                         {"Mathematics": (11, 10)})
        with self.assertRaises(ValueError):
            self.repo.record_test_scores(pid, self.cid,
                                         {"Basketweaving": (1, 2)})


class TestService(unittest.TestCase):
    def setUp(self):
        self.repo = fresh_repo()
        self.cid = self.repo.add_child("Theo", 3, "TK")

    def test_math_worksheet_end_to_end_unique(self):
        seen = set()
        for _ in range(6):
            p = service.generate_worksheet_packet(
                self.repo, self.cid, "Mathematics", "TK", "Easy")
            h = canonical_hash(p["content"])
            self.assertNotIn(h, seen)
            seen.add(h)
            self.assertEqual(p["status"], "approved")   # auto: programmatic
            self.assertEqual(p["content"]["source"], "programmatic")

    @mock.patch("sproutlings.service.llm.generate_sheet",
                side_effect=fake_llm_sheet)
    def test_llm_worksheet_needs_review(self, _):
        p = service.generate_worksheet_packet(
            self.repo, self.cid, "Penmanship", "TK", "Easy")
        self.assertEqual(p["status"], "needs_review")
        self.assertEqual(p["content"]["source"], "llm")
        self.assertEqual(len(p["content"]["sheets"]),
                         config.SHEETS_PER_PACKET)

    @mock.patch("sproutlings.service.llm.generate_sheet",
                side_effect=fake_llm_sheet)
    def test_test_packet_allocation_follows_weakness(self, _):
        # Seed scores: weak Literature, strong Mathematics.
        content = {"sheets": []}
        pid = self.repo.save_packet(self.cid, "test", None, "TK", "Easy",
                                    content, canonical_hash(content))
        self.repo.record_test_scores(pid, self.cid, {
            "Mathematics": (10, 10), "Literature": (3, 10)})

        p = service.generate_test_packet(
            self.repo, self.cid, ["Mathematics", "Literature"],
            "TK", "Easy", total_questions=12)
        alloc = p["content"]["allocation"]
        self.assertEqual(sum(alloc.values()), 12)
        self.assertGreater(alloc["Literature"], alloc["Mathematics"])

        m_total, l_total = alloc["Mathematics"], alloc["Literature"]
        result = service.record_test_result(
            self.repo, p["id"],
            {"Mathematics": (min(5, m_total), m_total),
             "Literature": (min(2, l_total), l_total)})
        self.assertIn("Literature", result["new_averages"])
        self.assertEqual(self.repo.get_packet(p["id"])["status"],
                         "completed")

    def test_validation_errors(self):
        with self.assertRaises(service.GenerationError):
            service.generate_worksheet_packet(
                self.repo, 999, "Mathematics", "1", "Easy")
        with self.assertRaises(service.GenerationError):
            service.generate_worksheet_packet(
                self.repo, self.cid, "Astrology", "1", "Easy")
        with self.assertRaises(service.GenerationError):
            service.generate_test_packet(
                self.repo, self.cid, [], "1", "Easy")

    def test_scoring_non_test_packet_rejected(self):
        p = service.generate_worksheet_packet(
            self.repo, self.cid, "Mathematics", "TK", "Easy")
        with self.assertRaises(service.GenerationError):
            service.record_test_result(self.repo, p["id"],
                                       {"Mathematics": (1, 2)})


if __name__ == "__main__":
    unittest.main()
