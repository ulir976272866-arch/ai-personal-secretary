import os
# 本地開發允許使用 HTTP 進行 OAuth 驗證 (防止 InsecureTransportError)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
# 允許 OAuth Token 範圍變更 (防止 Scope has changed Warning 導致崩潰)
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
import json
import uuid
import requests
from datetime import datetime, time, timedelta, timezone
from PIL import Image

# 定義台灣時區 (UTC+8) 的動態時區委託代理 (Dynamic Timezone Proxy)
# 當處於 Web 請求 context 時，自動依據使用者當前的 session 時區調整；
# 非請求 context（如啟動初始化）或未設定時，預設為台北時間 (UTC+8)
from datetime import tzinfo
class DynamicTimezone(tzinfo):
    def get_inner_tz(self):
        try:
            from flask import has_request_context, session
            if has_request_context() and 'timezone' in session:
                tz_name = session['timezone']
                import pytz
                return pytz.timezone(tz_name)
        except Exception as e:
            print(f"DynamicTimezone parsing error: {e}")
        return timezone(timedelta(hours=8))

    def utcoffset(self, dt):
        return self.get_inner_tz().utcoffset(dt)
        
    def tzname(self, dt):
        return self.get_inner_tz().tzname(dt)
        
    def dst(self, dt):
        return self.get_inner_tz().dst(dt)
        
    def fromutc(self, dt):
        inner_tz = self.get_inner_tz()
        dt_inner = dt.replace(tzinfo=inner_tz)
        res_inner = inner_tz.fromutc(dt_inner)
        return res_inner.replace(tzinfo=self)

TW_TZ = DynamicTimezone()

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from dotenv import load_dotenv
import google.generativeai as genai
from google.oauth2.service_account import Credentials as SACredentials
from google.oauth2.credentials import Credentials as OAuthCredentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# 載入環境變數 (確保能讀到腳本同目錄下的 .env)
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "ai_personal_secretary_super_secret_key_12345")

# -----------------------------------------------------------------
# 1. Google OAuth 2.0 與 Service Account 初始化
# -----------------------------------------------------------------
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/userinfo.email'
]

# 載入 Service Account (做為沒有登入時的後備機制)
SERVICE_ACCOUNT_FILE = os.path.join(os.path.dirname(__file__), 'service_account.json')
creds_sa = None
sa_json = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
if sa_json:
    try:
        creds_sa = SACredentials.from_service_account_info(json.loads(sa_json), scopes=SCOPES)
        print("Success: Loaded backup credentials from GOOGLE_SERVICE_ACCOUNT_JSON")
    except Exception as e:
        print(f"Error loading backup credentials from env: {e}")

if not creds_sa and os.path.exists(SERVICE_ACCOUNT_FILE):
    try:
        creds_sa = SACredentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        print("Success: Loaded backup credentials from service_account.json")
    except Exception as e:
        print(f"Error loading backup credentials from file: {e}")

# --- OAuth 憑證輔助函數 ---
CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

def get_client_config():
    return {
        "web": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs"
        }
    }

def get_flow():
    redirect_uri = request.url_root.rstrip('/') + '/callback'
    # 確保 Cloud Run 生產環境下使用 https 重新導向，防止 http 混合內容報錯
    if 'localhost' not in redirect_uri and '127.0.0.1' not in redirect_uri:
        if redirect_uri.startswith('http://'):
            redirect_uri = 'https://' + redirect_uri[7:]
    
    return Flow.from_client_config(
        get_client_config(),
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )

def get_valid_credentials():
    if 'credentials' not in session:
        return None
    creds_data = session['credentials']
    creds = OAuthCredentials(
        token=creds_data.get('token'),
        refresh_token=creds_data.get('refresh_token'),
        token_uri=creds_data.get('token_uri'),
        client_id=creds_data.get('client_id'),
        client_secret=creds_data.get('client_secret'),
        scopes=creds_data.get('scopes')
    )
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            session['credentials'] = {
                'token': creds.token,
                'refresh_token': creds.refresh_token,
                'token_uri': creds.token_uri,
                'client_id': creds.client_id,
                'client_secret': creds.client_secret,
                'scopes': creds.scopes
            }
        except Exception as e:
            print(f"Error refreshing OAuth credentials: {e}")
            return None
    return creds

def get_sheets_service():
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "true":
        if creds_sa:
            return build('sheets', 'v4', credentials=creds_sa)
    creds = get_valid_credentials()
    if creds:
        return build('sheets', 'v4', credentials=creds)
    if creds_sa:
        return build('sheets', 'v4', credentials=creds_sa)
    return build('sheets', 'v4')

