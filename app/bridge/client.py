"""EventzFlow device API client — implements the RfiDex P5 contract exactly.

Wire shapes mirror rfidex/crates/rfidex-core/src/contract.rs. Auth is the
RFID-scope API key in the Authorization header; the station UUID goes in
X-RfiDex-Station so the backend can tell stations apart.

Every mutating call carries a caller-supplied operation_id / delivery_id
(UUID). The backend is idempotent on those ids: a replayed request returns
the original stored result instead of acting twice. Callers that retry MUST
reuse the same id — desk.py and gate.py do.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

# Python's default "Python-urllib/x.y" UA is blocked by Cloudflare (error
# 1010) and similar WAFs — reuse the browser-looking UA that already works.
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

HEADER_STATION = "X-RfiDex-Station"

PATH_HEARTBEAT = "/v1/rfid/stations/heartbeat"
PATH_CACHE = "/v1/rfid/cache"
PATH_DESK_SCANS = "/v1/rfid/desk_scans"
PATH_TICKET_SEARCH = "/v1/rfid/tickets/search"
PATH_BINDINGS = "/v1/rfid/bindings"
PATH_LOOKUP = "/v1/rfid/bindings/lookup"
PATH_OBSERVATIONS = "/v1/rfid/observations"

# contract.rs ErrorCode — closed set; anything else is a bug or a proxy page.
ERROR_CODES = {
    "unauthorized", "ticket_not_found", "ticket_unpaid", "ticket_cancelled",
    "uid_bound_elsewhere", "ticket_has_sticker", "reason_required",
    "batch_too_large", "malformed",
}


class ApiError(Exception):
    """A structured error from the backend (contract ErrorBody), or a
    transport/HTTP failure with .error == 'unreachable' | 'http'."""

    def __init__(self, error: str, message: str, status: int | None = None,
                 holder=None, binding=None):
        super().__init__(message)
        self.error = error
        self.message = message
        self.status = status
        self.holder = holder
        self.binding = binding

    @property
    def is_contract_error(self) -> bool:
        return self.error in ERROR_CODES


def classify_url_error(exc: Exception) -> str:
    """Raw network exception → plain-English operator sentence."""
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, TimeoutError):
            return "Server took too long to answer — check the internet connection."
        text = str(reason)
        if "Name or service not known" in text or "getaddrinfo" in text or "11001" in text:
            return "Server address not found — check the URL in Settings."
        if "refused" in text.lower():
            return "Server refused the connection — is the backend up?"
        return f"Network problem: {reason}"
    if isinstance(exc, TimeoutError):
        return "Server took too long to answer — check the internet connection."
    return f"Unexpected error: {exc}"


class RfidClient:
    def __init__(self, api_base: str, api_key: str, station_id: str,
                 timeout: float = 10.0):
        self.api_base = (api_base or "").rstrip("/")
        self.api_key = api_key or ""
        self.station_id = station_id
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_base and self.api_key)

    def _headers(self) -> dict:
        return {
            "User-Agent": _BROWSER_USER_AGENT,
            "Authorization": self.api_key,
            "Content-Type": "application/json",
            HEADER_STATION: self.station_id,
        }

    def _request(self, method: str, path: str, payload: dict | None = None,
                 query: dict | None = None) -> dict:
        if not self.configured:
            raise ApiError("unreachable",
                           "Backend not configured — set URL and API key in Settings.")
        url = self.api_base + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                raise ApiError("http", f"Server returned HTTP {e.code}.", status=e.code)
            raise ApiError(
                parsed.get("error", "http"),
                parsed.get("message", f"Server returned HTTP {e.code}."),
                status=e.code,
                holder=parsed.get("holder"),
                binding=parsed.get("binding"),
            )
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ApiError("unreachable", classify_url_error(e))
        except json.JSONDecodeError:
            raise ApiError("http", "Server answered with something that isn't JSON.")

    # ---- contract calls -------------------------------------------------

    def heartbeat(self, name: str, kind: str, role: str | None,
                  hw_model: str | None, firmware: str | None,
                  app_version: str) -> dict:
        return self._request("POST", PATH_HEARTBEAT, {
            "name": name, "kind": kind, "role": role,
            "hw_model": hw_model, "firmware": firmware,
            "app_version": app_version,
        })

    def cache(self) -> dict:
        return self._request("GET", PATH_CACHE)

    def desk_scan(self, public_id: str, operation_id: str,
                    captured_at: str) -> dict:
        """→ DeskScanResp: {ticket, binding, check_in:{result, checked_in_at}}.
        Idempotent on operation_id — retries must reuse it."""
        return self._request("POST", PATH_DESK_SCANS, {
            "public_id": public_id,
            "operation_id": operation_id,
            "captured_at": captured_at,
        })

    def search_tickets(self, by: str, q: str) -> dict:
        if by not in ("name", "email", "phone"):
            raise ApiError("malformed", f"Unknown search field: {by}")
        return self._request("GET", PATH_TICKET_SEARCH, query={"by": by, "q": q})

    def bind(self, public_id: str, protocol: str, uid_raw_hex: str,
             mode: str, operation_id: str, captured_at: str,
             payload_version: int | None = None, replace: bool = False,
             reason: str | None = None) -> dict:
        return self._request("POST", PATH_BINDINGS, {
            "public_id": public_id, "protocol": protocol,
            "uid_raw_hex": uid_raw_hex, "mode": mode,
            "payload_version": payload_version,
            "operation_id": operation_id, "captured_at": captured_at,
            "replace": replace, "reason": reason,
        })

    def lookup(self, tag_key: str) -> dict:
        return self._request("GET", PATH_LOOKUP, query={"tag_key": tag_key})

    def observations(self, items: list[dict]) -> dict:
        """items: ObservationItem dicts, each with a unique delivery_id.
        Max batch is 50 (contract MAX_OBSERVATION_BATCH)."""
        if len(items) > 50:
            raise ApiError("batch_too_large", "At most 50 observations per batch.")
        return self._request("POST", PATH_OBSERVATIONS,
                             {"observations": items})
