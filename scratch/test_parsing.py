import os
from datetime import datetime
from dotenv import load_dotenv
import google.generativeai as genai
import json

load_dotenv('.env')
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

now = datetime.now()
cat_list_str = "食、衣、住、行、育、樂、醫、投資、公益"
ai_rules_str = ""
cycle_info_str = ""

prompt = f"""
你是一個精明的數位秘書，現在時間是 {now.strftime('%Y-%m-%d %H:%M:%S')}。
{cycle_info_str}

【視覺掃描規則】：
- 如果是收據：優先尋找「NT$」後的金額。
- 如果是行程：提取標題、時間與地點。

【意圖判斷】：
- 記帳：type: "expense" (item, amount, category: {cat_list_str}, expense_type: "income" 或 "expense")
- 行事曆：type: "calendar" (title, start_time, location)
- 查詢行程/未來/今日/本週行程：type: "query_schedule" (days: 查詢天數，預設 1) (例如：「今日行程」、「這週行程」、「未來三天行程」)
- 查詢已完成行程：type: "query_completed_schedule" (keyword: 搜尋關鍵字如離職或 null, days: 過去查詢天數，預設 30) (例如：「查詢過去30天內完成的行程」、「我上週完成了什麼」、「搜尋已完成的池府王爺行程」、「查詢過三天內已完成的行程」)
- 其他：chat, query_expense_report

【特別規則】：如果是領錢、薪水、進帳、退款、中獎等屬於「收入」，請將 expense_type 設為 "income"。
{ai_rules_str}
請回傳 JSON。
"""

test_inputs = [
    "晚餐素食義大利麵$360",
    "晚餐素食義大利麵360元",
    "晚餐素食義大利麵三百六十元",
    "晚餐素食義大利麵360",
    "晚餐素食義大利麵三百六十"
]

model = genai.GenerativeModel('gemini-3.1-flash-lite')

for user_text in test_inputs:
    print(f"\n======================================")
    print(f"Testing User Input: {user_text}")
    contents = [prompt, f"使用者：{user_text}"]
    try:
        response = model.generate_content(contents)
        print("Raw Response:")
        print(response.text)
        
        text = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(text)
        parsed_data = data[0] if isinstance(data, list) and len(data) > 0 else data
        print("Parsed JSON:")
        print(json.dumps(parsed_data, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error for '{user_text}': {e}")

