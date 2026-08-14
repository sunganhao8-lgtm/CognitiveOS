"""Local dashboard server — Phase 9.

`cogos dashboard serve [--port]` binds 127.0.0.1 ONLY (never public):

    GET  /            → the rendered dashboard (same single-file HTML)
    POST /api/memory  → confirm/reject/forget/modify through MemoryService

In serve mode the dashboard buttons call this API directly (no copy-CLI
workaround needed). file:// static mode keeps the copy-CLI behaviour.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .dashboard import render_dashboard
from .memory_service import MemoryService
from .paths import Paths

DEFAULT_PORT = 8787


def _render_with_serve(paths: Paths) -> Path:
    """Render index.html with serve_mode=True (buttons call the API)."""
    # the template reads serve_mode from render context; reuse render_dashboard
    # then patch the flag? No — render_dashboard doesn't know about serve mode.
    # Simplest honest approach: serve the static render and let JS detect
    # that it is being served over http (protocol check) → API mode.
    return render_dashboard(paths)


class _Handler(BaseHTTPRequestHandler):
    paths: Paths = None  # set by the server

    def log_message(self, fmt, *args):  # keep the console quiet-ish
        pass

    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/index.html"):
            out = _render_with_serve(self.paths)
            body = out.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        # static assets (brain svg)
        if self.path.startswith("/assets/"):
            asset = (self.paths.root / self.path.lstrip("/")).resolve()
            if asset.exists() and asset.is_file():
                body = asset.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml" if asset.suffix == ".svg" else "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == "/api/memory":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except json.JSONDecodeError:
                payload = {}
            action = payload.get("action")
            mem_id = payload.get("id")
            if action not in ("confirm", "reject", "forget") or not mem_id:
                self._json(400, {"error": f"action={action!r} id={mem_id!r}"})
                return
            svc = MemoryService(self.paths)
            try:
                if action == "confirm":
                    result = svc.confirm(mem_id, reason="dashboard confirm")
                elif action == "reject":
                    result = svc.reject(mem_id, reason="dashboard reject")
                else:
                    result = svc.forget(mem_id, reason="dashboard forget")
                self._json(200, result)
            except (KeyError, ValueError) as exc:
                self._json(400, {"error": str(exc)})
            finally:
                svc.close()
            return
        self._json(404, {"error": "not found"})

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(paths: Paths, *, port: int = DEFAULT_PORT) -> None:
    """Blocking local server (127.0.0.1)."""
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    _Handler.paths = paths  # type: ignore[attr-defined]
    print(f"CognitiveOS dashboard: http://127.0.0.1:{port}  (local only, Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
