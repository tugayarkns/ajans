# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A Python CLI (`main.py`) running a multi-agent order-fulfillment workflow
(Master → Order → Supplier → Payment → Shipping → Notify) via the Anthropic
Messages API, wired to a real Shopify store (`shopify_client.py`) for order
ingestion. All prompts and UI text are in Turkish. There is no test suite.

## Running

```
pip install -r requirements.txt
python main.py
```

Requires in `.env` (loaded via `python-dotenv`):
- `ANTHROPIC_API_KEY`
- `SHOPIFY_STORE_DOMAIN` (e.g. `norvexget.myshopify.com`)
- `SHOPIFY_CLIENT_ID` / `SHOPIFY_CLIENT_SECRET` (custom app credentials, see below)
- `OPENAI_API_KEY` (product model-photo generation, see below)
- `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` / `EBAY_REFRESH_TOKEN` and
  `EBAY_MARKETPLACE_ID` (see eBay integration section below)

Lint: `ruff check .` (config in `ruff.toml`).

## Agent loading convention

Every `.md` file in `agents/` is loaded at startup as a system prompt; the key
is the filename uppercased with `.md` stripped (e.g. `master_agent.md` →
`MASTER_AGENT`). `main.py` looks up `"MASTER_AGENT"` specifically as the
orchestrator, so that file must always exist.

To add a new agent: create `agents/<name>_agent.md` with `## Rol`,
`## Görevler`, and a `## Çıktı` (output format) section — no code changes
needed, it's picked up automatically by `load_agents()`.

## Model

`MODEL` in `main.py` is pinned to `"claude-opus-5"`. Text extraction uses
`next(b.text for b in response.content if b.type == "text")` rather than
`response.content[0].text`, because this model can emit a thinking block
before the text block.

## Shopify integration

`shopify_client.py` (`ShopifyClient`) authenticates via OAuth
`client_credentials` grant against `/admin/oauth/access_token` — not a static
Admin API access token. The token is cached in memory and auto-refreshed
(24h TTL). This is deliberate: the store's custom app was created through
Shopify's newer Dev Dashboard, which does not expose a simple "reveal token
once" flow the way the old admin-created custom apps did.

