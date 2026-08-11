# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Numbered project map (`HARITA.md`)

`HARITA.md` numbers the system **1-48 in workflow order**, not by file:
1-6 product discovery/approval, 7-16 publishing, 17-27 order handling,
28-30 stock, 31-38 panel, 39-48 config/files. Each entry says in plain
non-technical Turkish what that station does, what a failure looks like from
the outside, and — as a footnote for us — which file/function it maps to. It
ends with a "what this system deliberately cannot do" section (no automatic
supplier ordering, no real shipping labels, no hosted panel) so those don't get
reported as bugs.

The user is non-technical and reports issues by number ("8 bozuk", "26
çalışmıyor"). **When a message contains such a number, go straight to that
entry's file and function; do not re-scan the project** — the numbering exists
specifically to keep context (and cost) small.

Renumbering breaks the user's mental index, so **never renumber existing
entries.** When adding a station, append it or use a letter suffix (e.g. `8b`);
when a function moves or is renamed, update only the file/function footnote of
its entry.

## Project

A Python CLI (`main.py`) running a multi-agent order-fulfillment workflow
(Master → Order → Supplier → Payment → Shipping → Notify) via the Anthropic
Messages API, wired to a real Shopify store (`shopify_client.py`) for order
ingestion. All prompts and UI text are in Turkish. There is no general test
suite; `test_policy.py` covers only the product-selection policy (see below).

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
- `EBAY_MARKETPLACES` (comma-separated eBay sites to dual-publish to, e.g.
  `EBAY_AT,EBAY_US`) plus, per site, `EBAY_{SITE}_FULFILLMENT_POLICY_ID` /
  `EBAY_{SITE}_PAYMENT_POLICY_ID` / `EBAY_{SITE}_RETURN_POLICY_ID` /
  `EBAY_{SITE}_MERCHANT_LOCATION_KEY` (dual-channel publish on new
  products, see "Dual-channel publish on new products" below)

Lint: `ruff check .` (config in `ruff.toml`).

Tests: `python test_policy.py` — regression checks for the product-selection
policy (`trust_score.py`, `ebay_client._search_query`). Run it after touching
either file; see "Regression tests" below for why it exists.

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

Because the red panel task (see above) only surfaces while the panel tab is
open, `notifier.py`'s `send_supplier_alert()` also emails the same warning —
called right after `panel.log_event("tedarikci", ...)` in
`_warn_supplier_order_required()`. It posts to the Resend HTTP API
(`RESEND_API_KEY` / `NOTIFY_EMAIL_TO` in `.env`) via stdlib `urllib`, not
`requests` (this repo has no HTTP client dependency — `shopify_client.py`
and `ebay_client.py` both already use `urllib` for the same reason).
Gmail SMTP + App Password was tried first and rejected every login attempt
with `535 5.7.8 BadCredentials` even with a freshly generated,
byte-verified-correct app password (confirmed via SMTP debug trace) — the
account-side cause couldn't be identified from the browser, so this was
abandoned in favor of Resend. Missing config makes `send_supplier_alert()`
a silent no-op (logged once as an `info` panel event, not an error) so a
merchant who hasn't set it up yet sees no behavior change. Send failures
are caught and logged, never raised — this is best-effort and must not
block order processing. Resend's sandbox sender (`onboarding@resend.dev`,
the default for `NOTIFY_EMAIL_FROM`) only delivers to the email address
the Resend account itself was signed up with, until a custom domain is
verified — fine here since `NOTIFY_EMAIL_TO` is the same address
(`tugayarkns@gmail.com`, the account this whole integration is under —
note the trailing "s", easy to mistype as `tugayarkn@gmail.com`).

The first Resend call also failed, with a Cloudflare `403`/error `1010`
(not a Resend-shaped error body) — Cloudflare sits in front of
`api.resend.com` and was rejecting `urllib`'s default `Python-urllib/x.y`
User-Agent as bot traffic. Fixed by sending a browser-like `User-Agent`
header; see `notifier.py`'s request headers.

## Product image generation

**AI never generates product photos.** `product_image.py` only makes the brand
logo (`generate_logo`, OpenAI `gpt-image-2`). It used to have
`generate_model_photo()` / `generate_model_photos()` filling in missing product
shots; that was removed on 2026-08-11 after the merchant rejected it: a
generated photo does not show the item the customer actually receives
(stitching, colour, pocket count all differ), which is a direct **return-risk
and trust problem**. Do not reintroduce it. Product photos come only from the
supplier.

