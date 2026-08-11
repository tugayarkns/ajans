"""Urun secim politikasi: guven skoru ve iade riski elemesi.

Neden var: magaza dropshipping yapiyor, urunu elle gormuyoruz. Yanlis urun
secmenin bedeli iade, kotu yorum ve kayip kargo parasi. Bu yuzden bir aday
urun panele bile girmeden once burada eleniyor — "sert elemeler" (blockers)
varsa aday hic kuyruga alinmaz, kalanlar 0-100 arasi puanlanip siralanir.

Politika bilincli olarak **sikidir**: az ama saglam urun satmak, cok ama
iade donen urun satmaktan iyidir. Esikler asagida tek yerde; gevsetmek
istersen MIN_* sabitlerini degistir, kodun geri kalanina dokunma.

Stdlib disinda bagimliligi yoktur; panel de main.py de ayni fonksiyonu
kullanir ki panelde gorunen skor ile denetim raporundaki skor hep ayni olsun.
"""

import re

# --- Sert elemeler (biri bile varsa aday reddedilir) ---------------------
MIN_RATING = 4.6          # tedarikci puani (5 uzerinden)
MIN_ORDERS = 1000         # kanitlanmis satis adedi
MIN_IMAGES = 6            # gercek tedarikci fotografi
MIN_STOCK = 20            # toplam stok (tukenen urun = iptal + kotu yorum)
MAX_PRICE_EUR = 40.0      # pahali urunde iade motivasyonu yuksek
MIN_MARGIN_PCT = 30.0     # bu marjin altinda tek iade tum kari siliyor

# --- Iade riski yuksek urun tipleri --------------------------------------
# Her desen (regex, sebep) ciftidir. Desenler bilincli olarak dar tutuldu:
# yanlislikla iyi bir urunu elemek de bir maliyet. Yeni bir iade dalgasi
# gorursen buraya desen ekle - kural tek yerde dursun.
RISK_PATTERNS = [
    # Not: "boots" bilincli olarak dar yazildi - "car boot organizer" (bagaj)
    # arac aksesuari kategorimizin tam ortasinda ve ayakkabiyla ilgisi yok.
    (r"\b(t-?shirt|dress|hoodie|jacket|trousers|jeans|sneakers?|sandals?|"
     r"socks?|underwear|swimwear|gloves?)\b|"
     r"\b(ankle|winter|rain|hiking|leather) boots?\b",
     "Beden/kalip gerektiren giyim urunu - yanlis beden = kesin iade"),
    # "one size fits all" bir risk degil, tam tersi bir avantaj - o yuzden
    # burada yok; sadece beden tablosuna baglilik eleniyor.
    (r"\b(size chart|us size|eu size|fits size)\b",
     "Beden tablosuna bagli urun"),
    (r"\b(watch (band|strap)|bracelet strap)\b",
     "Bileklik/kayis olcusu tutmazsa iade doner"),
    (r"\bfor (iphone|ipad|airpods|macbook|samsung|galaxy|xiaomi|huawei|pixel)\b",
     "Belirli cihaz modeline bagli - yanlis model = iade"),
    # "mirror" kasitli olarak yok: arac kor-nokta aynasi gibi urunler
    # genelde plastik ve bu kategoride cok yaygin.
    (r"\bglass\b|\b(ceramic|porcelain|crystal)\b",
     "Kirilabilir urun - kargoda hasar riski"),
    (r"\b(cream|serum|lotion|shampoo|perfume|essential oil|supplement|"
     r"vitamin|snack)\b",
     "Kozmetik/gida - saglik mevzuati ve iade riski"),
    (r"\b(razor|epilator|hair removal|toothbrush|face mask)\b",
     "Cilde temas eden urun - hijyen sebebiyle iade sorunlu"),
    (r"\b(power ?bank|lithium|li-ion|18650|battery pack|replacement battery)\b",
     "Lityum pil - kargo kisitli ve ariza orani yuksek"),
    (r"\b(replica|copy|clone|1:1|aaa quality)\b|"
     r"\b(gucci|louis vuitton|rolex|chanel|prada|nike|adidas)\b",
     "Marka taklidi riski - hesap kapatilma sebebi"),
    (r"\b(hardwire|drilling required|installation required)\b",
     "Montaj/kurulum gerektiriyor - musteri kuramazsa iade eder"),
]

# --- Rakip ilan sayisi yorumu (gozden kacan urun) ------------------------
# eBay'de o urun icin kac ilan var. Az rakip = gozden kacmis firsat.
COMPETITION_BANDS = [
    (300, 10, "Rakip cok az - gozden kacmis urun"),
    (1000, 8, "Rakip az"),
    (3000, 5, "Normal rekabet"),
    (10000, 2, "Rekabet yuksek"),
    (float("inf"), 0, "Pazar doymus - herkes satiyor"),
]
_NO_COMPETITION_DATA_POINTS = 5  # veri yoksa notr puan


def _num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _image_count(item):
    urls = item.get("image_urls")
    if isinstance(urls, list):
        return len(urls)
    return int(_num(item.get("images_count"), 0) or 0)


def _margin_pct(item):
    """Satis fiyatina gore yuzde kar marji (urun + kargo maliyeti dusulerek)."""
    sell = _num(item.get("sell_price_min"), 0) or 0
    cost = (_num(item.get("cost_min"), 0) or 0) + (_num(item.get("shipping_cost"), 0) or 0)
    if sell <= 0:
        return 0.0
    return (sell - cost) / sell * 100


