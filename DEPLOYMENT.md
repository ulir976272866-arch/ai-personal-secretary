# 🚀 Google Cloud Run 布署指南 (小秘書專用版)

這份指南將帶領您將「AI 全能行事曆秘書」布署到 Google Cloud，讓您隨時隨地都能使用。

## 1. 準備工作
*   確認您已經安裝了 [Google Cloud SDK (gcloud CLI)](https://cloud.google.com/sdk/docs/install)。
*   確保您的 `service_account.json` 已經放在專案根目錄（本機測試用，布署時我們會手動設定環境變數）。

## 2. 布署指令
在專案目錄下執行以下指令即可布署：

```bash
# 登入 Google Cloud
gcloud auth login

# 設定專案 ID (請替換成您的專案 ID)
gcloud config set project [YOUR_PROJECT_ID]

# 直接布署到 Cloud Run
gcloud run deploy ai-scheduler-assistant \
  --source . \
  --region asia-east1 \
  --allow-unauthenticated \
  --set-env-vars="GEMINI_API_KEY=[您的_API_KEY],SPREADSHEET_ID=[您的_SHEET_ID]"
```

## 3. 重要安全性提醒 (元辰專案模式)
比照元辰專案，為了安全，請在 Cloud Run 的 **「變數與祕密 (Variables & Secrets)」** 中設定以下內容：

1.  **環境變數 (Environment Variables):**
    *   `GEMINI_API_KEY`: 您的 Google AI API Key。
    *   `SPREADSHEET_ID`: 您的 Google Sheet ID。
2.  **服務帳號金鑰 (Credentials):**
    *   建議將 `service_account.json` 的內容貼到 Cloud Run 的環境變數 `GOOGLE_APPLICATION_CREDENTIALS_JSON` 中（如果程式有支援讀取字串），或是直接將該檔案布署（目前 Dockerfile 已包含，但請注意安全性）。

## 4. 更新 PWA 連結
布署成功後，gcloud 會給您一個網址（例如 `https://ai-scheduler-xxx.a.run.app`）。
請在手機瀏覽器開啟該網址，並重新「加入主畫面」，即可完成搬家！

---
祝布署順利！如果有任何錯誤訊息，隨時截圖給我看。🫡