**Where the single-image problem actually came from.** `dsers_find_product`
returns exactly **one** image per search hit. The scheduled discovery bot was
posting that single thumbnail to `/api/discovery/submit`, so those products went
live with one photo — while the eight products imported properly through DSers
(`dsers_product_import` → `dsers_product_preview(include_images=true)`, which
returns the real gallery, e.g. `images: 18`) all had 5-13 real photos. The fix
is in the discovery step, not in the publish step: see `agents/scout_agent.md`,
which makes import→preview mandatory and forbids submitting the search
thumbnail.

`panel.MIN_PRODUCT_IMAGES` (6) is the floor for every publish path.
`panel.attach_product_images()` uploads the supplier URLs and returns the
**Shopify CDN** URLs — eBay is given those rather than the original supplier
links, since an AliExpress CDN URL may not be fetchable from eBay's side while a
Shopify-hosted image always is. It never generates or substitutes anything.

`publish_dual_channel()` creates every product as `status="draft"` first and
only flips it to `active` (and publishes to eBay) once at least
`MIN_PRODUCT_IMAGES` real images actually attached. Under the floor, the product
stays an invisible draft with a red `urun` event — deliberately preferring "not
for sale" over "for sale with one photo".

`main.py`'s `backfill_product_images()` (menu command `gorseller`) now only
**reports** which products are short of the floor. It cannot fix them itself:
real photos exist only in DSers, which `main.py` cannot reach (see the
architecture note under "Proactive product discovery"). Repair means a Claude
Code session locating the source product and uploading its gallery.

## Product selection policy (`trust_score.py`)

The store is dropshipping — nobody here has ever held the product — so choosing
the wrong item costs returns, bad reviews and shipping losses. `trust_score.py`
encodes the merchant's chosen policy: **few but solid products**.

`find_blockers()` returns hard disqualifiers (rating < 4.6, orders < 1000, real
images < 6, stock < 20, price > 40 EUR, margin < 30%, plus `RISK_PATTERNS` for
return-prone categories: sized clothing, device-model-specific items, fragile
glass/ceramic, cosmetics/food, skin contact, lithium batteries, counterfeit
brand risk, items needing installation). Missing `rating`/`orders`/`stock` is
itself a blocker — an unverifiable product is not sellable. `evaluate()` adds a
0-100 score (rating 30 · orders 20 · images 15 · stock 10 · margin 15 ·
competition 10).

Two regex traps worth remembering, both found by testing: `boots?` matched "car
**boot** organizer" (British for trunk — a core category here), and "one size
fits all" was treated as a sizing risk when it is actually the opposite, a
universal-fit advantage. Both are now narrowed, with comments saying why.

`EbayClient.count_competing_listings()` supplies the competition signal via the
Browse API (`/buy/browse/v1/item_summary/search`) using the **app token** from
`_get_app_token()` — the same client-credentials token the taxonomy calls use,
so this needs no new OAuth consent. It never raises; on failure it returns
`None` and the score treats competition as neutral.

The gate runs **server-side** in `panel.screen_candidate()`, called from
`add_pending_products()`. The bot's own `score` is ignored and recomputed here,
so an over-optimistic scout cannot push a risky product into the store.
Rejected candidates never enter the queue — they go to `panel._rejected` and are
shown in the panel's "Elenen Adaylar" table with their reasons, so the merchant
can see what the agent filtered out and why. `add_pending_products()` returns
`(accepted, rejected)` and `/api/discovery/submit` reports both back to the
caller.

`main.py`'s `audit_catalog()` (menu command `denetim`) runs the same rules over
the already-listed catalogue and prints a KALSIN / DÜZELT / KALDIR
recommendation per product. It deliberately changes nothing — the merchant
decides. It only passes the signals Shopify actually has (image count, price,
title/description), stubbing rating/orders/stock at the threshold values so
"unknown" doesn't masquerade as a finding.

**It also runs unattended.** `run_automatic()` calls `audit_catalog(quiet=True)`
roughly once an hour (`audit_every = round(3600 / interval_seconds)` cycles,
not every 5-minute tick — 13+ per-product eBay competition lookups every cycle
would be wasteful and would spam the panel). Quiet mode suppresses console
output and only writes the panel summary event when there's something to flag
(`kaldir` or `duzelt` non-empty); a fully clean catalogue logs nothing, so real
problems don't get lost in "all good" noise. This exists specifically so a
regression like the 2026-08-11 single-image incident (see below) surfaces on
its own instead of waiting for the merchant to remember to run `denetim`.

