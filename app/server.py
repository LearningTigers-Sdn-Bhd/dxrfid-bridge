#!/usr/bin/env python3
"""
Local web dashboard for the DXRFID reader (mock or real, network mode).

Serves a browser UI (index.html) plus a small JSON API that:
  - opens/closes a TCP connection to the reader (mock_reader.py or a real
    reader in network mode) and speaks the EC_RFID/ECRFID wire protocol
  - triggers commands (inventory, reader info) and logs every raw TX/RX frame
  - proxies GET/POST calls to an external "live server" API, so the browser
    can test connectivity/auth without hitting CORS restrictions

Pure stdlib, no pip installs required.

Run:
    python3 server.py [--port 5050]
Then open http://localhost:5050
"""
import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mock_reader import SOF, crc16, parse_frame  # reuse protocol logic

STATE = {
    "conn": None,
    "host": "127.0.0.1",
    "port": 6688,
    "com_adr": 0xFF,
    "lock": threading.Lock(),
    "last_ping_ok": None,      # True/False/None(never pinged)
    "last_ping_ts": None,
    "last_ping_error": None,
    # EventzFlow (or any live server) API settings
    "api_url": "",
    "api_auth_header": "Authorization",
    "api_auth_value": "",
    "api_content_type": "application/json",
    # Encoder helper service (runs on the Windows PC with the USB encoder)
    "encoder_url": "http://127.0.0.1:7000",
    # Auto-forward: continuously poll the reader and push NEW tag sightings
    # to the API URL above, without a person clicking anything.
    "auto_forward": False,
    "dedup_seconds": 5,
    "last_forwarded": {},   # uid -> timestamp last successfully forwarded
    "forwarded_count": 0,
    "suppressed_count": 0,
}
LOG = deque(maxlen=300)
TAGS = {}
HEARTBEAT_INTERVAL = 5    # seconds between automatic reader pings
AUTO_FORWARD_POLL = 2     # seconds between automatic inventory scans
IO_LOCK = threading.Lock()  # only one command may be in flight on the socket at a time


def log_event(direction, data: bytes, summary=""):
    LOG.appendleft({"ts": time.time(), "dir": direction, "hex": data.hex(), "summary": summary})


def describe_frame(direction: str, frame: dict) -> str:
    """Turn a raw protocol frame into a one-line, human-readable description."""
    ct, cc, data = frame["cmd_type"], frame["cmd_code"], frame["data"]
    warn = "" if frame["crc_ok"] else "  ⚠ data looked corrupted (checksum mismatch)"

    if ct == 0xFE and cc == 0x01:  # ISO15693 inventory
        if len(data) >= 10:
            uid_hex = data[2:10].hex().upper()
            return f"Found a tag — ID {uid_hex}{warn}"
        return f"No more tags — scan finished{warn}"
    if ct == 0x78 and cc == 0x00:  # reader info
        name = data[1:].split(b"\x00")[0].decode("utf-8", errors="replace")
        return f"Scanner identified itself: \"{name}\"{warn}"
    return f"Scanner replied (unrecognized message type){warn}"


def build_request(com_adr, cmd_type, cmd_code, payload=b""):
    length = 6 + len(payload)
    body = bytes([length, com_adr, cmd_type, cmd_code]) + payload
    crc = crc16(body)
    return bytes([SOF]) + body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def do_connect(host, port):
    with STATE["lock"]:
        if STATE["conn"]:
            try:
                STATE["conn"].close()
            except OSError:
                pass
        s = socket.create_connection((host, port), timeout=4)
        STATE["conn"], STATE["host"], STATE["port"] = s, host, port
    log_event("sys", b"", f"Linked up with the scanner at {host}:{port}")


def do_disconnect():
    with STATE["lock"]:
        if STATE["conn"]:
            try:
                STATE["conn"].close()
            except OSError:
                pass
        STATE["conn"] = None
    log_event("sys", b"", "Disconnected from the scanner")


