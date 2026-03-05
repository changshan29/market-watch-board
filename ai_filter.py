"""
ai_filter.py — AI 严格相关性筛选（带行业预过滤）

从 stdin 读取 JSON:
  { articles: [{id, title, content, industry_label}], filter_value: str, filter_type: "concept"|"keyword" }

输出 JSON:
  { matched_ids: [...] }

概念筛选流程：
  1. 根据概念映射到对应行业
  2. 先按 industry_label 预过滤
  3. 对预过滤结果进行严格 AI 验证

每批最多 10 条，AI 失败时该批返回空（宁可漏掉，不引入噪音）。
"""

import json
import re
import sys
import requests

AI_BASE_URL = "https://sz.uyilink.com/v1"
AI_API_KEY  = "sk-wdo3MB4nX555Cy1Lv0tcsLeYRyRUzaNVN7cYYsc9iJivoT6D"
AI_MODEL    = "claude-haiku-4-5-20251001"

BATCH_SIZE = 10

# 概念 → 行业映射
CONCEPT_TO_INDUSTRIES = {
    "人工智能":     ["人工智能", "半导体芯片", "云计算", "数字经济"],
    "半导体芯片":   ["半导体芯片", "消费电子"],
    "新能源汽车":   ["新能源汽车", "锂电池", "自动驾驶"],
    "储能":         ["储能", "锂电池", "新能源汽车"],
    "光伏太阳能":   ["光伏太阳能", "新能源汽车"],
    "锂电池":       ["锂电池", "新能源汽车", "储能"],
    "医疗器械":     ["医疗器械", "生物医药"],
    "创新药":       ["创新药", "生物医药"],
    "生物医药":     ["生物医药", "创新药", "基因检测"],
    "基因检测":     ["基因检测", "生物医药"],
    "数字经济":     ["数字经济", "云计算", "人工智能"],
    "云计算":       ["云计算", "数字经济", "人工智能"],
    "网络安全":     ["网络安全", "信创国产化", "数字经济"],
    "信创国产化":   ["信创国产化", "网络安全", "半导体芯片"],
    "军工国防":     ["军工国防", "航天航空", "无人机"],
    "航天航空":     ["航天航空", "军工国防"],
    "无人机":       ["无人机", "军工国防", "航天航空"],
    "消费电子":     ["消费电子", "半导体芯片", "人工智能"],
    "智能制造":     ["智能制造", "工业机器人", "人工智能"],
    "工业机器人":   ["工业机器人", "智能制造", "人工智能"],
    "自动驾驶":     ["自动驾驶", "新能源汽车", "人工智能"],
    "房地产":       ["房地产", "建筑建材"],
    "建筑建材":     ["建筑建材", "房地产"],
    "物业管理":     ["物业管理", "房地产"],
    "银行金融":     ["银行金融", "证券", "保险"],
    "证券":         ["证券", "银行金融"],
    "保险":         ["保险", "银行金融"],
    "期货":         ["期货", "证券", "黄金贵金属"],
    "煤炭能源":     ["煤炭能源", "石油天然气"],
    "石油天然气":   ["石油天然气", "煤炭能源", "化工材料"],
    "化工材料":     ["化工材料", "石油天然气"],
    "钢铁有色":     ["钢铁有色", "黄金贵金属"],
    "黄金贵金属":   ["黄金贵金属", "钢铁有色"],
    "农业食品":     ["农业食品"],
    "游戏传媒":     ["游戏传媒", "数字经济"],
}

SYSTEM_PROMPT = (
    "你是一个严格的金融资讯筛选助手。"
    "你的唯一任务是判断每篇文章是否与给定概念或关键词**实质相关**。\n"
    "【判断原则】\n"
    "- 必须：文章的主题、核心内容或主要论述直接围绕该概念/关键词\n"
    "- 不算：仅在列举、背景描述或一句话中顺带提及\n"
    "- 不算：与该概念有间接、远程或牵强的关联\n"
    "- 原则：宁可漏掉，绝不引入无关内容\n"
    "只输出序号加判断结果，不要解释，不要废话。"
)


