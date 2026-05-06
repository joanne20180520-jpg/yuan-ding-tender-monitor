#!/usr/bin/env python3
"""
monitor.py
元頂國際控股集團 — 政府標案即時監控系統

資料來源：pcc.g0v.ronny.tw（g0v 社群整合自政府電子採購網）
執行方式：由 GitHub Actions 每 5 分鐘自動觸發
"""

import os
import json
import hashlib
import smtplib
import requests
from datetime import datetime, date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from keywords import KEYWORD_GROUPS, ALL_KEYWORDS

# ── 設定區 ────────────────────────────────────────────────
API_BASE      = "https://pcc.g0v.ronny.tw/api"
SEEN_FILE     = "seen_tenders.json"   # 已通知過的標案 ID 快取
NOTIFY_EMAIL  = os.environ.get("NOTIFY_EMAIL", "")   # 收件人，從 GitHub Secret 讀取
GMAIL_USER    = os.environ.get("GMAIL_USER", "")     # 寄件 Gmail 帳號
GMAIL_PASS    = os.environ.get("GMAIL_PASS", "")     # Gmail App Password
# ────────────────────────────────────────────────────────


def fetch_tenders_by_date(target_date: date) -> list[dict]:
    """抓取指定日期的所有招標公告（API 按日期分頁）"""
    tenders = []
    page = 1
    date_str = target_date.strftime("%Y/%m/%d")

    while True:
        url = f"{API_BASE}/listbydate/{target_date.strftime('%Y%m%d')}"
        params = {"page": page}
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[ERROR] 抓取 {date_str} 第 {page} 頁失敗：{e}")
            break

        records = data.get("records", [])
        if not records:
            break

        tenders.extend(records)
        total_pages = data.get("total_page", 1)
        if page >= total_pages:
            break
        page += 1

    print(f"[INFO] {date_str} 共取得 {len(tenders)} 筆標案")
    return tenders


def match_keywords(tender: dict) -> list[str]:
    """
    比對標案名稱與機關名稱，回傳命中的關鍵字清單。
    空清單代表沒有命中。
    """
    text = " ".join([
        tender.get("brief", {}).get("title", ""),
        tender.get("unit_name", ""),
        tender.get("brief", {}).get("category", ""),
    ])

    hits = []
    for kw in ALL_KEYWORDS:
        if kw in text:
            hits.append(kw)
    return hits


def classify_hits(hits: list[str]) -> dict:
    """將命中關鍵字對應回業務線"""
    result = {}
    for group_name, kws in KEYWORD_GROUPS.items():
        matched = [kw for kw in hits if kw in kws]
        if matched:
            result[group_name] = matched
    return result


def load_seen() -> set:
    """載入已通知過的標案 ID"""
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    """儲存已通知的標案 ID（只保留最近 30 天，避免檔案無限增長）"""
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f, ensure_ascii=False)


def tender_id(tender: dict) -> str:
    """產生每筆標案的唯一 ID"""
    pk = tender.get("pk", "")
    if pk:
        return str(pk)
    # fallback：用標案名稱 + 機關名稱 hash
    raw = tender.get("brief", {}).get("title", "") + tender.get("unit_name", "")
    return hashlib.md5(raw.encode()).hexdigest()


def build_email_html(matches: list[dict]) -> str:
    """組裝 HTML 格式的通知信內容"""
    rows = ""
    for item in matches:
        t = item["tender"]
        title    = t.get("brief", {}).get("title", "（無標題）")
        unit     = t.get("unit_name", "—")
        budget   = t.get("brief", {}).get("budget", "—")
        deadline = t.get("brief", {}).get("date", "—")
        url      = f"https://pcc.g0v.ronny.tw/id/{t.get('pk', '')}"
        groups   = "、".join(item["classified"].keys())
        keywords = "、".join(item["hits"])

        rows += f"""
        <tr>
          <td style="padding:12px;border-bottom:1px solid #eee;">
            <strong><a href="{url}" style="color:#1a73e8;text-decoration:none;">{title}</a></strong><br>
            <span style="color:#666;font-size:13px;">🏢 {unit}</span>
          </td>
          <td style="padding:12px;border-bottom:1px solid #eee;color:#444;">{budget}</td>
          <td style="padding:12px;border-bottom:1px solid #eee;color:#444;">{deadline}</td>
          <td style="padding:12px;border-bottom:1px solid #eee;">
            <span style="background:#e8f0fe;color:#1a73e8;padding:3px 8px;border-radius:12px;font-size:12px;">{groups}</span><br>
            <span style="color:#888;font-size:12px;margin-top:4px;display:block;">關鍵字：{keywords}</span>
          </td>
        </tr>
        """

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;max-width:900px;margin:auto;">
      <div style="background:#1a73e8;color:white;padding:20px 24px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">🔔 元頂國際 — 政府標案新通知</h2>
        <p style="margin:6px 0 0;opacity:.85;font-size:14px;">偵測時間：{now}　共 {len(matches)} 筆符合業務的新標案</p>
      </div>
      <table style="width:100%;border-collapse:collapse;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,.08);">
        <thead style="background:#f8f9fa;">
          <tr>
            <th style="padding:12px;text-align:left;font-size:13px;color:#666;">標案名稱 / 機關</th>
            <th style="padding:12px;text-align:left;font-size:13px;color:#666;">預算金額</th>
            <th style="padding:12px;text-align:left;font-size:13px;color:#666;">截止日期</th>
            <th style="padding:12px;text-align:left;font-size:13px;color:#666;">業務線 / 關鍵字</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      <p style="font-size:12px;color:#aaa;margin-top:16px;text-align:center;">
        資料來源：政府電子採購網 × pcc.g0v.ronny.tw　|　由元頂標案監控系統自動發送
      </p>
    </body></html>
    """


def send_email(subject: str, html_body: str):
    """透過 Gmail SMTP 寄送通知信"""
    if not all([NOTIFY_EMAIL, GMAIL_USER, GMAIL_PASS]):
        print("[WARN] Email 設定不完整，略過寄信（請確認 GitHub Secrets 已設定）")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = NOTIFY_EMAIL
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASS)
            server.sendmail(GMAIL_USER, NOTIFY_EMAIL, msg.as_string())
        print(f"[INFO] 通知信已寄出至 {NOTIFY_EMAIL}")
    except Exception as e:
        print(f"[ERROR] 寄信失敗：{e}")


def run():
    today     = date.today()
    yesterday = today - timedelta(days=1)

    # 抓今天 + 昨天（避免跨日邊界漏掉）
    tenders = fetch_tenders_by_date(today) + fetch_tenders_by_date(yesterday)

    seen    = load_seen()
    matches = []

    for tender in tenders:
        tid = tender_id(tender)
        if tid in seen:
            continue  # 已通知過，跳過

        hits = match_keywords(tender)
        if not hits:
            continue  # 不符合業務關鍵字

        classified = classify_hits(hits)
        matches.append({
            "tender":     tender,
            "hits":       hits,
            "classified": classified,
        })
        seen.add(tid)

    if matches:
        print(f"[INFO] 發現 {len(matches)} 筆新符合標案，準備寄信通知")
        title_list = "、".join(
            m["tender"].get("brief", {}).get("title", "")[:15] for m in matches[:3]
        )
        subject = f"【元頂標案通知】{len(matches)} 筆新標案 — {title_list}{'...' if len(matches) > 3 else ''}"
        html    = build_email_html(matches)
        send_email(subject, html)
    else:
        print("[INFO] 無新的符合標案，不發送通知")

    save_seen(seen)


if __name__ == "__main__":
    run()