## Regression tests (`test_policy.py`)

No test framework is used elsewhere in this repo, but `trust_score.py` and
`ebay_client._search_query()` broke twice during manual testing on
2026-08-11 — once quietly, in a way that would have shipped as a real bug if
not caught by hand:
- The regex `boots?` matched "car **boot** organizer" (UK for trunk, a core
  category here) and mislabelled it as footwear.
- "one size fits all" was flagged as a sizing risk when it's actually the
  opposite — a universal-fit advantage.
- The eBay competition query, run with the full product title, returned 0 for
  almost every product (titles are too specific) until shortened and
  stopword-filtered in `_search_query()`.

`python test_policy.py` (stdlib `assert`, no pytest dependency) encodes these
three cases plus the boundary values for every hard blocker (rating 4.6,
orders 1000, images 6, stock 20) so a future edit to `trust_score.py` or
`_search_query()` fails loudly instead of silently reintroducing one of these.
Run it after touching either file.

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
`EbayClient.get_required_aspects()` automates this lookup — see "Never
fabricate item specifics" below for how unknown values are filled.

Currently listed via the Inventory API on `EBAY_AT`: `AJANS-005`
(307118017053), `AJANS-006` (307118047792), `AJANS-007` (307118048040),
`AJANS-008` (307118048374).

### Dual-channel publish on new products