def _ai_call(messages: list) -> str:
    try:
        resp = requests.post(
            f"{AI_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {AI_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": AI_MODEL,
                  "messages": messages,
                  "max_tokens": 200,
                  "temperature": 0},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[ai_filter] AI 调用失败: {e}", file=sys.stderr)
        return ""


def _build_messages(articles: list, filter_value: str, filter_type: str) -> list:
    items = "\n".join([
        f"{i+1}. 标题：{a.get('title', '')[:100]}\n   内容：{a.get('content', '')[:250]}"
        for i, a in enumerate(articles)
    ])

    if filter_type == "concept":
        user_content = (
            "概念：「" + filter_value + "」\n\n"
            "判断以下每篇文章是否【主要讲述】与「" + filter_value + "」直接相关的公司、产品、政策或市场动态。\n"
            "要求：文章核心内容必须围绕该概念，不能只是泛泛提及或背景介绍。\n"
            "例如：选择「航天航空」时，只有火箭、卫星、航天器、航空公司等直接相关内容才算，"
            "苹果公司发布新产品、特斯拉电动车等不算。\n\n"
            "文章列表：\n" + items + "\n\n"
            "按序号逐行回答，只写【是】或【否】：\n"
            "1. ?\n2. ?\n（以此类推）"
        )
    else:
        user_content = (
            "关键词：「" + filter_value + "」\n\n"
            "判断以下每篇文章是否以「" + filter_value + "」为【核心话题】或【主要论述对象】。\n"
            "文章必须主要讲的就是该关键词，一笔带过或间接相关的判断为否。\n\n"
            "文章列表：\n" + items + "\n\n"
            "按序号逐行回答，只写【是】或【否】：\n"
            "1. ?\n2. ?\n（以此类推）"
        )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_content},
    ]


def _parse_response(text: str, batch: list) -> list:
    """解析 AI 回复。AI 失败（text 为空）时返回空列表——宁漏勿滥。"""
    if not text:
        return []
    matched = []
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for line in lines:
        m = re.match(r'^(\d+)[\.）、\s]+(.+)', line)
        if m:
            idx    = int(m.group(1)) - 1
            answer = m.group(2).strip()
            is_yes = answer.startswith("是") or answer.startswith("【是】") or answer.lower().startswith("yes")
            if 0 <= idx < len(batch) and is_yes:
                matched.append(batch[idx]["id"])
    return matched


def validate(articles: list, filter_value: str, filter_type: str) -> list:
    # 概念筛选：先按行业预过滤
    if filter_type == "concept":
        target_industries = CONCEPT_TO_INDUSTRIES.get(filter_value, [])
        if target_industries and target_industries != ["其他"]:
            candidates = [
                a for a in articles
                if a.get("industry_label", "其他") in target_industries
            ]
            print(f"[ai_filter] 概念「{filter_value}」→ 行业 {target_industries}，预过滤 {len(articles)} → {len(candidates)} 条",
                  file=sys.stderr)
        else:
            candidates = articles
    else:
        candidates = articles

    if not candidates:
        return []

    matched_ids = []
    for i in range(0, len(candidates), BATCH_SIZE):
        batch    = candidates[i:i + BATCH_SIZE]
        messages = _build_messages(batch, filter_value, filter_type)
        text     = _ai_call(messages)
        ids      = _parse_response(text, batch)
        matched_ids.extend(ids)
        print(f"[ai_filter] 批次 {i//BATCH_SIZE+1}: {len(batch)} 条 → {len(ids)} 条命中", file=sys.stderr)
    return matched_ids


if __name__ == "__main__":
    try:
        data         = json.loads(sys.stdin.read())
        articles     = data.get("articles", [])
        filter_value = data.get("filter_value", "")
        filter_type  = data.get("filter_type", "keyword")
        matched_ids  = validate(articles, filter_value, filter_type)
        print(json.dumps({"matched_ids": matched_ids}))
    except Exception as e:
        print(json.dumps({"matched_ids": [], "error": str(e)}))

