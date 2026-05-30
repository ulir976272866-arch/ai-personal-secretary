# 🚀 AI 個人秘書系統 (AI Personal Secretary) 核心架構與業務邏輯懶人包

本指南（懶人包）為本專案的**終極開發架構交接說明書**。當您在未來的對話中將此檔案提供給任何 AI 助理時，該助理將能在一秒內完全理解本專案的代碼組織、數據模型與業務邏輯，並直接進入高效開發狀態！

---

## 📅 專案概觀 (Project Overview)
本專案是一款**基於 PWA（漸進式網頁應用）架構開發的超高級莫蘭迪粉美學個人秘書系統**。其核心理念為 **「前端極致美學互動 + 後端 TiDB 雲端資料庫 + 雲端 Google Sheets 備份同步 + Gemini 智慧助理」**。

---

## 📂 1. 程式碼目錄結構與重要檔案解析

```bash
ai-personal-secretary/
├── app.py                      # 核心後端：Flask 路由、Google APIs、TiDB、Gemini 整合
├── requirements.txt            # Python 依賴包
├── service_account.json        # Google 服務帳戶憑證 ( sheets/calendar 讀寫 )
├── .env                        # 環境變數設定檔 (TiDB 密碼, API Keys 等)
├── templates/
│   ├── index.html              # 主畫面前端：單頁 PWA、所有功能 Modal 彈窗與 HTML5 架構
│   └── checkout.html           # 結帳與會員升級 UI (Morandi 風格)
└── static/
    ├── css/
    │   └── style.css           # 樣式控制：莫蘭迪配色系統、毛玻璃、CSS 動畫
    ├── js/
    │   ├── app.js              # 前端邏輯：AJAX 請求、互動 Modal、圖表、Google Maps
    │   └── sw.js               # PWA 服務線程：快取與離線運作支援
    └── manifest.json           # PWA 行動裝置配置檔
```

### 🔑 核心三大檔案分工
1. **`app.py` (270KB+)**：集成了所有的 API 路由。負責與 TiDB（股票、訂閱數據）以及 Google Sheets（日常記帳、備忘、生理期）進行數據讀寫，並包含背景非同步自癒線程。
2. **`templates/index.html` (160KB+)**：前端主要界面，採用極簡單頁面（SPA）與複數彈窗（Modal Drawer）設計，確保移動端宛如 Native APP 的流暢度。
3. **`static/js/app.js` (310KB+)**：包含整個前端的控制邏輯。包括日曆生成、記帳動態載入、TiDB 股票數據即時查詢、AI 語音互動反饋等。

---

## ⚙️ 2. 八大核心業務模組架構

### ① 🌸 生理健康助理 (Menstrual Health Assistant)
* **雙核心雲端結構**：
  * `生理紀錄` 工作表：記錄經期的「開始」與「結束」時間，計算經期規律。
  * `生理症狀紀錄` 工作表：獨立儲存每日的身體感受（經痛、頭痛、疲憊與心情備忘）。
* **智能 Upsert 合併**：使用 `datetime` 物件進行日期相容比對，同一天重複輸入會自動覆寫舊紀錄，不會堆疊重複行。
* **物理降冪排序**：後端寫入完成後會強制進行時間降冪排序，**最新日期永遠排列在試算表最上方**。
* **守衛自癒與誤刪防護**：背景線程自動鎖定 Row 1 表頭，在 GID 遺失時強制自癒；表頭保護鎖連帶啟動了 Google Sheets 原生的「分頁防誤刪警告彈窗」。
* **極簡膠囊 UI (Pill Button)**：開啟試算表按鈕全面收窄為精緻的 Pill 尺寸，儲存症狀時加入 **`[ 🔄 正在儲存... ]`** 的白色流暢旋轉動畫反饋。

### ② 💰 智慧股票投資組合 (Stock Portfolio Engine)
* **即時同步**：後端在啟動時自動透過 API 從台股伺服器下載 11,000+ 檔台灣上市上櫃股票/ETF 的即時資料，並全數清洗寫入 TiDB `stock_list`。
* **投資計量**：結合 Google Sheets 股票交易明細（交易日期、類型、股數、單價、手續費），進行即時市價損益估算，並自動以 Row 1 / Column H \u0026 I 警告鎖保護公式。

### ③ 📊 記帳與財富追蹤 (Financial Bookkeeping)
* 透過 Google Sheets 進行流水帳儲存（年度、月份、日期、項目、金額、類別）。
* 前端自動解析記帳數據，利用 **Chart.js** 繪製動態收支分析圓餅圖與趨勢折線圖。

### ④ ⚙️ AI 訓練室 (AI Command Training Room)
* 使用者可手動定義「教導 AI」指令規則（例如：若輸入「吃晚餐」，自動執行「記帳-支出-晚餐」）。
* 規則即時寫入 `AI_指令集` 工作表，並由後端語意分析引擎自動配對執行。

### ⑤ 📝 任務待辦、日記、願望清單、口袋名單
* 均採用「Google Sheets 做為極致私密資料庫」的安全理念，各自建立專屬分頁（`待辦`、`日記`、`願望`、`口袋`）。
* **口袋名單**：整合 **Google Maps API**，結合緯度、經度與常用標記，在前端直接地圖渲染常用美食或地點。

---

## 🛡️ 3. Google Sheets 核心自癒守衛 (Sheet Self-Healing Engine)
為了防止使用者手動修改 Google Sheets 時弄亂格式，系統後端設有：
* **`ensure_all_sheets_warning_protected`**：非同步守衛。在每次網頁載入時啟動，自動掃描所有分頁。
* **表頭自癒**：比對標準表頭格式（如待辦、記帳、生理等），若發現表頭文字被改動或刪除，自動強制重新寫入覆寫。
* **警告鎖上鎖**：為所有表頭 Row 1 自動加入 `warningOnly: True` 的 Google API 保護鎖，防止手殘誤改。

---

## 🔗 4. 第三方與 API 整合配置
* **Google Service Account**：使用 `service_account.json` 進行 Sheets API v4 與 Calendar API v3 的無縫伺服器端存取。
* **TiDB 雲端資料庫**：透過 SQLAlchemy 連結 TiDB，用於高頻儲存使用者訂閱狀態、台灣股票代碼聯想表等。
* **Gemini Pro / Flash**：後端集成 Google Generative AI，用於日常對話、記帳指令語意拆解、以及生理期健康 AI 分析。

---

## 🛠️ 5. 開發快速診斷指令 (Cheat Sheet)

### 端口檢查與伺服器重啟
```bash
# 檢查伺服器是否在 port 8080 正常監聽
lsof -i :8080

# 結束失控的 Python 背景進程
kill -9 <PID>

# 重新啟動 Flask 生產/開發伺服器
python3 app.py
```

### 備份與日誌監控
```bash
# 即時滾動式查看伺服器日誌
tail -f server.log
```
