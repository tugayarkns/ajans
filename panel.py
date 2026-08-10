"""Yerel canli izleme paneli.

Dis bagimlilik gerektirmez (stdlib http.server). main.py bu modulu
kullanarak arka planda bir web sunucusu baslatir; agents/order/product
aksiyonlari log_event() ile bildirilir, panel bunlari taraycida
otomatik yenilenen bir sayfada gosterir. Olaylar ayni zamanda
activity_log.jsonl dosyasina yazilir, boylece program yeniden
baslatilinca gecmis kaybolmaz.
"""
import json
import os
import re
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import panel_auth

LOG_FILE = "activity_log.jsonl"
PENDING_FILE = "pending_products.json"
MAX_EVENTS = 500
ANALYTICS_REFRESH_SECONDS = 600
ANALYTICS_WINDOW_DAYS = 7

# eBay Inventory API uzerinden yayinlanan SKU -> listingId eslemesi (bkz.
# CLAUDE.md eBay bolumu). AJANS-001..004 Seller Hub UI'dan elle yayinlandigi
# icin item ID'leri kodda/hicbir yerde kayitli degil; bu SKU'lar icin
# UI'de dogrudan urun linki yerine Seller Hub arama linkine dusulur.
_EBAY_ITEM_IDS = {
    "AJANS-005": "307118017053",
    "AJANS-006": "307118047792",
    "AJANS-007": "307118048040",
    "AJANS-008": "307118048374",
}

_lock = threading.Lock()
_events = []
_pending = []
_state = {
    "agents_loaded": 0,
    "automatic_mode": False,
    "last_check": None,
    "started_at": datetime.now().isoformat(),
}
_analytics = {}
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
        snap = {
            "state": dict(_state),
            "events": list(reversed(_events)),
            "pending": list(_pending),
            "analytics": dict(_analytics),
            "links": _store_links(),
        }
    # inventory_db kendi kilidini yonetir, _lock icinde cagirmaya gerek yok.
    try:
        import inventory_db

        snap["supplier_tasks"] = inventory_db.get_open_supplier_tasks()
    except Exception:
        snap["supplier_tasks"] = []
    return snap


def _store_links():
    domain = os.environ.get("SHOPIFY_STORE_DOMAIN")
    return {
        "shopify_admin": f"https://{domain}/admin" if domain else None,
        "shopify_orders": f"https://{domain}/admin/orders" if domain else None,
        "ebay_listings": "https://www.ebay.com/sh/lst/active",
        "ebay_orders": "https://www.ebay.com/sh/ord",
    }


def _shopify_product_url(product_id):
    domain = os.environ.get("SHOPIFY_STORE_DOMAIN")
    if not domain or not product_id:
        return None
    return f"https://{domain}/admin/products/{product_id}"


def _ebay_item_url(sku):
    item_id = _EBAY_ITEM_IDS.get(sku)
    if item_id:
        return f"https://www.ebay.com/itm/{item_id}"
    return f"https://www.ebay.com/sh/lst/active?q={sku}"


