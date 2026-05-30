# 💰 AI 個人秘書系統：股票投資組合（存股功能）資料庫與計算方法交接說明書

本文件為您詳細整理了「AI 個人秘書系統」中關於 **「股票投資組合/存股」** 功能的所有核心設計，包含 Google Sheets 表格欄位、TiDB 資料庫結構、即時市價抓取方式、以及核心財務精算（移動平均成本法、即時損益、股息配息）的計算公式。這份文件能讓您的獨立新專案 **`存股導航系統`** 實現 100% 完美的資料庫共用與邏輯對接！

---

## 📂 1. Google Sheets 試算表結構與配置 (`💰股票投資組合`)

股票功能的前端交易流水帳完全記錄於名為 **`💰股票投資組合`** 的專屬工作表中：

### 📊 工作表欄位結構 (A1:J1)

| 欄位字母 | 欄位名稱 (Header) | 欄位類型 (Type) | 說明與儲存內容 |
| :--- | :--- | :--- | :--- |
| **Column A** | `交易日期` | `String (YYYY/MM/DD)`| 交易發生的日期（例如：`2026/05/28`） |
| **Column B** | `股票代號` | `String (Ticker)` | 標準證券代碼（台股如 `TPE:2330`，美股如 `NASDAQ:AAPL`） |
| **Column C** | `股票名稱` | `String` | 股票名稱（例如：`台積電`、`元大台灣50`） |
| **Column D** | `交易類型` | `String` | 交易類別。支援：`買進`、`賣出`、`股息`、`配息` |
| **Column E** | `交易股數` | `Float` | 交易的股數（整數，如買進一張為 `1000`，零股為實際股數） |
| **Column F** | `交易單價` | `Float` | 交易時的單股價格（元） |
| **Column G** | `手續費` | `Float` | 交易時產生的券商手續費/稅金等（元） |
| **Column H** | `即時市價` | `Formula (活公式)` | **系統自癒公式：** `=GOOGLEFINANCE(B{Row}, "price")` |
| **Column I** | `即時損益` | `Formula (活公式)` | **系統自癒公式：** `=IF(D{Row}="買進", (H{Row}-F{Row})*E{Row}-G{Row}, (F{Row}-H{Row})*E{Row}-G{Row})` |
| **Column J** | `備註` | `String` | 使用者手動填寫的個人備註事項 |

### 🔒 核心保護鎖與公式自癒守衛 (Formula Guardian)
* **表頭警告鎖 (Row 1)**：為 Row 1 (Index 0) 加上 `warningOnly: True` 的 Google API 保護鎖，防止手滑修改。
* **H / I 欄位公式警告鎖 (Row 2 起)**：為 **Column H (即時市價)** 與 **Column I (即時損益)** 加上獨立的 `warningOnly: True` 警告鎖，防止使用者手動覆寫損毀公式。
* **自癒引擎**：系統在背景會隨時監控 Column H 與 Column I，若發現公式非以 `=GOOGLEFINANCE` 或 `=IF` 開頭（例如被使用者手動打入數字），**守衛會自動在背景以批次更新 (`batchUpdate`) 重置回標準公式**，保證活體計算不中斷！

---

## 💾 2. TiDB 雲端資料庫資料表設計

本系統在 TiDB Cloud 中主要有兩個資料表與股票存股功能密切相關：

### ① 股票代號模糊聯想表：`stock_suggestions`
用於使用者在前端輸入股票代號或名稱時，進行實時的 Auto-complete 模糊聯想輸入推薦。

