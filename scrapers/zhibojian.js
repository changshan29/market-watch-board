/**
 * scrapers/zhibojian.js
 * 抓取 http://43.142.67.10:1000/#/ 直播间消息
 * 接口：POST /4/api/msg/list  {rid, msgid, tt}  headers: token/AD/version/i
 * 结果转换为「小作文」格式写入 articles.json
 */

'use strict';

const http  = require('http');
const https = require('https');
const fs    = require('fs');
const path  = require('path');

// ── 配置 ──────────────────────────────────────────────────────────────────
const BASE_URL   = 'http://43.142.67.10:1000';
const DATA_FILE  = path.join(__dirname, '..', 'data', 'articles.json');
const STATE_FILE = path.join(__dirname, '..', 'data', 'zhibojian_state.json');
const MAX_ITEMS  = 150;   // 小作文区域最大条数
const PAGE_SIZE  = 30;    // 每次拉取消息数（服务端默认返回 30）

// ── HTTP POST 工具 ────────────────────────────────────────────────────────
function postJSON(urlStr, body, token) {
  return new Promise((resolve, reject) => {
    const parsed  = new URL(urlStr);
    const isHttps = parsed.protocol === 'https:';
    const lib     = isHttps ? https : http;
    const payload = JSON.stringify(Object.assign({}, body, { tt: Date.now() }));
    const opts = {
      hostname: parsed.hostname,
      port:     parsed.port || (isHttps ? 443 : 80),
      path:     parsed.pathname + parsed.search,
      method:   'POST',
      headers: {
        'Content-Type':   'application/json',
        'Content-Length': Buffer.byteLength(payload),
        'token':          token || '',
        'AD':             'true',
        'version':        '4.2.3',
        'i':              'qq',
        'Referer':        BASE_URL + '/',
      },
      timeout: 10000,
    };
    const req = lib.request(opts, res => {
      let data = '';
      res.on('data', c => { data += c; });
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch(e) { reject(new Error('JSON parse error: ' + data.slice(0, 200))); }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('request timeout')); });
    req.write(payload);
    req.end();
  });
}

