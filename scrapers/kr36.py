#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
36氪快讯抓取
URL: https://www.36kr.com/newsflashes/
"""
import requests
import re
import json
import sys
from datetime import datetime
from bs4 import BeautifulSoup

def scrape_36kr(max_items=30):
    """抓取36氪快讯"""
    # 36kr 有 API 接口
    url = "https://www.36kr.com/api/newsflash/home-flow"
    params = {
        "column": "newsflash",
        "category": "newsflash",
        "limit": str(max_items),
        "use_local_time": "0",
        "timezone_offset": "-480"
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.36kr.com/newsflashes/",
        "Accept": "application/json, text/plain, */*",
    }
    
    articles = []
    
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        data = resp.json()
        
        items = []
        # 尝试几种结构
        if isinstance(data, dict):
            items = data.get("data", {}).get("items", []) or \
                    data.get("data", {}).get("results", []) or \
                    data.get("items", []) or []
        elif isinstance(data, list):
            items = data
            
        if items:
            for item in items[:max_items]:
                # 36kr 快讯字段
                item_id = str(item.get("id", item.get("itemId", "")))
                title = item.get("title", item.get("itemTitle", "")).strip()
                content = item.get("description", item.get("summary", "")).strip()
                published_at_raw = item.get("publishTime", item.get("created_at", ""))
                
                # 时间转换
                try:
                    if isinstance(published_at_raw, (int, float)):
                        dt = datetime.fromtimestamp(published_at_raw / 1000)
                    else:
                        dt = datetime.fromisoformat(str(published_at_raw))
                    published_at = dt.isoformat() + "+08:00"
                except:
                    published_at = datetime.now().isoformat() + "+08:00"
                
                final_title = title or (content[:50] + ('…' if len(content) > 50 else '')) or "[无标题]"
                
                articles.append({
                    "id": "36kr_" + item_id,
                    "title": final_title,
                    "content": content[:3000],
                    "content_html": f"<p>{content}</p>",
                    "source_type": "网页",
                    "source_sub": "36氪快讯",
                    "url": f"https://www.36kr.com/newsflashes/{item_id}" if item_id else "",
                    "published_at": published_at,
                    "source_label": "网页",
                    "topic_label": "其他",
                    "summary": content[:100],
                    "kb_keywords": [],
                    "kb_matched": False,
                    "kb_snippets": [],
                    "industry_label": "其他",
                })
    except Exception as e:
        print(f"[36kr] API failed: {e}, falling back to HTML", file=sys.stderr)
        items = []
    
    # Fallback: HTML 解析
    if not articles:
        try:
            resp = requests.get("https://www.36kr.com/newsflashes/", headers=headers, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            
            for el in soup.select(".newsflash-item")[:max_items]:
                title_el = el.select_one(".item-title")
                time_el = el.select_one(".time")
                
                if not title_el:
                    continue
                
                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                item_id = href.rstrip("/").split("/")[-1] if href else ""
                url_full = f"https://www.36kr.com{href}" if href else ""
                
                # 时间处理（"X小时前"格式）
                published_at = datetime.now().isoformat() + "+08:00"
                
                articles.append({
                    "id": "36kr_" + (item_id or title[:20].replace(" ", "_")),
                    "title": title,
                    "content": title,
                    "content_html": f"<p>{title}</p>",
                    "source_type": "网页",
                    "source_sub": "36氪快讯",
                    "url": url_full,
                    "published_at": published_at,
                    "source_label": "网页",
                    "topic_label": "其他",
                    "summary": title[:100],
                    "kb_keywords": [],
                    "kb_matched": False,
                    "kb_snippets": [],
                    "industry_label": "其他",
                })
        except Exception as e:
            print(f"[36kr] HTML fallback error: {e}", file=sys.stderr)
    
    return articles

if __name__ == "__main__":
    articles = scrape_36kr(20)
    print(f"获取到 {len(articles)} 条", file=sys.stderr)
    for a in articles[:3]:
        print(f"  [{a['id']}] {a['title'][:60]}", file=sys.stderr)
    print(json.dumps(articles, ensure_ascii=False, indent=2))
