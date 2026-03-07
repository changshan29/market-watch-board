// background.js — service worker，负责实际发送 HTTP 请求（绕过 CORS 限制）

// 启动时从服务器同步插件采集间隔
chrome.runtime.onInstalled.addListener(syncInterval);
chrome.runtime.onStartup.addListener(syncInterval);

async function syncInterval() {
  const items = await chrome.storage.local.get(['serverUrl']);
  const serverUrl = items.serverUrl || 'https://web-production-af97c.up.railway.app';
  try {
    const resp = await fetch(serverUrl + '/api/plugin-config');
    const data = await resp.json();
    await chrome.storage.local.set({ pluginInterval: data.plugin_interval || 60 });
    console.log('[插件] 采集间隔已同步:', data.plugin_interval, '秒');
  } catch (e) {
    console.log('[插件] 同步间隔失败，使用默认60秒');
  }
}

// 把图片 URL 下载转成 base64（Service Worker 无 CORS 限制）
async function urlToBase64(imgUrl) {
  try {
    // 尝试带 Referer 请求（聚量图片防盗链需要）
    const referer = new URL(imgUrl).origin;
    const r = await fetch(imgUrl, {
      headers: { 'Referer': referer }
    });
    if (!r.ok) return null;
    const blob = await r.blob();
    const buf = await blob.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let binary = '';
    for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
    const b64 = btoa(binary);
    const mime = blob.type || 'image/jpeg';
    return `data:${mime};base64,${b64}`;
  } catch { return null; }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'PUSH_MESSAGES') {
    fetch(msg.serverUrl + '/api/feishu-msg', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: msg.messages }),
    })
      .then(r => r.json())
      .then(data => sendResponse({ ok: true, data }))
      .catch(e => sendResponse({ ok: false, error: e.message }));
    return true;
  }

  if (msg.type === 'FETCH_IMAGE_BASE64') {
    urlToBase64(msg.url)
      .then(b64 => sendResponse({ ok: !!b64, b64 }))
      .catch(() => sendResponse({ ok: false, b64: null }));
    return true;
  }
});
