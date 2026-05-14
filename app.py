import os
import json
import datetime
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

import google.generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# 載入環境變數 (確保能讀到腳本同目錄下的 .env)
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

app = Flask(__name__)

# -----------------------------------------------------------------
# 1. 初始化 Google API (Calendar & Sheets)
# -----------------------------------------------------------------
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/spreadsheets'
]
# 使用相對路徑確保搬家後也能讀到金鑰
SERVICE_ACCOUNT_FILE = os.path.join(os.path.dirname(__file__), 'service_account.json')

creds = None
if os.path.exists(SERVICE_ACCOUNT_FILE):
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)

import requests

# -----------------------------------------------------------------
# 2. 初始化 Gemini API (透過 requests 直接呼叫，避免舊版 SDK 問題)
# -----------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 試算表 ID (從 .env 取得)
SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")
# 使用者的日曆 ID (通常是使用者的 Gmail)
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")

def get_monthly_report(service, now):
    """
    計算本月記帳總額 (含收支比) 與分類統計。
    """
    try:
        rows_result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID, range='記帳!A:G'
        ).execute()
        rows = rows_result.get('values', [])
        cur_year = now.strftime('%Y')
        cur_month = now.strftime('%m')
        
        monthly_expense = 0
        monthly_income = 0
        category_totals = {}
        
        for row in rows[1:]:
            if len(row) >= 6:
                r_year = str(row[0]).replace("'", "")
                r_month = str(row[1]).replace("'", "").zfill(2)
                
                if r_year == cur_year and r_month == cur_month:
                    try:
                        amt = float(str(row[5]).replace(',', ''))
                        
                        # 判斷是收入還是支出 (看 D 欄位是否有內容)
                        is_income = len(row) > 3 and row[3].strip() != ""
                        
                        if is_income:
                            monthly_income += amt
                        else:
                            monthly_expense += amt
                            cat = row[6] if len(row) > 6 else "未分類"
                            category_totals[cat] = category_totals.get(cat, 0) + amt
                    except:
                        pass
        
        balance = monthly_income - monthly_expense
        save_rate = (balance / monthly_income * 100) if monthly_income > 0 else 0
        
        cat_report = ""
        for cat, total in category_totals.items():
            percentage = (total / monthly_expense * 100) if monthly_expense > 0 else 0
            cat_report += f"🔹 {cat}: ${int(total)} ({percentage:.1f}%)\n"
            
        summary = f"💰 本月收入：${int(monthly_income):,}\n"
        summary += f"💸 本月支出：${int(monthly_expense):,}\n"
        summary += f"⚖️ 剩餘結餘：${int(balance):,}\n"
        if monthly_income > 0:
            summary += f"📈 結餘比例：{save_rate:.1f}%\n"
            
        return monthly_expense, f"{summary}\n支出細目：\n{cat_report}", category_totals, monthly_income
    except Exception as e:
        print(f"Error generating monthly report: {e}")
        return 0, "", {}, 0

def check_conflicts(service, start_time, end_time):
    """
    檢查指定時間範圍內是否有衝突的行程。
    start_time/end_time 可以是 ISO 格式字串或 date 字串。
    """
    try:
        # 確保時間字串包含時區 (RFC3339)
        def ensure_tz(ts):
            if 'T' in ts:
                # 如果已經有 T 但沒有時區符號 (Z 或 +)，補上 +08:00
                if '+' not in ts and ts.count(':') >= 1 and not ts.endswith('Z'):
                    return ts + "+08:00"
                return ts
            else:
                # 只有日期，轉為當天凌晨
                return f"{ts}T00:00:00+08:00"

        t_min = ensure_tz(start_time)
        t_max = ensure_tz(end_time)
        
        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=t_min,
            timeMax=t_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        conflicts = events_result.get('items', [])
        if conflicts:
            titles = [e.get('summary', '無標題') for e in conflicts]
            return f"⚠️ 注意：這段時間您已經有其他行程了喔！\n包含：{', '.join(titles)}"
        return None
    except Exception as e:
        print(f"Conflict Check Error: {e}")
        return None