def send_and_collect(req: bytes, request_label="Sent a request to the scanner", timeout=1.5):
    with STATE["lock"]:
        conn = STATE["conn"]
    if not conn:
        raise RuntimeError("not connected to reader")
    # Two background loops (heartbeat, auto-forward) plus manual dashboard
    # clicks can all try to talk to the reader at once — the socket is a
    # single request/response channel, so only one conversation may be in
    # flight at a time or replies would interleave and corrupt parsing.
    with IO_LOCK:
        conn.sendall(req)
        log_event("tx", req, request_label)
        buf, frames, deadline = b"", [], time.time() + timeout
        conn.settimeout(timeout)
        while time.time() < deadline:
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
            while True:
                frame, buf = parse_frame(buf)
                if frame is None:
                    break
                frames.append(frame)
                log_event("rx", frame["raw"], describe_frame("rx", frame))
    return frames


def do_inventory():
    req = build_request(STATE["com_adr"], 0xFE, 0x01, bytes([0x00]))
    frames = send_and_collect(req, "Asked the scanner: what tags are nearby?")
    tags = []
    for f in frames:
        d = f["data"]
        if len(d) >= 10:  # status(1) + dsfid(1) + uid(8)
            uid_hex = d[2:10].hex()
            entry = TAGS.setdefault(uid_hex, {"uid": uid_hex, "dsfid": d[1], "count": 0})
            entry["count"] += 1
            entry["last_seen"] = time.time()
            tags.append(entry)
    return tags


def do_reader_info():
    req = build_request(STATE["com_adr"], 0x78, 0x00)
    frames = send_and_collect(req, "Asked the scanner to identify itself")
    if not frames:
        raise TimeoutError("no response from reader")
    return frames[0]["data"][1:].decode("utf-8", errors="replace")


# Python's default "Python-urllib/x.y" User-Agent gets blocked outright by
# Cloudflare and similar WAFs/bot-protection as a suspicious client (seen in
# practice as Cloudflare error code 1010) — a normal browser-looking one
# avoids that, independent of whether the credentials are correct.
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _request_headers(extra=None, use_auth=True):
    headers = {"User-Agent": _BROWSER_USER_AGENT}
    headers.update(extra or {})
    if use_auth and STATE["api_auth_value"]:
        headers[STATE["api_auth_header"] or "Authorization"] = STATE["api_auth_value"]
    return headers


def proxy_get(url, use_auth=True):
    req = urllib.request.Request(url, method="GET", headers=_request_headers(use_auth=use_auth))
    with urllib.request.urlopen(req, timeout=6) as resp:
        body = resp.read(4096)
        return {"status": resp.status, "headers": dict(resp.headers), "body": body.decode("utf-8", errors="replace")}


def proxy_post(url, payload, use_auth=True):
    data = json.dumps(payload).encode()
    headers = _request_headers({"Content-Type": STATE["api_content_type"] or "application/json"}, use_auth=use_auth)
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=6) as resp:
        body = resp.read(4096)
        return {"status": resp.status, "headers": dict(resp.headers), "body": body.decode("utf-8", errors="replace")}


