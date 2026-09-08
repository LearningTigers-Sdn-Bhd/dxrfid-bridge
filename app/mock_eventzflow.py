#!/usr/bin/env python3
"""
Mock EventzFlow — a stand-in "live server" that logs every request it
receives, so you can visually confirm the dashboard's auto-forward/dedup
logic isn't spamming duplicate tag events before pointing it at the real
EventzFlow API.

Run:
    python3 mock_eventzflow.py --port 9000
Then set the dashboard's API base URL (Settings tab) to:
    http://127.0.0.1:9000/events

Open http://127.0.0.1:9000/ in a browser to watch calls arrive live, with
duplicate UIDs received within a short window flagged in red.
"""
import argparse
import json
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CALLS = deque(maxlen=500)
DUPLICATE_WINDOW = 5  # seconds — flag a UID seen again within this window


def record_call(method, path, headers, body):
    uid = None
    if isinstance(body, dict):
        uid = body.get("uid")

    is_dup = False
    if uid:
        for c in CALLS:
            if c["uid"] == uid and (time.time() - c["ts"]) < DUPLICATE_WINDOW:
                is_dup = True
                break

    CALLS.appendleft({
        "ts": time.time(),
        "method": method,
        "path": path,
        "auth": headers.get("Authorization", ""),
        "content_type": headers.get("Content-Type", ""),
        "body": body,
        "uid": uid,
        "duplicate": is_dup,
    })
    return is_dup


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Mock EventzFlow</title>
<style>
  body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f4f5f7;margin:0;padding:20px;color:#1c1f26;}
  h1{font-size:16px;}
  table{width:100%;border-collapse:collapse;font-size:12px;background:#fff;border:1px solid #e2e4e9;border-radius:8px;overflow:hidden;}
  th,td{padding:6px 8px;text-align:left;border-bottom:1px solid #eee;}
  th{background:#f8f9fb;color:#6b7280;font-weight:600;}
  tr.dup{background:#fee2e2;}
  .pill{padding:2px 6px;border-radius:10px;font-size:10px;font-weight:700;}
  .pill.dup{background:#dc2626;color:#fff;}
  .pill.new{background:#16a34a;color:#fff;}
  code{font-family:ui-monospace,Menlo,monospace;font-size:11px;}
  .stats{margin-bottom:10px;font-size:13px;color:#374151;}
</style></head>
<body>
<h1>Mock EventzFlow — received calls (newest first)</h1>
<div class="stats" id="stats"></div>
<table><thead><tr><th>Time</th><th>Method</th><th>Path</th><th>UID</th><th>Status</th><th>Body</th></tr></thead>
<tbody id="rows"></tbody></table>
<script>
async function refresh() {
  const r = await fetch('/api/calls');
  const calls = await r.json();
  const dupCount = calls.filter(c => c.duplicate).length;
  document.getElementById('stats').textContent =
    `${calls.length} call(s) received — ${dupCount} flagged as duplicate (same UID within ${5}s)`;
  document.getElementById('rows').innerHTML = calls.map(c => `
    <tr class="${c.duplicate ? 'dup' : ''}">
      <td>${new Date(c.ts*1000).toLocaleTimeString('en-GB',{hour12:false})}</td>
      <td>${c.method}</td>
      <td><code>${c.path}</code></td>
      <td><code>${c.uid || ''}</code></td>
      <td><span class="pill ${c.duplicate ? 'dup' : 'new'}">${c.duplicate ? 'DUPLICATE' : 'new'}</span></td>
      <td><code>${JSON.stringify(c.body)}</code></td>
    </tr>`).join('');
}
refresh();
setInterval(refresh, 1500);
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, status=200):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/calls":
            self._json(list(CALLS))
        else:
            # any other GET (e.g. a "verify connection" check) — just say hello
            self._json({"status": "ok", "service": "mock-eventzflow"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"_unparsed": raw.decode(errors="replace")}
        is_dup = record_call("POST", self.path, self.headers, body)
        self._json({"success": True, "duplicate_detected": is_dup})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9000)
    args = ap.parse_args()
    print(f"Mock EventzFlow running at http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    print(f"Point the dashboard's API URL at http://127.0.0.1:{args.port}/events")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
