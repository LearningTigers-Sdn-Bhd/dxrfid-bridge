#!/usr/bin/env python3
"""DXRFID Bridge — EventzFlow RFID desk + gate companion.

This is now a thin entry point; the implementation lives in the bridge/
package (client, desk, gate, encoder, printer, server). The old protocol
debug dashboard has been replaced by the ops console UI in ui/index.html.

Run (development):
    python3 server.py [--port 5050] [--open] [--gate]

The standalone debug pieces are still here for hardware work:
    python3 mock_reader.py       fake gate reader on TCP
    python3 mock_eventzflow.py   fake backend
    python3 encoder_service.py   standalone USB encoder helper

Pure stdlib, no pip installs required.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bridge.server import serve  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="DXRFID Bridge console")
    ap.add_argument("--port", type=int, default=5050)
    ap.add_argument("--open", action="store_true",
                    help="open the console in a browser")
    ap.add_argument("--gate", action="store_true",
                    help="start the gate watch immediately")
    args = ap.parse_args()
    # Frozen exe (double-clicked): open the console automatically —
    # nobody should have to pass flags to a .exe.
    open_browser = args.open or bool(getattr(sys, "frozen", False))
    serve(port=args.port, open_browser=open_browser, autostart_gate=args.gate)


if __name__ == "__main__":
    main()
