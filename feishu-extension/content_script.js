// 飞书消息采集 content_script.js
// 每60秒扫描飞书群聊 DOM，将新消息推送到服务器

const INTERVAL_MS = 60 * 1000;

function getConfig() {
  return new Promise(resolve => {
    chrome.storage.local.get(['serverUrl', 'groupName'], items => {
      resolve({
        serverUrl: items.serverUrl || 'http://localhost:3220',
        groupName: items.groupName || '飞书群',
      });
    });
  });
}

function hashMsg(sender, text) {
  return sender + '::' + text.slice(0, 20);
}

function getSentHashes() {
  try {
    return new Set(JSON.parse(sessionStorage.getItem('_feishu_sent') || '[]'));
  } catch {
    return new Set();
  }
}

function saveSentHashes(set) {
  // 最多保留2000条，防止无限增长
  const arr = [...set].slice(-2000);
  sessionStorage.setItem('_feishu_sent', JSON.stringify(arr));
}

function extractMessages() {
  // 多套备选选择器，应对飞书 DOM 变更
  const containerSelectors = [
    '[data-testid="message-list"]',
    '.message-list',
    '.chat-content',
    '.im-chat-main-msg-list',
    '.msg-list',
  ];
  const itemSelectors = [
    '[data-testid="message-item"]',
    '.message-item',
    '.msg-list-item',
    '.im-message-item',
    '.chat-message-item',
  ];
  const textSelectors = [
    '.text-content',
    '.message-text',
    '.msg-text',
    '.im-message-text',
    '[data-type="text"]',
  ];
  const senderSelectors = [
    '.sender-name',
    '.name',
    '.msg-sender-name',
    '.im-sender-name',
    '.author-name',
  ];

  // 找消息容器
  let container = null;
  for (const sel of containerSelectors) {
    container = document.querySelector(sel);
    if (container) break;
  }
  if (!container) container = document.body;

  // 找消息条目
  let items = [];
  for (const sel of itemSelectors) {
    items = [...container.querySelectorAll(sel)];
    if (items.length > 0) break;
  }
  if (items.length === 0) return [];

  const msgs = [];
  for (const item of items) {
    // 提取文本
    let text = '';
    for (const sel of textSelectors) {
      const el = item.querySelector(sel);
      if (el) { text = el.innerText.trim(); break; }
    }
    if (!text) text = item.innerText.trim();
    if (!text) continue;

    // 提取发送者
    let sender = '';
    for (const sel of senderSelectors) {
      const el = item.querySelector(sel);
      if (el) { sender = el.innerText.trim(); break; }
    }

    // 提取时间（尽力而为）
    let timestamp = new Date().toISOString();
    const timeEl = item.querySelector('time, [data-time], .time, .msg-time, .message-time');
    if (timeEl) {
      const t = timeEl.getAttribute('datetime') || timeEl.getAttribute('data-time') || timeEl.innerText;
      if (t) {
        const parsed = new Date(t);
        if (!isNaN(parsed)) timestamp = parsed.toISOString();
      }
    }

    msgs.push({ sender, text, timestamp });
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

  const sent = getSentHashes();
  const newMsgs = [];

  for (const msg of msgs) {
    const h = hashMsg(msg.sender, msg.text);
    if (sent.has(h)) continue;
    sent.add(h);
    newMsgs.push({
      id: h + '_' + Date.now(),
      text: msg.text,
      sender: msg.sender,
      group_name: groupName,
      timestamp: msg.timestamp,
    });
  }

  saveSentHashes(sent);

  if (newMsgs.length === 0) {
    console.log('[飞书采集] 无新消息');
    return;
  }

  console.log(`[飞书采集] 发现 ${newMsgs.length} 条新消息，推送中...`);
  try {
    chrome.runtime.sendMessage(
      { type: 'PUSH_MESSAGES', serverUrl, messages: newMsgs },
      resp => {
        if (resp && resp.ok) {
          console.log('[飞书采集] 推送结果:', resp.data);
          const stats = JSON.parse(sessionStorage.getItem('_feishu_stats') || '{"total":0}');
          stats.total = (stats.total || 0) + (resp.data.added || 0);
          stats.lastSent = new Date().toISOString();
          sessionStorage.setItem('_feishu_stats', JSON.stringify(stats));
        } else {
          console.error('[飞书采集] 推送失败:', resp && resp.error);
        }
      }
    );
  } catch (e) {
    console.error('[飞书采集] 推送失败:', e);
  }
}

// 初次延迟5秒后运行（等页面加载完成），之后每60秒一次
let _timer = null;
setTimeout(() => {
  if (!chrome.runtime?.id) return;
  collectAndSend();
  _timer = setInterval(() => {
    if (!chrome.runtime?.id) { clearInterval(_timer); return; }
    collectAndSend();
  }, INTERVAL_MS);
}, 5000);
