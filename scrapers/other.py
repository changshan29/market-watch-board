"""
scrapers/other.py — 其他平台（框架占位）

接口预留，方法签名与其他 scraper 保持一致。
后续接入其他平台时，在此补充实现。
"""

import json
from pathlib import Path

SOURCES_FILE = Path(__file__).parent.parent / "sources.json"


def fetch() -> list[dict]:
    """
    爬取 sources.json → other 中配置的平台内容。
    当前为占位框架，返回空列表。

    TODO: 按平台类型分发不同爬取逻辑
    标准返回格式：
      {id, title, content, source_type="其他", source_sub=平台名, url, published_at}
    """
    try:
        sources = json.loads(SOURCES_FILE.read_text())
    except Exception:
        return []

    platforms = sources.get("other", [])
    if not platforms:
        return []

    # 占位：暂无实现
    print(f"[other] 配置了 {len(platforms)} 个平台，接入逻辑待实现")
    return []
