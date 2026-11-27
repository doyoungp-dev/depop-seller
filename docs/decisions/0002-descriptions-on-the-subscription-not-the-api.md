# 2. Descriptions run on the seller's Claude subscription; the API key only groups photos

**Status:** accepted, 2026-09-20. **Area:** `describe.py`, `style.py`, `settings.py`.

## Context

Two kinds of Claude work happen in the app. Grouping hundreds of photos into items is a batch job
with structured output, priced per photo and shown before it runs. Writing descriptions is done item
by item, many times, and sellers already pay for a Claude plan. An early version wrote descriptions
through the API and was removed; later, the API key leaked into Claude Code's environment and
quietly billed descriptions to the API (about $0.66) instead of the subscription.

## Decision

- **Grouping** uses the Anthropic API with the seller's key (`group.py`, key passed explicitly).
- **Descriptions and style changes** use Claude Code (`claude -p`) on the seller's subscription,
  never the API. Two layers guarantee it: Claude Code is started with every `ANTHROPIC_*` variable
  removed, and the run is stopped (its whole process tree killed) unless Claude Code's first event
  says it uses no API key.
- The key is read from `.env` without being put into the process environment.

## Consequences

- Sellers see one predictable cost (grouping, priced up front) and no per-description charges.
- Claude Code has its own sign-in; Settings runs it in the browser and checks it.
- The rule is enforced in code and tested (`test_claude_code_never_sees_the_api_key`), not only
  written down.
