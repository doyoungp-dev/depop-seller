// Runs on depop.com. When the local Sell page has queued an item and this tab is on
// "List an item", get the item's photos from the local app (through the helper's background
// script - this tab may not reach the app itself) and put them into Depop's photo input exactly
// as a drag-and-drop from Explorer would. Never touches the Post button.

const FILE_INPUT = 'input[type=file]';
let busy = false;

function banner(text, isError) {
  let b = document.getElementById('depop-seller-banner');
  if (!b) {
    b = document.createElement('div');
    b.id = 'depop-seller-banner';
    b.style.cssText = 'position:fixed;top:12px;right:12px;z-index:2147483647;background:#111;color:#fff;font:14px system-ui;padding:10px 14px;border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.3);max-width:360px';
    document.body.appendChild(b);
  }
  b.style.background = isError ? '#b91c1c' : '#111';
  b.textContent = 'Depop Seller: ' + text;
  if (!isError) clearTimeout(b._t), b._t = setTimeout(() => b.remove(), 8000);
}

// React ignores a plain `el.value = x`; go through the native setter and fire an input event.
function setReactValue(el, value) {
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

const DESCRIPTION_SELECTORS = [
  'textarea[name*="description" i]', 'textarea[id*="description" i]', 'textarea[placeholder*="worn" i]',
  'textarea', '[contenteditable="true"][aria-label*="description" i]', '[contenteditable="true"]',
  'input[name*="description" i]',
];

// Depop's description box may be a plain textarea (React) or an editable div (Slate/Lexical style):
// try each in turn, using the mechanism that box type actually listens to.
async function fillDescription(text) {
  for (const sel of DESCRIPTION_SELECTORS) {
    const el = await waitFor(sel, sel === 'textarea' ? 6000 : 800);
    if (!el || !isVisible(el)) continue;
    el.focus();
    if (el.isContentEditable) {
      document.execCommand('selectAll', false, null);
      let ok = false;
      try { ok = document.execCommand('insertText', false, text); } catch (e) { ok = false; }
      if (!ok) {
        el.textContent = text;
        el.dispatchEvent(new InputEvent('input', { bubbles: true, data: text, inputType: 'insertText' }));
      }
    } else {
      setReactValue(el, text);
    }
    await new Promise(r => setTimeout(r, 300));
    const now = el.isContentEditable ? el.textContent : el.value;
    if (now && now.trim().startsWith(text.trim().slice(0, 20))) return true;
  }
  return false;
}

function isVisible(el) { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }

function waitFor(selector, ms) {
  return new Promise(resolve => {
    const t0 = Date.now();
    (function look() {
      const el = document.querySelector(selector);
      if (el) return resolve(el);
      if (Date.now() - t0 > ms) return resolve(null);
      setTimeout(look, 300);
    })();
  });
}

async function pendingJob() {
  const { pending } = await chrome.storage.local.get('pending');
  if (!pending) return null;
  if (Date.now() - pending.at > 30 * 60 * 1000) { await chrome.storage.local.remove('pending'); return null; }
  return pending;
}

async function addPhotos(job) {
  const input = document.querySelector(FILE_INPUT);
  if (!input) return false;
  busy = true;
  try {
    banner(`fetching photos for item ${job.item}…`);
    const server = job.server || 'http://127.0.0.1:8765';
    // through the helper's background script: this tab may not reach the app itself
    const got = await chrome.runtime.sendMessage({ type: 'sell-photos', server, batch: job.batch, item: job.item });
    if (!got || !got.ok) throw new Error((got && got.error) || 'the helper could not get the photos from Depop Seller');
    const { photos, description } = got;
    const dt = new DataTransfer();
    for (let i = 0; i < photos.length; i++) {
      const raw = atob(photos[i].data);
      const bytes = new Uint8Array(raw.length);
      for (let j = 0; j < raw.length; j++) bytes[j] = raw.charCodeAt(j);
      dt.items.add(new File([bytes], photos[i].name, { type: 'image/jpeg', lastModified: Date.now() }));
    }
    banner(`adding ${photos.length} photos to the form…`);
    if (input.multiple) {
      input.files = dt.files;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    } else {
      // one photo per slot: the form re-renders after each upload, so re-query every time
      for (let i = 0; i < dt.files.length; i++) {
        const inputs = document.querySelectorAll(FILE_INPUT);
        const target = inputs[Math.min(i, inputs.length - 1)];
        const one = new DataTransfer();
        one.items.add(dt.files[i]);
        target.files = one.files;
        target.dispatchEvent(new Event('input', { bubbles: true }));
        target.dispatchEvent(new Event('change', { bubbles: true }));
        await new Promise(r => setTimeout(r, 1500));
      }
    }
    let pasted = false;
    if (description && description.trim()) {
      banner('pasting the description…');
      pasted = await fillDescription(description);
    }
    await chrome.storage.local.remove('pending');
    if (description && !pasted) {
      banner(`${photos.length} photos added, but no description box was found on this page (tried: textarea, editable box, input). Paste it by hand from the Sell page.`, true);
    } else {
      banner(`${photos.length} photos${pasted ? ' and the description' : ''} added for item ${job.item}. Check everything, fill in the rest, and post when you're ready.`);
    }
    chrome.runtime.sendMessage({ type: 'sell-opened', server, batch: job.batch, item: job.item });
    return true;
  } catch (e) {
    banner('failed: ' + e.message, true);
    await chrome.storage.local.remove('pending');
    return true;
  } finally {
    busy = false;
  }
}

async function tick() {
  if (busy) return;
  if (!location.pathname.startsWith('/products/create')) return;
  const job = await pendingJob();
  if (!job) return;
  if (!document.querySelector(FILE_INPUT)) { banner(`item ${job.item} queued - waiting for the photo form (log in if Depop asks)`); return; }
  await addPhotos(job);
}

setInterval(tick, 1500);
tick();

// ---- Shop tab: what is selling and what has sold ---------------------------------------
// The app's Shop page asks for a refresh; the background script opens a Depop tab in the
// background and only that tab (it asks the background script) reads the lists - from Depop's
// own web API, a page at a time, exactly the requests the selling hub page makes when you
// scroll, with this browser's sign-in, which never leaves it. Buyer names and addresses are
// left behind; only the fields the Shop tab shows go to the app. Then the tab closes itself.
const DEPOP_API = 'https://webapi.depop.com';
let shopBusy = false;

function depopToken() {
  const m = document.cookie.match(/(?:^|; )access_token=([^;]*)/);
  return m ? decodeURIComponent(m[1]) : '';
}

async function depopGet(path) {
  const res = await fetch(DEPOP_API + path, { headers: { Authorization: 'Bearer ' + depopToken() } });
  if (res.status === 401 || res.status === 403) throw new Error('Depop says you are not signed in - sign in to Depop in Chrome, then press Refresh again');
  if (!res.ok) throw new Error(`Depop answered ${res.status} - try Refresh again in a minute`);
  return res.json();
}

const pause = (ms) => new Promise((r) => setTimeout(r, ms));

function pickSelling(p) {
  return { id: p.id, slug: p.slug, description: p.description, status: p.status, likeCount: p.likeCount,
           price: p.price, sizes: p.sizes, pictures: (p.pictures || []).slice(0, 1),
           dateCreated: p.dateCreated, dateUpdated: p.dateUpdated };
}

function pickSold(r) {                            // no buyer, no address, no tracking
  return { purchase_id: r.purchase_id, status: r.status, sold_timestamp: r.sold_timestamp, is_bundle: r.is_bundle,
           currency: r.currency, items_amount: r.items_amount, seller_amount: r.seller_amount,
           line_items: (r.line_items || []).map((li) => ({ product_id: li.product_id, description: li.description, picture_url: li.picture_url })) };
}

async function readSelling(progress) {
  const out = [];
  let cursor = '';
  for (let page = 0; page < 500; page++) {
    const body = await depopGet('/api/v1/shop/products/?lang=en&limit=24&statusFilter=selling' + (cursor ? '&cursor=' + encodeURIComponent(cursor) : ''));
    const products = body.products || [];
    products.forEach((p) => out.push(pickSelling(p)));
    progress(out.length);
    if (!products.length || !body.meta || body.meta.end || !body.meta.cursor) break;
    cursor = body.meta.cursor;
    await pause(250);                             // gentle: about the pace of someone scrolling
  }
  return out;
}

// Newest sales come first. With `since` (from the app: it already holds the older sales, and
// their state no longer moves) reading stops once a page reaches back past it.
async function readSold(progress, since) {
  const out = [];
  const stop = since ? new Date(since).getTime() : NaN;
  let after = '';
  for (let page = 0; page < 2000; page++) {
    const body = await depopGet('/presentation/api/v1/receipts/?role=seller&limit=12' + (after ? '&after=' + encodeURIComponent(after) : ''));
    const receipts = body.objects || [];
    receipts.forEach((r) => out.push(pickSold(r)));
    progress(out.length);
    const info = body.page_info || {};
    if (!receipts.length || !info.has_more || !info.last) break;
    const oldest = new Date(receipts[receipts.length - 1].sold_timestamp).getTime();
    if (!isNaN(stop) && oldest < stop) break;
    after = info.last;
    await pause(250);
  }
  return out;
}

async function shopSync(job) {
  const report = { token: job.token };
  try {
    if (!depopToken()) throw new Error('you are not signed in to Depop in this Chrome - sign in, then press Refresh again');
    if (job.what !== 'sold') {
      report.selling = await readSelling((n) => banner(`reading what you are selling… ${n}`));
      try { report.counts = await depopGet('/presentation/api/v1/users/me/product-counts/'); } catch (e) { /* only a cross-check */ }
    }
    if (job.what !== 'selling') {
      report.sold = await readSold((n) => banner(`reading what you have sold… ${n}`), job.since);
      if (job.since) report.sold_since = job.since;   // tells the app to keep the older sales it has
    }
  } catch (e) {
    report.error = String((e && e.message) || e);
  }
  await chrome.storage.local.remove('shopJob');
  try {
    // handed over through the background script: this tab itself may not reach the app
    const res = await chrome.runtime.sendMessage({ type: 'shop-import', server: job.server, report });
    if (!res || !res.ok) throw new Error((res && res.text) || 'no answer from the helper');
    banner(report.error ? 'could not read your shop: ' + report.error : 'done - your shop is in the app. This tab closes now.', !!report.error);
  } catch (e) {
    banner('the app did not take the lists: ' + e.message, true);
    return;                                       // leave the tab open so the message can be read
  }
  setTimeout(() => chrome.runtime.sendMessage({ type: 'close-shop-tab' }), report.error ? 8000 : 1500);
}

async function shopTick() {
  if (shopBusy) return;
  shopBusy = true;                                // before the first await, so two ticks cannot both start
  try {
    const { shopJob } = await chrome.storage.local.get('shopJob');
    if (!shopJob) { shopBusy = false; return; }
    if (Date.now() - shopJob.at > 10 * 60 * 1000) { await chrome.storage.local.remove('shopJob'); shopBusy = false; return; }
    const mine = await chrome.runtime.sendMessage({ type: 'is-shop-tab' });
    if (!mine) { shopBusy = false; return; }      // another Depop tab the seller has open: not this one
    await shopSync(shopJob);                      // the shop tab closes afterwards, so it stays busy
  } catch (e) {
    shopBusy = false;
  }
}

setInterval(shopTick, 1500);
shopTick();
