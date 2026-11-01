// Opens the background Depop tab a Shop refresh runs in, tells that tab it is the one, and
// closes it when it is done. Only this extension's own scripts can send these messages.
const SHOP_URL = 'https://www.depop.com/sellinghub/selling/active/';

// Only ever the app on this computer: every address that comes in a message is checked against this.
const APP = /^http:\/\/(127\.0\.0\.1|localhost):8765$/;

function toBase64(buffer) {                      // runtime messages carry text, not binary
  const bytes = new Uint8Array(buffer);
  let text = '';
  for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(text);
}

// The Depop button: fetch the item's photos and description from the app for the Depop tab.
// The tab itself does not ask the app - Chrome is closing that road for websites (Local Network
// Access), while this script may reach the app because the helper has permission for it.
async function sellPhotos(msg) {
  const query = `batch=${encodeURIComponent(msg.batch)}&item=${encodeURIComponent(msg.item)}`;
  const res = await fetch(`${msg.server}/sell/photos?${query}`);
  if (!res.ok) throw new Error(`Depop Seller answered ${res.status} - is it still open?`);
  const { photos, description } = await res.json();
  const out = [];
  for (const p of photos || []) {
    if (!String(p.url || '').startsWith(msg.server + '/')) throw new Error('a photo address that is not the app');
    const img = await fetch(p.url);
    if (!img.ok) throw new Error(`photo ${p.name} could not be loaded (${img.status})`);
    out.push({ name: p.name, data: toBase64(await img.arrayBuffer()) });
  }
  return { ok: true, photos: out, description: description || '' };
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (!msg) return false;
  if (msg.type === 'sell-photos' || msg.type === 'sell-opened') {
    if (!APP.test(String(msg.server || ''))) { reply({ ok: false, error: 'not the Depop Seller app address' }); return false; }
    if (msg.type === 'sell-photos') {
      sellPhotos(msg).then(reply).catch((e) => reply({ ok: false, error: e.message || String(e) }));
      return true;                                // answers once the photos are in
    }
    fetch(`${msg.server}/sell/item?batch=${encodeURIComponent(msg.batch)}&item=${encodeURIComponent(msg.item)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'opened' }),
    }).catch(() => {});
    return false;
  }
  if (msg.type === 'open-shop-tab') {
    chrome.tabs.create({ url: SHOP_URL, active: false }, (tab) => chrome.storage.local.set({ shopTabId: tab.id }));
    return false;
  }
  if (msg.type === 'is-shop-tab') {
    chrome.storage.local.get('shopTabId', ({ shopTabId }) => reply(!!sender.tab && sender.tab.id === shopTabId));
    return true;                                  // answers after the storage read
  }
  if (msg.type === 'shop-import') {
    // The Depop tab cannot reach this computer (Chrome blocks websites from the local network, and
    // Depop's consent script blocks unknown hosts); this script may, for the app's own address only.
    if (!APP.test(String(msg.server || ''))) {
      reply({ ok: false, text: 'not the Depop Seller app address' });
      return false;
    }
    fetch(msg.server + '/shop/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(msg.report) })
      .then(async (res) => reply({ ok: res.ok, text: await res.text() }))
      .catch((e) => reply({ ok: false, text: 'the app is not open (' + e.message + ')' }));
    return true;                                  // answers after the request
  }
  if (msg.type === 'close-shop-tab' && sender.tab) {
    chrome.storage.local.get('shopTabId', ({ shopTabId }) => {
      if (sender.tab.id === shopTabId) {          // only ever the tab it opened itself
        chrome.storage.local.remove('shopTabId');
        chrome.tabs.remove(sender.tab.id);
      }
    });
  }
  return false;
});
