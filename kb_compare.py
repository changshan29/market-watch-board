"""
kb_compare.py — 甘棠知识库比对

自包含模块，不引用项目一任何代码。
对文章提取关键词，查询甘棠知识库，返回相关内容摘要。
"""

import sys
import re
import json
import time
import requests
from pathlib import Path
from datetime import datetime

# 甘棠知识库凭证
KB_SCRIPTS = Path("/Users/liu/.openclaw/workspace/skills/gangtise-kb/scripts")
sys.path.insert(0, str(KB_SCRIPTS))

try:
    from configure import get_credentials
    from query_kb import get_access_token, query_knowledge
    KB_AVAILABLE = True
except ImportError:
    KB_AVAILABLE = False
    print("[kb_compare] 警告：无法加载知识库模块，KB比对将跳过")

AI_BASE_URL = "https://sz.uyilink.com/v1"
AI_API_KEY  = "sk-wdo3MB4nX555Cy1Lv0tcsLeYRyRUzaNVN7cYYsc9iJivoT6D"
AI_MODEL    = "claude-haiku-4-5-20251001"

RESOURCE_TYPES = [40, 60]   # 分析师观点 + 会议纪要
KB_TOP         = 3
KB_DAYS        = 7


def _ai_call(prompt: str, max_tokens: int = 200) -> str:
    try:
        resp = requests.post(
            f"{AI_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {AI_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": AI_MODEL,
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": max_tokens},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"__ERROR__:{e}"


def extract_keywords(article: dict) -> list[str]:
    """
    从文章中提取公司/行业关键词，用于知识库检索。
    先用简单正则提取，再用AI补充。
    """
    text = f"{article.get('title', '')} {article.get('content', '')}"[:300]

    # 简单规则：提取A股股票名称模式（2-5个汉字+股份/科技/集团等）
    company_pattern = re.compile(
        r'[\u4e00-\u9fa5]{2,5}(?:股份|科技|集团|控股|医药|能源|银行|证券|电子|汽车|地产|建设|'
        r'传媒|文化|网络|信息|资本|投资|基金|保险|通信|农业|钢铁|化工|材料|制造)(?:有限公司|公司)?'
    )
    kws = company_pattern.findall(text)
    # 去除"有限公司"等后缀
    kws = [re.sub(r'有限公司|公司$', '', k) for k in kws]

    # AI补充关键词
    if not kws:
        prompt = (
            f"从以下金融资讯中提取最多2个核心公司或行业关键词（用于知识库检索），"
            f"只输出关键词，用逗号分隔：\n{text}"
        )
        raw = _ai_call(prompt, max_tokens=30)
        if not raw.startswith("__ERROR__"):
            kws = [k.strip() for k in raw.split(",") if k.strip()]

    return list(dict.fromkeys(kws))[:3]   # 去重，最多3个


def query_kb_for_keywords(keywords: list[str], token: str) -> list[dict]:
    """对关键词列表查询知识库，返回合并去重后的条目"""
    if not KB_AVAILABLE or not token or not keywords:
        return []

    seen = set()
    items = []
    for kw in keywords:
        try:
            result = query_knowledge(
                queries=kw,
                resource_types=RESOURCE_TYPES,
                top=KB_TOP,
                days_back=KB_DAYS,
                token=token,
            )
            if not result or result.get("code") != "000000":
                continue
            for qr in result.get("data", []):
                for item in qr.get("data", []):
                    content = item.get("content", "")
                    if content not in seen and len(content) > 50:
                        seen.add(content)
                        ts = item.get("time")
                        items.append({
                            "title":   item.get("title", ""),
                            "date":    datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d") if ts else "",
                            "content": content[:500],
                        })
        except Exception:
            pass
        time.sleep(0.5)
    return items


def compare_article(article: dict, token: str) -> dict:
    """
    对单篇文章进行知识库比对。
    返回：{kb_keywords, kb_matched, kb_snippets}
    """
    kws  = extract_keywords(article)
    items = query_kb_for_keywords(kws, token) if kws else []

    return {
        **article,
        "kb_keywords": kws,
        "kb_matched":  len(items) > 0,
        "kb_snippets": [f"[{it['date']}] {it['title']}: {it['content'][:100]}…"
                        for it in items[:2]],
    }


def compare_batch(articles: list[dict]) -> list[dict]:
    """批量知识库比对"""
    if not KB_AVAILABLE:
        return [{**a, "kb_keywords": [], "kb_matched": False, "kb_snippets": []}
                for a in articles]

    token = get_access_token()
    if not token:
        print("[kb_compare] 获取Token失败，跳过KB比对")
        return [{**a, "kb_keywords": [], "kb_matched": False, "kb_snippets": []}
                for a in articles]

    results = []
    total = len(articles)
    for i, article in enumerate(articles, 1):
        print(f"[kb_compare] [{i}/{total}] {article.get('title', '')[:40]}")
        results.append(compare_article(article, token))
    return results


if __name__ == "__main__":
    test = [
        {"id": "1", "title": "比亚迪发布新款车型", "content": "比亚迪今日发布...",
         "source_type": "财联社", "source_label": "财联社", "topic_label": "个股公司"},
    ]
    results = compare_batch(test)
    for r in results:
        print(f"KB匹配: {r['kb_matched']} 关键词: {r['kb_keywords']}")
