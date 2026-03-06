// 飞书消息采集 content_script.js
// 每60秒扫描飞书群聊 DOM，将新消息推送到服务器
// 选择器基于实际 DOM 分析（2026-03）：
//   消息容器：[data-id].messageItem-wrapper
//   文字消息：.richTextContainer
//   图片消息：.im-image-message 或 .message-content img
//   发送者：.message-info-name
//   时间戳：.message-timestamp

const INTERVAL_MS = 60 * 1000;

function getConfig() {
  return new Promise(resolve => {
    chrome.storage.local.get(['serverUrl', 'groupName', 'pluginInterval'], items => {
      resolve({
        serverUrl: items.serverUrl || 'http://localhost:3220',
        groupName: items.groupName || '飞书群',
        interval: (items.pluginInterval || 60) * 1000,
      });
    });
  });
}

function getSentIds() {
  try {
    return new Set(JSON.parse(sessionStorage.getItem('_feishu_sent') || '[]'));
  } catch {
    return new Set();
  }
}

function saveSentIds(set) {
  const arr = [...set].slice(-2000);
  sessionStorage.setItem('_feishu_sent', JSON.stringify(arr));
}

// 把 img 元素（含 blob: URL）转成 base64 data URL
function imgToBase64(imgEl) {
  return new Promise(resolve => {
    try {
      const canvas = document.createElement('canvas');
      // 限制最大尺寸，避免 base64 太大
      const MAX = 1200;
      let w = imgEl.naturalWidth || imgEl.width || 200;
      let h = imgEl.naturalHeight || imgEl.height || 200;
      if (w > MAX) { h = Math.round(h * MAX / w); w = MAX; }
      if (h > MAX) { w = Math.round(w * MAX / h); h = MAX; }
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(imgEl, 0, 0, w, h);
      resolve(canvas.toDataURL('image/jpeg', 0.8));
    } catch (e) {
      resolve(null);
    }
  });
}

async function extractMessages() {
  const items = document.querySelectorAll('[data-id].messageItem-wrapper');
  if (items.length === 0) {
    console.log('[飞书采集] 未找到 .messageItem-wrapper，可能不在群聊页面');
    return [];
  }

  const msgs = [];
  let lastSender = '';
  let lastTime = '';

  for (const item of items) {
    const msgId = item.getAttribute('data-id');
    if (!msgId) continue;

    // 发送者
    const senderEl = item.querySelector('.message-info-name');
    if (senderEl && senderEl.innerText.trim()) {
      lastSender = senderEl.innerText.trim();
    }

    // 时间戳
    const timeEl = item.querySelector('.message-timestamp');
    if (timeEl && timeEl.innerText.trim()) {
      lastTime = timeEl.innerText.trim();
    }

    let timestamp = new Date().toISOString();
    if (lastTime) {
      const m = lastTime.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?/);
      if (m) {
        const d = new Date();
        d.setHours(parseInt(m[1]), parseInt(m[2]), parseInt(m[3] || '0'), 0);
        timestamp = d.toISOString();
      }
    }

    // ── 文字消息 ──
    const richEl = item.querySelector('.richTextContainer');
    if (richEl) {
      const text = richEl.innerText.trim();
      if (text) {
        msgs.push({ msgId, sender: lastSender, text, timestamp, images: [] });
        continue;
      }
    }

    // ── 图片消息：转 base64 ──
    const imgEls = item.querySelectorAll(
      '.im-image-message img, .message-content img, [class*="image-message"] img, [class*="imageMessage"] img, .messenger-image__img'
    );
    if (imgEls.length > 0) {
      const imageBase64s = [];
      for (const imgEl of imgEls) {
        // 等图片加载完
        if (!imgEl.complete || imgEl.naturalWidth === 0) continue;
        const b64 = await imgToBase64(imgEl);
        if (b64) imageBase64s.push(b64);
      }
      if (imageBase64s.length > 0) {
        msgs.push({
          msgId,
          sender: lastSender,
          text: '[图片]',
          timestamp,
          images: imageBase64s,
        });
        console.log(`[飞书采集] 图片消息 ${msgId}: ${imageBase64s.length} 张已转 base64`);
      }
    }
  }

  return msgs;
}

async function collectAndSend() {
  const { serverUrl, groupName } = await getConfig();
  const msgs = extractMessages();

  if (msgs.length === 0) {
    console.log('[飞书采集] 未找到消息，跳过');
    return;
  }

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

  if (newMsgs.length === 0) {
    console.log('[飞书采集] 无新消息');
    return;
  }

  console.log(`[飞书采集] 发现 ${newMsgs.length} 条新消息（含图片），推送中...`);
  chrome.runtime.sendMessage(
    { type: 'PUSH_MESSAGES', serverUrl, messages: newMsgs },
    resp => {
      if (chrome.runtime.lastError) {
        console.error('[飞书采集] runtime 错误:', chrome.runtime.lastError.message);
        return;
      }
      if (resp && resp.ok) {
        console.log('[飞书采集] 推送成功:', resp.data);
        try {
          const stats = JSON.parse(sessionStorage.getItem('_feishu_stats') || '{"total":0}');
          stats.total = (stats.total || 0) + newMsgs.length;
          stats.lastSent = new Date().toISOString();
          sessionStorage.setItem('_feishu_stats', JSON.stringify(stats));
        } catch {}
      } else {
        console.error('[飞书采集] 推送失败:', resp && resp.error);
      }
    }
  );
}

// 初次延迟5秒后运行，之后按服务器配置间隔运行
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
