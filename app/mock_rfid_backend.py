#!/usr/bin/env python3
"""Mock EventzFlow RFID backend — implements the P5 device contract
(/v1/rfid/*) with the same rules as rfidex-mock, for offline demos and for
verifying the bridge end-to-end without touching production.

Rules implemented (same as the real backend):
  - Auth: any request to /v1/rfid/* needs an Authorization header.
  - desk_scans: first scan of a ticket → checked_in; later scans →
    already_checked_in. Idempotent on operation_id (replay returns the
    original stored response verbatim).
  - search: name LIKE %q% / email exact / phone digits, paid only, max 10,
    email/phone masked in responses.
  - bindings: one tag → one ticket; binding a tag bound elsewhere → 409
    uid_bound_elsewhere (unless replace=true).
  - observations: idempotent on delivery_id; unknown tag → outcome
    unknown_tag; entry for a not-checked-in ticket → not_checked_in
    (with require_check_in on).

Run:
    python3 mock_rfid_backend.py --port 9100 --api-key demo-key
Seeded demo tickets are printed at startup.
"""
import argparse
import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE = {
    "api_key": "demo-key",
    "event": {"event_id": 1, "name": "Demo Conference 2026",
              "rfid_mode": "bind", "require_check_in": True},
    "tickets": {},      # public_id -> ticket dict
    "ops": {},          # operation_id -> stored desk scan response
    "deliveries": {},   # delivery_id -> stored observation result
    "bindings": {},     # tag_key (uid hex) -> binding dict
}


def _uuid():
    return str(uuid.uuid4())


def _iso(ts=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts or time.time()))


def seed():
    demo = [
        ("Ahmad Bin Ali", "Delegate", "ahmad@example.com", "0123456789"),
        ("Siti Nurhaliza", "VIP", "siti@example.com", "0198765432"),
        ("John Tan", "Delegate", "john.tan@example.com", "0161122334"),
        ("Priya Raman", "Speaker", "priya@example.com", "0175566778"),
        ("Lee Chong Wei", "VIP", "lcw@example.com", "0129988776"),
        ("Maria Santos", "Delegate", "maria@example.com", "0134433221"),
    ]
    for name, ttype, email, phone in demo:
        pid = _uuid()
        STATE["tickets"][pid] = {
            "public_id": pid, "name": name, "ticket_type": ttype,
            "valid": True, "checked_in": False, "checked_in_at": None,
            "email": email, "phone": phone,
        }
    return list(STATE["tickets"].values())


def _mask_email(email):
    local, _, domain = email.partition("@")
    return (local[:2] + "***@" + domain) if domain else "***"


def _mask_phone(phone):
    return "•••• " + phone[-4:] if len(phone) >= 4 else "••••"


