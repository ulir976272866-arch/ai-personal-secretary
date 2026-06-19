import os
import sys
import json

# Add parent directory to sys.path to allow importing from app.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import rule_based_expense_parser, GEMINI_API_KEY
import google.generativeai as genai

print("=== 測試 1: 本地規則解析器 ===")
test_cases = [
    "推拿 1200",
    "美甲 800",
    "SPA按摩 1500"
]

for test in test_cases:
    res = rule_based_expense_parser(test)
    print(f"輸入: {test} -> 解析結果: {json.dumps(res, indent=2, ensure_ascii=False)}")

print("\n=== 測試 2: Gemini AI 解析器 (若 API Key 有效) ===")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    
    # We construct a minimized version of the secretaty prompt matching app.py logic
    # to check what Gemini returns for these inputs.
    from datetime import datetime
    now = datetime.now()
    cat_list_str = "食、衣、住、行、育、樂、醫、保險費、貸款、儲蓄/投資、公益、其他雜支"
    
    prompt = f"""
    你是一個精明的數位秘書，現在時間是 {now.strftime('%Y-%m-%d %H:%M:%S')}。
    
    【意圖判斷】：
    - 記帳：type: "expense" (item, amount, category: {cat_list_str}, sub_category: "對應的子分類", expense_type: "income" 或 "expense")
    
    【特別規則 (收入母子分類映射)】：
    * 「其他」回退規則：如果此項支出/收入在各母分類的預設子分類中沒有對應項目，請將 sub_category 設定為 "其他"。
    
    【格式要求】：
    - 請務必返回 JSON。例如，輸入「晚餐壽司170」應返回:
    {{
      "type": "expense",
      "item": "晚餐壽司",
      "amount": 170,
      "category": "食",
      "sub_category": "晚餐",
      "expense_type": "expense"
    }}
    """
    
    model = genai.GenerativeModel('gemini-3.1-flash-lite')
    for test in test_cases:
        try:
            contents = [prompt, f"使用者：{test}"]
            response = model.generate_content(contents)
            text = response.text.replace('```json', '').replace('```', '').strip()
            print(f"輸入: {test} -> Gemini 回覆:\n{text}\n")
        except Exception as e:
            print(f"輸入: {test} -> Gemini 錯誤: {e}")
else:
    print("未設定 GEMINI_API_KEY，跳過 AI 測試。")
