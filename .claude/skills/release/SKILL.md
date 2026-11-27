---
name: release
description: Publish a new Depop Seller release to its users (Windows release machine only). Use when the owner asks to release, publish or ship a version, or to get a change to sellers.
---

# Release Depop Seller

A release reaches every installed copy through **Check for updates**, so it is never a side effect of
other work. The owner says yes to publishing; `.claude/hooks/guard.py` asks for it as well.

## Before

1. Be on the Windows machine (Inno Setup builds the installer there): `git switch main`, `git pull`,
   and a clean `git status`.
2. CI must be green on `HEAD`: `gh run list --repo doyoungp-dev/depop-seller --commit $(git rev-parse HEAD)`.
   A red run means a test failed on Windows or macOS; read its log before going on.
3. Read **Check on a Mac** in `CLAUDE.md`. If an unchecked line covers a change going into this
   release, tell the owner; they decide whether it waits.
4. Draft the notes from `git log <last tag>..HEAD --format=%s` in plain words for sellers. Add:
   - if `chrome_extension/manifest.json`'s version changed: "open chrome://extensions in Chrome and
     press the reload arrow on Depop Seller";
   - if `project.dependencies` in `pyproject.toml` changed: installed Windows copies will be sent to
     the new installer instead of updating in place. Raise this with the owner before going on.
   Show the notes to the owner.

## Publish

5. `python -m depop_seller release X.Y.Z --notes "<notes>" --dry-run`, then fix every `!` line it
   reports. It builds both zips and the installer but publishes nothing.
6. With the owner's yes: the same command without `--dry-run`. It commits `Release X.Y.Z` (versions,
   README buttons, `CHANGELOG.md`), tags, pushes `main` and the tag, and uploads the three files.
   Every step can be re-run after a failure.

## After

7. Check `gh release view vX.Y.Z --repo doyoungp-dev/depop-seller`: `DepopSellerSetup.exe`,
   `DepopSeller.zip` and `DepopSeller-Mac.zip` must all be there, or a download button breaks.
8. Check that the README's two buttons show the new version, `CHANGELOG.md` has the new section, and
   CI is green on the `Release X.Y.Z` commit.

Never publish a release missing one of its files, never replace a published file without the
owner's yes, and never force push.
