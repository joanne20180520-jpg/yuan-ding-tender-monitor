# 元頂國際控股集團 — 政府標案即時監控系統

> 每 **5 分鐘**自動掃描政府電子採購網，一旦出現符合元頂業務的新標案，立刻寄信通知。

---

## 系統架構

```
GitHub Actions（每 5 分鐘觸發）
        ↓
monitor.py 呼叫 pcc.g0v.ronny.tw API
        ↓
比對元頂業務關鍵字（keywords.py）
        ↓
有命中 → 寄送 HTML 格式 Email 通知
        ↓
更新 seen_tenders.json（避免重複通知）
        ↓
自動 commit 回 GitHub
```

### 為什麼不直接爬政府電子採購網？

| 方式 | 優點 | 缺點 |
|------|------|------|
| 直接爬官網 | 資料最原始 | 容易被封鎖、需處理 JS 渲染 |
| **pcc.g0v.ronny.tw API** | 穩定、免費、JSON 格式乾淨 | 有 1～2 小時同步延遲 |

對於標案監控，1～2 小時的延遲完全可接受（標案截止通常是幾天後），因此選擇 API 方案。

---

## 關鍵字設計（keywords.py）

依元頂集團業務線分類：

| 業務線 | 代表關鍵字（部分）|
|--------|-----------------|
| 室內設計／商空 | 室內裝修、空間規劃、商業空間、軟裝、工程管理 |
| 品牌整合行銷 | 品牌設計、整合行銷、視覺設計、展場設計、短影音 |
| 空調工程 | 空調工程、空調安裝、冷氣工程、機電工程 |
| 進出口貿易／食品通路 | 食品推廣、通路推廣、國產牛肉、進口建材、木地板 |
| 建設營造 | 營造工程、建築工程、修繕工程 |

---

## 快速部署步驟

### 1. Fork 這個 Repository

到 GitHub 點 **Fork**，複製到你自己的帳號底下。

### 2. 設定 Gmail App Password

1. 前往 [Google 帳戶安全性](https://myaccount.google.com/security)
2. 啟用**兩步驟驗證**
3. 搜尋「應用程式密碼」，產生一組新密碼（16 碼）
4. 記下這組密碼

### 3. 設定 GitHub Secrets

在你 Fork 的 repo 中，前往 **Settings → Secrets and variables → Actions → New repository secret**，新增以下三個：

| Secret 名稱 | 說明 | 範例 |
|-------------|------|------|
| `NOTIFY_EMAIL` | 要收到通知的 Email | `yuan@company.com` |
| `GMAIL_USER` | 用來寄信的 Gmail 帳號 | `monitor@gmail.com` |
| `GMAIL_PASS` | 上一步產生的 App Password | `xxxx xxxx xxxx xxxx` |

### 4. 啟用 GitHub Actions

前往 **Actions** 頁籤，點擊 **"I understand my workflows, go ahead and enable them"**。

### 5. 手動測試一次

在 Actions 頁面找到「標案即時監控」，點 **Run workflow** → **Run workflow**，確認執行成功、信箱有收到通知（或 log 顯示「無新的符合標案」）。

完成！之後每 5 分鐘會自動執行。

---

## 自訂關鍵字

編輯 `keywords.py` 的 `KEYWORD_GROUPS`，直接新增或刪除關鍵字即可：

```python
KEYWORD_GROUPS = {
    "室內設計／商空": [
        "室內裝修", "空間規劃",
        "你想新增的關鍵字",   # ← 在這裡加
    ],
    ...
}
```

---

## 檔案結構

```
yuan-ding-tender-monitor/
├── monitor.py              # 主程式
├── keywords.py             # 元頂業務關鍵字設定
├── requirements.txt        # Python 套件
├── seen_tenders.json       # 已通知標案快取（自動生成）
├── README.md               # 說明文件
└── .github/
    └── workflows/
        └── monitor.yml     # GitHub Actions 排程設定
```

---

## Email 通知樣式

每封通知信包含：
- 📌 標案名稱（可直接點擊前往採購網）
- 🏢 招標機關
- 💰 預算金額
- 📅 截止日期
- 🏷 命中的業務線與關鍵字

---

## 技術說明

- **資料來源**：[pcc.g0v.ronny.tw](https://pcc.g0v.ronny.tw/)（g0v 社群整合自政府電子採購網）
- **執行環境**：GitHub Actions（免費）
- **觸發頻率**：每 5 分鐘（GitHub Actions cron 最小間隔）
- **去重機制**：`seen_tenders.json` 記錄已通知的標案 ID，重複出現的標案不會重複發信
- **程式語言**：Python 3.11，僅依賴 `requests` 標準套件
