"""DXRFID Bridge — EventzFlow RFID desk + gate companion.

Online-first parity with the RfiDex P5/P7 contract, in stdlib-only Python.
Modules:

    config    — persisted settings, data dir, atomic save
    client    — EventzFlow device API (/v1/rfid/*) client
    printer   — event-printing hook (health + reprint, fire-and-report)
    protocol  — 0xEC gate reader wire protocol (CRC16, frames)
    encoder   — ECRFID.dll ctypes wrapper (desk USB encoder)
    desk      — desk flow: scan/search → check-in → print → bind
    gate      — gate loop: inventory → dedup → observation batch
    state     — shared runtime state + operator event log
    server    — HTTP API + serves the dark ops console UI
"""

__version__ = "0.3.0"
