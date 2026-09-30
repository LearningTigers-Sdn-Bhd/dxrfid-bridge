"""Gate flow — inventory → dedup → observation batch → headcount.

Reuses the proven TCP exchange pattern from the old server.py (connect,
heartbeat ping, inventory poll) but posts contract-shaped observations
(POST /v1/rfid/observations) instead of a generic payload.

Each sighting gets a delivery_id minted ONCE and kept in a small retry
buffer: if a batch fails to send, the same delivery_ids go out again on
the next attempt, so a retried delivery is idempotent on the backend
instead of becoming a second passage. Buffer is in-memory (online-first);
durable replay is phase 2b.

Headcount is local display math from server outcomes: accepted entry
increments in-count, accepted exit increments out-count. Late binding /
anomalies arrive per-observation in the response and land in the event log.
"""
from __future__ import annotations

import datetime
import socket
import threading
import time
import uuid

from . import protocol
from .client import ApiError

PING_INTERVAL = 5.0


def _utcnow_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class GateFlow:
    def __init__(self, runtime):
        self.rt = runtime
        self._sock: socket.socket | None = None
        self._io_lock = threading.Lock()   # one command in flight at a time
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pending: dict[str, dict] = {}  # delivery_id -> ObservationItem

    # ---- lifecycle -------------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="gate-loop")
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._close()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _close(self):
        with self._io_lock:
            if self._sock:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
        with self.rt.lock:
            self.rt.gate_connected = False

    # ---- wire exchange ----------------------------------------------------

    def _connect(self, host: str, port: int):
        sock = socket.create_connection((host, port), timeout=4)
        sock.settimeout(2.0)
        with self._io_lock:
            self._sock = sock
        with self.rt.lock:
            self.rt.gate_connected = True
            self.rt.gate_last_error = None
        self.rt.event("gate", f"Linked up with the gate at {host}:{port}")

    def _exchange(self, frame: bytes, collect_for: float = 1.0) -> list[dict]:
        """Send one frame, collect response frames for a short window."""
        with self._io_lock:
            if not self._sock:
                raise OSError("not connected")
            self._sock.sendall(frame)
            frames, buf = [], b""
            deadline = time.time() + collect_for
            while time.time() < deadline:
                try:
                    chunk = self._sock.recv(4096)
                    if not chunk:
                        raise OSError("gate closed the connection")
                    buf += chunk
                except socket.timeout:
                    break
                while True:
                    parsed, buf = protocol.parse_frame(buf)
                    if parsed is None:
                        break
                    frames.append(parsed)
        return frames

    def _inventory(self, com_adr: int) -> list[dict]:
        req = protocol.build_frame(com_adr, *protocol.CMD_INVENTORY,
                                   bytes([0x00]))
        tags = []
        for f in self._exchange(req, collect_for=1.2):
            if (f["cmd_type"], f["cmd_code"]) != protocol.CMD_INVENTORY:
                continue
            if not f["crc_ok"]:
                self.rt.event("err", "Gate frame failed CRC — cabling noise?")
                continue
            tag = protocol.parse_inventory_tag(f["data"])
            if tag:
                tags.append(tag)
        return tags

    # ---- observation pipeline ---------------------------------------------

    def _dedup_ok(self, uid_hex: str, window: float) -> bool:
        now = time.time()
        last = self.rt.last_forwarded.get(uid_hex)
        if last is not None and now - last < window:
            return False
        self.rt.last_forwarded[uid_hex] = now
        # keep the map bounded
        if len(self.rt.last_forwarded) > 2000:
            cutoff = now - max(window, 60)
            self.rt.last_forwarded = {
                k: v for k, v in self.rt.last_forwarded.items() if v > cutoff}
        return True

    def _handle_tags(self, tags: list[dict]):
        cfg = self.rt.config
        role = cfg.get("gate_role", "entry")
        dedup = float(cfg.get("dedup_seconds", 10.0))
        for tag in tags:
            uid_hex = tag["uid_hex"]
            if not self._dedup_ok(uid_hex, dedup):
                continue
            item = {
                "delivery_id": str(uuid.uuid4()),
                "role": role,
                "protocol": "iso15693",
                "uid_raw_hex": uid_hex,
                "payload_hex": None,
                "device_direction_raw": None,
                "device_time_raw_hex": None,
                "device_record_seq": None,
                "flags_raw": {},
                "captured_at": _utcnow_iso(),
            }
            self._pending[item["delivery_id"]] = item
        self._flush()

    def _flush(self):
        if not self._pending:
            return
        batch = list(self._pending.values())[:50]
        try:
            resp = self.rt.client().observations(batch)
        except ApiError as e:
            with self.rt.lock:
                self.rt.failed_count += len(batch)
            # Keep the same delivery_ids — the retry is idempotent server-side.
            self.rt.event("err", f"Could not reach EventzFlow — "
                                 f"{len(batch)} sighting(s) will retry. ({e.message})")
            return
        results = {r.get("delivery_id"): r for r in resp.get("results", [])}
        role = self.rt.config.get("gate_role", "entry")
        for item in batch:
            did = item["delivery_id"]
            result = results.get(did)
            self._pending.pop(did, None)
            outcome = (result or {}).get("outcome", "?")
            anomalies = (result or {}).get("anomalies") or []
            display = (result or {}).get("display") or {}
            with self.rt.lock:
                self.rt.forwarded_count += 1
                if outcome == "accepted":
                    if role == "entry":
                        self.rt.headcount_in += 1
                    else:
                        self.rt.headcount_out += 1
            label = display.get("name") or item["uid_raw_hex"]
            if outcome == "accepted":
                self.rt.event("gate", f"→ {label} ({role})")
            else:
                self.rt.event("gate", f"→ {label}: {outcome.replace('_', ' ')}")
            for a in anomalies:
                self.rt.event("err", f"Anomaly on {label}: {a.replace('_', ' ')}")
            self.rt.passage({
                "ts": time.time(), "uid": item["uid_raw_hex"],
                "role": role, "outcome": outcome,
                "name": display.get("name"),
                "ticket_type": display.get("ticket_type"),
                "anomalies": anomalies,
            })

    # ---- main loop ----------------------------------------------------------

    def _run(self):
        cfg = self.rt.config
        host = cfg.get("gate_host", "192.168.1.222")
        port = int(cfg.get("gate_port", 6688))
        com_adr = int(cfg.get("com_adr", 0))
        poll = max(0.5, float(cfg.get("inventory_poll_seconds", 2.0)))
        while not self._stop.is_set():
            try:
                self._connect(host, port)
                while not self._stop.is_set():
                    tags = self._inventory(com_adr)
                    if tags and cfg.get("auto_forward", True):
                        self._handle_tags(tags)
                    else:
                        self._flush()  # retry pending even when forwarding off
                    self._stop.wait(poll)
            except (OSError, TimeoutError) as e:
                with self.rt.lock:
                    self.rt.gate_connected = False
                    self.rt.gate_last_error = str(e)
                self.rt.event("err", f"Gate link down: {e} — retrying in 5s.")
                self._close()
                self._stop.wait(5.0)
        self._close()
