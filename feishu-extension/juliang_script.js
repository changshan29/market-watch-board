// 聚量群消息采集 juliang_script.js
// 每60秒扫描 msg.juliang888.top 消息列表，推送到服务器

const INTERVAL_MS = 60 * 1000;

function getConfig() {
  return new Promise(resolve => {
    chrome.storage.local.get(['serverUrl', 'juliangGroupName'], items => {
      resolve({
        serverUrl: items.serverUrl || 'http://localhost:3220',
        groupName: items.juliangGroupName || '聚量群',
      });
    });
  });
}

function getSentHashes() {
  try {
    return new Set(JSON.parse(sessionStorage.getItem('_juliang_sent') || '[]'));
  } catch { return new Set(); }
}

function saveSentHashes(set) {
  const arr = [...set].slice(-2000);
  sessionStorage.setItem('_juliang_sent', JSON.stringify(arr));
}

// 从文本里提取标题：取【...】内的内容，否则取前50字
function parseTitle(text) {
  const m = text.match(/【([^】]+)】/);
  if (m) return m[1];
  return text.replace(/^\d{1,2}:\d{2}:\d{2}\s*/, '').slice(0, 50);
}

function extractMessages() {
  // 稳定选择器：MuiTypography-body1
  const paras = [...document.querySelectorAll('p.MuiTypography-body1')];
  if (paras.length === 0) return [];

  const msgs = [];
  for (const p of paras) {
    const text = p.innerText.trim();
    if (!text) continue;
    // 跳过纯时间格式（如 "13:42:14"）
    if (/^\d{1,2}:\d{2}:\d{2}$/.test(text)) continue;

    // 尝试从文本头部解析时间 "13:42:14"
    let timestamp = new Date().toISOString();
    const timeMatch = text.match(/^(\d{1,2}:\d{2}:\d{2})/);
    if (timeMatch) {
      const today = new Date();
      const [h, m, s] = timeMatch[1].split(':').map(Number);
      today.setHours(h, m, s, 0);
      timestamp = today.toISOString();
    }

    // 构建 content_html：文本 + 父容器内的图片
    let contentHtml = `<p>${text.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</p>`;
    const container = p.parentElement;
    if (container) {
      const imgs = container.querySelectorAll('img');
      for (const img of imgs) {
        const src = img.getAttribute('src') || img.getAttribute('data-src') || '';
        if (src && !src.startsWith('data:')) {
          contentHtml += `<img src="${src}" style="max-width:100%;display:block;margin:4px 0;">`;
        }
      }
    }

    msgs.push({
      text,
      timestamp,
      contentHtml,
      title: parseTitle(text),
    });
  }
  return msgs;
}

async function collectAndSend() {
  const { serverUrl, groupName } = await getConfig();
  const msgs = extractMessages();

  if (msgs.length === 0) {
    console.log('[聚量采集] 未找到消息，跳过');
    return;
  }

  const sent = getSentHashes();
  const newMsgs = [];

  for (const msg of msgs) {
    const h = msg.text.slice(0, 30);
    if (sent.has(h)) continue;
    sent.add(h);
    newMsgs.push({
      id: msg.text.slice(0, 60).replace(/\s+/g, ''),
      text: msg.text,
      title: msg.title,
      content_html: msg.contentHtml,
      group_name: groupName,
      timestamp: msg.timestamp,
    });
  }

  saveSentHashes(sent);

  if (newMsgs.length === 0) {
    console.log('[聚量采集] 无新消息');
    return;
  }

  console.log(`[聚量采集] 发现 ${newMsgs.length} 条新消息，推送中...`);
  try {
    chrome.runtime.sendMessage(
      { type: 'PUSH_MESSAGES', serverUrl, messages: newMsgs },
      resp => {
        if (resp && resp.ok) {
          console.log('[聚量采集] 推送结果:', resp.data);
          const stats = JSON.parse(sessionStorage.getItem('_juliang_stats') || '{"total":0}');
          stats.total = (stats.total || 0) + (resp.data.added || 0);
          stats.lastSent = new Date().toISOString();
          sessionStorage.setItem('_juliang_stats', JSON.stringify(stats));
        } else {
          console.error('[聚量采集] 推送失败:', resp && resp.error);
        }
      }
    );
  } catch (e) {
    console.error('[聚量采集] 推送失败:', e);
  }
}

let _timer = null;
setTimeout(() => {
  if (!chrome.runtime?.id) return;
  collectAndSend();
  _timer = setInterval(() => {
    if (!chrome.runtime?.id) { clearInterval(_timer); return; }
    collectAndSend();
  }, INTERVAL_MS);
}, 5000);
