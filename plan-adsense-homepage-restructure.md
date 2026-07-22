# Unitask.club（ai-personal-secretary）AdSense 改版計畫書

## 0. 專案現況校正（重要）

原始需求書假設專案是 React/Next.js 架構（路由、React 元件、`manifest.json` 待補）。實際勘查 `私人行事曆安排/ai-personal-secretary` 後發現：

- 這是 **Flask + Jinja** 專案，`app.py` 近萬行，`templates/index.html` 3018 行單一樣板，用 `{% if logged_in %}...{% else %}...{% endif %}` 切換「登入卡」與「App 主介面」。
- `manifest.json`、`sw.js`、`ads.txt`、`/privacy`、`/terms` 頁面**已存在**，PWA 基礎建設已完成大半，不用從零開始。
- `/login` 目前不是一個頁面，而是直接觸發 Google OAuth 導向（`flow.authorization_url`）。真正的「登入卡」UI 是內嵌在 `/` 的 `{% if not logged_in %}` 區塊裡。
- 專案正式營運中，已串接 ECPay 金流與訂閱付費邏輯，`app.py` 目前有未提交的修改（`git status` 顯示 6 個檔案 modified）。

**已與你確認的範圍決策：**
1. 專案認定：`ai-personal-secretary`（Flask），非 React。
2. 執行順序：先做首頁改版解決 AdSense 核心問題，其餘分階段推進。
3. 已登入使用者造訪 `/` 時**維持顯示 App 介面**（不強制導向 `/app`）——因此不需要新增獨立的 `/app` 路由，大幅降低這次改版的風險與工程量。

以下計畫依 Flask 架構調整，用 Jinja 條件樣板 + Flask route，不建立 React 元件。

---

## 1. 安全網：開分支再動工

`app.py` 目前有未提交修改且是正式營運金流專案，建議：

- 從目前工作狀態建立新分支（例如 `feature/adsense-landing-restructure`），保留現有未提交修改一起帶過去，不動 `main`。
- 每個階段完成後在分支上獨立 commit，方便逐步 review、也方便單獨回退。
- 全部驗證通過後才合併回 `main` 並部署。

---

## 2. Phase 1（最高優先）：公開首頁改版 + 登入頁獨立

**目標**：讓 Google 爬蟲與未登入訪客看到的 `/`，變成內容豐富、可被索引的產品介紹頁，不再是「只有登入框」。這是解決 AdSense 退件的核心。

### 改動內容
1. **新增 `templates/landing.html`**：包含 Hero / Features（語意排程、自動記帳、隱私安全）/ PWA 安裝教學（iOS Safari「分享→加入主畫面」、Android Chrome「選單→新增至主畫面」）/ How It Works 三步驟 / FAQ / Footer（服務條款、隱私權政策、聯絡我們、© 2026 Unitask.club）六大區塊，RWD 響應式。CTA 按鈕導向 `/login`。
2. **新增 `templates/login.html`**：把現有 `index.html` 裡的「登入卡」（含 carousel、NDA 條款勾選、Google 登入按鈕、權限用途說明）整段搬過來，做成獨立、乾淨、**不放廣告**的登入頁。
3. **調整 Flask 路由**（`app.py`）：
   - 現有 `/login`（直接觸發 OAuth 的邏輯）改名為 `/auth/google`。
   - 新增 `GET /login`，render `login.html`；登入按鈕連到 `/auth/google`。
   - `/`：未登入 → render `landing.html`；已登入 → 沿用現有邏輯 render `index.html`（App 介面，維持你要求的行為不變）。
4. **`index.html` 瘦身**：移除已搬到 `login.html` 的登入卡區塊（`{% if not logged_in %}...{% endif %}` 那段），只保留 App 介面部分，降低這個檔案未來維護的複雜度。

### 風險點
- `index.html` 開頭有 `dev-sandbox-bar`（沙盒調試列）與深色模式初始化 script，這些邏輯要確認在拆分後仍正常運作，且不會誤植到 `landing.html` / `login.html`。
- Service Worker (`sw.js`) 目前快取清單包含 `/`，拆分路由後要確認快取邏輯不會讓已登入使用者被快取住的舊版首頁卡住。

