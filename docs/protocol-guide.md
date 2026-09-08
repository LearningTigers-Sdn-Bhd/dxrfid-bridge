# RFID Reader Protocol Guide (Plain-English Edition)

> **Source**: translated and simplified from the vendor's own
> `高频读写器协议开发指南v1.9.doc` ("High-Frequency Reader Protocol
> Development Guide"). This isn't a word-for-word translation — repetitive
> byte-table structures are summarized into reference tables so this stays
> readable, but nothing substantive from the original has been left out.
>
> For the CRC16 algorithm (reverse-engineered from the compiled driver,
> since the doc alone doesn't give the exact formula) and how this protocol
> has actually been tested, see [`PROJECT_NOTES.md`](./PROJECT_NOTES.md).

## 1. What this reader actually is

This document describes an **HF (High-Frequency, 13.56MHz) RFID reader** —
the kind used for short-range tag reads (centimeters, not meters). It talks
to tags using the ISO15693 standard (and can also handle ISO14443A cards,
which is the Mifare-style standard used in stored-value/e-purse cards).

> ⚠ **Important**: this specific document only covers the HF reader. A
> newer SDK generation exists (see `PROJECT_NOTES.md`) that adds support for
> a completely different, longer-range technology (UHF). Don't assume every
> reader in this product line has the same range/behavior — check the
> actual model number against a datasheet.

## 2. How the reader talks to your computer

Three physical connection options — pick one per device:

| Connection | What it is | Notes |
|---|---|---|
| **Serial (RS232)** | A traditional wired serial cable | Default speed 38,400 baud (can be set to 9,600/19,200/38,400), 1 start bit, 8 data bits, even parity by default |
| **USB** | Plug directly into a computer | Identifies itself with a fixed vendor/product ID pair so your computer recognizes it |
| **Network (Ethernet/TCP)** | Connects over a LAN, like any network device | Default port `6688` |

Regardless of which one you use, the conversation always works the same
way: **your computer sends a command, the reader sends back a response.**
The reader never talks first — it only replies when spoken to.

## 3. The message format

Every command and every response is wrapped in the same "envelope" — a
sequence of bytes with a fixed structure:

**Command you send to the reader:**
```
[Start marker] [Length] [Reader address] [Command type] [Command code] [Data...] [Checksum]
```

**Reply the reader sends back:**
```
[Start marker] [Length] [Reader address] [Command type] [Command code] [Status] [Data...] [Checksum]
```

In plain terms:
- **Start marker** — a fixed byte (`0xEC`) that always begins a message, like the "Dear" at the start of a letter — lets the receiving side know a new message is starting.
- **Length** — how many bytes follow, so the receiver knows when the message ends.
- **Reader address** — which specific reader this is for, if you have more than one on the same line (`0xFF` means "all of them").
- **Command type + code** — together, these say *what* is being asked for (e.g. "scan for tags," "read this stored value," "turn the buzzer on").
- **Status** (replies only) — did it work or not.
- **Data** — the actual payload — parameters going in, or results coming back.
- **Checksum** — a small calculated value that lets the receiver detect if the message got corrupted in transit (a bit like a postal tracking number that only makes sense if nothing was tampered with along the way).

## 4. Command reference, by category

Every command has a **type code** (which category it belongs to) and a
**command code** (which specific action within that category). Grouped
below by what they're actually for, not the order they appear in the
original document.

### A. Reading/writing generic RFID tags — type `0xFE` (ISO15693)
The bread-and-butter commands — this is what you'd use for a typical
attendance/access tag.

| Code | What it does |
|---|---|
| `0x01` | **Scan for tags** — "what tags are in range right now?" (this is the command used throughout this project's mock reader/dashboard) |
| `0x02` | Silence a tag temporarily (tell it to stop responding, useful when multiple tags are present and you want to isolate one) |
| `0x20` | Read one block of data from a tag |
| `0x21` | Write one block of data to a tag |
| `0x22` | Lock a data block (make it permanently read-only) |
| `0x23` | Read multiple data blocks at once |
| `0x24` | Write multiple data blocks at once |
| `0x25` | Put a tag into "selected" state (for addressing one specific tag among several) |
| `0x26` | Put a tag into "ready" state |
| `0x27` | Write the AFI byte (a category/application marker — e.g. "this tag belongs to Event X") |
| `0x28` | Lock the AFI byte permanently |
| `0x29` | Write the DSFID byte (a data-format marker) |
| `0x2A` | Lock the DSFID byte permanently |
| `0x2B` | Get a tag's system info (capabilities, memory size, etc.) |

### B. NXP-brand anti-theft features — type `0xED`
Only relevant if using NXP-brand tags with EAS (Electronic Article
Surveillance — the same tech used for shop anti-theft tags).

| Code | What it does |
|---|---|
| `0xA2` | Turn on the anti-theft alarm bit |
| `0xA3` | Turn it back off |
| `0xA4` | Lock the anti-theft bit permanently |
| `0xA5` | Check the anti-theft bit's current state |

### C. Reader configuration — type `0xA5`
Settings for the reader hardware itself (device address, baud rate, RF
power, which antenna ports are active — see `PROJECT_NOTES.md`'s
"Confirmed hardware/RF specs" section for the actual default values).

| Code | What it does |
|---|---|
| `0x00` | Read the current configuration |
| `0x01` | Write new configuration values |
| `0x02` | Save configuration (persist across power cycles) |

### D. Reader system commands — type `0x78`

| Code | What it does |
|---|---|
| `0x00` | Read basic system info (used by this project's diagnostics/heartbeat check) |
| `0x01` | Search for other devices |

### E. Miscellaneous reader controls

| Type | Code | What it does |
|---|---|---|
| `0x79` | `0x01` | Turn the radio signal on/off |
| `0x80` | `0x01` | Factory reset |
| `0xEE` | `0xEC` | "Pass-through" — send a raw, non-standard command directly to the tag (an escape hatch for advanced/unsupported operations) |

### F. ICODE tag security features — type `0xC0`
ICODE is NXP's specific brand of ISO15693 tags, with extra password/locking
features beyond the base standard.

| Code | What it does |
|---|---|
| `0xB3` | Verify a password |
| `0xB4` | Change a password |
| `0xB5` | Lock a password permanently |
| `0xB6` | Change page-level write protection |
| `0xB7` | Lock page protection permanently |
| `0xA6` | Password-protect the EAS/AFI bits specifically |

### G. Onboard hardware control — type `0xA6` (sub-commands `0x03`–`0x05`)
Controls physical bits on the reader unit itself, not the tags.

| Sub-command | What it does |
|---|---|
| `0x03` | Control onboard hardware (buzzer/relay/indicator — used for feedback like a beep on successful scan) |
| `0x04` | Open a specific antenna port (for multi-antenna reader models) |
| `0x05` | High-power MOS(FET) control — likely used to drive an external device like an electric door lock or turnstile release |

### H. Reading/writing Mifare-style stored-value cards — type `0xFD` (ISO14443A)
A completely separate card family from the ISO15693 tags above — this is
the standard used for e-wallet/stored-value cards (think transit cards).

| Code | What it does |
|---|---|
| `0x01` | Request UID |
| `0x02` | Select a specific tag |
| `0x03` | Read a data block |
| `0x04` | Write a data block |
| `0x05` | Authenticate with a security key (required before read/write) |
| `0x06` | Format a block as an e-wallet |
| `0x07` | Top up (add value to) the e-wallet |
| `0x08` | Back up the wallet's balance to another block |

### I. Network-only special commands — type `0xCB`
Only apply when using the network/Ethernet connection mode.

| Code | What it does |
|---|---|
| `0x01` | Search for a reader's IP address on the network |
| `0x02` | Change a reader's IP address |
| `0x03` | Scan for tags over the network (adds a sequence-number handshake for reliable delivery — see the "known gap" note in `PROJECT_NOTES.md`) |

### J. Security-door/gate-specific commands — type `0xDB`
Only relevant if using the dedicated "gate" hardware models (turnstile/access-control units, not a plain reader).

| Code | What it does |
|---|---|
| `0x01` | Get (and optionally clear) stored entry/exit records |
| `0x02` | Get current people-flow count |
| `0x03` | Clear in/out counters |
| `0x04` | Swap which physical side counts as "in" vs "out" |
| `0x05` | Set the device's onboard clock |
| `0x06` | Read the device's onboard clock |
| `0x07` | Clear all stored records |
| `0x08` | Trigger the door alarm |

## 5. What actually matters for this project

- **Registration desk (USB encoder)**: mainly Section A's scan command
  (`0x01`) to read a tag's UID — see `PROJECT_NOTES.md` for why we
  recommend *not* writing anything to the tag by default.
- **Entrance/exit gates (network mode)**: Section A's scan command, sent
  over the network variant in Section I. If the actual hardware turns out
  to be one of the dedicated gate models, Section J's commands could offload
  in/out direction-sensing and record-keeping onto the hardware itself,
  instead of building that logic in EventzFlow.
