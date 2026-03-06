/**
 * server.js — 财联社项目二服务端（端口 3220）
 *
 * GET  /               → 看板首页
 * GET  /admin          → 后台管理页
 * GET  /api/articles   → 文章列表（支持过滤）
 * POST /api/refresh    → 触发爬取
 * GET  /api/sources    → 读取 sources.json
 * POST /api/sources    → 更新 sources.json
 * GET  /api/settings   → 读取 settings.json
 * POST /api/settings   → 更新 settings.json
 * GET  /api/fetch-content?url=  → 服务端代理抓取原文 HTML
 */

const http   = require('http');
const https  = require('https');
const fs     = require('fs');
const path   = require('path');
const { exec, execFile, spawn } = require('child_process');

// 图片存储目录
const IMAGES_DIR = path.join(__dirname, 'data', 'images');
if (!fs.existsSync(IMAGES_DIR)) fs.mkdirSync(IMAGES_DIR, { recursive: true });

// 保存 base64 图片到本地，返回公开路径
function saveBase64Image(b64) {
  try {
    const matches = b64.match(/^data:image\/(\w+);base64,(.+)$/);
    if (!matches) return null;
    const ext = matches[1] === 'jpeg' ? 'jpg' : matches[1];
    const data = matches[2];
    const hash = require('crypto').createHash('md5').update(data.slice(0, 100)).digest('hex').slice(0, 16);
    const filename = `${hash}.${ext}`;
    const localPath = path.join(IMAGES_DIR, filename);
    if (!fs.existsSync(localPath)) {
      fs.writeFileSync(localPath, Buffer.from(data, 'base64'));
      console.log(`[image-save] saved ${filename}`);
    }
    return `/api/images/${filename}`;
  } catch { return null; }
}

const PORT          = 3220;
const DATA_FILE     = path.join(__dirname, 'data', 'articles.json');
const INDEX_FILE    = path.join(__dirname, 'index.html');
const ADMIN_FILE    = path.join(__dirname, 'admin.html');
const SOURCES_FILE  = path.join(__dirname, 'sources.json');
const SETTINGS_FILE = path.join(__dirname, 'settings.json');

const DEFAULT_SETTINGS = { intervals: { webpages: 1800, xueqiu: 600 }, plugin_interval: 60 };

function readJson(file, fallback) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return fallback; }
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', () => { try { resolve(JSON.parse(body)); } catch(e) { reject(e); } });
    req.on('error', reject);
  });
}

function readArticles() {
  return readJson(DATA_FILE, []);
}

// ── 权限检查：密码保护 ──────────────────────────────────────────────────────
const ADMIN_PASSWORD = '1995';

function requireAuth(req, res) {
  const auth = req.headers.authorization;
  if (!auth || !auth.startsWith('Basic ')) {
    res.writeHead(401, {
      'WWW-Authenticate': 'Basic realm="Admin Area"',
      'Content-Type': 'text/html; charset=utf-8'
    });
    res.end('需要密码访问');
    return false;
  }

  const credentials = Buffer.from(auth.split(' ')[1], 'base64').toString();
  const [username, password] = credentials.split(':');

  if (password !== ADMIN_PASSWORD) {
    res.writeHead(401, {
      'WWW-Authenticate': 'Basic realm="Admin Area"',
      'Content-Type': 'text/html; charset=utf-8'
    });
    res.end('密码错误');
    return false;
  }

  return true;
}

// ── 自动刷新调度（统一刷新，使用最小间隔）──────────────────────────────────
let refreshTimer = null;
let isPaused = false;
let serverStartTime = new Date().toISOString();
let lastScrapeTime = null;
let lastScrapeStatus = null;

