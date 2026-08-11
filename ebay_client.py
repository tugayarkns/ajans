import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

REQUEST_TIMEOUT_SECONDS = 30
TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
API_BASE = "https://api.ebay.com/sell/inventory/v1"
ACCOUNT_API_BASE = "https://api.ebay.com/sell/account/v1"
FULFILLMENT_API_BASE = "https://api.ebay.com/sell/fulfillment/v1"
TAXONOMY_API_BASE = "https://api.ebay.com/commerce/taxonomy/v1"
BROWSE_API_BASE = "https://api.ebay.com/buy/browse/v1"
SCOPE = (
    "https://api.ebay.com/oauth/api_scope/sell.inventory "
    "https://api.ebay.com/oauth/api_scope/sell.account "
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment"
)
# Taksonomi uc noktalari kullanici token'ini reddediyor (403), sadece duz
# client_credentials app token kabul ediyor (bkz. CLAUDE.md eBay bolumu).
APP_SCOPE = "https://api.ebay.com/oauth/api_scope"

# Zorunlu marka/uretici aspect'leri icin GPSR uyumlu "marka yok" degerleri
# (bkz. CLAUDE.md "Category-required aspects").
_ASPECT_DEFAULTS = {
    "Marke": "Markenlos",
    "Brand": "Unbranded",
    "Hersteller": "Nicht zutreffend",
    "Herstellernummer": "Nicht zutreffend",
    "MPN": "Does not apply",
    "Manufacturer": "Does not apply",
    "Manufacturer Part Number": "Does not apply",
}

# Bilinmeyen zorunlu alanlar icin pazarin dilinde "gecerli degil" karsiligi.
# Serbest-metin alanlarda eBay'in "onerilen" ilk degerini kullanmak fiziksel
# olcu uydurmaya yol aciyordu (orn. bilinmeyen bir urune "Item Height: 15 cm"
# yazmak) - alicinin gordugu bilgi yanlis olacagi icin bunun yerine acikca
# "belirtilmemis" denir.
_NOT_APPLICABLE_BY_LANGUAGE = {
    "de": "Nicht zutreffend",
    "en": "Does not apply",
    "fr": "Sans objet",
    "it": "Non applicabile",
    "es": "No aplicable",
}

# Shopify magazasi EUR uzerinden fiyatlandiriyor (bkz. CLAUDE.md); eBay'e
# baska para biriminde yayinlarken bu sabit yaklasik kurlarla EUR'dan
# cevrilir. Sabit kur - canli doviz API'si degil - periyodik olarak elle
# guncellenmesi gerekir (bkz. panel.convert_price_from_eur).
EUR_EXCHANGE_RATES = {
    "EUR": 1.0,
    "USD": 1.08,
    "GBP": 0.86,
    "CHF": 0.95,
}


# eBay'in payload'dan bagimsiz, rastgele donebildigi gecici hatalari:
# 25604 ("Availability not found") mevcut ve gecerli bir inventory_item/offer
# guncellenirken bile cikabiliyor; 25001 ise eBay'in kendi sunucu hatasi
# ("Core Inventory Service internal error", HTTP 500). Ikisi de ayni istek
# tekrarlandiginda geciyor - canliya cikan bir urunun sirf bu yuzden
# yayinlanmadan kalmamasi icin _request() bunlari otomatik tekrar dener.
_TRANSIENT_ERROR_IDS = ("25604", "25001")
TRANSIENT_RETRY_ATTEMPTS = 3
TRANSIENT_RETRY_DELAY_SECONDS = 3

# Kategori aramasina baslik disinda eklenen aciklama uzunlugu (bkz.
# suggest_category) - tum aciklamayi gondermek aramayi sulandiriyor.
CATEGORY_QUERY_DESCRIPTION_CHARS = 150


