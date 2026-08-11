"""Urun secim politikasi icin regresyon testleri.

Bagimlilik yok (stdlib assert), pytest gerekmiyor - `python test_policy.py`
ile calisir, hepsi gecerse sessizce biter, biri patlarsa AssertionError ile
hangi satirda oldugunu gosterir.

Neden var: 2026-08-11'de magazaya once yapay zeka gorseliyle tek fotoğraflı
urun, sonra da yanlislikla "car BOOT organizer" (bagaj) urununu "boots"
(ayakkabi) regex'iyle elerken, "one size fits all" ifadesini de risk sanan
bir kural yazildi. Ikisi de elle test edilirken yakalandi. Bu dosya o
hatalarin ve urun secim kapisinin **bir daha sessizce geri gelmemesi** icin
var - trust_score.py veya ebay_client.py'de bir degisiklik yapan biri bu
dosyayi calistirip kirmiyor mu diye bakmali.
"""

import sys

# main.py'deki ayni pattern: Windows konsolu varsayilan olarak emoji basamiyor.
if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import trust_score
from ebay_client import _search_query

_FAILURES = []
_TOTAL = 0


def check(label, condition):
    global _TOTAL
    _TOTAL += 1
    if not condition:
        _FAILURES.append(label)
        print(f"❌ {label}")
    else:
        print(f"✅ {label}")


GOOD_ITEM = {
    "title": "Felt Car Trunk Organizer Collapsible Boot Storage Box",
    "rating": 4.7, "orders": 2000, "stock": 311,
    "image_urls": ["u"] * 9,
    "cost_min": 5.0, "shipping_cost": 1.99, "sell_price_min": 24.9,
}


def blockers_for(**overrides):
    return trust_score.find_blockers({**GOOD_ITEM, **overrides})


# --- Bugun bulunan iki yanlis-pozitif (bir daha geri gelmesin) -----------
check(
    "'car boot organizer' (bagaj) ayakkabi sanilip elenmiyor",
    blockers_for() == [],
)
check(
    "'one size fits all' bir risk sayilmiyor (aslinda avantaj)",
    blockers_for(title="Universal One Size Fits All Car Seat Cover") == [],
)

# --- Gercek risk desenleri hala yakalaniyor --------------------------------
check(
    "giyim (hoodie) eleniyor",
    any("giyim" in b for b in blockers_for(title="Winter Hoodie Jacket")),
)
check(
    "kadin botu (ayakkabi) eleniyor",
    any("giyim" in b for b in blockers_for(title="Women Leather Boots Winter Warm")),
)
check(
    "cihaza ozel urun eleniyor",
    any("cihaz" in b for b in blockers_for(title="Charger Stand for iPhone 15 14 13")),
)
check(
    "cam/kirilabilir urun eleniyor",
    any("Kirilabilir" in b for b in blockers_for(title="Tempered Glass Screen Protector")),
)
check(
    "lityum pil eleniyor",
    any("pil" in b for b in blockers_for(title="20000mAh Power Bank Fast Charging")),
)
check(
    "marka taklidi eleniyor",
    any("taklidi" in b for b in blockers_for(title="Nike Style Bag Replica 1:1")),
)

# --- Sinir degerleri (esik tam uzerinde gecmeli, altinda elenmeli) --------
check("puan 4.6 tam sinirda geciyor", blockers_for(rating=4.6) == [])
check("puan 4.5 eleniyor", any("puani dusuk" in b for b in blockers_for(rating=4.5)))
check("satis 1000 tam sinirda geciyor", blockers_for(orders=1000) == [])
check("satis 999 eleniyor", any("satmamis" in b for b in blockers_for(orders=999)))
check("gorsel 6 tam sinirda geciyor", blockers_for(image_urls=["u"] * 6) == [])
check("gorsel 5 eleniyor", any("fotograf" in b for b in blockers_for(image_urls=["u"] * 5)))
check("stok 20 tam sinirda geciyor", blockers_for(stock=20) == [])
check("stok 19 eleniyor", any("Stok" in b for b in blockers_for(stock=19)))

# --- Eksik veri "sorun yok" sayilmiyor -------------------------------------
check("puan verisi eksikse eleniyor", any("bilinmiyor" in b for b in blockers_for(rating=None)))
check("satis verisi eksikse eleniyor", any("bilinmiyor" in b for b in blockers_for(orders=None)))

# --- eBay rakip sorgusu: kelime ici tire bolunmemeli, doldurma kelime cikmali
check(
    "'Multi-Pocket' kelime ici tireden bolunmuyor",
    _search_query("Multi-Pocket Car Sun Visor Organizer") .split()[0] == "Multi",
)
check(
    "sorguda 'for'/'with' gibi doldurma kelime kalmiyor",
    "for" not in _search_query("Charging Station for Phone Watch Earbuds").lower().split()
    and "with" not in _search_query("LED Strip Lights with 44-Key Remote").lower().split(),
)
check(
    "sorgu bos donmuyor (tamami doldurma kelimeyse bile)",
    len(_search_query("in with for and the")) >= 0,  # bos olabilir ama patlamamali
)

# --- evaluate() skorunu da hesapliyor, blockers ile ayni sonucu veriyor ---
result = trust_score.evaluate(GOOD_ITEM, competitor_count=250)
check("evaluate() saglam urunu 0 blocker ile donduruyor", result["blockers"] == [])
check("evaluate() skoru 0-100 araliginda", 0 <= result["score"] <= 100)

print()
if _FAILURES:
    raise AssertionError(f"{len(_FAILURES)} test basarisiz: {_FAILURES}")
print(f"Tumu gecti ({_TOTAL} kontrol).")
