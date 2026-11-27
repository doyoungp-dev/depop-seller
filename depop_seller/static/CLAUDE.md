# The pages (`depop_seller/static/`)

Vanilla HTML, CSS and JavaScript, one file per tab (`hub.html` Batches, `review.html`, `sell.html`,
`shop.html`, `style.html`, `settings.html`), served by `depop_seller/web.py`. The pages share no JS:
each carries its own copy of the small shared pieces. Full detail per tab: `docs/architecture.md`.

- **Design system:** link `/app.css` first and use its tokens (`--primary` blue for actions,
  `--depop` red for the Depop button, `--font-display` for titles). A page keeps only its own layout in
  `<style>`: never a colour value and never a `:root`. No web fonts and no `background-attachment:
  fixed`. `test_every_page_uses_the_shared_design` guards this.
- **No real newline inside a quoted JavaScript string.** It stops the whole script from loading, and
  the page then sits at "checking..." while the server answers fine
  (`test_every_page_script_has_no_string_broken_across_lines`). Build such strings with `chr(10)`
  when writing them from Python, or write the file with the Write tool.
- **Every page carries the same header:** the icon and "Depop Seller" linking to `/hub`, and the tabs
  through `syncTabs(active, batch, hasManifest)`, which carries `?batch=` across and greys out what
  does not apply yet.
- **Every page calls `checkVersion()`** and shows `#stale-banner` when the code on disk is newer than
  the running app. Word it as closing and reopening the app (desktop icon or Dock), never as closing
  a console window: there is none.
- **Every page sends `navigator.sendBeacon('/closing')` on `pagehide`**, which is how closing the window
  closes the app. Never use `visibilitychange` for this: minimising would look like closing.
- **Sell page refreshes** redraw only the cards whose `snapshot()` changed, and never a card that holds
  the focus, so a seller typing in one card does not lose it while descriptions are written.
- **`HELPER_VERSION`** in `sell.html` and `shop.html` must match `chrome_extension/manifest.json`.
- Drag and drop cannot be driven by synthetic mouse events. Test the handlers with dispatched
  `DragEvent`s, and leave real drags to a person. Check any visible change in the real app on demo
  data (the `verify-ui` skill).
