import os
import json
import uuid
import requests
from datetime import datetime, time, timedelta, timezone
from PIL import Image

# 定義台灣時區 (UTC+8)
TW_TZ = timezone(timedelta(hours=8))

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


# -----------------------------------------------------------------
# 2. 初始化 Gemini API (透過 requests 直接呼叫，避免舊版 SDK 問題)
# -----------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY, transport='rest')
else:
    print("Warning: GEMINI_API_KEY not found in environment.")

# 試算表 ID (從 .env 取得)
SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")
# 使用者的日曆 ID (通常是使用者的 Gmail)
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")

# 記帳分類與 Emoji 映射對照表 (確保雲端與本地端都有超高顏值 Emoji 符號)
CATEGORY_EMOJI_MAP = {
    # 支出分類
    "食": "🍔", "衣": "👔", "住": "🏠", "行": "🚗", "育": "📚", "樂": "🎬", "醫": "🏥", "投資": "📈", "公益": "💖", "未分類": "❓",
    # 收入分類
    "薪資": "💰", "獎金": "🧧", "投資獲利": "💹", "退款": "🔙", "其他進帳": "🪙"
}

def format_category_with_emoji(category, is_income=False):
    if not category:
        return "❓ 未分類"
        
    category_clean = str(category).strip()
    
    # 1. 檢查是否已經有任何「圖示 分類」格式的空格分隔符 (例如：🍔 食 或 🐶 寵物)
    if ' ' in category_clean:
        parts = category_clean.split(' ', 1)
        if len(parts) == 2 and len(parts[0]) > 0:
            return category_clean
            
    # 2. 如果是純文字，檢查是否包含預設分類的關鍵字，並主動加上對應 Emoji
    for cat_name, emoji in CATEGORY_EMOJI_MAP.items():
        if cat_name in category_clean:
            return f"{emoji} {cat_name}"
            
    # 3. 若是自訂分類但尚未有圖示，則依照收支類型給予預設圖示
    default_emoji = "💰" if is_income else "📝"
    return f"{default_emoji} {category_clean}"

def ensure_tz(ts):
    """確保時間字串包含時區偏移量"""
    if 'T' in ts:
        if '+' not in ts and ts.count(':') >= 1 and not ts.endswith('Z'):
            return ts + "+08:00"
        return ts
    else:
        return f"{ts}T00:00:00+08:00"

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
        # 按金額排序
        sorted_cats = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
        for cat, total in sorted_cats:
            percentage = (total / monthly_expense * 100) if monthly_expense > 0 else 0
            cat_report += f"🔹 {cat}: ${int(total):,} ({percentage:.1f}%)\n"
            
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
    now = datetime.now(TW_TZ)
    service_sheets = build('sheets', 'v4', credentials=creds)
    
    # 抓取本月支出
    monthly_total, _, _, _ = get_monthly_report(service_sheets, now)
    
    # 為了省錢與節省額度，目前使用固定親切招呼
    reply = f"老闆早安！本月已支出 ${int(monthly_total):,}。祝您有美好的一天！"
    return jsonify({"status": "success", "message": reply})

@app.route('/')
def index():
    # 優先尋找專用地圖 Key，若無則嘗試共用 Gemini Key
    maps_api_key = os.getenv('GOOGLE_MAPS_API_KEY') or os.getenv('GEMINI_API_KEY')
    return render_template('index.html', maps_api_key=maps_api_key)

