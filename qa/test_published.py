"""Check the actual Render entry point without accessing a model provider."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class PublishedRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.old_db = server.film.DB
        server.film.DB = Path(cls.temp.name) / "runs.sqlite3"
        server.film.initialize()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.PublishedHandler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()
        server.film.DB = cls.old_db
        cls.temp.cleanup()

    def request(self, path, method="GET", read=True):
        try:
            response = urllib.request.urlopen(urllib.request.Request(self.base + path, method=method), timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, response.headers, response.read() if read else b""

    def test_new_root_and_legacy_directory(self):
        status, _, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("风暴初夜", body.decode())
        status, _, body = self.request("/classic/")
        self.assertEqual(status, 200)
        self.assertIn("名场面目录", body.decode())
        status, _, body = self.request("/classic/app.js")
        self.assertEqual(status, 200)
        self.assertIn(b'/api/classic/health', body)
        status, _, body = self.request("/api/classic/health")
        self.assertEqual(status, 200)
        self.assertIsInstance(json.loads(body)["deepseekConfigured"], bool)

    def test_health_identifies_published_edition(self):
        status, _, body = self.request("/api/health")
        health = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(health["worldId"], "ming1566-film")
        self.assertEqual(health["readyVideoCount"], 9)
        self.assertEqual(health["saveRecovery"], "browser-action-journal")

    def test_legacy_mount_cannot_publish_source_or_saves(self):
        for path in ("/server.py", "/legacy_server.py", "/.env", "/film/private/runs.sqlite3",
                     "/classic/.env", "/classic/server.py", "/classic/film/private/runs.sqlite3",
                     "/classic/assets/../../.env", "/classic/assets/%2e%2e/legacy_server.py",
                     "/classic/assets/%252e%252e/legacy_server.py", "/classic/assets/"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path, read=False)[0], 404)
                self.assertEqual(self.request(path, method="HEAD", read=False)[0], 405)


if __name__ == "__main__":
    unittest.main()