#### 📌 建立 Table SQL 結構：
```sql
CREATE TABLE IF NOT EXISTS stock_suggestions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ticker VARCHAR(50) UNIQUE NOT NULL,      -- 例如: "TPE:2330", "NASDAQ:AAPL"
    name VARCHAR(100) NOT NULL,               -- 例如: "台積電", "Apple"
    short_code VARCHAR(50) NOT NULL,          -- 例如: "2330", "AAPL" (用於純數字/代碼模糊查詢)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 🔄 台灣證交所 (TWSE) & 櫃買中心 (TPEx) 實時同步邏輯
* 後端在每次啟動時，會自動調用台灣證交所與櫃買中心的官方 OpenAPI：
  * **上市股票 (TWSE)**：`https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL`
  * **上櫃股票 (TPEx)**：`https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes`
* **資料清洗規則**：過濾掉代碼長度超過 6 位的衍生權證或認購證，只保留正統股票與 ETF（如：0050、2330）。
* **批次更新**：以 `INSERT INTO stock_suggestions ... ON DUPLICATE KEY UPDATE` 的 SQL 機制，以批次 (Upsert) 實時寫入 TiDB。

### ② 使用者主表標籤：`users`
* 含有一個 `has_stock_record` (`BOOLEAN DEFAULT FALSE`) 欄位。
* 當使用者第一次新增股票交易成功時，系統會自動將 TiDB 中該使用者的此欄位更新為 `TRUE`，做為旗艦版股票服務行銷或後續分析的依據。

---

## 📈 3. 核心財務精算邏輯 (Financial & Valuation Algorithms)

系統在解析 Google Sheets 中的歷史交易明細（遍歷 Row 2 起的每列數據）時，採用了標準的**「移動平均成本法 (Weighted Average Cost)」**進行持倉與損益精算：

### 🅰️ 買進 (Buy) 邏輯
當遍歷列的 `交易類型 == "買進"` 時：
* **庫存股數增加**：`net_shares` += `shares`
* **庫存總成本增加**：`total_cost` += `(shares * price + fee)`（包含了手續費成本）

### 🅱️ 賣出 (Sell) 邏輯
當遍歷列的 `交易類型 == "賣出"` 時：
* **計算買進平均單股成本**：`avg_buy_cost = total_cost / net_shares`
* **計算此次賣出對應的持倉成本**：`cost_of_sold = shares * avg_buy_cost`
* **計算賣出實際收入淨值**：`revenue_from_sold = shares * price - fee`（扣除了手續費成本）
* **計算此次賣出已實現損益 (Realized PnL)**：`realized_pnl` += `(revenue_from_sold - cost_of_sold)`
* **更新持倉餘額**：
  * `net_shares` -= `shares`
  * `total_cost` -= `cost_of_sold`
  * 若淨股數小於 `0.001`（近乎結清），強制設為零：`net_shares = 0` 且 `total_cost = 0`

### 🅲 股息 / 配息 (Dividend) 邏輯
當遍歷列的 `交易類型` 屬於 `["股息", "配息"]` 時：
* **計算利息收入**：`dividend_amount = price * (shares if shares > 0 else 1.0)`
* **累加股息收入**：`dividends` += `dividend_amount`

---

## 📊 4. 持倉估值與總回報率 (Valuation Formulas)

當所有歷史流水帳遍歷完成後，每個代號 `ticker` 將會擁有其最終的持倉餘額，系統會結合由 Google Sheets API 實時撈出的 `live_price`（即時市價）進行估值計算：

1. **平均持股成本 (Average Buy Cost)**：
   $$\text{avg\_cost} = \frac{\text{total\_cost}}{\text{net\_shares}}$$
2. **當前持股市值 (Current Portfolio Value)**：
   $$\text{current\_value} = \text{net\_shares} \times \text{live\_price}$$
3. **未實現損益 (Unrealized ROI)**：
   $$\text{unrealized\_roi} = \text{current\_value} - \text{total\_cost}$$
4. **單檔股票總投資損益 (Total ROI Per Stock)**：
   $$\text{total\_roi} = \text{unrealized\_roi} + \text{realized\_pnl} + \text{dividends}$$
5. **全局總回報率 (Global ROI & ROI Rate)**：
   * **全局總回報金額**：
     $$\text{global\_total\_roi} = \sum(\text{unrealized\_roi}) + \sum(\text{realized\_pnl}) + \sum(\text{dividends})$$
   * **全局總持倉成本**：
     $$\text{total\_unrealized\_cost} = \sum(\text{total\_cost})$$
   * **全局總年化回報率 (%)**：
     $$\text{global\_roi\_rate} = \frac{\text{global\_total\_roi}}{\text{total\_unrealized\_cost}} \times 100\%$$