def _is_transient_error(detail):
    try:
        errors = json.loads(detail).get("errors") or []
    except (json.JSONDecodeError, AttributeError):
        return False
    return any(str(e.get("errorId")) in _TRANSIENT_ERROR_IDS for e in errors)


COMPETITION_QUERY_WORDS = 5
_QUERY_STOPWORDS = {
    "in", "for", "with", "and", "the", "of", "to", "on", "your", "a", "an",
}


def _search_query(title):
    """Urun basligini rakip aramasi icin kisa, jenerik bir sorguya cevirir.

    Magaza basliklari pazarlama amacli uzun ve tireli ("... — Anti-Slip
    Collapsible Boot Storage for SUV"); bu haliyle aranirsa eBay 0 sonuc
    dondurur ve her urun rakipsiz gorunur. Once tire/virgul oncesi ana kisim
    alinir, dolgu kelimeler atilir, sonra ilk birkac kelimeye inilir.
    """
    # Ayirici olarak yalniz uzun tire / bosluklu tire ve noktalama kullanilir;
    # kelime ici tire bolunmez ("Multi-Pocket" -> "Multi" olunca sorgu
    # anlamsizlasip milyonlarca sonuc donuyordu).
    head = re.split(r"[—–|,:(]|\s-\s", title or "", maxsplit=1)[0]
    words = [
        w for w in re.findall(r"[\w']+", head)
        if len(w) > 1 and w.lower() not in _QUERY_STOPWORDS
    ]
    return " ".join(words[:COMPETITION_QUERY_WORDS])


def _truncate_title(title, limit=80):
    """Basligi eBay'in 80 karakter sinirina, kelime ortasindan kesmeden sigdirir.

    Duz `title[:80]` bir kelimeyi yarida kesip ("...Earbuds" -> "...Earbu" gibi)
    kirik/guvensiz gorunen basliklar uretiyordu - alici gozunden bu bir
    profesyonellik/guven sorunu.
    """
    if len(title) <= limit:
        return title
    cut = title[:limit]
    last_space = cut.rfind(" ")
    if last_space > 0:
        cut = cut[:last_space]
    return cut.rstrip(" -–—,")

# eBay, envanter kaydini Content-Language'e gore locale bazli saklar. Yanlis dil
# kodu gonderilirse inventory_item basariyla olusur (204) ama sonraki offer
# cagrisi "SKU ... could not be found for the marketplace X" (25751) hatasi
# verir. Bu yuzden dil kodu marketplace ile eslesmek zorunda.
MARKETPLACE_LANGUAGES = {
    "EBAY_AT": "de-AT",
    "EBAY_DE": "de-DE",
    "EBAY_CH": "de-CH",
    "EBAY_GB": "en-GB",
    "EBAY_US": "en-US",
    "EBAY_FR": "fr-FR",
    "EBAY_IT": "it-IT",
    "EBAY_ES": "es-ES",
}

# Offer fiyati, pazarin kendi para biriminde gonderilmek zorunda.
MARKETPLACE_CURRENCIES = {
    "EBAY_AT": "EUR",
    "EBAY_DE": "EUR",
    "EBAY_FR": "EUR",
    "EBAY_IT": "EUR",
    "EBAY_ES": "EUR",
    "EBAY_CH": "CHF",
    "EBAY_GB": "GBP",
    "EBAY_US": "USD",
}


