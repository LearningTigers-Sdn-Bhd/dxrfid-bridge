"""Update checking against GitHub Releases.

The bridge is versioned with tags (bridge-vX.Y.Z) on the dxrfid-bridge
repo; CI builds dxrfid-bridge.exe and attaches it to the matching GitHub
Release. This module compares APP_VERSION with the latest release tag.

Update flow (honest, no magic): the UI offers "Download update" which
opens the release asset in the browser. The operator closes the bridge,
replaces the exe, and starts it again. A running Windows exe cannot
replace itself in-place, and a fake "auto-update" that just downloads
somewhere the operator can't find is worse than clear instructions.
"""
from __future__ import annotations

import json
import re
import urllib.request

REPO = "LearningTigers-Sdn-Bhd/dxrfid-bridge"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
TIMEOUT = 8.0

# Set at build time by CI from the tag (build/inject_version.py); falls
# back to the package __version__ for dev runs.
try:
    from ._build_version import BUILD_VERSION as _build
except ImportError:
    _build = None


def current_version() -> str:
    if _build:
        return _build
    from . import __version__
    return __version__


def parse_version(text: str) -> tuple[int, ...] | None:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def check_latest() -> dict:
    """→ {ok, current, latest, update_available, url, exe_url, name, error}"""
    current = current_version()
    out = {"ok": False, "current": current, "latest": None,
           "update_available": False, "url": None, "exe_url": None,
           "name": None, "error": None}
    req = urllib.request.Request(LATEST_API, headers={
        "User-Agent": f"dxrfid-bridge/{current}",
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            out["ok"] = True
            out["error"] = None
            out["latest"] = None  # no releases published yet
        else:
            out["error"] = f"GitHub returned HTTP {e.code}."
        return out
    except Exception as e:
        out["error"] = f"Could not reach GitHub — {e}"
        return out

    tag = data.get("tag_name", "")
    latest = parse_version(tag)
    cur = parse_version(current)
    out["ok"] = True
    out["latest"] = tag
    out["name"] = data.get("name") or tag
    out["url"] = data.get("html_url")
    for asset in data.get("assets", []):
        if asset.get("name", "").endswith(".exe"):
            out["exe_url"] = asset.get("browser_download_url")
            break
    if latest and cur:
        out["update_available"] = latest > cur
    return out
