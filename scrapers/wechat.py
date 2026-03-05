"""
scrapers/wechat.py — 微信公众号爬取

通过搜狗微信（weixin.sogou.com）抓取指定公众号的最新文章。
来源列表读取自 sources.json → wechat。

链接解析：搜狗跳转页中用 JS 拼接真实 mp.weixin.qq.com URL，
用 regex 提取后直接返回，浏览器可直接打开原文。

统一返回格式：
  {id, title, content, source_type="公众号", source_sub=公众号名, url, published_at}
"""

import re
import json
import hashlib
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from bs4 import BeautifulSoup

# 中国时区 UTC+8
CHINA_TZ = timezone(timedelta(hours=8))

SOURCES_FILE = Path(__file__).parent.parent / "sources.json"
SOGOU_SEARCH = "https://weixin.sogou.com/weixin"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://weixin.sogou.com/",
}


def _fetch_article_content(session: requests.Session, url: str) -> tuple[str, str]:
    """
    访问 mp.weixin.qq.com 文章页，提取正文。
    返回 (content_html, content_text)；失败时均返回空串。
    """
    if not url:
        return "", ""
    try:
        r = session.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        content_el = soup.select_one("#js_content") or soup.select_one(".rich_media_content")
        if content_el:
            # 微信用 JS 延迟显示内容，容器带 visibility:hidden/opacity:0，去掉
            content_el.attrs.pop("style", None)
            # 修复微信懒加载：data-src → src（src 可能是 data: 占位 GIF）
            for img in content_el.find_all("img"):
                ds  = img.get("data-src", "")
                src = img.get("src", "")
                if ds and (not src or src.startswith("data:")):
                    img["src"] = ds
            content_html = str(content_el)
            content_text = re.sub(r"\n{3,}", "\n\n",
                                  content_el.get_text(separator="\n", strip=True)).strip()
            return content_html, content_text
    except Exception:
        pass
    return "", ""


def _resolve_url(session: requests.Session, sogou_path: str) -> str:
    """
    访问搜狗跳转页，从 JS 拼接片段中提取真实的 mp.weixin.qq.com URL。
    失败时返回空串。
    """
    if not sogou_path:
        return ""
    link = ("https://weixin.sogou.com" + sogou_path) if sogou_path.startswith("/") else sogou_path
    try:
        r = session.get(link, headers=HEADERS, timeout=10, allow_redirects=False)
        # JS 形如: url += 'https://mp.'; url += 'weixin.qq.c'; ...
        parts = re.findall(r"url \+= '([^']+)'", r.text)
        real_url = "".join(parts).replace("@", "")
        if real_url.startswith("https://mp.weixin.qq.com"):
            return real_url
    except Exception:
        pass
    return ""


def _fetch_account(session: requests.Session, account_name: str, limit: int = 10) -> list[dict]:
    """
    抓取单个公众号的最新文章列表（复用 session 保持 Cookie）。
    """
    params = {
        "type":    "2",
        "query":   account_name,
        "account": account_name,
        "ie":      "utf8",
    }
    try:
        resp = session.get(SOGOU_SEARCH, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"[wechat] {account_name} 请求失败: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    items = soup.select(".news-box li")

    articles = []
    for item in items:
        # 精确匹配来源公众号名
        src_el = item.select_one(".all-time-y2")
        if not src_el or src_el.get_text(strip=True) != account_name:
            continue

        title_el  = item.select_one("h3 a")
        abs_el    = item.select_one("p.txt-info")
        script_el = item.select_one(".s2 script")

        if not title_el:
            continue

        title   = title_el.get_text(strip=True)
        summary = re.sub(r"\s+", " ", abs_el.get_text(strip=True)).strip() if abs_el else ""

        ts_match = re.search(r"timeConvert\('(\d+)'\)", script_el.string or "")
        ts = int(ts_match.group(1)) if ts_match else 0
        published_at = datetime.fromtimestamp(ts, tz=CHINA_TZ).isoformat() if ts else datetime.now(tz=CHINA_TZ).isoformat()

        sogou_path = title_el.get("href", "")
        real_url   = _resolve_url(session, sogou_path)

        uid = hashlib.md5(f"{account_name}:{title}:{ts}".encode()).hexdigest()[:12]

        content_html, content_text = _fetch_article_content(session, real_url) if real_url else ("", summary)

        articles.append({
            "id":           uid,
            "title":        title,
            "content":      content_text or summary,
            "content_html": content_html,
            "source_type":  "公众号",
            "source_sub":   account_name,
            "url":          real_url,
            "published_at": published_at,
        })

        if len(articles) >= limit:
            break

    return articles


def fetch(limit: int = 10) -> list[dict]:
    """读取 sources.json → wechat，抓取所有公众号的最新文章。"""
    try:
        sources = json.loads(SOURCES_FILE.read_text())
    except Exception as e:
        print(f"[wechat] 读取 sources.json 失败: {e}")
        return []

    accounts = sources.get("wechat", [])
    if not accounts:
        return []

    session = requests.Session()
    all_articles = []
    for item in accounts:
        name = item.get("name", "")
        if not name:
            continue
        articles = _fetch_account(session, name, limit=limit)
        print(f"[wechat] {name}: {len(articles)} 条")
        all_articles.extend(articles)

    return all_articles


if __name__ == "__main__":
    items = fetch()
    print(f"\n共 {len(items)} 条：")
    for it in items:
        print(f"  [{it['source_sub']}] [{it['published_at'][:10]}] {it['title'][:50]}")
        print(f"    {it['url'][:80]}")