def _summary(t):
    return {"public_id": t["public_id"], "name": t["name"],
            "ticket_type": t["ticket_type"], "valid": t["valid"],
            "checked_in": t["checked_in"]}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth_ok(self):
        return self.headers.get("Authorization") == STATE["api_key"]

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode())
        except json.JSONDecodeError:
            return {}

    def _deny(self):
        self._json({"error": "unauthorized", "message": "Missing or wrong API key."}, 401)

    # ------------------------------------------------------------------

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        q = parse_qs(parsed.query)
        if parsed.path == "/":
            rows = "".join(
                f"<tr><td style='font-family:monospace'>{t['public_id']}</td>"
                f"<td>{t['name']}</td><td>{t['ticket_type']}</td>"
                f"<td>{'✓' if t['checked_in'] else ''}</td></tr>"
                for t in STATE["tickets"].values())
            page = (f"<html><body style='font-family:sans-serif;background:#0b0e14;color:#e6eaf2;padding:24px'>"
                    f"<h1>Mock RFID backend</h1><p>{len(STATE['tickets'])} tickets · "
                    f"{len(STATE['bindings'])} bindings</p>"
                    f"<table cellpadding='8'>{rows}</table></body></html>")
            data = page.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if not self._auth_ok():
            return self._deny()
        if parsed.path == "/v1/rfid/tickets/search":
            self._search(q.get("by", ["name"])[0], q.get("q", [""])[0])
        elif parsed.path == "/v1/rfid/bindings/lookup":
            tag_key = q.get("tag_key", [""])[0].upper()
            b = STATE["bindings"].get(tag_key)
            holder = _summary(STATE["tickets"][b["public_id"]]) if b else None
            self._json({"binding": b, "holder": holder})
        elif parsed.path == "/v1/rfid/cache":
            self._json({
                "tickets": [_summary(t) for t in STATE["tickets"].values()],
                "bindings": list(STATE["bindings"].values()),
                "revoked_tag_keys": [], "server_time": _iso(),
            })
        else:
            self._json({"error": "malformed", "message": "not found"}, 404)

    def do_POST(self):
        from urllib.parse import urlparse
        if not self._auth_ok():
            return self._deny()
        body = self._body()
        path = urlparse(self.path).path
        if path == "/v1/rfid/stations/heartbeat":
            self._json({"event": STATE["event"], "uid_rule": "as_is",
                        "server_time": _iso()})
        elif path == "/v1/rfid/desk_scans":
            self._desk_scan(body)
        elif path == "/v1/rfid/bindings":
            self._bind(body)
        elif path == "/v1/rfid/observations":
            self._observations(body)
        else:
            self._json({"error": "malformed", "message": "not found"}, 404)

    # ------------------------------------------------------------------

    def _search(self, by, q):
        qn = " ".join(q.lower().split())
        out = []
        for t in STATE["tickets"].values():
            if not t["valid"]:
                continue
            if by == "name" and len(qn) >= 2 and qn in t["name"].lower():
                out.append(t)
            elif by == "email" and qn and t["email"].lower() == qn:
                out.append(t)
            elif by == "phone":
                digits = "".join(c for c in q if c.isdigit())
                for prefix in ("60", "0"):
                    if digits.startswith(prefix):
                        digits = digits[len(prefix):]
                        break
                tdigits = "".join(c for c in t["phone"] if c.isdigit())
                if tdigits.startswith("0"):
                    tdigits = tdigits[1:]
                if len(digits) >= 4 and digits in tdigits:
                    out.append(t)
        items = [{
            "public_id": t["public_id"], "name": t["name"],
            "ticket_type": t["ticket_type"], "valid": t["valid"],
            "checked_in": t["checked_in"], "checked_in_at": t["checked_in_at"],
            "email_hint": _mask_email(t["email"]),
            "phone_hint": _mask_phone(t["phone"]),
        } for t in out[:10]]
        self._json({"tickets": items})

    def _desk_scan(self, body):
        op = body.get("operation_id")
        if op in STATE["ops"]:
            return self._json(STATE["ops"][op])   # idempotent replay
        t = STATE["tickets"].get(body.get("public_id"))
        if not t:
            return self._json({"error": "ticket_not_found",
                               "message": "No ticket with that QR code."}, 404)
        if not t["valid"]:
            return self._json({"error": "ticket_unpaid",
                               "message": "Ticket is not paid."}, 422)
        first = not t["checked_in"]
        if first:
            t["checked_in"] = True
            t["checked_in_at"] = _iso()
        binding = next((b for b in STATE["bindings"].values()
                        if b["public_id"] == t["public_id"]), None)
        resp = {
            "ticket": _summary(t), "binding": binding,
            "check_in": {
                "result": "checked_in" if first else "already_checked_in",
                "checked_in_at": t["checked_in_at"],
            },
        }
        if op:
            STATE["ops"][op] = resp
        self._json(resp)

    def _bind(self, body):
        uid = (body.get("uid_raw_hex") or "").upper()
        t = STATE["tickets"].get(body.get("public_id"))
        if not t:
            return self._json({"error": "ticket_not_found",
                               "message": "No such ticket."}, 404)
        existing = STATE["bindings"].get(uid)
        if existing and existing["public_id"] != t["public_id"] and not body.get("replace"):
            return self._json({
                "error": "uid_bound_elsewhere",
                "message": "That sticker is already linked to another guest.",
                "holder": _summary(STATE["tickets"][existing["public_id"]]),
                "binding": existing}, 409)
        binding = {
            "id": len(STATE["bindings"]) + 1, "public_id": t["public_id"],
            "protocol": body.get("protocol", "iso15693"),
            "uid_raw_hex": uid, "tag_key": uid,
            "mode": body.get("mode", "bind"),
        }
        revoked = []
        if existing:
            revoked.append(existing)
        STATE["bindings"][uid] = binding
        self._json({"binding": binding, "revoked": revoked})

    def _observations(self, body):
        items = body.get("observations") or []
        if len(items) > 50:
            return self._json({"error": "batch_too_large",
                               "message": "At most 50 per batch."}, 422)
        results = []
        for it in items:
            did = it.get("delivery_id")
            if did in STATE["deliveries"]:
                results.append(STATE["deliveries"][did])
                continue
            uid = (it.get("uid_raw_hex") or "").upper()
            binding = STATE["bindings"].get(uid)
            if not binding:
                result = {"delivery_id": did, "outcome": "unknown_tag",
                          "anomalies": [], "display": {"reason": "No sticker link"}}
            else:
                t = STATE["tickets"][binding["public_id"]]
                anomalies = []
                outcome = "accepted"
                if not t["checked_in"] and STATE["event"]["require_check_in"]:
                    outcome = "not_checked_in"
                    anomalies.append("entered_without_check_in")
                result = {"delivery_id": did, "outcome": outcome,
                          "anomalies": anomalies,
                          "display": {"name": t["name"],
                                      "ticket_type": t["ticket_type"]}}
            if did:
                STATE["deliveries"][did] = result
            results.append(result)
        self._json({"results": results})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9100)
    ap.add_argument("--api-key", default="demo-key")
    args = ap.parse_args()
    STATE["api_key"] = args.api_key
    tickets = seed()
    print(f"Mock RFID backend on http://127.0.0.1:{args.port}  (API key: {args.api_key})")
    print("Seeded tickets (scan these as QR public_id):")
    for t in tickets:
        print(f"  {t['public_id']}  {t['name']} ({t['ticket_type']})")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
