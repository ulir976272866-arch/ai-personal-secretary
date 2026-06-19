import os
import sys
from dotenv import load_dotenv

# 載入環境變數
env_path = '/Users/yinmin/0_Ai coding/私人行事曆安排/ai-personal-secretary/.env'
load_dotenv(env_path)

api_key = os.getenv("GEMINI_API_KEY")
print(f"📌 正在測試金鑰: {api_key[:10]}...{api_key[-5:] if api_key else ''}")

# 使用 google-generativeai 庫進行連線測試
try:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    # 使用與系統相同的模型
    model = genai.GenerativeModel('gemini-3.1-flash-lite')
    response = model.generate_content("測試連線，請回答 OK")
    print(f"✅ 連線成功！API 回應: {response.text}")
except Exception as e:
    print(f"❌ 連線失敗！Google 伺服器回報錯誤:\n{str(e)}")