function scheduleAutoRefresh() {
  if (refreshTimer) clearTimeout(refreshTimer);
  if (isPaused) return;

  const settings = readJson(SETTINGS_FILE, DEFAULT_SETTINGS);
  const iv = settings.intervals || {};
  const minSec = Math.min(iv.webpages ?? 1800, iv.xueqiu ?? 600);

  refreshTimer = setTimeout(() => {
    console.log('[auto] running full scraper...');
    lastScrapeTime = new Date().toISOString();
    lastScrapeStatus = 'running';
    exec('python3 run_cailianshe_2.py --no-kb --fast', {
      cwd: __dirname,
      timeout: 300000,
      maxBuffer: 10 * 1024 * 1024
    }, (err, stdout, stderr) => {
      if (err) {
        console.error('[auto] error:', err.message);
        console.error('[auto] stderr:', stderr);
        lastScrapeStatus = 'error: ' + err.message;
      } else {
        console.log('[auto] done');
        lastScrapeStatus = 'success';
      }
      scheduleAutoRefresh();
    });
  }, minSec * 1000);
  console.log(`[auto] next scrape in ${minSec} sec (${(minSec/60).toFixed(1)} min)`);
}

function pauseAutoRefresh() {
  isPaused = true;
  if (refreshTimer) clearTimeout(refreshTimer);
  refreshTimer = null;
  console.log('[auto] paused');
}

function resumeAutoRefresh() {
  isPaused = false;
  scheduleAutoRefresh();
  console.log('[auto] resumed');
}

// 启动时立即执行一次爬取（非阻塞，超时60秒）
console.log('[startup] running initial scrape...');
console.log('[startup] cwd:', __dirname);
console.log('[startup] command: python3 run_cailianshe_2.py --no-kb --fast');

// 先测试简单的Python脚本
exec('python3 test_simple.py', { cwd: __dirname }, (err, stdout, stderr) => {
  console.log('[test] simple python test:');
  console.log('[test] err:', err);
  console.log('[test] stdout:', stdout);
  console.log('[test] stderr:', stderr);
});

// 测试Python是否可用
exec('python3 --version', (err, stdout) => {
  console.log('[startup] python3 --version:', stdout ? stdout.trim() : 'no output');
});

lastScrapeTime = new Date().toISOString();
lastScrapeStatus = 'running (startup)';
exec('python3 run_cailianshe_2.py --no-kb --fast', {
  cwd: __dirname,
  timeout: 300000,  // 60秒超时
  maxBuffer: 10 * 1024 * 1024  // 10MB buffer
}, (err, stdout, stderr) => {
  console.log('[startup] callback triggered');
  console.log('[startup] err:', err);
  console.log('[startup] stdout length:', stdout ? stdout.length : 0);
  console.log('[startup] stderr length:', stderr ? stderr.length : 0);

  if (err) {
    console.error('[startup] error:', err.message);
    console.error('[startup] error code:', err.code);
    console.error('[startup] stderr:', stderr);
    console.error('[startup] stdout:', stdout);
    lastScrapeStatus = 'error: ' + err.message;

    // 即使失败也创建空数据文件，避免前端报错
    const dataDir = path.join(__dirname, 'data');
    const dataFile = path.join(dataDir, 'articles.json');
    if (!fs.existsSync(dataDir)) fs.mkdirSync(dataDir, { recursive: true });
    if (!fs.existsSync(dataFile)) fs.writeFileSync(dataFile, '[]');
  } else {
    console.log('[startup] initial scrape done');
    console.log('[startup] stdout:', stdout.slice(0, 500));
    lastScrapeStatus = 'success';
  }
  scheduleAutoRefresh();
});

