"""
scrapers/xueqiu.py — 雪球广场爬取

优先使用 HTTP API（无需浏览器），失败时退回 Selenium。
若 sources.json 配置了指定用户（xueqiu[]），则爬取对应用户时间线。

统一返回格式：
  {id, title, content, source_type="雪球", source_sub=作者名, url, published_at}
"""

import json
import re
import time
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 中国时区 UTC+8
CHINA_TZ = timezone(timedelta(hours=8))

XUEQIU_HOME = "https://xueqiu.com"
SOURCES_FILE = Path(__file__).parent.parent / "sources.json"
STATE_FILE = Path(__file__).parent.parent / "data" / "xueqiu_state.json"  # 记录爬取进度

# 每次爬取的用户数量（可调整）
BATCH_SIZE = 5

# API 请求头
_API_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://xueqiu.com/',
}

# 尝试导入Selenium，如果失败则标记为不可用
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("[xueqiu] Selenium未安装，雪球爬虫不可用")


def _make_article(post_id, content, username, user_id, published_at, url=None):
    title = content[:40] + ("…" if len(content) > 40 else "")
    return {
        "id": str(post_id),
        "title": title,
        "content": content[:2000],
        "content_html": "",
        "source_type": "雪球",
        "source_sub": username,
        "url": url or f"https://xueqiu.com/u/{user_id}",
        "published_at": published_at,
        "source_label": "雪球",
        "topic_label": "",
        "summary": content[:100] + ("…" if len(content) > 100 else ""),
        "kb_keywords": [],
        "kb_matched": False,
        "kb_snippets": [],
    }


def _fetch_user_with_api(user_id: str, count: int = 20) -> list[dict]:
    """使用雪球 JSON API 获取用户时间线（无需 Selenium）"""
    session = requests.Session()
    session.headers.update(_API_HEADERS)

    try:
        # 先访问主页，获取 cookie（xq_a_token）
        session.get("https://xueqiu.com/", timeout=15)
        time.sleep(1)

        resp = session.get(
            "https://xueqiu.com/v4/statuses/user_timeline.json",
            params={"user_id": user_id, "page": 1, "count": count, "type": ""},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        statuses = data.get("statuses", [])
        if not statuses:
            print(f"[xueqiu-api] user {user_id}: 返回空列表（可能需要登录或已被限流）")
            return []

        articles = []
        username = "雪球用户"

        for status in statuses:
            try:
                # 用户名
                u = status.get("user") or {}
                if u.get("screen_name"):
                    username = u["screen_name"]

                # 内容
                raw = status.get("text") or status.get("description") or ""
                content = re.sub(r"<[^>]+>", " ", raw).strip()
                content = re.sub(r"\s+", " ", content).strip()
                if not content or len(content) < 5:
                    continue

                # 时间（created_at 为毫秒时间戳）
                created_ms = status.get("created_at") or 0
                if created_ms:
                    published_at = datetime.fromtimestamp(
                        created_ms / 1000, tz=CHINA_TZ
                    ).isoformat()
                else:
                    published_at = datetime.now(tz=CHINA_TZ).isoformat()

                # URL
                target = status.get("target") or ""
                post_url = (
                    f"https://xueqiu.com{target}"
                    if target.startswith("/")
                    else (target or f"https://xueqiu.com/u/{user_id}")
                )
                post_id = str(status.get("id") or abs(hash(content)))

                articles.append(_make_article(post_id, content, username, user_id, published_at, post_url))
            except Exception:
                continue

        return articles

    except Exception as e:
        print(f"[xueqiu-api] user {user_id} 失败: {e}")
        return []


def _parse_time_text(time_text: str) -> str:
    """解析雪球时间文本为 ISO 字符串，覆盖所有已知格式"""
    now = datetime.now(tz=CHINA_TZ)
    t = time_text.strip()
    if not t:
        return now.isoformat()

    # 刚刚
    if "刚刚" in t:
        return now.isoformat()
    # N分钟前
    m = re.search(r'(\d+)\s*分钟前', t)
    if m:
        return (now - timedelta(minutes=int(m.group(1)))).isoformat()
    # N小时前
    m = re.search(r'(\d+)\s*小时前', t)
    if m:
        return (now - timedelta(hours=int(m.group(1)))).isoformat()
    # N天前
    m = re.search(r'(\d+)\s*天前', t)
    if m:
        return (now - timedelta(days=int(m.group(1)))).isoformat()
    # N周前
    m = re.search(r'(\d+)\s*周前', t)
    if m:
        return (now - timedelta(weeks=int(m.group(1)))).isoformat()
    # N月前（近似30天）
    m = re.search(r'(\d+)\s*月前', t)
    if m:
        return (now - timedelta(days=int(m.group(1)) * 30)).isoformat()
    # 今天 HH:MM
    m = re.search(r'今天\s+(\d{1,2}):(\d{2})', t)
    if m:
        return now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0).isoformat()
    # 昨天 HH:MM 或 昨天
    m = re.search(r'昨天\s*(\d{1,2})?:?(\d{2})?', t)
    if m and '昨天' in t:
        d = now - timedelta(days=1)
        if m.group(1) and m.group(2):
            return d.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0).isoformat()
        return d.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    # YYYY-MM-DD HH:MM[:SS]
    m = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})', t)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                            int(m.group(4)), int(m.group(5)), tzinfo=CHINA_TZ).isoformat()
        except Exception:
            pass
    # YYYY年MM月DD日 HH:MM（带时间）
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})', t)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                            int(m.group(4)), int(m.group(5)), tzinfo=CHINA_TZ).isoformat()
        except Exception:
            pass
    # MM月DD日 HH:MM（当年）
    m = re.search(r'(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})', t)
    if m:
        try:
            candidate = now.replace(month=int(m.group(1)), day=int(m.group(2)),
                                    hour=int(m.group(3)), minute=int(m.group(4)),
                                    second=0, microsecond=0)
            if candidate > now:
                candidate = candidate.replace(year=now.year - 1)
            return candidate.isoformat()
        except Exception:
            pass
    # YYYY年MM月DD日（仅日期）
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', t)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                            tzinfo=CHINA_TZ).isoformat()
        except Exception:
            pass
    # MM月DD日（仅日期，当年）
    m = re.search(r'(\d{1,2})月(\d{1,2})日', t)
    if m:
        try:
            candidate = now.replace(month=int(m.group(1)), day=int(m.group(2)),
                                    hour=0, minute=0, second=0, microsecond=0)
            if candidate > now:
                candidate = candidate.replace(year=now.year - 1)
            return candidate.isoformat()
        except Exception:
            pass
    # MM-DD HH:MM（当年）
    m = re.search(r'(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})', t)
    if m:
        try:
            candidate = now.replace(month=int(m.group(1)), day=int(m.group(2)),
                                    hour=int(m.group(3)), minute=int(m.group(4)),
                                    second=0, microsecond=0)
            if candidate > now:
                candidate = candidate.replace(year=now.year - 1)
            return candidate.isoformat()
        except Exception:
            pass
    # HH:MM（今天）
    m = re.search(r'\b(\d{1,2}):(\d{2})\b', t)
    if m:
        return now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0).isoformat()

    print(f"[xueqiu] 无法解析时间文本: {repr(t)}")
    return now.isoformat()


