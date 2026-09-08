#!/usr/bin/env python3
"""
Check an ECRFID.dll before trusting it on a Windows registration PC.

Runs anywhere (macOS/Linux/Windows) with plain Python — it parses the PE
headers directly, it does not load the DLL.

It answers the three questions that actually bite:

  1. Is it x86 or x64?  (must match your Python's bitness, or WinError 193)
  2. Does it link the DEBUG C runtime?  Debug runtimes (MSVCP140D,
     VCRUNTIME140D, ucrtbased) ship only with Visual Studio and are NOT
     redistributable, so such a DLL can never load on a clean PC — it
     fails with WinError 126 even though the file is present.
  3. Does it export the functions encoder_service.py binds?

Usage:
    python3 tools/check_dll.py vendor/ECRFID.dll
    python3 tools/check_dll.py "../new demo/x64/ECRFID.dll"
    python3 tools/check_dll.py            # defaults to vendor/ECRFID.dll
"""
import os
import struct
import sys

# The functions app/encoder_service.py looks up by name.
REQUIRED = [
    "GetHIDDriverList", "GetHidConnectString", "Open", "Close",
    "GetDeviceInfo", "ISO15693_WriteAFI", "TagInventory", "FreeHGlobal",
]

MACHINE = {0x8664: "x64", 0x14C: "x86", 0xAA64: "arm64"}


class NotAPE(Exception):
    pass


class PE:
    def __init__(self, path):
        with open(path, "rb") as f:
            self.d = f.read()
        d = self.d
        if d[:2] != b"MZ":
            raise NotAPE("not a Windows executable (no MZ header)")
        self.pe = struct.unpack_from("<I", d, 0x3C)[0]
        if d[self.pe:self.pe + 4] != b"PE\0\0":
            raise NotAPE("not a PE file")
        self.machine = struct.unpack_from("<H", d, self.pe + 4)[0]
        nsec = struct.unpack_from("<H", d, self.pe + 6)[0]
        optsz = struct.unpack_from("<H", d, self.pe + 20)[0]
        self.opt = self.pe + 24
        magic = struct.unpack_from("<H", d, self.opt)[0]
        self.pe32p = magic == 0x20B
        self.ddir = self.opt + (112 if self.pe32p else 96)
        self.secs = []
        base = self.opt + optsz
        for i in range(nsec):
            b = base + 40 * i
            va = struct.unpack_from("<I", d, b + 12)[0]
            vs = struct.unpack_from("<I", d, b + 8)[0]
            raw = struct.unpack_from("<I", d, b + 20)[0]
            self.secs.append((va, vs, raw))

    def _off(self, rva):
        for va, vs, raw in self.secs:
            if va <= rva < va + max(vs, 1) + 0x1000:
                return raw + (rva - va)
        return None

    def _cstr(self, off):
        end = self.d.index(b"\0", off)
        return self.d[off:end].decode(errors="replace")

    @property
    def arch(self):
        return MACHINE.get(self.machine, hex(self.machine))

    def imports(self):
        rva = struct.unpack_from("<I", self.d, self.ddir + 8)[0]
        if not rva:
            return []
        o = self._off(rva)
        out = []
        while True:
            name_rva = struct.unpack_from("<I", self.d, o + 12)[0]
            if name_rva == 0:
                break
            out.append(self._cstr(self._off(name_rva)))
            o += 20
        return out

    def exports(self):
        rva = struct.unpack_from("<I", self.d, self.ddir)[0]
        if not rva:
            return []
        o = self._off(rva)
        n = struct.unpack_from("<I", self.d, o + 24)[0]
        names_rva = struct.unpack_from("<I", self.d, o + 32)[0]
        if not n or not names_rva:
            return []
        no = self._off(names_rva)
        return [self._cstr(self._off(struct.unpack_from("<I", self.d, no + 4 * i)[0]))
                for i in range(n)]


def is_debug_crt(dep):
    u = dep.upper()
    if u == "UCRTBASED.DLL":
        return True
    # MSVCP140D.dll / VCRUNTIME140D.dll / VCRUNTIME140_1D.dll
    if (u.startswith("MSVCP") or u.startswith("VCRUNTIME") or u.startswith("MSVCR")):
        return u.replace(".DLL", "").endswith("D")
    return False


def main():
    default = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           os.pardir, "vendor", "ECRFID.dll")
    path = sys.argv[1] if len(sys.argv) > 1 else default

    if not os.path.exists(path):
        print(f"ERROR: no such file: {path}")
        return 2

    print(f"File : {path}")
    print(f"Size : {os.path.getsize(path):,} bytes\n")

    try:
        pe = PE(path)
    except NotAPE as e:
        print(f"ERROR: {e}")
        return 2

    deps = pe.imports()
    exports = pe.exports()
    debug = [d for d in deps if is_debug_crt(d)]
    missing = [f for f in REQUIRED if f not in exports]

    print(f"Arch : {pe.arch}")
    print(f"       -> needs {'64' if pe.arch == 'x64' else '32'}-bit Python "
          f"(mismatch = WinError 193)\n")

    print("C runtime:")
    crt = [d for d in deps if d.upper().startswith(("MSVCP", "VCRUNTIME", "MSVCR", "UCRT"))]
    for d in crt or ["(none — statically linked)"]:
        print(f"   {d}")
    print()

    print(f"Exports: {len(exports)} total")
    if missing:
        print("   MISSING functions encoder_service.py needs:")
        for m in missing:
            print(f"      - {m}")
    else:
        print(f"   all {len(REQUIRED)} functions encoder_service.py needs are present")
    print()

    print("=" * 62)
    if debug:
        print("VERDICT: ❌ UNUSABLE — this is a DEBUG build.")
        print()
        print("  It links: " + ", ".join(debug))
        print("  Those debug runtimes ship ONLY with Visual Studio. They are not")
        print("  part of the VC++ Redistributable, so on a clean PC this DLL fails")
        print("  with WinError 126 ('module could not be found') — misleading,")
        print("  because the missing module is a dependency, not the DLL itself.")
        print()
        print("  Use the vendor's  new demo/x64/Release/ECRFID.dll  instead.")
        rc = 1
    elif missing:
        print("VERDICT: ❌ UNUSABLE — required functions are not exported.")
        rc = 1
    else:
        print("VERDICT: ✅ OK — release build, correct exports.")
        print()
        print(f"  Install the VC++ 2015-2022 Redistributable ({pe.arch}) on the")
        print(f"  target PC and use {'64' if pe.arch == 'x64' else '32'}-bit Python.")
        rc = 0
    print("=" * 62)
    return rc


if __name__ == "__main__":
    sys.exit(main())
