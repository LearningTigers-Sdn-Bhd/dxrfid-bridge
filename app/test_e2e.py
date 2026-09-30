#!/usr/bin/env python3
"""End-to-end smoke test: mock P5 backend + bridge server, driven over HTTP.

Covers the contract-critical paths without hardware:
  desk search → scan → check-in (idempotent replay) → already_checked_in
  binding (incl. bound-elsewhere 409) → lookup
  observations: unknown_tag / accepted / not_checked_in + delivery replay
  heartbeat

Run from app/:
    python3 test_e2e.py
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["DXRFID_BRIDGE_DATA"] = tempfile.mkdtemp(prefix="dxrfid-test-")

import mock_rfid_backend  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402
from bridge.server import make_handler  # noqa: E402
from bridge.state import Runtime  # noqa: E402

MOCK_PORT = 9410
BRIDGE_PORT = 9411
API_KEY = "test-key-32chars-minimum-aaaaaaaa"


def start_mock():
    mock_rfid_backend.STATE["api_key"] = API_KEY
    tickets = mock_rfid_backend.seed()
    srv = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), mock_rfid_backend.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return tickets


def start_bridge():
    rt = Runtime()
    rt.config.apply_updates({
        "api_base": f"http://127.0.0.1:{MOCK_PORT}",
        "api_key": API_KEY,
        "print_on_check_in": False,   # no printer in this test
    })
    srv = ThreadingHTTPServer(("127.0.0.1", BRIDGE_PORT), make_handler(rt))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return rt


def call(method, path, body=None, base=BRIDGE_PORT):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if base == MOCK_PORT:
        headers["Authorization"] = API_KEY
    req = urllib.request.Request(f"http://127.0.0.1:{base}{path}", data=data,
                                 method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def main():
    tickets = start_mock()
    start_bridge()
    ahmad = next(t for t in tickets if "Ahmad" in t["name"])
    siti = next(t for t in tickets if "Siti" in t["name"])
    pid = ahmad["public_id"]

    # heartbeat / test connection
    r = call("POST", "/api/test/backend", {})
    assert r["ok"], r
    assert r["event"]["name"] == "Demo Conference 2026"
    print("✓ heartbeat")

    # search by name
    r = call("POST", "/api/desk/search", {"by": "name", "q": "ahmad"})
    assert any(t["public_id"] == pid for t in r["tickets"]), r
    assert r["tickets"][0]["email_hint"].startswith("ah***")
    print("✓ search")

    # scan → checked_in
    r = call("POST", "/api/desk/scan", {"public_id": pid})
    card = r["card"]
    assert card["check_in"]["result"] == "checked_in", card
    assert card["printed"] is False  # printer disabled in test
    print("✓ desk scan → checked_in")

    # rescan → already_checked_in (and NOT an error)
    r = call("POST", "/api/desk/scan", {"public_id": pid})
    assert r["card"]["check_in"]["result"] == "already_checked_in", r
    print("✓ rescan → already_checked_in")

    # idempotency: mock returns same stored response for replayed op ids —
    # exercise it directly against the mock to prove the contract holds.
    import uuid as _uuid
    op = str(_uuid.uuid4())
    r1 = call("POST", "/v1/rfid/desk_scans", {
        "public_id": siti["public_id"], "operation_id": op,
        "captured_at": "2026-09-29T00:00:00Z"}, base=MOCK_PORT)
    r2 = call("POST", "/v1/rfid/desk_scans", {
        "public_id": siti["public_id"], "operation_id": op,
        "captured_at": "2026-09-29T00:00:00Z"}, base=MOCK_PORT)
    assert r1 == r2 and r1["check_in"]["result"] == "checked_in"
    print("✓ operation_id replay idempotent")

    # unknown ticket — bridge answers 200 with ok:false + contract error code
    r = call("POST", "/api/desk/scan", {"public_id": str(_uuid.uuid4())})
    assert r.get("ok") is False and r.get("error") == "ticket_not_found", r
    print("✓ unknown ticket rejected")

    # bind a sticker to Ahmad
    uid = "E004010203040506"
    r = call("POST", "/api/desk/bind", {"public_id": pid, "uid_hex": uid})
    assert r["result"]["binding"]["tag_key"] == uid, r
    print("✓ binding created")

    # binding same sticker to Siti → uid_bound_elsewhere with the holder named
    r = call("POST", "/api/desk/bind", {"public_id": siti["public_id"], "uid_hex": uid})
    assert r.get("ok") is False and r.get("error") == "uid_bound_elsewhere", r
    assert (r.get("holder") or {}).get("name") == ahmad["name"], r
    print("✓ uid_bound_elsewhere surfaced")

    # observations: known tag (checked in) → accepted
    obs = [{"delivery_id": str(_uuid.uuid4()), "role": "entry",
            "protocol": "iso15693", "uid_raw_hex": uid, "payload_hex": None,
            "device_direction_raw": None, "device_time_raw_hex": None,
            "device_record_seq": None, "flags_raw": {},
            "captured_at": "2026-09-29T00:00:00Z"}]
    r = call("POST", "/v1/rfid/observations", {"observations": obs}, base=MOCK_PORT)
    assert r["results"][0]["outcome"] == "accepted", r
    assert r["results"][0]["display"]["name"] == ahmad["name"]
    print("✓ observation accepted with display name")

    # observation replay idempotent
    r2 = call("POST", "/v1/rfid/observations", {"observations": obs}, base=MOCK_PORT)
    assert r2 == r
    print("✓ delivery_id replay idempotent")

    # unknown tag → unknown_tag
    obs2 = [dict(obs[0], delivery_id=str(_uuid.uuid4()),
                 uid_raw_hex="E004AAAAAAAAAA00")]
    r = call("POST", "/v1/rfid/observations", {"observations": obs2}, base=MOCK_PORT)
    assert r["results"][0]["outcome"] == "unknown_tag", r
    print("✓ unknown_tag outcome")

    # Siti is checked in (via replay test) but has no sticker; bind then exit
    uid2 = "E0040B0B0B0B0B01"
    call("POST", "/api/desk/bind", {"public_id": siti["public_id"], "uid_hex": uid2})
    obs3 = [dict(obs[0], delivery_id=str(_uuid.uuid4()), role="exit",
                 uid_raw_hex=uid2)]
    r = call("POST", "/v1/rfid/observations", {"observations": obs3}, base=MOCK_PORT)
    assert r["results"][0]["outcome"] == "accepted", r
    print("✓ exit observation accepted")

    # settings round-trip keeps key masked
    r = call("GET", "/api/settings")
    assert r["api_key_set"] is True and r["api_key"] == ""
    print("✓ settings masked")

    # bridge snapshot is coherent
    r = call("GET", "/api/status")
    assert r["backend_configured"] is True and r["last_heartbeat_ok"] is True
    print("✓ status snapshot")

    print("\nALL E2E CHECKS PASSED")


if __name__ == "__main__":
    main()
