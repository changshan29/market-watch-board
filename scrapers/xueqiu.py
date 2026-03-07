"""
scrapers/xueqiu.py — 雪球广场爬取

使用Selenium绕过WAF，获取用户时间线数据。
若 sources.json 配置了指定用户（xueqiu[]），则爬取对应用户时间线。

统一返回格式：
  {id, title, content, source_type="雪球", source_sub=作者名, url, published_at}
"""

import json
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 中国时区 UTC+8
CHINA_TZ = timezone(timedelta(hours=8))

XUEQIU_HOME = "https://xueqiu.com"
SOURCES_FILE = Path(__file__).parent.parent / "sources.json"
STATE_FILE = Path(__file__).parent.parent / "data" / "xueqiu_state.json"  # 记录爬取进度

# 每次爬取的用户数量（可调整）
BATCH_SIZE = 20
STATE_FILE = Path(__file__).parent.parent / "data" / "xueqiu_state.json"  # 记录爬取进度

# 每次爬取的用户数量（可调整）
BATCH_SIZE = 5

# 尝试导入Selenium，如果失败则标记为不可用
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("[xueqiu] Selenium未安装，雪球爬虫不可用")


def _create_driver():
    """创建无头Chrome浏览器"""
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    # 内存优化（适配 Render 512MB 限制）
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-software-rasterizer')
    options.add_argument('--disable-background-networking')
    options.add_argument('--disable-default-apps')
    options.add_argument('--disable-sync')
    options.add_argument('--disable-translate')
    options.add_argument('--hide-scrollbars')
    options.add_argument('--metrics-recording-only')
    options.add_argument('--mute-audio')
    options.add_argument('--no-first-run')
    options.add_argument('--safebrowsing-disable-auto-update')
    options.add_argument('--single-process')  # 单进程模式，减少内存占用
    options.add_argument('--window-size=1280,720')

    # 隐藏webdriver特征
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    try:
        driver = webdriver.Chrome(options=options)
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

                    # 提取时间（从 date-and-source 元素文本或 title 属性）
                    published_at = datetime.now(tz=CHINA_TZ).isoformat()
                    try:
                        time_elem = post.find_element(By.CSS_SELECTOR, "a.date-and-source")
                        # 雪球时间格式：'今天 14:30' / '03-07 14:30' / '2026-03-07' 等
                        time_text = (time_elem.get_attribute("title") or time_elem.text or "").strip()
                        if time_text:
                            now = datetime.now(tz=CHINA_TZ)
                            # 今天 HH:MM
                            m = re.match(r'今天\s+(\d{1,2}):(\d{2})', time_text)
                            if m:
                                published_at = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0).isoformat()
                            else:
                                # MM-DD HH:MM
                                m = re.match(r'(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})', time_text)
                                if m:
                                    published_at = now.replace(month=int(m.group(1)), day=int(m.group(2)),
                                        hour=int(m.group(3)), minute=int(m.group(4)), second=0, microsecond=0).isoformat()
                                else:
                                    # 纯 HH:MM
                                    m = re.match(r'(\d{1,2}):(\d{2})', time_text)
                                    if m:
                                        published_at = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0).isoformat()
                    except:
                        pass

                    articles.append({
                        "id": post_id,
                        "title": title,
                        "content": content[:2000],
                        "content_html": "",
                        "source_type": "雪球",
                        "source_sub": username,
                        "url": url,
                        "published_at": published_at,
                        "source_label": "雪球",
                        "topic_label": "",
                        "summary": content[:100] + ("…" if len(content) > 100 else ""),
                        "kb_keywords": [],
                        "kb_matched": False,
                        "kb_snippets": [],
                    })

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
    # 检查Selenium是否可用
    if not SELENIUM_AVAILABLE:
        print("[xueqiu] Selenium未安装，跳过雪球爬取")
        return []

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
        items = _fetch_user_with_selenium(str(uid), count)

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
