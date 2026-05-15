import os
import json
from datetime import datetime, time, timedelta
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

import google.generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

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
# 1. 優先嘗試從環境變數讀取 JSON 字串 (正式環境常用)
sa_json = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
if sa_json:
    try:
        creds = Credentials.from_service_account_info(json.loads(sa_json), scopes=SCOPES)
        print("Success: Loaded credentials from GOOGLE_SERVICE_ACCOUNT_JSON")
    except Exception as e:
        print(f"Error loading credentials from env: {e}")

# 2. 如果環境變數沒有，嘗試讀取實體檔案 (本地環境常用)
if not creds and os.path.exists(SERVICE_ACCOUNT_FILE):
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    print("Success: Loaded credentials from service_account.json")

def get_sheets_service():
    if not creds:
        # 如果都沒有憑證，嘗試使用 ADC (Cloud Run 預設身份)
        return build('sheets', 'v4')
    return build('sheets', 'v4', credentials=creds)

# --- Sheets 輔助函數 ---
def append_to_sheet(range_name, values, spreadsheet_id=None):
    if not spreadsheet_id:
        spreadsheet_id = os.getenv('GOOGLE_SHEET_ID')
    service = get_sheets_service()
    body = {'values': [values]}
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption='USER_ENTERED',
        body=body
    ).execute()

def get_sheet_values(range_name, spreadsheet_id=None):
    if not spreadsheet_id:
        spreadsheet_id = os.getenv('GOOGLE_SHEET_ID')
    service = get_sheets_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name
    ).execute()
    return result.get('values', [])

def find_row_by_id(rows, target_id, id_col_idx):
    """
    穩健地在試算表中尋找對應 ID 的列索引 (1-indexed)
    """
    target_id = str(target_id).strip()
    for i, row in enumerate(rows):
        if len(row) > id_col_idx:
            sheet_id = str(row[id_col_idx]).strip()
            # 處理可能出現的 .0
            if sheet_id.endswith('.0'):
                sheet_id = sheet_id[:-2]
            
            if sheet_id == target_id or ('.' in sheet_id and sheet_id.split('.')[0] == target_id):
                return i + 1
    return -1

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

