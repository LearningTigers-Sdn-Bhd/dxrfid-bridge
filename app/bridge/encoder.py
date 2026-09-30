"""ECRFID.dll ctypes wrapper — ported from encoder_service.py.

Wraps only what a registration desk needs: list HID devices, open one,
inventory (read the sticker on the pad), write AFI, close. Signatures are
taken verbatim from the vendor header (new demo/example/c++/ECRFID.h).

Windows only in practice (the vendor also ships libECRFID.so for Linux);
on macOS the wrapper loads nothing and reports unavailable, so the rest of
the bridge still runs for development.

⚠ Never re-tested against real hardware since the port — same caveat as
the original file. Validate on the registration PC before event day.
"""
from __future__ import annotations

import ctypes
import os
import platform
import sys
from ctypes import POINTER, c_char_p, c_int, c_ubyte, c_void_p

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.dirname(_HERE)
_VENDOR = os.path.join(_APP, os.pardir, "vendor")
# PyInstaller frozen layout: dll bundled next to the exe.
_FROZEN = getattr(sys, "_MEIPASS", None)

DLL_CANDIDATES = [
    *([os.path.join(_FROZEN, "ECRFID.dll")] if _FROZEN else []),
    os.path.join(_VENDOR, "ECRFID.dll"),
    os.path.join(_VENDOR, "libECRFID.so"),
    os.path.join(_APP, "ECRFID.dll"),
    "ECRFID.dll", "./ECRFID.dll", "libECRFID.so", "./libECRFID.so",
]


class EncoderUnavailable(Exception):
    pass


class ECRFIDEncoder:
    """Thin ctypes wrapper around the vendor's ECRFID library."""

    def __init__(self, model: str = "D5200"):
        self.model = model
        self.dll = self._load_dll()
        self._bind_signatures()

    def _load_dll(self):
        system = platform.system()
        if system not in ("Windows", "Linux"):
            raise EncoderUnavailable(
                f"USB encoding needs Windows (or Linux) with the vendor "
                f"library — cannot run on {system}."
            )
        last_err = None
        loader = ctypes.WinDLL if system == "Windows" else ctypes.CDLL
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
                "DLL from the vendor's top-level x64/ or x86/ folder, put the Release build "
                "back: those are debug builds and can never load on a normal PC.)"
            )
        elif "193" in err:
            hint = (
                " — architecture mismatch. The bundled ECRFID.dll is 64-bit, so the "
                "bridge must run as 64-bit."
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
        d.ISO15693_WriteAFI.argtypes = [c_void_p, POINTER(c_ubyte), c_ubyte,
                                        POINTER(c_ubyte)]
        d.ISO15693_WriteAFI.restype = c_int
        d.TagInventory.argtypes = [c_void_p, POINTER(POINTER(c_ubyte)),
                                   c_ubyte, c_ubyte]
        d.TagInventory.restype = c_int
        d.FreeHGlobal.argtypes = [c_void_p]
        d.FreeHGlobal.restype = c_int

    def list_hid_devices(self) -> list[str]:
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
            raise EncoderUnavailable(
                "No USB encoder found — check it's plugged in.")
        conn_str = self.dll.GetHidConnectString(
            self.model.encode(), devices[0].encode(), 1, 1)
        ctx = self.dll.Open(conn_str)
        if not ctx:
            raise EncoderUnavailable(
                "Found the USB device but couldn't open a session with it.")
        return ctx

    def inventory(self, ctx) -> list[dict]:
        """Read UIDs currently on the pad. Returns [{'uid_hex': …}]."""
        tags_ptr = POINTER(c_ubyte)()
        count = self.dll.TagInventory(ctx, tags_ptr, 0, 0)
        tags = []
        try:
            for i in range(max(0, count)):
                # TagInventory's out-param layout: array of 8-byte UIDs.
                # (Matches the vendor demo's usage; verify on hardware.)
                uid = bytes(bytearray(tags_ptr[i * 8:(i + 1) * 8]))
                if uid and any(uid):
                    tags.append({"uid_hex": uid.hex().upper()})
        finally:
            if tags_ptr:
                self.dll.FreeHGlobal(tags_ptr)
        return tags

    def write_afi(self, ctx, uid_hex: str, afi: int) -> bool:
        uid = (c_ubyte * 8)(*bytes.fromhex(uid_hex))
        receive = (c_ubyte * 32)()
        status = self.dll.ISO15693_WriteAFI(ctx, uid, c_ubyte(afi), receive)
        return status >= 0

    def close(self, ctx):
        self.dll.Close(ctx)


def probe(model: str = "D5200") -> dict:
    """Non-destructive availability check for the UI status card."""
    try:
        enc = ECRFIDEncoder(model=model)
    except EncoderUnavailable as e:
        return {"available": False, "detail": str(e)}
    try:
        devices = enc.list_hid_devices()
        return {"available": bool(devices), "devices": devices,
                "detail": "USB encoder connected" if devices
                else "Driver loaded; no USB encoder plugged in"}
    except Exception as e:  # driver calls can raise anything
        return {"available": False, "detail": f"Driver loaded but probe failed: {e}"}