class EbayClient:
    """eBay Sell API (Inventory + Offer) istemcisi.

    Shopify'daki app-only client_credentials akisinin aksine, eBay'in Sell
    API'si kullanici adina islem yaptigi icin authorization_code grant +
    refresh_token gerektirir. Refresh token, developer.ebay.com'da uygulama
    olusturulduktan sonra bir kerelik tarayici onayiyla alinir ve .env'e
    elle girilir (EBAY_REFRESH_TOKEN); bu istemci sadece refresh_token'i
    access_token'a cevirip cache'ler, ilk yetkilendirmeyi yapmaz.

    Bu dosya, EBAY_CLIENT_ID/EBAY_CLIENT_SECRET/EBAY_REFRESH_TOKEN .env'e
    girilene kadar calisir durumda degildir (bkz. CLAUDE.md eBay bolumu).
    """

    def __init__(self, marketplace_id=None):
        """`marketplace_id` verilirse `EBAY_MARKETPLACE_ID` .env degerinin yerine
        gecer - ayni hesaptan birden fazla eBay sitesine (orn. EBAY_AT + EBAY_US)
        yayin yapmak icin her site kendi marketplace_id'siyle ayri bir
        EbayClient orneği kullanir (bkz. panel.py sync_ebay_listing).
        """
        self.client_id = os.environ["EBAY_CLIENT_ID"]
        self.client_secret = os.environ["EBAY_CLIENT_SECRET"]
        self.refresh_token = os.environ["EBAY_REFRESH_TOKEN"]
        self.marketplace_id = marketplace_id or os.environ.get("EBAY_MARKETPLACE_ID", "EBAY_US")
        self.content_language = MARKETPLACE_LANGUAGES.get(self.marketplace_id, "en-US")
        self.currency = MARKETPLACE_CURRENCIES.get(self.marketplace_id, "USD")
        self._token = None
        self._token_expires_at = 0
        self._app_token = None
        self._app_token_expires_at = 0
        self._category_tree_id = None

    def convert_price_from_eur(self, price_eur):
        """Shopify'in EUR fiyatini bu clientin marketplace para birimine cevirir.

        Cevrim yapilmadan (orn. EUR_-16.99 -> USD_16.99 gibi ayni sayiyla)
        yayinlamak, kur farkinin (~%8-10) tamamini karsiliksiz kaybettirir -
        bkz. CLAUDE.md eBay bolumu.
        """
        rate = EUR_EXCHANGE_RATES.get(self.currency, 1.0)
        return round(float(price_eur) * rate, 2)

    def _get_token(self):
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        credentials = f"{self.client_id}:{self.client_secret}"
        auth_header = base64.b64encode(credentials.encode()).decode()
        data = urllib.parse.urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "scope": SCOPE,
            }
        ).encode()
        req = urllib.request.Request(
            TOKEN_URL,
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {auth_header}",
            },
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read())

        self._token = payload["access_token"]
        self._token_expires_at = time.time() + payload.get("expires_in", 7200)
        return self._token

    def _get_app_token(self):
        """Taksonomi uc noktalari icin duz client_credentials app token'i (kullanici
        token'inden ayri, kendi cache'inde tutulur - bkz. modul basindaki APP_SCOPE notu).
        """
        if self._app_token and time.time() < self._app_token_expires_at - 60:
            return self._app_token

        credentials = f"{self.client_id}:{self.client_secret}"
        auth_header = base64.b64encode(credentials.encode()).decode()
        data = urllib.parse.urlencode(
            {"grant_type": "client_credentials", "scope": APP_SCOPE}
        ).encode()
        req = urllib.request.Request(
            TOKEN_URL,
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {auth_header}",
            },
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read())

        self._app_token = payload["access_token"]
        self._app_token_expires_at = time.time() + payload.get("expires_in", 7200)
        return self._app_token

    def _request(self, method, path, body=None, base=API_BASE):
        """eBay Sell API cagrisi; gecici hatalarda otomatik tekrar dener.

        `_TRANSIENT_ERROR_IDS`'teki hatalar payload'dan bagimsiz, rastgele
        ortaya cikip ayni istek tekrarlandiginda gecebiliyor - kalici
        hatalar (eksik aspect, gecersiz kategori vb.) ilk denemede raise
        edilir, tekrar denemek onlarda anlamsiz olurdu.
        """
        url = f"{base}{path}"
        data = json.dumps(body).encode() if body is not None else None

        last_error = None
        for attempt in range(TRANSIENT_RETRY_ATTEMPTS):
            headers = {
                "Authorization": f"Bearer {self._get_token()}",
                "Content-Type": "application/json",
                "Content-Language": self.content_language,
            }
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                    raw = resp.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")
                error = RuntimeError(f"eBay API hatasi ({e.code}): {detail}")
                if not _is_transient_error(detail):
                    raise error from e
                last_error = error
                if attempt < TRANSIENT_RETRY_ATTEMPTS - 1:
                    time.sleep(TRANSIENT_RETRY_DELAY_SECONDS)

        raise last_error

    def _taxonomy_request(self, path):
        url = f"{TAXONOMY_API_BASE}{path}"
        headers = {"Authorization": f"Bearer {self._get_app_token()}"}
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            raise RuntimeError(f"eBay taksonomi API hatasi ({e.code}): {detail}") from e

    def count_competing_listings(self, query):
        """Bu pazarda `query` icin kac ilan oldugunu dondurur (bulunamazsa None).

        "Baskalarinin gozunden kacan urun" olcusu: az rakip = doymamis nis.
        Browse API'yi **app token** ile cagirir (taksonomi gibi; kullanici
        token'i gerekmez, dolayisiyla yeni bir OAuth izni de gerekmez).

        Sorgu `_search_query()` ile kisaltilir: tam urun basligiyla arama
        neredeyse her zaman 0 dondurur (baslik cok spesifik) ve her urun
        "rakipsiz" gorunur - bu olcuyu tamamen ise yaramaz hale getiriyordu.

        Asla raise etmez - rakip verisi bir bonus sinyal, alinamazsa
        trust_score onu notr puanliyor (bkz. trust_score.COMPETITION_BANDS).
        """
        url = (
            f"{BROWSE_API_BASE}/item_summary/search"
            f"?q={urllib.parse.quote(_search_query(query))}&limit=1"
        )
        headers = {
            "Authorization": f"Bearer {self._get_app_token()}",
            "X-EBAY-C-MARKETPLACE-ID": self.marketplace_id,
        }
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read()).get("total")
        except Exception:
            return None

    def _get_category_tree_id(self):
        if self._category_tree_id:
            return self._category_tree_id
        result = self._taxonomy_request(
            f"/get_default_category_tree_id?marketplace_id={self.marketplace_id}"
        )
        self._category_tree_id = result["categoryTreeId"]
        return self._category_tree_id

    def suggest_category(self, title, description_text=None):
        """Urun basligi (+ varsa aciklamasi) icin en uygun eBay kategorisini bulur.

        Kategoriler pazar/urun turune gore cok farkli zorunlu alanlar
        isteyebildigi icin (bkz. CLAUDE.md "Category-required aspects"), sabit
        tek kategori yerine her urun icin ayri kategori aranir.

        `description_text` verilirse sorguya eklenir: salt baslikla arama
        yaniltici olabiliyor (orn. "Monitor Light Bar" -> ekranli cihaz
        kategorisi), aciklamadaki baglam ("clip onto the top of your
        monitor") daha isabetli eslesme sagliyor. Bulunamazsa None doner.
        """
        query = title
        if description_text:
            query = f"{title} {description_text[:CATEGORY_QUERY_DESCRIPTION_CHARS]}"
        tree_id = self._get_category_tree_id()
        result = self._taxonomy_request(
            f"/category_tree/{tree_id}/get_category_suggestions?q={urllib.parse.quote(query)}"
        )
        suggestions = result.get("categorySuggestions") or []
        if not suggestions:
            return None
        return suggestions[0]["category"]["categoryId"]

    def get_required_aspects(self, category_id):
        """Bir kategorinin zorunlu tuttugu aspect'leri (varsayilan degerlerle) dondurur.

        Marka/uretici alanlari GPSR uyumlu "marka yok" degerlerini alir
        (_ASPECT_DEFAULTS). Geri kalan zorunlu alanlarda urunun gercek
        degerini bilmedigimiz icin:
        - serbest metne izin veriliyorsa pazarin dilinde "gecerli degil"
          yazilir; eBay'in onerdigi ilk degeri secmek "Item Height: 15 cm"
          gibi UYDURULMUS olculer uretiyordu, alici bunu gercek zannederdi.
        - sadece listeden secim yapilabiliyorsa (SELECTION_ONLY) mecburen
          ilk gecerli deger kullanilir; tam isabetli olmayabilir ama alan
          bos birakilamaz, aksi halde ilan hic yayinlanamaz.
        """
        tree_id = self._get_category_tree_id()
        result = self._taxonomy_request(
            f"/category_tree/{tree_id}/get_item_aspects_for_category?category_id={category_id}"
        )
        fallback = _NOT_APPLICABLE_BY_LANGUAGE.get(
            self.content_language.split("-")[0], "Does not apply"
        )
        aspects = {}
        for aspect in result.get("aspects", []):
            constraint = aspect.get("aspectConstraint", {})
            if not constraint.get("aspectRequired"):
                continue
            name = aspect.get("localizedAspectName")
            if not name:
                continue
            if name in _ASPECT_DEFAULTS:
                aspects[name] = [_ASPECT_DEFAULTS[name]]
                continue
            if constraint.get("aspectMode") == "SELECTION_ONLY":
                values = [v.get("localizedValue") for v in aspect.get("aspectValues") or []]
                aspects[name] = [values[0]] if values else [fallback]
            else:
                aspects[name] = [fallback]
        return aspects

    def create_or_update_listing(
        self,
        sku,
        title,
        description_html,
        price,
        quantity,
        category_id,
        fulfillment_policy_id,
        payment_policy_id,
        return_policy_id,
        merchant_location_key,
        condition="NEW",
        image_urls=None,
        aspects=None,
    ):
        """Inventory item olusturur/gunceller, offer acar ve yayinlar.

        fulfillment_policy_id / payment_policy_id / return_policy_id / merchant_location_key
        eBay hesabinda onceden tanimlanmis olmali (bkz. CLAUDE.md eBay
        bolumundeki "Account prerequisites"); bu istemci onlari olusturmaz,
        sadece referans olarak kullanir.

        `title` eBay tarafinda 80 karakterle sinirlidir, asilirsa kirpilir.
        `aspects` verilmezse pazarin zorunlu tuttugu asgari alanlar
        (Marke/Herstellernummer) "Markenlos"/"Nicht zutreffend" ile doldurulur.
        """
        self._request(
            "PUT",
            f"/inventory_item/{sku}",
            {
                "availability": {"shipToLocationAvailability": {"quantity": quantity}},
                "condition": condition,
                "product": {
                    "title": _truncate_title(title),
                    "description": description_html,
                    "imageUrls": image_urls or [],
                    "aspects": aspects
                    or {
                        "Marke": ["Markenlos"],
                        "Herstellernummer": ["Nicht zutreffend"],
                    },
                },
            },
        )

        offer_body = {
            "sku": sku,
            "marketplaceId": self.marketplace_id,
            "format": "FIXED_PRICE",
            "availableQuantity": quantity,
            "categoryId": category_id,
            "listingDescription": description_html,
            "listingPolicies": {
                "fulfillmentPolicyId": fulfillment_policy_id,
                "paymentPolicyId": payment_policy_id,
                "returnPolicyId": return_policy_id,
            },
            "merchantLocationKey": merchant_location_key,
            "pricingSummary": {
                "price": {"value": str(price), "currency": self.currency}
            },
        }

        # Bu SKU icin zaten bir offer varsa POST 25002 "Offer entity already
        # exists" ile patlar (orn. onceki bir denemede offer olusup publish
        # basarisiz olduysa). O yuzden once mevcut offer aranir, varsa
        # guncellenir — metodun adindaki "update" kismi budur.
        offer_id = self._find_offer_id(sku)
        if offer_id:
            self._request("PUT", f"/offer/{offer_id}", offer_body)
        else:
            offer_id = self._request("POST", "/offer", offer_body)["offerId"]

        publish_result = self._request("POST", f"/offer/{offer_id}/publish", {})
        return {"sku": sku, "offer_id": offer_id, "listing_id": publish_result.get("listingId")}

    def _find_offer_id(self, sku):
        """Bu SKU icin bu pazarda mevcut offer varsa id'sini dondurur."""
        try:
            result = self._request(
                "GET", f"/offer?sku={sku}&marketplace_id={self.marketplace_id}"
            )
        except RuntimeError:
            return None
        for offer in result.get("offers", []):
            if offer.get("marketplaceId") == self.marketplace_id:
                return offer.get("offerId")
        return None

    def get_listing_quantity(self, sku):
        """Bir SKU'nun envanterdeki guncel miktarini dondurur (yoksa None)."""
        try:
            item = self._request("GET", f"/inventory_item/{sku}")
        except RuntimeError:
            return None
        availability = item.get("availability", {}).get("shipToLocationAvailability", {})
        return availability.get("quantity")

    def update_quantity(self, sku, new_qty):
        """Bir SKU'nun stok miktarini gunceller (mevcut inventory item'i korur)."""
        item = self._request("GET", f"/inventory_item/{sku}")
        item.setdefault("availability", {}).setdefault("shipToLocationAvailability", {})[
            "quantity"
        ] = new_qty
        self._request("PUT", f"/inventory_item/{sku}", item)

    def get_new_orders(self):
        """Henuz kargolanmamis eBay siparislerini dondurur.

        Shopify'in aksine eBay'de siparise etiket eklenemez, bu yuzden
        "islendi" bilgisi yerelde tutulur (bkz. inventory_db.mark_order_processed).
        """
        query = (
            "/order?filter=orderfulfillmentstatus:"
            "%7BNOT_STARTED%7CIN_PROGRESS%7D&limit=50"
        )
        result = self._request("GET", query, base=FULFILLMENT_API_BASE)
        return result.get("orders", [])

    def get_order_stats(self, days=7):
        """Son N gundeki siparis sayisi + toplam ciroyu dondurur.

        ShopifyClient.get_order_stats() ile ayni sozlesmeyi kullanir; asla
        raise etmez, hata durumunda {"ok": False, "error": ...} doner.
        """
        try:
            now = datetime.now(UTC)
            start = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            end = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            query = (
                f"/order?filter=creationdate:[{start}..{end}]&limit=200"
            )
            result = self._request("GET", query, base=FULFILLMENT_API_BASE)
            orders = result.get("orders", [])
            revenue = sum(
                float(o.get("pricingSummary", {}).get("total", {}).get("value") or 0)
                for o in orders
            )
            return {
                "ok": True,
                "order_count": len(orders),
                "revenue": revenue,
                "currency": self.currency,
                "window_days": days,
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "window_days": days}

    @staticmethod
    def format_order_for_agent(order):
        """eBay siparisini Master Agent'in bekledigi serbest metin formatina cevirir.

        ShopifyClient.format_order_for_agent() ile ayni sozlesmeyi kullanir,
        boylece iki kanalin siparisleri ayni ajan hattindan gecebilir.
        """
        buyer = order.get("buyer", {}).get("username") or "Bilinmeyen Musteri"
        items = ", ".join(
            f"{i.get('quantity')}x {i.get('title')}"
            for i in order.get("lineItems", [])
        ) or "urun yok"
        total = order.get("pricingSummary", {}).get("total", {})
        return (
            f"Musteri {buyer}, {items}, "
            f"Toplam {total.get('value')} {total.get('currency')} "
            f"(eBay Siparis No: {order.get('orderId')})"
        )
