import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from web_gather.api import create_app


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.client = TestClient(create_app(data_root=self.tmp, reseach_root=self.tmp / "research"))

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_api_info(self):
        r = self.client.get("/api-info")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["service"], "web-gather")
        self.assertTrue(r.json()["cors_open"])

    def test_gui_served(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("web-gather studio", r.text)

    def test_tools_endpoint(self):
        r = self.client.get("/v1/tools")
        self.assertEqual(r.status_code, 200)
        names = [t["name"] for t in r.json()["tools"]]
        self.assertIn("research", names)

    def test_cors_open_preflight(self):
        r = self.client.options(
            "/v1/jobs",
            headers={
                "Origin": "https://any-website.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["access-control-allow-origin"], "*")

    def test_unknown_job_404(self):
        r = self.client.get("/v1/jobs/nope")
        self.assertEqual(r.status_code, 404)

    def test_research_validation(self):
        r = self.client.post("/v1/research", json={"goal": ""})
        self.assertEqual(r.status_code, 422)

    def test_cors_restricted_when_configured(self):
        client = TestClient(create_app(cors_origins=["https://mine.example"]))
        r = client.options(
            "/v1/jobs",
            headers={"Origin": "https://mine.example", "Access-Control-Request-Method": "POST"},
        )
        self.assertEqual(r.headers.get("access-control-allow-origin"), "https://mine.example")
        r2 = client.options(
            "/v1/jobs",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )
        self.assertIsNone(r2.headers.get("access-control-allow-origin"))


if __name__ == "__main__":
    unittest.main()