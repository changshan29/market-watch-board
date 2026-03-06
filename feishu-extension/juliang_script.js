// 聚量群消息采集 juliang_script.js
// 每60秒扫描 msg.juliang888.top 消息列表，推送到服务器

const INTERVAL_MS = 60 * 1000;

function getConfig() {
  return new Promise(resolve => {
    chrome.storage.local.get(['serverUrl', 'juliangGroupName', 'pluginInterval'], items => {
      resolve({
        serverUrl: items.serverUrl || 'http://localhost:3220',
        groupName: items.juliangGroupName || '聚量群',
        interval: (items.pluginInterval || 60) * 1000,
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

// 通过 background service worker 下载图片转 base64（绕过 CORS）
function fetchImgToBase64(src) {
  return new Promise(resolve => {
    chrome.runtime.sendMessage({ type: 'FETCH_IMAGE_BASE64', url: src }, resp => {
      if (chrome.runtime.lastError || !resp || !resp.ok) return resolve(null);
      resolve(resp.b64);
    });
  });
}

async function extractMessages() {
  const paras = [...document.querySelectorAll('p.MuiTypography-body1')];
  if (paras.length === 0) return [];

  const msgs = [];
  for (const p of paras) {
    const text = p.innerText.trim();
    if (/^\d{1,2}:\d{2}:\d{2}$/.test(text)) continue;

    const container = p.closest('li')
      || p.closest('[role="listitem"]')
      || p.parentElement?.parentElement
      || p.parentElement;

    // 收集容器内图片，fetch 转 base64
    const imageBase64s = [];
    if (container) {
      for (const img of container.querySelectorAll('img')) {
        const src = img.getAttribute('src') || '';
        if (!src || src.startsWith('data:')) continue;
        if (img.naturalWidth < 50 && img.naturalHeight < 50) continue;
        const b64 = await fetchImgToBase64(src);
        if (b64) imageBase64s.push(b64);
      }
    }

    if (!text) {
      if (imageBase64s.length > 0) {
        msgs.push({ text: '[图片]', timestamp: new Date().toISOString(), title: '图片', imageBase64s });
      }
      continue;
    }

    let timestamp = new Date().toISOString();
    const timeMatch = text.match(/^(\d{1,2}:\d{2}:\d{2})/);
    if (timeMatch) {
      const today = new Date();
      const [h, m, s] = timeMatch[1].split(':').map(Number);
      today.setHours(h, m, s, 0);
      timestamp = today.toISOString();
    }

    msgs.push({ text, timestamp, title: parseTitle(text), imageBase64s });
  }
  return msgs;
}

async function collectAndSend() {
  const { serverUrl, groupName } = await getConfig();
  const msgs = await extractMessages();

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
      content_html: '',
      images: msg.imageBase64s || [],
      image_urls: [],
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
setTimeout(async () => {
  if (!chrome.runtime?.id) return;
  const { interval } = await getConfig();
  collectAndSend();
  _timer = setInterval(() => {
    if (!chrome.runtime?.id) { clearInterval(_timer); return; }
    collectAndSend();
  }, interval || INTERVAL_MS);
}, 5000);
