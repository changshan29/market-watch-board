// 飞书消息采集 content_script.js
// 每60秒扫描飞书群聊 DOM，将新消息推送到服务器
// 含自动重连机制：runtime 断连后自动恢复

const INTERVAL_MS = 60 * 1000;
const RECONNECT_MS = 5 * 1000; // 断连后每5秒尝试重连

function getConfig() {
  return new Promise(resolve => {
    try {
      chrome.storage.local.get(['serverUrl', 'groupName', 'pluginInterval'], items => {
        resolve({
          serverUrl: items.serverUrl || 'https://web-production-af97c.up.railway.app',
          groupName: items.groupName || '飞书群',
          interval: (items.pluginInterval || 60) * 1000,
        });
      });
    } catch { resolve({ serverUrl: 'https://web-production-af97c.up.railway.app', groupName: '飞书群', interval: INTERVAL_MS }); }
  });
}

function getSentIds() {
  try { return new Set(JSON.parse(sessionStorage.getItem('_feishu_sent') || '[]')); }
  catch { return new Set(); }
}

function saveSentIds(set) {
  sessionStorage.setItem('_feishu_sent', JSON.stringify([...set].slice(-2000)));
}

// 检查 runtime 是否可用
function isRuntimeAlive() {
  try { return !!(chrome.runtime && chrome.runtime.id); }
  catch { return false; }
}

// 把 img 元素（含 blob URL）转成压缩后的 base64
function imgToBase64(imgEl) {
  return new Promise(resolve => {
    try {
      const MAX = 800;
      let w = imgEl.naturalWidth || imgEl.width || 200;
      let h = imgEl.naturalHeight || imgEl.height || 200;
      if (w > MAX) { h = Math.round(h * MAX / w); w = MAX; }
      if (h > MAX) { w = Math.round(w * MAX / h); h = MAX; }
      const canvas = document.createElement('canvas');
      canvas.width = w; canvas.height = h;
      canvas.getContext('2d').drawImage(imgEl, 0, 0, w, h);
      resolve(canvas.toDataURL('image/jpeg', 0.7));
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

    const richEl = item.querySelector('.richTextContainer');
    if (richEl?.innerText.trim()) {
      msgs.push({ msgId, sender: lastSender, text: richEl.innerText.trim(), timestamp, images: [] });
      continue;
    }

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

// 直接用 fetch 推送（不依赖 background，避免 runtime 断连问题）
async function pushMessages(serverUrl, messages) {
  try {
    const resp = await fetch(serverUrl + '/api/feishu-msg', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages }),
    });
    const data = await resp.json();
    return data;
  } catch (e) {
    console.error('[飞书采集] 推送失败:', e.message);
    return null;
  }
}

async function collectAndSend() {
  const { serverUrl, groupName } = await getConfig();
  const msgs = await extractMessages();

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

  // 图片单条推，文字批量推
  const textMsgs = newMsgs.filter(m => m.images.length === 0);
  const imgMsgs  = newMsgs.filter(m => m.images.length > 0);

  if (textMsgs.length > 0) {
    const r = await pushMessages(serverUrl, textMsgs);
    console.log('[飞书采集] 文字推送:', r);
  }
  for (const imgMsg of imgMsgs) {
    const r = await pushMessages(serverUrl, [imgMsg]);
    console.log('[飞书采集] 图片推送:', r);
  }
}

// ── 主循环：带自动重连 ───────────────────────────────────────────────────────
let _collectTimer = null;
let _reconnectTimer = null;
let _interval = INTERVAL_MS;

function startCollecting() {
  if (_collectTimer) return; // 已在运行
  console.log('[飞书采集] 启动采集循环，间隔', _interval / 1000, '秒');
  collectAndSend(); // 立即采集一次
  _collectTimer = setInterval(collectAndSend, _interval);
}

function stopCollecting() {
  if (_collectTimer) { clearInterval(_collectTimer); _collectTimer = null; }
}

// 心跳：每5秒检查 runtime 是否还活着
function startHeartbeat() {
  setInterval(() => {
    if (!isRuntimeAlive()) {
      // runtime 断了，停止采集，等待重连
      if (_collectTimer) {
        console.warn('[飞书采集] Runtime 断连，暂停采集，等待重连...');
        stopCollecting();
      }
    } else {
      // runtime 正常，确保采集在跑
      if (!_collectTimer) {
        console.log('[飞书采集] Runtime 恢复，重启采集');
        startCollecting();
      }
    }
  }, RECONNECT_MS);
}

// 初始化
setTimeout(async () => {
  const config = await getConfig();
  _interval = config.interval || INTERVAL_MS;
  startCollecting();
  startHeartbeat();
}, 5000);