def check_conflicts(service, start_time, end_time, exclude_id=None):
    """
    檢查指定時間範圍內是否有衝突的行程。
    """
    try:
        def ensure_tz(ts):
            if 'T' in ts:
                if '+' not in ts and ts.count(':') >= 1 and not ts.endswith('Z'):
                    return ts + "+08:00"
                return ts
            else:
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
        
        # 排除指定的 ID (用於更新行程時)
        if exclude_id:
            conflicts = [e for e in conflicts if e.get('id') != exclude_id]
            
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
    now = datetime.now()
    service_cal = build('calendar', 'v3', credentials=creds)
    service_sheets = build('sheets', 'v4', credentials=creds)
    
    # 1. 抓取今日行程
    today_start = datetime.combine(now.date(), time.min).isoformat() + '+08:00'
    today_end = datetime.combine(now.date(), time.max).isoformat() + '+08:00'
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
    # 優先尋找專用地圖 Key，若無則嘗試共用 Gemini Key
    maps_api_key = os.getenv('GOOGLE_MAPS_API_KEY') or os.getenv('GEMINI_API_KEY')
    return render_template('index.html', maps_api_key=maps_api_key)

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
    now = datetime.now()

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
                    dt = datetime.strptime(time_str.replace('/', '-'), '%Y-%m-%d %H:%M')
                    iso_start = dt.isoformat()
                    iso_end = (dt + timedelta(hours=1)).isoformat()
                    
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
            today_start = datetime.combine(now.date(), time.min).isoformat() + '+08:00'
            end_date = now + timedelta(days=days-1)
            today_end = datetime.combine(end_date.date(), time.max).isoformat() + '+08:00'
            
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
                    dt_obj = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
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

                is_all_day = 'date' in e['start']

                schedule_list.append({
                    'id': e['id'],
                    'time': time_val,
                    'title': display_title,
                    'display_title': final_title,
                    'completed': is_done,
                    'location': e.get('location', ''),
                    'start_time': start_str,
                    'is_all_day': is_all_day
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

@app.route('/api/memo/list', methods=['GET'])
def get_memos():
    try:
        rows = get_sheet_values('日記')
        if not rows: return jsonify({"status": "success", "data": []})
        
        memos = []
        for row in rows[1:]: # Skip header
            if len(row) > 3:
                memos.append({
                    'date': row[0],
                    'mood': row[1],
                    'weather': row[2],
                    'content': row[3]
                })
        return jsonify({"status": "success", "data": memos})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/query_finance', methods=['POST'])
def direct_query_finance():
    now = datetime.now()
    current_month = now.strftime('%m')
    current_year = now.strftime('%Y')
    
    try:
        rows = get_sheet_values('記帳')
        if not rows:
            return jsonify({"status": "error", "message": "找不到帳簿資料"})
            
        monthly_income = 0
        monthly_expense = 0
        category_totals = {}
        
        for row in rows[1:]: # 跳過標題
            # 檢查年份與月份 (假設 A 欄是年, B 欄是月)
            if len(row) >= 6 and str(row[0]) == current_year and str(row[1]).strip("'").zfill(2) == current_month:
                try:
                    amt = float(str(row[5]).replace(',', ''))
                    
                    # 判斷是收入還是支出 (看 D 欄 [index 3] 是否有內容)
                    is_income = len(row) > 3 and row[3].strip() != ""
                    
                    if is_income:
                        monthly_income += amt
                    else:
                        monthly_expense += amt
                        cat = row[6] if len(row) > 6 else "未分類"
                        category_totals[cat] = category_totals.get(cat, 0) + amt
                except:
                    pass
        
        msg = f"📊 {current_year}年{current_month}月 記帳小結：\n\n"
        msg += f"💰 本月收入：${monthly_income:,.0f} 元\n"
        msg += "------------------\n"
        
        if category_totals:
            msg += "📝 支出分類明細：\n"
            # 按金額排序
            sorted_cats = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
            for cat, amt in sorted_cats:
                msg += f" • {cat}：${amt:,.0f}\n"
        else:
            msg += "📝 本月暫無支出明細\n"
            
        msg += "------------------\n"
        msg += f"💸 本月總支出：${monthly_expense:,.0f} 元\n"
        balance = monthly_income - monthly_expense
        msg += f"⚖️ 本月結餘：${balance:,.0f} 元"
        
        return jsonify({"status": "success", "type": "chat", "message": msg})
    except Exception as e:
        print(f"Finance Query Error: {e}")
        return jsonify({"status": "error", "message": f"計算失敗：{str(e)}"})

@app.route('/api/query_schedule', methods=['POST'])
def direct_query_schedule():
    data = request.json
    days = data.get('days', 1)
    now = datetime.now()
    
    try:
        service = build('calendar', 'v3', credentials=creds)
        today_start = datetime.combine(now.date(), time.min).isoformat() + '+08:00'
        end_date = now + timedelta(days=days-1)
        today_end = datetime.combine(end_date.date(), time.max).isoformat() + '+08:00'
        
        events_result = service.events().list(
            calendarId=CALENDAR_ID, timeMin=today_start, timeMax=today_end,
            maxResults=50, singleEvents=True, orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        
        schedule_list = []
        for e in events:
            start_str = e['start'].get('dateTime', e['start'].get('date'))
            try:
                dt_obj = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                date_val = dt_obj.strftime('%m/%d')
                time_val = dt_obj.strftime('%H:%M') if 'T' in start_str else '全天'
            except:
                date_val = now.strftime('%m/%d')
                time_val = '全天'
            
            full_title = e.get('summary', '無標題')
            is_done = full_title.startswith("✅ ")
            display_title = full_title.replace("✅ ", "", 1) if is_done else full_title
            final_title = f"[{date_val}] {display_title}" if days > 1 else display_title

            is_all_day = 'date' in e['start']
            
            schedule_list.append({
                'id': e['id'],
                'time': time_val,
                'title': display_title, # 不要包含日期標籤，編輯時用原始標題
                'display_title': final_title, # 顯示用的標題
                'completed': is_done,
                'location': e.get('location', ''),
                'start_time': start_str,
                'is_all_day': is_all_day
            })
            
        range_label = "今日" if days == 1 else ("本週" if days == 7 else f"未來 {days} 天")
        return jsonify({
            "status": "success",
            "type": "query_schedule",
            "data": schedule_list,
            "date_str": range_label
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/manual_action', methods=['POST'])
def manual_action():
    """
    接收來自前端 Modal 的手動輸入，直接執行動作，完全不經過 AI。
    """
    data = request.get_json()
    action_type = data.get('type')
    now = datetime.now()

    try:
        if action_type == 'calendar':
            # 手動新增行程
            service = build('calendar', 'v3', credentials=creds)
            is_all_day = data.get('is_all_day', False)
            
            if is_all_day:
                # 全天行程使用 'date' 欄位
                # end.date 必須是開始日期的隔天才能顯示為「一天」
                start_date = data.get('start_time') # YYYY-MM-DD
                dt = datetime.strptime(start_date, '%Y-%m-%d')
                end_date = (dt + timedelta(days=1)).strftime('%Y-%m-%d')
                
                event = {
                    'summary': data.get('title'),
                    'location': data.get('location', ''),
                    'start': { 'date': start_date, 'timeZone': 'Asia/Taipei' },
                    'end': { 'date': end_date, 'timeZone': 'Asia/Taipei' },
                }
            else:
                # 一般行程使用 'dateTime'
                # 確保時間字串包含時區偏移量
                start_str = data.get('start_time')
                if 'T' in start_str and '+' not in start_str and 'Z' not in start_str:
                    start_str += '+08:00'
                
                start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                end_dt = start_dt + timedelta(hours=1)
                
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
            
            print(f"DEBUG: Inserting event: {json.dumps(event, indent=2, ensure_ascii=False)}")

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

# --- 備忘、願望、待辦 API ---
@app.route('/api/memo', methods=['GET', 'POST'])
def handle_memo():
    now = datetime.now()
    diary_id = os.getenv('DIARY_SHEET_ID')
    if request.method == 'POST':
        data = request.json
        # 欄位順序：建立日期, 今天記事, 天氣, 心情, 儲存時間
        row = [
            now.strftime("%Y-%m-%d"),
            data.get('content', ''),
            data.get('weather', ''),
            data.get('mood', ''),
            now.strftime("%H:%M:%S")
        ]
        append_to_sheet('日記', row, spreadsheet_id=diary_id)
        return jsonify({"status": "success", "message": "生活點滴已記錄"})
    else:
        rows = get_sheet_values('日記', spreadsheet_id=diary_id)
        if not rows or len(rows) < 2: return jsonify([])
        headers = rows[0]
        memos = [dict(zip(headers, row)) for row in rows[1:]]
        return jsonify(memos)

@app.route('/api/wishlist', methods=['GET', 'POST'])
def handle_wishlist():
    wish_id = os.getenv('WISH_SHEET_ID')
    if not wish_id:
        wish_id = os.getenv('GOOGLE_SHEET_ID') # 回退到主表 ID
        
    if request.method == 'POST':
        data = request.json
        if not wish_id:
            return jsonify({"status": "error", "message": "環境變數未設定 WISH_SHEET_ID"}), 500
            
        # 欄位：建立日期, 商品名稱, 預估價格, 備註/連結, 狀態, 分類, 實際價格, 唯一 ID, 儲存時間
        unique_id = str(int(datetime.now().timestamp() * 1000))
        row = [
            datetime.now().strftime("%Y-%m-%d"),
            data.get('name', ''),
            data.get('price', '0'),
            data.get('note', ''),
            '想買',
            data.get('category', '靈感'),
            '',
            unique_id,
            datetime.now().strftime("%H:%M:%S")
        ]
        try:
            append_to_sheet('願望清單', row, spreadsheet_id=wish_id)
            return jsonify({"status": "success", "message": "願望已許下", "id": unique_id})
        except Exception as e:
            return jsonify({"status": "error", "message": f"寫入失敗：{str(e)}"}), 500
    else:
        try:
            rows = get_sheet_values('願望清單', spreadsheet_id=wish_id)
            if not rows or len(rows) < 1: return jsonify([])
            
            headers = [h.strip() for h in rows[0]] # 去除表頭空格
            wishes = []
            for row in rows[1:]:
                if not any(row): continue # 跳過空行
                # 補齊缺失欄位
                while len(row) < len(headers): row.append('')
                wishes.append(dict(zip(headers, row)))
            return jsonify(wishes)
        except Exception as e:
            print(f"Wishlist API Error: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/wishlist/fulfill', methods=['POST'])
def fulfill_wish():
    data = request.json
    item_id = str(data.get('id', ''))
    title = data.get('title', '')
    actual_price = data.get('actual_price', '0')
    wish_id = os.getenv('WISH_SHEET_ID')
    
    rows = get_sheet_values('願望清單', spreadsheet_id=wish_id)
    if not rows: return jsonify({"status": "error", "message": "找不到資料"})
    
    target_row_idx = -1
    # 優先 ID 匹配 (第 8 欄, index 7)
    if item_id:
        for i, row in enumerate(rows):
            if len(row) > 7 and str(row[7]) == item_id:
                target_row_idx = i + 1
                break
    
    # 備案：標題匹配 (第 2 欄, index 1)
    if target_row_idx == -1 and title:
        for i, row in enumerate(rows):
            if len(row) > 1 and str(row[1]).strip() == str(title).strip():
                target_row_idx = i + 1
                item_id = str(int(datetime.now().timestamp() * 1000)) if not item_id else item_id
                break
                
    if target_row_idx == -1:
        return jsonify({"status": "error", "message": "找不到該願望"})
        
    service = get_sheets_service()
    # 更新狀態 (E 欄, index 4), 實際價格 (G 欄, index 6), 唯一ID (H 欄, index 7)
    service.spreadsheets().values().update(
        spreadsheetId=wish_id,
        range=f'願望清單!E{target_row_idx}:H{target_row_idx}',
        valueInputOption='USER_ENTERED',
        body={'values': [['已圓夢', rows[target_row_idx-1][5] if len(rows[target_row_idx-1]) > 5 else '', actual_price, item_id]]}
    ).execute()
    
    return jsonify({"status": "success", "message": "恭喜圓夢！✨"})

@app.route('/api/wishlist/delete', methods=['POST'])
def delete_wish():
    data = request.json
    item_id = str(data.get('id', ''))
    title = data.get('title', '')
    wish_id = os.getenv('WISH_SHEET_ID')
    
    rows = get_sheet_values('願望清單', spreadsheet_id=wish_id)
    if not rows: return jsonify({"status": "error", "message": "找不到資料"})
    
    target_row_idx = -1
    print(f"DEBUG: Deleting wish - Target ID: [{item_id}], Title: [{title}]")
    
    # 優先用 ID 進行精確匹配
    if item_id:
        for i, row in enumerate(rows):
            if len(row) > 7:
                # 強制轉換為字串並去除科學記號影響 (簡單處理：去除點與加號)
                current_id = str(row[7]).strip().split('.')[0] 
                if current_id == item_id.strip():
                    target_row_idx = i + 1
                    print(f"DEBUG: Found match by ID at row {target_row_idx}")
                    break
    
    # 如果 ID 沒對上，用名稱 + 狀態進行備案匹配 (優先找「想買」的)
    if target_row_idx == -1 and title:
        print("DEBUG: ID match failed, trying title + status match...")
        for i, row in enumerate(rows):
            if len(row) > 4 and str(row[1]).strip() == str(title).strip() and str(row[4]).strip() == '想買':
                target_row_idx = i + 1
                print(f"DEBUG: Found active match by title at row {target_row_idx}")
                break

    if target_row_idx == -1:
        return jsonify({"status": "error", "message": f"找不到該願望 (ID: {item_id})"})

    service = get_sheets_service()
    # 更新狀態為「已取消」 (E 欄)
    service.spreadsheets().values().update(
        spreadsheetId=wish_id,
        range=f'願望清單!E{target_row_idx}',
        valueInputOption='USER_ENTERED',
        body={'values': [['已取消']]}
    ).execute()
    
    return jsonify({"status": "success", "message": f"已斷捨離該願望 (行號: {target_row_idx}) 🍂"})

@app.route('/api/todo', methods=['GET', 'POST'])
def handle_todo():
    todo_id = os.getenv('TODO_SHEET_ID')
    if not todo_id:
        todo_id = os.getenv('GOOGLE_SHEET_ID')
        
    if request.method == 'POST':
        data = request.json
        if not todo_id:
            return jsonify({"status": "error", "message": "環境變數未設定 TODO_SHEET_ID"}), 500
        # 欄位：建立日期, 事項/內容, 分類, 狀態, 唯一 ID, 完成時間
        unique_id = str(int(datetime.now().timestamp() * 1000))
        priority = data.get('priority', '不重要且不緊急')
        row = [
            datetime.now().strftime("%Y-%m-%d"),
            data.get('title', ''),
            data.get('category', '待辦'),
            '未完成',
            unique_id,
            '',
            priority
        ]
        try:
            # 檢查並補足表頭 (如果尚未有 "優先級")
            try:
                rows_all = get_sheet_values('待辦', spreadsheet_id=todo_id)
                if rows_all and len(rows_all) > 0:
                    headers = rows_all[0]
                    if len(headers) < 7:
                        # 補足表頭
                        service = get_sheets_service()
                        service.spreadsheets().values().update(
                            spreadsheetId=todo_id,
                            range='待辦!G1',
                            valueInputOption='USER_ENTERED',
                            body={'values': [['優先級']]}
                        ).execute()
            except Exception as e:
                print(f"Warning: Failed to auto-update header: {e}")

            append_to_sheet('待辦', row, spreadsheet_id=todo_id)
            return jsonify({"status": "success", "message": "待辦事項已加入", "id": unique_id})
        except Exception as e:
            return jsonify({"status": "error", "message": f"寫入失敗：{str(e)}", "id": unique_id})
    else:
        try:
            rows = get_sheet_values('待辦', spreadsheet_id=todo_id)
            if not rows or len(rows) < 1: return jsonify([])
            
            headers = [h.strip() for h in rows[0]] # 去除表頭空格
            todos = []
            for row in rows[1:]:
                if not any(row): continue
                while len(row) < len(headers): row.append('')
                todos.append(dict(zip(headers, row)))
            return jsonify(todos)
        except Exception as e:
            print(f"Todo API Error: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/todo/toggle', methods=['POST'])
def toggle_todo():
    data = request.json
    item_id = str(data.get('id', ''))
    is_completed = data.get('completed')
    todo_id = os.getenv('TODO_SHEET_ID')
    
    rows = get_sheet_values('待辦', spreadsheet_id=todo_id)
    if not rows: return jsonify({"status": "error", "message": "找不到資料"})
    
    target_row_idx = -1
    # 優先嘗試 ID 匹配 (第 5 欄)
    if item_id and item_id != 'undefined' and item_id != '':
        for i, row in enumerate(rows):
            if len(row) > 4 and str(row[4]) == item_id:
                target_row_idx = i + 1
                break
    
    # 如果 ID 匹配失敗，嘗試標題匹配 (第 2 欄) 作為備案 (處理舊資料)
    if target_row_idx == -1:
        search_title = data.get('title') # 如果前端有傳標題過來
        if search_title:
            for i, row in enumerate(rows):
                if len(row) > 1 and str(row[1]).strip() == str(search_title).strip():
                    target_row_idx = i + 1
                    # 順便幫它補上一個 ID，以後就不會認錯了
                    item_id = str(int(datetime.now().timestamp() * 1000)) if not item_id else item_id
                    break
    
    if target_row_idx == -1:
        return jsonify({"status": "error", "message": "找不到該項目，請嘗試重新整理或重新建立"})
    
    service = get_sheets_service()
    status = '已完成' if is_completed else '未完成'
    finish_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if is_completed else ''
    
    # 更新狀態 (D 欄), ID (E 欄), 完成時間 (F 欄)
    service.spreadsheets().values().update(
        spreadsheetId=todo_id,
        range=f'待辦!D{target_row_idx}:F{target_row_idx}',
        valueInputOption='USER_ENTERED',
        body={'values': [[status, item_id, finish_time]]}
    ).execute()
    
    return jsonify({"status": "success", "message": f"已標記為{status}"})

@app.route('/api/todo/delete', methods=['POST'])
def delete_todo():
    data = request.json
    item_id = str(data.get('id', ''))
    title = data.get('title', '')
    todo_id = os.getenv('TODO_SHEET_ID')
    
    rows = get_sheet_values('待辦', spreadsheet_id=todo_id)
    if not rows: return jsonify({"status": "error", "message": "找不到資料"})
    
    target_row_idx = -1
    if item_id and item_id != 'undefined' and item_id != '':
        for i, row in enumerate(rows):
            if len(row) > 4 and str(row[4]) == item_id:
                target_row_idx = i + 1
                break
    
    if target_row_idx == -1 and title:
        for i, row in enumerate(rows):
            if len(row) > 1 and str(row[1]).strip() == str(title).strip():
                target_row_idx = i + 1
                break

    if target_row_idx == -1:
        return jsonify({"status": "error", "message": "找不到該待辦"})

    service = get_sheets_service()
    service.spreadsheets().values().update(
        spreadsheetId=todo_id,
        range=f'待辦!D{target_row_idx}',
        valueInputOption='USER_ENTERED',
        body={'values': [['已取消']]}
    ).execute()
    
    return jsonify({"status": "success", "message": "已刪除任務 ✕"})

@app.route('/api/wishlist/update', methods=['POST'])
def update_wish():
    data = request.json
    item_id = str(data.get('id', '')).strip()
    name = data.get('name', '')
    price = data.get('price', '')
    note = data.get('note', '')
    category = data.get('category', '')
    wish_id = os.getenv('WISH_SHEET_ID')
    
    rows = get_sheet_values('願望清單', spreadsheet_id=wish_id)
    if not rows: return jsonify({"status": "error", "message": "找不到資料"})
    
    # 使用 helper 尋找 ID (第 8 欄, index 7)
    target_row_idx = find_row_by_id(rows, item_id, 7)
    
    if target_row_idx == -1:
        return jsonify({"status": "error", "message": f"找不到 ID 為 {item_id} 的願望"})

    # 分次更新以確保準確
    service = get_sheets_service()
    
    # 1. 更新名稱、價格、備註 (B-D 欄)
    service.spreadsheets().values().update(
        spreadsheetId=wish_id,
        range=f'願望清單!B{target_row_idx}:D{target_row_idx}',
        valueInputOption='USER_ENTERED',
        body={'values': [[name, price, note]]}
    ).execute()

    # 2. 更新分類 (F 欄)
    if category:
        service.spreadsheets().values().update(
            spreadsheetId=wish_id,
            range=f'願望清單!F{target_row_idx}',
            valueInputOption='USER_ENTERED',
            body={'values': [[category]]}
        ).execute()

    # 3. 更新最後儲存時間 (I 欄)
    service.spreadsheets().values().update(
        spreadsheetId=wish_id,
        range=f'願望清單!I{target_row_idx}',
        valueInputOption='USER_ENTERED',
        body={'values': [[datetime.now().strftime("%H:%M:%S")]]}
    ).execute()
    
    return jsonify({"status": "success", "message": "願望已更新"})

@app.route('/api/todo/update', methods=['POST'])
def update_todo():
    data = request.json
    item_id = str(data.get('id', ''))
    todo_id = os.getenv('TODO_SHEET_ID')
    
    rows = get_sheet_values('待辦', spreadsheet_id=todo_id)
    if not rows: return jsonify({"status": "error", "message": "找不到資料"})
    
    target_row_idx = -1
    for i, row in enumerate(rows):
        if len(row) > 4 and str(row[4]) == item_id:
            target_row_idx = i + 1
            break
            
    if target_row_idx == -1:
        return jsonify({"status": "error", "message": "找不到該待辦"})

    service = get_sheets_service()
    orig_row = rows[target_row_idx-1]
    while len(orig_row) < 7: orig_row.append('')
    
    updated_values = [
        data.get('title', orig_row[1]),
        data.get('category', orig_row[2]),
        orig_row[3], # 狀態
        orig_row[4], # 唯一 ID
        orig_row[5], # 完成時間
        data.get('priority', orig_row[6] if len(orig_row) > 6 else '不重要且不緊急')
    ]

    service.spreadsheets().values().update(
        spreadsheetId=todo_id,
        range=f'待辦!B{target_row_idx}:G{target_row_idx}',
        valueInputOption='USER_ENTERED',
        body={'values': [updated_values]}
    ).execute()
    
    return jsonify({"status": "success", "message": "待辦已更新"})

@app.route('/api/delete_event', methods=['POST'])
def delete_event():
    data = request.json
    event_id = data.get('event_id')
    if not event_id:
        return jsonify({"status": "error", "message": "遺失行程 ID"})

    try:
        service = build('calendar', 'v3', credentials=creds)
        # 使用全域變數 CALENDAR_ID 確保刪除的是正確的日曆
        service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
        return jsonify({"status": "success", "message": "行程已從日曆刪除 ✕"})
    except HttpError as e:
        if e.resp.status == 404:
            return jsonify({"status": "success", "message": "行程已不存在，已從畫面移除"})
        print(f"Calendar API error: {e}")
        return jsonify({"status": "error", "message": f"日曆同步失敗: {str(e)}"})
@app.route('/api/update_event', methods=['POST'])
def update_event():
    data = request.json
    event_id = data.get('event_id')
    if not event_id:
        return jsonify({"status": "error", "message": "遺失行程 ID"})

    try:
        service = build('calendar', 'v3', credentials=creds)
        
        is_all_day = data.get('is_all_day', False)
        summary = data.get('title')
        location = data.get('location', '')
        start_str = data.get('start_time')
        
        # 取得現有活動以保留某些欄位（如描述或狀態）
        event = service.events().get(calendarId=CALENDAR_ID, eventId=event_id).execute()
        
        # 處理完成狀態前綴
        current_summary = event.get('summary', '')
        if current_summary.startswith("✅ ") and not summary.startswith("✅ "):
            summary = "✅ " + summary
        elif not current_summary.startswith("✅ ") and summary.startswith("✅ "):
            pass # Keep it as is if user manually added it? Or maybe just use provided summary.
        
        event['summary'] = summary
        event['location'] = location
        
        if is_all_day:
            dt = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = (dt + timedelta(days=1)).strftime('%Y-%m-%d')
            event['start'] = { 'date': start_str, 'timeZone': 'Asia/Taipei' }
            event['end'] = { 'date': end_date, 'timeZone': 'Asia/Taipei' }
        else:
            if 'T' in start_str and '+' not in start_str and 'Z' not in start_str:
                start_str += '+08:00'
            
            start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
            end_dt = start_dt + timedelta(hours=1)
            
            event['start'] = { 'dateTime': start_dt.isoformat(), 'timeZone': 'Asia/Taipei' }
            event['end'] = { 'dateTime': end_dt.isoformat(), 'timeZone': 'Asia/Taipei' }

        # 檢查衝突 (排除自己)
        conflict_msg = check_conflicts(service, 
                                      event['start'].get('dateTime', event['start'].get('date')), 
                                      event['end'].get('dateTime', event['end'].get('date')),
                                      exclude_id=event_id)
        
        if conflict_msg:
             return jsonify({
                 "status": "error",
                 "message": conflict_msg + "\n\n❌ 偵測到與其他行程衝突，已取消更新。"
             })
        
        service.events().update(calendarId=CALENDAR_ID, eventId=event_id, body=event).execute()
        return jsonify({"status": "success", "message": "行程更新成功 ✅"})
    except Exception as e:
        print(f"Error updating event: {e}")
        return jsonify({"status": "error", "message": f"更新失敗: {str(e)}"})

if __name__ == '__main__':
    # 讀取環境變數中的 PORT，這是 Google Cloud Run 的要求
    import os
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)
