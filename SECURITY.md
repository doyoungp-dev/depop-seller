# Security

Depop Seller runs on the seller's own computer. There is no server of ours and no account with us.
This page says what the app exposes, what protects it, and how to report a problem.

## Reporting a problem

Please report security problems privately: on this repository's **Security** tab, choose
**Report a vulnerability**. Don't open a public issue for them. Reports are read by the maintainer;
fixes ship as a normal release, which installed copies are offered through **Check for updates**.

Only the newest release is supported.

## What the app exposes

- **A local web server on `127.0.0.1:8765`.** It serves the app's own pages and is not reachable from
  other computers. Other websites open in the same browser cannot use it: answers carry CORS headers
  only for Depop's own pages and only on the few routes the Chrome helper needs (`web.py`,
  `DEPOP_ORIGINS` × `CORS_PATHS`), every other cross-site request is refused, and every POST from a
  foreign origin is refused. The Chrome helper's background worker is accepted on two routes only, one
  of them behind a single-use pass that expires after 10 minutes.
  Test: `test_only_depop_gets_cors_and_other_sites_cannot_post`.
- **The Chrome helper** runs in the seller's own Chrome. It reads Depop pages the seller is signed in
  to; the Depop sign-in never leaves Chrome, and the shop lists it reads are reduced to what the
  seller sees (no buyer names, no addresses) before they reach the app.

## Keys, accounts and data

- **The Anthropic API key** (used only to sort photos into items) is kept in a `.env` file in the
  seller's data folder. The Settings page shows a masked hint, never the key itself.
- **Descriptions** are written by Claude Code on the seller's own Claude subscription. It is started
  with every `ANTHROPIC_*` variable removed, and stopped if it reports any API key in use, so the paid
  key can never be billed for them.
- **Photos, listings and the seller's writing style** stay in the data folder on their computer. The
  only things sent anywhere are photos the seller chooses to group (to Anthropic), the photos and facts
  of an item they describe (to Claude), and what they post themselves (to Depop).

## Updates

The app asks GitHub for a new release only when the seller presses **Check for updates**. An update
must come from this repository's release downloads, stay under 50 MB, and contain only app files
inside one folder: no paths outside it, no `.env`, no data folders, no databases. Replaced files are
kept so a failed update is rolled back, and the new code must import cleanly before it is kept.

## Building and publishing

- Everything in this repository is public, so commits are checked before they are made: a Claude Code
  hook in `.claude/` stops any commit containing the developer's home folder, name or a real-looking
  key, and stops force pushes (`tests/test_guard.py`).
- The Windows installer build refuses to finish if any file in it contains a folder path of the
  machine that built it (`test_the_bundle_never_names_a_folder_of_the_release_machine`).
- Tests, linting and type checks run on Windows and macOS for every push and pull request; CI holds no
  secrets.
