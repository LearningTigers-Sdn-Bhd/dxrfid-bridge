#!/usr/bin/env python3
"""
Test client for mock_reader.py — sends a real command frame to the mock
reader over TCP and prints whatever comes back.

Usage:
  python3 mock_client.py                      # inventory (default)
  python3 mock_client.py --cmd info           # GetReaderInfor
  python3 mock_client.py --host 127.0.0.1 --port 6688
"""

import argparse
import socket

from mock_reader import SOF, crc16, parse_frame

COMMANDS = {
    "inventory": (0xFE, 0x01, bytes([0x00])),  # ISO15693 inventory, Mode=0x00
    "info": (0x78, 0x00, b""),                 # GetReaderInfor
}


def build_request(com_adr: int, cmd_type: int, cmd_code: int, payload: bytes = b"") -> bytes:
    length = 6 + len(payload)
    body = bytes([length, com_adr, cmd_type, cmd_code]) + payload
    crc = crc16(body)
    return bytes([SOF]) + body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def main():
    ap = argparse.ArgumentParser(description="Send a test command to mock_reader.py")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=6688)
    ap.add_argument("--cmd", choices=COMMANDS.keys(), default="inventory")
    ap.add_argument("--com-adr", type=lambda x: int(x, 0), default=0xFF, help="reader address, default 0xFF (broadcast)")
    args = ap.parse_args()

    cmd_type, cmd_code, payload = COMMANDS[args.cmd]
    req = build_request(args.com_adr, cmd_type, cmd_code, payload)
    print(f"-> sending {args.cmd}: {req.hex()}")

    s = socket.create_connection((args.host, args.port), timeout=5)
    s.sendall(req)

    buf = b""
    s.settimeout(3)
    try:
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
            while True:
                frame, buf = parse_frame(buf)
                if frame is None:
                    break
                print(
                    f"<- adr=0x{frame['com_adr']:02X} "
                    f"type=0x{frame['cmd_type']:02X} code=0x{frame['cmd_code']:02X} "
                    f"data={frame['data'].hex()} crc_ok={frame['crc_ok']}"
                )
    except socket.timeout:
        pass
    finally:
        s.close()


if __name__ == "__main__":
    main()
