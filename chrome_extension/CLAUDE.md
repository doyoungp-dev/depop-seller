# The Chrome helper (`chrome_extension/`)

A Manifest V3 extension the seller loads unpacked at chrome://extensions. In Chrome it is called
**Depop Seller**; the app's pages call it "the Chrome helper". Full detail: `docs/architecture.md`
(Selling on Depop, Shop tab) and `docs/decisions/0001-fill-depop-from-a-chrome-extension.md`.

- `sell_page.js` runs on the app's own pages (127.0.0.1:8765): it marks the page as having the
  helper (`documentElement.dataset.depopSellerExt`) and passes jobs to the background worker.
- `background.js` is the only part that talks to the app. It fetches `/sell/photos` and each photo
  (only URLs under the app's own address), hands them to the Depop tab as base64 (runtime messages
  carry no binary), posts "opened" to `/sell/item`, and posts the Shop lists to `/shop/import`.
- `depop.js` runs on depop.com: it fills the listing form (photos in the seller's order, then the
  description), and in the Shop's background tab reads Depop's own lists.

Rules:

- **The Depop tab never calls the app.** Chrome's Local Network Access blocks websites from reaching
  127.0.0.1, and a consent script on Depop's page blocks unknown hosts. Anything the tab needs comes
  through `background.js`.
- **Never press Post** or submit anything on Depop. The seller posts.
- **Never keep a buyer's name or address.** The Shop reader keeps only what the seller's own list
  shows (`pickSold`); Depop's sign-in token never leaves Chrome.
- **Bump the version in three places together:** `manifest.json`, and `HELPER_VERSION` in
  `depop_seller/static/sell.html` and `shop.html`. The pages warn when Chrome still runs an older
  copy, because unpacked extensions do not update themselves: release notes must tell sellers to
  press the reload arrow on Depop Seller at chrome://extensions.
- The icons in `icons/` are resized from `depop_seller/static/icon.png`; remake them if it changes.
- This folder ships to sellers as it is. Keep it free of anything they should not load.
- Test a content script with the harness pattern in git history: inject it into the app's
  `/sell/testform` page with a `chrome.storage` shim. Never test against a real Depop account
  without the owner.