`main.py`'s `list_products()` and `panel.py`'s `_publish_product()` (the
"Onayla ve Yayinla" button on discovery candidates) both now publish every
new product to eBay right after Shopify, via `panel.sync_ebay_listing()` /
`panel.publish_dual_channel()`. Since product types scanned by discovery
vary widely (car accessories, LED lighting, phone/desk accessories, ...)
and each lands in a different eBay category with different required
aspects (see "Category-required aspects" above), there is no fixed
category — `EbayClient.suggest_category(title)` calls the taxonomy API's
`get_category_suggestions` (using an app-only `client_credentials` token
via `_get_app_token()`/`_taxonomy_request()`, since taxonomy endpoints
reject the user token) against the marketplace's actual default category
tree (`_get_category_tree_id()`, fetched once and cached — do not hardcode
a tree id, it differs per marketplace and an earlier draft of this feature
got it wrong by assuming tree `77` for `EBAY_AT` when it's actually `16`).
`EbayClient.get_required_aspects(category_id)` then reads that category's
`aspectRequired` fields and fills them: known GPSR/brand fields
(`Marke`/`Hersteller`/`Herstellernummer`, see `_ASPECT_DEFAULTS` in
`ebay_client.py`) get the same placeholder values as before; other
required fields get the first value the category's own aspect list offers
if it's enum-constrained (`SELECTION_ONLY`), or `"Nicht zutreffend"` if
free text. This is best-effort, not perfectly accurate categorization, but
avoids the outright publish failures a wrong/missing category or aspect
caused. If no category is found for a title, publishing raises and is
caught — the Shopify listing is not rolled back, just logged as a red
`urun` event.

**Multi-site publish.** eBay's sites (`EBAY_AT`, `EBAY_US`, ...) are
separate catalogs — a listing published with `marketplaceId: EBAY_AT` is
only searchable/visible on ebay.at, not on ebay.com, even though both are
"the same eBay account" in Seller Hub. This is why `AJANS-001..004`
(created manually, targeting `EBAY_US`) show up on the ebay.com store page
but `AJANS-005..008` (published via this client to `EBAY_AT`) don't, and
vice versa on ebay.at. `panel._ebay_marketplaces()` reads a comma-separated
`EBAY_MARKETPLACES` env var (default: falls back to single-site
`EBAY_MARKETPLACE_ID`) and `sync_ebay_listing()` loops over it, publishing
the same SKU to every listed site with `EbayClient(marketplace_id=...)`
(the constructor accepts an override so one process can drive multiple
sites with independently cached tokens/category-tree-ids). One site
failing (e.g. a category/aspect mismatch particular to that site's
taxonomy) doesn't block the others — each is logged separately.

Each site in `EBAY_MARKETPLACES` needs its own **namespaced** `.env`
policy block: `EBAY_{SITE}_FULFILLMENT_POLICY_ID`,
`EBAY_{SITE}_PAYMENT_POLICY_ID`, `EBAY_{SITE}_RETURN_POLICY_ID`,
`EBAY_{SITE}_MERCHANT_LOCATION_KEY` (e.g. `EBAY_AT_FULFILLMENT_POLICY_ID`,
`EBAY_US_FULFILLMENT_POLICY_ID`). The `EBAY_AT_*` ones are the same
policy/location identifiers from "Account prerequisites" above, which were
created during the original eBay go-live but never previously written to
`.env` since nothing read them. The `EBAY_US_*` ones were created the same
way for the US site specifically for this feature — note the US
fulfillment policy's flat-rate shipping service code had to be
`shippingCarrierCode: "USPS"` / `shippingServiceCode: "USPSPriority"`;
several other plausible-looking codes (`USPSPriorityMail`,
`US_USPSPriorityMail`, `GENERIC`/`AT_StandardDispatch`-style site-prefixed
codes) are rejected by eBay's LSAS validation with an opaque
`UNKNOWN_SHIPPING_SERVICE_CODE` error and no discoverable code list (the
`/sell/metadata/v1/marketplace/{id}/get_shipping_service_codes` endpoint
404s), so this had to be found by trial and error against the live API.
All four values for any site can be re-fetched read-only via
`GET /sell/account/v1/{fulfillment,payment,return}_policy?marketplace_id=...`
and `GET /sell/inventory/v1/location` if ever lost. Missing any of a site's
four values makes `sync_ebay_listing()` fail (and log) for that site only.

`panel._next_sku()` auto-generates the next `AJANS-NNN` SKU (based on the
highest existing SKU in `inventory_db` plus the hardcoded `AJANS-001..008`)
and writes it to the Shopify variant via `update_variant_sku()` — SKU
assignment is no longer a manual step for products published through these
two paths. New eBay listings get `_DEFAULT_EBAY_QUANTITY` (10) rather than
the Shopify variant's full stock, consistent with the smaller sell-through
quantities described above.

**Currency conversion.** Shopify prices are EUR. `sync_ebay_listing()` /
`_publish_to_ebay()` pass that EUR number to
`EbayClient.convert_price_from_eur()`, which multiplies by a static rate
from `EUR_EXCHANGE_RATES` in `ebay_client.py` (e.g. `1.08` for USD) before
publishing to a non-EUR site. This is a hardcoded rate, not a live FX
lookup — it drifts over time and needs manual updates in that dict; the
first version of this feature skipped conversion entirely and published
the same numeric price in USD as in EUR, silently giving away the ~8-10%
difference on every US sale.

**Title truncation.** `EbayClient.create_or_update_listing()` caps titles
at eBay's 80-character limit via `_truncate_title()`, which backs off to
the last space rather than hard-cutting mid-word — a naive `title[:80]`
was shipping titles like "...Fast Charge for Phone, Watch & Earbu"
(cut mid-word), which reads as broken/untrustworthy to a buyer.

**Transient `errorId 25604` is retried automatically.** eBay intermittently
returns `25604` ("Availability not found. Please try again or contact
customer support") on well-formed `PUT /inventory_item` / `PUT /offer`
calls — unrelated to the payload; identical requests succeed on retry.
`_request()` retries only the ids in `_TRANSIENT_ERROR_IDS`
(`TRANSIENT_RETRY_ATTEMPTS` times, `TRANSIENT_RETRY_DELAY_SECONDS` apart);
every other error still raises on the first attempt, since retrying a real
validation failure (missing aspect, bad category) just wastes time.

**One eBay SKU per marketplace — `{sku}-{SITE}`.** The
`/inventory_item/{sku}` record is shared across marketplaces despite
`Content-Language`: publishing the same SKU to two sites writes
`title`/`description`/`aspects` to a single underlying record, and since
aspect *field names* are locale-specific (German `Produktart` vs English
`Type`), whichever site published last won the item-specifics language for
both — a US buyer would see German field names. `panel.ebay_sku_for()`
therefore suffixes the canonical SKU per site (`AJANS-009` →
`AJANS-009-AT` / `AJANS-009-US`), which makes each site's inventory record
structurally independent. The Shopify variant SKU stays canonical
(`AJANS-009`); `inventory_db.ebay_listing_skus` maps
`(sku, marketplace_id) → ebay_sku` so `sync_inventory()` knows which SKU to
read/write per site. SKUs with no mapping row (the older `AJANS-001..008`)
fall back to using the canonical SKU against the default marketplace, which
preserves their existing single-site behaviour.

Note eBay also blocks publishing what it considers a duplicate listing
(`errorId 25002`, *"Es sieht so aus, als ob dieses Angebot für einen
Artikel ist, den Sie bereits bei eBay eingestellt haben"*) — when migrating
an existing listing to a new SKU, the old offer must be withdrawn and
deleted (`POST /offer/{id}/withdraw` then `DELETE /offer/{id}`) *before*
the replacement can publish on that same marketplace.

**Never fabricate item specifics.** `get_required_aspects()` fills required
aspects that aren't brand/manufacturer fields with a localized "does not
apply" string (`_NOT_APPLICABLE_BY_LANGUAGE`) whenever eBay allows free
text. An earlier version took the category's first *suggested* value
instead, which invented physical measurements on real listings (a sun-visor
organizer went out with `Item Height: 15 cm`, `Item Length: Less Than 5 in`
— values nobody had measured). Only genuinely `SELECTION_ONLY` aspects fall
back to the first enumerated value, because those cannot be left blank and
cannot take free text; that remains a best-effort guess and is the reason
category accuracy matters (see `suggest_category`, which passes the product
description alongside the title precisely to land in a category whose
required aspects are answerable).

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
update doesn't clobber the other channel's last known value. Wired into
`main.py`'s `run_automatic()` loop via `MultiAgentSystem.sync_inventory()`
(also reachable manually with the `stok` menu command).

A second table, `ebay_listing_skus(sku, marketplace_id, ebay_sku)`, maps a
canonical SKU to its per-marketplace eBay SKU (see "One eBay SKU per
marketplace" above). `sync_inventory()` reads it to know which SKU to query
on which site, creating one `EbayClient` per marketplace; SKUs with no
mapping fall back to the canonical SKU on `EBAY_MARKETPLACE_ID`. The
reduction step ("Shopify sold N, drop eBay quota by N") is applied to every
site the SKU is listed on, and `shopify_qty`/`pool_qty` track the *lowest*
of the sites' quantities.

`ShopifyClient.get_product_quantity()` deliberately returns `None` — not
`0` — for variants with inventory tracking disabled (`inventory_management`
empty). Shopify reports `inventory_quantity: 0` for those even though they
are still infinitely sellable, which is the normal dropshipping setup here
(`AJANS-009`..`AJANS-013` are all untracked). Treating that 0 as real stock
would let a later reading make the sync think everything sold out and zero
the eBay quota on every site.

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

Since `start()` now binds `0.0.0.0` by default (so the panel is reachable
from other devices, e.g. through a tunnel — see below), every page and
`/api/*` route except `/login` requires a session cookie issued by
`panel_auth.py` (PBKDF2-hashed admin accounts stored in `panel_admins.json`,
gitignored; HMAC-signed session tokens). Manage admins from the `main.py`
menu: `admin-ekle` / `admin-liste` / `admin-sil`.

### Proactive product discovery (`/api/discovery/submit`)

Nothing in this codebase can call DSers MCP tools itself — that surface is
only reachable from a Claude Code session, not from `main.py`'s own
Anthropic-Messages-API agent pipeline (see "Automatic supplier ordering" above).
So proactive "find new products" scanning has to live in a *separate*
scheduled agent (e.g. a daily cloud routine with DSers MCP access) that POSTs
its finds to this panel. `POST /api/discovery/submit` accepts
`{"items": [...]}` (same shape `panel.add_pending_products()` expects, plus
optional `score` 0-100 and `score_reason`), authenticated via
`Authorization: Bearer <DISCOVERY_API_TOKEN>` (a `.env` secret, deliberately
separate from the cookie-based admin login since the caller is a bot, not a
browser). Items missing `id` get one generated (`uuid.uuid4().hex`).

Every submitted item must now carry the real supplier gallery (`image_urls`,
≥6) plus `rating` / `orders` / `stock`, and is screened by
`panel.screen_candidate()` before it can enter the queue — see "Product
selection policy" above and `agents/scout_agent.md` for the contract the
scheduled agent must follow. Accepted items land in the pending-approval queue
sorted by `score` descending; nothing is ever auto-published, every candidate
still needs a human "Onayla ve Yayınla" click. For this to work at all, the machine running `python main.py` must be
on and network-reachable from wherever the scheduled agent runs (e.g. via a
Cloudflare Tunnel) — there is no server-side deployment of this app.
