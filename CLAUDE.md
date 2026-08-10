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
read_fulfillments, write_fulfillments, read_customers`.

The `shopify` command in `main.py` polls `GET /orders.json` for open,
unfulfilled orders, skips ones already tagged `ajans-islendi`, formats each
into the same free-text description `process_order()` expects, runs it
through the normal agent pipeline, then tags the order `ajans-islendi` in
Shopify so it isn't reprocessed. There is no webhook listener — this is
pull-based polling.

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

## eBay integration (in progress)

`ebay_client.py` (`EbayClient`) mirrors `shopify_client.py`'s pattern but
targets eBay's Sell API (Inventory + Offer), which — unlike Shopify's
app-only `client_credentials` grant — acts on the seller's behalf and
requires an `authorization_code`-derived refresh token. **Not yet
functional**: requires `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`,
`EBAY_REFRESH_TOKEN` in `.env`, obtained by creating a Production app at
developer.ebay.com and completing a one-time OAuth consent — this is a
manual, user-driven step, not something the app does itself. Once those
credentials exist, `create_or_update_listing()` publishes a listing via the
Inventory API + Offer API (`listingPolicies` require pre-existing eBay
Business Policies — fulfillment/payment/return — and a merchant location
key, set up in Seller Hub, not created by this client). `get_listing_quantity()`
/ `update_quantity()` read/write stock for a given SKU, feeding
`inventory_db.py`'s sync.

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
alongside `list_products()` / `check_shopify_orders()` once the eBay side
is live).

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
