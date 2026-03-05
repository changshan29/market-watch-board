"""
scrapers/webpage.py — 指定URL列表爬取

读取 sources.json 中的 webpages 配置，
用 requests + BeautifulSoup 抓取正文内容。
统一返回格式：
  {id, title, content, source_type="网页", source_sub=域名, url, published_at}
"""

import json
import hashlib
import requests
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup

SOURCES_FILE = Path(__file__).parent.parent / "sources.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

# 正文提取：优先尝试常见正文容器
CONTENT_SELECTORS = [
    "article",
    "[class*='content']",
    "[class*='article']",
    "[class*='body']",
    "main",
]

# ── 同花顺财经 实时资讯 API ───────────────────────────────────────────────────
_THS_API = "https://news.10jqka.com.cn/tapp/news/push/stock"


def _fetch_ths(name: str = "同花顺财经") -> list[dict]:
    """通过同花顺财经内部 AJAX API 获取实时资讯列表"""
    headers = {
        **HEADERS,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://news.10jqka.com.cn/realtimenews.html",
    }
    try:
        resp = requests.get(
            _THS_API,
            params={"page": "1", "tag": "", "limit": "30",
                    "created_at": "", "last_time": "", "autoLoad": "1",
                    "orderby": "", "ajax": "1"},
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[webpage] 同花顺财经 API 失败: {e}")
        return []

    raw_list = (data.get("data") or {}).get("list") or data.get("list") or []
    if not raw_list:
        print(f"[webpage] 同花顺财经：响应结构未识别 keys={list(data.keys())}")
        return []

    articles = []
    for item in raw_list:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        raw_id  = str(item.get("id") or hashlib.md5(title.encode()).hexdigest()[:12])
        uid     = "ths_" + raw_id[:12]
        url     = item.get("url") or item.get("link") or ""
        content = (item.get("digest") or item.get("summary") or item.get("content") or "")[:2000]
        summary = content[:100] + ("…" if len(content) > 100 else "")

        ctime = item.get("ctime") or item.get("created_at") or ""
        try:
            if str(ctime).isdigit():
                published_at = datetime.fromtimestamp(int(ctime)).isoformat()
            elif ctime:
                published_at = datetime.fromisoformat(str(ctime)).isoformat()
            else:
                published_at = datetime.now().isoformat()
        except Exception:
            published_at = datetime.now().isoformat()

        articles.append({
            "id":           uid,
            "title":        title,
            "content":      content,
            "content_html": "",
            "summary":      summary,
            "source_type":  "网页",
            "source_sub":   name,
            "url":          url,
            "published_at": published_at,
            "source_label": "网页",
            "topic_label":  "",
            "kb_keywords":  [],
            "kb_matched":   False,
            "kb_snippets":  [],
        })

    print(f"[webpage] 同花顺财经：获取 {len(articles)} 条")
    return articles


def _extract_text(soup: BeautifulSoup) -> str:
    """从 BeautifulSoup 中提取主要正文"""
    for sel in CONTENT_SELECTORS:
        el = soup.select_one(sel)
        if el:
            return el.get_text(separator="\n", strip=True)
    # 降级：取 body 全文
    body = soup.find("body")
    return body.get_text(separator="\n", strip=True) if body else ""


def fetch_url(url: str, name: str = "") -> dict | None:
    """爬取单个URL，返回标准化文章，失败返回 None"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"[webpage] 请求失败 {url}: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    title = soup.title.string.strip() if soup.title else ""
    content = _extract_text(soup)

    if not content:
        return None

    domain = urlparse(url).netloc
    uid = hashlib.md5(url.encode()).hexdigest()[:12]

    return {
        "id":          uid,
        "title":       title,
        "content":     content[:3000],   # 截断超长正文
        "source_type": "网页",
        "source_sub":  name or domain,
        "url":         url,
        "published_at": datetime.now().isoformat(),
    }


def fetch() -> list[dict]:
    """
    读取 sources.json → webpages，爬取所有配置的URL。
    :return: 标准化文章列表
    """
    try:
        sources = json.loads(SOURCES_FILE.read_text())
    except Exception as e:
        print(f"[webpage] 读取 sources.json 失败: {e}")
        return []

    webpages = sources.get("webpages", [])
    if not webpages:
        return []

    articles = []
    for item in webpages:
        url  = item.get("url", "")
        name = item.get("name", "")
        if not url:
            continue
        domain = urlparse(url).netloc
        if "10jqka.com.cn" in domain:
            articles.extend(_fetch_ths(name))
        elif "cls.cn" in domain:
            # 财联社由 cls_telegraph.py 专用 API 爬取，此处跳过避免抓到 JS 空壳页
            print(f"[webpage] 跳过 cls.cn（由财联社电报爬虫专门处理）: {url}")
        else:
            article = fetch_url(url, name)
            if article:
                articles.append(article)

    return articles


if __name__ == "__main__":
    items = fetch()
    print(f"共爬取 {len(items)} 篇")
    for it in items:
        print(f"[{it['source_sub']}] {it['title'][:60]}")
