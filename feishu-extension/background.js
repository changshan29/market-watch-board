// background.js — service worker，负责实际发送 HTTP 请求（绕过混合内容限制）

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

  return true; // 保持 sendResponse 有效
});