def _create_driver():
    """创建无头Chrome浏览器"""
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    # 内存优化（适配 Railway/Render 512MB 限制）
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-software-rasterizer')
    options.add_argument('--disable-background-networking')
    options.add_argument('--disable-default-apps')
    options.add_argument('--disable-sync')
    options.add_argument('--disable-translate')
    options.add_argument('--hide-scrollbars')
    options.add_argument('--mute-audio')
    options.add_argument('--no-first-run')
    options.add_argument('--safebrowsing-disable-auto-update')
    options.add_argument('--window-size=1280,720')
    options.add_argument('--memory-pressure-off')
    options.add_argument('--js-flags=--max-old-space-size=256')

    # 隐藏webdriver特征
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    try:
        # 使用 apt 安装的 chromium + chromedriver（路径固定，无需外网下载）
        service = Service('/usr/bin/chromedriver')
        options.binary_location = '/usr/bin/chromium'
        driver = webdriver.Chrome(service=service, options=options)
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
        })
        return driver
    except Exception as e:
        print(f"[xueqiu] 创建浏览器失败: {e}")
        return None


def _fetch_user_with_selenium(user_id: str, count: int = 20) -> list[dict]:
    """使用Selenium获取用户时间线"""
    driver = _create_driver()
    if not driver:
        return []

    try:
        # 访问用户主页
        url = f"{XUEQIU_HOME}/u/{user_id}"
        driver.get(url)

        # 等待页面加载完成
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".timeline__item")))
        time.sleep(3)

        # 提取用户名（优先从页面元素，其次从标题）
        username = "雪球用户"
        try:
            # 方法1：从页面中的用户名元素提取
            name_elem = driver.find_element(By.CSS_SELECTOR, ".user-name")
            username = name_elem.text.strip()
        except:
            try:
                # 方法2：从页面标题提取（格式："用户名 - 雪球"）
                title = driver.title
                # 支持多种分隔符
                for sep in [" - ", " — ", "-", "—"]:
                    if sep in title:
                        username = title.split(sep)[0].strip()
                        break
            except:
                pass

        # 滚动加载更多内容
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)

        # 解析帖子
        articles = []
        try:
            posts = driver.find_elements(By.CSS_SELECTOR, ".timeline__item")

            for post in posts[:count]:
                try:
                    # 提取内容（使用innerText属性更可靠）
                    content = ""
                    try:
                        content_elem = post.find_element(By.CSS_SELECTOR, ".content")
                        content = content_elem.get_attribute("innerText") or content_elem.text
                        content = content.strip()
                    except:
                        pass

                    if not content or len(content) < 5:
                        continue

                    # 生成标题
                    title = content[:40] + ("…" if len(content) > 40 else "")

                    # 提取链接和ID
                    try:
                        link_elem = post.find_element(By.CSS_SELECTOR, "a.date-and-source")
                        href = link_elem.get_attribute("href")
                        # 提取帖子ID（格式：/用户ID/帖子ID）
                        match = re.search(r'/(\d+)$', href)
                        post_id = match.group(1) if match else str(abs(hash(content)))[:12]
                        url = href if href.startswith("http") else f"https://xueqiu.com{href}"
                    except:
                        post_id = str(abs(hash(content)))[:12]
                        url = f"https://xueqiu.com/u/{user_id}"

                    # 提取时间
                    published_at = datetime.now(tz=CHINA_TZ).isoformat()
                    try:
                        time_elem = post.find_element(By.CSS_SELECTOR, "a.date-and-source")
                        raw_title = time_elem.get_attribute("title") or ""
                        raw_text  = time_elem.text or ""
                        raw_inner = time_elem.get_attribute("innerText") or ""
                        time_text = (raw_title or raw_text or raw_inner).strip()

                        if not time_text:
                            # 时间元素为空，用 JS 在帖子内搜索所有含 HH:MM 的文本节点
                            found = driver.execute_script("""
                                var el = arguments[0];
                                var texts = [];
                                var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false);
                                var node;
                                while (node = walker.nextNode()) {
                                    var t = node.textContent.trim();
                                    if (t.match(/\\d{1,2}:\\d{2}/)) texts.push(t);
                                }
                                return texts;
                            """, post)
                            if found:
                                time_text = found[0].strip()
                                print(f"[xueqiu] JS找到时间文本: {repr(time_text)}")
                            else:
                                outer = time_elem.get_attribute("outerHTML") or ""
                                print(f"[xueqiu] 时间元素为空，outerHTML={repr(outer[:300])}")

                        published_at = _parse_time_text(time_text)
                    except Exception as te:
                        print(f"[xueqiu] 时间解析失败: {te}")

                    articles.append(_make_article(post_id, content, username, user_id, published_at, url))

                except Exception as e:
                    continue

        except Exception as e:
            print(f"[xueqiu] 解析帖子失败: {e}")

        return articles

    except Exception as e:
        print(f"[xueqiu] 访问用户 {user_id} 失败: {e}")
        return []
    finally:
        driver.quit()


