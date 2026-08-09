"""Yerel canli izleme paneli.

Dis bagimlilik gerektirmez (stdlib http.server). main.py bu modulu
kullanarak arka planda bir web sunucusu baslatir; agents/order/product
aksiyonlari log_event() ile bildirilir, panel bunlari taraycida
otomatik yenilenen bir sayfada gosterir. Olaylar ayni zamanda
activity_log.jsonl dosyasina yazilir, boylece program yeniden
baslatilinca gecmis kaybolmaz.
"""
import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG_FILE = "activity_log.jsonl"
MAX_EVENTS = 500

_lock = threading.Lock()
_events = []
_state = {
    "agents_loaded": 0,
    "automatic_mode": False,
    "last_check": None,
    "started_at": datetime.now().isoformat(),
}
_server = None


def _load_existing():
    try:
        with open(LOG_FILE, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return
    for line in lines[-MAX_EVENTS:]:
        line = line.strip()
        if not line:
            continue
        try:
            _events.append(json.loads(line))
        except json.JSONDecodeError:
            continue


def log_event(kind, message, status="info"):
    """status: 'info' | 'success' | 'error'"""
    entry = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "kind": kind,
        "message": message,
        "status": status,
    }
    with _lock:
        _events.append(entry)
        if len(_events) > MAX_EVENTS:
            del _events[: len(_events) - MAX_EVENTS]
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def set_state(**kwargs):
    with _lock:
        _state.update(kwargs)


def _snapshot():
    with _lock:
        return {"state": dict(_state), "events": list(reversed(_events))}


_PAGE_HTML = """<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<title>AJANS Panel</title>
<style>
  body { font-family: -apple-system, Segoe UI, Arial, sans-serif; background:#0f1117; color:#e6e6e6; margin:0; padding:24px; }
  h1 { font-size:20px; margin:0 0 16px; }
  .cards { display:flex; gap:12px; margin-bottom:20px; flex-wrap:wrap; }
  .card { background:#1a1d27; border:1px solid #2a2e3a; border-radius:8px; padding:12px 16px; min-width:160px; }
  .card .label { font-size:12px; color:#9aa1af; }
  .card .value { font-size:18px; font-weight:600; margin-top:4px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { text-align:left; padding:8px 10px; border-bottom:1px solid #232733; }
  th { color:#9aa1af; font-weight:500; }
  .status-success { color:#4ade80; }
  .status-error { color:#f87171; }
  .status-info { color:#9aa1af; }
  .kind { color:#7aa2f7; font-family:monospace; }
</style>
</head>
<body>
  <h1>AJANS &mdash; Canli Panel</h1>
  <div class="cards" id="cards"></div>
  <table>
    <thead><tr><th>Zaman</th><th>Tip</th><th>Mesaj</th><th>Durum</th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
<script>
async function refresh() {
  try {
    const res = await fetch('/api/data');
    const data = await res.json();
    const s = data.state;
    document.getElementById('cards').innerHTML = `
      <div class="card"><div class="label">Yuklu Ajan</div><div class="value">${s.agents_loaded}</div></div>
      <div class="card"><div class="label">Otomatik Mod</div><div class="value">${s.automatic_mode ? 'Calisiyor' : 'Kapali'}</div></div>
      <div class="card"><div class="label">Son Kontrol</div><div class="value">${s.last_check ? new Date(s.last_check).toLocaleTimeString() : '-'}</div></div>
      <div class="card"><div class="label">Baslangic</div><div class="value">${new Date(s.started_at).toLocaleString()}</div></div>
    `;
    document.getElementById('rows').innerHTML = data.events.map(e => `
      <tr>
        <td>${new Date(e.time).toLocaleTimeString()}</td>
        <td class="kind">${e.kind}</td>
        <td>${e.message}</td>
        <td class="status-${e.status}">${e.status}</td>
      </tr>
    `).join('');
  } catch (err) { /* sunucu henuz hazir olmayabilir, sessizce tekrar dene */ }
}
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, _PAGE_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/data":
            body = json.dumps(_snapshot(), ensure_ascii=False).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
        else:
            self._send(404, b"Not Found", "text/plain; charset=utf-8")

    def _send(self, code, body, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start(port=8765):
    """Paneli arka plan thread'inde baslatir, URL'ini dondurur."""
    global _server
    _load_existing()
    _server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=_server.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{port}"
