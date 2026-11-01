// Opens the background Depop tab a Shop refresh runs in, tells that tab it is the one, and
// closes it when it is done. Only this extension's own scripts can send these messages.
const SHOP_URL = 'https://www.depop.com/sellinghub/selling/active/';

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (!msg) return false;
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
    if (!/^http:\/\/(127\.0\.0\.1|localhost):8765$/.test(String(msg.server || ''))) {
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