def get_calendar_service():
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "true":
        if creds_sa:
            return build('calendar', 'v3', credentials=creds_sa)
    creds = get_valid_credentials()
    if creds:
        return build('calendar', 'v3', credentials=creds)
    if creds_sa:
        return build('calendar', 'v3', credentials=creds_sa)
    return build('calendar', 'v3')

def get_drive_service():
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "true":
        if creds_sa:
            return build('drive', 'v3', credentials=creds_sa)
    creds = get_valid_credentials()
    if creds:
        return build('drive', 'v3', credentials=creds)
    if creds_sa:
        return build('drive', 'v3', credentials=creds_sa)
    return build('drive', 'v3')

def get_user_info():
    creds = get_valid_credentials()
    if not creds:
        return None
    try:
        oauth2_service = build('oauth2', 'v2', credentials=creds)
        user_info = oauth2_service.userinfo().get().execute()
        return user_info
    except Exception as e:
        print(f"Error getting user info: {e}")
        return None

def get_spreadsheet_id():
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "true":
        return os.getenv("GOOGLE_SHEET_ID")
    if 'spreadsheet_id' in session:
        return session['spreadsheet_id']
    return os.getenv("GOOGLE_SHEET_ID")

def get_calendar_id():
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "true":
        return os.getenv("GOOGLE_CALENDAR_ID", "primary")
    if 'credentials' in session:
        return "primary"
    return os.getenv("GOOGLE_CALENDAR_ID", "primary")

from werkzeug.local import LocalProxy
SPREADSHEET_ID = LocalProxy(lambda: get_spreadsheet_id())
CALENDAR_ID = LocalProxy(lambda: get_calendar_id())
def ensure_user_spreadsheet():
    """
    檢查使用者雲端硬碟是否有 AI_Personal_Secretary_Data。
    若無則自動在使用者個人雲端硬碟建立一組全新的資料表並初始化所有欄位。
    """
    if 'spreadsheet_id' in session:
        return session['spreadsheet_id']
        
    # 如果是創作者本人的 Email 登入，直接回傳最原始的歷史資料表，避免新建空白表！
    try:
        user_info = get_user_info()
        if user_info and user_info.get('email') == os.getenv("GOOGLE_CALENDAR_ID"):
            session['spreadsheet_id'] = os.getenv("GOOGLE_SHEET_ID")
            print(f"Owner logged in. Reusing existing original spreadsheet: {os.getenv('GOOGLE_SHEET_ID')}")
            return os.getenv("GOOGLE_SHEET_ID")
    except Exception as e:
        print(f"Error checking owner email in ensure_user_spreadsheet: {e}")
        
    creds = get_valid_credentials()
    if not creds:
        return os.getenv("GOOGLE_SHEET_ID")
        
    try:
        drive_service = get_drive_service()
        sheets_service = get_sheets_service()
        
        spreadsheet_name = "AI_Personal_Secretary_Data"
        query = f"name = '{spreadsheet_name}' and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
        results = drive_service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        files = results.get('files', [])
        
        if files:
            spreadsheet_id = files[0]['id']
            session['spreadsheet_id'] = spreadsheet_id
            print(f"Found existing spreadsheet in user drive: {spreadsheet_id}")
            return spreadsheet_id
            
        print("Spreadsheet not found in user drive. Creating and initializing a brand new one...")
        spreadsheet_metadata = {
            'properties': {
                'title': spreadsheet_name
            }
        }
        spreadsheet = sheets_service.spreadsheets().create(
            body=spreadsheet_metadata,
            fields='spreadsheetId'
        ).execute()
        spreadsheet_id = spreadsheet.get('spreadsheetId')
        
        # 取得預設建立的 sheet ID 並進行多表初始化
        sheet_meta = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        default_sheet_id = sheet_meta['sheets'][0]['properties']['sheetId']
        
        requests_list = [
            {'addSheet': {'properties': {'title': '記帳'}}},
            {'addSheet': {'properties': {'title': '待辦'}}},
            {'addSheet': {'properties': {'title': '日記'}}},
            {'addSheet': {'properties': {'title': '願望'}}},
            {'addSheet': {'properties': {'title': '生理紀錄'}}},
            {'addSheet': {'properties': {'title': 'AI_指令集'}}},
            {'deleteSheet': {'sheetId': default_sheet_id}}
        ]
        
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={'requests': requests_list}
        ).execute()
        
        headers = {
            '記帳!A1:G1': [['年度', '月份', '日期', '收入項目', '支出項目', '金額', '類別']],
            '待辦!A1:F1': [['唯一 ID', '事項/內容', '優先級', '分類', '狀態', '建立時間']],
            '日記!A1:D1': [['日期', '心情', '天氣', '內容']],
            '願望!A1:F1': [['唯一 ID', '願望名稱', '預算', '狀態', '實際花費', '建立時間']],
            '生理紀錄!A1:F1': [['年度', '月份', '日期', '動作', '症狀/心情', '備註']],
            'AI_指令集!A1:B1': [['觸發語句', '執行動作']]
        }
        
        for range_name, values in headers.items():
            sheets_service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption='USER_ENTERED',
                body={'values': values}
            ).execute()
            
        # 寫入預設指令以訓練小秘書
        default_instructions = [
            ['當我說「累了」，排入一小時「放鬆休息」行程', '排入行程: 放鬆休息, 時間: 1小時'],
            ['當我說「吃大餐」，記帳支出「🍔 大餐」金額 500 元', '記帳支出: 🍔 大餐, 金額: 500元, 類別: 食']
        ]
        sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range='AI_指令集!A2:B',
            valueInputOption='USER_ENTERED',
            body={'values': default_instructions}
        ).execute()
        
        session['spreadsheet_id'] = spreadsheet_id
        print(f"Created and initialized new spreadsheet in user drive: {spreadsheet_id}")
        return spreadsheet_id
        
    except Exception as e:
        print(f"Error in ensure_user_spreadsheet: {e}")
        return os.getenv("GOOGLE_SHEET_ID")

