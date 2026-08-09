import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

PROCESSED_TAG = "ajans-islendi"


class ShopifyClient:
    """Shopify Admin API istemcisi.

    Kimlik dogrulama icin OAuth client_credentials grant kullanir (bkz.
    https://shopify.dev/docs/apps/build/dev-dashboard/get-api-access-tokens).
    Token 24 saatte bir dolar; bu sinif otomatik olarak yeniler.
    """

    def __init__(self):
        self.domain = os.environ["SHOPIFY_STORE_DOMAIN"]
        self.client_id = os.environ["SHOPIFY_CLIENT_ID"]
        self.client_secret = os.environ["SHOPIFY_CLIENT_SECRET"]
        self.api_version = "2024-10"
        self._token = None
        self._token_expires_at = 0

    def _get_token(self):
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        url = f"https://{self.domain}/admin/oauth/access_token"
        data = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        ).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        with urllib.request.urlopen(req) as resp:
            payload = json.loads(resp.read())

        self._token = payload["access_token"]
        self._token_expires_at = time.time() + payload.get("expires_in", 86399)
        return self._token

    def _request(self, method, path, body=None):
        url = f"https://{self.domain}/admin/api/{self.api_version}{path}"
        headers = {
            "X-Shopify-Access-Token": self._get_token(),
            "Content-Type": "application/json",
        }
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            raise RuntimeError(f"Shopify API hatasi ({e.code}): {detail}") from e

    def get_new_orders(self):
        """Henuz AJANS tarafindan islenmemis, odemesi tamamlanmis siparisleri dondurur."""
        result = self._request(
            "GET", "/orders.json?status=open&fulfillment_status=unfulfilled&limit=50"
        )
        orders = result.get("orders", [])
        return [o for o in orders if PROCESSED_TAG not in (o.get("tags") or "")]

    def mark_processed(self, order):
        existing = [t.strip() for t in (order.get("tags") or "").split(",") if t.strip()]
        if PROCESSED_TAG not in existing:
            existing.append(PROCESSED_TAG)
        self._request(
            "PUT",
            f"/orders/{order['id']}.json",
            {"order": {"id": order["id"], "tags": ", ".join(existing)}},
        )

    @staticmethod
    def format_order_for_agent(order):
        """Shopify siparisini Master Agent'in bekledigi serbest metin formatina cevirir."""
        customer = order.get("customer") or {}
        name = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
        name = name or "Bilinmeyen Musteri"

        items = order.get("line_items", [])
        items_desc = ", ".join(f"{i['quantity']}x {i['title']}" for i in items) or "urun yok"

        total = order.get("total_price")
        currency = order.get("currency")
        order_number = order.get("name")

        return (
            f"Musteri {name}, {items_desc}, "
            f"Toplam {total} {currency} (Shopify Siparis No: {order_number})"
        )