// ── 状态读写（记录各群最后消息 id，增量拉取）─────────────────────────────
function readState() {
  try { return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')); }
  catch { return {}; }
}
function writeState(state) {
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

// ── 获取所有直播间列表 ────────────────────────────────────────────────────
async function fetchRoomList(token) {
  const data = await postJSON(`${BASE_URL}/4/api/room/list`, {}, token);
  if (data.code !== 200 || !Array.isArray(data.list)) {
    throw new Error('room/list failed: ' + JSON.stringify(data).slice(0, 100));
  }
  return data.list; // [{id, title, msg, msgtime, ...}]
}

// ── 获取某个直播间的消息列表（增量）──────────────────────────────────────
// msgid=0 表示从最新开始；msgid=N 表示拉取比 N 更旧的消息（分页）
// 增量策略：记录 lastId，只保留 id > lastId 的新消息
async function fetchMessages(roomId, token, lastId) {
  const data = await postJSON(`${BASE_URL}/4/api/msg/list`, { rid: roomId, msgid: 0 }, token);
  if (!data || data.code !== 200 || !Array.isArray(data.list)) return [];
  let msgs = data.list;
  if (lastId) {
    msgs = msgs.filter(m => Number(m.id) > Number(lastId));
  }
  return msgs;
}

// ── 把直播间消息转换为看板 article 格式 ───────────────────────────────────
// msg 字段结构：JSON 字符串 [{type:'text',msg:'...'},{type:'pic',url:'...'}]
function msgToArticle(msg, roomTitle) {
  let textParts  = [];
  let contentHtml = '';

  const rawMsg = msg.msg || '';
  try {
    const parts = JSON.parse(rawMsg);
    for (const p of parts) {
      if (p.type === 'text' && p.msg) {
        // 服务端双重转义了 \n，需处理
        const txt = p.msg
          .replace(/\\\\n/g, '\n')
          .replace(/\\n/g, '\n')
          .replace(/　/g, '')
          .trim();
        textParts.push(txt);
        contentHtml += `<p>${txt.replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>')}</p>`;
      } else if (p.type === 'pic' && p.url) {
        contentHtml += `<img src="${p.url}" style="max-width:100%;display:block;margin:4px 0;">`;
        if (!textParts.length) textParts.push('[图片]');
      }
    }
  } catch {
    const raw = String(rawMsg);
    textParts.push(raw);
    contentHtml = `<p>${raw.replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>')}</p>`;
  }

  const fullText = textParts.join('\n').trim();
  const title = fullText === '[图片]' ? '图片消息'
    : (fullText.slice(0, 50) + (fullText.length > 50 ? '…' : ''));

  // createtime 是毫秒时间戳（number）
  const publishedAt = msg.createtime
    ? new Date(Number(msg.createtime)).toISOString()
    : new Date().toISOString();

  return {
    id:             'zhibojian_' + msg.id,
    title:          title || '[空消息]',
    content:        fullText.slice(0, 3000),
    content_html:   contentHtml,
    source_type:    '小作文',
    source_sub:     roomTitle || '直播间',
    url:            '',
    published_at:   publishedAt,
    source_label:   '小作文',
    zhibojian:      true,
    zhibojian_msg_id: String(msg.id),
    zhibojian_room:   roomTitle || '',
    topic_label:    '其他',
    summary:        fullText.slice(0, 100),
    kb_keywords: [], kb_matched: false, kb_snippets: [],
    industry_label: '其他',
  };
}

// ── 读写 articles.json ───────────────────────────────────────────────────
function readArticles() {
  try { return JSON.parse(fs.readFileSync(DATA_FILE, 'utf8')); }
  catch { return []; }
}
function writeArticles(articles) {
  fs.writeFileSync(DATA_FILE, JSON.stringify(articles, null, 2));
}

// ── 主抓取函数 ────────────────────────────────────────────────────────────
async function scrape(token, settings) {
  if (!token) {
    console.error('[zhibojian] no token configured');
    return { added: 0, error: 'no token' };
  }

  const state   = readState();
  let articles  = readArticles();
  const existingIds = new Set(articles.map(a => a.id));
  let totalAdded = 0;

  // 确定要抓取的房间列表
  let targetRooms = [];
  if (settings && Array.isArray(settings.enabled_rooms) && settings.enabled_rooms.length > 0) {
    targetRooms = settings.enabled_rooms;
  } else {
    // fallback：自动找「每日调研」
    try {
      const allRooms = await fetchRoomList(token);
      const mrdyan = allRooms.find(r => r.title && r.title.includes('每日调研'));
      targetRooms = mrdyan
        ? [{ id: mrdyan.id, title: mrdyan.title }]
        : allRooms.slice(0, 1).map(r => ({ id: r.id, title: r.title }));
    } catch(e) {
      console.error('[zhibojian] fetchRoomList failed:', e.message);
      return { added: 0, error: e.message };
    }
  }

  // 并发拉各群消息
  await Promise.all(targetRooms.map(async room => {
    try {
      const lastId = state[String(room.id)] || null;
      const msgs   = await fetchMessages(room.id, token, lastId);
      if (msgs.length === 0) return;

      const newArticles = [];
      for (const msg of msgs) {
        const art = msgToArticle(msg, room.title);
        if (!existingIds.has(art.id)) {
          newArticles.push(art);
          existingIds.add(art.id);
          totalAdded++;
        }
      }

      if (newArticles.length > 0) {
        articles = [...newArticles, ...articles];
        // 记录最新 id（取最大值）
        const maxId = msgs.reduce((max, m) => Number(m.id) > Number(max) ? m.id : max, 0);
        state[String(room.id)] = maxId;
        console.log(`[zhibojian] 「${room.title}」新增 ${newArticles.length} 条`);
      }
    } catch(e) {
      console.error(`[zhibojian] room ${room.id} (${room.title}) failed:`, e.message);
    }
  }));

  if (totalAdded > 0) {
    const nonZhibo = articles.filter(a => a.source_label !== '小作文');
    let zhiboArts  = articles.filter(a => a.source_label === '小作文');
    zhiboArts.sort((a, b) => String(b.published_at || '').localeCompare(String(a.published_at || '')));
    if (zhiboArts.length > MAX_ITEMS) zhiboArts = zhiboArts.slice(0, MAX_ITEMS);
    const merged = [...zhiboArts, ...nonZhibo];
    merged.sort((a, b) => String(b.published_at || '').localeCompare(String(a.published_at || '')));
    writeArticles(merged);
    writeState(state);
  }

  return { added: totalAdded };
}

// ── 获取房间列表（供后台管理页） ──────────────────────────────────────────
async function getRoomList(token) {
  return fetchRoomList(token);
}

module.exports = { scrape, getRoomList };
