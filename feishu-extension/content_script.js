// 飞书消息采集 content_script.js
// 每60秒扫描飞书群聊 DOM，将新消息推送到服务器

const INTERVAL_MS = 60 * 1000;

function getConfig() {
  return new Promise(resolve => {
    chrome.storage.local.get(['serverUrl', 'groupName', 'pluginInterval'], items => {
      resolve({
        serverUrl: items.serverUrl || 'https://market-watch-board-production.up.railway.app',
        groupName: items.groupName || '飞书群',
        interval: (items.pluginInterval || 60) * 1000,
      });
    });
  });
}

function getSentIds() {
  try { return new Set(JSON.parse(sessionStorage.getItem('_feishu_sent') || '[]')); }
  catch { return new Set(); }
}

function saveSentIds(set) {
  sessionStorage.setItem('_feishu_sent', JSON.stringify([...set].slice(-2000)));
}

// 把 img 元素（含 blob URL）转成压缩后的 base64
function imgToBase64(imgEl) {
  return new Promise(resolve => {
    try {
      const MAX = 800; // 限制尺寸，控制 base64 大小
      let w = imgEl.naturalWidth || imgEl.width || 200;
      let h = imgEl.naturalHeight || imgEl.height || 200;
      if (w > MAX) { h = Math.round(h * MAX / w); w = MAX; }
      if (h > MAX) { w = Math.round(w * MAX / h); h = MAX; }
      const canvas = document.createElement('canvas');
      canvas.width = w; canvas.height = h;
      canvas.getContext('2d').drawImage(imgEl, 0, 0, w, h);
      resolve(canvas.toDataURL('image/jpeg', 0.7)); // 0.7 质量，更小
    } catch { resolve(null); }
  });
}

async function extractMessages() {
  const items = document.querySelectorAll('[data-id].messageItem-wrapper');
  if (items.length === 0) return [];

  const msgs = [];
  let lastSender = '';
  let lastTime = '';

  for (const item of items) {
    const msgId = item.getAttribute('data-id');
    if (!msgId) continue;

    const senderEl = item.querySelector('.message-info-name');
    if (senderEl?.innerText.trim()) lastSender = senderEl.innerText.trim();

    const timeEl = item.querySelector('.message-timestamp');
    if (timeEl?.innerText.trim()) lastTime = timeEl.innerText.trim();

    let timestamp = new Date().toISOString();
    if (lastTime) {
      const m = lastTime.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?/);
      if (m) {
        const d = new Date();
        d.setHours(+m[1], +m[2], +(m[3] || 0), 0);
        timestamp = d.toISOString();
      }
    }

    // 文字消息
    const richEl = item.querySelector('.richTextContainer');
    if (richEl?.innerText.trim()) {
      msgs.push({ msgId, sender: lastSender, text: richEl.innerText.trim(), timestamp, images: [] });
      continue;
    }

    // 图片消息（最多3张，避免 payload 过大）
    const imgEls = item.querySelectorAll(
      '.im-image-message img, .message-content img, [class*="image-message"] img, .messenger-image__img'
    );
    if (imgEls.length > 0) {
      const imageBase64s = [];
      for (const imgEl of [...imgEls].slice(0, 3)) {
        if (!imgEl.complete || imgEl.naturalWidth === 0) continue;
        const b64 = await imgToBase64(imgEl);
        if (b64) imageBase64s.push(b64);
      }
      if (imageBase64s.length > 0) {
        msgs.push({ msgId, sender: lastSender, text: '[图片]', timestamp, images: imageBase64s });
      }
    }
  }
  return msgs;
}

async function collectAndSend() {
  const { serverUrl, groupName } = await getConfig();
  const msgs = await extractMessages(); // ← 必须 await！

  const sentIds = getSentIds();
  const newMsgs = [];

  for (const msg of msgs) {
    if (sentIds.has(msg.msgId)) continue;
    sentIds.add(msg.msgId);
    newMsgs.push({
      id: msg.msgId,
      text: msg.text,
      images: msg.images || [],
      sender: msg.sender,
      group_name: groupName,
      timestamp: msg.timestamp,
    });
  }

  saveSentIds(sentIds);

  if (newMsgs.length === 0) { console.log('[飞书采集] 无新消息'); return; }

  console.log(`[飞书采集] ${newMsgs.length} 条新消息，推送中...`);

  // 图片消息单独推，文字批量推，避免 payload 过大
  const textMsgs = newMsgs.filter(m => m.images.length === 0);
  const imgMsgs = newMsgs.filter(m => m.images.length > 0);

  if (textMsgs.length > 0) {
    chrome.runtime.sendMessage({ type: 'PUSH_MESSAGES', serverUrl, messages: textMsgs }, resp => {
      if (chrome.runtime.lastError) { console.error('[飞书采集]', chrome.runtime.lastError.message); return; }
      console.log('[飞书采集] 文字推送:', resp?.data);
    });
  }

  for (const imgMsg of imgMsgs) {
    chrome.runtime.sendMessage({ type: 'PUSH_MESSAGES', serverUrl, messages: [imgMsg] }, resp => {
      if (chrome.runtime.lastError) { console.error('[飞书采集]', chrome.runtime.lastError.message); return; }
      console.log('[飞书采集] 图片推送:', resp?.data);
    });
  }
}

let _timer = null;
setTimeout(async () => {
  if (!chrome.runtime?.id) return;
  const { interval } = await getConfig();
  collectAndSend();
  _timer = setInterval(() => {
    if (!chrome.runtime?.id) { clearInterval(_timer); return; }
    collectAndSend();
  }, interval || INTERVAL_MS);
}, 5000);
