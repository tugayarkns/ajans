# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A single-file Python demo (`main.py`) simulating a multi-agent order-fulfillment
workflow (Master → Order → Supplier → Payment → Shipping → Notify) via the
Anthropic Messages API. All prompts and UI text are in Turkish. There is no
test suite, linter, or build step.

## Running

```
pip install -r requirements.txt
python main.py
```

Requires `ANTHROPIC_API_KEY` in `.env` (loaded via `python-dotenv`).

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
