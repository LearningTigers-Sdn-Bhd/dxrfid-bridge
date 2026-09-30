"""Desk flow — scan/search → check-in → print → sticker bind (P7 contract §1).

    Staff scans QR (or searches name/email/phone)
      → POST /v1/rfid/desk_scans
      → check_in.result == "checked_in" (this scan made it)
          → print badge via local event-printing
      → "Already checked in at 09:14" otherwise — NOT an error, no auto-print
      → sticker step: read UID on the pad → POST /v1/rfid/bindings

Online-first: when the backend is unreachable the desk answers honestly
("Offline — cannot check in"); the durable queue lands in phase 2b.

Exact-once rule: one scan gets ONE operation_id, generated when the scan
arrives and reused if the same scan is retried by the UI. A retry returns
the stored result instead of checking the guest in twice — that's the
backend's idempotency doing its job.
"""
from __future__ import annotations

import datetime
import uuid

from .client import ApiError
from .printer import PrinterError


def _utcnow_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class DeskFlow:
    """Exact-once model: each call to scan() is ONE new operation and gets a
    fresh operation_id — so a deliberate rescan correctly reports
    already_checked_in from the backend. The idempotency guarantee lives on
    the backend (replay by operation_id); the UI's retry of the SAME HTTP
    POST is what replays it, never a new scan.

    Edge case: a QR scanned twice in quick succession can get its second
    POST answered with the stored result of the first IF a proxy or the UI
    retried the first POST with the same id. We detect that stale replay by
    comparing checked_in_at with now, and re-ask once with a fresh id so the
    operator sees the truthful "Already checked in" state."""

    def __init__(self, runtime):
        self.rt = runtime

    @staticmethod
    def _stale_check_in(check_in: dict, max_age_s: float = 30.0) -> bool:
        """True when checked_in_at is clearly older than this scan — i.e. the
        check-in was made earlier, not by the request we just sent."""
        raw = check_in.get("checked_in_at")
        if not raw:
            return False
        try:
            ts = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return False
        age = (datetime.datetime.now(datetime.timezone.utc) - ts).total_seconds()
        return age > max_age_s

    # ---- search (contract §3.2/§3.3 — server-side; offline name-only in 2b)

    def search(self, by: str, q: str) -> dict:
        q = (q or "").strip()
        minimum = {"name": 2, "email": 3, "phone": 4}.get(by, 2)
        if by == "email" and "@" not in q:
            return {"tickets": [], "hint": "An email search needs an @."}
        if len(q) < minimum:
            return {"tickets": [], "hint": f"Type at least {minimum} characters."}
        try:
            return self.rt.client().search_tickets(by, q)
        except ApiError as e:
            self.rt.event("err", f"Search failed — {e.message}")
            raise

    # ---- scan → check-in → print (contract §3.1 + §4)

    def scan(self, public_id: str) -> dict:
        """One desk scan. Returns a UI-ready result card."""
        public_id = (public_id or "").strip()
        if not public_id:
            raise ApiError("malformed", "Nothing scanned — scan a QR code first.")
        op_id = str(uuid.uuid4())
        try:
            resp = self.rt.client().desk_scan(
                public_id=public_id, operation_id=op_id,
                captured_at=_utcnow_iso())
        except ApiError as e:
            if e.error == "unreachable":
                self.rt.event("err", "Offline — cannot check in right now.")
            raise

        ticket = resp.get("ticket") or {}
        check_in = resp.get("check_in") or {}
        result = check_in.get("result")
        if result == "checked_in" and self._stale_check_in(check_in):
            # The answer claims this scan checked the guest in, yet the
            # check-in is minutes old — this is a replayed stored result of
            # an earlier scan (proxy/UI retry with a reused id), not what
            # just happened. Re-ask once with a fresh id for the truth.
            resp = self.rt.client().desk_scan(
                public_id=public_id, operation_id=str(uuid.uuid4()),
                captured_at=_utcnow_iso())
            ticket = resp.get("ticket") or ticket
            check_in = resp.get("check_in") or check_in
            result = check_in.get("result")
        name = ticket.get("name", "?")

        card = {
            "ticket": ticket,
            "binding": resp.get("binding"),
            "check_in": check_in,
            "printed": False,
            "print_error": None,
        }

        if result == "checked_in":
            self.rt.event("desk", f"✓ {name} checked in.")
            if self.rt.config.get("print_on_check_in", True):
                card.update(self._try_print(public_id))
        else:
            when = check_in.get("checked_in_at", "")
            self.rt.event("desk", f"{name} was already checked in ({when}).")
        return card

    def _try_print(self, public_id: str) -> dict:
        try:
            self.rt.printer().reprint(public_id)
            self.rt.event("print", "Badge sent to printer.")
            return {"printed": True, "print_error": None}
        except PrinterError as e:
            self.rt.event("err", f"Badge not printed — press Reprint. ({e})")
            return {"printed": False, "print_error": str(e)}

    def reprint(self, public_id: str) -> dict:
        """Staff pressed Reprint badge (contract §4 row 3)."""
        return self._try_print(public_id)

    # ---- sticker step: read pad → bind (contract §1 final step)

    def bind_sticker(self, public_id: str, uid_hex: str,
                     protocol: str = "iso15693") -> dict:
        """Link the sticker on the pad to the checked-in ticket."""
        public_id = (public_id or "").strip()
        uid_hex = (uid_hex or "").strip().upper()
        if not public_id or not uid_hex:
            raise ApiError("malformed", "Need both a ticket and a sticker UID.")
        resp = self.rt.client().bind(
            public_id=public_id, protocol=protocol, uid_raw_hex=uid_hex,
            mode="bind", operation_id=str(uuid.uuid4()),
            captured_at=_utcnow_iso())
        self.rt.event("desk", f"✓ Sticker {uid_hex} linked.")
        return resp

    def cancel_session(self, public_id: str):
        """Desk moved on without binding. No server state is held per desk
        session (op ids are per-scan now), so this is a no-op hook kept for
        the UI — it exists so "Next guest" can log the abandonment."""
        if public_id:
            self.rt.event("desk", "Desk cleared without linking a sticker.")
