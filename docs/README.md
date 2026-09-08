# Documentation Index

Start here. Pick based on what you're trying to do:

| Doc | Read this when you want to... |
|---|---|
| [`PROJECT_NOTES.md`](./PROJECT_NOTES.md) | Get full context on this project — what's been built, what's tested vs. still assumed, the EventzFlow attendance-tracking data model, future plans. **Start here if picking this project back up.** |
| [`protocol-guide.md`](./protocol-guide.md) | Understand the reader's wire protocol — what commands exist, how a message is structured, what each command category is for. Plain-English translation of the vendor's original Chinese doc. |
| [`c-api-reference.md`](./c-api-reference.md) | Look up a specific SDK function's parameters and purpose while writing integration code. Plain-English translation of the vendor's original Chinese C API doc. |

## A note on these translations

`protocol-guide.md` and `c-api-reference.md` are **translated and
simplified**, not literal word-for-word conversions — repetitive low-level
byte tables from the originals are condensed into scannable reference
tables, and every entry gets a plain-English one-line explanation instead
of just a Chinese label. Nothing substantive has been cut; if you need the
original byte-level tables (e.g. exact request/response frame examples for
one specific command), refer back to the source files in the **vendor SDK
package** (not included in this repo — it's the unzipped `D5XXX_DXRFID`
distribution from the reader supplier):
- `高频读写器协议开发指南v1.9.doc` — the wire protocol spec
- `C API demo/C API说明文档.docx` — the C API function reference
