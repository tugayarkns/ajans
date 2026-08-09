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
pull-based polling, triggered manually by the `shopify` command.