@app.route('/api/morning_briefing', methods=['POST'])
def morning_briefing():
    """生成每日早晨簡報"""
    now = datetime.datetime.now()
    service_cal = build('calendar', 'v3', credentials=creds)
    service_sheets = build('sheets', 'v4', credentials=creds)
    
    # 1. 抓取今日行程
    today_start = datetime.datetime.combine(now.date(), datetime.time.min).isoformat() + '+08:00'
    today_end = datetime.datetime.combine(now.date(), datetime.time.max).isoformat() + '+08:00'
    events_result = service_cal.events().list(
        calendarId=CALENDAR_ID, timeMin=today_start, timeMax=today_end,
        singleEvents=True, orderBy='startTime'
    ).execute()
    events = events_result.get('items', [])
    schedule_text = ", ".join([f"{e.get('summary')} ({e['start'].get('dateTime', '全天')[11:16]})" for e in events]) or "今天沒有行程"
    
    # 2. 抓取本月支出與收入
    monthly_total, _, _, monthly_income = get_monthly_report(service_sheets, now)
    
    # 3. 呼叫 AI 生成簡報
    prompt = f"""
    你是老闆的私人秘書。今天是 {now.strftime('%Y/%m/%d')}。
    今日行程：{schedule_text}
    本月目前累計收入：${int(monthly_income)}
    本月目前累計支出：${int(monthly_total)}
    結餘：${int(monthly_income - monthly_total)}
    請寫一段大約 60 字的親切早晨簡報，語氣要專業且鼓勵老闆。
    """
    
    # 為了省錢與節省額度，取消自動 AI 招呼語，改為固定親切招呼
    reply = f"老闆早安！您今天有 {len(events)} 個行程，本月已支出 ${int(monthly_total)}。祝您有美好的一天！"
    return jsonify({"status": "success", "message": reply})

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
@app.route('/api/chat', methods=['POST'])
def chat():
    """處理前端送來的對話訊息"""
    data = request.json
    user_text = data.get('text', '')
    
    if not user_text:
        return jsonify({"status": "error", "message": "請輸入內容"}), 400

    if not GEMINI_API_KEY:
        return jsonify({
            "status": "error", 
            "message": "系統尚未設定 GEMINI_API_KEY，請先在 .env 中填寫您的 API Key。"
        }), 400

    if not creds:
        return jsonify({
            "status": "error", 
            "message": "系統找不到 service_account.json，請確認檔案存在。"
        }), 400

    data = request.get_json()
    user_text = data.get('text', '')
    now = datetime.datetime.now()

    bypass_data = None
    if user_text == "今日行程":
        bypass_data = {"type": "query_schedule", "days": 1}
    elif user_text == "這週行程":
        bypass_data = {"type": "query_schedule", "days": 7}
    elif user_text == "本月合計":
        bypass_data = {"type": "query_expense_report"}
    elif user_text == "開啟記帳表單":
        bypass_data = {"type": "open_spreadsheet"}
    elif user_text.startswith("+行程"):
        # 格式：+行程 標題, 時間, 地點
        # 範例：+行程 開會, 2026-05-14 14:00, 台北車站
        try:
            parts = user_text[3:].strip().split(',')
            if len(parts) >= 3:
                title = parts[0].strip()
                time_str = parts[1].strip()
                location = parts[2].strip()
                
                # 簡單處理時間格式，如果沒年份就補上今年
                if len(time_str) <= 11: # MM-DD HH:MM
                    time_str = f"{now.year}-{time_str}"
                
                # 轉換為 ISO 格式 (假設輸入是 YYYY-MM-DD HH:MM)
                try:
                    dt = datetime.datetime.strptime(time_str.replace('/', '-'), '%Y-%m-%d %H:%M')
                    iso_start = dt.isoformat()
                    iso_end = (dt + datetime.timedelta(hours=1)).isoformat()
                    
                    bypass_data = {
                        "type": "calendar",
                        "title": title,
                        "start_time": iso_start,
                        "end_time": iso_end,
                        "location": location
                    }
                except:
                    return jsonify({"status": "error", "message": "時間格式錯誤！請使用：YYYY-MM-DD HH:MM"})
            else:
                return jsonify({"status": "error", "message": "格式不對喔！請輸入：+行程 標題, 時間, 地點"})
        except Exception as e:
            return jsonify({"status": "error", "message": f"手動輸入解析失敗：{str(e)}"})
    elif user_text.startswith("+記帳"):
        # 格式：+記帳 項目, 金額, 分類
        # 範例：+記帳 晚餐, 150, 食
        try:
            parts = user_text[3:].strip().split(',')
            if len(parts) >= 3:
                item = parts[0].strip()
                amount = parts[1].strip()
                category = parts[2].strip()
                
                bypass_data = {
                    "type": "expense",
                    "item": item,
                    "amount": int(amount),
                    "category": category
                }
            else:
                return jsonify({"status": "error", "message": "格式不對喔！請輸入：+記帳 項目, 金額, 分類"})
        except Exception as e:
            return jsonify({"status": "error", "message": f"手動記帳解析失敗：{str(e)}"})
        
    if bypass_data:
        parsed_data = bypass_data
        intent_type = parsed_data.get('type')
    else:
        # -----------------------------------------------------------------
        # 步驟 A: 讓 Gemini 判斷意圖並萃取資訊
        # -----------------------------------------------------------------
        prompt = f"""
        你是一個專屬秘書，現在的時間是 {now.strftime('%Y-%m-%d %H:%M:%S')} (星期{now.weekday() + 1})。
        使用者輸入了一句話，請判斷這是「行事曆行程」還是「記帳花費」，並將萃取出的資訊以 JSON 格式回傳。
        
        【重要行事曆規則】：使用者如果要新增行事曆，必須同時明確提供「日期」、「時間」與「地點(或提及線上)」。
        如果這三個條件有任何一個遺漏，請「不要」回傳 type: "calendar"，而是改為回傳 type: "chat"，並在 "message" 中以親切的語氣詢問使用者缺少的資訊。

        如果資訊完全齊全（包含日期、時間、地點），才能回傳行事曆格式：
        {{
            "type": "calendar",
            "title": "行程名稱",
            "start_time": "YYYY-MM-DDTHH:MM:SS",
            "end_time": "YYYY-MM-DDTHH:MM:SS",
            "location": "地點"
        }}
        
        如果是記帳，請依照以下分類歸類 (醫、行、投資、食、住、衣、育、樂、未分類)，並回傳：
        {{
            "type": "expense",
            "item": "消費項目",
            "amount": 數值 (整數),
            "category": "分類名稱"
        }}
        
        如果是想要查詢今天或特定天數的行程 (例如「這週行程」、「明後天行程」)，請回傳：
        {{
            "type": "query_schedule",
            "days": 天數 (整數，例如這週回傳 7，明天回傳 2)
        }}

        如果是想要查詢本月的記帳合計或報告 (例如「本月合計」)，請回傳：
        {{
            "type": "query_expense_report"
        }}

        如果是想要刪除最後一筆記帳資料 (例如「刪除上一筆」或「刪除最後一筆」)，請回傳：
        {{
            "type": "delete_last_expense"
        }}

        如果是想要開啟記帳本、打開表單 (例如「開啟記帳表單」、「打開表單」)，請回傳：
        {{
            "type": "open_spreadsheet"
        }}
        
        如果都不是，或者是普通的聊天，請回傳：
        {{
            "type": "chat",
            "reply": "你對使用者的聊天回覆"
        }}

        請只回傳合法的 JSON 字串，不要有其他 markdown 標籤或文字。
        使用者輸入：「{user_text}」
        """

        try:
            # 使用帳號清單中確認存在的 gemini-flash-latest
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={GEMINI_API_KEY}"
            
            payload = {
                "contents": [{
                    "parts": [{"text": f"現在日期時間是 {now.strftime('%Y-%m-%d %H:%M:%S')}。請根據以下指令回傳 JSON：\n{prompt}\n指令：{user_text}"}]
                }]
            }
            
            response = requests.post(url, json=payload, timeout=15)
            res_data = response.json()
            
            if response.status_code != 200:
                error_info = res_data.get('error', {}).get('message', '未知錯誤')
                print(f"Gemini API Error (HTTP {response.status_code}): {res_data}")
                return jsonify({"status": "error", "message": f"Gemini API 報錯 ({response.status_code}): {error_info}"})
            
            if 'candidates' not in res_data:
                print("Gemini API missing candidates:", res_data)
                return jsonify({"status": "error", "message": f"Gemini API 未回傳有效內容: {json.dumps(res_data)}"})
                
            response_text = res_data['candidates'][0]['content']['parts'][0]['text'].strip()
            
            # 移除可能存在的 markdown json 標記
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            
            parsed_data = json.loads(response_text)
            intent_type = parsed_data.get('type')
        except Exception as e:
            print(f"Gemini 解析錯誤: {e}")
            return jsonify({"status": "error", "message": "抱歉，我不太懂您的意思，可以換個說法嗎？"})

    # -----------------------------------------------------------------
    # 步驟 B: 根據意圖執行動作
    # -----------------------------------------------------------------歉，我不太懂您的意思，可以換個說法嗎？"})

    # -----------------------------------------------------------------
    # 步驟 B: 根據意圖執行動作
    # -----------------------------------------------------------------
    intent_type = parsed_data.get("type")

    try:
        if intent_type == "calendar":
            # 呼叫 Google Calendar API 新增行程
            service = build('calendar', 'v3', credentials=creds)
            event = {
                'summary': parsed_data.get('title'),
                'location': parsed_data.get('location', ''),
                'start': {
                    'dateTime': parsed_data.get('start_time'),
                    'timeZone': 'Asia/Taipei',
                },
                'end': {
                    'dateTime': parsed_data.get('end_time'),
                    'timeZone': 'Asia/Taipei',
                },
            }
            # 檢查衝突
            conflict_msg = check_conflicts(service, parsed_data.get('start_time'), parsed_data.get('end_time'))
            if conflict_msg:
                return jsonify({
                    "status": "error",
                    "message": conflict_msg + "\n\n❌ 為了維持日曆整潔，已攔截此重複行程。"
                })
            
            created_event = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
            
            return jsonify({
                "status": "success",
                "type": "calendar",
                "message": f"✅ 已幫您將「{parsed_data.get('title')}」加入日曆！"
            })

        elif intent_type == "expense":
            # 呼叫 Google Sheets API 新增記帳紀錄
            if not SPREADSHEET_ID:
                return jsonify({"status": "error", "message": "尚未設定 GOOGLE_SHEET_ID"})
                
            service = build('sheets', 'v4', credentials=creds)
            
            # A:Year, B:Month, C:Date, D:IncomeItem, E:ExpenseItem, F:Amount, G:Category
            values = [
                [
                    now.strftime('%Y'), 
                    f"'{now.strftime('%m')}", 
                    now.strftime('%Y/%m/%d'), 
                    "", # 收入項目留空
                    parsed_data.get('item'), 
                    parsed_data.get('amount'), 
                    parsed_data.get('category')
                ]
            ]
            body = {'values': values}
            
            range_name = '記帳!A:G'
            
            result = service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=range_name,
                valueInputOption='USER_ENTERED',
                body=body
            ).execute()

            # 呼叫小助手計算本月總額
            monthly_total, cat_report, cat_dict, monthly_income = get_monthly_report(service, now)

            return jsonify({
                "status": "success",
                "type": "expense",
                "message": f"💰 已幫您記帳：{parsed_data.get('item')} ${parsed_data.get('amount')} (分類: {parsed_data.get('category')})\n\n{cat_report}",
                "chart_data": cat_dict
            })

        elif intent_type == "query_expense_report":
            if not SPREADSHEET_ID:
                return jsonify({"status": "error", "message": "尚未設定 GOOGLE_SHEET_ID"})
            service = build('sheets', 'v4', credentials=creds)
            
            # 呼叫小助手計算本月總額
            monthly_total, cat_report, cat_dict, monthly_income = get_monthly_report(service, now)

            return jsonify({
                "status": "success",
                "type": "expense_report",
                "message": f"📊 本月收支結算報告：\n\n{cat_report}",
                "chart_data": cat_dict
            })

        elif intent_type == "delete_last_expense":
            if not SPREADSHEET_ID:
                return jsonify({"status": "error", "message": "尚未設定 GOOGLE_SHEET_ID"})
            service = build('sheets', 'v4', credentials=creds)
            
            result = service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID, range='記帳!A:F'
            ).execute()
            rows = result.get('values', [])
            last_row_index = len(rows)
            
            if last_row_index > 1:
                deleted_data = rows[-1]
                clear_range = f'記帳!A{last_row_index}:F{last_row_index}'
                service.spreadsheets().values().clear(
                    spreadsheetId=SPREADSHEET_ID, range=clear_range
                ).execute()
                
                item = deleted_data[3] if len(deleted_data) > 3 else "未知"
                amt = deleted_data[4] if len(deleted_data) > 4 else "0"
                return jsonify({
                    "status": "success",
                    "type": "chat",
                    "message": f"🗑️ 已刪除最後一筆資料：\n「{item} ${amt}」"
                })
            else:
                return jsonify({
                    "status": "success",
                    "type": "chat",
                    "message": "⚠️ 表單是空的，沒有資料可以刪除喔！"
                })

        elif intent_type == "open_spreadsheet":
            if not SPREADSHEET_ID:
                return jsonify({"status": "error", "message": "尚未設定 GOOGLE_SHEET_ID"})
            link = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit"
            return jsonify({
                "status": "success",
                "type": "open_spreadsheet",
                "url": link,
                "message": f"已為您準備好記帳本連結：\n<a href='{link}' target='_blank' class='chat-link'>點此開啟記帳本</a>"
            })

        elif intent_type == "query_schedule":
            service = build('calendar', 'v3', credentials=creds)
            
            # 取得查詢天數，預設為 1 天 (今天)
            days = parsed_data.get("days", 1)
            
            # 取得範圍：今天凌晨到 X 天後的午夜
            today_start = datetime.datetime.combine(now.date(), datetime.time.min).isoformat() + '+08:00'
            end_date = now + datetime.timedelta(days=days-1)
            today_end = datetime.datetime.combine(end_date.date(), datetime.time.max).isoformat() + '+08:00'
            
            try:
                events_result = service.events().list(
                    calendarId=CALENDAR_ID, timeMin=today_start, timeMax=today_end,
                    maxResults=50, singleEvents=True, orderBy='startTime'
                ).execute()
                events = events_result.get('items', [])
            except Exception as e:
                # 若發生 404，通常是使用者沒有將個人日曆共用給 Service Account
                if "Not Found" in str(e) or "404" in str(e):
                    return jsonify({
                        "status": "success",
                        "type": "chat",
                        "message": "⚠️ 讀取行事曆失敗！請確認您已在 Google 日曆設定中，將日曆共用給「ulirbooking@booking-calendar-486007.iam.gserviceaccount.com」，並且權限設定為「進行變更」。"
                    })
                events = []
            
            schedule_list = []
            for e in events:
                start_str = e['start'].get('dateTime', e['start'].get('date'))
                
                # 處理日期與時間
                try:
                    dt_obj = datetime.datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                    date_val = dt_obj.strftime('%m/%d')
                    time_val = dt_obj.strftime('%H:%M') if 'T' in start_str else '全天'
                except:
                    date_val = now.strftime('%m/%d')
                    time_val = '全天'
                    
                full_title = e.get('summary', '無標題')
                is_done = full_title.startswith("✅ ")
                display_title = full_title.replace("✅ ", "", 1) if is_done else full_title
                
                # 如果是多天查詢，在標題前面加上日期
                final_title = f"[{date_val}] {display_title}" if days > 1 else display_title

                schedule_list.append({
                    'id': e['id'],
                    'time': time_val,
                    'title': final_title,
                    'completed': is_done,
                    'location': e.get('location', '')
                })
                
            range_label = "今日" if days == 1 else f"未來 {days} 天"
            return jsonify({
                "status": "success",
                "type": "query_schedule",
                "data": schedule_list,
                "date_str": range_label
            })

        elif intent_type == "chat":
            return jsonify({
                "status": "success",
                "type": "chat",
                "message": parsed_data.get("reply", "收到！")
            })
            
        else:
            return jsonify({"status": "error", "message": "我不確定該怎麼處理這個指令。"})

    except Exception as e:
        print(f"API 執行錯誤: {e}")
        return jsonify({"status": "error", "message": f"執行時發生錯誤：{str(e)}"})