Required Admin API scopes on the app (set in Dev Dashboard → app →
Versions → new version → Scopes, then re-run "Install app" to refresh the
grant — deploying a new version alone does *not* update an already-installed
app's permissions): `read_orders, write_orders, read_products,
write_products, read_fulfillments, write_fulfillments, read_customers`.
`write_products` is required for `create_product()` / `add_product_image()` /
`update_variant_sku()` in `shopify_client.py`.

The `shopify` command in `main.py` polls `GET /orders.json` for open,
unfulfilled orders, skips ones already tagged `ajans-islendi`, formats each
into the same free-text description `process_order()` expects, runs it
through the normal agent pipeline, then tags the order `ajans-islendi` in
Shopify so it isn't reprocessed. There is no webhook listener — this is
pull-based polling.

**The pipeline does not actually fulfil anything.** The agents only produce
text: no supplier order is placed with DSers/AliExpress, no shipping label
is bought, no tracking number is real. Because the order is nevertheless
tagged `ajans-islendi` and therefore never shown again, a paid order could
silently go unshipped. `_warn_supplier_order_required()` exists for exactly
this: after each processed order it records a row in `inventory_db`'s
`supplier_tasks` table and logs a red `tedarikci` event. The panel renders
open tasks in a dedicated red section at the top with a "Sipariş verdim"
button hitting `POST /api/supplier-task/done`; completed rows keep their
`done_at` (nothing is deleted). A log line alone was not enough — the event
feed scrolls, and a missed line means an unshipped paid order. Do not
remove this without first making fulfilment genuinely automatic. The same
applies to eBay orders (see below).

Automatic supplier ordering is **not currently possible**: the DSers MCP
surface is catalog-only (find / import / preview / push / remap supplier /
inventory policy) and exposes no order-placement endpoint, so nothing in
this codebase can place the AliExpress order on the merchant's behalf.

## Product image generation

`product_image.py` calls OpenAI's `gpt-image-2` model (`client.images.generate`,
**not** the Anthropic API — Claude has no image generation) to produce an
AI-model product photo, returned as base64 PNG. `list_products()` uploads it
to the newly-created Shopify product via `ShopifyClient.add_product_image()`
(`POST /products/{id}/images.json`). Image generation failure is caught and
logged but does not roll back the product creation — the product stays
listed without a photo if this step fails.

## Automatic mode

`MultiAgentSystem.run_automatic()` (menu command `otomatik`) loops
`list_products()` + `check_shopify_orders()` every `AUTO_INTERVAL_SECONDS`
(default 300s) until `Ctrl+C`, which returns to the interactive menu rather
than exiting the process. This is an in-process polling loop, not a
scheduled task — the terminal must stay open for it to keep running.

## eBay integration

`ebay_client.py` (`EbayClient`) mirrors `shopify_client.py`'s pattern but
targets eBay's Sell API (Inventory + Offer), which — unlike Shopify's
app-only `client_credentials` grant — acts on the seller's behalf and
requires an `authorization_code`-derived refresh token. **Live and
functional**: `EBAY_CLIENT_ID`/`EBAY_CLIENT_SECRET` come from a Production
keyset at developer.ebay.com (Application Keys page); `EBAY_REFRESH_TOKEN`
comes from a one-time browser OAuth consent (`sell.inventory` scope) via
`https://auth.ebay.com/oauth2/authorize?...&redirect_uri=<RuName>`, then
exchanging the returned `code` for a token at
`https://api.ebay.com/identity/v1/oauth2/token` — this is a manual,
user-driven step, not something the app does itself, and the refresh token
is long-lived (~18 months) but not indefinite.

Before the keyset can make production calls, eBay requires subscribing to
or opting out of "Marketplace Account Deletion" notifications (Application
Keys → Notifications page). Since AJANS doesn't persist eBay buyer personal
data, we filed for the **exemption** (toggle "Exempted from Marketplace
Account Deletion" → Confirm → pick "I do not persist eBay data" → Submit)
rather than standing up a public HTTPS webhook endpoint.

`create_or_update_listing()` publishes a listing via the Inventory API +
Offer API (`listingPolicies` require pre-existing eBay Business Policies —
fulfillment/payment/return — and a merchant location key, set up in Seller
Hub, not created by this client). `get_listing_quantity()` / `update_quantity()`
read/write stock for a given SKU, feeding `inventory_db.py`'s sync.

Note: `get_listing_quantity()` returns `None` (404 from the API) for any
SKU whose eBay listing was created through the classic Seller Hub UI rather
than through the Inventory API — the two are different data models and
classic listings aren't visible via `/inventory_item/{sku}` even when the
SKU is set correctly. This affects the four `AJANS-001`..`AJANS-004`
listings described below. Confirmed by contrast: `AJANS-005`, published
through the Inventory API, reads back correctly.

### Account prerequisites (one-time, already done for this account)

Publishing through the Inventory API needs all of these to exist first;
each was set up via API during the eBay go-live:
- **Merchant location** `AJANS_MAIN` (Herndlgasse 8/15, Wien 1100, AT) —
  `POST /sell/inventory/v1/location/{key}`. Without it, publish fails.
- **Business Policies opt-in** — the account was *not* eligible at first
  (`errorId 20403 "User is not eligible for Business Policy"`); fixed with
  `POST /sell/account/v1/program/opt_in {"programType":
  "SELLING_POLICY_MANAGEMENT"}`.
- **Three policies** (fulfillment / payment / return) on `EBAY_AT`, created
  via `/sell/account/v1/*_policy`. The fulfillment policy uses a 3-day
  handling time, consistent with the dropshipping reality documented in
  `agents/shipping_agent.md`.

Note the token needs `sell.account` scope to read/write policies and
`sell.fulfillment` for orders — `sell.inventory` alone returns 403 on those
endpoints. `SCOPE` in `ebay_client.py` covers all three; changing it
requires redoing the browser OAuth consent to mint a new refresh token.

### Content-Language must match the marketplace

eBay stores inventory records per locale. Sending the wrong `Content-Language`
lets `PUT /inventory_item/{sku}` succeed (204) while the subsequent
`POST /offer` fails with `errorId 25751 "SKU ... could not be found ... for
the marketplace EBAY_AT"` — a confusing failure that looks like the item was
never created. `MARKETPLACE_LANGUAGES` in `ebay_client.py` maps
`EBAY_MARKETPLACE_ID` (set in `.env`, currently `EBAY_AT`) to the right
language tag, and `_request()` sends it on every call.

Taxonomy endpoints (`/commerce/taxonomy/...`, used to look up `categoryId`)
reject the user token with 403 — they need a plain `client_credentials`
application token instead.

### Category-required aspects

Publishing fails with `errorId 25002` naming a missing aspect (in the
marketplace's language, e.g. *"Das erforderliche Artikelmerkmal Hersteller
fehlt"*) unless every aspect that category marks `aspectRequired` is
supplied. These differ per category — `262203` (car storage) wants
`Hersteller`, while `123417`/`35190` (phone accessories) want `Marke` and
`Produktart`, and `Produktart` only accepts values from eBay's own
enumeration. Look them up with
`/commerce/taxonomy/v1/category_tree/16/get_item_aspects_for_category?category_id=…`
(app token) and pass them via `create_or_update_listing(aspects=…)`; the
default only covers `Marke`/`Herstellernummer`, which is not enough for
most categories. EU GPSR rules are why `Hersteller` is now mandatory.

Currently listed via the Inventory API on `EBAY_AT`: `AJANS-005`
(307118017053), `AJANS-006` (307118047792), `AJANS-007` (307118048040),
`AJANS-008` (307118048374).

### eBay order polling

`check_ebay_orders()` (menu command `ebay`, also part of `run_automatic()`)
pulls unshipped orders from the Fulfillment API and pushes them through the
same agent pipeline as Shopify orders — `EbayClient.format_order_for_agent()`
deliberately emits the same free-text shape as its Shopify counterpart.

Deduplication differs by necessity: Shopify orders get tagged
`ajans-islendi` on the order itself, but the eBay API has no equivalent, so
processed eBay order ids are recorded locally in `inventory_db`'s
`processed_orders` table. That means **wiping `inventory.db` would cause
already-handled eBay orders to be reprocessed**, whereas Shopify's tag
survives independently of local state.

The four products currently listed on eBay were created manually through
the browser (Seller Hub UI), not through this client. Each now shares a
canonical SKU (`AJANS-001`..`AJANS-004`) with one Shopify variant — set on
both sides (eBay "Custom label" field, Shopify variant SKU via
`update_variant_sku()`) and seeded into `inventory_db.py`. Note the pool/eBay
quantities (10/8/5/15) intentionally differ from the larger Shopify variant
quantities (54/68/33/65) — the eBay listings were published with smaller,
deliberately chosen sell-through quantities, not the full Shopify stock.

## Stock sync (`inventory_db.py`)

Stdlib-only (`sqlite3`, no new dependency) local database tracking a single
"pool" quantity per SKU across Shopify and eBay, since neither platform
knows about the other's stock. Schema: `inventory(sku PRIMARY KEY, title,
pool_qty, shopify_qty, ebay_qty, updated_at)`. `upsert()` preserves
whichever channel quantity isn't passed in, so a Shopify-only or eBay-only
update doesn't clobber the other channel's last known value. Depends on
`ShopifyClient.get_product_quantity(sku)` / `EbayClient.get_listing_quantity(sku)`
existing and on both channels' listings sharing the same SKU — not yet
wired into `main.py`'s `run_automatic()` loop (planned as a third step
alongside `list_products()` / `check_shopify_orders()`; the eBay side is
now live, this wiring just hasn't been done yet).

## Live panel

`panel.py` starts a stdlib-only (`http.server`, no new dependency) HTTP
server on a background daemon thread at program startup (`panel.start()` in
`main()`), printing the URL to the console. It serves a single
auto-refreshing HTML page (polls `/api/data` every 2s) showing agent count,
automatic-mode status, last check time, and a live event table. Call sites
(`process_order`, `check_shopify_orders`, `list_products`, `run_automatic`)
report through `panel.log_event(kind, message, status)` and
`panel.set_state(**kwargs)`. Events are also appended to
`activity_log.jsonl` (gitignored) so history survives a restart — loaded
back in on `panel.start()`.