# --- Sheets 輔助函數 ---
def append_to_sheet(range_name, values, spreadsheet_id=None):
    if not spreadsheet_id:
        spreadsheet_id = get_spreadsheet_id()
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
        spreadsheet_id = get_spreadsheet_id()
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

# 試算表與日曆 ID 的動態模組屬性代理 (多用戶執行緒安全隔離)
def __getattr__(name):
    if name == "SPREADSHEET_ID":
        return get_spreadsheet_id()
    if name == "CALENDAR_ID":
        return get_calendar_id()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

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
    service_sheets = get_sheets_service()
    
    # 抓取本月支出
    monthly_total, _, _, _ = get_monthly_report(service_sheets, now)
    
    # 為了省錢與節省額度，目前使用固定親切招呼
    reply = f"老闆早安！本月已支出 ${int(monthly_total):,}。祝您有美好的一天！"
    return jsonify({"status": "success", "message": reply})


def format_event_success_message(title, start_time_str, location, is_all_day=False, is_manual=False, prefix=None):
    """
    格式化行程新增成功後的詳細回饋訊息。
    """
    # 格式化日期與時間
    formatted_time_detail = "未定"
    try:
        if is_all_day:
            # 格式：YYYY-MM-DD
            dt_obj = datetime.strptime(start_time_str[:10], "%Y-%m-%d")
            formatted_date = dt_obj.strftime("%m月%d日")
            weekdays = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
            weekday = weekdays[dt_obj.weekday()]
            formatted_time_detail = f"{formatted_date} ({weekday}) 全天行程"
        else:
            # 格式：ISO dateTime
            clean_str = start_time_str.replace('Z', '+00:00')
            if 'T' in clean_str and '+' not in clean_str:
                clean_str += '+08:00'
            
            dt_obj = datetime.fromisoformat(clean_str)
            if dt_obj.tzinfo:
                dt_obj = dt_obj.astimezone(TW_TZ)
                
            formatted_date = dt_obj.strftime("%m月%d日")
            formatted_time = dt_obj.strftime("%H:%M")
            weekdays = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
            weekday = weekdays[dt_obj.weekday()]
            formatted_time_detail = f"{formatted_date} ({weekday}) {formatted_time}"
    except Exception as e:
        print(f"Error formatting success time: {e}")
        formatted_time_detail = start_time_str
        
    loc_str = location if location and location.strip() else "(未設定地點)"
    if not prefix:
        prefix = "✅ 手動新增行程成功！" if is_manual else "✅ 新增行程成功！"
    
    return f"{prefix}\n📅 時間：{formatted_time_detail}\n📍 地點：{loc_str}\n📌 行程：{title}"

