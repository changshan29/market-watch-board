"""
scrapers/wechat.py — Gmail IMAP 邮件爬取（钉钉群消息通知）

通过 Gmail IMAP 获取钉钉群消息通知邮件，显示在"公众号"区域。
账户配置读取自 sources.json → gmail。

过滤规则：发件人或主题含 dingtalk / dingding / alibaba / 钉钉 关键词。

统一返回格式：
  {id, title, content, source_type="公众号", source_sub=发件人, url, published_at}
"""

import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from bs4 import BeautifulSoup

CHINA_TZ = timezone(timedelta(hours=8))
SOURCES_FILE = Path(__file__).parent.parent / "sources.json"

GMAIL_HOST = "imap.gmail.com"
GMAIL_PORT = 993

# 默认过滤关键词（发件人或主题含其一即视为钉钉通知）
DEFAULT_FILTERS = ["dingtalk", "dingding", "alibaba", "钉钉", "ding talk"]


def _decode_str(value) -> str:
    """解码邮件头部（支持 =?utf-8?...?= 等编码）"""
    if not value:
        return ""
    parts = decode_header(value)
    result = []
    for text, charset in parts:
        if isinstance(text, bytes):
            result.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(str(text))
    return "".join(result)


def _get_body(msg) -> tuple[str, str]:
    """
    提取邮件正文，返回 (content_html, content_text)。
    优先使用纯文本，其次解析 HTML。
    """
    text_body = ""
    html_body = ""

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if "attachment" in cd:
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if ct == "text/plain" and not text_body:
                text_body = decoded
            elif ct == "text/html" and not html_body:
                html_body = decoded
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            ct = msg.get_content_type()
            if ct == "text/html":
                html_body = decoded
            else:
                text_body = decoded

    # 优先返回纯文本
    if text_body:
        cleaned = re.sub(r"\n{3,}", "\n\n", text_body).strip()
        return html_body, cleaned

    # 从 HTML 中提取文本
    if html_body:
        soup = BeautifulSoup(html_body, "html.parser")
        text = re.sub(r"\n{3,}", "\n\n",
                      soup.get_text(separator="\n", strip=True)).strip()
        return html_body, text

    return "", ""


def _is_dingtalk(sender: str, subject: str, filters: list[str]) -> bool:
    """判断是否为钉钉通知邮件"""
    combined = (sender + " " + subject).lower()
    for kw in filters:
        if kw.lower() in combined:
            return True
    return False


def fetch(limit: int = 20) -> list[dict]:
    """通过 Gmail IMAP 获取钉钉群消息通知邮件。"""
    print("[gmail] 开始执行 fetch()...", flush=True)

    try:
        sources = json.loads(SOURCES_FILE.read_text())
    except Exception as e:
        print(f"[gmail] 读取 sources.json 失败: {e}")
        return []

    gmail_cfg = sources.get("gmail", {})
    user = gmail_cfg.get("user", "").strip()
    password = gmail_cfg.get("password", "").replace(" ", "")  # 去除 App Password 中的空格
    filters = gmail_cfg.get("filters", DEFAULT_FILTERS)
    days = gmail_cfg.get("days", 7)  # 抓取最近 N 天的邮件

    if not user or not password:
        print("[gmail] 未配置 gmail.user 或 gmail.password，跳过")
        return []

    # 连接 Gmail IMAP
    print(f"[gmail] 连接 {GMAIL_HOST}...", flush=True)
    try:
        mail = imaplib.IMAP4_SSL(GMAIL_HOST, GMAIL_PORT, timeout=10)
        mail.login(user, password)
        mail.select("INBOX")
        print("[gmail] 连接成功", flush=True)
    except Exception as e:
        print(f"[gmail] 连接/登录 Gmail 失败: {e}")
        return []

    articles = []
    try:
        # 搜索最近 N 天的邮件
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        print(f"[gmail] 搜索 {since_date} 之后的邮件...", flush=True)
        _, data = mail.search(None, f'(SINCE "{since_date}")')
        mail_ids = data[0].split() if data and data[0] else []

        # 倒序（最新优先），最多检查 limit*2 封（减少处理量）
        mail_ids = mail_ids[::-1][: limit * 2]
        print(f"[gmail] 共检索到 {len(mail_ids)} 封近期邮件，开始解析...", flush=True)

        processed = 0
        for mid in mail_ids:
            if len(articles) >= limit:
                break
            try:
                processed += 1
                if processed % 10 == 0:
                    print(f"[gmail] 已处理 {processed}/{len(mail_ids)} 封，匹配 {len(articles)} 条", flush=True)

                _, msg_data = mail.fetch(mid, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                sender  = _decode_str(msg.get("From", ""))
                subject = _decode_str(msg.get("Subject", ""))

                # 仅处理钉钉通知邮件
                if not _is_dingtalk(sender, subject, filters):
                    continue

                # 解析时间
                date_str = msg.get("Date", "")
                try:
                    dt = parsedate_to_datetime(date_str).astimezone(CHINA_TZ)
                    published_at = dt.isoformat()
                except Exception:
                    published_at = datetime.now(tz=CHINA_TZ).isoformat()

                # 提取正文
                content_html, content_text = _get_body(msg)
                if not content_text:
                    content_text = subject

                # 生成唯一ID（发件人+主题+时间）
                uid = hashlib.md5(
                    f"{sender}:{subject}:{date_str}".encode()
                ).hexdigest()[:12]

                # 提取发件人名称（去除邮件地址部分）
                sender_name = re.sub(r"<[^>]+>", "", sender).strip().strip('"')
                if not sender_name:
                    sender_name = sender

                articles.append({
                    "id":           uid,
                    "title":        subject or content_text[:50],
                    "content":      content_text[:3000],
                    "content_html": content_html,
                    "source_type":  "公众号",
                    "source_sub":   sender_name or "钉钉通知",
                    "url":          "",
                    "published_at": published_at,
                })

            except Exception:
                continue

    except Exception as e:
        print(f"[gmail] 搜索邮件失败: {e}")
    finally:
        try:
            mail.close()
            mail.logout()
        except Exception:
            pass

    print(f"[gmail] 获取到 {len(articles)} 封钉钉通知邮件")
    return articles


if __name__ == "__main__":
    items = fetch()
    print(f"\n共 {len(items)} 条：")
    for it in items:
        print(f"  [{it['source_sub']}] [{it['published_at'][:10]}] {it['title'][:60]}")
