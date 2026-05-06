#!/usr/bin/env python3
"""
monitor.py v5 — Playwright 版（正確網址）
元頂國際控股集團 — 政府標案即時監控系統
"""

import os
import json
import smtplib
import asyncio
from datetime import datetime, date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from playwright.async_api import async_playwright
from keywords import KEYWORD_GROUPS, ALL_KEYWORDS

SEEN_FILE    = "seen_tenders.json"
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "")
GMAIL_USER   = os.environ.get("GMAIL_USER", "")
GMAIL_PASS   = os.environ.get("GMAIL_PASS", "")

SEARCH_KEYWORDS = [
    "室內裝修", "裝潢", "展館設計", "裝潢施工",
    "整合行銷", "品牌設計", "形象展",
    "空調工程", "冷氣工程",
    "食品推廣", "農產品推廣",
    "營造工程", "修繕工程",
]


async def search_tenders(keyword: str, page) -> list[dict]:
    tenders = []
    try:
        today     = date.today().strftime("%Y/%m/%d")
        yesterday = (date.today() - timedelta(days=1)).strftime("%Y/%m/%d")

        # 用正確的搜尋網址，直接帶入關鍵字和日期
        url = (
            f"https://web.pcc.gov.tw/prkms/tender/common/basic/readTenderBasic"
            f"?firstSearch=true&searchType=basic&isBinding=N&isLogIn=N"
            f"&tenderName={keyword}"
            f"&tenderType=TENDER_DECLARATION"
            f"&tenderWay=TENDER_WAY_ALL_DECLARATION"
            f"&dateType=isSpdt"
            f"&tenderStartDate={yesterday.replace('/', '%2F')}"
            f"&tenderEndDate={today.replace('/', '%2F')}"
        )

        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # 抓所有標案列
        rows = await page.query_selector_all("tr.tender-row, table.tb_tnd tr, tbody tr")

        for row in rows:
            try:
                link = await row.query_selector("a")
                if not link:
                    continue
                title = (await link.inner_text()).strip()
                href  = await link.get_attribute("href") or ""
                if href and not href.startswith("http"):
                    href = "https://web.pcc.gov.tw" + href
                cells = await row.query_selector_all("td")
                unit  = (await cells[0].inner_text()).strip() if cells else "—"
                if title and len(title) > 5:
                    tenders.append({
                        "id":       href.split("pkPmsMain=")[-1] if "pkPmsMain=" in href else title[:20],
                        "title":    title,
                        "unit":     unit,
                        "budget":   "—",
                        "deadline": "—",
                        "url":      href or url,
                    })
            except:
                continue

        print(f"[INFO] 關鍵字「{keyword}」找到 {len(tenders)} 筆")

    except Exception as e:
        print(f"[WARN] 搜尋「{keyword}」失敗：{e}")

    return tenders


async def fetch_all_tenders() -> list[dict]:
    all_tenders = []
    seen_ids    = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="zh-TW",
        )
        page = await context.new_page()

        for kw in SEARCH_KEYWORDS:
            results = await search_tenders(kw, page)
            for t in results:
                if t["id"] not in seen_ids:
                    seen_ids.add(t["id"])
                    all_tenders.append(t)
            await asyncio.sleep(1)

        await browser.close()

    print(f"[INFO] 共取得 {len(all_tenders)} 筆不重複標案")
    return all_tenders


def match_keywords(tender):
    text = tender.get("title", "") + " " + tender.get("unit", "")
    return [kw for kw in ALL_KEYWORDS if kw in text]


def classify_hits(hits):
    result = {}
    for group_name, kws in KEYWORD_GROUPS.items():
        matched = [kw for kw in hits if kw in kws]
        if matched:
            result[group_name] = matched
    return result


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen)[-2000:], f, ensure_ascii=False)


def build_email_html(matches):
    rows = ""
    for item in matches:
        t        = item["tender"]
        title    = t.get("title", "（無標題）")
        unit     = t.get("unit", "—")
        budget   = t.get("budget", "—")
        deadline = t.get("deadline", "—")
        url      = t.get("url", "#")
        groups   = "、".join(item["classified"].keys()) if item["classified"] else "其他"
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
        </tr>"""

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<html><body style="font-family:Arial,sans-serif;color:#333;max-width:900px;margin:auto;">
      <div style="background:#1a73e8;color:white;padding:20px 24px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">🔔 元頂國際 — 政府標案新通知</h2>
        <p style="margin:6px 0 0;opacity:.85;font-size:14px;">偵測時間：{now}　共 {len(matches)} 筆符合業務的新標案</p>
      </div>
      <table style="width:100%;border-collapse:collapse;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,.08);">
        <thead style="background:#f8f9fa;"><tr>
          <th style="padding:12px;text-align:left;font-size:13px;color:#666;">標案名稱 / 機關</th>
          <th style="padding:12px;text-align:left;font-size:13px;color:#666;">預算金額</th>
          <th style="padding:12px;text-align:left;font-size:13px;color:#666;">截止日期</th>
          <th style="padding:12px;text-align:left;font-size:13px;color:#666;">業務線 / 關鍵字</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <p style="font-size:12px;color:#aaa;margin-top:16px;text-align:center;">
        資料來源：政府電子採購網　|　由元頂標案監控系統自動發送
      </p>
    </body></html>"""


def send_email(subject, html_body):
    if not all([NOTIFY_EMAIL, GMAIL_USER, GMAIL_PASS]):
        print("[WARN] Email 設定不完整")
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
        print(f"[INFO] ✅ 通知信已寄出至 {NOTIFY_EMAIL}")
    except Exception as e:
        print(f"[ERROR] 寄信失敗：{e}")


def run():
    tenders = asyncio.run(fetch_all_tenders())
    seen    = load_seen()
    matches = []
    for tender in tenders:
        tid = tender.get("id", "")
        if not tid or tid in seen:
            continue
        hits = match_keywords(tender)
        if not hits:
            continue
        matches.append({"tender": tender, "hits": hits, "classified": classify_hits(hits)})
        seen.add(tid)
    if matches:
        print(f"[INFO] 發現 {len(matches)} 筆新符合標案，準備寄信")
        title_list = "、".join(m["tender"].get("title", "")[:15] for m in matches[:3])
        subject    = f"【元頂標案通知】{len(matches)} 筆新標案 — {title_list}{'...' if len(matches) > 3 else ''}"
        send_email(subject, build_email_html(matches))
    else:
        print("[INFO] 無新的符合標案，不發送通知")
    save_seen(seen)


if __name__ == "__main__":
    run()
