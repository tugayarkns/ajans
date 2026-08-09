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
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AJANS Panel</title>
<style>
  :root {
    --bg: #0b0d12;
    --panel: #14161e;
    --panel-border: #262a38;
    --text: #e8e9ed;
    --muted: #8b90a0;
    --accent: #6d8dfa;
    --green: #34d399;
    --red: #f87171;
    --gray: #8b90a0;
  }
  * { box-sizing: border-box; }
  body {
    font-family: "Segoe UI", -apple-system, Inter, Arial, sans-serif;
    background:
      radial-gradient(1200px 500px at 15% -10%, rgba(109,141,250,0.10), transparent),
      var(--bg);
    color: var(--text);
    margin: 0;
    padding: 32px 40px 60px;
    min-height: 100vh;
  }
  .topbar { display:flex; align-items:center; justify-content:space-between; margin-bottom:28px; flex-wrap:wrap; gap:12px; }
  .brand { display:flex; align-items:center; gap:12px; }
  .brand .mark {
    width:36px; height:36px; border-radius:10px;
    background:linear-gradient(135deg, var(--accent), #a78bfa);
    display:flex; align-items:center; justify-content:center;
    font-weight:700; font-size:15px; color:#0b0d12;
  }
  .brand h1 { font-size:18px; margin:0; font-weight:600; letter-spacing:.2px; }
  .brand .sub { font-size:12px; color:var(--muted); margin-top:2px; }
  .live { display:flex; align-items:center; gap:8px; font-size:12px; color:var(--muted); background:var(--panel); border:1px solid var(--panel-border); padding:6px 12px; border-radius:999px; }
  .live .dot { width:8px; height:8px; border-radius:50%; background:var(--green); box-shadow:0 0 0 0 rgba(52,211,153,.6); animation:pulse 2s infinite; }
  @keyframes pulse {
    0% { box-shadow:0 0 0 0 rgba(52,211,153,.55); }
    70% { box-shadow:0 0 0 7px rgba(52,211,153,0); }
    100% { box-shadow:0 0 0 0 rgba(52,211,153,0); }
  }
  .cards { display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:14px; margin-bottom:28px; }
  .card { background:var(--panel); border:1px solid var(--panel-border); border-radius:12px; padding:16px 18px; position:relative; overflow:hidden; }
  .card::before { content:""; position:absolute; inset:0 auto 0 0; width:3px; background:var(--accent); opacity:.8; }
  .card .label { font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.6px; font-weight:600; }
  .card .value { font-size:22px; font-weight:700; margin-top:8px; letter-spacing:.2px; }
  .card .value.on { color:var(--green); }
  .card .value.off { color:var(--muted); }
  .panel-section { background:var(--panel); border:1px solid var(--panel-border); border-radius:12px; overflow:hidden; }
  .panel-section .head { padding:16px 20px; border-bottom:1px solid var(--panel-border); display:flex; align-items:center; justify-content:space-between; }
  .panel-section .head h2 { font-size:14px; margin:0; font-weight:600; }
  .panel-section .head .count { font-size:12px; color:var(--muted); }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { text-align:left; padding:11px 20px; border-bottom:1px solid var(--panel-border); }
  th { color:var(--muted); font-weight:600; font-size:11px; text-transform:uppercase; letter-spacing:.5px; }
  tbody tr:hover { background:rgba(255,255,255,0.02); }
  tbody tr:last-child td { border-bottom:none; }
  td.time { color:var(--muted); white-space:nowrap; font-variant-numeric:tabular-nums; }
  .kind { color:var(--accent); font-family:ui-monospace, SFMono-Regular, Consolas, monospace; font-size:12px; background:rgba(109,141,250,0.1); padding:3px 8px; border-radius:6px; }
  .badge { display:inline-flex; align-items:center; gap:6px; font-size:11px; font-weight:600; padding:3px 10px; border-radius:999px; text-transform:uppercase; letter-spacing:.4px; }
  .badge::before { content:""; width:6px; height:6px; border-radius:50%; }
  .badge.success { color:var(--green); background:rgba(52,211,153,0.12); }
  .badge.success::before { background:var(--green); }
  .badge.error { color:var(--red); background:rgba(248,113,113,0.12); }
  .badge.error::before { background:var(--red); }
  .badge.info { color:var(--gray); background:rgba(139,144,160,0.12); }
  .badge.info::before { background:var(--gray); }
  .empty { padding:40px 20px; text-align:center; color:var(--muted); font-size:13px; }
</style>
</head>
<body>
  <div class="topbar">
    <div class="brand">
      <div class="mark">A</div>
      <div>
        <h1>AJANS Panel</h1>
        <div class="sub">Multi-agent siparis yonetimi &middot; canli izleme</div>
      </div>
    </div>
    <div class="live"><span class="dot"></span> Canli &middot; 2sn'de bir yenilenir</div>
  </div>

  <div class="cards" id="cards"></div>

  <div class="panel-section">
    <div class="head">
      <h2>Olay Akisi</h2>
      <span class="count" id="event-count"></span>
    </div>
    <table>
      <thead><tr><th>Zaman</th><th>Tip</th><th>Mesaj</th><th>Durum</th></tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </div>

<script>
function timeAgo(iso) {
  return new Date(iso).toLocaleTimeString('tr-TR');
}
async function refresh() {
  try {
    const res = await fetch('/api/data');
    const data = await res.json();
    const s = data.state;
    document.getElementById('cards').innerHTML = `
      <div class="card"><div class="label">Yuklu Ajan</div><div class="value">${s.agents_loaded}</div></div>
      <div class="card"><div class="label">Otomatik Mod</div><div class="value ${s.automatic_mode ? 'on' : 'off'}">${s.automatic_mode ? 'Calisiyor' : 'Kapali'}</div></div>
      <div class="card"><div class="label">Son Kontrol</div><div class="value">${s.last_check ? timeAgo(s.last_check) : '—'}</div></div>
      <div class="card"><div class="label">Baslangic</div><div class="value">${new Date(s.started_at).toLocaleString('tr-TR')}</div></div>
    `;
    const countEl = document.getElementById('event-count');
    countEl.textContent = data.events.length ? `${data.events.length} olay` : '';
    document.getElementById('rows').innerHTML = data.events.length ? data.events.map(e => `
      <tr>
        <td class="time">${timeAgo(e.time)}</td>
        <td><span class="kind">${e.kind}</span></td>
        <td>${e.message}</td>
        <td><span class="badge ${e.status}">${e.status}</span></td>
      </tr>
    `).join('') : '<tr><td colspan="4" class="empty">Henuz olay yok — bir siparis veya urun islendiginde burada gorunecek.</td></tr>';
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
