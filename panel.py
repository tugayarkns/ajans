"""Yerel canli izleme paneli.

Dis bagimlilik gerektirmez (stdlib http.server). main.py bu modulu
kullanarak arka planda bir web sunucusu baslatir; agents/order/product
aksiyonlari log_event() ile bildirilir, panel bunlari taraycida
otomatik yenilenen bir sayfada gosterir. Olaylar ayni zamanda
activity_log.jsonl dosyasina yazilir, boylece program yeniden
baslatilinca gecmis kaybolmaz.
"""
import json
import re
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG_FILE = "activity_log.jsonl"
PENDING_FILE = "pending_products.json"
MAX_EVENTS = 500

_lock = threading.Lock()
_events = []
_pending = []
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


def _load_pending():
    try:
        with open(PENDING_FILE, encoding="utf-8") as f:
            _pending.extend(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return


def _save_pending():
    with open(PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump(_pending, f, ensure_ascii=False, indent=2)


def add_pending_products(items):
    """Onay bekleyen yeni urun adaylarini panele ekler (orn. DSers'tan gelen adaylar).

    Her aday, panele eklenmeden ONCE PRODUCT_AGENT'tan gecirilip nihai
    baslik/aciklamasi uretilir (description_html eksikse). Boylece kullanici
    panelde her zaman satisa hazir, son hali gordugu bir urunu onaylar —
    onay sonrasi arka planda hicbir icerik uretimi/degisimi olmaz.
    """
    prepared = []
    for item in items:
        if not item.get("description_html"):
            title, description_html, needs_review = _generate_listing(item)
            item = {
                **item,
                "title": title,
                "description_html": description_html,
                "needs_review": needs_review,
            }
        if not item.get("image_urls") and item.get("image_url"):
            item["image_urls"] = [item["image_url"]]
        prepared.append(item)
    with _lock:
        _pending.extend(prepared)
        _save_pending()
    return prepared


def get_pending_product(product_id):
    with _lock:
        return next((p for p in _pending if p["id"] == product_id), None)


def remove_pending_product(product_id):
    with _lock:
        _pending[:] = [p for p in _pending if p["id"] != product_id]
        _save_pending()


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
        return {
            "state": dict(_state),
            "events": list(reversed(_events)),
            "pending": list(_pending),
        }


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
    --amber: #f5a623;
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
  .pending-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(280px, 1fr)); gap:14px; padding:20px; }
  .pcard { background:#0f1118; border:1px solid var(--panel-border); border-radius:10px; overflow:hidden; display:flex; flex-direction:column; }
  .pcard img { width:100%; height:160px; object-fit:cover; background:#1a1c26; }
  .pcard .thumbs { display:flex; gap:4px; padding:6px 6px 0; }
  .pcard .thumbs img { width:36px; height:36px; border-radius:6px; flex-shrink:0; cursor:pointer; border:1px solid var(--panel-border); }
  .pcard .thumbs img.active { border-color:var(--accent); }
  .pcard .thumbs .more { width:36px; height:36px; border-radius:6px; background:#1a1c26; display:flex; align-items:center; justify-content:center; font-size:10px; color:var(--muted); flex-shrink:0; }
  .pcard .body { padding:12px 14px 14px; display:flex; flex-direction:column; gap:6px; flex:1; }
  .pcard .title { font-size:13px; line-height:1.35; font-weight:600; }
  .pcard .price { font-size:13px; color:var(--text); font-weight:700; }
  .pcard .cost { font-size:11px; color:var(--muted); }
  .pcard .margin { font-size:12px; font-weight:700; display:flex; align-items:center; gap:6px; margin-top:2px; }
  .pcard .margin .pct { font-size:11px; font-weight:600; padding:2px 7px; border-radius:999px; }
  .pcard .desc { font-size:11.5px; line-height:1.5; color:var(--muted); background:#0b0d12; border:1px solid var(--panel-border); border-radius:8px; padding:8px 10px; max-height:70px; overflow:hidden; position:relative; }
  .pcard .desc.expanded { max-height:none; }
  .pcard .desc-toggle { font-size:11px; color:var(--accent); cursor:pointer; background:none; border:none; padding:2px 0; text-align:left; font-weight:600; }
  .pcard .actions { display:flex; gap:8px; margin-top:auto; padding-top:8px; }
  .pcard button { flex:1; border:none; border-radius:8px; padding:8px 0; font-size:12px; font-weight:600; cursor:pointer; }
  .btn-approve { background:var(--green); color:#0b0d12; }
  .btn-approve:hover { filter:brightness(1.08); }
  .btn-reject { background:rgba(248,113,113,0.12); color:var(--red); }
  .btn-reject:hover { background:rgba(248,113,113,0.2); }
  .pcard button:disabled { opacity:.5; cursor:not-allowed; }
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

  <div class="panel-section" style="margin-bottom:28px;">
    <div class="head">
      <h2>Onay Bekleyen Yeni Urunler</h2>
      <span class="count" id="pending-count"></span>
    </div>
    <div class="pending-grid" id="pending-grid"></div>
  </div>

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
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = String(str);
  return div.innerHTML;
}
let _lastPendingSig = null;
async function decide(id, action, btn) {
  const card = btn.closest('.pcard');
  card.querySelectorAll('button').forEach(b => b.disabled = true);
  btn.textContent = action === 'approve' ? 'Yayinlaniyor...' : 'Kaldiriliyor...';
  try {
    const res = await fetch('/api/' + action, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id })
    });
    if (!res.ok) throw new Error(await res.text());
  } catch (err) {
    alert('Islem basarisiz: ' + err.message);
    card.querySelectorAll('button').forEach(b => b.disabled = false);
    btn.textContent = action === 'approve' ? 'Onayla ve Yayinla' : 'Reddet';
    return;
  }
  refresh();
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
    const pending = data.pending || [];
    document.getElementById('pending-count').textContent = pending.length ? `${pending.length} urun` : '';
    const pendingSig = pending.map(p => p.id).join(',');
    if (pendingSig !== _lastPendingSig) {
    _lastPendingSig = pendingSig;
    document.getElementById('pending-grid').innerHTML = pending.length ? pending.map(p => {
      const cur = p.currency || 'EUR';
      const shipping = p.shipping_cost || 0;
      const totalCost = (p.cost_min || 0) + shipping;
      const sell = p.sell_price_min || 0;
      const profit = sell - totalCost;
      const marginPct = sell > 0 ? (profit / sell * 100) : 0;
      const marginColor = marginPct >= 40 ? 'var(--green)' : marginPct >= 20 ? 'var(--amber)' : 'var(--red)';
      const images = (p.image_urls && p.image_urls.length) ? p.image_urls : (p.image_url ? [p.image_url] : []);
      const descText = (p.description_html || '').replace(/<[^>]+>/g, ' ').replace(/\\s+/g, ' ').trim();
      const cardId = 'p_' + escapeHtml(p.id);
      const thumbs = images.slice(0, 6).map((url, i) => `<img src="${escapeHtml(url)}" referrerpolicy="no-referrer" class="${i===0?'active':''}" onclick="document.getElementById('${cardId}_main').src=this.src; this.parentElement.querySelectorAll('img').forEach(im=>im.classList.remove('active')); this.classList.add('active');">`).join('');
      const moreCount = images.length - 6;
      return `
      <div class="pcard" data-id="${escapeHtml(p.id)}">
        <img id="${cardId}_main" src="${escapeHtml(images[0] || '')}" referrerpolicy="no-referrer" alt="">
        ${images.length > 1 ? `<div class="thumbs">${thumbs}${moreCount > 0 ? `<div class="more">+${moreCount}</div>` : ''}</div>` : ''}
        <div class="body">
          ${p.needs_review ? '<div class="desc" style="color:var(--amber); border-color:var(--amber);">⚠️ PRODUCT_AGENT bu urunde bir sorun isaretledi (fiyat/aciklama eksik olabilir) — onaylamadan once dikkatlice kontrol edin.</div>' : ''}
          <div class="title">${escapeHtml(p.title)}</div>
          <div class="price">Satis: ${cur} ${sell.toFixed(2)}${p.sell_price_max && p.sell_price_max !== sell ? '–' + p.sell_price_max.toFixed(2) : ''}</div>
          <div class="cost">Maliyet (urun+kargo): ${cur} ${totalCost.toFixed(2)} (urun ${cur} ${(p.cost_min || 0).toFixed(2)} + kargo ${cur} ${shipping.toFixed(2)})</div>
          <div class="margin" style="color:${marginColor}">
            Kar: ${cur} ${profit.toFixed(2)}
            <span class="pct" style="background:color-mix(in srgb, ${marginColor} 15%, transparent); color:${marginColor}">%${marginPct.toFixed(0)}</span>
          </div>
          ${descText ? `
          <div class="desc" id="${cardId}_desc">${escapeHtml(descText)}</div>
          <button class="desc-toggle" onclick="const d=document.getElementById('${cardId}_desc'); d.classList.toggle('expanded'); this.textContent = d.classList.contains('expanded') ? 'Daralt' : 'Tumunu gor';">Tumunu gor</button>
          ` : '<div class="desc" style="color:var(--red)">Aciklama uretilememis — onaylamadan once kontrol edin.</div>'}
          <div class="actions">
            <button class="btn-approve" onclick="decide('${p.id}','approve',this)">Onayla ve Yayinla</button>
            <button class="btn-reject" onclick="decide('${p.id}','reject',this)">Reddet</button>
          </div>
        </div>
      </div>
    `;
    }).join('') : '<div class="empty" style="grid-column:1/-1;">Onay bekleyen urun yok.</div>';
    }
    const countEl = document.getElementById('event-count');
    countEl.textContent = data.events.length ? `${data.events.length} olay` : '';
    document.getElementById('rows').innerHTML = data.events.length ? data.events.map(e => `
      <tr>
        <td class="time">${timeAgo(e.time)}</td>
        <td><span class="kind">${escapeHtml(e.kind)}</span></td>
        <td>${escapeHtml(e.message)}</td>
        <td><span class="badge ${escapeHtml(e.status)}">${escapeHtml(e.status)}</span></td>
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


def parse_agent_listing(raw_text, fallback_title):
    """PRODUCT_AGENT'in serbest metin ciktisindan MUSTERIYE GOSTERILECEK
    baslik ve aciklamayi ayiklar.

    Agent ciktisi "Başlık/Açıklama/Fiyat/Kâr Marjı/Durum" alanlarini bir arada
    dondurur; Fiyat/Kâr Marjı/Durum sadece bizim ic degerlendirmemiz icindir
    ve musteri sayfasina (Shopify body_html) asla yazilmamali — daha once bu
    ayiklama yapilmadigi icin ic alanlar (ve onlarin Turkce etiketleri)
    canli urun sayfasina siziyordu. (title, description_html, needs_review)
    dondurur; needs_review, agent ciktisinda "⚠️" (KONTROL GEREKIYOR) varsa
    True olur.
    """
    raw_text = (raw_text or "").strip().strip("`").strip()
    if not raw_text:
        return fallback_title, f"<p>{fallback_title}</p>", False

    title = fallback_title
    match = re.search(r"^Başlık:\s*(.+)$", raw_text, re.MULTILINE)
    if match:
        title = match.group(1).strip()

    description = fallback_title
    match = re.search(
        r"^Açıklama:\s*(.+?)(?=\n(?:Fiyat|Kâr Marjı|Durum):|\Z)",
        raw_text,
        re.MULTILINE | re.DOTALL,
    )
    if match:
        description = match.group(1).strip()

    needs_review = "⚠️" in raw_text

    return title, f"<p>{description}</p>", needs_review


def _generate_listing(product):
    """PRODUCT_AGENT'i cagirip satisa yonelik bir baslik/aciklama uretir.

    main.py'nin list_products() akisiyla ayni girdi/cikti sozlesmesini kullanir,
    boylece elle eklenen urunlerle DSers'tan onaylanan urunler ayni kalitede
    baslik/aciklamaya sahip olur. (title, description_html, needs_review) dondurur.
    """
    fallback_title = product["title"]

    try:
        with open("agents/product_agent.md", encoding="utf-8") as f:
            system_prompt = f.read()
    except FileNotFoundError:
        return fallback_title, f"<p>{fallback_title}</p>", False

    from anthropic import Anthropic

    raw_description = product.get("raw_description") or product.get("original_title") or product["title"]
    task = (
        f"Ürün Adı: {product['title']}\n"
        "Hedef Pazar: global/EN\n"
        f"Maliyet: {product.get('cost_min', '?')} {product.get('currency', 'EUR')}\n"
        f"Satış Fiyatı: {product.get('sell_price_min', '?')} {product.get('currency', 'EUR')}\n"
        f"Ham Açıklama: {raw_description} (tedarikçi: {product.get('source', 'DSers')}, "
        f"kaynak: {product.get('supplier_url', '(yok)')})"
    )
    try:
        response = Anthropic().messages.create(
            model="claude-opus-5",
            max_tokens=1500,
            system=system_prompt,
            messages=[{"role": "user", "content": task}],
        )
        result = next((b.text for b in response.content if b.type == "text"), "")
    except Exception:
        return fallback_title, f"<p>{fallback_title}</p>", False

    return parse_agent_listing(result, fallback_title)


def _publish_product(product):
    """Onaylanan bir aday urunu gercek Shopify magazasina, canli (active) olarak ekler."""
    from shopify_client import ShopifyClient

    shopify = ShopifyClient()
    if product.get("description_html"):
        title, description_html = product["title"], product["description_html"]
    else:
        title, description_html, _ = _generate_listing(product)
    created = shopify.create_product(
        title=title,
        description_html=description_html,
        price=product["sell_price_min"],
    )

    image_urls = product.get("image_urls") or (
        [product["image_url"]] if product.get("image_url") else []
    )
    for url in image_urls[:8]:
        try:
            shopify.add_product_image_from_url(created["id"], url)
        except Exception:
            continue
    return created


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

    def do_POST(self):
        if self.path not in ("/api/approve", "/api/reject"):
            self._send(404, b"Not Found", "text/plain; charset=utf-8")
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            product_id = str(payload["id"])
        except (json.JSONDecodeError, KeyError, ValueError):
            self._send(400, b"Gecersiz istek", "text/plain; charset=utf-8")
            return

        product = get_pending_product(product_id)
        if not product:
            self._send(404, b"Urun bulunamadi (zaten islenmis olabilir)", "text/plain; charset=utf-8")
            return

        if self.path == "/api/reject":
            remove_pending_product(product_id)
            log_event("urun", f"'{product['title'][:60]}' reddedildi", "info")
            self._send(200, b'{"ok":true}', "application/json; charset=utf-8")
            return

        try:
            _publish_product(product)
        except Exception as e:
            log_event("urun", f"'{product['title'][:60]}' yayinlanamadi: {e}", "error")
            self._send(500, str(e).encode("utf-8", errors="replace"), "text/plain; charset=utf-8")
            return

        remove_pending_product(product_id)
        log_event("urun", f"'{product['title'][:60]}' onaylanip Shopify'a yayinlandi", "success")
        self._send(200, b'{"ok":true}', "application/json; charset=utf-8")

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
    _load_pending()
    _server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    _server.daemon_threads = True
    thread = threading.Thread(target=_server.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{port}"