@app.route('/')
def index():
    # 優先尋找專用地圖 Key，若無則嘗試共用 Gemini Key
    maps_api_key = os.getenv('GOOGLE_MAPS_API_KEY') or os.getenv('GEMINI_API_KEY')
    
    # 支援單人模式 (直接使用 Service Account，繞過登入)
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "true":
        return render_template(
            'index.html', 
            maps_api_key=maps_api_key, 
            logged_in=True, 
            user_info={
                "name": "個人秘書系統",
                "picture": "https://lh3.googleusercontent.com/a/default-user"
            },
            spreadsheet_id=SPREADSHEET_ID
        )
        
    logged_in = 'credentials' in session
    user_info = None
    if logged_in:
        user_info = get_user_info()
        # 若憑證過期或失效導致無法獲取 user_info，則強制登出以防畫面異常
        if not user_info:
            session.pop('credentials', None)
            session.pop('spreadsheet_id', None)
            logged_in = False
            
    return render_template(
        'index.html', 
        maps_api_key=maps_api_key, 
        logged_in=logged_in, 
        user_info=user_info,
        spreadsheet_id=SPREADSHEET_ID
    )

@app.route('/login')
def login():
    # 請求 offline 權限以取得 refresh_token，並強制要求 consent 彈窗確認
    flow = get_flow()
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    session['state'] = state
    # 將 PKCE code_verifier 存入 session，以便在 callback 路由中跨請求還原驗證
    session['code_verifier'] = flow.code_verifier
    return redirect(authorization_url)

