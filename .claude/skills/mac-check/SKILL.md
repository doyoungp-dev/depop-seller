---
name: mac-check
description: On the MacBook, work through CLAUDE.md's "Check on a Mac" list with the owner - the things CI cannot see (system dialogs, Finder and the Trash, the app icon, setup, Gatekeeper, downloads). Use when the owner starts a session on the Mac or asks what still needs checking there.
---

# Check on a Mac

CI runs every test on a real Mac but cannot see the screen. This is the hand-over from the Windows
machine; the owner does the clicking and Claude Code checks what it can.

1. `git pull`, then make sure `.venv` exists and `pytest -q` passes here.
2. Read **Check on a Mac** in `CLAUDE.md`. If it says nothing is waiting, say so and stop.
3. For each line, one at a time:
   - tell the owner exactly what to click and what should happen;
   - check what you can yourself: `~/Library/Logs/Depop Seller.log`, the Trash (`ls ~/.Trash`), the
     data folder, the app's answers on `http://127.0.0.1:8765/version`;
   - if it does not work, find the cause, fix it, test it, and have the owner try again.
4. Delete each line once it works. When the list is empty, write "(Nothing waiting.)" with a note of
   what was checked and for which version.
5. Commit with a short note of what passed (or what was fixed) and push, following "How changes are
   made" in `CLAUDE.md`.

Never use the owner's real batches for a destructive check such as Delete batch or Delete Depop
Seller; make a throwaway batch or a copy of the app first.
