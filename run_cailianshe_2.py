#!/usr/bin/env python3
"""
run_cailianshe_2.py — 财联社项目二一键运行入口

数据流：
  各scraper并发爬取 → classifier AI双标签 → kb_compare知识库比对
  → 合并保存 data/articles.json → POST /api/refresh 通知前端

用法：
  python3 run_cailianshe_2.py             # 完整流程（一次性）
  python3 run_cailianshe_2.py --no-kb     # 跳过知识库比对
  python3 run_cailianshe_2.py --cls-only  # 只爬财联社
  python3 run_cailianshe_2.py --poll-cls  # 财联社电报持续轮询（每5秒）
"""

import sys
import json
import re
import argparse
import requests
from datetime import datetime, timedelta
from pathlib import Path

# 添加项目根目录到路径
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from scrapers.cls_telegraph import fetch as fetch_cls, poll as poll_cls
from scrapers.webpage import fetch as fetch_webpage
from scrapers.xueqiu import fetch as fetch_xueqiu
from scrapers.other import fetch as fetch_other
from classifier import classify_batch
from kb_compare import compare_batch

DATA_DIR     = ROOT / "data"
ARTICLES_FILE = DATA_DIR / "articles.json"
SERVER_URL   = "http://localhost:3220"


def print_step(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ── 标题相似度去重 ─────────────────────────────────────────────────────────────
def _title_bigrams(title: str) -> frozenset:
    """提取标题字符二元组，只保留中文/英文/数字"""
    cleaned = re.sub(r'[^\u4e00-\u9fff\w]', '', title.lower())
    return frozenset(cleaned[i:i+2] for i in range(len(cleaned) - 1)) if len(cleaned) >= 2 else frozenset()


def dedup_similar(articles: list[dict], threshold: float = 0.6) -> list[dict]:
    """
    在 ID 去重之后进一步去除标题高度相似的文章（保留较早出现的那篇）。
    使用字符二元组 Jaccard 相似度，threshold=0.6 表示 60% 重叠视为重复。
    """
    result = []
    seen_bigrams: list[frozenset] = []

    for a in articles:
        bg = _title_bigrams(a.get("title", ""))
        if not bg:
            result.append(a)
            continue
        is_dup = False
        for ebg in seen_bigrams:
            inter = len(bg & ebg)
            union = len(bg | ebg)
            if union and inter / union >= threshold:
                is_dup = True
                break
        if not is_dup:
            result.append(a)
            seen_bigrams.append(bg)

    return result


def run_scrapers(cls_only: bool = False, source_filter: str = None) -> list[dict]:
    """
    并发运行各爬虫
    source_filter: 'webpages', 'xueqiu' 或 None（全部）
    """
    print_step("开始爬取...")

    tasks = {}
    if source_filter == 'webpages':
        tasks["网页"] = fetch_webpage
    elif source_filter == 'xueqiu':
        tasks["雪球"] = fetch_xueqiu
    elif cls_only:
        tasks["财联社电报"] = fetch_cls
    else:
        # 全部来源
        tasks["财联社电报"] = fetch_cls
        tasks["网页"]   = fetch_webpage
        tasks["雪球"]   = fetch_xueqiu
        tasks["其他"]   = fetch_other

    all_articles = []
    for name, fn in tasks.items():
        try:
            items = fn()
            print_step(f"  {name}: {len(items)} 条")
            all_articles.extend(items)
        except Exception as e:
            print_step(f"  {name} 失败: {e}")

    # 去重（按id）
    seen = set()
    unique = []
    for a in all_articles:
        aid = a.get("id", "")
        if aid and aid in seen:
            continue
        seen.add(aid)
        unique.append(a)

    # 去重（标题高度相似）
    before = len(unique)
    unique = dedup_similar(unique)
    removed = before - len(unique)
    if removed:
        print_step(f"  相似去重：移除 {removed} 条高度相似文章")

    print_step(f"爬取完成，共 {len(unique)} 条（去重后）")
    return unique


def save_articles(articles: list[dict], merge: bool = False):
    """
    保存文章到 articles.json。
    始终按 ID 合并：新数据覆盖同 ID 旧数据，不丢弃之前抓到的文章。
    只保留最近 30 天内的文章，防止旧数据无限积累。
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    cutoff = (datetime.now() - timedelta(days=30)).isoformat()

    existing = []
    if ARTICLES_FILE.exists():
        try:
            existing = json.loads(ARTICLES_FILE.read_text())
        except Exception:
            existing = []

    # 以现有数据为基础，用新数据更新/添加（智能合并：保留已有的分类标签）
    existing_map = {a.get("id"): a for a in existing if a.get("id")}
    for article in articles:
        aid = article.get("id")
        if aid:
            # 如果已存在该文章，且新文章是未分类的（快速模式），保留旧的分类标签
            if aid in existing_map:
                old = existing_map[aid]
                new_industry = article.get("industry_label", "其他")
                new_topic = article.get("topic_label", "")
                # 新文章是默认标签 + 旧文章有非默认标签 → 保留旧标签
                if new_industry in ("其他", "") and old.get("industry_label") not in ("其他", ""):
                    article["industry_label"] = old["industry_label"]
                if new_topic in ("其他", "") and old.get("topic_label") not in ("其他", ""):
                    article["topic_label"] = old["topic_label"]
            existing_map[aid] = article

    # 过滤时间窗口 + 排序
    merged = [a for a in existing_map.values() if a.get("published_at", "") >= cutoff]
    merged.sort(key=lambda a: a.get("published_at", ""), reverse=True)

    ARTICLES_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2))
    print_step(f"已保存到 {ARTICLES_FILE}（共 {len(merged)} 条）")


def notify_server():
    try:
        requests.post(f"{SERVER_URL}/api/notify", timeout=5)
        print_step("已通知前端刷新")
    except Exception:
        pass   # server可能未启动，静默忽略


def main():
    parser = argparse.ArgumentParser(description="财联社项目二运行入口")
    parser.add_argument("--no-kb",    action="store_true", help="跳过知识库比对")
    parser.add_argument("--cls-only", action="store_true", help="只爬财联社")
    parser.add_argument("--poll-cls", action="store_true", help="财联社电报持续轮询（每5秒）")
    parser.add_argument("--webpages-only", action="store_true", help="只爬网页")
    parser.add_argument("--xueqiu-only",   action="store_true", help="只爬雪球")
    parser.add_argument("--fast",     action="store_true", help="快速模式：先保存后分类")
    args = parser.parse_args()

    # 轮询模式：持续抓取财联社电报
    if args.poll_cls:
        print_step("=== 财联社电报轮询模式 ===")
        poll_cls()
        return

    print_step("=== 财联社项目二 启动 ===")

    # 确定爬取来源
    source_filter = None
    if args.webpages_only:
        source_filter = 'webpages'
    elif args.xueqiu_only:
        source_filter = 'xueqiu'

    # 1. 爬取
    articles = run_scrapers(cls_only=args.cls_only, source_filter=source_filter)
    if not articles:
        # 单独爬取某个来源时，如果返回0条可能是网络问题，不覆盖现有数据
        if source_filter:
            print_step(f"[{source_filter}] 爬取失败或无新数据，保留现有数据")
        else:
            print_step("无数据，退出")
        return

    # 快速模式：只保存原始数据，跳过AI分类（用于自动刷新）
    if args.fast:
        print_step(f"快速模式：保存 {len(articles)} 条原始数据（跳过AI分类）")

        # 给未分类文章添加默认标签
        for a in articles:
            if 'source_label' not in a:
                a['source_label'] = a.get('source_type', '其他')
            if 'topic_label' not in a:
                a['topic_label'] = '其他'
            if 'industry_label' not in a:
                a['industry_label'] = '其他'
            if 'kb_keywords' not in a:
                a['kb_keywords'] = []
            if 'kb_matched' not in a:
                a['kb_matched'] = False
            if 'kb_snippets' not in a:
                a['kb_snippets'] = []

        # 按发布时间排序
        articles.sort(key=lambda a: a.get("published_at", ""), reverse=True)

        # 保存并通知前端
        use_merge = source_filter is not None
        save_articles(articles, merge=use_merge)
        notify_server()
        print_step(f"=== 快速完成，共处理 {len(articles)} 条 ===")
        return

    # 2. AI双标签分类
    print_step(f"AI分类中（{len(articles)} 条）...")
    articles = classify_batch(articles)
    print_step("分类完成")

    # 3. 知识库比对（可选）
    if not args.no_kb:
        print_step("知识库比对中...")
        articles = compare_batch(articles)
        kb_count = sum(1 for a in articles if a.get("kb_matched"))
        print_step(f"KB比对完成，{kb_count} 条有匹配")
    else:
        articles = [{**a, "kb_keywords": [], "kb_matched": False, "kb_snippets": []}
                    for a in articles]

    # 4. 按发布时间排序（新→旧）
    articles.sort(key=lambda a: a.get("published_at", ""), reverse=True)

    # 5. 保存（单独爬取某个来源时使用合并模式）
    use_merge = source_filter is not None
    save_articles(articles, merge=use_merge)

    # 6. 通知前端
    notify_server()

    print_step(f"=== 完成，共处理 {len(articles)} 条 ===")


if __name__ == "__main__":
    main()
