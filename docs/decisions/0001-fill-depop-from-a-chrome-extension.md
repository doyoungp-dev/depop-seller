# 1. Fill Depop's listing form from a Chrome extension, not browser automation

**Status:** accepted, 2026-09-19. **Area:** selling (`chrome_extension/`, `static/sell.html`, `listing.py`).

## Context

The Depop button has to put an item's photos (in the seller's order) and its description into
Depop's listing form. The first version drove a Chrome window with Playwright. On its second run,
Depop's bot protection answered 403: an automated browser is exactly what it is built to stop.

## Decision

A small Manifest V3 extension, loaded by the seller into their own Chrome, fills the form. It runs
in the browser the seller is already signed in to, with no automation flags. The app hands it the
item through `chrome.storage`; the extension's background worker fetches the photos from the app and
the page's content script fills the form. Since Chrome's Local Network Access and a consent script
on Depop's page block websites from calling `127.0.0.1`, the Depop tab never calls the app itself.

The app never presses **Post**. The seller checks the listing, adds price and category, and posts it.

## Consequences

- Nothing for Depop to block, and no second sign-in.
- One extra setup step for sellers (load the helper at chrome://extensions), explained on the
  Settings tab. Unpacked extensions don't update themselves, so the pages warn when Chrome still
  runs an older helper.
- Playwright stays only as an optional fallback (`listing.py`) and is not installed by default.
- The final, public action always stays with a person.
