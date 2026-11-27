# 4. White Background is switched off

**Status:** accepted, 2026-10-31. **Area:** `whitebg.py`, `static/review.html`, `config.WHITE_BACKGROUND`.

## Context

White Background cut the clothes out of a photo onto plain white, locally, with the BiRefNet tiny
model (chosen after comparing three models on real photos). It shipped in 1.1.0. Used on real
listings, the cut-outs were not good enough to sell with: close-ups are ambiguous, and a strip of
floor or the photographer's feet joined to the garment stayed in the picture.

## Decision

Switch it off with one flag (`config.WHITE_BACKGROUND = False`) rather than delete it:

- The Review page hides it; the server refuses it; originals are shown, uploaded and exported again,
  and any cut-outs already made stay on disk unused.
- The code and its tests stay (the tests switch it on for themselves), so it can come back if a
  better model appears.
- `onnxruntime` stays a dependency, because removing it would change the app's dependency list and
  make every installed copy refuse the in-app update and ask for a new installer.

## Consequences

- Sellers' listings use their real photos, which is what sells.
- A dormant dependency in the bundle, which also caps setup at Python 3.14 until onnxruntime
  supports 3.15.
- Turning a feature off cleanly is treated as part of building it
  (`test_switched_off_the_app_hides_it_refuses_it_and_shows_originals`).
