// 飞书消息采集 content_script.js
// 每60秒扫描飞书群聊 DOM，将新消息推送到服务器
// 选择器基于实际 DOM 分析（2026-03）：
//   消息容器：[data-id].messageItem-wrapper
//   消息文本：.richTextContainer（内含 .rich-text-paragraph）
//   发送者：.message-info-name
//   时间戳：.message-timestamp（连续消息只有第一条有时间）

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

function extractMessages() {
  // 飞书消息容器：[data-id].messageItem-wrapper
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

    // 提取文本：.richTextContainer 包含实际富文本内容
    const richEl = item.querySelector('.richTextContainer');
    if (!richEl) continue;
    const text = richEl.innerText.trim();
    if (!text) continue;

    // 发送者：.message-info-name（连续消息没有发送者节点，沿用上一条）
    const senderEl = item.querySelector('.message-info-name');
    if (senderEl && senderEl.innerText.trim()) {
      lastSender = senderEl.innerText.trim();
    }

    // 时间戳：.message-timestamp（连续消息没有，沿用上一条）
    const timeEl = item.querySelector('.message-timestamp');
    if (timeEl && timeEl.innerText.trim()) {
      lastTime = timeEl.innerText.trim();
    }

    // 将 "14:54" 格式转为完整 ISO 时间戳
    let timestamp = new Date().toISOString();
    if (lastTime) {
      const m = lastTime.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?/);
      if (m) {
        const d = new Date();
        d.setHours(parseInt(m[1]), parseInt(m[2]), parseInt(m[3] || '0'), 0);
        timestamp = d.toISOString();
      }
    }

    msgs.push({ msgId, sender: lastSender, text, timestamp });
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

  console.log(`[飞书采集] 发现 ${newMsgs.length} 条新消息，推送中...`);
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