def _classify_url_error(exc: Exception) -> str:
    """Translate a raw network exception into a plain-English reason."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 401 or exc.code == 403:
            return f"Server rejected the request (HTTP {exc.code}) — check the Authorization value"
        if 500 <= exc.code < 600:
            return f"Server had an internal error (HTTP {exc.code}) — problem on their side, not yours"
        return f"Server responded with HTTP {exc.code}: {exc.reason}"
    if isinstance(exc, urllib.error.URLError):
        reason = str(exc.reason)
        if "Name or service not known" in reason or "nodename nor servname" in reason:
            return "Cannot find that address — check the URL for typos"
        if "Connection refused" in reason:
            return "Connection refused — server is reachable but nothing is listening on that port"
        if "timed out" in reason:
            return "No response — check your internet connection or firewall"
        return f"Could not reach the server: {reason}"
    return f"Unexpected error: {exc}"


def check_reader_link() -> dict:
    """Diagnostic: is the gate reader actually responding right now?"""
    with STATE["lock"]:
        connected = STATE["conn"] is not None
    if not connected:
        return {"ok": False, "label": "Reader link", "detail": "Not connected — click Connect, or check the Ethernet cable/power to the reader."}
    try:
        info = do_reader_info()
        STATE["last_ping_ok"], STATE["last_ping_ts"], STATE["last_ping_error"] = True, time.time(), None
        return {"ok": True, "label": "Reader link", "detail": f"Responding normally ({info or 'no info string'})."}
    except Exception as e:
        STATE["last_ping_ok"], STATE["last_ping_ts"], STATE["last_ping_error"] = False, time.time(), str(e)
        log_event("sys", b"", f"⚠ Reader stopped responding — possible cable/power disconnect ({e})")
        return {"ok": False, "label": "Reader link", "detail": f"Was connected but isn't responding — check the Ethernet cable, antenna, and reader power. ({e})"}


def check_eventzflow() -> dict:
    if not STATE["api_url"]:
        return {"ok": False, "label": "EventzFlow connection", "detail": "No API URL configured yet."}
    try:
        result = proxy_get(STATE["api_url"])
        return {"ok": True, "label": "EventzFlow connection", "detail": f"Reachable — server responded with HTTP {result['status']}."}
    except Exception as e:
        return {"ok": False, "label": "EventzFlow connection", "detail": _classify_url_error(e)}


def check_encoder() -> dict:
    url = STATE["encoder_url"].rstrip("/") + "/status"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            body = json.loads(resp.read().decode())
        if body.get("device_present"):
            return {"ok": True, "label": "Encoder", "detail": f"Encoder helper reachable, device present: {body.get('model', 'unknown model')}."}
        return {"ok": False, "label": "Encoder", "detail": "Encoder helper is running, but no USB encoder device detected — check the USB cable."}
    except Exception:
        return {
            "ok": False,
            "label": "Encoder",
            "detail": (
                f"Cannot reach the encoder helper at {STATE['encoder_url']}. "
                "This is expected if you're not running it on the Windows registration PC yet."
            ),
        }


def run_diagnostics() -> list:
    return [check_reader_link(), check_eventzflow(), check_encoder()]


def forward_tag(tag: dict):
    """POST a single new tag sighting to the configured API URL."""
    payload = {"uid": tag["uid"], "dsfid": tag["dsfid"], "seen_at": time.time()}
    try:
        result = proxy_post(STATE["api_url"], payload)
        STATE["forwarded_count"] += 1
        log_event("api", b"", f"Auto-forwarded tag {tag['uid']} — server responded with status {result['status']}")
    except Exception as e:
        log_event("api", b"", f"⚠ Failed to auto-forward tag {tag['uid']}: {_classify_url_error(e)}")


def auto_forward_loop():
    while True:
        time.sleep(AUTO_FORWARD_POLL)
        if not STATE["auto_forward"] or not STATE["api_url"]:
            continue
        with STATE["lock"]:
            connected = STATE["conn"] is not None
        if not connected:
            continue
        try:
            tags = do_inventory()
        except Exception:
            continue  # reader hiccup — heartbeat_loop already reports link problems

        now = time.time()
        for tag in tags:
            uid = tag["uid"]
            last = STATE["last_forwarded"].get(uid)
            if last is not None and (now - last) < STATE["dedup_seconds"]:
                STATE["suppressed_count"] += 1
                continue
            STATE["last_forwarded"][uid] = now
            forward_tag(tag)


def heartbeat_loop():
    while True:
        time.sleep(HEARTBEAT_INTERVAL)
        with STATE["lock"]:
            connected = STATE["conn"] is not None
        if connected:
            try:
                do_reader_info()
                STATE["last_ping_ok"], STATE["last_ping_ts"], STATE["last_ping_error"] = True, time.time(), None
            except Exception as e:
                if STATE["last_ping_ok"] is not False:  # only log the transition, not every tick
                    log_event("sys", b"", f"⚠ Lost contact with the reader — check the cable/power ({e})")
                STATE["last_ping_ok"], STATE["last_ping_ts"], STATE["last_ping_error"] = False, time.time(), str(e)


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            path = os.path.join(os.path.dirname(__file__), "index.html")
            with open(path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            with STATE["lock"]:
                connected = STATE["conn"] is not None
            self._json({
                "connected": connected,
                "host": STATE["host"],
                "port": STATE["port"],
                "com_adr": STATE["com_adr"],
                "last_ping_ok": STATE["last_ping_ok"],
                "last_ping_ts": STATE["last_ping_ts"],
            })
        elif self.path == "/api/log":
            self._json(list(LOG))
        elif self.path == "/api/tags":
            self._json(list(TAGS.values()))
        elif self.path == "/api/settings":
            self._json({
                "com_adr": STATE["com_adr"],
                "api_url": STATE["api_url"],
                "api_auth_header": STATE["api_auth_header"],
                "api_auth_value": STATE["api_auth_value"],
                "api_content_type": STATE["api_content_type"],
                "encoder_url": STATE["encoder_url"],
                "auto_forward": STATE["auto_forward"],
                "dedup_seconds": STATE["dedup_seconds"],
            })
        elif self.path == "/api/forward-stats":
            self._json({
                "auto_forward": STATE["auto_forward"],
                "dedup_seconds": STATE["dedup_seconds"],
                "forwarded_count": STATE["forwarded_count"],
                "suppressed_count": STATE["suppressed_count"],
                "unique_tags_tracked": len(STATE["last_forwarded"]),
            })
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        try:
            body = self._body()
            if self.path == "/api/connect":
                do_connect(body.get("host", STATE["host"]), int(body.get("port", STATE["port"])))
                self._json({"ok": True})
            elif self.path == "/api/disconnect":
                do_disconnect()
                self._json({"ok": True})
            elif self.path == "/api/settings":
                if "com_adr" in body:
                    v = body["com_adr"]
                    STATE["com_adr"] = int(v, 0) if isinstance(v, str) else int(v)
                for key in ("api_url", "api_auth_header", "api_auth_value", "api_content_type", "encoder_url"):
                    if key in body:
                        STATE[key] = body[key]
                if "auto_forward" in body:
                    STATE["auto_forward"] = bool(body["auto_forward"])
                    log_event("sys", b"", "Auto-forward turned ON — new tag reads will be pushed to your server automatically" if STATE["auto_forward"] else "Auto-forward turned OFF")
                if "dedup_seconds" in body:
                    STATE["dedup_seconds"] = float(body["dedup_seconds"])
                self._json({"ok": True})
            elif self.path == "/api/inventory":
                tags = do_inventory()
                self._json({"ok": True, "tags": tags})
            elif self.path == "/api/info":
                info = do_reader_info()
                self._json({"ok": True, "info": info})
            elif self.path == "/api/test-get":
                STATE["api_url"] = body["url"]
                result = proxy_get(body["url"])
                log_event("api", b"", f"Checked your server ({body['url']}) — it responded with status {result['status']}")
                self._json({"ok": True, "result": result})
            elif self.path == "/api/test-post":
                STATE["api_url"] = body["url"]
                result = proxy_post(body["url"], body.get("payload", {}))
                log_event("api", b"", f"Sent tag data to your server ({body['url']}) — it responded with status {result['status']}")
                self._json({"ok": True, "result": result})
            elif self.path == "/api/diagnostics":
                results = run_diagnostics()
                log_event("sys", b"", "Ran a full diagnostic check")
                self._json({"ok": True, "results": results})
            elif self.path == "/api/encode":
                try:
                    url = STATE["encoder_url"].rstrip("/") + "/encode"
                    req = urllib.request.Request(
                        url, data=json.dumps(body).encode(),
                        method="POST", headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=6) as resp:
                        result = json.loads(resp.read().decode())
                    log_event("sys", b"", f"Encode request sent to helper — {result.get('detail', 'done')}")
                    self._json({"ok": True, "result": result})
                except Exception as e:
                    self._json({"ok": False, "error": f"Encoder helper unreachable at {STATE['encoder_url']} ({e}). Run encoder_service.py on the Windows registration PC first."})
            else:
                self._json({"error": "not found"}, 404)
        except urllib.error.HTTPError as e:
            self._json({"ok": False, "error": f"HTTP {e.code}: {e.reason}"})
        except Exception as e:
            self._json({"ok": False, "error": str(e)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5050)
    args = ap.parse_args()
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    threading.Thread(target=auto_forward_loop, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Dashboard running at http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
