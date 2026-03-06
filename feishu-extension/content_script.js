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

// 从图片元素提取真实 URL（飞书图片有多种存放方式）
function extractImgUrl(imgEl) {
  // 优先取高清 src，飞书图片 src 通常已是完整 URL
  const src = imgEl.getAttribute('src') || '';
  const dataSrc = imgEl.getAttribute('data-src') || '';
  const url = src.startsWith('http') ? src : (dataSrc.startsWith('http') ? dataSrc : '');
  // 过滤 base64 和极小图标
  if (!url || url.startsWith('data:')) return null;
  // 飞书图片域名特征
  if (url.includes('feishu') || url.includes('larksuit') || url.includes('larksuite') ||
      url.includes('bytedance') || url.includes('byteimg') || url.includes('feishucdn')) {
    return url;
  }
  // 其他 https 图片也接受
  if (url.startsWith('https://')) return url;
  return null;
}

function extractMessages() {
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

    // ── 图片消息 ──
    // 飞书图片消息：.im-image-message，或 .message-content 内含 img
    const imgEls = item.querySelectorAll(
      '.im-image-message img, .message-content img, [class*="image-message"] img, [class*="imageMessage"] img'
    );
    if (imgEls.length > 0) {
      const imageUrls = [];
      for (const imgEl of imgEls) {
        const url = extractImgUrl(imgEl);
        if (url) imageUrls.push(url);
      }
      if (imageUrls.length > 0) {
        msgs.push({
          msgId,
          sender: lastSender,
          text: '[图片]',
          timestamp,
          images: imageUrls,
        });
        console.log(`[飞书采集] 图片消息 ${msgId}: ${imageUrls.length} 张`);
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
