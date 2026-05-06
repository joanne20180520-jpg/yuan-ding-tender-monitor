#!/usr/bin/env python3
"""
monitor.py v2
元頂國際控股集團 — 政府標案即時監控系統

資料來源：政府電子採購網 XML 開放資料
執行方式：由 GitHub Actions 每 5 分鐘自動觸發
"""

import os
import json
import smtplib
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from keywords import KEYWORD_GROUPS, ALL_KEYWORDS

# ── 設定區 ────────────────────────────────────────────────
SEEN_FILE    = "seen_tenders.json"
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "")
GMAIL_USER   = os.environ.get("GMAIL_USER", "")
GMAIL_PASS   = os.environ.get("GMAIL_PASS", "")

# 政府電子採購網 開放資料 XML endpoint
PCC_XML_URL  = "https://web.pcc.gov.tw/tps/tp/OpenData/exportXML"
# ────────────────────────────────────────────────────────


def fetch_tenders() -> list[dict]:
    """抓取政府電子採購網最新招標公告（XML 開放資料）"""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TenderMonitor/2.0)",
        "Accept": "application/xml, text/xml, */*",
    }
    
    # 抓今天和昨天的資料
    tenders = []
    for days_ago in [0, 1]:
        target = date.today() - timedelta(days=days_ago)
        date_str = target.strftime("%Y%m%d")
        
        params = {
            "tenderType": "TENDER_DECLARATION",  # 招標公告
            "dateType": "isDate",
            "tenderStartDate": date_str,
            "tenderEndDate": date_str,
        }
        
        try:
            resp = requests.get(PCC_XML_URL, params=params, headers=headers, timeout=20)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            
            for item in root.findall(".//tender"):
                tender = {
                    "id": item.findtext("tenderSystemId", ""),
                    "title": item.findtext("tenderName", ""),
                    "unit": item.findtext("orgName", ""),
                    "budget": item.findtext("budget", "—"),
                    "deadline": item.findtext("tenderDeadline", "—"),
                    "url": item.findtext("pkAtmMain", ""),
                }
                tenders.append(tender)
                
            print(f"[INFO] {target.strftime('%Y/%m/%d')} 取得 {len(root.findall('.//tender'))} 筆")
            
        except Exception as e:
            print(f"[ERROR] 抓取 {target} 失敗：{e}")
            # fallback: 用搜尋頁面方式
            tenders.extend(fetch_by_search(date_str))
    
    return tenders


def fetch_by_search(date_str: str) -> list[dict]:
    """備用方案：直接對每個關鍵字搜尋"""
    tenders = []
    headers = {"User-Agent": "Mozilla/5.0 (compatible; TenderMonitor/2.0)"}
    
    # 只搜尋幾個代表性關鍵字避免太多請求
    sample_keywords = ["室內設計", "整合行銷", "空調工程", "食品推廣", "營造工程"]
    
    for kw in sample_keywords:
        try:
            url = "https://web.pcc.gov.tw/tps/pss/tender.do"
            params = {
                "method": "search",
                "searchMode": "common",
                "tenderName": kw,
                "dateType": "isDate",
                "tenderStartDate": f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:]}",
            }
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            # 簡單解析回傳的標案 ID
            content = resp.text
            import re
            ids = re.findall(r'pkAtmMain=([A-Z0-9]+)', content)
            titles = re.findall(r'tenderName=([^&"]+)', content)
            
            for i, tid in enumerate(ids[:5]):
                tenders.append({
                    "id": tid,
                    "title": titles[i] if i < len(titles) else kw + "相關標案",
                    "unit": "—",
                    "budget": "—",
                    "deadline": "—",
                    "url": f"https://web.pcc.gov.tw/tps/pss/tender.do?method=detail&pkAtmMain={tid}",
                })
        except Exception as e:
            print(f"[WARN] 搜尋關鍵字 {kw} 失敗：{e}")
    
    return tenders


def match_keywords(tender: dict) -> list[str]:
    """比對標案名稱與機關名稱，回傳命中的關鍵字清單"""
    text = tender.get("title", "") + " " + tender.get("unit", "")
    return [kw for kw in ALL_KEYWORDS if kw in text]


def classify_hits(hits: list[str]) -> dict:
    """將命中關鍵字對應回業務線"""
    result = {}
    for group_name, kws in KEYWORD_GROUPS.items():
        matched = [kw for kw in hits if kw in kws]
        if matched:
            result[group_name] = matched
    return result


def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen)[-2000:], f, ensure_ascii=False)


def build_email_html(matches: list[dict]) -> str:
    rows = ""
    for item in matches:
        t = item["tender"]
        title    = t.get("title", "（無標題）")
        unit     = t.get("unit", "—")
        budget   = t.get("budget", "—")
        deadline = t.get("deadline", "—")
        url      = t.get("url", "#")
        groups   = "、".join(item["classified"].keys()) if item["classified"] else "其他"
        keywords = "、".join(item["hits"])

        if url and not url.startswith("http"):
            url = f"https://web.pcc.gov.tw/tps/pss/tender.do?method=detail&pkAtmMain={url}"

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
        資料來源：政府電子採購網　|　由元頂標案監控系統自動發送
      </p>
    </body></html>
    """


def send_email(subject: str, html_body: str):
    if not all([NOTIFY_EMAIL, GMAIL_USER, GMAIL_PASS]):
        print("[WARN] Email 設定不完整，略過寄信")
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
    tenders = fetch_tenders()
    print(f"[INFO] 共取得 {len(tenders)} 筆標案，開始比對關鍵字")

    seen    = load_seen()
    matches = []

    for tender in tenders:
        tid = tender.get("id", "") or tender.get("title", "")
        if not tid or tid in seen:
            continue

        hits = match_keywords(tender)
        if not hits:
            continue

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
            m["tender"].get("title", "")[:15] for m in matches[:3]
        )
        subject = f"【元頂標案通知】{len(matches)} 筆新標案 — {title_list}{'...' if len(matches) > 3 else ''}"
        html    = build_email_html(matches)
        send_email(subject, html)
    else:
        print("[INFO] 無新的符合標案，不發送通知")

    save_seen(seen)


if __name__ == "__main__":
    run()
