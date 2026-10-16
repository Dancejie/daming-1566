"""Published entry point: cinematic game plus the original character demo."""
import importlib.util
import os
import sys
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import legacy_server

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "film" / "backend"))
spec = importlib.util.spec_from_file_location("ming_film_server", ROOT / "film" / "backend" / "server.py")
film = importlib.util.module_from_spec(spec)
spec.loader.exec_module(film)

# Reuse the same engine and HTTP contract with isolated content and persistence.
original_spec = importlib.util.spec_from_file_location("ming_original_server", ROOT / "film" / "backend" / "server.py")
original = importlib.util.module_from_spec(original_spec)
original_spec.loader.exec_module(original)
original.ROOT = ROOT / "original"
data_dir = os.environ.get("DAMING_DATA_DIR")
if data_dir:
    film.DB = Path(data_dir) / "storm" / "runs.sqlite3"
original.DB = (Path(data_dir) / "original" if data_dir else original.ROOT / "private") / "runs.sqlite3"


class PublishedHandler(film.Handler, legacy_server.DemoHandler):
    edition = film

    def select_edition(self):
        parsed = urlsplit(self.path)
        self.edition = original if parsed.path.startswith("/original/") else film
        if self.edition is original:
            self.path = self.path[len("/original"):]

    def engine(self):
        return self.edition.Handler.engine(self)

    def media(self):
        return self.edition.Handler.media(self)

    def redirect(self, target):
        self.send_response(302)
        self.send_header("Location", target)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def end_headers(self):
        allowed_origin = os.environ.get("DAMING_ALLOWED_ORIGIN", "")
        if allowed_origin and self.headers.get("Origin") == allowed_origin:
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        BaseHTTPRequestHandler.end_headers(self)

    def do_OPTIONS(self):
        allowed = os.environ.get("DAMING_ALLOWED_ORIGIN", "")
        if not allowed or self.headers.get("Origin") != allowed:
            self.send_response(403)
        else:
            self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        # Never inherit SimpleHTTPRequestHandler's unrestricted root dispatch.
        self.send_error(405, "Use GET")

    def do_GET(self):
        if urlsplit(self.path).path in ("/", "/original"):
            return self.redirect("/original/")
        if urlsplit(self.path).path == "/storm":
            return self.redirect("/storm/")
        if urlsplit(self.path).path == "/storm/":
            self.path = "/"
        self.select_edition()
        parsed = urlsplit(self.path)
        path = unquote(parsed.path)
        if path in ("/health", "/api/health"):
            active = original
            story = active.read(active.ROOT / "content/story.json")
            return self.json({
                "status": "ok", "worldId": story["id"], "agentMode": "authored-rules",
                "contentVersion": story["contentVersion"],
                "release": os.environ.get("DAMING_RELEASE", os.environ.get("RENDER_GIT_COMMIT", "local")),
                "readyVideoCount": len(active.Handler.media(self)["assets"]),
                "saveRecovery": "browser-action-journal", "classicUrl": "/classic/",
                "originalUrl": "/original/", "previousEditionUrl": "/storm/",
            })
        if path == "/classic":
            self.send_response(308)
            self.send_header("Location", "/classic/")
            self.send_header("Content-Length", "0")
            return self.end_headers()
        if path.startswith("/classic/"):
            relative = path[len("/classic/"):] or "index.html"
            file = (ROOT / relative).resolve()
            allowed = relative in ("index.html", "app.js", "style.css") or (
                relative.startswith("assets/") and file.is_relative_to((ROOT / "assets").resolve())
            )
            if not allowed or not file.is_file():
                return self.send_error(404)
            self.path = "/" + quote(relative, safe="/")
            return SimpleHTTPRequestHandler.do_GET(self)
        if path == "/api/classic/health":
            self.path = "/api/health"
            return legacy_server.DemoHandler.do_GET(self)
        if path == "/api/classic-voice" and os.environ.get("DAMING_STATIC_BASE"):
            import urllib.parse
            clip_id = (urllib.parse.parse_qs(parsed.query).get("id") or [""])[0]
            item = legacy_server.load_classic_voice_manifest().get(clip_id)
            source = str(item.get("src", "")) if item else ""
            source = source.removeprefix("./")
            if not source.startswith("assets/classic_voice/") or ".." in Path(source).parts:
                return self.json({"error": "classic voice clip not found"}, 404)
            return self.redirect(os.environ["DAMING_STATIC_BASE"].rstrip("/") + "/" + quote(source, safe="/"))
        if path in ("/api/tts/health", "/api/classic-voice"):
            return legacy_server.DemoHandler.do_GET(self)
        return self.edition.Handler.do_GET(self)

    def do_POST(self):
        self.select_edition()
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.json({"error": "无效请求长度"}, 400)
        if length < 0 or length > 20000:
            return self.json({"error": "输入过长"}, 413)
        if urlsplit(self.path).path in ("/api/deepseek", "/api/tts"):
            return legacy_server.DemoHandler.do_POST(self)
        return self.edition.Handler.do_POST(self)


def main():
    legacy_server.MODEL = os.environ.get("DEEPSEEK_MODEL", legacy_server.MODEL)
    film.initialize()
    original.initialize()
    port = int(os.environ.get("PORT", "8157"))
    print(f"Ming1566 cinematic edition listening on {port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), PublishedHandler).serve_forever()


if __name__ == "__main__":
    main()