@app.route('/callback')
def callback():
    # 嚴格的 CSRF 狀態比對驗證
    if request.args.get('state') != session.get('state'):
        return "安全性驗證失敗 (CSRF State Mismatch)！請返回首頁重登試試看。", 400
        
    # 確保 authorization_response 的 URL 協定為 https，以繞過 oauthlib 的 InsecureTransportError
    auth_resp = request.url
    if auth_resp.startswith('http://'):
        auth_resp = 'https://' + auth_resp[7:]

    flow = get_flow()
    # 還原 PKCE 的 code_verifier，防止 Google 驗證回報 (invalid_grant) Missing code verifier 錯誤
    if 'code_verifier' in session:
        flow.code_verifier = session['code_verifier']
        
    flow.fetch_token(authorization_response=auth_resp)
    
    # 將 OAuth 金鑰資料保存至 Session 中
    creds = flow.credentials
    session['credentials'] = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': creds.scopes
    }
    
    # 背景自動初始化或檢查試算表資料庫
    ensure_user_spreadsheet()
    
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/api/sync_profile', methods=['POST'])
def sync_profile():
    """同步前端設定的性別、生理期啟用狀態與時區"""
    data = request.json or {}
    gender = data.get('gender', 'girl')
    enable_period = data.get('enable_period', True)
    timezone_str = data.get('timezone', 'Asia/Taipei')
    
    session['user_gender'] = gender
    session['enable_period'] = enable_period
    session['timezone'] = timezone_str
    
    print(f"Profile synced: gender={gender}, enable_period={enable_period}, timezone={timezone_str}")
    return jsonify({
        "status": "success",
        "gender": gender,
        "enable_period": enable_period,
        "timezone": timezone_str
    })

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

    creds = get_valid_credentials()
    if not creds and not creds_sa:
        return jsonify({"status": "error", "message": "找不到任何有效的 Google 憑證 (請先登入或設定 service_account.json)"}), 400

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
            service_sheets = get_sheets_service()
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

        # 讀取生理期助理狀態以動態調整 AI 對話關懷人格
        cycle_info_str = ""
        is_boy = session.get('user_gender') == 'boy'
        enable_period = session.get('enable_period') != False

        if is_boy or not enable_period:
            cycle_info_str = """
        【極重要人設與內容限制】：
        - 當前使用者為「男性」或已「停用生理健康追蹤」。
        - 在所有行程安排、日記分析、財務問答以及日常對話中，你『絕對禁止』提及任何生理期、月經、經痛、黑糖薑茶、女性調養等話題。
        - 當使用者說「我累了」、「身體不舒服」、「肚子痛」等，請完全從工作疲勞、消化不良、感冒受涼等大眾化角度進行溫馨體貼的問候與叮嚀，絕對不要聯想到任何經期或女性生理方面。
"""
        else:
            try:
                cycle_status = get_current_cycle_status()
                if cycle_status:
                    cycle_info_str = f"""
        【女性生理週期秘書感知】(當前用戶生理狀態)：
        - 今天是週期的第 {cycle_status['days_in_cycle']} 天。
        - 當前生理階段：{cycle_status['current_phase']} ({cycle_status['phase_icon']})
        - 懷孕機率備註：{cycle_status['pregnancy_probability']}
        - 貼心叮嚀與特徵：{cycle_status['phase_desc']}
        - 當前預測說明：{cycle_status['status_title']}{cycle_status['days_until_next']}天 (預測日期為 {cycle_status['next_date']})。
        
        【AI 暖心語氣調整指引】：
        - 請對使用者展現極致溫柔、體貼、包容且有溫度的語氣，像一位最懂她、陪伴在她身邊的好閨蜜。
        - 根據當前生理階段給予「主動」且「自然」的貼心問候與叮嚀：
          * 當前為「生理期」：說話極致溫柔，主動提醒多喝熱水、黑糖薑茶，叮嚀不要喝冷飲，不要勉強自己，展現最高限度的呵護與寵溺。
          * 當前為「安全期 (濾泡期)」：語氣充滿朝氣與活力，多給予正面肯定，鼓勵她大膽嘗試新事物或安排運動。
          * 當前為「排卵期 (黃體前期)」：主動讚美她這幾天氣色很好、散發光芒與魅力，適合多出門走走、約會或社交.
          * 當前為「黃體期 (經前期)」：理解她可能容易水腫、疲憊、經前不適或情緒浮躁，用最令人安心的溫柔語氣主動安撫、聆聽，建議她深度放鬆，陪伴她度過波動期。
"""
            except Exception as e:
                print(f"Error loading cycle status for prompt: {e}")

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

        try:
            model = genai.GenerativeModel('gemini-3.1-flash-lite')
            contents = [prompt]
            if user_text: contents.append(f"使用者：{user_text}")
            if image_file: contents.append(Image.open(image_file))
            
            response = model.generate_content(contents)
            text = response.text.replace('```json', '').replace('```', '').strip()
            
            data = json.loads(text)
            parsed_data = data[0] if isinstance(data, list) and len(data) > 0 else data
            print(f"Parsed AI response: {parsed_data}")
        except Exception as e:
            print(f"Gemini AI Error: {e}")
            return jsonify({"status": "error", "message": "AI 處理失敗，請稍後再試。"})

    ai_response_message = None
    if isinstance(parsed_data, dict):
        if "response" in parsed_data:
            ai_response_message = parsed_data.pop("response", None)
        elif "reply" in parsed_data:
            ai_response_message = parsed_data.pop("reply", None)
        elif "message" in parsed_data:
            ai_response_message = parsed_data.pop("message", None)
            
        if "data" in parsed_data and isinstance(parsed_data["data"], dict):
            # If there's a nested 'data' key, merge its keys back or use it, and preserve the greeting
            nested_data = parsed_data["data"]
            if isinstance(nested_data, dict):
                if "response" in nested_data and not ai_response_message:
                    ai_response_message = nested_data.pop("response", None)
                if "reply" in nested_data and not ai_response_message:
                    ai_response_message = nested_data.pop("reply", None)
                if "message" in nested_data and not ai_response_message:
                    ai_response_message = nested_data.pop("message", None)
                parsed_data = nested_data

    intent_type = parsed_data.get("type") if isinstance(parsed_data, dict) else None
    try:
        if intent_type == "calendar":
            service = get_calendar_service()
            
            start_time_str = parsed_data.get('start_time')
            if not start_time_str:
                return jsonify({"status": "error", "message": "❌ AI 解析失敗：遺失開始時間。"})
            
            is_all_day = False
            if len(start_time_str) <= 10 or 'T' not in start_time_str:
                is_all_day = True
                start_date = start_time_str[:10]
                dt = datetime.strptime(start_date, '%Y-%m-%d')
                end_date = (dt + timedelta(days=1)).strftime('%Y-%m-%d')
                
                event = {
                    'summary': parsed_data.get('title'),
                    'location': parsed_data.get('location', ''),
                    'start': { 'date': start_date, 'timeZone': 'Asia/Taipei' },
                    'end': { 'date': end_date, 'timeZone': 'Asia/Taipei' },
                }
            else:
                is_all_day = False
                start_str = start_time_str
                if 'T' in start_str and '+' not in start_str and 'Z' not in start_str:
                    start_str += '+08:00'
                start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                
                end_str = parsed_data.get('end_time')
                if end_str:
                    if 'T' in end_str and '+' not in end_str and 'Z' not in end_str:
                        end_str += '+08:00'
                    end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                else:
                    end_dt = start_dt + timedelta(hours=1)
                
                event = {
                    'summary': parsed_data.get('title'),
                    'location': parsed_data.get('location', ''),
                    'start': { 'dateTime': start_dt.isoformat(), 'timeZone': 'Asia/Taipei' },
                    'end': { 'dateTime': end_dt.isoformat(), 'timeZone': 'Asia/Taipei' },
                }
                
            conflict_msg = check_conflicts(
                service, 
                event['start'].get('dateTime', event['start'].get('date')), 
                event['end'].get('dateTime', event['end'].get('date'))
            )
            if conflict_msg: 
                return jsonify({"status": "error", "message": conflict_msg})
                
            service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
            
            success_msg = format_event_success_message(
                title=parsed_data.get('title'),
                start_time_str=start_time_str,
                location=parsed_data.get('location', ''),
                is_all_day=is_all_day,
                is_manual=False
            )
            if ai_response_message:
                success_msg = f"{ai_response_message}\n\n{success_msg}"
            return jsonify({"status": "success", "type": "calendar", "message": success_msg})

        elif intent_type == "expense":
            service = get_sheets_service()
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
            msg = f"{emoji} 已記{label}：{parsed_data.get('item')} ${parsed_data.get('amount')}\n\n{cat_report}"
            if ai_response_message:
                msg = f"{ai_response_message}\n\n{msg}"
            return jsonify({"status": "success", "type": "expense", "message": msg, "chart_data": cat_dict})

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
            service = get_sheets_service()
            _, cat_report, cat_dict, _ = get_monthly_report(service, now)
            return jsonify({"status": "success", "type": "expense_report", "message": f"📊 本月結算：\n\n{cat_report}", "chart_data": cat_dict})

        elif intent_type == "delete_last_expense":
            service = get_sheets_service()
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
            
        creds = get_valid_credentials()
        if not creds and not creds_sa:
             return jsonify({"status": "error", "message": "尚未設定 Google 憑證"}), 500
             
        service = get_calendar_service()
        
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
        service_sheets = get_sheets_service()
        _, cat_report, _, _ = get_monthly_report(service_sheets, now)
        
        msg = f"📊 {now.year}年{now.month}月 記帳小結：\n\n"
        msg += cat_report
        
        return jsonify({"status": "success", "type": "chat", "message": msg})
    except Exception as e:
        print(f"Finance Query Error: {e}")
        return jsonify({"status": "error", "message": f"計算失敗：{str(e)}"})