def _load_state() -> dict:
    """加载爬取进度"""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_index": 0}


def _save_state(state: dict):
    """保存爬取进度"""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"[xueqiu] 保存进度失败: {e}")


def fetch(count: int = 20) -> list[dict]:
    """
    若 sources.json 配置了雪球用户，则爬取用户时间线。
    网络失败时返回空列表，不抛出异常。
    """
    try:
        raw_sources = json.loads(SOURCES_FILE.read_text())
        xq_users = raw_sources.get("xueqiu", [])
    except Exception:
        xq_users = []

    if not xq_users:
        print("[xueqiu] 未配置用户，请在后台添加")
        return []

    # 加载爬取进度
    state = _load_state()
    last_index = state.get("last_index", 0)

    articles = []
    valid_users = [u for u in xq_users if u.get("id") or u.get("user_id")]
    total_users = len(valid_users)

    if total_users == 0:
        print("[xueqiu] 用户均无 ID，请在后台添加用户主页 URL 或数字 ID")
        return []

    # 计算本次要爬取的用户范围
    start_index = last_index
    end_index = min(start_index + BATCH_SIZE, total_users)
    batch_users = valid_users[start_index:end_index]

    print(f"[xueqiu] 分批爬取：第 {start_index + 1}-{end_index} 个用户（共 {total_users} 个）")

    sources_updated = False

    for user in batch_users:
        uid = user.get("id") or user.get("user_id")

        # 直接用 Selenium（API 被雪球 WAF 拦截，云服务器 IP 无法访问）
        if SELENIUM_AVAILABLE:
            items = _fetch_user_with_selenium(str(uid), count)
        else:
            print("[xueqiu] Selenium不可用，跳过")
            items = []

        # 如果获取到文章且用户名为空，自动更新用户名
        if items and not user.get("name"):
            username = items[0].get("source_sub", "")
            if username and username != "雪球用户":
                user["name"] = username
                sources_updated = True
                print(f"[xueqiu] 自动更新用户名: {uid} -> {username}")

        articles.extend(items)
        print(f"[xueqiu] user {uid}: {len(items)} 条")

    # 更新进度：如果已经爬完所有用户，重置为 0
    next_index = end_index if end_index < total_users else 0
    state["last_index"] = next_index
    _save_state(state)

    print(f"[xueqiu] 下次将从第 {next_index + 1} 个用户开始")

    # 保存更新后的 sources.json
    if sources_updated:
        try:
            raw_sources["xueqiu"] = xq_users
            SOURCES_FILE.write_text(json.dumps(raw_sources, ensure_ascii=False, indent=2))
            print("[xueqiu] 已更新 sources.json 中的用户名")
        except Exception as e:
            print(f"[xueqiu] 更新 sources.json 失败: {e}")

    return articles


if __name__ == "__main__":
    items = fetch(10)
    print(f"共 {len(items)} 条：")
    for it in items:
        print(f"  [{it['source_sub']}] {it['title'][:50]}")
        print(f"    {it['url'][:70]}")
