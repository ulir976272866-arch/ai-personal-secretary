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
  --set-env-vars="GEMINI_API_KEY=[您的_API_KEY],GOOGLE_CLIENT_ID=[您的_CLIENT_ID],GOOGLE_CLIENT_SECRET=[您的_CLIENT_SECRET],FLASK_SECRET_KEY=[自訂隨機安全字串]"
```

## 3. Google Cloud Console 憑證設定要點 (最重要)
由於升級為 **Google OAuth 2.0 安全多用戶架構**，當您的 Cloud Run 部署完成取得網址（例如 `https://ai-scheduler-assistant-xxx.a.run.app`）後，您**必須**回到 Google Cloud Console 設定：

1.  **已授權的 JavaScript 來源 (Authorized JavaScript origins)**：
    *   `https://ai-scheduler-assistant-xxx.a.run.app`
2.  **已授權的重新導向 URI (Authorized redirect URIs)**：
    *   `https://ai-scheduler-assistant-xxx.a.run.app/callback` *(注意：末尾必須為 `/callback`，系統將自動處理登入成功後的資料庫建置！)*

## 4. 重要安全性提醒 (多用戶安全隔離)
為了保護您和測試好友的隱私，請確保在 Cloud Run 的 **「變數與祕密 (Variables & Secrets)」** 中設定以下內容：

1.  **環境變數 (Environment Variables):**
    *   `GEMINI_API_KEY`: 您的 Google AI API Key。
    *   `GOOGLE_CLIENT_ID`: 您的 Google OAuth 2.0 用戶端 ID。
    *   `GOOGLE_CLIENT_SECRET`: 您的 Google OAuth 2.0 用戶端密鑰。
    *   `FLASK_SECRET_KEY`: 用於加密瀏覽器 Session 的自訂隨機金鑰（例如：`ai_sec_secret_random_9988`）。
2.  **服務帳號後備金鑰 (可選):**
    *   如果您仍保留 `service_account.json` 檔案在目錄中，它將自動做為未登入狀態下的「後備開發測試機制」，不會干擾正常用戶的隱私資料庫。

## 5. 更新 PWA 連結
布署成功後，gcloud 會給您一個網址（例如 `https://ai-scheduler-assistant-xxx.a.run.app`）。
請在手機瀏覽器開啟該網址，並重新「加入主畫面」，即可體驗極致安全的 PWA 智慧中控台！
布署成功後，gcloud 會給您一個網址（例如 `https://ai-scheduler-xxx.a.run.app`）。
請在手機瀏覽器開啟該網址，並重新「加入主畫面」，即可完成搬家！

---
祝布署順利！如果有任何錯誤訊息，隨時截圖給我看。🫡