def find_blockers(item):
    """Adayin satisa uygun OLMADIGINI gosteren sebepleri dondurur (bos = uygun)."""
    blockers = []
    title = (item.get("title") or "").lower()
    description = (item.get("description") or "").lower()
    haystack = f"{title} {description}"

    rating = _num(item.get("rating"))
    orders = _num(item.get("orders"))
    stock = _num(item.get("stock"))

    # Veri yoksa "sorun yok" saymiyoruz - dogrulanamayan urun satilmaz.
    if rating is None:
        blockers.append("Tedarikci puani bilinmiyor - dogrulanamayan urun satilmaz")
    elif rating < MIN_RATING:
        blockers.append(f"Tedarikci puani dusuk ({rating} < {MIN_RATING})")

    if orders is None:
        blockers.append("Satis adedi bilinmiyor - kanitlanmamis urun")
    elif orders < MIN_ORDERS:
        blockers.append(f"Yeterince satmamis ({int(orders)} < {MIN_ORDERS})")

    images = _image_count(item)
    if images < MIN_IMAGES:
        blockers.append(f"Yeterli gercek fotograf yok ({images} < {MIN_IMAGES})")

    if stock is None:
        blockers.append("Stok bilgisi yok")
    elif stock < MIN_STOCK:
        blockers.append(f"Stok yetersiz ({int(stock)} < {MIN_STOCK})")

    sell = _num(item.get("sell_price_min"), 0) or 0
    if sell > MAX_PRICE_EUR:
        blockers.append(f"Fiyat yuksek ({sell:.2f} > {MAX_PRICE_EUR} EUR) - iade riski artiyor")

    margin = _margin_pct(item)
    if sell > 0 and margin < MIN_MARGIN_PCT:
        blockers.append(f"Kar marji dusuk (%{margin:.0f} < %{MIN_MARGIN_PCT:.0f})")

    for pattern, reason in RISK_PATTERNS:
        if re.search(pattern, haystack):
            blockers.append(reason)

    return blockers


def _competition_points(competitor_count):
    if competitor_count is None:
        return _NO_COMPETITION_DATA_POINTS, "Rakip verisi alinamadi"
    for limit, points, label in COMPETITION_BANDS:
        if competitor_count < limit:
            return points, f"{label} ({int(competitor_count)} ilan)"
    return 0, ""


def evaluate(item, competitor_count=None):
    """Bir aday urunu degerlendirir.

    item: {title, description, rating, orders, stock, image_urls|images_count,
           cost_min, shipping_cost, sell_price_min}
    competitor_count: eBay'de ayni urun icin ilan sayisi (bkz.
    EbayClient.count_competing_listings). None ise o bilesen notr puanlanir.

    Dondurur: {"score": 0-100, "blockers": [...], "reasons": [...],
               "competitor_count": int|None}
    Skor, blockers bos olsa da hesaplanir - denetim raporu mevcut urunleri de
    puanlayabilsin diye.
    """
    blockers = find_blockers(item)
    reasons = []

    rating = _num(item.get("rating"), 0) or 0
    orders = _num(item.get("orders"), 0) or 0
    stock = _num(item.get("stock"), 0) or 0
    images = _image_count(item)
    margin = _margin_pct(item)

    # Tedarikci puani: 30 puan (4.0 taban, 5.0 tavan)
    rating_pts = max(0.0, min(30.0, (rating - 4.0) / 1.0 * 30))
    if rating >= 4.8:
        reasons.append(f"Cok yuksek tedarikci puani ({rating})")

    # Satis adedi: 20 puan
    if orders >= 10000:
        orders_pts = 20
        reasons.append(f"Cok satan urun ({int(orders)}+ siparis)")
    elif orders >= 5000:
        orders_pts = 17
    elif orders >= 2000:
        orders_pts = 14
    elif orders >= 1000:
        orders_pts = 10
    else:
        orders_pts = max(0, orders / 1000 * 10)

    # Gercek fotograf sayisi: 15 puan
    images_pts = min(15.0, images / 12 * 15)
    if images >= 10:
        reasons.append(f"Zengin gorsel ({images} gercek fotograf)")

    # Stok saglig: 10 puan
    if stock >= 200:
        stock_pts = 10
    elif stock >= 100:
        stock_pts = 8
    elif stock >= 50:
        stock_pts = 6
    elif stock >= MIN_STOCK:
        stock_pts = 4
    else:
        stock_pts = 0

    # Kar marji: 15 puan
    if margin >= 60:
        margin_pts = 15
        reasons.append(f"Yuksek kar marji (%{margin:.0f})")
    elif margin >= 50:
        margin_pts = 12
    elif margin >= 40:
        margin_pts = 9
    elif margin >= MIN_MARGIN_PCT:
        margin_pts = 5
    else:
        margin_pts = 0

    competition_pts, competition_note = _competition_points(competitor_count)
    if competition_note:
        reasons.append(competition_note)

    score = int(round(
        rating_pts + orders_pts + images_pts + stock_pts + margin_pts + competition_pts
    ))
    return {
        "score": max(0, min(100, score)),
        "blockers": blockers,
        "reasons": reasons,
        "competitor_count": competitor_count,
    }
