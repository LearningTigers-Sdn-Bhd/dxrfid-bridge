"""0xEC gate reader wire protocol — ported verbatim from mock_reader.py.

Frame layout (base variant):
  Host -> Reader: SOF(0xEC) Len ComAdr CmdType CmdCode Data...        CRC16(LSB,MSB)
  Reader -> Host: SOF(0xEC) Len ComAdr CmdType CmdCode Status Data... CRC16(LSB,MSB)
  CRC16 = poly 0xA001, init 0xEEEE, computed over [Len .. Data]

The gate-side limitation from mock_reader.py still applies: the "network
Flag" flow-control variant isn't byte-exact here. The existing bridge has
driven a real gate with this framing; RfiDex's ec.rs handles the fuller
candidate set. If your gate model insists on the Flag variant, the fix
lands in build_frame()/the inventory exchange, not anywhere else.
"""

SOF = 0xEC

CMD_INVENTORY = (0xFE, 0x01)      # ISO15693 inventory
CMD_READER_INFO = (0x78, 0x00)    # GetReaderInfor


def crc16(data: bytes, init: int = 0xEEEE) -> int:
    crc = init
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF


def build_frame(com_adr: int, cmd_type: int, cmd_code: int,
                payload: bytes = b"") -> bytes:
    length = 6 + len(payload)  # Len + ComAdr + CmdType/Code + payload + CRC
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
    recv_crc = frame[-2] | (frame[-1] << 8)
    calc_crc = crc16(frame[1:-2])
    return {
        "com_adr": frame[2],
        "cmd_type": frame[3],
        "cmd_code": frame[4],
        "data": frame[5:-2],
        "crc_ok": recv_crc == calc_crc,
        "raw": frame,
    }, rest


def parse_inventory_tag(data: bytes) -> dict | None:
    """One inventory response frame's data → tag, or None for end-of-inventory.

    Layout from the mock (matches the real gate the bridge was built against):
        [status=0x00, dsfid, uid(8)]  — a tag
        [status=0x00]                 — end of inventory round
    """
    if len(data) <= 1:
        return None
    dsfid = data[1]
    uid = data[2:]
    if not uid:
        return None
    return {"dsfid": dsfid, "uid_raw": uid, "uid_hex": uid.hex().upper()}
