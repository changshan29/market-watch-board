"""
scrapers/cls_telegraph.py — 财联社电报/快讯爬取

API: https://www.cls.cn/nodeapi/telegraphList
每次返回最新20条，字段：id, title, content, ctime, level, shareurl

fetch()  — 一次性抓取最新 N 条
poll()   — 每5秒轮询，新条目实时追加到 data/articles.json
"""

import json
import re
import time
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 中国时区 UTC+8
CHINA_TZ = timezone(timedelta(hours=8))

API_URL = "https://www.cls.cn/nodeapi/telegraphList"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/114.0.0.0 Safari/537.36"
    )
}

DATA_FILE = Path(__file__).parent.parent / "data" / "articles.json"
POLL_INTERVAL = 5   # 秒

# 财联社 API 中偶尔出现的版块聚合标题前缀，不是真正的文章标题
_SECTION_PREFIXES = (
    "财联社A股24小时电报",
    "财联社A股每日电报",
    "财联社早报",
    "财联社午报",
    "财联社晚报",
)


def _resolve_title(title: str, content: str) -> str:
    """
    处理两种情况：
    1. title 是版块聚合名（如"财联社A股24小时电报-..."），
       从 content 中提取第一个【真实标题】。
    2. title 以【版块名】开头（如"【财联社早知道】..."），
       去掉【...】前缀，保留后面的真实标题。
    """
    for prefix in _SECTION_PREFIXES:
        if title.startswith(prefix):
            m = re.search(r'【([^】]{4,60})】', content)
            if m:
                return m.group(1).strip()
            # 尝试取第一条 ①... 作为标题
            m2 = re.search(r'[①②③④⑤⑥⑦⑧⑨⑩](.{4,40}?)(?=[①②③④⑤⑥⑦⑧⑨⑩]|$)', content)
            if m2:
                return m2.group(1).strip()
            # 最后兜底：去掉版块前缀后的剩余部分
            remainder = re.sub(r'^.+?电报[-—·\s]*', '', title).strip()
            return remainder if remainder else title

    # 去掉开头的【...】列名前缀（如【财联社早知道】、【财联社焦点】）
    m = re.match(r'^【([^】]{2,10})】(.+)', title)
    if m:
        return m.group(2).strip()

    return title


def _raw_to_article(item: dict) -> dict:
    ts = item.get("ctime", 0)
    published_at = datetime.fromtimestamp(ts, tz=CHINA_TZ).isoformat() if ts else ""
    raw_title = item.get("title", "") or item.get("brief", "")
    content   = item.get("content", "") or item.get("brief", "")
    title     = _resolve_title(raw_title, content)
    # 去掉content开头的【标题】重复部分
    if content.startswith("【") and "】" in content:
        bracket_end = content.index("】") + 1
        if title and content[bracket_end:].strip().startswith(title[:5]):
            content = content[bracket_end:].strip()
    return {
        "id":           str(item.get("id", "")),
        "title":        title,
        "content":      content,
        "source_type":  "网页",
        "source_sub":   "财联社电报",
        "level":        item.get("level", ""),   # A=重要 B=一般
        "url":          item.get("shareurl", ""),
        "published_at": published_at,
        "source_label": "网页",
        "topic_label":  "",
        "summary":      content[:100] + ("…" if len(content) > 100 else ""),
        "kb_keywords":  [],
        "kb_matched":   False,
        "kb_snippets":  [],
    }


def fetch(limit: int = 20) -> list[dict]:
    """一次性获取最新电报，返回标准化文章列表"""
    try:
        resp = requests.get(API_URL, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        roll_data = resp.json().get("data", {}).get("roll_data", [])
    except Exception as e:
        print(f"[cls_telegraph] 请求失败: {e}")
        return []

    return [_raw_to_article(it) for it in roll_data[:limit]]


def _load_articles() -> list[dict]:
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_articles(articles: list[dict]):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(
        json.dumps(articles, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def poll(on_new=None):
    """
    每5秒轮询一次财联社电报。
    新条目实时追加到 data/articles.json，并回调 on_new(new_articles)。
    :param on_new: 可选回调，接收新文章列表
    """
    print(f"[cls_telegraph] 开始轮询，每 {POLL_INTERVAL} 秒一次...")
    seen_ids: set[str] = {a["id"] for a in _load_articles()}

    while True:
        try:
            resp = requests.get(API_URL, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            roll_data = resp.json().get("data", {}).get("roll_data", [])
        except Exception as e:
            print(f"[cls_telegraph] 请求失败: {e}")
            time.sleep(POLL_INTERVAL)
            continue

        new_articles = []
        for item in roll_data:
            aid = str(item.get("id", ""))
            if aid and aid not in seen_ids:
                seen_ids.add(aid)
                new_articles.append(_raw_to_article(item))

        if new_articles:
            ts_now = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts_now}] 新增 {len(new_articles)} 条")
            for a in new_articles:
                print(f"  [{a['published_at'][11:16]}] {a['title'][:60]}")

            # 追加到 articles.json（新条目放前面，保持新→旧顺序）
            existing = _load_articles()
            merged = new_articles + existing
            _save_articles(merged)

            if on_new:
                on_new(new_articles)
        else:
            ts_now = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts_now}] 无新条目")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    import sys
    if "--poll" in sys.argv:
        poll()
    else:
        items = fetch(20)
        print(f"共 {len(items)} 条：")
        for it in items:
            lv = f"[{it['level']}]" if it["level"] else ""
            print(f"  {lv} [{it['published_at'][11:16]}] {it['title'][:60]}")
