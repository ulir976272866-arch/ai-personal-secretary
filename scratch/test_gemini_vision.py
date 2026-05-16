import os
import requests
import base64
from dotenv import load_dotenv

load_dotenv('.env')
key = os.getenv('GEMINI_API_KEY')

print(f"Testing with API Key: {key[:5]}...{key[-5:]}")

# 測試三種可能的模型路徑
models = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro-vision']

for m in models:
    print(f"\n--- Testing model: {m} ---")
    url = f"https://generativelanguage.googleapis.com/v1/models/{m}:generateContent?key={key}"
    payload = {
        "contents": [{"parts": [{"text": "Hello, are you there?"}]}]
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        print(f"Status: {res.status_code}")
        print(f"Response: {res.text[:200]}")
    except Exception as e:
        print(f"Error: {e}")
