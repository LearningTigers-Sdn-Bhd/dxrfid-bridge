#!/usr/bin/env python3
"""
Encoder Helper — runs on the REGISTRATION PC (Windows), where the USB
encoder is physically plugged in.

Why this is a separate program from server.py:
  The unified dashboard (server.py) can run anywhere and talks to the gate
  reader over plain TCP — no vendor code needed. USB encoding is different:
  it requires the vendor's ECRFID.dll, which only loads on Windows (or a
  Linux libECRFID.so on Linux) — it cannot run on macOS. So this helper is
  a thin, Windows-only HTTP service that the main dashboard calls into,
  keeping ONE web UI for staff while isolating the OS-specific part here.

Function signatures below are taken verbatim from the vendor's own header
(new demo/example/c++/ECRFID.h) — not guessed. This file has NOT been
executed against real hardware (no Windows/USB encoder available in this
environment) — review/test it on the actual registration PC before relying
on it. It will run and log clearly on macOS/Linux too, it just won't find
a device.

Run (on the Windows registration PC, with ECRFID.dll on the PATH or next
to this script):
    python3 encoder_service.py --port 7000 --model D5200

Exposes:
    GET  /status   -> {"device_present": bool, "model": str|null}
    POST /encode   -> body {"uid": "<hex, optional>", "afi": int}
                      writes the AFI byte (a simple, common "encode" op —
                      swap for ISO15693_WriteMultipleBlocks if you need to
                      write arbitrary data blocks instead)
"""
import argparse
import ctypes
import json
import os
import platform
import sys
from ctypes import POINTER, c_char_p, c_int, c_ubyte, c_ushort, c_void_p
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
_VENDOR = os.path.join(_HERE, os.pardir, "vendor")

# vendor/ first: that copy is the x64 *Release* build. The vendor package's
# top-level x64/ and x86/ DLLs are DEBUG builds (they link MSVCP140D /
# VCRUNTIME140D / ucrtbased, which ship only with Visual Studio and are NOT
# in the VC++ Redistributable) — those fail with WinError 126 on a clean PC
# even though the file exists. See docs/PROJECT_NOTES.md.
DLL_CANDIDATES = [
    os.path.join(_VENDOR, "ECRFID.dll"),
    os.path.join(_VENDOR, "libECRFID.so"),
    os.path.join(_HERE, "ECRFID.dll"),
    "ECRFID.dll", "./ECRFID.dll", "libECRFID.so", "./libECRFID.so",
]


class EncoderUnavailable(Exception):
    pass


class ECRFIDEncoder:
    """Thin ctypes wrapper around the vendor's ECRFID library.

    Only wraps the handful of calls needed for USB-encoder use at a
    registration desk: list HID devices, open one, write AFI, close.
    """

    def __init__(self, model="D5200"):
        self.model = model
        self.dll = self._load_dll()
        self._bind_signatures()

    def _load_dll(self):
        if platform.system() != "Windows" and not sys.platform.startswith("linux"):
            raise EncoderUnavailable(
                f"ECRFID encoding requires Windows (or Linux) with the vendor DLL — "
                f"cannot run on {platform.system()}."
            )
        last_err = None
        loader = ctypes.WinDLL if platform.system() == "Windows" else ctypes.CDLL
        for name in DLL_CANDIDATES:
            try:
                return loader(name)
            except OSError as e:
                last_err = e
        hint = ""
        err = str(last_err)
        if "126" in err:
            hint = (
                " — the DLL was found but one of ITS dependencies wasn't. Install the "
                "'Microsoft Visual C++ 2015-2022 Redistributable (x64)'. (If you swapped in a "
                "DLL from the vendor's top-level x64/ or x86/ folder, put vendor/ECRFID.dll back: "
                "those are debug builds and can never load on a normal PC.)"
            )
        elif "193" in err:
            hint = (
                " — architecture mismatch. vendor/ECRFID.dll is 64-bit, so you need 64-bit Python. "
                "Check with: python -c \"import platform; print(platform.architecture())\""
            )
        raise EncoderUnavailable(f"Could not load ECRFID driver library: {last_err}{hint}")

    def _bind_signatures(self):
        d = self.dll
        d.GetHIDDriverList.restype = POINTER(c_char_p)
        d.GetHidConnectString.argtypes = [c_char_p, c_char_p, c_int, c_int]
        d.GetHidConnectString.restype = c_char_p
        d.Open.argtypes = [c_char_p]
        d.Open.restype = c_void_p
        d.Close.argtypes = [c_void_p]
        d.Close.restype = c_int
        d.GetDeviceInfo.argtypes = [c_void_p, POINTER(c_ubyte)]
        d.GetDeviceInfo.restype = c_int
        d.ISO15693_WriteAFI.argtypes = [c_void_p, POINTER(c_ubyte), c_ubyte, POINTER(c_ubyte)]
        d.ISO15693_WriteAFI.restype = c_int
        d.TagInventory.argtypes = [c_void_p, POINTER(POINTER(c_ubyte)), c_ubyte, c_ubyte]
        d.TagInventory.restype = c_int
        d.FreeHGlobal.argtypes = [c_void_p]
        d.FreeHGlobal.restype = c_int

    def list_hid_devices(self) -> list:
        arr = self.dll.GetHIDDriverList()
        devices = []
        i = 0
        while arr[i]:
            devices.append(arr[i].decode(errors="replace"))
            i += 1
        return devices

    def open_first_device(self):
        devices = self.list_hid_devices()
        if not devices:
            raise EncoderUnavailable("No USB HID encoder found — check it's plugged in.")
        conn_str = self.dll.GetHidConnectString(
            self.model.encode(), devices[0].encode(), 1, 1
        )
        ctx = self.dll.Open(conn_str)
        if not ctx:
            raise EncoderUnavailable("Found the USB device but couldn't open a session with it.")
        return ctx

    def write_afi(self, ctx, uid_hex: str, afi: int) -> bool:
        uid = (c_ubyte * 8)(*bytes.fromhex(uid_hex))
        receive = (c_ubyte * 32)()
        status = self.dll.ISO15693_WriteAFI(ctx, uid, c_ubyte(afi), receive)
        return status >= 0

    def close(self, ctx):
        self.dll.Close(ctx)


STATE = {"encoder": None, "model": "D5200", "last_error": None}


def get_encoder():
    if STATE["encoder"] is None:
        STATE["encoder"] = ECRFIDEncoder(model=STATE["model"])
    return STATE["encoder"]


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path == "/status":
            try:
                enc = get_encoder()
                devices = enc.list_hid_devices()
                self._json({"device_present": bool(devices), "model": STATE["model"], "devices": devices})
            except EncoderUnavailable as e:
                self._json({"device_present": False, "model": STATE["model"], "error": str(e)})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/encode":
            self._json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        try:
            enc = get_encoder()
            ctx = enc.open_first_device()
            try:
                ok = enc.write_afi(ctx, body["uid"], int(body.get("afi", 0x00)))
            finally:
                enc.close(ctx)
            self._json({"ok": ok, "detail": "Tag encoded successfully" if ok else "Encoder reported a write failure"})
        except EncoderUnavailable as e:
            self._json({"ok": False, "detail": str(e)}, 200)
        except Exception as e:
            self._json({"ok": False, "detail": f"Unexpected error: {e}"}, 200)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7000)
    ap.add_argument("--model", default="D5200", help="reader model string, e.g. D5200")
    args = ap.parse_args()
    STATE["model"] = args.model
    print(f"Encoder helper running at http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    print("NOTE: requires Windows + ECRFID.dll + the USB encoder plugged in to actually do anything.")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
