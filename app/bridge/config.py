"""Persisted bridge configuration.

Lives in a per-user data dir so the frozen .exe never writes next to itself:

    Windows:  %LOCALAPPDATA%\\DXRFIDBridge\\config.json
    macOS:    ~/Library/Application Support/DXRFIDBridge/config.json
    Linux:    ~/.local/share/dxrfid-bridge/config.json

Save is atomic (write temp + os.replace) — a crash mid-write never leaves a
half JSON file, same rule as RfiDex's config.rs.
"""
from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
import threading
import uuid

_LOCK = threading.RLock()  # reentrant: load() calls save() on first run

DEFAULTS = {
    # Identity of this station on the EventzFlow backend.
    "station_name": "DXRFID Bridge",
    # "desk" or "gate" — a single bridge instance serves both roles in the UI,
    # but the backend wants one kind per station UUID; desk is the safe default.
    "station_kind": "desk",
    # Gate role reported in observations: "entry" or "exit".
    "gate_role": "entry",
    # EventzFlow backend.
    "api_base": "",            # e.g. https://eventzflow.com  (no trailing slash)
    "api_key": "",             # RFID-scope API key, sent as Authorization header
    # Local event-printing app (direct mode, loopback only).
    "printer_url": "http://127.0.0.1:8000",
    # Gate reader over TCP.
    "gate_host": "192.168.1.222",
    "gate_port": 6688,
    "com_adr": 0,
    # USB desk encoder helper — embedded in this process when possible, but a
    # remote helper URL is still supported (encoder on another Windows PC).
    "encoder_url": "http://127.0.0.1:7000",
    "encoder_model": "D5200",
    # Gate behaviour.
    "dedup_seconds": 10.0,
    "inventory_poll_seconds": 2.0,
    "auto_forward": True,
    # Desk behaviour.
    "print_on_check_in": True,
}


def data_dir() -> str:
    """Per-user writable directory for config (and later, SQLite)."""
    override = os.environ.get("DXRFID_BRIDGE_DATA")
    if override:
        return override
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return os.path.join(base, "DXRFIDBridge")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/DXRFIDBridge")
    return os.path.expanduser("~/.local/share/dxrfid-bridge")


class Config:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(data_dir(), "config.json")
        self._values = dict(DEFAULTS)
        # Stable station UUID, generated once on first run and persisted.
        self._values.setdefault("station_id", "")
        self.load()

    def load(self):
        with _LOCK:
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                if isinstance(stored, dict):
                    self._values.update(stored)
            except FileNotFoundError:
                pass
            except (json.JSONDecodeError, OSError):
                # Corrupt config: keep defaults rather than crash the desk.
                pass
            if not self._values.get("station_id"):
                self._values["station_id"] = str(uuid.uuid4())
                self.save()

    def save(self):
        with _LOCK:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self._values, f, indent=2, sort_keys=True)
                os.replace(tmp, self.path)
            except OSError:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise

    def get(self, key, default=None):
        with _LOCK:
            return self._values.get(key, default)

    def update(self, **kwargs):
        with _LOCK:
            for k, v in kwargs.items():
                if k in DEFAULTS or k == "station_id":
                    self._values[k] = v
        self.save()

    def public_view(self) -> dict:
        """Settings shown in the UI. API key is masked — write-only field."""
        with _LOCK:
            view = dict(self._values)
        key = view.get("api_key") or ""
        view["api_key"] = ""
        view["api_key_set"] = bool(key)
        view["api_key_hint"] = (key[:4] + "…" + key[-4:]) if len(key) > 8 else ("set" if key else "")
        view["data_dir"] = data_dir()
        view["platform"] = platform.system()
        return view

    def apply_updates(self, body: dict):
        """Apply a settings form post. Empty api_key keeps the stored one."""
        updates = {}
        for key in DEFAULTS:
            if key not in body:
                continue
            if key == "api_key" and not body[key]:
                continue
            updates[key] = body[key]
        # Coerce the typed fields; a bad form value must not poison the file.
        if "gate_port" in updates:
            updates["gate_port"] = int(updates["gate_port"])
        if "com_adr" in updates:
            v = updates["com_adr"]
            updates["com_adr"] = int(v, 0) if isinstance(v, str) else int(v)
        if "dedup_seconds" in updates:
            updates["dedup_seconds"] = float(updates["dedup_seconds"])
        if "inventory_poll_seconds" in updates:
            updates["inventory_poll_seconds"] = max(0.5, float(updates["inventory_poll_seconds"]))
        for key in ("auto_forward", "print_on_check_in"):
            if key in updates:
                updates[key] = bool(updates[key])
        if updates.get("gate_role") not in (None, "entry", "exit"):
            updates.pop("gate_role")
        if updates.get("station_kind") not in (None, "desk", "gate"):
            updates.pop("station_kind")
        if updates:
            self.update(**updates)
