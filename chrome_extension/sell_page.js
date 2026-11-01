// Runs on the local app's pages. Tells the page the helper is installed, remembers which item
// to add when the Sell page asks (the Depop tab picks it up after it opens), and starts a Shop
// refresh when the Shop page asks: the job waits in storage while the background script opens
// a Depop tab in the background, and that tab does the reading (depop.js).
document.documentElement.dataset.depopSellerExt = chrome.runtime.getManifest().version;

window.addEventListener('message', (event) => {
  if (event.source !== window || !event.data) return;
  if (event.data.type === 'depop-seller:open') {
    const { batch, item, server } = event.data;
    chrome.storage.local.set({ pending: { batch, item, server, at: Date.now() } }, () => {
      window.postMessage({ type: 'depop-seller:stored', batch, item }, '*');
    });
  }
  if (event.data.type === 'depop-seller:shop-sync') {
    const { token, what, server } = event.data;
    chrome.storage.local.set({ shopJob: { token, what, server, at: Date.now() } }, () => {
      chrome.runtime.sendMessage({ type: 'open-shop-tab' });
      window.postMessage({ type: 'depop-seller:shop-started', what }, '*');
    });
  }
});