def _refresh_analytics():
    """Shopify/eBay siparis istatistiklerini + capraz-kanal stok tablosunu tazeler.

    Her iki kanal da birbirinden bagimsiz try/except icinde cagrilir, boylece
    biri (orn. eBay kimlik bilgisi eksikse) hata verirse digeri yine de
    gosterilir. Durum geciside (ok<->error) log_event yazilir, her turda degil
    — aksi halde 10 dakikada bir olay akisi spam olur.
    """
    global _analytics

    try:
        from shopify_client import ShopifyClient

        shopify_stats = ShopifyClient().get_order_stats(ANALYTICS_WINDOW_DAYS)
    except Exception as e:
        shopify_stats = {"ok": False, "error": str(e), "window_days": ANALYTICS_WINDOW_DAYS}

    try:
        from ebay_client import EbayClient

        ebay_stats = EbayClient().get_order_stats(ANALYTICS_WINDOW_DAYS)
    except Exception as e:
        ebay_stats = {"ok": False, "error": str(e), "window_days": ANALYTICS_WINDOW_DAYS}

    products = []
    try:
        import inventory_db

        shopify_ids = {}
        try:
            from shopify_client import ShopifyClient

            shopify_ids = {p["title"]: p.get("id") for p in ShopifyClient().get_active_products()}
        except Exception:
            pass

        for row in inventory_db.get_all():
            products.append({
                **row,
                "shopify_url": _shopify_product_url(shopify_ids.get(row.get("title"))),
                "ebay_url": _ebay_item_url(row.get("sku")),
            })
    except Exception:
        pass

    combined_revenue = (shopify_stats.get("revenue") or 0) + (ebay_stats.get("revenue") or 0)
    combined_count = (shopify_stats.get("order_count") or 0) + (ebay_stats.get("order_count") or 0)

    with _lock:
        prev_shopify_ok = _analytics.get("shopify", {}).get("ok")
        prev_ebay_ok = _analytics.get("ebay", {}).get("ok")
        _analytics = {
            "shopify": shopify_stats,
            "ebay": ebay_stats,
            "combined": {"order_count": combined_count, "revenue": combined_revenue},
            "products": products,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "window_days": ANALYTICS_WINDOW_DAYS,
        }

    if prev_shopify_ok is not None and prev_shopify_ok != shopify_stats.get("ok"):
        status = "success" if shopify_stats.get("ok") else "error"
        msg = "Shopify analitik baglantisi kuruldu" if shopify_stats.get("ok") \
            else f"Shopify analitik baglantisi koptu: {shopify_stats.get('error')}"
        log_event("analitik", msg, status)
    if prev_ebay_ok is not None and prev_ebay_ok != ebay_stats.get("ok"):
        status = "success" if ebay_stats.get("ok") else "error"
        msg = "eBay analitik baglantisi kuruldu" if ebay_stats.get("ok") \
            else f"eBay analitik baglantisi koptu: {ebay_stats.get('error')}"
        log_event("analitik", msg, status)


def _analytics_loop():
    while True:
        try:
            _refresh_analytics()
        except Exception:
            pass
        time.sleep(ANALYTICS_REFRESH_SECONDS)