def get_schedule_response(days):
    """查詢當前與未來行程的共通回傳格式"""
    now = datetime.now(TW_TZ)
    try:
        service = get_calendar_service()
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
        end_str = e['end'].get('dateTime', e['end'].get('date'))
        
        schedule_list.append({
            'id': e['id'], 'time': time_val, 'title': display_title,
            'display_title': final_title, 'completed': is_done,
            'location': e.get('location', ''), 'start_time': start_str,
            'end_time': end_str,
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
        service = get_calendar_service()
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
        display_title = full_title.replace("✅ ", "", 1) if is_done else full_title
        
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
            'location': e.get('location', ''), 'start_time': start_str, 'completed': is_done
        })
        
    if not completed_list:
        k_str = f"關鍵字「{keyword}」" if keyword else ""
        return jsonify({
            "status": "success",
            "type": "chat",
            "message": f"🔍 過去 {days} 天內，沒有找到任何符合{k_str}的行程喔！"
        })
        
    # Generate direct clean message for LINE / fallback
    msg = f"🔍 幫您找到過去 {days} 天內的行程：\n\n"
    for i, item in enumerate(completed_list, 1):
        status_label = " [已完成]" if item['completed'] else " [未完成]"
        time_label = f" ({item['time']})" if item['time'] != '全天' else " (全天)"
        loc_label = f"\n📍 地址：{item['location']}" if item['location'] else ""
        msg += f"{i}. [{item['date']}] {item['title']}{status_label}{time_label}{loc_label}\n"
        
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
            service = get_calendar_service()
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
                duration = int(data.get('duration', 60))
                end_dt = start_dt + timedelta(minutes=duration)
                
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
            
            success_msg = format_event_success_message(
                title=data.get('title'),
                start_time_str=data.get('start_time'),
                location=data.get('location', ''),
                is_all_day=is_all_day,
                is_manual=True
            )
            return jsonify({"status": "success", "message": success_msg})

        elif action_type == 'expense':
            # 手動記帳
            if not SPREADSHEET_ID:
                return jsonify({"status": "error", "message": "尚未設定 GOOGLE_SHEET_ID"}), 400
                
            service = get_sheets_service()
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
        service = get_calendar_service()
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
        service = get_calendar_service()
        
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
            duration = int(data.get('duration', 60))
            end_dt = start_dt + timedelta(minutes=duration)
            
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
        success_msg = format_event_success_message(
            title=summary,
            start_time_str=event['start'].get('dateTime', event['start'].get('date')),
            location=location,
            is_all_day=is_all_day,
            is_manual=True,
            prefix="✅ 行程更新成功！"
        )
        return jsonify({"status": "success", "message": success_msg})
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
    service = get_sheets_service()

    if action == 'list':
        try:
            result = service.spreadsheets().values().get(
                spreadsheetId=sheet_id, range='A2:I').execute()
            rows = result.get('values', [])
            pocket_list = []
            for row in rows:
                if len(row) >= 3:
                    loc_val = row[3] if len(row) > 3 else ''
                    area_val = row[4] if len(row) > 4 else ''
                    if not area_val and loc_val:
                        cities = ["台北市", "新北市", "桃園市", "台中市", "台南市", "高雄市", 
                                  "基隆市", "新竹市", "嘉義市", "新竹縣", "苗栗縣", "彰化縣", "南投縣", 
                                  "雲林縣", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣", "台東縣", "澎湖縣", "金門縣", "連江縣"]
                        for city in cities:
                            if city in loc_val:
                                area_val = city
                                break
                                
                    pocket_list.append({
                        'id': row[0],
                        'category': row[1],
                        'name': row[2],
                        'location': loc_val,
                        'area': area_val,
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
            
            # 智慧解析縣市地區標籤 (從地址字串提取)
            if not area and location:
                cities = ["台北市", "新北市", "桃園市", "台中市", "台南市", "高雄市", 
                          "基隆市", "新竹市", "嘉義市", "新竹縣", "苗栗縣", "彰化縣", "南投縣", 
                          "雲林縣", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣", "台東縣", "澎湖縣", "金門縣", "連江縣"]
                for city in cities:
                    if city in location:
                        area = city
                        break
            
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
            new_name = data.get('name')

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

            # 更新自訂稱呼 (Column F，即 'F' + row_index)
            body_note = {'values': [[new_note]]}
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id, range=f'F{row_index}',
                valueInputOption='RAW', body=body_note).execute()

            # 若有傳入主要名稱，更新主要名稱 (Column C，即 'C' + row_index)
            if new_name is not None:
                body_name = {'values': [[new_name]]}
                service.spreadsheets().values().update(
                    spreadsheetId=sheet_id, range=f'C{row_index}',
                    valueInputOption='RAW', body=body_name).execute()

            return True
        except Exception as e:
            print(f"Error updating pocket item note/name: {e}")
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
def get_current_cycle_status():
    """計算生理週期狀態、排卵期與生理四階段的核心輔助函數"""
    health_id = os.getenv('HEALTH_SHEET_ID')
    if not health_id:
        return None
    try:
        rows = get_sheet_values('生理紀錄', spreadsheet_id=health_id)
        if not rows or len(rows) < 2:
            return None
            
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
        
        # 預設週期四階段
        current_phase = "安全期 (濾泡期)"
        phase_desc = "代謝極佳、思緒敏捷。精力充沛、皮膚狀況極佳，適合衝刺事業與高強度鍛鍊！"
        phase_icon = "🟢"
        days_in_cycle = 0
        days_until_ovulation = 0
        
        if history:
            latest_start = history[0]["start"] # 最上面那筆是最新
            latest_end = history[0]["end"]
            try:
                # datetime 轉換
                last_dt = datetime.strptime(latest_start, "%Y/%m/%d")
                now = datetime.now(TW_TZ)
                
                # 計算今天是週期第幾天
                days_in_cycle = (now.date() - last_dt.date()).days + 1
                if days_in_cycle < 1: days_in_cycle = 1
                
                # 預估下次經期日期
                next_dt = last_dt + timedelta(days=avg_cycle)
                next_date_str = next_dt.strftime("%Y/%m/%d")
                
                # 預算排卵日 (下次月經來潮前 14 天)
                ovulation_dt = next_dt - timedelta(days=14)
                ovulation_start_dt = ovulation_dt - timedelta(days=5)
                ovulation_end_dt = ovulation_dt + timedelta(days=1)
                
                if latest_end == "進行中" or latest_end.strip() == "":
                    # 進行中
                    days_in_period = (now.date() - last_dt.date()).days + 1
                    days_until_next = days_in_period if days_in_period > 0 else 1
                    status_title = "🌸 經期第"
                    next_date_str = "進行中..."
                    is_ongoing = True
                    current_phase = "生理期"
                    phase_desc = "身體最脆弱，容易疲憊、經痛。建議溫熱呵護，多喝溫水，避免劇烈運動及生冷食物。"
                    phase_icon = "🩸"
                else:
                    # 非進行中
                    diff = (next_dt.date() - now.date()).days
                    days_until_next = diff if diff >= 0 else 0
                    status_title = "距離下次預測"
                    is_ongoing = False
                    
                    # 依日期判定所屬生理階段
                    today_date = now.date()
                    if ovulation_start_dt.date() <= today_date <= ovulation_end_dt.date():
                        current_phase = "排卵期 (黃體前期)"
                        phase_desc = "荷爾蒙散發魅力，皮膚最彈潤，心情最開朗的黃金週。適合安排約會、社交活動！"
                        phase_icon = "🍑"
                    elif today_date > ovulation_end_dt.date() and today_date < next_dt.date():
                        current_phase = "黃體期 (經前期)"
                        phase_desc = "容易水腫、易累、情緒波動。建議深度放鬆，做些溫和伸展，可喝洋甘菊茶舒緩。"
                        phase_icon = "💜"
                    else:
                        current_phase = "安全期 (濾泡期)"
                        phase_desc = "代謝極佳、思緒敏捷。精力充沛、皮膚狀況極佳，適合衝刺事業與高強度鍛鍊！"
                        phase_icon = "🟢"
                
                # 計算距離排卵期起點還有幾天
                days_to_ov = (ovulation_start_dt.date() - now.date()).days
                days_until_ovulation = days_to_ov if days_to_ov > 0 else 0
                
            except Exception as e:
                print(f"Cycle helper date parse error: {e}")
                
        # 計算懷孕機率 (易孕或不易懷孕)
        pregnancy_probability = "🍀 不易懷孕 (安全期)"
        if current_phase == "生理期":
            pregnancy_probability = "❄️ 不易懷孕 (經期)"
        elif "排卵期" in current_phase:
            pregnancy_probability = "🔥 易懷孕 (黃金受孕期)"
        elif "黃體期" in current_phase:
            pregnancy_probability = "🍀 不易懷孕 (安全期)"
        else:
            pregnancy_probability = "🍀 不易懷孕 (安全期)"

        return {
            "avg_cycle": avg_cycle,
            "avg_length": avg_length,
            "days_until_next": days_until_next,
            "next_date": next_date_str,
            "status_title": status_title,
            "is_ongoing": is_ongoing,
            "current_phase": current_phase,
            "phase_desc": phase_desc,
            "phase_icon": phase_icon,
            "days_in_cycle": days_in_cycle,
            "days_until_ovulation": days_until_ovulation,
            "pregnancy_probability": pregnancy_probability
        }
    except Exception as e:
        print(f"Cycle helper error: {e}")
        return None

# --- 🌸 健康與 AI 訓練 API ---
@app.route('/api/health/info', methods=['GET'])
def get_health_info():
    health_id = os.getenv('HEALTH_SHEET_ID')
    if not health_id:
         return jsonify({"status": "error", "message": "尚未設定 HEALTH_SHEET_ID"})
    try:
        status = get_current_cycle_status()
        if not status:
            return jsonify({"status": "success", "history": [], "avg_cycle": 28, "avg_length": 5, "days_until_next": 28, "next_date": "", "current_phase": "安全期 (濾泡期)", "phase_desc": "代謝極佳、思緒敏捷。"})
            
        rows = get_sheet_values('生理紀錄', spreadsheet_id=health_id)
        history = []
        for row in rows[1:]:
             start_d = row[2] if len(row) > 2 else ""
             end_d = row[3] if len(row) > 3 and row[3].strip() else "進行中"
             symptoms = row[6] if len(row) > 6 else ""
             if start_d:
                 history.append({"start": start_d, "end": end_d, "symptoms": symptoms})
                 
        return jsonify({
            "status": "success",
            "history": history[:3],
            **status
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/health/record_start', methods=['POST'])
def record_health_start():
    health_id = os.getenv('HEALTH_SHEET_ID')
    if not health_id: return jsonify({"status": "error", "message": "未設定 HEALTH_SHEET_ID"})
    
    try:
        service_sheets = get_sheets_service()
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
        service_cal = get_calendar_service()
        
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
        service_sheets = get_sheets_service()
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
    
    service = get_sheets_service()
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
        service = get_sheets_service()
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
