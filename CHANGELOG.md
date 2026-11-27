# Changelog

What changed in each release of Depop Seller, newest first. The same notes appear on the
[releases page](https://github.com/doyoungp-dev/depop-seller/releases) and in the app under
**Settings → Updates**. `python -m depop_seller release` adds each new release here.

## 1.1.6 - 2026-11-01

- New **Shop** tab: what you are selling and what you have sold on Depop, with totals (asking value, what you received, this month, sales to ship), search, and a Refresh for each list. Each list folds away with the arrow by its title.
- **Export CSV** on each Shop list saves it as a spreadsheet in your Downloads folder.
- Shop's **Refresh** stays quick for big shops: it reads your recent sales again and keeps the older ones (every sale is read again once a month).
- **Settings → Delete Depop Seller** removes the app cleanly on Windows and Mac. Your photos and data stay unless you choose otherwise.
- Settings lists where each of your batches is kept.
- **Generate Description** finds Claude again after a Claude app update moved it.
- The **Depop** button now gets its photos through the Chrome helper, so a future Chrome update cannot block it.
- The Chrome helper is now called **Depop Seller** and carries the app's logo. After updating, open chrome://extensions in Chrome and press the reload arrow on it.
- A freshly started app no longer looks busy for two minutes after the computer starts.
- The project's page moved to github.com/doyoungp-dev/depop-seller. If you have version 1.1.5 or older, download this version once from that page; Check for updates works again from here on.

## 1.1.5 - 2026-11-01

- Delete batch: asks first, then moves the batch's folder to the Recycle Bin or Trash
- Choose folder opens Explorer's Select Folder window in front, instead of one that never appeared
- The New batch panel says where a batch is saved, with a clear Choose folder button
- Keep each batch wherever you like - the Desktop, Downloads, any folder

## 1.1.4 - 2026-11-01

- Check for updates works on a Mac

## 1.1.3 - 2026-11-01

- The Mac download unzips into a folder called Depop Seller
- On a Mac, Depop Seller opens without asking to install Rosetta
- Download buttons on the project page show the version of each new release straight away

## 1.1.2 - 2026-11-01

- Setup on Windows also finds Python 3.13 or 3.12 when 3.14 is not installed
- Setup asks for Python 3.14: Python 3.15 does not work with Depop Seller yet

## 1.1.1 - 2026-10-31

- White Background is switched off for now: photos are shown, uploaded and exported as you took them
- Download buttons show the newest version

## 1.1.0 - 2026-10-31

- White Background: tick photos on the Review page to put the clothes on plain white; Restore original undoes it (on a Mac it needs Apple silicon and macOS 14 or later)
- Depop Seller now runs on a Mac, with a Download for Mac button and step-by-step install
- Windows and Mac get the same features and the same newest version
- On Windows this version adds a library, so Update points you to the new DepopSellerSetup.exe, which upgrades your copy in place

## 1.0.0 - 2026-09-29

The first public version of Depop Seller.

- Drop in a shoot's photos and let Claude sort them into items; fix anything by drag and drop
- Write descriptions in your own style - for one item, or for every item you tick
- The Depop button opens Depop's listing form with the photos and the description already in it
- Change how descriptions are written by just saying so, on the Style tab
- Settings walks you through the API key, signing in to Claude (in your browser) and the Chrome helper
- Check for updates from Settings; your photos and listings are never touched by an update