### 測試檢查點（Phase 1 完成後必須驗證）
- [ ] 未登入訪客造訪 `/`：看到完整行銷頁六大區塊，無登入表單直接曝光，CTA 導向 `/login` 正常。
- [ ] `curl` 或「檢視原始碼」確認 `/` 回傳的 HTML 內含實際文字內容（非空殼，AdSense 爬蟲不會執行你這邊額外的 JS 邏輯，重點看 SSR 出來的文字）。
- [ ] `/login`：登入卡正常顯示、NDA/條款勾選才能啟用登入按鈕、點擊後正確導向 Google OAuth（`/auth/google`）、完整走完一次登入流程到 callback。
- [ ] 已登入使用者造訪 `/`：App 介面照舊（header、AI 點數膠囊、廣告條件顯示邏輯、dev-sandbox bar 在 DEBUG 模式下）全部正常，這是回歸測試重點。
- [ ] `/privacy`、`/terms` 連結在 landing 與 login 頁都可正常開啟。
- [ ] 手機（iOS Safari / Android Chrome）與桌面瀏覽器 RWD 排版檢查。
- [ ] Google Search Console 的「網址檢查工具」重新抓取 `/`，確認索引到新內容。

---

## 3. Phase 2：PWA 安裝教學強化與資源確認

**目標**：既有 PWA 基礎已存在，這階段是補強使用者引導與素材完整度，不是重建。

### 改動內容
- `manifest.json` 目前只有一個 `icon.png`（宣稱 192x192/512x512/1024x1024 多尺寸但實際同一檔案）：視覺品質足夠的話可維持，若要更嚴謹可補上實際切好尺寸的 icon 檔案。
- 確認 Phase 1 新增的 `landing.html` 也正確引入 `<link rel="manifest">`、`apple-touch-icon`、`theme-color` 等 meta（這些目前寫在 `index.html` 的 `<head>`，拆分後兩個樣板都要有，或抽成共用的 `_head.html` include 避免重複維護）。
- landing 頁 PWA 教學區塊放清楚的圖文步驟（已包含在 Phase 1 的 landing.html 內容裡，這裡是驗證環節）。

### 測試檢查點
- [ ] iOS Safari 實機或模擬：依教學操作「加入主畫面」，確認圖示與名稱正確（讀取自 `manifest.json` 的 `short_name`）。
- [ ] Android Chrome 實機：確認出現「安裝應用程式」選項並可正常安裝、啟動後是 standalone 模式（無瀏覽器網址列）。
- [ ] PWA 模式下登入流程（OAuth 導回）不因 standalone context 而失敗。

---

## 4. Phase 3：AdBanner 廣告區塊與投放位置

**目標**：把目前寫死在 `<head>` 的 AdSense script 載入邏輯，搭配實際的廣告版位標記，並確保版位符合 AdSense 規範（登入頁禁止廣告）。

### 改動內容
- 建立可重複使用的 Jinja include（例如 `templates/_ad_banner.html`），放 `<ins class="adsbygoogle">` 廣告單元標記，取代目前只載入 SDK 卻沒有實際版位的狀態。
- 在 `landing.html` 放 1～2 個版位（頂部或內文間）。
- 在 `index.html`（App 介面）側邊欄底部或主內容下方放既有 `show_ads` 條件邏輯對應的版位。
- 確認 `login.html` 完全不引入 AdSense script、不放任何版位。

### 測試檢查點
- [ ] 廣告版位在有無廣告內容時都不造成版面跳動（CLS）。
- [ ] `show_ads` session 邏輯（付費會員/試用期前3天 = 無廣告）在新版位上依然生效。
- [ ] `/login`、`/privacy`、`/terms` 確認零廣告。

---

## 5. Phase 4：SEO 收尾與正式送審

**目標**：把 AdSense/Google 爬蟲能看到的訊號補齊，並完成回歸測試後部署、重新送審。

### 改動內容
- `landing.html` 補上 meta description、Open Graph 標籤。
- 新增 `robots.txt`（目前專案沒有），明確允許 `/`、`/privacy`、`/terms` 被索引。
- 完整回歸測試：ECPay 結帳流程、OAuth callback、訂閱/試用期邏輯、dev role 切換列，確認這次改版全程沒有動到這些既有商業邏輯。

### 測試檢查點
- [ ] 全站關鍵路徑（登入→使用 App→結帳）手動走一次，無回歸問題。
- [ ] 部署到正式環境後，用「Google 行動裝置相容性測試」與「網址檢查工具」重新驗證。
- [ ] 重新提交 AdSense 審查。

---

## 建議下一步

先做 **Phase 1**（首頁改版 + 登入頁獨立），這是直接對應 AdSense 退件原因、影響面也最集中的部分。做完會先讓你 review 並過一輪測試檢查點，確認沒問題再進 Phase 2。

要我現在開始動工 Phase 1 嗎？會先開一個新分支再改，不動 `main`。
