import os
from datetime import datetime
from dotenv import load_dotenv
import google.generativeai as genai
import json

load_dotenv('/Users/yinmin/0_Ai coding/私人行事曆安排/ai-personal-secretary/.env')
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

now = datetime.now()
cat_list_str = "食、衣、住、行、育、樂、醫、保險費、貸款、儲蓄/投資、公益"
ai_rules_str = ""
cycle_info_str = ""

prompt = f"""
你是一個精明的數位秘書，現在時間是 {now.strftime('%Y-%m-%d %H:%M:%S')}。
{cycle_info_str}

【視覺掃描規則】：
- 如果是收據或發票：
  1. 必須以「使用者實際支付的總金額（真正從口袋掏出或行動支付、信用卡付出的總額）」為準！
  2. 注意：有些收據上會包含「代售/代收商品/代收款項」（例如 2 元的垃圾袋、兩用袋或代售車票）。店家的發票明細「實付金額」或「應稅/免稅小計」可能只列出商店開立發票的金額（如 114 元），但下方會另有「代收/代售合計」或在支付明細顯示「掃碼付_街口」、「LINE Pay」、「信用卡」、「實付/合計」為 116 元。此時你【必須選擇包含代收商品在內的最終實際總支付金額 116 元】，千萬不要漏掉用戶實際付出的任何一毛錢！
  3. 金額優先順序：用戶實際支付的最終總額（如「掃碼付_街口」、「行動支付明細」、「信用卡/現金實付總計」、「合計」包含代收費用後的金額） > 店家發票發行小計。
- 如果是行程：提取標題、時間與地點。

【意圖判斷】：
- 記帳：type: "expense" (item, amount, category: {cat_list_str}, sub_category: "對應的子分類", expense_type: "income" 或 "expense")
- 行事曆：type: "calendar" (title, start_time, location)
- 查詢行程/未來/今日/本週行程：type: "query_schedule" (days: 查詢天數，預設 1) (例如：「今日行程」、「這週行程」、「未來三天行程」)
- 查詢已完成行程：type: "query_completed_schedule" (keyword: 搜尋關鍵字如離職或 null, days: 過去查詢天數，預設 30) (例如：「查詢過去30天內完成的行程」、「我上週完成了什麼」、「搜尋已完成的池府王爺行程」、「查詢過三天內已完成的行程」)
- 股票交易：type: "stock" (ticker: 股票代號如 "TPE:2330"、"NASDAQ:AAPL", name: 股票名稱如 "台積電", tx_type: "買進" 或 "賣出", shares: 交易股數(整數), price: 單價(浮點數), fee: 手續費(浮點數, 預設 0), date: 交易日期 "YYYY-MM-DD")
- 其他：chat, query_expense_report

【特別規則 (收入母子分類映射)】：
如果是領錢、薪水、進帳、退款、中獎等屬於「收入」，請將 expense_type 設為 "income"。
並且 category 只能從以下五大母分類挑選，且必須配對正確的 sub_category：
1. "薪資" -> sub_category: "正職薪水"、"兼職時薪"、"小費進帳"
2. "獎金" -> sub_category: "年終獎金"、"績效/三節"、"專案分紅"
3. "投資獲利" -> sub_category: "股票股利/價差"、"基金配息"、"定存利息"、"加密貨幣"
4. "副業收入" -> sub_category: "諮詢服務"、"個人項目"、"團購/分潤"、"諮詢隨喜/小費"
5. "變更/退款" -> sub_category: "購物退款"、"代墊款收回"、"其他雜項"
{ai_rules_str}
請回傳 JSON。
"""

user_text = "晚餐壽司170然後飲料50"
print(f"Testing User Input: {user_text}")
contents = [prompt, f"使用者：{user_text}"]

try:
    model = genai.GenerativeModel('gemini-3.1-flash-lite')
    response = model.generate_content(contents)
    print("\nRaw Response:")
    print(response.text)
    
    text = response.text.replace('```json', '').replace('```', '').strip()
    data = json.loads(text)
    print("\nParsed JSON:")
    print(json.dumps(data, indent=2, ensure_ascii=False))
except Exception as e:
    print(f"Error: {e}")
