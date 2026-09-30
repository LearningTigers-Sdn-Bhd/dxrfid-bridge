"""event-printing hook — mirrors the P7 contract §4.

The bridge never builds badge fields. It asks the local event-printing app
to print a ticket id; event-printing looks the ticket up and applies its own
layout. Loopback only. Printing is fire-and-report: it never blocks the
sticker step, and a failed print never undoes a check-in.

Rules from the contract:
    desk scan returns checked_in          → POST /scan/{public_id}/reprint
    staff press Reprint badge             → POST /scan/{public_id}/reprint
    desk scan was offline (queued)        → no print (phase 2b)
    Setup "Test printer"                  → GET /health
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from .client import _BROWSER_USER_AGENT, classify_url_error

TIMEOUT = 10.0  # contract: printing never blocks the sticker step


class PrinterError(Exception):
    pass


def _check_loopback(url: str):
    host = urllib.parse.urlparse(url).hostname or ""
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise PrinterError(
            "Printer address must be on this PC (127.0.0.1) — a printer on "
            "another PC is not supported.")


class Printer:
    def __init__(self, base_url: str):
        self.base_url = (base_url or "").rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def health(self) -> dict:
        """→ {ok, printer, output_dir, version}. Raises PrinterError."""
        if not self.configured:
            raise PrinterError("No printer address configured.")
        _check_loopback(self.base_url)
        req = urllib.request.Request(
            self.base_url + "/health",
            headers={"User-Agent": _BROWSER_USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise PrinterError(
                "Printer app not running on this PC — start event-printing "
                f"and try again. ({classify_url_error(e)})")
        except json.JSONDecodeError:
            raise PrinterError("Printer app answered with something that isn't JSON.")

    def reprint(self, public_id: str) -> dict:
        """Print the badge for a ticket. Raises PrinterError on failure —
        the caller reports it and moves on (check-in already happened)."""
        if not self.configured:
            raise PrinterError("No printer address configured.")
        _check_loopback(self.base_url)
        url = f"{self.base_url}/scan/{urllib.parse.quote(public_id)}/reprint"
        req = urllib.request.Request(url, data=b"{}", method="POST", headers={
            "User-Agent": _BROWSER_USER_AGENT,
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            raise PrinterError(f"Printer refused the badge (HTTP {e.code}).")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise PrinterError(
                f"Badge not printed — {classify_url_error(e)}")
        except json.JSONDecodeError:
            raise PrinterError("Printer app answered with something that isn't JSON.")
