import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

REQUEST_TIMEOUT_SECONDS = 30
TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
API_BASE = "https://api.ebay.com/sell/inventory/v1"
SCOPE = "https://api.ebay.com/oauth/api_scope/sell.inventory"


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

    def _request(self, method, path, body=None):
        url = f"{API_BASE}{path}"
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
            "Content-Language": "en-US",
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
        country_of_origin="CN",
    ):
        """Inventory item olusturur/gunceller, offer acar ve yayinlar.

        fulfillment_policy_id / payment_policy_id / return_policy_id / merchant_location_key
        eBay hesabinda (Seller Hub > Business Policies + Shipping locations)
        onceden tanimlanmis olmali; bu istemci onlari olusturmaz, sadece
        referans olarak kullanir.
        """
        self._request(
            "PUT",
            f"/inventory_item/{sku}",
            {
                "availability": {"shipToLocationAvailability": {"quantity": quantity}},
                "condition": condition,
                "product": {
                    "title": title,
                    "description": description_html,
                    "imageUrls": image_urls or [],
                },
            },
        )

        offer = self._request(
            "POST",
            "/offer",
            {
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
                "pricingSummary": {"price": {"value": str(price), "currency": "USD"}},
                "countryOfOrigin": country_of_origin,
            },
        )
        offer_id = offer["offerId"]

        publish_result = self._request("POST", f"/offer/{offer_id}/publish", {})
        return {"sku": sku, "offer_id": offer_id, "listing_id": publish_result.get("listingId")}

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
