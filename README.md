# DXRFID Bridge

Reads RFID tags from a DXRFID reader and forwards them to **EventzFlow**,
with a browser dashboard for the staff running the event.

Two touchpoints:

- **Registration desk** — a USB encoder binds a blank tag to an attendee.
- **Entrance / exit gates** — a network (Ethernet) reader detects tags as
  attendees pass through, and the bridge posts each new sighting to EventzFlow.

---

## Quick start (Windows)

1. Install **Python 3.9 or newer** from <https://www.python.org/downloads/>
   — on the first installer screen, tick **"Add python.exe to PATH"**.
2. Double-click **`START-HERE.bat`**.

That's it. It starts the dashboard, starts the USB encoder helper, and opens
your browser at <http://localhost:5050>. Close the window to stop everything.

There is nothing to `pip install` — this project uses only the Python
standard library.

### No hardware yet?

Double-click **`START-DEMO-no-hardware.bat`** instead. It additionally runs a
fake reader and a fake EventzFlow server, so you get a fully working
dashboard on any PC, with no RFID equipment at all.

## Quick start (macOS / Linux)

```bash
bin/dev          # fake reader + fake server + dashboard, Ctrl+C stops all
```

Or run just the dashboard against a real reader:

```bash
python3 app/server.py --port 5050
```

The dashboard is pure Python and runs on any OS. Only the **USB encoder**
needs Windows (or Linux) — see [`vendor/README.md`](vendor/README.md).

---

## First-time setup

Open the dashboard, go to the **Settings** tab, and fill in:

| Setting | What to put |
|---|---|
| Reader host / port | Your gate reader's IP, e.g. `192.168.1.50`, port `6688` |
| API base URL | Where tag events get posted, e.g. `https://.../api/tags` |
| Authorization value | Your EventzFlow API key, e.g. `Bearer abc123` |
| Encoder helper URL | Leave as `http://127.0.0.1:7000` |

Press **Save Settings**, then on the **Dashboard** tab press **Connect**, and
turn on **Auto-Forward**.

Use the **Test** tab to check each link separately before going live:
*1 · Reader Test* pokes the scanner, *2 · Live Server / API Test* pokes
EventzFlow.

---

## What's in here

```
dxrfid-bridge/
├── START-HERE.bat                 one-click start (Windows)
├── START-DEMO-no-hardware.bat     one-click demo, no hardware needed
├── bin/dev                        same thing for macOS / Linux
├── app/
│   ├── server.py                  the dashboard backend  ← the core
│   ├── index.html                 the dashboard UI (single page, no build step)
│   ├── encoder_service.py         USB encoder helper (Windows registration PC)
│   ├── mock_reader.py             fake reader, speaks the real wire protocol
│   ├── mock_eventzflow.py         fake live server, flags duplicate posts
│   └── mock_client.py             CLI to poke the mock reader directly
├── vendor/
│   ├── ECRFID.dll                 vendor driver — read vendor/README.md first
│   └── README.md                  ⚠ which DLL copy to use, and why
├── tools/
│   └── check_dll.py               verify a DLL before trusting it on a PC
└── docs/
    ├── PROJECT_NOTES.md           full context — start here if picking this up
    ├── protocol-guide.md          the reader's wire protocol, in English
    └── c-api-reference.md         the vendor C API, in English
```

## Which machine runs what

| Machine | Run | Does |
|---|---|---|
| Gate laptop | `START-HERE.bat` | Reads the gate reader over Ethernet, forwards tags to EventzFlow |
| Registration PC | `START-HERE.bat` | Same, plus drives the USB encoder for binding new tags |

`START-HERE.bat` is the same on both — the encoder helper simply reports "no
encoder found" on a machine that hasn't got one plugged in.

---

## Important: the vendor DLL

The USB encoder needs `vendor/ECRFID.dll`, and **it must be the vendor's
`x64/Release` build**. The vendor's other Windows DLLs are *debug* builds
that can never load on a normal PC — they fail with a misleading
`WinError 126`. Full explanation in [`vendor/README.md`](vendor/README.md).

To check any DLL before trusting it (works on any OS):

```bash
python3 tools/check_dll.py vendor/ECRFID.dll
```

## Status

The protocol logic, dashboard, dedup and the EventzFlow API call are working
and tested. **No real RFID hardware has been connected yet** — the reader
protocol and the encoder bindings are verified on paper and against a mock,
not against a physical device. See
[`docs/PROJECT_NOTES.md`](docs/PROJECT_NOTES.md) for an honest breakdown of
what is proven vs. still assumed, and what to check first when the hardware
arrives.
