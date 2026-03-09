#!/usr/bin/env node
/**
 * zhibojian-push.js
 * 本地运行：从直播间抓取最新消息，通过 /api/feishu-msg 接口推送到 Railway
 * 解决 Railway IP 被直播间 API 屏蔽的问题
 */

const http  = require('http');
const https = require('https');
const fs    = require('fs');
const path  = require('path');

const SETTINGS_PATH  = path.join(__dirname, 'settings.json');
const STATE_PATH     = path.join(__dirname, 'data', 'zhibojian_push_state.json');
const RAILWAY_URL    = 'https://web-production-af97c.up.railway.app';
const ZHIBOJIAN_URL  = 'http://43.142.67.10:1000';

function postJSON(urlStr, body, extraHeaders) {
  return new Promise((resolve, reject) => {
    const parsed  = new URL(urlStr);
    const lib     = parsed.protocol === 'https:' ? https : http;
    const payload = JSON.stringify(body);
    const headers = {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(payload),
      ...(extraHeaders || {}),
    };
    const opts = {
      hostname: parsed.hostname,
      port: parsed.port || (parsed.protocol === 'https:' ? 443 : 80),
      path: parsed.pathname,
      method: 'POST',
      headers,
      timeout: 20000,
    };
    const req = lib.request(opts, res => {
      let d = ''; res.on('data', c => d += c);
      res.on('end', () => { try { resolve(JSON.parse(d)); } catch { resolve({ raw: d.slice(0,200) }); } });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
    req.write(payload); req.end();
  });
}

function zbPost(zbPath, body, token) {
  return postJSON(`${ZHIBOJIAN_URL}${zbPath}`, body, {
    token, AD: 'true', version: '4.2.3', i: 'qq',
    Referer: ZHIBOJIAN_URL + '/',
  });
}

function parseMsg(raw) {
  try {
    const arr = JSON.parse(raw);
    let text = '', imageUrls = [];
    for (const seg of arr) {
      if (seg.type === 'text') text += (seg.msg || '').replace(/\\n/g, '\n');
      else if (seg.type === 'pic' && seg.url) imageUrls.push(seg.url);
      else if (seg.type === 'file') text += `[文件:${seg.name || ''}]`;
    }
    return { text: text.trim(), imageUrls };
  } catch { return { text: raw, imageUrls: [] }; }
}

async function scrapeRoom(room, token, lastMsgId) {
  const data = await zbPost('/4/api/msg/list', { rid: room.id, msgid: lastMsgId || 0, tt: Date.now() }, token);
  if (!data || data.code !== 200) {
    throw new Error(`code ${data && data.code}: ${data && data.msg}`);
  }
  const list = (data.list || []).filter(m => !lastMsgId || m.id > lastMsgId);
  return list;
}

async function main() {
  const ts = new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' });
  console.log(`[zhibojian-push] ${ts}`);

  let settings;
  try { settings = JSON.parse(fs.readFileSync(SETTINGS_PATH, 'utf8')); }
  catch(e) { console.error('读取 settings.json 失败:', e.message); process.exit(1); }

  const zb = settings.zhibojian || {};
  const token = zb.token;
  if (!token) { console.error('无 token'); process.exit(1); }

  const rooms = [
    ...(zb.xiaozuowen_rooms || []).map(r => ({ ...r, subType: 'xiaozuowen' })),
    ...(zb.jigou_rooms || []).map(r => ({ ...r, subType: 'jigou' })),
  ];

  let state = {};
  try { state = JSON.parse(fs.readFileSync(STATE_PATH, 'utf8')); } catch {}

  const allMessages = [];
  const newState = { ...state };

  for (const room of rooms) {
    const lastId = state[`lastId_${room.id}`] || 0;
    try {
      const msgs = await scrapeRoom(room, token, lastId);
      console.log(`[zhibojian-push] 「${room.title}」 ${msgs.length} 条新消息`);
      for (const msg of msgs) {
        const { text, imageUrls } = parseMsg(msg.msg || '');
        if (!text && !imageUrls.length) continue;
        const content = text || '[图片]';
        const title = content === '[图片]' ? '图片消息'
          : content.slice(0, 60).replace(/\n/g, ' ');
        allMessages.push({
          id: `zb_${room.id}_${msg.id || msg.oid}`,
          text: content,
          title,
          group_name: room.title,
          image_urls: imageUrls,
          timestamp: msg.createtime || Date.now(),
          // 标记 source_sub_type 让前端知道是 jigou 还是 xiaozuowen
          _subType: room.subType,
        });
        const msgId = msg.id || msg.oid || 0;
        if (msgId > (newState[`lastId_${room.id}`] || 0)) {
          newState[`lastId_${room.id}`] = msgId;
        }
      }
    } catch(e) {
      console.error(`[zhibojian-push] 「${room.title}」 失败:`, e.message);
    }
  }

  if (allMessages.length === 0) {
    console.log('[zhibojian-push] 无新消息');
    fs.writeFileSync(STATE_PATH, JSON.stringify(newState, null, 2));
    return;
  }

  // 推给 Railway（用 feishu-msg 接口，无需认证）
  console.log(`[zhibojian-push] 推送 ${allMessages.length} 条到 Railway...`);
  try {
    const resp = await postJSON(`${RAILWAY_URL}/api/feishu-msg`, allMessages);
    console.log('[zhibojian-push] Railway 响应:', resp);
    fs.writeFileSync(STATE_PATH, JSON.stringify(newState, null, 2));
    console.log('[zhibojian-push] ✅ 完成');
  } catch(e) {
    console.error('[zhibojian-push] 推送失败:', e.message);
    process.exit(1);
  }
}

main().catch(e => { console.error('[zhibojian-push] fatal:', e.message); process.exit(1); });
