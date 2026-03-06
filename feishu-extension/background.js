// background.js — service worker，负责实际发送 HTTP 请求（绕过混合内容限制）

// 启动时从服务器同步插件采集间隔
chrome.runtime.onInstalled.addListener(syncInterval);
chrome.runtime.onStartup.addListener(syncInterval);

async function syncInterval() {
  const items = await chrome.storage.local.get(['serverUrl']);
  const serverUrl = items.serverUrl || 'http://localhost:3220';
  try {
    const resp = await fetch(serverUrl + '/api/plugin-config');
    const data = await resp.json();
    await chrome.storage.local.set({ pluginInterval: data.plugin_interval || 60 });
    console.log('[插件] 采集间隔已同步:', data.plugin_interval, '秒');
  } catch (e) {
    console.log('[插件] 同步间隔失败，使用默认60秒');
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type !== 'PUSH_MESSAGES') return;

  fetch(msg.serverUrl + '/api/feishu-msg', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(msg.messages),
  })
    .then(r => r.json())
    .then(data => sendResponse({ ok: true, data }))
    .catch(e => sendResponse({ ok: false, error: e.message }));

  return true;
});
