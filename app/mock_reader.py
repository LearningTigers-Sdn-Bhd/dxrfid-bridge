#!/usr/bin/env python3
"""
Mock DXRFID reader — speaks the real EC_RFID/ECRFID wire protocol over TCP,
so the vendor driver (ECRFID.so / EC_RFID.dll, network mode) can connect to
it exactly as it would a physical reader.

Protocol reconstructed from:
  - 高频读写器协议开发指南v1.9.doc (frame layout, ISO15693 inventory 0xFE/0x01)
  - CRC16 table extracted from libECRFID.so (matches standard CRC-16/ARC, poly 0xA001)

Frame layout:
  Host -> Reader: SOF(0xEC) Len ComAdr CmdType CmdCode Data...        CRC16(LSB,MSB)
  Reader -> Host: SOF(0xEC) Len ComAdr CmdType CmdCode Status Data... CRC16(LSB,MSB)
  CRC16 = poly 0xA001, init 0xEEEE, computed over [Len .. Data] (SOF and CRC excluded)

Note: this implements the base (non-"network Flag") frame variant, which is
the unambiguous part of the spec. Real network-mode inventory adds a 2-byte
flow-control Flag field per tag (ack'd by the host) — not reverse-engineered
here byte-exact, since the doc's network-mode tables were too garbled to
trust. Good enough to validate framing/CRC/command dispatch against the real
client library; extend build_frame()/handle_command() if your driver insists
on the Flag-based variant.
"""

import argparse
import random
import socket
import threading
import time

SOF = 0xEC


def crc16(data: bytes, init: int = 0xEEEE) -> int:
    crc = init
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF


def build_frame(com_adr: int, cmd_type: int, cmd_code: int, payload: bytes = b"") -> bytes:
    length = 6 + len(payload)  # Len itself + ComAdr(1) + CmdType/Code(2) + payload + CRC(2)
    body = bytes([length, com_adr, cmd_type, cmd_code]) + payload
    crc = crc16(body)
    return bytes([SOF]) + body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def parse_frame(buf: bytes):
    """Return (frame_dict, remaining_bytes) or (None, buf) if incomplete."""
    idx = buf.find(bytes([SOF]))
    if idx == -1:
        return None, b""
    buf = buf[idx:]
    if len(buf) < 2:
        return None, buf
    length = buf[1]
    total = 1 + length  # SOF + (Len..CRC)
    if len(buf) < total:
        return None, buf
    frame, rest = buf[:total], buf[total:]
    com_adr, cmd_type, cmd_code = frame[2], frame[3], frame[4]
    data = frame[5:-2]
    recv_crc = frame[-2] | (frame[-1] << 8)
    calc_crc = crc16(frame[1:-2])
    return {
        "com_adr": com_adr,
        "cmd_type": cmd_type,
        "cmd_code": cmd_code,
        "data": data,
        "crc_ok": recv_crc == calc_crc,
        "raw": frame,
    }, rest


def fake_tag_uid() -> bytes:
    return bytes([0xE0, 0x04]) + bytes(random.getrandbits(8) for _ in range(6))


def handle_command(cmd, log) -> list:
    """Return list of response frames for a parsed command."""
    com_adr = cmd["com_adr"]
    ct, cc = cmd["cmd_type"], cmd["cmd_code"]
    frames = []

    if ct == 0xFE and cc == 0x01:  # ISO15693 inventory
        n = random.randint(1, 4)
        log(f"  -> inventory: faking {n} tag(s)")
        for _ in range(n):
            dsfid = 0x00
            uid = fake_tag_uid()
            frames.append(build_frame(com_adr, ct, cc, bytes([0x00, dsfid]) + uid))
            time.sleep(0.05)
        frames.append(build_frame(com_adr, ct, cc, bytes([0x00])))  # end-of-inventory
    elif ct == 0x78 and cc == 0x00:  # read system/reader info
        log("  -> GetReaderInfor: faking device info")
        fake_info = b"MOCKD5200\x00" + bytes([1, 9])
        frames.append(build_frame(com_adr, ct, cc, bytes([0x00]) + fake_info))
    else:
        log(f"  -> unhandled cmd_type=0x{ct:02X} cmd_code=0x{cc:02X}, echoing OK status")
        frames.append(build_frame(com_adr, ct, cc, bytes([0x00])))

    return frames


def serve(conn: socket.socket, addr, verbose: bool):
    def log(msg):
        if verbose:
            print(f"[{addr[0]}:{addr[1]}] {msg}")

    log("connected")
    buf = b""
    conn.settimeout(120)
    try:
        while True:
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                break
            buf += chunk
            while True:
                cmd, buf = parse_frame(buf)
                if cmd is None:
                    break
                log(
                    f"recv adr=0x{cmd['com_adr']:02X} "
                    f"type=0x{cmd['cmd_type']:02X} code=0x{cmd['cmd_code']:02X} "
                    f"data={cmd['data'].hex()} crc_ok={cmd['crc_ok']}"
                )
                for resp in handle_command(cmd, log):
                    conn.sendall(resp)
    finally:
        log("disconnected")
        conn.close()


def main():
    ap = argparse.ArgumentParser(description="Mock DXRFID reader (TCP, network mode)")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=6688, help="matches reader default port")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.host, args.port))
    srv.listen(5)
    print(f"Mock DXRFID reader listening on {args.host}:{args.port} (Ctrl+C to stop)")

    try:
        while True:
            conn, addr = srv.accept()
            threading.Thread(target=serve, args=(conn, addr, not args.quiet), daemon=True).start()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        srv.close()


if __name__ == "__main__":
    main()
