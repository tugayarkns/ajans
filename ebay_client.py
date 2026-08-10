import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

REQUEST_TIMEOUT_SECONDS = 30
TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
API_BASE = "https://api.ebay.com/sell/inventory/v1"
FULFILLMENT_API_BASE = "https://api.ebay.com/sell/fulfillment/v1"
SCOPE = (
    "https://api.ebay.com/oauth/api_scope/sell.inventory "
    "https://api.ebay.com/oauth/api_scope/sell.account "
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment"
)

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

    def __init__(self):
        self.client_id = os.environ["EBAY_CLIENT_ID"]
        self.client_secret = os.environ["EBAY_CLIENT_SECRET"]
        self.refresh_token = os.environ["EBAY_REFRESH_TOKEN"]
        self.marketplace_id = os.environ.get("EBAY_MARKETPLACE_ID", "EBAY_US")
        self.content_language = MARKETPLACE_LANGUAGES.get(self.marketplace_id, "en-US")
        self.currency = MARKETPLACE_CURRENCIES.get(self.marketplace_id, "USD")
        self._token = None
        self._token_expires_at = 0

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

    def _request(self, method, path, body=None, base=API_BASE):
        url = f"{base}{path}"
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
            "Content-Language": self.content_language,
        }
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            raise RuntimeError(f"eBay API hatasi ({e.code}): {detail}") from e

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
                    "title": title[:80],
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
