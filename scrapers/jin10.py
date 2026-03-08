#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
金十数据快讯抓取
API: https://flash-api.jin10.com/get_flash_list
"""
import requests
import json
import sys
from datetime import datetime

def scrape_jin10(max_items=30):
    """抓取金十数据快讯"""
    url = "https://flash-api.jin10.com/get_flash_list"
    params = {
        "channel": "-8200",  # 全部频道
        "vip": "1",
        "size": str(max_items)
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "x-app-id": "bVBF4FyRTn5NJF5n",
        "x-version": "1.0.0"
    }
    
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        data = resp.json()
        
        if data.get("status") != 200 or "data" not in data:
            print(f"[jin10] API error: {data}", file=sys.stderr)
            return []
        
        articles = []
        for item in data["data"]:
            content = item.get("data", {}).get("content", "").strip()
            title = item.get("data", {}).get("title", "").strip()
            
            # 去除 HTML 标签
            import re
            content_text = re.sub(r'<[^>]+>', '', content)
            title_text = re.sub(r'<[^>]+>', '', title) if title else ""
            
            # 标题优先用 title，否则截取 content 前50字
            final_title = title_text if title_text else (content_text[:50] + ('…' if len(content_text) > 50 else ''))
            
            # 时间格式：2026-03-08 23:10:07
            time_str = item.get("time", "")
            try:
                dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                published_at = dt.isoformat() + "+08:00"
            except:
                published_at = datetime.now().isoformat() + "+08:00"
            
            articles.append({
                "id": "jin10_" + item.get("id", ""),
                "title": final_title or "[无标题]",
                "content": content_text[:3000],
                "content_html": content,  # 保留原始 HTML（可能有加粗等格式）
                "source_type": "网页",
                "source_sub": "金十数据",
                "url": "",
                "published_at": published_at,
                "source_label": "网页",
                "topic_label": "其他",
                "summary": content_text[:100],
                "kb_keywords": [],
                "kb_matched": False,
                "kb_snippets": [],
                "industry_label": "其他",
                "important": item.get("important", 0) == 1,
            })
        
        return articles
    
    except Exception as e:
        print(f"[jin10] scrape error: {e}", file=sys.stderr)
        return []

if __name__ == "__main__":
    articles = scrape_jin10(20)
    print(json.dumps(articles, ensure_ascii=False, indent=2))