// ── HTTP 服务 ─────────────────────────────────────────────────────────────────
const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);

  // GET /
  if (req.method === 'GET' && url.pathname === '/') {
    try {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(fs.readFileSync(INDEX_FILE, 'utf8'));
    } catch { res.writeHead(404); res.end('index.html not found'); }
    return;
  }

  // GET /admin - 仅本地访问
  if (req.method === 'GET' && url.pathname === '/admin') {
    if (!requireAuth(req, res)) return;
    try {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(fs.readFileSync(ADMIN_FILE, 'utf8'));
    } catch { res.writeHead(404); res.end('admin.html not found'); }
    return;
  }

  // GET /api/articles
  if (req.method === 'GET' && url.pathname === '/api/articles') {
    let articles = readArticles();
    const source = url.searchParams.get('source');
    const topic  = url.searchParams.get('topic');
    const q      = url.searchParams.get('q');
    if (source) articles = articles.filter(a => a.source_label === source || a.source_type === source);
    if (topic)  articles = articles.filter(a => a.topic_label === topic);
    if (q) {
      const lq = q.toLowerCase();
      articles = articles.filter(a =>
        (a.title   || '').toLowerCase().includes(lq) ||
        (a.content || '').toLowerCase().includes(lq)
      );
    }
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' });
    res.end(JSON.stringify(articles));
    return;
  }

  // POST /api/refresh - 仅本地访问
  if (req.method === 'POST' && url.pathname === '/api/refresh') {
    if (!requireAuth(req, res)) return;
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' });
    res.end(JSON.stringify({ status: 'refreshing' }));
    exec('python3 run_cailianshe_2.py --no-kb --fast', {
      cwd: __dirname,
      timeout: 300000,
      maxBuffer: 10 * 1024 * 1024
    }, (err, stdout, stderr) => {
      if (err) {
        console.error('[refresh] error:', err.message);
        console.error('[refresh] stderr:', stderr);
      } else {
        console.log('[refresh] done:', stdout.slice(0, 200));
      }
    });
    return;
  }

  // POST /api/notify  — 爬虫通知前端数据已更新（不触发再次爬取）
  if (req.method === 'POST' && url.pathname === '/api/notify') {
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' });
    res.end(JSON.stringify({ ok: true }));
    console.log('[notify] data updated by scraper');
    return;
  }

  // OPTIONS 预检（飞书插件跨域）
  if (req.method === 'OPTIONS' && url.pathname === '/api/feishu-msg') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    });
    res.end();
    return;
  }

  // POST /api/feishu-msg — 接收飞书插件推送的消息
  if (req.method === 'POST' && url.pathname === '/api/feishu-msg') {
    readBody(req).then(messages => {
      const articles = readArticles();
      const existingIds = new Set(articles.map(a => a.id));
      let added = 0;
      for (const msg of (Array.isArray(messages) ? messages : [messages])) {
        const uid = 'feishu_' + msg.id;
        if (existingIds.has(uid)) continue;
        const content = msg.text || '';
        const title = msg.title || (content === '[图片]' ? '图片消息' : (content.slice(0, 50) + (content.length > 50 ? '…' : '')));

        // 处理图片：base64 存本地，生成 content_html
        let contentHtml = msg.content_html || '';
        const imagePaths = [];
        for (const b64 of (msg.images || [])) {
          if (b64 && b64.startsWith('data:')) {
            const localPath = saveBase64Image(b64);
            if (localPath) imagePaths.push(localPath);
          }
        }
        if (imagePaths.length > 0) {
          contentHtml = imagePaths.map(p => `<img src="${p}" style="max-width:100%;display:block;margin:4px 0;">`).join('');
        } else if (content && content !== '[图片]') {
          contentHtml = `<p>${content.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>')}</p>`;
        }
        articles.unshift({
          id: uid,
          title,
          content: content.slice(0, 3000),
          content_html: contentHtml,
          source_type: '小作文',
          source_sub: msg.group_name || '飞书群',
          url: '',
          published_at: msg.timestamp || new Date().toISOString(),
          source_label: '小作文',
          feishu: true,
          topic_label: '其他',
          summary: content.slice(0, 100),
          kb_keywords: [], kb_matched: false, kb_snippets: [],
          industry_label: '其他',
        });
        existingIds.add(uid);
        added++;
      }
      if (added > 0) {
        // 小作文区域最多保留100条，超出时从末尾删除
        const MAX_XIAOZUOWEN = 100;
        const nonFeishu = articles.filter(a => a.source_label !== '小作文');
        let feishuArts = articles.filter(a => a.source_label === '小作文');
        if (feishuArts.length > MAX_XIAOZUOWEN) {
          feishuArts = feishuArts.slice(0, MAX_XIAOZUOWEN); // 已按时间倒序，保留最新的
        }
        const merged = [...feishuArts, ...nonFeishu];
        merged.sort((a, b) => (b.published_at || '').localeCompare(a.published_at || ''));
        fs.writeFileSync(DATA_FILE, JSON.stringify(merged, null, 2));
      }
      console.log(`[feishu-msg] received ${Array.isArray(messages) ? messages.length : 1}, added ${added}`);
      res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' });
      res.end(JSON.stringify({ ok: true, added }));
    }).catch(e => {
      res.writeHead(400);
      res.end(JSON.stringify({ error: e.message }));
    });
    return;
  }

  // GET /api/sources
  if (req.method === 'GET' && url.pathname === '/api/sources') {
    const src = readJson(SOURCES_FILE, { webpages: [], xueqiu: [], wechat: [], other: [] });
    if (!src.xueqiu) src.xueqiu = [];   // 兼容旧格式
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' });
    res.end(JSON.stringify(src));
    return;
  }

  // POST /api/sources - 仅本地访问
  if (req.method === 'POST' && url.pathname === '/api/sources') {
    if (!requireAuth(req, res)) return;
    readBody(req).then(data => {
      fs.writeFileSync(SOURCES_FILE, JSON.stringify(data, null, 2));
      res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
      res.end(JSON.stringify({ ok: true }));
    }).catch(e => {
      res.writeHead(400); res.end(JSON.stringify({ error: e.message }));
    });
    return;
  }

  // GET /api/settings - 仅本地访问
  if (req.method === 'GET' && url.pathname === '/api/settings') {
    if (!requireAuth(req, res)) return;
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' });
    res.end(JSON.stringify(readJson(SETTINGS_FILE, DEFAULT_SETTINGS)));
    return;
  }

  // GET /api/plugin-config — 公开端点，供 Chrome 插件读取采集间隔
  if (req.method === 'GET' && url.pathname === '/api/plugin-config') {
    const s = readJson(SETTINGS_FILE, DEFAULT_SETTINGS);
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' });
    res.end(JSON.stringify({ plugin_interval: s.plugin_interval || 60 }));
    return;
  }

  // GET /api/images/:filename — 本地代理图片
  if (req.method === 'GET' && url.pathname.startsWith('/api/images/')) {
    const filename = path.basename(url.pathname);
    const filePath = path.join(IMAGES_DIR, filename);
    if (fs.existsSync(filePath)) {
      const ext = path.extname(filename).slice(1);
      const mime = { jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', gif: 'image/gif', webp: 'image/webp' }[ext] || 'image/jpeg';
      res.writeHead(200, { 'Content-Type': mime, 'Cache-Control': 'public, max-age=86400' });
      res.end(fs.readFileSync(filePath));
    } else {
      res.writeHead(404); res.end('Not found');
    }
    return;
  }

  // GET /api/debug - 调试信息（公开）
  if (req.method === 'GET' && url.pathname === '/api/debug') {
    const articles = readArticles();
    const latestArticle = articles.length > 0 ? articles[0] : null;
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' });
    res.end(JSON.stringify({
      serverStartTime,
      lastScrapeTime,
      lastScrapeStatus,
      isPaused,
      articlesCount: articles.length,
      latestArticleTime: latestArticle ? latestArticle.published_at : null,
      latestArticleTitle: latestArticle ? latestArticle.title : null,
    }));
    return;
  }

  // POST /api/settings - 仅本地访问
  if (req.method === 'POST' && url.pathname === '/api/settings') {
    if (!requireAuth(req, res)) return;
    readBody(req).then(data => {
      fs.writeFileSync(SETTINGS_FILE, JSON.stringify(data, null, 2));
      scheduleAutoRefresh();   // 用新间隔重置计时器
      res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
      res.end(JSON.stringify({ ok: true }));
    }).catch(e => {
      res.writeHead(400); res.end(JSON.stringify({ error: e.message }));
    });
    return;
  }

  // POST /api/ai-filter
  if (req.method === 'POST' && url.pathname === '/api/ai-filter') {
    readBody(req).then(data => {
      const child = spawn('python3', ['ai_filter.py'], { cwd: __dirname });
      let out = '', err = '';
      child.stdin.write(JSON.stringify(data));
      child.stdin.end();
      child.stdout.on('data', d => out += d);
      child.stderr.on('data', d => err += d);
      child.on('close', () => {
        res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' });
        try {
          res.end(out.trim() || JSON.stringify({ matched_ids: [], error: err }));
        } catch {
          res.end(JSON.stringify({ matched_ids: [] }));
        }
      });
      child.on('error', e => {
        res.writeHead(500);
        res.end(JSON.stringify({ matched_ids: [], error: e.message }));
      });
    }).catch(e => {
      res.writeHead(400); res.end(JSON.stringify({ error: e.message }));
    });
    return;
  }

  // POST /api/pause - 仅本地访问
  if (req.method === 'POST' && url.pathname === '/api/pause') {
    if (!requireAuth(req, res)) return;
    pauseAutoRefresh();
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' });
    res.end(JSON.stringify({ status: 'paused' }));
    return;
  }

  // POST /api/resume - 仅本地访问
  if (req.method === 'POST' && url.pathname === '/api/resume') {
    if (!requireAuth(req, res)) return;
    resumeAutoRefresh();
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' });
    res.end(JSON.stringify({ status: 'running' }));
    return;
  }

  // GET /api/status
  if (req.method === 'GET' && url.pathname === '/api/status') {
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' });
    res.end(JSON.stringify({ paused: isPaused }));
    return;
  }

  // GET /api/xueqiu-user?id=xxx - 获取雪球用户名（仅本地访问）
  if (req.method === 'GET' && url.pathname === '/api/xueqiu-user') {
    if (!requireAuth(req, res)) return;
    const userId = url.searchParams.get('id');
    if (!userId) {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: '缺少用户ID' }));
      return;
    }
    const pyScript = `
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import sys
import time

user_id = sys.argv[1]

options = Options()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--disable-gpu')
options.add_experimental_option("excludeSwitches", ["enable-automation"])

try:
    driver = webdriver.Chrome(options=options)
    driver.get(f"https://xueqiu.com/u/{user_id}")

    wait = WebDriverWait(driver, 10)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".timeline__item")))
    time.sleep(3)

    # 提取用户名
    name_elem = driver.find_element(By.CSS_SELECTOR, ".user-name")
    print(name_elem.text.strip())

    driver.quit()
except Exception:
    print("")
    try:
        driver.quit()
    except:
        pass
`;
    execFile('python3', ['-c', pyScript, userId], { timeout: 35000, cwd: __dirname }, (err, stdout, stderr) => {
      const username = stdout.trim();
      res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' });
      res.end(JSON.stringify({ name: username || '' }));
    });
    return;
  }

  // GET /api/fetch-content?url=...
  if (req.method === 'GET' && url.pathname === '/api/fetch-content') {
    const targetUrl = url.searchParams.get('url');
    if (!targetUrl) {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ content_html: '' }));
      return;
    }
    const pyScript = [
      'import sys, requests, re',
      'from bs4 import BeautifulSoup',
      'url = sys.argv[1]',
      'hdrs = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}',
      'try:',
      '    r = requests.get(url, headers=hdrs, timeout=15)',
      '    soup = BeautifulSoup(r.text, "html.parser")',
      '    el = (soup.select_one("#js_content") or soup.select_one(".rich_media_content")',
      '         or soup.select_one("article") or soup.select_one(".article-content")',
      '         or soup.select_one(".post-content") or soup.select_one(".entry-content")',
      '         or soup.select_one("main") or soup.select_one(".main-content"))',
      '    if el:',
      '        el.attrs.pop("style", None)',
      '        for img in el.find_all("img"):',
      '            ds  = img.get("data-src", "")',
      '            src = img.get("src", "")',
      '            if ds and (not src or src.startswith("data:")):',
      '                img["src"] = ds',
      '        print(str(el))',
      'except Exception:',
      '    pass',
    ].join('\n');
    execFile('python3', ['-c', pyScript, targetUrl], { timeout: 20000, cwd: __dirname }, (err, stdout) => {
      res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' });
      res.end(JSON.stringify({ content_html: stdout.trim() }));
    });
    return;
  }

  res.writeHead(404);
  res.end('Not found');
});

server.listen(PORT, () => {
  console.log(`盯盘资讯看板服务已启动：http://localhost:${PORT}`);
});
