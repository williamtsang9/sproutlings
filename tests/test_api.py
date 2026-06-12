"""HTTP API tests. Run on your machine after `pip install -r requirements.txt`;
they self-skip in environments without FastAPI."""
import unittest
from unittest import mock

try:
    from fastapi.testclient import TestClient
    HAVE_FASTAPI = True
except ImportError:
    HAVE_FASTAPI = False


@unittest.skipUnless(HAVE_FASTAPI, "fastapi not installed")
class TestAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ["SPROUTLINGS_DB_PATH"] = ":memory:"
        # Re-import with the in-memory DB.
        import importlib
        from sproutlings import config as cfg
        importlib.reload(cfg)
        from sproutlings import api
        importlib.reload(api)
        cls.api = api
        cls.client = TestClient(api.app)

    def test_meta(self):
        r = self.client.get("/api/meta")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("Mathematics", body["fields"])
        self.assertIn("EXTREME", body["levels"])

    def test_full_worksheet_flow(self):
        r = self.client.post("/api/children", json={
            "name": "Jon-API", "age": 6, "default_grade": "1"})
        self.assertEqual(r.status_code, 201)
        cid = r.json()["id"]

        r = self.client.post("/api/worksheets", json={
            "child_id": cid, "field": "Mathematics",
            "grade": "1", "level": "Moderate"})
        self.assertEqual(r.status_code, 201)
        packet = r.json()
        self.assertEqual(packet["status"], "approved")

        r = self.client.patch(f"/api/packets/{packet['id']}/status",
                              json={"status": "completed"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "completed")

        r = self.client.get(f"/api/children/{cid}/stats")
        math_row = next(f for f in r.json()["fields"]
                        if f["field"] == "Mathematics")
        self.assertEqual(math_row["completed"], 1)

    def test_test_flow_with_mocked_llm(self):
        r = self.client.post("/api/children", json={
            "name": "Theo-API", "age": 3, "default_grade": "TK"})
        cid = r.json()["id"]

        def fake_sheet(field, grade, level, n_problems, avoid_topics,
                       focus_hints, child_age, seed):
            return {"title": f"{field}", "topic": f"t{seed}",
                    "instructions": "do",
                    "problems": [{"prompt": f"q{i}", "answer": "a",
                                  "work_space": True}
                                 for i in range(n_problems)]}

        with mock.patch("sproutlings.service.llm.generate_sheet",
                        side_effect=fake_sheet):
            r = self.client.post("/api/tests", json={
                "child_id": cid, "fields": ["Mathematics", "Penmanship"],
                "grade": "TK", "level": "Easy", "total_questions": 10})
        self.assertEqual(r.status_code, 201)
        packet = r.json()

        r = self.client.post(f"/api/packets/{packet['id']}/score", json={
            "per_field": {"Mathematics": [4, 5], "Penmanship": [2, 5]}})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Penmanship", r.json()["new_averages"])

    def test_validation_errors_are_422(self):
        r = self.client.post("/api/worksheets", json={
            "child_id": 9999, "field": "Mathematics",
            "grade": "1", "level": "Easy"})
        self.assertEqual(r.status_code, 422)
        r = self.client.get("/api/packets/424242")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
