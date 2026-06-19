import os
import sys
import json

# Add parent directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, get_valid_credentials

# We use Flask's test client
client = app.test_client()

# Set up session mocking if needed, or bypass login check since in our dev environment we might bypass it.
# Let's inspect session keys that app.py uses.
with client.session_transaction() as sess:
    sess['user_email'] = 'mina.chen.xstar.sg@gmail.com' # bypass points limit
    sess['subscription_type'] = 'YEARLY_AI' # unlimited points

test_cases = [
    "推拿 1200",
    "美甲 800",
    "SPA按摩 1500"
]

print("=== 測試 3: Flask Test Client呼叫 /api/chat ===")
for test in test_cases:
    try:
        response = client.post('/api/chat', json={"text": test})
        print(f"輸入: {test}")
        print(f"HTTP 狀態碼: {response.status_code}")
        data = response.get_json()
        print(f"回傳 JSON:\n{json.dumps(data, indent=2, ensure_ascii=False)}\n")
    except Exception as e:
        print(f"測試 {test} 失敗: {e}\n")
