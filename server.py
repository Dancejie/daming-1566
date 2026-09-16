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


class PublishedHandler(film.Handler, legacy_server.DemoHandler):
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        BaseHTTPRequestHandler.end_headers(self)

    def do_HEAD(self):
        # Never inherit SimpleHTTPRequestHandler's unrestricted root dispatch.
        self.send_error(405, "Use GET")

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = unquote(parsed.path)
        if path in ("/health", "/api/health"):
            return self.json({
                "status": "ok", "worldId": "ming1566-film", "agentMode": "authored-rules",
                "contentVersion": self.engine().story["contentVersion"],
                "release": os.environ.get("RENDER_GIT_COMMIT", "local"),
                "readyVideoCount": len(self.media()["assets"]),
                "saveRecovery": "browser-action-journal", "classicUrl": "/classic/",
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
        if path in ("/api/tts/health", "/api/classic-voice"):
            return legacy_server.DemoHandler.do_GET(self)
        return film.Handler.do_GET(self)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.json({"error": "无效请求长度"}, 400)
        if length < 0 or length > 20000:
            return self.json({"error": "输入过长"}, 413)
        if urlsplit(self.path).path in ("/api/deepseek", "/api/tts"):
            return legacy_server.DemoHandler.do_POST(self)
        return film.Handler.do_POST(self)


def main():
    legacy_server.MODEL = os.environ.get("DEEPSEEK_MODEL", legacy_server.MODEL)
    film.initialize()
    port = int(os.environ.get("PORT", "8157"))
    print(f"Ming1566 cinematic edition listening on {port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), PublishedHandler).serve_forever()


if __name__ == "__main__":
    main()
