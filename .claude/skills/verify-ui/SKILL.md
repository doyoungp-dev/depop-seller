---
name: verify-ui
description: Check a change to a page, a route or anything a seller sees in the real running Depop Seller app, on a throwaway demo data folder, before calling it done. Use after editing depop_seller/static/*, web.py, review.py, session.py or a feature's server code.
---

# Check a change in the real app, on demo data

Tests prove the code; this proves what a seller sees. Never use the seller's own data folder
(`~/DepopSeller`): the app writes to whatever data folder it runs on.

1. **Make a demo data folder** in the session's scratchpad, not in the repo:
   - a small Python script that sets `DEPOP_SELLER_DATA` to that folder *before* importing
     `depop_seller`, and asserts `config.DATA_DIR` is it;
   - a batch with a few generated JPEGs (Pillow shapes, with an EXIF `DateTime` so they sort), then
     `cli.main(["sort", "<batch>", "--engine", "local"])` - offline grouping, no API, no cost.
2. **Start the app on a spare port** (8768), never 8765, which is the seller's own app: a wrapper
   script that sets `DEPOP_SELLER_DATA` and runs `depop_seller hub --no-browser --port 8768`, added
   to the local `.claude/launch.json` and started with the preview tools (not with a shell command).
3. **Use it:** open each tab the change touches, do the action (save, tick, refresh), then read the
   browser console errors and the server log. A page stuck at "checking..." usually means its script
   did not load.
4. **System windows** (the folder chooser, the Recycle Bin, Finder) can exist without being visible:
   capture the real screen to check them, never window flags.
5. **Clean up:** stop the server and remove the launch entry. The app also closes itself about 10
   seconds after its last window goes.

What this cannot reach: the Chrome helper on a real Depop page. Say so, and ask the owner to try it
in their own Chrome.