_LOGIN_HTML = """<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AJANS Panel - Giris</title>
<style>
  :root {
    --bg: #0b0d12; --panel: #14161e; --panel-border: #262a38;
    --text: #e8e9ed; --muted: #8b90a0; --accent: #6d8dfa; --red: #f87171;
  }
  * { box-sizing: border-box; }
  body {
    font-family: "Segoe UI", -apple-system, Inter, Arial, sans-serif;
    background: radial-gradient(1200px 500px at 15% -10%, rgba(109,141,250,0.10), transparent), var(--bg);
    color: var(--text); margin:0; min-height:100vh;
    display:flex; align-items:center; justify-content:center; padding:20px;
  }
  .box { background:var(--panel); border:1px solid var(--panel-border); border-radius:14px; padding:32px; width:100%; max-width:340px; }
  .mark { width:40px; height:40px; border-radius:10px; background:linear-gradient(135deg, var(--accent), #a78bfa); display:flex; align-items:center; justify-content:center; font-weight:700; color:#0b0d12; margin-bottom:16px; }
  h1 { font-size:17px; margin:0 0 20px; font-weight:600; }
  label { display:block; font-size:12px; color:var(--muted); margin:14px 0 6px; font-weight:600; }
  input { width:100%; padding:10px 12px; border-radius:8px; border:1px solid var(--panel-border); background:#0f1118; color:var(--text); font-size:14px; }
  input:focus { outline:none; border-color:var(--accent); }
  button { width:100%; margin-top:22px; padding:11px 0; border:none; border-radius:8px; background:var(--accent); color:#0b0d12; font-weight:700; font-size:14px; cursor:pointer; }
  button:disabled { opacity:.6; cursor:not-allowed; }
  .err { color:var(--red); font-size:12px; margin-top:12px; min-height:16px; }
</style>
</head>
<body>
  <form class="box" id="login-form">
    <div class="mark">A</div>
    <h1>AJANS Panel'e giris yap</h1>
    <label for="email">E-posta</label>
    <input id="email" type="email" autocomplete="username" required>
    <label for="password">Sifre</label>
    <input id="password" type="password" autocomplete="current-password" required>
    <button id="submit-btn" type="submit">Giris yap</button>
    <div class="err" id="err"></div>
  </form>
<script>
document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const btn = document.getElementById('submit-btn');
  const err = document.getElementById('err');
  btn.disabled = true; btn.textContent = 'Giris yapiliyor...'; err.textContent = '';
  try {
    const res = await fetch('/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: document.getElementById('email').value,
        password: document.getElementById('password').value,
      }),
    });
    if (!res.ok) throw new Error('E-posta veya sifre hatali');
    window.location.href = '/';
  } catch (ex) {
    err.textContent = ex.message;
    btn.disabled = false; btn.textContent = 'Giris yap';
  }
});
</script>
</body>
</html>
"""


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
  .store-links { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
  .store-link {
    display:inline-flex; align-items:center; gap:6px; font-size:12px; font-weight:600;
    color:var(--text); background:var(--panel); border:1px solid var(--panel-border);
    padding:6px 12px; border-radius:999px; text-decoration:none;
  }
  .store-link:hover { border-color:var(--accent); color:var(--accent); }
  .store-link.disabled { color:var(--muted); pointer-events:none; opacity:.5; }
  .analytics-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }
  .btn-refresh {
    border:1px solid var(--panel-border); background:var(--panel); color:var(--text);
    font-size:12px; font-weight:600; padding:6px 14px; border-radius:8px; cursor:pointer;
  }
  .btn-refresh:hover { border-color:var(--accent); color:var(--accent); }
  .btn-refresh:disabled { opacity:.5; cursor:not-allowed; }
  .card.error-card { border-color:rgba(248,113,113,0.4); }
  .card .err { font-size:11px; color:var(--red); margin-top:6px; }
  .link-cell a { color:var(--accent); text-decoration:none; font-size:12px; margin-right:10px; }
  .link-cell a:hover { text-decoration:underline; }
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
    <div style="display:flex; align-items:center; gap:14px; flex-wrap:wrap;">
      <div class="store-links" id="store-links"></div>
      <div class="live"><span class="dot"></span> Canli &middot; 2sn'de bir yenilenir</div>
      <button class="btn-refresh" onclick="logout()">Cikis yap</button>
    </div>
  </div>

  <div class="cards" id="cards"></div>

  <div class="panel-section" style="margin-bottom:28px;">
    <div class="head">
      <h2>Onay Bekleyen Yeni Urunler</h2>
      <span class="count" id="pending-count"></span>
    </div>
    <div class="pending-grid" id="pending-grid"></div>
  </div>

  <div class="panel-section" id="tasks-section" style="margin-bottom:28px; display:none; border-color:var(--red);">
    <div class="head" style="background:rgba(248,113,113,0.08);">
      <h2 style="color:var(--red);">⚠️ Tedarikciye Siparis Verilmeli</h2>
      <span class="count" id="tasks-count"></span>
    </div>
    <table>
      <thead><tr><th>Zaman</th><th>Kanal</th><th>Siparis</th><th>Urunler</th><th></th></tr></thead>
      <tbody id="tasks-rows"></tbody>
    </table>
  </div>

  <div class="panel-section" style="margin-bottom:28px;">
    <div class="head analytics-head">
      <h2>Magaza Analitigi (Son 7 Gun)</h2>
      <button class="btn-refresh" id="analytics-refresh-btn" onclick="refreshAnalytics(this)">Yenile</button>
    </div>
    <div class="cards" id="analytics-cards" style="padding:20px; margin-bottom:0;"></div>
    <table>
      <thead><tr><th>SKU</th><th>Urun</th><th>Havuz</th><th>Shopify</th><th>eBay</th><th>Linkler</th></tr></thead>
      <tbody id="analytics-products"></tbody>
    </table>
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
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
let _lastPendingSig = null;
async function logout() {
  try {
    await fetch('/logout', { method: 'POST' });
  } catch (err) { /* olsa da olmasa da giris sayfasina don */ }
  window.location.href = '/login';
}
async function refreshAnalytics(btn) {
  btn.disabled = true;
  btn.textContent = 'Yenileniyor...';
  try {
    await fetch('/api/analytics-refresh', { method: 'POST' });
  } catch (err) { /* refresh() zaten periyodik cekiyor, sessizce devam */ }
  btn.disabled = false;
  btn.textContent = 'Yenile';
  refresh();
}
async function completeTask(ref, btn) {
  btn.disabled = true;
  btn.textContent = 'Kaydediliyor...';
  try {
    const res = await fetch('/api/supplier-task/done', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ order_ref: ref })
    });
    if (!res.ok) throw new Error(await res.text());
  } catch (err) {
    alert('Islem basarisiz: ' + err.message);
    btn.disabled = false;
    btn.textContent = 'Siparis verdim';
    return;
  }
  refresh();
}
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

    const links = data.links || {};
    const linkPill = (url, label) => url
      ? `<a class="store-link" href="${escapeHtml(url)}" target="_blank" rel="noopener">${label} ↗</a>`
      : `<span class="store-link disabled">${label} ↗</span>`;
    document.getElementById('store-links').innerHTML =
      linkPill(links.shopify_admin, 'Shopify Admin') +
      linkPill(links.shopify_orders, 'Shopify Siparisler') +
      linkPill(links.ebay_listings, 'eBay Seller Hub') +
      linkPill(links.ebay_orders, 'eBay Siparisler');

    const a = data.analytics || {};
    const money = (v, cur) => (v === undefined || v === null) ? '—' : `${(cur || 'EUR')} ${Number(v).toFixed(2)}`;
    const statCard = (label, stats) => `
      <div class="card ${stats && stats.ok === false ? 'error-card' : ''}">
        <div class="label">${label}</div>
        <div class="value">${stats && stats.ok !== false ? (stats.order_count ?? '—') + ' siparis' : '—'}</div>
        <div class="err">${stats && stats.ok !== false ? money(stats.revenue, stats.currency) : (stats ? 'Baglanti hatasi: ' + escapeHtml(stats.error || '') : 'Henuz veri yok')}</div>
      </div>`;
    document.getElementById('analytics-cards').innerHTML =
      statCard('Shopify (7g)', a.shopify) +
      statCard('eBay (7g)', a.ebay) +
      statCard('Toplam (7g)', a.combined ? { ok: true, order_count: a.combined.order_count, revenue: a.combined.revenue, currency: (a.shopify && a.shopify.currency) || (a.ebay && a.ebay.currency) } : null);

    const products = a.products || [];
    document.getElementById('analytics-products').innerHTML = products.length ? products.map(p => `
      <tr>
        <td>${escapeHtml(p.sku)}</td>
        <td>${escapeHtml(p.title)}</td>
        <td>${p.pool_qty ?? '—'}</td>
        <td>${p.shopify_qty ?? '—'}</td>
        <td>${p.ebay_qty ?? '—'}</td>
        <td class="link-cell">
          ${p.shopify_url ? `<a href="${escapeHtml(p.shopify_url)}" target="_blank" rel="noopener">Shopify ↗</a>` : ''}
          ${p.ebay_url ? `<a href="${escapeHtml(p.ebay_url)}" target="_blank" rel="noopener">eBay ↗</a>` : ''}
        </td>
      </tr>
    `).join('') : '<tr><td colspan="6" class="empty">Henuz stok verisi yok.</td></tr>';

    const tasks = data.supplier_tasks || [];
    document.getElementById('tasks-section').style.display = tasks.length ? '' : 'none';
    document.getElementById('tasks-count').textContent = tasks.length ? `${tasks.length} bekleyen` : '';
    document.getElementById('tasks-rows').innerHTML = tasks.map(t => `
      <tr>
        <td class="time">${timeAgo(t.created_at)}</td>
        <td><span class="kind">${escapeHtml(t.channel)}</span></td>
        <td>${escapeHtml(t.order_ref)}</td>
        <td>${escapeHtml(t.items)}</td>
        <td><button class="btn-approve" style="padding:6px 12px;" onclick="completeTask(${escapeHtml(JSON.stringify(t.order_ref))}, this)">Siparis verdim</button></td>
      </tr>
    `).join('');

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
      const cardId = 'p_' + String(p.id).replace(/[^a-zA-Z0-9_-]/g, '_');
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
            <button class="btn-approve" onclick="decide(${escapeHtml(JSON.stringify(p.id))},'approve',this)">Onayla ve Yayinla</button>
            <button class="btn-reject" onclick="decide(${escapeHtml(JSON.stringify(p.id))},'reject',this)">Reddet</button>
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

    def _current_user(self):
        cookie_header = self.headers.get("Cookie") or ""
        for part in cookie_header.split(";"):
            name, _, value = part.strip().partition("=")
            if name == panel_auth.SESSION_COOKIE:
                return panel_auth.verify_session_token(value)
        return None

    def _set_session_cookie(self, token):
        self.send_header(
            "Set-Cookie",
            f"{panel_auth.SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; "
            f"Max-Age={panel_auth.SESSION_MAX_AGE_SECONDS}",
        )

    def _clear_session_cookie(self):
        self.send_header(
            "Set-Cookie", f"{panel_auth.SESSION_COOKIE}=; Path=/; HttpOnly; Max-Age=0"
        )

    def do_GET(self):
        if self.path == "/login":
            if self._current_user():
                self._send_redirect("/")
                return
            self._send(200, _LOGIN_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return

        if not self._current_user():
            if self.path.startswith("/api/"):
                self._send(401, b'{"error":"giris gerekli"}', "application/json; charset=utf-8")
            else:
                self._send_redirect("/login")
            return

        if self.path in ("/", "/index.html"):
            self._send(200, _PAGE_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/data":
            body = json.dumps(_snapshot(), ensure_ascii=False).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
        else:
            self._send(404, b"Not Found", "text/plain; charset=utf-8")

    def do_POST(self):
        if self.path == "/login":
            self._handle_login()
            return

        if self.path == "/logout":
            self.send_response(200)
            self._clear_session_cookie()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            body = b'{"ok":true}'
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if not self._current_user():
            self._send(401, b'{"error":"giris gerekli"}', "application/json; charset=utf-8")
            return

        if self.path == "/api/supplier-task/done":
            self._handle_supplier_task_done()
            return

        if self.path == "/api/analytics-refresh":
            try:
                _refresh_analytics()
            except Exception as e:
                self._send(500, str(e).encode("utf-8", errors="replace"), "text/plain; charset=utf-8")
                return
            body = json.dumps(_snapshot(), ensure_ascii=False).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return

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

    def _handle_login(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            email = str(payload["email"])
            password = str(payload["password"])
        except (json.JSONDecodeError, KeyError, ValueError):
            self._send(400, b"Gecersiz istek", "text/plain; charset=utf-8")
            return

        if not panel_auth.verify_admin(email, password):
            self._send(401, b'{"error":"E-posta veya sifre hatali"}', "application/json; charset=utf-8")
            return

        token = panel_auth.create_session_token(email.strip().lower())
        self.send_response(200)
        self._set_session_cookie(token)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        body = b'{"ok":true}'
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_supplier_task_done(self):
        import inventory_db

        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            order_ref = str(payload["order_ref"])
        except (json.JSONDecodeError, KeyError, ValueError):
            self._send(400, b"Gecersiz istek", "text/plain; charset=utf-8")
            return

        if not inventory_db.complete_supplier_task(order_ref):
            self._send(
                404,
                b"Gorev bulunamadi (zaten tamamlanmis olabilir)",
                "text/plain; charset=utf-8",
            )
            return

        log_event("tedarikci", f"{order_ref}: tedarikçi siparişi verildi", "success")
        self._send(200, b'{"ok":true}', "application/json; charset=utf-8")

    def _send(self, code, body, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start(port=8765):
    """Paneli arka plan thread'inde baslatir, URL'ini dondurur.

    Varsayilan olarak tum ag arayuzlerinde (0.0.0.0) dinler, boylece
    tanimli adminler ayni ag/tunelden panele erisebilir (bkz. panel_auth.py
    - giris ekrani olmadan bu artik guvensiz olurdu). Sadece bu makineden
    erisim isteniyorsa PANEL_HOST=127.0.0.1 .env'e eklenebilir.
    """
    global _server
    _load_existing()
    _load_pending()
    host = os.environ.get("PANEL_HOST", "0.0.0.0")
    _server = ThreadingHTTPServer((host, port), _Handler)
    _server.daemon_threads = True
    thread = threading.Thread(target=_server.serve_forever, daemon=True)
    thread.start()
    analytics_thread = threading.Thread(target=_analytics_loop, daemon=True)
    analytics_thread.start()
    return f"http://127.0.0.1:{port}"