@app.route('/api/toggle_completion', methods=['POST'])
def toggle_completion():
    try:
        data = request.get_json()
        event_id = data.get('event_id')
        if not event_id:
            return jsonify({"status": "error", "message": "未提供 event_id"}), 400
            
        if not creds:
             return jsonify({"status": "error", "message": "尚未設定 Google 憑證"}), 500
             
        service = build('calendar', 'v3', credentials=creds)
        
        # 取得現有活動
        event = service.events().get(calendarId=CALENDAR_ID, eventId=event_id).execute()
        summary = event.get('summary', '')
        
        if summary.startswith("✅ "):
            event['summary'] = summary.replace("✅ ", "", 1)
            is_completed = False
        else:
            event['summary'] = "✅ " + summary
            is_completed = True
            
        service.events().update(calendarId=CALENDAR_ID, eventId=event_id, body=event).execute()
        
        return jsonify({
            "status": "success",
            "is_completed": is_completed,
            "new_title": event['summary']
        })
    except Exception as e:
        print("Toggle Completion Error:", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500

    except Exception as e:
        print(f"API 執行錯誤: {e}")
        return jsonify({"status": "error", "message": f"執行時發生錯誤：{str(e)}"})

@app.route('/api/manual_action', methods=['POST'])
def manual_action():
    """
    接收來自前端 Modal 的手動輸入，直接執行動作，完全不經過 AI。
    """
    data = request.get_json()
    action_type = data.get('type')
    now = datetime.datetime.now()

    try:
        if action_type == 'calendar':
            # 手動新增行程
            service = build('calendar', 'v3', credentials=creds)
            is_all_day = data.get('is_all_day', False)
            
            if is_all_day:
                # 全天行程使用 'date' 欄位
                # end.date 必須是開始日期的隔天才能顯示為「一天」
                start_date = data.get('start_time') # YYYY-MM-DD
                dt = datetime.datetime.strptime(start_date, '%Y-%m-%d')
                end_date = (dt + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
                
                event = {
                    'summary': data.get('title'),
                    'location': data.get('location', ''),
                    'start': { 'date': start_date, 'timeZone': 'Asia/Taipei' },
                    'end': { 'date': end_date, 'timeZone': 'Asia/Taipei' },
                }
            else:
                # 一般行程使用 'dateTime'
                start_dt = datetime.datetime.fromisoformat(data.get('start_time'))
                end_dt = start_dt + datetime.timedelta(hours=1)
                
                event = {
                    'summary': data.get('title'),
                    'location': data.get('location', ''),
                    'start': {
                        'dateTime': start_dt.isoformat(),
                        'timeZone': 'Asia/Taipei',
                    },
                    'end': {
                        'dateTime': end_dt.isoformat(),
                        'timeZone': 'Asia/Taipei',
                    },
                }
            # 檢查衝突
            conflict_msg = check_conflicts(service, event['start'].get('dateTime', event['start'].get('date')), 
                                          event['end'].get('dateTime', event['end'].get('date')))
            
            if conflict_msg:
                return jsonify({
                    "status": "error", 
                    "message": conflict_msg + "\n\n❌ 偵測到衝突，已攔截手動新增要求。"
                })

            service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
            
            return jsonify({"status": "success", "message": f"✅ 手動新增行程成功：{data.get('title')}"})

        elif action_type == 'expense':
            # 手動記帳
            if not SPREADSHEET_ID:
                return jsonify({"status": "error", "message": "尚未設定 GOOGLE_SHEET_ID"}), 400
                
            service = build('sheets', 'v4', credentials=creds)
            # A:Year, B:Month, C:Date, D:IncomeItem, E:ExpenseItem, F:Amount, G:Category
            values = [[
                now.strftime('%Y'), 
                f"'{now.strftime('%m')}", 
                now.strftime('%Y/%m/%d'), 
                "", # 收入項目留空
                data.get('item'), 
                data.get('amount'), 
                data.get('category')
            ]]
            body = {'values': values}
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range='記帳!A:G',
                valueInputOption='USER_ENTERED',
                body=body
            ).execute()
            
            # 呼叫小助手計算本月總額
            monthly_total, cat_report, cat_dict, monthly_income = get_monthly_report(service, now)

            return jsonify({
                "status": "success", 
                "message": f"💰 手動記帳成功：{data.get('item')} ${data.get('amount')}\n\n{cat_report}",
                "chart_data": cat_dict
            })

    except Exception as e:
        print(f"Manual Action Error: {e}")
        return jsonify({"status": "error", "message": f"執行失敗：{str(e)}"}), 500

    return jsonify({"status": "error", "message": "未知的動作類型"}), 400

if __name__ == '__main__':
    # 讀取環境變數中的 PORT，這是 Google Cloud Run 的要求
    import os
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)
