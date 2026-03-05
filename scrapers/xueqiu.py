"""
scrapers/xueqiu.py — 雪球广场爬取

通过雪球公开 API 获取广场最新帖子。
若 sources.json 配置了指定用户（xueqiu[]），则爬取对应用户时间线；
否则回退到公开广场时间线。

统一返回格式：
  {id, title, content, source_type="雪球", source_sub=作者名, url, published_at}
"""

import json
import re
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from pathlib import Path

XUEQIU_HOME          = "https://xueqiu.com"
XUEQIU_TIMELINE      = "https://xueqiu.com/v4/statuses/public_timeline_by_category.json"
XUEQIU_USER_TIMELINE = "https://xueqiu.com/v4/statuses/user_timeline.json"
XUEQIU_USER_INFO     = "https://xueqiu.com/statuses/original/show.json"

SOURCES_FILE = Path(__file__).parent.parent / "sources.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://xueqiu.com/",
}


def _make_session() -> requests.Session:
    """请求首页 + hq 页面，获取 xq_a_token 等必要 Cookie。"""
    s = requests.Session()
    try:
        s.get(XUEQIU_HOME, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=20)
        s.get(f"{XUEQIU_HOME}/hq",
              headers={"User-Agent": HEADERS["User-Agent"], "Referer": XUEQIU_HOME},
              timeout=20)
    except Exception as e:
        print(f"[xueqiu] 创建会话失败: {e}")
    return s


def get_user_name(user_id: str) -> str:
    """根据用户ID获取用户昵称"""
    try:
        session = _make_session()
        # 先尝试获取用户的一条帖子，从中提取用户名
        resp = session.get(
            XUEQIU_USER_TIMELINE,
            params={"user_id": user_id, "page": "1", "count": "1", "type": "status"},
            headers=HEADERS,
            timeout=20,  # 增加超时时间
        )
        resp.raise_for_status()
        data = resp.json()
        statuses = data.get("statuses") or data.get("list") or []
        if statuses and len(statuses) > 0:
            user = statuses[0].get("user", {})
            screen_name = user.get("screen_name", "")
            if screen_name:
                return screen_name
        return ""
    except Exception as e:
        print(f"[xueqiu] 获取用户名失败 {user_id}: {e}")
        return ""


def _parse_item(raw: dict) -> dict | None:
    """解析单条雪球帖子（兼容公开广场和用户时间线两种格式）。"""
    # 用户时间线格式：直接在顶层有 id, text, user 等字段
    # 公开广场格式：在 data 字段内
    if "data" in raw and isinstance(raw["data"], (str, dict)):
        data_raw = raw.get("data", {})
        if isinstance(data_raw, str):
            try:
                data = json.loads(data_raw)
            except Exception:
                return None
        else:
            data = data_raw
    else:
        # 用户时间线格式，直接使用 raw
        data = raw

    uid   = str(data.get("id", ""))
    title = (data.get("title") or data.get("topic_title") or "").strip()

    # 用户时间线用 text 字段，公开广场用 description 字段
    html_content = data.get("description") or data.get("text") or ""
    desc  = BeautifulSoup(html_content, "html.parser").get_text()
    desc  = re.sub(r"\s+", " ", desc).strip()

    # 内容：标题 + 正文；若无标题取正文前80字做标题
    if not title and desc:
        title = desc[:40] + ("…" if len(desc) > 40 else "")

    # 用户时间线没有 target，需要自己构造
    target = data.get("target", "")
    if not target and uid:
        target = f"/status/{uid}"
    url = f"https://xueqiu.com{target}" if target.startswith("/") else (target or "")

    user = (data.get("user") or {}).get("screen_name", "雪球用户")

    # 时间：毫秒时间戳
    orig = raw.get("original_status") or {}
    ts_ms = orig.get("created_at") or data.get("created_at") or 0
    if isinstance(ts_ms, int) and ts_ms > 0:
        published_at = datetime.fromtimestamp(ts_ms / 1000).isoformat()
    else:
        published_at = datetime.now().isoformat()

    summary = desc[:100] + ("…" if len(desc) > 100 else "")

    return {
        "id":           uid,
        "title":        title,
        "content":      desc[:2000],
        "content_html": data.get("description", ""),   # 原始 HTML，含图片
        "source_type":  "雪球",
        "source_sub":   user,
        "url":          url,
        "published_at": published_at,
        "source_label": "雪球",
        "topic_label":  "",
        "summary":      summary,
        "kb_keywords":  [],
        "kb_matched":   False,
        "kb_snippets":  [],
    }


def fetch(count: int = 20) -> list[dict]:
    """
    若 sources.json 配置了雪球用户，则爬取用户时间线；
    否则回退到广场公开时间线。
    网络失败时返回空列表，不抛出异常。
    """
    try:
        raw_sources = json.loads(SOURCES_FILE.read_text())
        xq_users = raw_sources.get("xueqiu", [])
    except Exception:
        xq_users = []

    try:
        session = _make_session()
    except Exception as e:
        print(f"[xueqiu] 创建会话失败，跳过本次爬取: {e}")
        return []

    if xq_users:
        articles = []
        valid_users = [u for u in xq_users if u.get("id") or u.get("user_id")]
        for user in valid_users:
            uid = user.get("id") or user.get("user_id")
            items = _fetch_user(session, str(uid), count)
            articles.extend(items)
            print(f"[xueqiu] user {uid}: {len(items)} 条")
        # 有配置但全部无 ID（只填了名字），返回空列表
        if not valid_users:
            print("[xueqiu] 用户均无 ID，请在后台添加用户主页 URL 或数字 ID")
            return []
        return articles
    else:
        # 未配置任何用户，返回空列表
        print("[xueqiu] 未配置用户，请在后台添加")
        return []


def _fetch_user(session: requests.Session, user_id: str, count: int = 20) -> list[dict]:
    """爬取指定用户的时间线。"""
    try:
        resp = session.get(
            XUEQIU_USER_TIMELINE,
            params={"user_id": user_id, "page": "1", "count": str(count), "type": "status"},
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        statuses = data.get("statuses") or data.get("list") or []
        articles = []
        for raw in statuses:
            item = _parse_item(raw)
            if item and item.get("title"):
                articles.append(item)
        return articles
    except Exception as e:
        print(f"[xueqiu] user {user_id} 失败: {e}")
        return []


def _fetch_public(session: requests.Session, count: int = 20) -> list[dict]:
    """爬取广场公开时间线（无指定用户时的回退）。"""
def _fetch_public(session: requests.Session, count: int = 20) -> list[dict]:
    """爬取广场公开时间线（无指定用户时的回退）。"""
    try:
        resp = session.get(
            XUEQIU_TIMELINE,
            params={"since_id": "-1", "max_id": "-1", "count": str(count), "category": "0"},
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[xueqiu] 请求失败: {e}")
        return []

    articles = []
    for raw in data.get("list", []):
        item = _parse_item(raw)
        if item and item["title"]:
            articles.append(item)

    return articles


if __name__ == "__main__":
    items = fetch(10)
    print(f"共 {len(items)} 条：")
    for it in items:
        print(f"  [{it['source_sub']}] [{it['published_at'][11:16]}] {it['title'][:50]}")
        print(f"    {it['url'][:70]}")
