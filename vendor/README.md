# vendor/

`ECRFID.dll` — the RFID reader driver library, used by
`app/encoder_service.py` through `ctypes` to drive the **USB encoder** at
the registration desk.

## Which copy is this, and why it matters

This is the vendor package's **`new demo/x64/Release/ECRFID.dll`** — and it
has to be that specific copy.

The vendor ships several builds. Most of them are **debug builds** that link
the debug C runtime (`MSVCP140D.dll`, `VCRUNTIME140D.dll`, `ucrtbased.dll`).
Those runtimes ship **only with Visual Studio** — they are deliberately not
redistributable and are *not* included in the "Visual C++ Redistributable".
On a clean Windows PC they fail to load with:

```
OSError: [WinError 126] The specified module could not be found
```

which is misleading — the DLL is right there; its *dependencies* are missing.

| Vendor path | Arch | C runtime | Usable on a clean PC |
|---|---|---|---|
| `new demo/x64/ECRFID.dll` | x64 | debug | ❌ |
| `new demo/x86/ECRFID.dll` | x86 | debug | ❌ |
| **`new demo/x64/Release/ECRFID.dll`** | **x64** | release | ✅ **this file** |

So: **do not replace this file with the one from the vendor's top-level
`x64/` folder**, even though that's the obvious place to look.

## Requirements on the Windows PC

- **Microsoft Visual C++ 2015–2022 Redistributable (x64)**
- **64-bit Python** — this DLL is x64. A 32-bit Python gives
  `OSError: [WinError 193] %1 is not a valid Win32 application`.
  Check with: `python -c "import platform; print(platform.architecture())"`

## Linux

Drop the vendor's `libECRFID.so` (from `new demo/x64/` or `new demo/arm64/`)
in this folder; `encoder_service.py` looks for it here too.

## macOS

There is no macOS build of this library — anything USB/DLL-related has to run
on Windows or Linux. The dashboard itself (`app/server.py`) is pure Python and
runs anywhere; only the USB encoder needs this DLL.

## Verifying an unknown copy

To check any DLL before trusting it (works on any OS, no Windows needed):

```bash
python3 tools/check_dll.py path/to/ECRFID.dll
```

It prints the architecture, whether it links the debug CRT, and whether all
the functions `encoder_service.py` needs are exported.
