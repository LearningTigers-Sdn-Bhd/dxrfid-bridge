# DXRFID Bridge

Registration-desk and gate companion for **EventzFlow** RFID events — the
Python backup to the primary RfiDex app. Speaks the same EventzFlow device
API contract (`/v1/rfid/*`) as RfiDex, so the backend treats both apps
identically.

Two touchpoints:

- **Registration desk** — scan a QR or search a name, the guest is checked
  in, the badge prints, and a sticker on the USB encoder pad is linked to
  the ticket.
- **Entrance / exit gates** — a network (TCP) reader detects stickers as
  guests pass; each sighting is posted to EventzFlow with an idempotent
  delivery id, and the console shows live passages and headcount.

The console is a single-page dark/light UI served by the bridge itself —
no build step, no npm.

---

## Quick start (Windows)

1. Install **Python 3.9 or newer** from <https://www.python.org/downloads/>
   — on the first installer screen, tick **"Add python.exe to PATH"**.
2. Double-click **`START-HERE.bat`**.

That's it. The bridge starts and your browser opens at
<http://localhost:5050>. Close the window to stop.

There is nothing to `pip install` — the bridge uses only the Python
standard library.

### No hardware yet?

Double-click **`START-DEMO-no-hardware.bat`** instead. It runs a mock
EventzFlow backend (speaking the real RFID contract, seeded with demo
tickets) and a fake gate reader, so you can click through the full desk
and gate flow on any PC.

### Single-file .exe

On Windows, `build\build-exe.bat` produces `dist\dxrfid-bridge.exe`
(PyInstaller, one file, includes the console UI and the vendor Release
DLL). Config and data live in `%LOCALAPPDATA%\DXRFIDBridge`, never next
to the exe.

## Quick start (macOS / Linux)

```bash
python3 app/mock_rfid_backend.py --port 9100 --api-key demo-key &
python3 app/server.py --port 5050 --open
```

Then in Settings → Backend: URL `http://127.0.0.1:9100`, key `demo-key`.

Only the **USB encoder** needs Windows (or Linux) — on macOS the encoder
status simply reports unavailable; everything else runs. See
[`vendor/README.md`](vendor/README.md).

---

## First-time setup (real event)

Settings view (rail, bottom icon), in order:

1. **Backend** — server URL + RFID API key → Save → **Test connection**
   (should show the event name).
2. **Gate reader** — reader IP + port (default 6688), direction
   (entry/exit) → Save.
3. **Printer** — address of the local event-printing app
   (`http://127.0.0.1:8000`) → **Test printer**.
4. **Encoder** — reader model (e.g. `D5200`) → **Check encoder**.

Desk tab: scan a QR (or search name/email/phone) → guest checks in →
badge prints → tap a sticker on the pad → **Link**.

Gate tab: **Start watch** — passages stream in with per-guest outcomes
(`accepted`, `unknown tag`, `not checked in`, anomalies) and the
headcount strip updates live.

---

## What's in here

```
dxrfid-bridge/
├── START-HERE.bat                 one-click start (Windows)
├── START-DEMO-no-hardware.bat     one-click demo, no hardware needed
├── bin/dev                        legacy dev launcher (macOS / Linux)
├── app/
│   ├── server.py                  entry point — python3 app/server.py
│   ├── bridge/                    the bridge itself (all stdlib)
│   │   ├── client.py              EventzFlow /v1/rfid/* contract client
│   │   ├── desk.py                scan → check-in → print → bind flow
│   │   ├── gate.py                inventory → dedup → observations loop
│   │   ├── encoder.py             ECRFID.dll ctypes wrapper
│   │   ├── printer.py             event-printing hook (fire-and-report)
│   │   ├── protocol.py            0xEC gate wire protocol (CRC16, frames)
│   │   ├── config.py              persisted settings (atomic save)
│   │   ├── state.py               runtime state + operator event log
│   │   └── server.py              HTTP API + serves the console UI
│   ├── ui/index.html              the console (single file, no build step)
│   ├── mock_rfid_backend.py       mock EventzFlow backend (real contract)
│   ├── test_e2e.py                end-to-end suite: python3 app/test_e2e.py
│   ├── mock_reader.py             fake gate reader (real wire protocol)
│   ├── mock_eventzflow.py         legacy generic mock server
│   ├── encoder_service.py         legacy standalone encoder helper
│   └── mock_client.py             CLI to poke the mock reader directly
├── build/
│   ├── dxrfid-bridge.spec         PyInstaller spec (single-file exe)
│   └── build-exe.bat              Windows build script
├── vendor/
│   ├── ECRFID.dll                 vendor driver — read vendor/README.md first
│   └── README.md                  ⚠ which DLL copy to use, and why
├── tools/
│   └── check_dll.py               verify a DLL before trusting it on a PC
└── docs/
    ├── PROJECT_NOTES.md           background notes
    ├── protocol-guide.md          the reader's wire protocol, in English
    └── c-api-reference.md         the vendor C API, in English
```

## Exact-once rules (same as RfiDex)

- Every desk scan and gate sighting carries a UUID operation/delivery id.
  The backend is idempotent on those ids — a replay returns the stored
  result instead of acting twice. Retried deliveries reuse the same id.
- A check-in prints **only** when the backend says this scan made the
  first check-in (`checked_in`). Rescans show "Already checked in" with
  the original time and offer Reprint instead.
- Printing never blocks the sticker step; a failed print never undoes a
  check-in.

## Important: the vendor DLL

The USB encoder needs `vendor/ECRFID.dll`, and **it must be the vendor's
`x64/Release` build**. The vendor's other Windows DLLs are *debug* builds
that can never load on a normal PC — they fail with a misleading
`WinError 126`. Full explanation in [`vendor/README.md`](vendor/README.md).

```bash
python3 tools/check_dll.py vendor/ECRFID.dll
```

## Status

Contract behavior (check-in, search, bindings, observations, idempotent
replay, error surface) is covered by `app/test_e2e.py` — 14 checks
against a mock backend implementing the same rules as production.

**Not yet done:** the offline queue (durable SQLite outbox, offline name
search) — the bridge is online-first and says so honestly when the
backend is unreachable. Hardware paths (real gate TCP exchange, real
ECRFID.dll calls) are ported from verified code but untested against
physical devices — test on the venue PC before event day.
