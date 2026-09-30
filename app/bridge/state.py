"""Shared runtime state + operator event log.

One Runtime instance per process. Everything the HTTP handlers and the
background loops share lives here, guarded by locks. The event log is the
operator-facing history ("what just happened at my desk/gate") — capped,
newest first, rendered by the console UI.
"""
from __future__ import annotations

import threading
import time
from collections import deque

from .client import RfidClient
from .config import Config
from .printer import Printer

LOG_CAP = 500
PASSAGE_CAP = 200   # recent gate passages shown in the UI


class Runtime:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.lock = threading.Lock()
        self.log: deque = deque(maxlen=LOG_CAP)
        self.passages: deque = deque(maxlen=PASSAGE_CAP)
        # Gate connection + reader state.
        self.gate_conn = None          # socket while connected
        self.gate_connected = False
        self.gate_last_error = None
        self.gate_stop = threading.Event()
        # Counters for the console header.
        self.headcount_in = 0
        self.headcount_out = 0
        self.forwarded_count = 0
        self.failed_count = 0
        self.last_forwarded: dict = {}  # uid hex -> ts (dedup window)
        # Last backend heartbeat answer (event settings).
        self.event_settings = None
        self.last_heartbeat_ok = None
        self.last_heartbeat_error = None

    # ---- derived clients -------------------------------------------------

    def client(self) -> RfidClient:
        return RfidClient(
            api_base=self.config.get("api_base", ""),
            api_key=self.config.get("api_key", ""),
            station_id=self.config.get("station_id", ""),
        )

    def printer(self) -> Printer:
        return Printer(self.config.get("printer_url", ""))

    # ---- operator log ----------------------------------------------------

    def event(self, kind: str, message: str):
        """kind: desk | gate | api | print | sys | err"""
        entry = {"ts": time.time(), "kind": kind, "message": message}
        with self.lock:
            self.log.appendleft(entry)

    def log_since(self, cursor: float | None) -> tuple[list, float]:
        with self.lock:
            items = list(self.log)
        if cursor:
            items = [e for e in items if e["ts"] > cursor]
        return items, time.time()

    def passage(self, p: dict):
        with self.lock:
            self.passages.appendleft(p)

    def snapshot(self) -> dict:
        """Everything the console UI polls every few seconds."""
        with self.lock:
            return {
                "gate_connected": self.gate_connected,
                "gate_last_error": self.gate_last_error,
                "headcount_in": self.headcount_in,
                "headcount_out": self.headcount_out,
                "forwarded_count": self.forwarded_count,
                "failed_count": self.failed_count,
                "passages": list(self.passages)[:50],
                "event_settings": self.event_settings,
                "last_heartbeat_ok": self.last_heartbeat_ok,
                "last_heartbeat_error": self.last_heartbeat_error,
                "backend_configured": bool(self.config.get("api_base")
                                           and self.config.get("api_key")),
            }
