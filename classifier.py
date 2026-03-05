"""
classifier.py — AI 三标签分类器

对每篇文章打三类标签：
  - source_label: 网页 / 公众号 / 雪球 / 其它
  - topic_label:  宏观政策 / 行业动态 / 个股公司 / 市场资金 / 其他
  - industry_label: 行业分类（见 INDUSTRY_LABELS）

批量处理，调用AI接口。
"""

import json
import requests
from pathlib import Path

AI_BASE_URL = "https://sz.uyilink.com/v1"
AI_API_KEY  = "sk-wdo3MB4nX555Cy1Lv0tcsLeYRyRUzaNVN7cYYsc9iJivoT6D"
AI_MODEL    = "claude-haiku-4-5-20251001"

SOURCE_LABELS = ["网页", "公众号", "雪球", "其它"]
TOPIC_LABELS  = ["宏观政策", "行业动态", "个股公司", "市场资金", "其他"]

# 行业分类（与A股概念对应）
INDUSTRY_LABELS = [
    "人工智能", "半导体芯片", "新能源汽车", "储能", "光伏太阳能", "锂电池",
    "医疗器械", "创新药", "生物医药", "基因检测",
    "数字经济", "云计算", "网络安全", "信创国产化",
    "军工国防", "航天航空", "无人机",
    "消费电子", "智能制造", "工业机器人", "自动驾驶",
    "房地产", "建筑建材", "物业管理",
    "银行金融", "证券", "保险", "期货",
    "煤炭能源", "石油天然气", "化工材料", "钢铁有色", "黄金贵金属",
    "农业食品", "游戏传媒",
    "其他"
]


def _ai_call(prompt: str, max_tokens: int = 50) -> str:
    try:
        resp = requests.post(
            f"{AI_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {AI_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": AI_MODEL,
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": max_tokens,
                  "temperature": 0},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"__ERROR__:{e}"


def classify_article(article: dict) -> dict:
    """
    对单篇文章打三标签：来源、主题、行业。
    返回原文章 + source_label + topic_label + industry_label + summary。
    """
    src = article.get("source_type", "其他")
    source_label = src if src in SOURCE_LABELS else "其他"

    title   = article.get("title", "")
    content = article.get("content", "")
    text    = f"{title}\n{content}"[:600]

    # 一次调用同时获取主题和行业
    prompt = (
        "请对以下金融资讯打两个标签，严格按格式输出：\n"
        "主题：[从以下选一个：宏观政策、行业动态、个股公司、市场资金、其他]\n"
        "行业：[从以下选一个最相关的：人工智能、半导体芯片、新能源汽车、储能、光伏太阳能、锂电池、"
        "医疗器械、创新药、生物医药、基因检测、数字经济、云计算、网络安全、信创国产化、"
        "军工国防、航天航空、无人机、消费电子、智能制造、工业机器人、自动驾驶、"
        "房地产、建筑建材、物业管理、银行金融、证券、保险、期货、"
        "煤炭能源、石油天然气、化工材料、钢铁有色、黄金贵金属、农业食品、游戏传媒、其他]\n\n"
        f"资讯内容：\n{text}\n\n"
        "只输出两行，格式如下：\n主题：个股公司\n行业：半导体芯片"
    )

    raw = _ai_call(prompt, max_tokens=80)

    topic_label = "其他"
    industry_label = "其他"

    if not raw.startswith("__ERROR__"):
        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        for line in lines:
            if line.startswith("主题：") or line.startswith("主题:"):
                for label in TOPIC_LABELS:
                    if label in line:
                        topic_label = label
                        break
            elif line.startswith("行业：") or line.startswith("行业:"):
                for label in INDUSTRY_LABELS:
                    if label in line:
                        industry_label = label
                        break

    summary = content[:100].replace("\n", " ").strip()
    if len(content) > 100:
        summary += "…"

    return {
        **article,
        "source_label":   source_label,
        "topic_label":    topic_label,
        "industry_label": industry_label,
        "summary":        summary,
    }


def classify_batch(articles: list[dict]) -> list[dict]:
    """批量分类，返回带标签的文章列表"""
    results = []
    total = len(articles)
    for i, article in enumerate(articles, 1):
        print(f"[classifier] [{i}/{total}] {article.get('title', '')[:40]}")
        classified = classify_article(article)
        results.append(classified)
    return results


if __name__ == "__main__":
    test = [
        {"id": "1", "title": "特斯拉与三星磋商AI6芯片产能",
         "content": "消息人士称特斯拉计划就大幅提升AI6芯片产能规模与三星电子磋商，涉及2nm工艺先进制程。",
         "source_type": "网页", "source_sub": "同花顺", "url": "", "published_at": "2024-01-01"},
        {"id": "2", "title": "比特币突破10万美元",
         "content": "比特币价格突破10万美元关口，以太坊、XRP等主流加密货币全线跟涨。",
         "source_type": "网页", "source_sub": "财联社", "url": "", "published_at": "2024-01-01"},
    ]
    results = classify_batch(test)
    for r in results:
        print(f"来源:{r['source_label']} 主题:{r['topic_label']} 行业:{r['industry_label']} — {r['title']}")
