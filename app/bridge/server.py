"""Bridge HTTP server — JSON API for the console UI + serves the UI itself.

Stdlib ThreadingHTTPServer, same as before: no pip install, no build step,
trivially frozen by PyInstaller. All endpoints are loopback-only.

Desk:
    POST /api/desk/scan        {public_id}            → result card
    POST /api/desk/search      {by, q}                → {tickets:[…]}
    POST /api/desk/bind        {public_id, uid_hex}   → binding
    POST /api/desk/reprint     {public_id}            → print result
    POST /api/desk/cancel      {public_id}

Gate:
    POST /api/gate/start | /api/gate/stop
    GET  /api/gate/state       connection + headcounts + recent passages

Ops:
    GET  /api/status           header snapshot (backend, gate, encoder, counts)
    GET  /api/log?since=ts     operator event log
    GET  /api/settings         masked config
    POST /api/settings         update (empty api_key keeps stored one)
    POST /api/test/backend     heartbeat against the real backend
    POST /api/test/printer     event-printing /health
    GET  /api/encoder/status   USB encoder probe
    POST /api/encoder/read     one inventory on the pad → UIDs
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from .client import ApiError
from .desk import DeskFlow
from .encoder import ECRFIDEncoder, EncoderUnavailable, probe as encoder_probe
from .gate import GateFlow
from .printer import PrinterError
from .state import Runtime

_UI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui")


def make_handler(rt: Runtime, gate: GateFlow | None = None):
    desk = DeskFlow(rt)
    gate = gate or GateFlow(rt)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        # -- plumbing ------------------------------------------------------

        def log_message(self, fmt, *args):
            pass  # quiet; operators use the UI log, not stderr

        def _json(self, obj, status=200):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            raw = self.rfile.read(length)
            try:
                parsed = json.loads(raw.decode("utf-8", errors="replace"))
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}

        def _err(self, e: Exception):
            if isinstance(e, ApiError):
                self._json({"ok": False, "error": e.error, "message": e.message,
                            "holder": e.holder, "binding": e.binding})
            elif isinstance(e, (PrinterError, EncoderUnavailable)):
                self._json({"ok": False, "error": "unavailable", "message": str(e)})
            else:
                self._json({"ok": False, "error": "internal", "message": str(e)})

        # -- GET -------------------------------------------------------------

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path, query = parsed.path, urllib.parse.parse_qs(parsed.query)
            try:
                if path in ("/", "/index.html"):
                    self._serve_ui()
                elif path == "/api/status":
                    self._json(rt.snapshot() | {
                        "version": __version__,
                        "gate_running": gate.running,
                    })
                elif path == "/api/log":
                    since = float(query["since"][0]) if query.get("since") else None
                    items, now = rt.log_since(since)
                    self._json({"items": items, "now": now})
                elif path == "/api/settings":
                    self._json(rt.config.public_view())
                elif path == "/api/gate/state":
                    self._json({
                        "running": gate.running,
                        "connected": rt.gate_connected,
                        "last_error": rt.gate_last_error,
                        "pending": len(gate._pending),
                    })
                elif path == "/api/encoder/status":
                    self._json(encoder_probe(rt.config.get("encoder_model", "D5200")))
                else:
                    self._json({"error": "not found"}, 404)
            except Exception as e:
                self._err(e)

        def _serve_ui(self):
            path = os.path.join(_UI, "index.html")
            try:
                with open(path, "rb") as f:
                    body = f.read()
            except FileNotFoundError:
                self._json({"error": "UI not installed"}, 404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        # -- POST ------------------------------------------------------------

        def do_POST(self):
            try:
                body = self._body()
                if self.path == "/api/desk/scan":
                    self._json({"ok": True, "card": desk.scan(body.get("public_id", ""))})
                elif self.path == "/api/desk/search":
                    self._json({"ok": True, **desk.search(body.get("by", "name"),
                                                          body.get("q", ""))})
                elif self.path == "/api/desk/bind":
                    self._json({"ok": True, "result": desk.bind_sticker(
                        body.get("public_id", ""), body.get("uid_hex", ""),
                        body.get("protocol", "iso15693"))})
                elif self.path == "/api/desk/reprint":
                    self._json({"ok": True, **desk.reprint(body.get("public_id", ""))})
                elif self.path == "/api/desk/cancel":
                    desk.cancel_session(body.get("public_id", ""))
                    self._json({"ok": True})
                elif self.path == "/api/gate/start":
                    gate.start()
                    rt.event("sys", "Gate watch started.")
                    self._json({"ok": True})
                elif self.path == "/api/gate/stop":
                    gate.stop()
                    rt.event("sys", "Gate watch stopped.")
                    self._json({"ok": True})
                elif self.path == "/api/settings":
                    rt.config.apply_updates(body)
                    rt.event("sys", "Settings saved.")
                    self._json({"ok": True})
                elif self.path == "/api/test/backend":
                    self._json(self._test_backend())
                elif self.path == "/api/test/printer":
                    self._json(self._test_printer())
                elif self.path == "/api/encoder/read":
                    self._json(self._encoder_read())
                else:
                    self._json({"error": "not found"}, 404)
            except Exception as e:
                self._err(e)

        # -- test buttons ------------------------------------------------------

        def _test_backend(self) -> dict:
            cfg = rt.config
            try:
                resp = rt.client().heartbeat(
                    name=cfg.get("station_name", "DXRFID Bridge"),
                    kind=cfg.get("station_kind", "desk"),
                    role=cfg.get("gate_role") if cfg.get("station_kind") == "gate" else None,
                    hw_model=cfg.get("encoder_model"),
                    firmware=None, app_version=__version__)
                with rt.lock:
                    rt.event_settings = resp.get("event")
                    rt.last_heartbeat_ok = True
                    rt.last_heartbeat_error = None
                ev = resp.get("event") or {}
                rt.event("api", f"Backend OK — event: {ev.get('name', '?')}")
                return {"ok": True, "event": ev, "server_time": resp.get("server_time")}
            except ApiError as e:
                with rt.lock:
                    rt.last_heartbeat_ok = False
                    rt.last_heartbeat_error = e.message
                rt.event("err", f"Backend check failed — {e.message}")
                return {"ok": False, "message": e.message}

        def _test_printer(self) -> dict:
            try:
                health = rt.printer().health()
                rt.event("print", f"Printer OK — {health.get('printer', '?')}")
                return {"ok": True, "health": health}
            except PrinterError as e:
                rt.event("err", str(e))
                return {"ok": False, "message": str(e)}

        def _encoder_read(self) -> dict:
            """One-shot pad inventory for the sticker step."""
            model = rt.config.get("encoder_model", "D5200")
            enc = ECRFIDEncoder(model=model)
            ctx = enc.open_first_device()
            try:
                tags = enc.inventory(ctx)
            finally:
                enc.close(ctx)
            return {"ok": True, "tags": tags}

    return Handler


def serve(port: int = 5050, open_browser: bool = False, autostart_gate: bool = False):
    rt = Runtime()
    gate = GateFlow(rt)
    handler = make_handler(rt, gate)
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}"
    rt.event("sys", f"DXRFID Bridge {__version__} started.")
    print(f"DXRFID Bridge console at {url}  (Ctrl+C to stop)")
    if autostart_gate:
        gate.start()
    if open_browser:
        threading.Timer(0.6, lambda: __import__("webbrowser").open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        gate.stop()