@app.route('/chat', methods=['POST'])
@app.route('/api/chat', methods=['POST'])
def chat():
    """處理前端送來的對話訊息 (支援文字與圖片)"""
    user_text = ""
    image_file = None
    
    if request.is_json:
        data = request.json
        user_text = data.get('text', '')
    else:
        user_text = request.form.get('text', '')
        if 'image' in request.files:
            image_file = request.files['image']
    
    if not user_text and not image_file:
        return jsonify({"status": "error", "message": "請輸入內容或傳送圖片"}), 400

    if not GEMINI_API_KEY:
        return jsonify({"status": "error", "message": "尚未設定 API Key"}), 400

    if not creds:
        return jsonify({"status": "error", "message": "找不到 service_account.json"}), 400

    now = datetime.now(TW_TZ)
    bypass_data = None
    
    if not image_file:
        if user_text == "今日行程":
            bypass_data = {"type": "query_schedule", "days": 1}
        elif user_text == "這週行程":
            bypass_data = {"type": "query_schedule", "days": 7}
        elif user_text == "本月合計":
            bypass_data = {"type": "query_expense_report"}
        elif user_text == "開啟記帳表單":
            bypass_data = {"type": "open_spreadsheet"}
        elif user_text.startswith("+行程"):
            try:
                parts = user_text[3:].strip().split(',')
                if len(parts) >= 3:
                    title, time_str, location = [p.strip() for p in parts[:3]]
                    if len(time_str) <= 11: time_str = f"{now.year}-{time_str}"
                    dt = datetime.strptime(time_str.replace('/', '-'), '%Y-%m-%d %H:%M')
                    bypass_data = {
                        "type": "calendar", "title": title, "location": location,
                        "start_time": dt.isoformat(), "end_time": (dt + timedelta(hours=1)).isoformat()
                    }
            except: pass

    if bypass_data:
        parsed_data = bypass_data
    else:
        ai_rules_str = ""
        expense_categories = ["食", "衣", "住", "行", "育", "樂", "醫", "投資", "公益"]
        try:
            service_sheets = build('sheets', 'v4', credentials=creds)
            # 讀取記帳分類
            rows_result = service_sheets.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID, range='記帳!G:G'
            ).execute()
            existing_cats = set([row[0] for row in rows_result.get('values', [])[1:] if row])
            for ec in existing_cats:
                if ec not in expense_categories: expense_categories.append(ec)
                
            # 讀取 AI 自訂指令集
            health_sheet_id = os.getenv('HEALTH_SHEET_ID')
            if health_sheet_id:
                rules_result = service_sheets.spreadsheets().values().get(
                    spreadsheetId=health_sheet_id, range='AI_指令集!A:B'
                ).execute()
                rule_rows = rules_result.get('values', [])
                if len(rule_rows) > 1:
                    ai_rules_str = "\n        【用戶自訂訓練指令】(最高優先級)：\n"
                    for r in rule_rows[1:]:
                        if len(r) >= 2 and r[0].strip():
                            ai_rules_str += f"        - 當用戶說「{r[0]}」時，你必須執行「{r[1]}」。\n"
        except Exception as e:
            print(f"Error loading dynamic context: {e}")
            
        cat_list_str = "、".join(expense_categories)

        prompt = f"""
        你是一個精明的數位秘書，現在時間是 {now.strftime('%Y-%m-%d %H:%M:%S')}。
        
        【視覺掃描規則】：
        - 如果是收據：優先尋找「NT$」後的金額。
        - 如果是行程：提取標題、時間與地點。
        
        【意圖判斷】：
        - 記帳：type: "expense" (item, amount, category: {cat_list_str}, expense_type: "income" 或 "expense")
        - 行事曆：type: "calendar" (title, start_time, location)
        - 查詢已完成行程：type: "query_completed_schedule" (keyword: 搜尋關鍵字如離職或 null, days: 過去查詢天數，預設 30)
        - 其他：chat, query_schedule, query_expense_report
        
        【特別規則】：如果是領錢、薪水、進帳、退款、中獎等屬於「收入」，請將 expense_type 設為 "income"。
        {ai_rules_str}
        請回傳 JSON。
        """

        try:
            model = genai.GenerativeModel('gemini-3.1-flash-lite')
            contents = [prompt]
            if user_text: contents.append(f"使用者：{user_text}")
            if image_file: contents.append(Image.open(image_file))
            
            response = model.generate_content(contents)
            text = response.text.replace('```json', '').replace('```', '').strip()
            
            data = json.loads(text)
            parsed_data = data[0] if isinstance(data, list) and len(data) > 0 else data
        except Exception as e:
            print(f"Gemini AI Error: {e}")
            return jsonify({"status": "error", "message": "AI 處理失敗，請稍後再試。"})

    intent_type = parsed_data.get("type")
    try:
        if intent_type == "calendar":
            service = build('calendar', 'v3', credentials=creds)
            event = {
                'summary': parsed_data.get('title'),
                'location': parsed_data.get('location', ''),
                'start': {'dateTime': parsed_data.get('start_time'), 'timeZone': 'Asia/Taipei'},
                'end': {'dateTime': parsed_data.get('end_time') or (datetime.fromisoformat(parsed_data.get('start_time')) + timedelta(hours=1)).isoformat(), 'timeZone': 'Asia/Taipei'},
            }
            conflict_msg = check_conflicts(service, event['start']['dateTime'], event['end']['dateTime'])
            if conflict_msg: return jsonify({"status": "error", "message": conflict_msg})
            service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
            return jsonify({"status": "success", "type": "calendar", "message": f"✅ 已排入日曆：{parsed_data.get('title')}"})

        elif intent_type == "expense":
            service = build('sheets', 'v4', credentials=creds)
            # 欄位順序：年度(A), 月份(B), 日期(C), 收入(D), 支出(E), 金額(F), 類別(G)
            is_income = parsed_data.get('expense_type') == 'income'
            body = {'values': [[
                str(now.year), 
                f"'{now.month:02d}", 
                now.strftime("%Y/%m/%d"), 
                parsed_data.get('item') if is_income else "", 
                "" if is_income else parsed_data.get('item'), 
                parsed_data.get('amount'), 
                format_category_with_emoji(parsed_data.get('category'), is_income)
            ]]}
            service.spreadsheets().values().append(spreadsheetId=SPREADSHEET_ID, range='記帳!A:G', valueInputOption='USER_ENTERED', body=body).execute()
            _, cat_report, cat_dict, _ = get_monthly_report(service, now)
            emoji = "💰" if is_income else "💸"
            label = "收入" if is_income else "支出"
            return jsonify({"status": "success", "type": "expense", "message": f"{emoji} 已記{label}：{parsed_data.get('item')} ${parsed_data.get('amount')}\n\n{cat_report}", "chart_data": cat_dict})

        elif intent_type == "query_schedule":
            return get_schedule_response(parsed_data.get("days", 1))

        elif intent_type == "query_completed_schedule":
            keyword = parsed_data.get("keyword")
            days = parsed_data.get("days") or 30
            try:
                days = int(days)
            except:
                days = 30
            return get_completed_schedule_response(keyword, days)

        elif intent_type == "query_expense_report":
            service = build('sheets', 'v4', credentials=creds)
            _, cat_report, cat_dict, _ = get_monthly_report(service, now)
            return jsonify({"status": "success", "type": "expense_report", "message": f"📊 本月結算：\n\n{cat_report}", "chart_data": cat_dict})

        elif intent_type == "delete_last_expense":
            service = build('sheets', 'v4', credentials=creds)
            res = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range='記帳!A:F').execute()
            rows = res.get('values', [])
            last_row_index = len(rows)
            if last_row_index > 1:
                deleted_data = rows[-1]
                service.spreadsheets().values().clear(spreadsheetId=SPREADSHEET_ID, range=f'記帳!A{last_row_index}:F{last_row_index}').execute()
                item = deleted_data[3] if len(deleted_data) > 3 else "未知"
                amt = deleted_data[4] if len(deleted_data) > 4 else "0"
                return jsonify({"status": "success", "type": "chat", "message": f"🗑️ 已刪除最後一筆資料：\n「{item} ${amt}」"})
            else:
                return jsonify({"status": "success", "type": "chat", "message": "⚠️ 表單是空的，沒有資料可以刪除。"})

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
    except HttpError as e:
        status_code = getattr(e, 'resp', None) and getattr(e.resp, 'status', None) or getattr(e, 'status_code', None)
        if status_code == 403:
            return jsonify({
                "status": "error", 
                "message": "權限不足！請至 Google 日曆共用設定中，將助理帳號「ulirbooking@booking-calendar-486007.iam.gserviceaccount.com」的權限調整為「做出變更並管理共用」或「做出變更行程」，才能將行程標記為完成喔！"
            }), 403
        return jsonify({"status": "error", "message": str(e)}), 500
    except Exception as e:
        print("Toggle Completion Error:", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500

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
    now = datetime.now(TW_TZ)
    try:
        service_sheets = build('sheets', 'v4', credentials=creds)
        _, cat_report, _, _ = get_monthly_report(service_sheets, now)
        
        msg = f"📊 {now.year}年{now.month}月 記帳小結：\n\n"
        msg += cat_report
        
        return jsonify({"status": "success", "type": "chat", "message": msg})
    except Exception as e:
        print(f"Finance Query Error: {e}")
        return jsonify({"status": "error", "message": f"計算失敗：{str(e)}"})

def get_schedule_response(days):
    """取得行事曆行程的共通回傳格式"""
    now = datetime.now(TW_TZ)
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
    except Exception as e:
        if "Not Found" in str(e) or "404" in str(e):
            return jsonify({
                "status": "success",
                "type": "chat",
                "message": "⚠️ 讀取行事曆失敗！請確認日曆共用設定。"
            })
        events = []
    
    schedule_list = []
    for e in events:
        start_str = e['start'].get('dateTime', e['start'].get('date'))
        try:
            if 'T' in start_str:
                dt_obj = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                dt_obj = dt_obj.astimezone(TW_TZ)
                date_val = dt_obj.strftime('%m/%d')
                time_val = dt_obj.strftime('%H:%M')
            else:
                dt_obj = datetime.strptime(start_str, '%Y-%m-%d')
                date_val = dt_obj.strftime('%m/%d')
                time_val = '全天'
        except Exception as ex:
            print(f"Error parsing start_str '{start_str}': {ex}")
            date_val = now.strftime('%m/%d')
            time_val = '全天'
        
        full_title = e.get('summary', '無標題')
        is_done = full_title.startswith("✅ ")
        display_title = full_title.replace("✅ ", "", 1) if is_done else full_title
        final_title = f"[{date_val}] {display_title}" if days > 1 else display_title
        is_all_day = 'date' in e['start']
        
        schedule_list.append({
            'id': e['id'], 'time': time_val, 'title': display_title,
            'display_title': final_title, 'completed': is_done,
            'location': e.get('location', ''), 'start_time': start_str,
            'is_all_day': is_all_day
        })
        
    range_label = "今日" if days == 1 else ("本週" if days == 7 else f"未來 {days} 天")
    return jsonify({
        "status": "success", "type": "query_schedule",
        "data": schedule_list, "date_str": range_label
    })

def get_completed_schedule_response(keyword, days):
    """查詢過去已完成行程的共通回傳格式"""
    now = datetime.now(TW_TZ)
    try:
        service = build('calendar', 'v3', credentials=creds)
        today_end = datetime.combine(now.date(), time.max).isoformat() + '+08:00'
        past_start = datetime.combine((now - timedelta(days=days)).date(), time.min).isoformat() + '+08:00'
        
        events_result = service.events().list(
            calendarId=CALENDAR_ID, timeMin=past_start, timeMax=today_end,
            maxResults=150, singleEvents=True, orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
    except Exception as e:
        print(f"Error fetching past completed events: {e}")
        return jsonify({
            "status": "success",
            "type": "chat",
            "message": "⚠️ 讀取行事曆失敗！請確認日曆共用設定。"
        })
        
    completed_list = []
    for e in events:
        full_title = e.get('summary', '無標題')
        is_done = full_title.startswith("✅ ")
        if not is_done:
            continue
            
        display_title = full_title.replace("✅ ", "", 1)
        
        # Keyword filter (case-insensitive)
        if keyword:
            keyword_lower = keyword.lower()
            if keyword_lower not in display_title.lower() and keyword_lower not in e.get('location', '').lower():
                continue
                
        start_str = e['start'].get('dateTime', e['start'].get('date'))
        try:
            if 'T' in start_str:
                dt_obj = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                dt_obj = dt_obj.astimezone(TW_TZ)
                date_val = dt_obj.strftime('%m/%d')
                time_val = dt_obj.strftime('%H:%M')
            else:
                dt_obj = datetime.strptime(start_str, '%Y-%m-%d')
                date_val = dt_obj.strftime('%m/%d')
                time_val = '全天'
        except Exception as ex:
            print(f"Error parsing start_str '{start_str}': {ex}")
            date_val = now.strftime('%m/%d')
            time_val = '全天'
            
        completed_list.append({
            'id': e['id'], 'time': time_val, 'date': date_val, 'title': display_title,
            'location': e.get('location', ''), 'start_time': start_str
        })
        
    if not completed_list:
        k_str = f"關鍵字「{keyword}」" if keyword else ""
        return jsonify({
            "status": "success",
            "type": "chat",
            "message": f"🔍 過去 {days} 天內，沒有找到任何符合{k_str}的已完成行程喔！"
        })
        
    # Generate direct clean message for LINE / fallback
    msg = f"🔍 幫您找到過去 {days} 天內已完成的行程：\n\n"
    for i, item in enumerate(completed_list, 1):
        time_label = f" ({item['time']})" if item['time'] != '全天' else " (全天)"
        loc_label = f"\n📍 地址：{item['location']}" if item['location'] else ""
        msg += f"{i}. [{item['date']}] {item['title']}{time_label}{loc_label}\n"
        
    return jsonify({
        "status": "success",
        "type": "query_completed_schedule",
        "data": completed_list,
        "message": msg,
        "keyword": keyword,
        "days": days
    })

@app.route('/api/query_schedule', methods=['POST'])
def direct_query_schedule():
    data = request.json
    days = data.get('days', 1)
    return get_schedule_response(days)

@app.route('/api/manual_action', methods=['POST'])
def manual_action():
    """
    接收來自前端 Modal 的手動輸入，直接執行動作，完全不經過 AI。
    """
    data = request.get_json()
    action_type = data.get('type')
    now = datetime.now(TW_TZ)

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
            is_income = data.get('expense_type') == 'income'
            values = [[
                now.strftime('%Y'), 
                f"'{now.strftime('%m')}", 
                now.strftime('%Y/%m/%d'), 
                data.get('item') if is_income else "", # 收入項目
                "" if is_income else data.get('item'), # 支出項目
                data.get('amount'), 
                format_category_with_emoji(data.get('category'), is_income)
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
    now = datetime.now(TW_TZ)
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
        unique_id = str(int(datetime.now(TW_TZ).timestamp() * 1000))
        row = [
            datetime.now(TW_TZ).strftime("%Y-%m-%d"),
            data.get('name', ''),
            data.get('price', '0'),
            data.get('note', ''),
            '想買',
            data.get('category', '靈感'),
            '',
            unique_id,
            datetime.now(TW_TZ).strftime("%H:%M:%S")
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
                item_id = str(int(datetime.now(TW_TZ).timestamp() * 1000)) if not item_id else item_id
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
    
    # 優先用 ID 進行精確匹配
    if item_id:
        for i, row in enumerate(rows):
            if len(row) > 7:
                # 強制轉換為字串並去除科學記號影響 (簡單處理：去除點與加號)
                current_id = str(row[7]).strip().split('.')[0] 
                if current_id == item_id.strip():
                    target_row_idx = i + 1
                    break
    
    # 如果 ID 沒對上，用名稱 + 狀態進行備案匹配 (優先找「想買」的)
    if target_row_idx == -1 and title:
        for i, row in enumerate(rows):
            if len(row) > 4 and str(row[1]).strip() == str(title).strip() and str(row[4]).strip() == '想買':
                target_row_idx = i + 1
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
        unique_id = str(int(datetime.now(TW_TZ).timestamp() * 1000))
        priority = data.get('priority', '不重要且不緊急')
        row = [
            datetime.now(TW_TZ).strftime("%Y-%m-%d"),
            data.get('title', ''),
            data.get('category', '待辦'),
            '未完成',
            unique_id,
            datetime.now(TW_TZ).strftime("%H:%M:%S"),
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
                    item_id = str(int(datetime.now(TW_TZ).timestamp() * 1000)) if not item_id else item_id
                    break
    
    if target_row_idx == -1:
        return jsonify({"status": "error", "message": "找不到該項目，請嘗試重新整理或重新建立"})
    
    service = get_sheets_service()
    status = '已完成' if is_completed else '未完成'
    finish_time = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S") if is_completed else ''
    
    # 更新狀態 (D 欄), ID (E 欄)
    service.spreadsheets().values().update(
        spreadsheetId=todo_id,
        range=f'待辦!D{target_row_idx}:E{target_row_idx}',
        valueInputOption='USER_ENTERED',
        body={'values': [[status, item_id]]}
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
        body={'values': [[datetime.now(TW_TZ).strftime("%H:%M:%S")]]}
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
        status_code = getattr(e, 'resp', None) and getattr(e.resp, 'status', None) or getattr(e, 'status_code', None)
        if status_code == 404:
            return jsonify({"status": "success", "message": "行程已不存在，已從畫面移除"})
        elif status_code == 403:
            return jsonify({
                "status": "error", 
                "message": "權限不足！請至 Google 日曆共用設定中，將助理帳號「ulirbooking@booking-calendar-486007.iam.gserviceaccount.com」的權限調整為「做出變更並管理共用」或「做出變更行程」，才能進行刪除喔！"
            })
        print(f"Calendar API error: {e}")
        return jsonify({"status": "error", "message": f"日曆同步失敗: {str(e)}"})
    except Exception as e:
        print(f"Delete event general error: {e}")
        return jsonify({"status": "error", "message": f"伺服器錯誤: {str(e)}"})
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


def get_lat_lng(address):
    """將地址轉為經緯度 (使用 Google Maps 官方 API)"""
    if not address: return None, None
    try:
        api_key = os.getenv('GOOGLE_MAPS_API_KEY')
        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={api_key}"
        res = requests.get(url, timeout=5).json()
        if res.get('status') == 'OK':
            loc = res['results'][0]['geometry']['location']
            return loc['lat'], loc['lng']
    except Exception as e:
        print(f"Geocoding error: {e}")
    return None, None

def handle_pocket(action, data=None):
    """
    處理口袋名單的 CRUD 操作。
    """
    sheet_id = os.getenv('POCKET_SHEET_ID')
    service = build('sheets', 'v4', credentials=creds)

    if action == 'list':
        try:
            result = service.spreadsheets().values().get(
                spreadsheetId=sheet_id, range='A2:I').execute()
            rows = result.get('values', [])
            pocket_list = []
            for row in rows:
                if len(row) >= 3:
                    pocket_list.append({
                        'id': row[0],
                        'category': row[1],
                        'name': row[2],
                        'location': row[3] if len(row) > 3 else '',
                        'area': row[4] if len(row) > 4 else '',
                        'note': row[5] if len(row) > 5 else '',
                        'time': row[6] if len(row) > 6 else '',
                        'lat': row[7] if len(row) > 7 else None,
                        'lng': row[8] if len(row) > 8 else None
                    })
            return pocket_list
        except Exception as e:
            print(f"Error listing pocket items: {e}")
            return []

    elif action == 'add':
        try:
            item_id = str(uuid.uuid4())[:8] # 簡短 ID
            category = data.get('category', '其他')
            name = data.get('name', '')
            location = data.get('location', '')
            area = data.get('area', '')
            note = data.get('note', '')
            create_time = datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')
            
            # 優先使用前端傳來的經緯度，若無則嘗試後端抓取
            lat = data.get('lat')
            lng = data.get('lng')
            if lat is None or lng is None:
                lat, lng = get_lat_lng(location or name)
            
            values = [[item_id, category, name, location, area, note, create_time, lat, lng]]
            body = {'values': values}
            service.spreadsheets().values().append(
                spreadsheetId=sheet_id, range='A2',
                valueInputOption='RAW', body=body).execute()
            return True
        except Exception as e:
            print(f"Error adding pocket item: {e}")
            return False

    elif action == 'delete':
        try:
            target_id = data.get('id')
            # 1. 先獲取試算表資訊，找出第一個分頁的 sheetId
            spreadsheet_metadata = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
            first_sheet_id = spreadsheet_metadata['sheets'][0]['properties']['sheetId']

            # 2. 找出 ID 所在的行號
            result = service.spreadsheets().values().get(
                spreadsheetId=sheet_id, range='A:A').execute()
            ids = result.get('values', [])
            
            row_index = -1
            for i, row in enumerate(ids):
                if row and row[0] == target_id:
                    row_index = i
                    break
            
            if row_index == -1:
                return False

            # 3. 刪除該行
            body = {
                'requests': [{
                    'deleteDimension': {
                        'range': {
                            'sheetId': first_sheet_id,
                            'dimension': 'ROWS',
                            'startIndex': row_index,
                            'endIndex': row_index + 1
                        }
                    }
                }]
            }
            service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body=body).execute()
            return True
        except Exception as e:
            print(f"Error deleting pocket item: {e}")
            return False

    elif action == 'update_category':
        try:
            target_id = data.get('id')
            new_cat = data.get('category', '常用')

            result = service.spreadsheets().values().get(
                spreadsheetId=sheet_id, range='A:A').execute()
            ids = result.get('values', [])

            row_index = -1
            for i, row in enumerate(ids):
                if row and row[0] == target_id:
                    row_index = i + 1
                    break

            if row_index == -1:
                return False

            body = {'values': [[new_cat]]}
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id, range=f'B{row_index}',
                valueInputOption='RAW', body=body).execute()
            return True
        except Exception as e:
            print(f"Error updating pocket item category: {e}")
            return False

    elif action == 'update_note':
        try:
            target_id = data.get('id')
            new_note = data.get('note', '')

            result = service.spreadsheets().values().get(
                spreadsheetId=sheet_id, range='A:A').execute()
            ids = result.get('values', [])

            row_index = -1
            for i, row in enumerate(ids):
                if row and row[0] == target_id:
                    row_index = i + 1
                    break

            if row_index == -1:
                return False

            # 在 Google Sheet 中，備註對應的是第 6 欄 (Column F，即 'F' + row_index)
            body = {'values': [[new_note]]}
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id, range=f'F{row_index}',
                valueInputOption='RAW', body=body).execute()
            return True
        except Exception as e:
            print(f"Error updating pocket item note: {e}")
            return False

@app.route('/api/pocket/delete', methods=['POST'])
def delete_pocket_item():
    data = request.json
    success = handle_pocket('delete', data)
    if success:
        return jsonify({"status": "success", "message": "已刪除"})
    return jsonify({"status": "error", "message": "刪除失敗"})

@app.route('/api/pocket/update_note', methods=['POST'])
def update_pocket_note():
    data = request.json
    success = handle_pocket('update_note', data)
    if success:
        return jsonify({"status": "success", "message": "已更新自訂稱呼！"})
    return jsonify({"status": "error", "message": "更新失敗"})

@app.route('/api/pocket/list')
def get_pocket_list():
    items = handle_pocket('list')
    return jsonify({"status": "success", "data": items})

@app.route('/api/pocket/add', methods=['POST'])
def add_pocket_item():
    data = request.json
    success = handle_pocket('add', data)
    if success:
        return jsonify({"status": "success", "message": "成功存入口袋名單！📍"})
    return jsonify({"status": "error", "message": "存入失敗"})

@app.route('/api/pocket/update_category', methods=['POST'])
def update_pocket_category():
    data = request.json
    success = handle_pocket('update_category', data)
    if success:
        return jsonify({"status": "success", "message": "已成功將景點移入常用地址！📌"})
    return jsonify({"status": "error", "message": "移入失敗"})

# --- 🌸 健康與 AI 訓練 API ---
@app.route('/api/health/info', methods=['GET'])
def get_health_info():
    health_id = os.getenv('HEALTH_SHEET_ID')
    if not health_id:
         return jsonify({"status": "error", "message": "尚未設定 HEALTH_SHEET_ID"})
    try:
        rows = get_sheet_values('生理紀錄', spreadsheet_id=health_id)
        if not rows or len(rows) < 2:
            return jsonify({"status": "success", "history": [], "avg_cycle": 28, "avg_length": 5, "days_until_next": 28, "next_date": ""})
            
        history = []
        cycles = []
        lengths = []
        
        for row in rows[1:]:
             # 0: 年度, 1: 月份, 2: 開始日期, 3: 結束日期, 4: 經期天數, 5: 週期天數, 6: 備註
             start_d = row[2] if len(row) > 2 else ""
             end_d = row[3] if len(row) > 3 and row[3].strip() else "進行中"
             symptoms = row[6] if len(row) > 6 else ""
             
             if start_d:
                 history.append({"start": start_d, "end": end_d, "symptoms": symptoms})
                 
             try:
                 if len(row) > 5 and row[5].strip():
                     cycles.append(int(row[5]))
                 if len(row) > 4 and row[4].strip():
                     lengths.append(int(row[4]))
             except: pass
                 
        avg_cycle = round(sum(cycles)/len(cycles)) if cycles else 31
        avg_length = round(sum(lengths)/len(lengths)) if lengths else 7
        
        days_until_next = 0
        next_date_str = "未定"
        status_title = "距離下次預測"
        is_ongoing = False
        
        if history:
            latest_start = history[0]["start"] # 最上面那筆是最新
            latest_end = history[0]["end"]
            try:
                # datetime 轉換
                last_dt = datetime.strptime(latest_start, "%Y/%m/%d")
                # 計算距離今天幾天
                now = datetime.now(TW_TZ)
                
                if latest_end == "進行中" or latest_end.strip() == "":
                    # 進行中：計算目前是經期第幾天 (台灣時區精準計算)
                    days_in_period = (now.date() - last_dt.date()).days + 1
                    days_until_next = days_in_period if days_in_period > 0 else 1
                    status_title = "🌸 經期第"
                    next_date_str = "進行中..."
                    is_ongoing = True
                else:
                    # 非進行中：計算距離下次預測還有幾天
                    next_dt = last_dt + timedelta(days=avg_cycle)
                    diff = (next_dt.date() - now.date()).days
                    days_until_next = diff if diff >= 0 else 0
                    status_title = "距離下次預測"
                    next_date_str = next_dt.strftime("%Y/%m/%d")
                    is_ongoing = False
            except Exception as e:
                print(f"Date parse error: {e}")
        
        return jsonify({
            "status": "success",
            "history": history[:3],
            "avg_cycle": avg_cycle,
            "avg_length": avg_length,
            "days_until_next": days_until_next,
            "next_date": next_date_str,
            "status_title": status_title,
            "is_ongoing": is_ongoing
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/health/record_start', methods=['POST'])
def record_health_start():
    health_id = os.getenv('HEALTH_SHEET_ID')
    if not health_id: return jsonify({"status": "error", "message": "未設定 HEALTH_SHEET_ID"})
    
    try:
        service_sheets = build('sheets', 'v4', credentials=creds)
        rows = get_sheet_values('生理紀錄', spreadsheet_id=health_id)
        
        # 1. 檢查是否已經在進行中
        if len(rows) > 1:
             latest_end = rows[1][3] if len(rows[1]) > 3 else "進行中"
             if latest_end == "進行中" or latest_end.strip() == "":
                 return jsonify({"status": "error", "message": "目前已經有進行中的紀錄囉！"})
                 
        # 計算平均天數
        cycles = []
        lengths = []
        for row in rows[1:]:
             try:
                 if len(row) > 5 and row[5].strip(): cycles.append(int(row[5]))
                 if len(row) > 4 and row[4].strip(): lengths.append(int(row[4]))
             except: pass
        avg_cycle = round(sum(cycles)/len(cycles)) if cycles else 31
        avg_length = round(sum(lengths)/len(lengths)) if lengths else 7
        
        now = datetime.now(TW_TZ)
        today_str = now.strftime("%Y/%m/%d")
        
        # 計算週期天數 (與上一次的間距)
        cycle_days = ""
        if len(rows) > 1 and len(rows[1]) > 2:
             last_start_str = rows[1][2]
             try:
                 last_dt = datetime.strptime(last_start_str, "%Y/%m/%d").replace(tzinfo=TW_TZ)
                 cycle_days = str((now - last_dt).days)
             except: pass
             
        # 2. 寫入新紀錄到試算表 (插入在第二列)
        new_row = [now.strftime("%Y"), now.strftime("%m"), today_str, "進行中", "", "", ""]
        
        sh = service_sheets.spreadsheets().get(spreadsheetId=health_id).execute()
        sheet_id = next(s['properties']['sheetId'] for s in sh['sheets'] if s['properties']['title'] == '生理紀錄')
        
        # 插入新的一列
        requests = [{
            "insertDimension": {
                "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 1, "endIndex": 2},
                "inheritFromBefore": False
            }
        }]
        service_sheets.spreadsheets().batchUpdate(spreadsheetId=health_id, body={"requests": requests}).execute()
        
        # 寫入新資料到 A2
        service_sheets.spreadsheets().values().update(
            spreadsheetId=health_id, range="生理紀錄!A2",
            valueInputOption="USER_ENTERED", body={"values": [new_row]}
        ).execute()
        
        # 如果有算出週期天數，更新上一筆 (原本的第2列變成第3列)
        if cycle_days:
            service_sheets.spreadsheets().values().update(
                spreadsheetId=health_id, range="生理紀錄!F3",
                valueInputOption="USER_ENTERED", body={"values": [[cycle_days]]}
            ).execute()
        
        # 3. 日曆操作
        service_cal = build('calendar', 'v3', credentials=creds)
        
        # 刪除未來所有的 🌸 (預測) 行程
        time_min = now.isoformat()
        events_result = service_cal.events().list(calendarId=CALENDAR_ID, timeMin=time_min, q="🌸 (預測)").execute()
        for event in events_result.get('items', []):
            if "🌸 (預測)" in event.get('summary', ''):
                service_cal.events().delete(calendarId=CALENDAR_ID, eventId=event['id']).execute()
                
        # 排入本次生理期
        for i in range(avg_length):
            day_dt = now + timedelta(days=i)
            event_body = {
                'summary': f'🌸 生理期 (第{i+1}天)',
                'start': {'date': day_dt.strftime("%Y-%m-%d")},
                'end': {'date': (day_dt + timedelta(days=1)).strftime("%Y-%m-%d")}
            }
            service_cal.events().insert(calendarId=CALENDAR_ID, body=event_body).execute()
            
        # 排入下次預測
        next_start_dt = now + timedelta(days=avg_cycle)
        for i in range(avg_length):
            day_dt = next_start_dt + timedelta(days=i)
            event_body = {
                'summary': f'🌸 (預測) 生理期',
                'start': {'date': day_dt.strftime("%Y-%m-%d")},
                'end': {'date': (day_dt + timedelta(days=1)).strftime("%Y-%m-%d")}
            }
            service_cal.events().insert(calendarId=CALENDAR_ID, body=event_body).execute()
            
        return jsonify({"status": "success", "message": "已記錄開始，並排入日曆與未來預測！🌸"})
        
    except Exception as e:
        print(f"Record start error: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/health/record_end', methods=['POST'])
def record_health_end():
    health_id = os.getenv('HEALTH_SHEET_ID')
    if not health_id: return jsonify({"status": "error", "message": "未設定 HEALTH_SHEET_ID"})
    
    try:
        service_sheets = build('sheets', 'v4', credentials=creds)
        rows = get_sheet_values('生理紀錄', spreadsheet_id=health_id)
        
        if len(rows) < 2: return jsonify({"status": "error", "message": "沒有找到紀錄可以結束。"})
        
        latest_end = rows[1][3] if len(rows[1]) > 3 else ""
        if latest_end != "進行中" and latest_end.strip() != "":
             return jsonify({"status": "error", "message": "最新紀錄已經結束囉！"})
             
        start_str = rows[1][2]
        now = datetime.now(TW_TZ)
        today_str = now.strftime("%Y/%m/%d")
        
        length_days = ""
        try:
             start_dt = datetime.strptime(start_str, "%Y/%m/%d").replace(tzinfo=TW_TZ)
             length_days = str((now - start_dt).days + 1)
        except: pass
        
        body = {"values": [[today_str, length_days]]}
        service_sheets.spreadsheets().values().update(
            spreadsheetId=health_id, range="生理紀錄!D2:E2",
            valueInputOption="USER_ENTERED", body=body
        ).execute()
        
        return jsonify({"status": "success", "message": "已記錄結束，辛苦了！✅"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/health/symptoms/options', methods=['GET', 'POST', 'DELETE'])
def manage_symptoms_options():
    health_id = os.getenv('HEALTH_SHEET_ID')
    if not health_id: return jsonify({"status": "error", "message": "未設定 HEALTH_SHEET_ID"})
    
    service = build('sheets', 'v4', credentials=creds)
    try:
        if request.method == 'GET':
            rows = get_sheet_values('症狀選項', spreadsheet_id=health_id)
            options = [r[0] for r in rows[1:] if len(r) > 0 and r[0].strip()]
            return jsonify({"status": "success", "data": options})
            
        elif request.method == 'POST':
            new_option = request.json.get('option', '').strip()
            if not new_option: return jsonify({"status": "error", "message": "選項不能為空"})
            
            body = {'values': [[new_option]]}
            service.spreadsheets().values().append(
                spreadsheetId=health_id, range="症狀選項!A:A",
                valueInputOption="USER_ENTERED", body=body
            ).execute()
            return jsonify({"status": "success", "message": "已新增選項"})
            
        elif request.method == 'DELETE':
            target_option = request.json.get('option', '').strip()
            if not target_option: return jsonify({"status": "error", "message": "請指定要刪除的選項"})
            
            rows = get_sheet_values('症狀選項', spreadsheet_id=health_id)
            if not rows: return jsonify({"status": "success"})
            
            new_rows = [r for r in rows if len(r) == 0 or r[0].strip() != target_option]
            
            # 清空原本範圍
            service.spreadsheets().values().clear(spreadsheetId=health_id, range="症狀選項!A:A").execute()
            # 寫回新的
            service.spreadsheets().values().update(
                spreadsheetId=health_id, range="症狀選項!A1",
                valueInputOption="USER_ENTERED", body={"values": new_rows}
            ).execute()
            return jsonify({"status": "success", "message": "已刪除選項"})
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/health/symptoms/record', methods=['POST'])
def record_symptoms():
    health_id = os.getenv('HEALTH_SHEET_ID')
    if not health_id: return jsonify({"status": "error", "message": "未設定 HEALTH_SHEET_ID"})
    
    selected = request.json.get('symptoms', [])
    symptoms_str = "、".join(selected)
    
    try:
        # 我們假設寫入最新的一筆 (第二列)
        service = build('sheets', 'v4', credentials=creds)
        service.spreadsheets().values().update(
            spreadsheetId=health_id, range="生理紀錄!G2",
            valueInputOption="USER_ENTERED", body={"values": [[symptoms_str]]}
        ).execute()
        return jsonify({"status": "success", "message": "症狀已記錄！🩺"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/training/rules', methods=['GET'])
def get_training_rules():
    health_id = os.getenv('HEALTH_SHEET_ID')
    if not health_id: return jsonify({"status": "error", "message": "未設定 HEALTH_SHEET_ID"})
    try:
        rows = get_sheet_values('AI_指令集', spreadsheet_id=health_id)
        rules = []
        if rows and len(rows) > 1:
            for r in rows[1:]:
                 if len(r) >= 2 and r[0].strip():
                     rules.append({"trigger": r[0], "action": r[1]})
        return jsonify({"status": "success", "data": rules})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/training/add_rule', methods=['POST'])
def add_training_rule():
    data = request.json
    health_id = os.getenv('HEALTH_SHEET_ID')
    if not health_id: return jsonify({"status": "error", "message": "未設定 HEALTH_SHEET_ID"})
    trigger = data.get('trigger', '')
    action = data.get('action', '')
    if not trigger or not action: return jsonify({"status": "error", "message": "請輸入完整規則"})
    
    now = datetime.now(TW_TZ)
    row = [trigger, action, now.strftime("%Y-%m-%d %H:%M:%S")]
    try:
        append_to_sheet('AI_指令集', row, spreadsheet_id=health_id)
        return jsonify({"status": "success", "message": "訓練指令已寫入大腦！🧠"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)
