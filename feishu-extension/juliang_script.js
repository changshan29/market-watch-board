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

// 把 img 元素转成 base64（处理跨域：先通过 canvas 绘制）
function imgToBase64(imgEl) {
  return new Promise(resolve => {
    try {
      // 如果已经是 base64，直接返回
      const src = imgEl.getAttribute('src') || '';
      if (src.startsWith('data:')) return resolve(src);

      const MAX = 1200;
      let w = imgEl.naturalWidth || imgEl.width || 200;
      let h = imgEl.naturalHeight || imgEl.height || 200;
      if (w > MAX) { h = Math.round(h * MAX / w); w = MAX; }
      if (h > MAX) { w = Math.round(w * MAX / h); h = MAX; }
      const canvas = document.createElement('canvas');
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(imgEl, 0, 0, w, h);
      resolve(canvas.toDataURL('image/jpeg', 0.8));
    } catch {
      resolve(null);
    }
  });
}

function getImgsHtml(container) {
  let html = '';
  if (!container) return html;
  for (const img of container.querySelectorAll('img')) {
    const src = img.getAttribute('src') || img.getAttribute('data-src') || '';
    if (src && !src.startsWith('data:')) {
      html += `<img src="${src}" style="max-width:100%;display:block;margin:4px 0;">`;
    }
  }
  return html;
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

    // 收集容器内图片转 base64
    const imageBase64s = [];
    if (container) {
      for (const img of container.querySelectorAll('img')) {
        if (!img.complete || img.naturalWidth === 0) continue;
        // 跳过极小图标（头像等）
        if (img.naturalWidth < 50 && img.naturalHeight < 50) continue;
        const b64 = await imgToBase64(img);
        if (b64) imageBase64s.push(b64);
      }
    }

    if (!text) {
      if (imageBase64s.length > 0) {
        msgs.push({
          text: '[图片]',
          timestamp: new Date().toISOString(),
          contentHtml: '',
          title: '图片',
          images: imageBase64s,
        });
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

    msgs.push({
      text,
      timestamp,
      contentHtml: '',
      title: parseTitle(text),
      images: imageBase64s,
    });
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
      content_html: msg.contentHtml,
      images: msg.images || [],
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
