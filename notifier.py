"""Odenmis ama tedarikciye siparisi gecilmemis islemler icin e-posta uyarisi.

panel.py'nin kirmizi gorev satiri (bkz. HARITA.md 26) sadece panel acikken
gorunur. Bu modul aynı uyariyi e-posta ile de gonderir ki panel kapaliyken
de odenmis bir siparis gozden kacmasin.

Gmail SMTP + uygulama sifresi denendi ama bu hesapta 535 "Username and
Password not accepted" hatasi verdi (taze olusturulmus, dogru kopyalanmis
bir uygulama sifresiyle bile) — buna sebep olan hesaba ozel kisitlama
tarayicidan tespit edilemedi. Resend'in HTTP API'si (tek API anahtari,
OAuth/uygulama-sifresi derdi yok) yerine kullanildi. `RESEND_API_KEY`
yoksa bu adim sessizce atlanir, mevcut siparis akisi bozulmaz.
"""

import json
import os
import urllib.error
import urllib.request

_warned_missing_config = False


def send_supplier_alert(order_ref, items, channel="shopify"):
    """Tedarikciye elle siparis verilmesi gerektigini e-posta ile bildirir.

    Basarisizlik (eksik ayar, API hatasi) sessizce loglanir, exception
    yukselmez — bu bildirim best-effort, ana siparis akisini durdurmamali.
    """
    api_key = os.getenv("RESEND_API_KEY")
    to_addr = os.getenv("NOTIFY_EMAIL_TO")

    if not (api_key and to_addr):
        _warn_missing_config()
        return False

    from_addr = os.getenv("NOTIFY_EMAIL_FROM", "AJANS <onboarding@resend.dev>")
    subject = f"AJANS: {order_ref} icin tedarikciye siparis gerekiyor"
    body = (
        f"Kanal: {channel}\n"
        f"Siparis: {order_ref}\n"
        f"Urunler: {items}\n\n"
        "Bu siparis odendi ama tedarikciye (DSers/AliExpress) henuz elle "
        "siparis verilmedi. Verdikten sonra paneldeki 'Siparis verdim' "
        "dugmesine basmayi unutma."
    )

    payload = json.dumps(
        {"from": from_addr, "to": [to_addr], "subject": subject, "text": body}
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Cloudflare (api.resend.com'un onunde) urllib'in varsayilan
            # "Python-urllib/x.y" User-Agent'ini bot sanip 403/1010 ile
            # engelliyor; tarayici gibi bir deger bunu asiyor.
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=15):
            pass
        return True
    except urllib.error.HTTPError as e:
        import panel

        detail = e.read().decode("utf-8", errors="replace")
        panel.log_event(
            "tedarikci", f"E-posta uyarisi gonderilemedi: {e.code} {detail}", "error"
        )
        return False
    except Exception as e:
        import panel

        panel.log_event("tedarikci", f"E-posta uyarisi gonderilemedi: {e}", "error")
        return False


def _warn_missing_config():
    global _warned_missing_config
    if _warned_missing_config:
        return
    _warned_missing_config = True
    import panel

    panel.log_event(
        "tedarikci",
        "E-posta uyarisi kapali: .env'de RESEND_API_KEY / NOTIFY_EMAIL_TO "
        "tanimli degil.",
        "info",
    )
