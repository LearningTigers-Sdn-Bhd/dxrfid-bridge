# C API Reference (Plain-English Edition)

> **Source**: translated and simplified from the vendor's own
> `C API demo/C API说明文档.docx`. This is the older SDK generation's
> function list (`EC_RFID.dll`/`.lib`) — every function returns `TRUE` on
> success unless noted, and all of them take a shared `RFData` buffer
> struct that holds the raw bytes sent/received under the hood (you don't
> need to touch its contents directly — just pass the same struct instance
> into each call).
>
> The newer SDK generation (`ECRFID.dll`, used by `encoder_service.py` in
> this project) has a different, cleaner function set — see the header
> `new demo/example/c++/ECRFID.h` directly, it's short and self-explanatory
> once you've read this document's concepts.

## Using this from different languages

The vendor demonstrates linking this DLL from four languages. If you're
not using one of these, the pattern is the same regardless of language:
load the DLL, declare each function's signature to match the table below,
call it.

| Language | How you link it |
|---|---|
| **C++** | `#include "EC_RFID.h"` + link `EC_RFID.lib` |
| **C#** | `[DllImport("EC_RFID.DLL", ...)]` attribute per function |
| **Delphi** | `external 'EC_RFID.dll'` per function declaration |
| **VB6** | Similar `Declare Function ... Lib "EC_RFID.dll"` pattern (see the vendor's VB6 demo) |

**Type mapping cheat-sheet** (what a C++ type becomes in other languages):

| C++ | C# | Delphi |
|---|---|---|
| `RFData *` | `ref RFData` | `P_RFdata` |
| `BOOL` | `bool` | `BOOL` |
| `UINT8` | `byte` | `Byte` |
| `UINT16` | `ushort` | `Word` |
| `UINT32` | `uint` | — |
| `UINT8 *` | `byte[]` | `PChar` |
| `const char*` | `string`/`IntPtr` | `PChar` |

## Setting up a connection

Do one of these first, before calling anything else.

| Function | What it does |
|---|---|
| `EC_EnumCOM()` | Lists every available serial port on the machine (e.g. `"COM1;COM2;COM3;"`) — call this first if using serial, to know what to pass to the next function |
| `EC_RFIDopenCOM(port, baudRate=38400, byteSize=8, parityBit=even, stopBit=1)` | Opens a serial connection |
| `EC_RFIDopenUSB(VID=0xFFFE, PID=0x0091, DEVINDEX=0)` | Opens a USB connection. `DEVINDEX` picks which device if more than one matching USB reader is plugged in |
| `EC_NETInit()` | Initializes networking — call once at program start if using network mode |
| `EC_EC_SetNETIP(ip)` | Sets which reader IP to talk to (network port is fixed at `6688`) |
| `EC_NETExit()` | Releases networking resources — call once at program shutdown |
| `EC_RFIDclose()` | Closes whichever connection is currently open (serial, USB, or network) |
| `EC_GetCommType()` | Reports which connection is currently active: `-1` none, `0` serial, `1` USB, `2` network |

## Basic device operations

| Function | What it does |
|---|---|
| `EC_OpenDevice(buf)` | Opens/initializes the device after a connection is established |
| `EC_GetDeviceInfoVersion(buf)` | Retrieves the device's info/version string |
| `EC_RestartCfgBlock(buf)` | Factory-resets the reader's configuration |
| `EC_Open_CloseRFPower(buf, on)` | Turns the radio signal on (`1`) or off (`0`) |
| `EC_SetBuzzerState(buf, state)` | Controls the onboard beeper: `0` off, `1` on, `2` blinking |
| `EC_SetRelayState(buf, state)` | Controls an onboard relay output the same way (off/on/blinking) — useful for driving an indicator light or a simple lock release |

## Network-specific functions

Only relevant when connected via network mode.

| Function | What it does |
|---|---|
| `EC_NetScanDeviceInfo(buf)` | Searches the network for reader devices |
| `EC_NetWriteDeviceInfo(buf, ip, mask, gateway)` | Changes a reader's network settings (new IP/subnet/gateway, each as 4 raw bytes) |
| `EC_NetInventoryACK(buf, sequenceNumber)` | Acknowledges receipt of one scan result over the network — part of the network scanning handshake described in the protocol guide |

## Scanning for tags

| Function | What it does |
|---|---|
| `EC_OpenAnt_One(buf, antennaNumber)` | Selects a specific antenna port (for multi-antenna reader models) |
| `EC_InventoryTag(buf, antOneFlag)` | Scans for tags in range. If `antOneFlag` is `0x04`, only the specifically-opened antenna is scanned |
| `EC_GetOneTagInfo(buf, uid, addressed)` | Gets details on one specific tag. Set `addressed=1` and pass its UID to target one tag among several present |

## Reading and writing tag memory

Every one of these takes a `uid` + an `addressed` flag (`1` = target this
specific tag by UID; useful when multiple tags are in range at once).

| Function | What it does |
|---|---|
| `EC_ReadCardOneBlock(buf, uid, addressed, block)` | Reads one memory block |
| `EC_ReadCardMultBlock(buf, uid, addressed, startBlock, numBlocks)` | Reads several blocks at once |
| `EC_WriteCardOneBlock(buf, uid, addressed, block, data[4 bytes])` | Writes one memory block |
| `EC_WriteCardMultBlock(buf, uid, addressed, startBlock, numBlocks, data)` | Writes several blocks at once (`data` is `4 × numBlocks` bytes) |
| `EC_LockCardOneBlock(buf, uid, addressed, startBlock, numBlocks)` | Permanently locks blocks as read-only |

## Tag identity fields (AFI / DSFID)

AFI is a one-byte "category" marker; DSFID is a one-byte "data format"
marker. Both can optionally be locked so they can never be changed again.

| Function | What it does |
|---|---|
| `EC_WriteOneTagAFI(buf, uid, addressed, afi)` | Sets the AFI byte |
| `EC_LockOneTagAFI(buf, uid, addressed)` | Locks it permanently |
| `EC_WriteOneTagDSFID(buf, uid, addressed, dsfid)` | Sets the DSFID byte |
| `EC_LockOneTagDSFID(buf, uid, addressed)` | Locks it permanently |

## Anti-theft (EAS) — NXP tags only

| Function | What it does |
|---|---|
| `EC_EnableOneTagEAS(buf, uid, addressed)` | Turns the anti-theft alarm bit on |
| `EC_BanOneTagEAS(buf, uid, addressed)` | Turns it back off |
| `EC_LockOneTagEAS(buf, uid, addressed)` | Locks the bit permanently |
| `EC_CheckOneTagEAS(buf, uid, addressed)` | Checks its current state |

## Passwords and page protection

| Function | What it does |
|---|---|
| `EC_VerifyPassword(buf, uid, passType, password[8 bytes])` | Verifies a password. `passType` selects which permission it unlocks: Read `0x01`, Write `0x02`, Privacy `0x04`, Destroy `0x08`, EAS/AFI `0x10` |
| `EC_ModifyPassword(buf, uid, passType, password[8 bytes])` | Changes a password |
| `EC_LockPassword(buf, uid, passType)` | Locks a password so it can never be changed again |
| `EC_EASAFIPasswordProtect(buf, uid, type)` | Requires a password before EAS/AFI can be changed |
| `EC_RunPageProtect(buf, uid, pageNumber, condition)` | Sets write-protection rules on a memory page |
| `EC_LockPageProtect(buf, uid, pageNumber)` | Locks that protection setting permanently |

## Advanced / escape hatch

| Function | What it does |
|---|---|
| `EC_OSFPDataSend(buf, data, length)` | Sends a raw, non-standard command straight to the tag — for operations not covered by any other function here |

## Mifare-style stored-value cards (ISO14443A)

A separate card family from everything above — used for e-wallet/stored-value
cards. Requires authenticating with a security key before reading/writing.

| Function | What it does |
|---|---|
| `EC_ISO14443AInventoryTag(buf)` | Scans for ISO14443A cards in range |
| `EC_ISO14443AKeyAuthentication(buf, uid, block, keyType, key[6 bytes])` | Authenticates before accessing a block. `keyType`: `0` = Key A, `1` = Key B |
| `EC_ISO14443AReadBlock(buf, uid, startBlock, numBlocks, keyType, key)` | Reads block(s) |
| `EC_ISO14443AWriteBlock(buf, uid, startBlock, numBlocks, keyType, key, data)` | Writes block(s) |
| `EC_ISO14443AFormatWriteBlock(buf, uid, block, keyType, key, data[4 bytes])` | Formats a block as an e-wallet |
| `EC_ISO14443ARechargeWriteBlock(buf, uid, block, cmd, keyType, key, amount[4 bytes, hex])` | Adds or deducts value from the wallet |
| `EC_ISO14443ABackWriteBlock(buf, uid, sourceBlock, targetBlock, keyType, key)` | Backs up a wallet's balance to another block |

## Security-door / gate hardware functions

Only relevant if the physical unit is one of the dedicated "gate"/access-
control hardware models (see the protocol guide's Section J).

| Function | What it does |
|---|---|
| `EC_DoorTakeRecords(buf, sequenceNumber, flag)` | Retrieves stored entry/exit records. `flag`: `0x00` just fetch, `0x01` delete the previously-fetched batch then fetch new, `0x02` start reading from the very first record |
| `EC_GetInOutInfo(buf)` | Gets current in/out people counts |
| `EC_ClearInOutInfo(buf, which)` | Resets counters: `0x01` in-count, `0x02` out-count, `0x03` both |
| `EC_InOutExchange(buf)` | Swaps which physical direction counts as "in" vs "out" |
| `EC_SetSysTimer(buf, time[6 bytes, BCD])` | Sets the device's onboard clock — bytes are year/month/day/hour/min/sec, e.g. `20,11,05,12,00,00` = 2020-11-05 12:00:00 |
| `EC_GetSysTimer(buf)` | Reads the device's onboard clock |
| `EC_ClearAllRecordData(buf)` | Wipes all stored records |
| `EC_AllDoorAlarm(buf, mode)` | Triggers an alarm: `0` = unified alarm across all doors, `1` = per-door individual alarm |

## Raw fallback

| Function | What it does |
|---|---|
| `EC_Write(data, length)` | Sends raw bytes directly, bypassing all the higher-level functions above |
| `EC_Read(buf)` | Reads whatever raw bytes come back into `buf->recvData` |

## What actually matters for this project

- **Registration desk (USB encoder)**: `EC_RFIDopenUSB` → `EC_InventoryTag` → `EC_GetOneTagInfo` covers the recommended UID-read-only approach from `PROJECT_NOTES.md`. The AFI/DSFID/password functions are only needed if you later decide to write data onto tags (Option B in that doc).
- **Entrance/exit gates**: if using the newer SDK/network mode, see `ECRFID.h` directly instead — cleaner API, and what `mock_reader.py`/`server.py` in this project are built against.
- Note this whole document describes the **older** SDK generation
  (`EC_RFID.dll`) — cross-check against `PROJECT_NOTES.md`'s hardware specs
  section for which generation your actual ordered hardware uses.
