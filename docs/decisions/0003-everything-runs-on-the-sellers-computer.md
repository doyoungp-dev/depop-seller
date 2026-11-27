# 3. Everything runs on the seller's computer

**Status:** accepted, 2026-09-19. **Area:** the whole app.

## Context

The app handles a seller's photos, listings, writing style and an API key. Its users are not
engineers, and the project has no budget or wish to run a service.

## Decision

- No server of ours, no accounts, no hosted database. The app is a local web server on
  `127.0.0.1` with local files and SQLite.
- The only network calls are the Anthropic API (grouping), Claude Code on the seller's subscription
  (descriptions), Depop in the seller's own Chrome, and GitHub, only when the seller presses
  **Check for updates** or **Update**.
- The seller's data lives in one data folder, separate from the app folder, so moving to another
  computer is one copy and the app folder can be replaced, updated or published.

## Consequences

- Nothing to operate, nothing to breach centrally, nothing to pay for.
- Distribution and updates go through GitHub Releases: a Windows installer that bundles its own
  Python, and a Mac zip that sets itself up.
- CI (tests only, no secrets) is the one hosted piece, and it never builds or publishes.
