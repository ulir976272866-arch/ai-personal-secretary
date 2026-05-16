import os
import requests
import base64
from dotenv import load_dotenv

load_dotenv('.env')
key = os.getenv('GEMINI_API_KEY')

def test_ocr_with_20_flash():
    # 這裡我用您提供的收據內容作為文字描述，模擬視覺辨識
    prompt = "你是專業收據掃描儀。尋找「NT$」後金額與前方品項，回傳 JSON: {\"item\": \"...\", \"amount\": 0, \"category\": \"...\"}"
    
    # 模擬視覺輸入 (實際上我會用 requests 傳送圖片，這裡先驗證模型是否能處理)
    api_url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent?key={key}"
    
    # 模擬一張收據的 OCR 內容
    mock_receipt_text = "商戶：快易墊子有限公司, 瑜珈墊 NT$1200, 野餐墊 NT$850, 付款金額 NT$2050"
    
    payload = {
        "contents": [{"parts": [
            {"text": f"請從以下收據內容中提取資訊：{mock_receipt_text}\n\n{prompt}"}
        ]}]
    }
    
    try:
        res = requests.post(api_url, json=payload, timeout=10)
        print(f"Status: {res.status_code}")
        print(f"Response: {res.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_ocr_with_20_flash()
