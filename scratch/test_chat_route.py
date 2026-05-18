import sys
sys.path.append('.')
from app import app
import json

# 建立 Flask 測試客戶端
client = app.test_client()

# 我們使用 Flask 的 session_transaction 來模擬已登入狀態（如果需要）
# 但首先我們先用空的 session 測試，看看是否會噴 NameError

print("Sending request to /api/chat...")
try:
    response = client.post('/api/chat', json={"text": "晚餐素食義大利麵$360"})
    print(f"Status Code: {response.status_code}")
    print("Response JSON:")
    print(json.dumps(response.get_json(), indent=2, ensure_ascii=False))
except Exception as e:
    print(f"Caught Exception: {e}")
