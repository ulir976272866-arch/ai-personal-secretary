import os
# 本地開發允許使用 HTTP 進行 OAuth 驗證 (防止 InsecureTransportError)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
# 允許 OAuth Token 範圍變更 (防止 Scope has changed Warning 導致崩潰)
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
import json
import uuid
import requests
import pymysql
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
        if dt is None:
            return None
        # 將 dt 轉換為 naive datetime 以相容 pytz 的 utcoffset，徹底解決 Not naive datetime 錯誤
        naive_dt = dt.replace(tzinfo=None) if dt.tzinfo else dt
        return self.get_inner_tz().utcoffset(naive_dt)
        
    def tzname(self, dt):
        if dt is None:
            return None
        naive_dt = dt.replace(tzinfo=None) if dt.tzinfo else dt
        return self.get_inner_tz().tzname(naive_dt)
        
    def dst(self, dt):
        if dt is None:
            return None
        naive_dt = dt.replace(tzinfo=None) if dt.tzinfo else dt
        return self.get_inner_tz().dst(naive_dt)

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

# 載入環境變數 (確保能讀到腳本同目錄下的 .env，並允許強制覆蓋環境變數)
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'), override=True)

app = Flask(__name__)
print("--- [DEBUG] SINGLE_USER_MODE in Flask initialization:", os.getenv("SINGLE_USER_MODE"), "---")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "ai_personal_secretary_super_secret_key_12345")
# 配置 PWA 會員登入長效記憶：將 session 的有效期設定為 365 天，直到按登出才失效
app.permanent_session_lifetime = timedelta(days=365)

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
    # 如果 credentials 中缺少 refresh_token，但 session 中有記錄 user_email，則動態從 TiDB Cloud 還原修復它
    if not creds.refresh_token and 'user_email' in session:
        try:
            user = get_user_by_email(session['user_email'])
            if user and user.get('google_refresh_token'):
                creds.refresh_token = user['google_refresh_token']
                session['credentials']['refresh_token'] = user['google_refresh_token']
                session.modified = True
                print(f"Dynamically restored refresh_token from TiDB Cloud for {session['user_email']}")
        except Exception as ex:
            print(f"Failed to restore refresh_token from TiDB: {ex}")

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

# -----------------------------------------------------------------
# TiDB Cloud Multi-User Database Helper Functions
# -----------------------------------------------------------------
TIDB_HOST = os.getenv("TIDB_HOST")
TIDB_PORT = int(os.getenv("TIDB_PORT", 4000))
TIDB_USER = os.getenv("TIDB_USER")
TIDB_PASSWORD = os.getenv("TIDB_PASSWORD")
TIDB_DATABASE = os.getenv("TIDB_DATABASE", "unitask_db")

def get_db_connection():
    """獲取 TiDB Cloud 安全連線"""
    return pymysql.connect(
        host=TIDB_HOST,
        user=TIDB_USER,
        password=TIDB_PASSWORD,
        port=TIDB_PORT,
        database=TIDB_DATABASE,
        ssl={"ssl_ca": "/etc/ssl/cert.pem"} if os.path.exists("/etc/ssl/cert.pem") else {}
    )

def get_user_by_email(email):
    """從 TiDB 查詢使用者，若為單人模式或開發者白名單信箱則直接回傳開發者模擬 VIP 帳號"""
    developer_emails = {'ulir976272866@gmail.com'}
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "true" or (email and email.lower() in developer_emails):
        return {
            "user_id": "uid_owner",
            "email": email,
            "is_subscribed": True,
            "subscription_type": "YEARLY_AI",
            "ai_points": 9999,
            "has_stock_record": True
        }
    
    try:
        conn = get_db_connection()
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT * FROM users WHERE email = %s;", (email,))
            user = cursor.fetchone()
            
            # 🌟 7天旗艦版免費試用過期安全降級守衛 🌟
            if user and user.get('trial_expires_at'):
                from datetime import datetime
                expires_at = user.get('trial_expires_at')
                if isinstance(expires_at, str):
                    try:
                        expires_at = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        pass
                
                # 如果試用期限已過，且使用者目前的 subscription_type 不是 NONE，則降級為免費版
                if expires_at and datetime.now() > expires_at and user.get('subscription_type') != 'NONE':
                    print(f"[TiDB Guard] 使用者 {email} 的 7天試用已過期！自動安全降級為免費基礎版 (NONE)")
                    cursor.execute(
                        "UPDATE users SET is_subscribed = FALSE, subscription_type = 'NONE', ai_points = 0 WHERE email = %s;",
                        (email,)
                    )
                    conn.commit()
                    # 重新拉取已降級的最新資料
                    cursor.execute("SELECT * FROM users WHERE email = %s;", (email,))
                    user = cursor.fetchone()
            
            return user
    except Exception as e:
        print(f"Error querying user by email in TiDB: {e}")
        return None
    finally:
        if 'conn' in locals() and conn:
            conn.close()

def get_tidb_user_sheet_id(email):
    """獲取用戶在 TiDB 綁定的 Google 試算表 ID"""
    user = get_user_by_email(email)
    return user.get('google_spreadsheet_id') if user else None

def update_user_sheet_id(email, spreadsheet_id):
    """更新用戶在 TiDB 中綁定的試算表 ID"""
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "true":
        return True
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET google_spreadsheet_id = %s WHERE email = %s;",
                (spreadsheet_id, email)
            )
            conn.commit()
            return True
    except Exception as e:
        print(f"Error updating user sheet id in TiDB: {e}")
        return False
    finally:
        if 'conn' in locals() and conn:
            conn.close()

def update_user_refresh_token(email, refresh_token):
    """更新用戶在 TiDB 中的 refresh_token 以便背景續存授權"""
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "true":
        return True
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET google_refresh_token = %s WHERE email = %s;",
                (refresh_token, email)
            )
            conn.commit()
            return True
    except Exception as e:
        print(f"Error updating user refresh token in TiDB: {e}")
        return False
    finally:
        if 'conn' in locals() and conn:
            conn.close()

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

def get_diary_sheet_id():
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "true":
        return os.getenv("DIARY_SHEET_ID")
    try:
        user_info = get_user_info()
        if user_info and user_info.get('email') == os.getenv("GOOGLE_CALENDAR_ID"):
            return os.getenv("DIARY_SHEET_ID")
    except Exception:
        pass
    return session.get('spreadsheet_id') or os.getenv("DIARY_SHEET_ID")

def get_todo_sheet_id():
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "true":
        return os.getenv("TODO_SHEET_ID")
    try:
        user_info = get_user_info()
        if user_info and user_info.get('email') == os.getenv("GOOGLE_CALENDAR_ID"):
            return os.getenv("TODO_SHEET_ID")
    except Exception:
        pass
    return session.get('spreadsheet_id') or os.getenv("TODO_SHEET_ID")

def get_wish_sheet_id():
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "true":
        return os.getenv("WISH_SHEET_ID")
    try:
        user_info = get_user_info()
        if user_info and user_info.get('email') == os.getenv("GOOGLE_CALENDAR_ID"):
            return os.getenv("WISH_SHEET_ID")
    except Exception:
        pass
    return session.get('spreadsheet_id') or os.getenv("WISH_SHEET_ID")

def get_pocket_sheet_id():
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "true":
        return os.getenv("POCKET_SHEET_ID")
    try:
        user_info = get_user_info()
        if user_info and user_info.get('email') == os.getenv("GOOGLE_CALENDAR_ID"):
            return os.getenv("POCKET_SHEET_ID")
    except Exception:
        pass
    return session.get('spreadsheet_id') or os.getenv("POCKET_SHEET_ID")

def get_health_sheet_id():
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "true":
        return os.getenv("HEALTH_SHEET_ID")
    try:
        user_info = get_user_info()
        if user_info and user_info.get('email') == os.getenv("GOOGLE_CALENDAR_ID"):
            return os.getenv("HEALTH_SHEET_ID")
    except Exception:
        pass
    return session.get('spreadsheet_id') or os.getenv("HEALTH_SHEET_ID")

def get_sheet_urls():
    is_owner = False
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "true":
        is_owner = True
    else:
        try:
            user_info = get_user_info()
            if user_info and user_info.get('email') == os.getenv("GOOGLE_CALENDAR_ID"):
                is_owner = True
        except Exception:
            pass
            
    # Unified Spreadsheet ID resolution
    if is_owner:
        spreadsheet_id = os.getenv("GOOGLE_SHEET_ID")
    else:
        spreadsheet_id = ensure_user_spreadsheet()
        
    gids = session.get('sheet_gids', {})
    
    if (not gids or '💰股票投資組合' not in gids) and spreadsheet_id:
        try:
            sheets_service = get_sheets_service()
            sheet_meta = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
            gids = {}
            for s in sheet_meta.get('sheets', []):
                title = s['properties']['title']
                gids[title] = s['properties']['sheetId']
            session['sheet_gids'] = gids
            session.modified = True
        except Exception as e:
            print(f"Error fetching GIDs for index: {e}")
            import traceback
            try:
                with open('/Users/mina.chen/00_AI coding/私人行事曆安排/ai-personal-secretary/gids_error.log', 'w') as f:
                    f.write(f"Error: {e}\n")
                    traceback.print_exc(file=f)
            except Exception:
                pass
            
    def get_url_with_gid(title, default_sheet_id=None):
        current_sheet_id = default_sheet_id if (is_owner and default_sheet_id) else spreadsheet_id
        if is_owner and default_sheet_id:
            return f"https://docs.google.com/spreadsheets/d/{current_sheet_id}/edit"
        gid = gids.get(title)
        if gid is not None:
            return f"https://docs.google.com/spreadsheets/d/{current_sheet_id}/edit#gid={gid}"
        return f"https://docs.google.com/spreadsheets/d/{current_sheet_id}/edit"
        
    return {
        "finance_sheet_url": get_url_with_gid('記帳'),
        "stock_sheet_url": get_url_with_gid('💰股票投資組合'),
        "diary_sheet_url": get_url_with_gid('日記', os.getenv('DIARY_SHEET_ID')),
        "todo_sheet_url": get_url_with_gid('待辦', os.getenv('TODO_SHEET_ID')),
        "wish_sheet_url": get_url_with_gid('願望', os.getenv('WISH_SHEET_ID')),
        "pocket_sheet_url": get_url_with_gid('口袋', os.getenv('POCKET_SHEET_ID')),
        "health_sheet_url": get_url_with_gid('生理紀錄', os.getenv('HEALTH_SHEET_ID')),
        "training_sheet_url": get_url_with_gid('AI_指令集', os.getenv('HEALTH_SHEET_ID'))
    }
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
            if 'user_email' in session:
                update_user_sheet_id(session['user_email'], spreadsheet_id)
            # 確保 session 中有 gids
            if 'sheet_gids' not in session:
                try:
                    sheet_meta = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
                    gids = {}
                    for s in sheet_meta.get('sheets', []):
                        title = s['properties']['title']
                        gids[title] = s['properties']['sheetId']
                    session['sheet_gids'] = gids
                    print(f"Restored existing GIDs into session: {gids}")
                except Exception as ex:
                    print(f"Error restoring GIDs: {ex}")
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
            {'addSheet': {'properties': {'title': '口袋'}}},
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
            '日記!A1:E1': [['日期', '內容', '天氣', '心情', '時間']],
            '願望!A1:F1': [['唯一 ID', '願望名稱', '預算', '狀態', '實際花費', '建立時間']],
            '生理紀錄!A1:G1': [['年度', '月份', '日期', '動作', '症狀/心情', '週期', '備註']],
            '口袋!A1:I1': [['ID', '分類', '店名', '地址', '地區', '備註', '建立時間', '緯度', '經度']],
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
        
        # 取得新建試算表中所有分頁的唯一 GID 並寫入 session，同時為每一張表的第一列 (Row 1) 加上「警告保護鎖」防止手殘誤改！
        sheet_meta = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        gids = {}
        protect_requests = []
        for s in sheet_meta.get('sheets', []):
            title = s['properties']['title']
            s_id = s['properties']['sheetId']
            gids[title] = s_id
            
            # 計算每張表的欄數
            col_count = 7
            if title == '待辦': col_count = 6
            elif title == '日記': col_count = 5
            elif title == '願望': col_count = 6
            elif title == '口袋': col_count = 9
            elif title == 'AI_指令集': col_count = 2
            
            protect_requests.append({
                "addProtectedRange": {
                    "protectedRange": {
                        "range": {
                            "sheetId": s_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": col_count
                        },
                        "description": f"系統 {title} 核心表頭，請勿任意變動以防當機",
                        "warningOnly": True
                    }
                }
            })
            
        session['sheet_gids'] = gids
        
        # 執行批次保護鎖定
        if protect_requests:
            try:
                sheets_service.spreadsheets().batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={'requests': protect_requests}
                ).execute()
            except Exception as protect_err:
                print(f"Failed to protect sheet headers: {protect_err}")
                
        print(f"Created new spreadsheet. Stored sheet GIDs in session: {gids}")
        
        session['spreadsheet_id'] = spreadsheet_id
        print(f"Created and initialized new spreadsheet in user drive: {spreadsheet_id}")
        if 'user_email' in session:
            update_user_sheet_id(session['user_email'], spreadsheet_id)
        return spreadsheet_id
        
    except Exception as e:
        print(f"Error in ensure_user_spreadsheet: {e}")
        return os.getenv("GOOGLE_SHEET_ID")

# --- Sheets 輔助函數 ---
_wish_tab_cache = {}

def get_wish_tab_name(spreadsheet_id, service=None):
    if spreadsheet_id in _wish_tab_cache:
        return _wish_tab_cache[spreadsheet_id]
    if not service:
        service = get_sheets_service()
    try:
        metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        titles = [s['properties']['title'] for s in metadata.get('sheets', [])]
        if '願望' in titles:
            _wish_tab_cache[spreadsheet_id] = '願望'
            return '願望'
    except Exception:
        pass
    _wish_tab_cache[spreadsheet_id] = '願望清單'
    return '願望清單'

def append_to_sheet(range_name, values, spreadsheet_id=None):
    if not spreadsheet_id:
        spreadsheet_id = get_spreadsheet_id()
    service = get_sheets_service()
    body = {'values': [values]}
    try:
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()
    except Exception as e:
        # 智慧地自動匹配「願望清單」與「願望」分頁以防寫入報錯
        if '願望清單' in range_name:
            new_range = range_name.replace('願望清單', '願望')
            try:
                service.spreadsheets().values().append(
                    spreadsheetId=spreadsheet_id,
                    range=new_range,
                    valueInputOption='USER_ENTERED',
                    body=body
                ).execute()
            except Exception:
                raise e
        elif '願望' in range_name:
            new_range = range_name.replace('願望', '願望清單')
            try:
                service.spreadsheets().values().append(
                    spreadsheetId=spreadsheet_id,
                    range=new_range,
                    valueInputOption='USER_ENTERED',
                    body=body
                ).execute()
            except Exception:
                raise e
        else:
            raise e

def get_sheet_values(range_name, spreadsheet_id=None):
    if not spreadsheet_id:
        spreadsheet_id = get_spreadsheet_id()
    service = get_sheets_service()
    
    # 智慧地自動匹配「願望清單」與「願望」分頁名以防讀取報錯
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
    except Exception as e:
        if '願望清單' in range_name:
            new_range = range_name.replace('願望清單', '願望')
            try:
                result = service.spreadsheets().values().get(
                    spreadsheetId=spreadsheet_id,
                    range=new_range
                ).execute()
                range_name = new_range
            except Exception:
                raise e
        elif '願望' in range_name:
            new_range = range_name.replace('願望', '願望清單')
            try:
                result = service.spreadsheets().values().get(
                    spreadsheetId=spreadsheet_id,
                    range=new_range
                ).execute()
                range_name = new_range
            except Exception:
                raise e
        else:
            raise e
            
    values = result.get('values', [])
    
    # 🛡️ 全局主動式表頭自癒安全護盾 (Proactive Header Self-Healing Shield)
    try:
        if values and len(values) > 0:
            sheet_title = range_name.split('!')[0] if '!' in range_name else range_name
            
            standard_headers_map = {
                '生理紀錄': ['年度', '月份', '日期', '動作', '症狀/心情', '週期', '備註'],
                '記帳': ['年度', '月份', '日期', '收入項目', '支出項目', '金額', '類別'],
                '待辦': ['建立日期', '事項/內容', '分類', '狀態', '唯一 ID', '建立時間', '優先級'],
                '日記': ['日期', '內容', '天氣', '心情', '時間'],
                '願望': ['建立日期', '商品名稱', '預估價格', '備註/連結', '狀態', '分類', '實際價格', '唯一 ID', '儲存時間'],
                '願望清單': ['建立日期', '商品名稱', '預估價格', '備註/連結', '狀態', '分類', '實際價格', '唯一 ID', '儲存時間'],
                '口袋': ['ID', '分類', '店名', '地址', '地區', '備註', '建立時間', '緯度', '經度'],
                'AI_指令集': ['觸發語句', '執行動作'],
                '💰股票投資組合': ['交易日期', '股票代號', '股票名稱', '交易類型', '交易股數', '交易單價', '手續費', '即時市價', '即時損益', '備註']
            }
            
            if sheet_title in standard_headers_map:
                standard_headers = standard_headers_map[sheet_title]
                is_full_sheet_read = '!' not in range_name or (':' not in range_name and len(values[0]) > 1)
                
                if is_full_sheet_read:
                    current_headers = values[0]
                    if len(current_headers) != len(standard_headers) or current_headers != standard_headers:
                        print(f"[Self-Healing] Detected header mismatch in sheet '{sheet_title}': {current_headers} vs standard {standard_headers}. Overwriting...")
                        
                        col_letter = chr(ord('A') + len(standard_headers) - 1)
                        header_range = f"{sheet_title}!A1:{col_letter}1"
                        
                        service.spreadsheets().values().update(
                            spreadsheetId=spreadsheet_id,
                            range=header_range,
                            valueInputOption='USER_ENTERED',
                            body={'values': [standard_headers]}
                        ).execute()
                        
                        values[0] = standard_headers
                        
                    # 🔒 全局表頭警告保護鎖自癒守衛 (Header Protection Lock Self-Healing Sandbox)
                    # 包裝在完全獨立的 try-except 程式沙盒中，完美解耦，保證絕不干擾主流程數據讀取
                    try:
                        meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
                        sheet_obj = None
                        for s in meta.get('sheets', []):
                            if s['properties']['title'] == sheet_title:
                                sheet_obj = s
                                break
                                
                        if sheet_obj:
                            sheet_id = sheet_obj['properties']['sheetId']
                            protected_ranges = sheet_obj.get('protectedRanges', [])
                            
                            has_header_protect = any(
                                p.get('range', {}).get('startRowIndex') == 0 and p.get('range', {}).get('endRowIndex') == 1
                                for p in protected_ranges
                            )
                            
                            if not has_header_protect:
                                print(f"[Header Lock Self-Healing] '{sheet_title}' is missing Row 1 header warning lock. Restoring...")
                                req = {
                                    "addProtectedRange": {
                                        "protectedRange": {
                                            "range": {
                                                "sheetId": sheet_id,
                                                "startRowIndex": 0,
                                                "endRowIndex": 1,
                                                "startColumnIndex": 0,
                                                "endColumnIndex": len(standard_headers)
                                            },
                                            "description": f"系統 {sheet_title} 核心表頭，請勿任意變動以防當機",
                                            "warningOnly": True
                                        }
                                    }
                                }
                                service.spreadsheets().batchUpdate(
                                    spreadsheetId=spreadsheet_id,
                                    body={'requests': [req]}
                                ).execute()
                                print(f"[Header Lock Self-Healing] Header warning lock successfully restored for '{sheet_title}'!")
                    except Exception as lock_err:
                        print(f"[Header Lock Self-Healing Error] Skipped header lock restoration on '{sheet_title}' due to: {lock_err}")
    except Exception as heal_err:
        print(f"[Self-Healing Error] Central protector failed silently: {heal_err}")
        
    return values

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

def check_conflicts(service, start_time, end_time, exclude_id=None, summary=None):
    """
    檢查指定時間範圍內是否有衝突的行程。
    """
    # 🌸 核心生理期防禦護盾：生理期為背景標記，豁免於衝突檢測，絕對放行！
    if summary:
        summary_str = str(summary).strip()
        is_period = any(k in summary_str for k in ['生理期', '月經', '經期', '🌸'])
        if is_period:
            print(f"[Period Bypass] 偵測到生理期標題 '{summary_str}'，自動豁免衝突限制！")
            return None

    try:
        t_min = ensure_tz(start_time)
        t_max = ensure_tz(end_time)
        
        current_cal_id = session.get('calendar_id', 'primary')
        events_result = service.events().list(
            calendarId=current_cal_id,
            timeMin=t_min,
            timeMax=t_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        conflicts = events_result.get('items', [])
        
        # 排除指定的 ID (用於更新行程時)
        if exclude_id:
            conflicts = [e for e in conflicts if e.get('id') != exclude_id]
            
        # 🛡️ 雙向防護盾：同時過濾掉日曆中已存在的「生理期背景提示」，因為它們是背景記錄，不應阻擋其他正常行程排入！
        conflicts = [e for e in conflicts if not any(k in e.get('summary', '') for k in ['生理期', '月經', '經期', '🌸'])]
            
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
        # 單人開發者模式下，若未有模擬 Session，強行賦予全功能旗艦權限與無限 AI 點數，確保開發一切順暢
        if not session.get('user_email'):
            session['is_subscribed'] = True
            session['subscription_type'] = 'YEARLY_AI'
            session['ai_points'] = 9999
            session['has_stock_record'] = True
            session['user_email'] = 'ulir976272866@gmail.com'
        
        urls = get_sheet_urls()
        
        # 🚀 在主線程預先獲取已授權的 sheets service 物件，避免背景線程失去 Session 上下文
        try:
            user_sheets_service = get_sheets_service()
        except Exception:
            user_sheets_service = None
            
        # 🚀 背景非同步啟動全局自癒與警告鎖，極致流暢防呆！
        import threading
        spreadsheet_id = session.get('spreadsheet_id') or os.getenv("GOOGLE_SHEET_ID")
        if spreadsheet_id:
            threading.Thread(
                target=ensure_all_sheets_warning_protected, 
                args=(spreadsheet_id, user_sheets_service)
            ).start()
            
        return render_template(
            'index.html', 
            maps_api_key=maps_api_key, 
            logged_in=True, 
            user_info={
                "name": "個人秘書系統",
                "picture": "https://lh3.googleusercontent.com/a/default-user"
            },
            spreadsheet_id=SPREADSHEET_ID,
            **urls
        )
        
    logged_in = 'credentials' in session
    user_info = None
    urls = {}
    if logged_in:
        user_info = get_user_info()
        # 若憑證過期或失效導致無法獲取 user_info，則強制登出以防畫面異常
        if not user_info:
            session.pop('credentials', None)
            session.pop('spreadsheet_id', None)
            session.pop('sheet_gids', None)
            logged_in = False
        else:
            urls = get_sheet_urls()
            
            # 🚀 在主線程預先獲取已授權的 sheets service 物件，避免背景線程失去 Session 上下文
            try:
                user_sheets_service = get_sheets_service()
            except Exception:
                user_sheets_service = None
                
            # 🚀 背景非同步啟動全局自癒與警告鎖，極致流暢防呆！
            import threading
            spreadsheet_id = session.get('spreadsheet_id') or os.getenv("GOOGLE_SHEET_ID")
            if spreadsheet_id:
                threading.Thread(
                    target=ensure_all_sheets_warning_protected, 
                    args=(spreadsheet_id, user_sheets_service)
                ).start()
            
    return render_template(
        'index.html', 
        maps_api_key=maps_api_key, 
        logged_in=logged_in, 
        user_info=user_info,
        spreadsheet_id=SPREADSHEET_ID,
        **urls
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
    
    # 啟用長效永久 Cookie 以在裝置上記憶使用者狀態，直到按登出按鈕才清除
    session.permanent = True
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
    
    # 提取使用者資料並進行多用戶註冊比對
    try:
        user_info = get_user_info()
        user_email = user_info.get('email') if user_info else None
        if user_email:
            session['user_email'] = user_email
            print(f"User email captured: {user_email}")
            
            # 從 TiDB 查詢使用者
            user = get_user_by_email(user_email)
            if not user and os.getenv("SINGLE_USER_MODE", "false").lower() != "true":
                # 全新註冊的用戶，自動開啟「7天旗艦版全功能免費試用」！
                try:
                    conn = get_db_connection()
                    with conn.cursor() as cursor:
                        new_uid = f"uid_{uuid.uuid4().hex[:12]}"
                        from datetime import datetime, timedelta
                        trial_expiry = datetime.now() + timedelta(days=7)
                        cursor.execute(
                            "INSERT INTO users (user_id, email, is_subscribed, subscription_type, ai_points, trial_used, trial_expires_at, has_stock_record) VALUES (%s, %s, TRUE, 'YEARLY_AI', 100, TRUE, %s, TRUE);",
                            (new_uid, user_email, trial_expiry)
                        )
                        conn.commit()
                    user = get_user_by_email(user_email)
                    print(f"Successfully registered new user with 7-day flagship trial in TiDB: {user_email}")
                except Exception as ex:
                    print(f"Failed to auto register new user in TiDB: {ex}")
                finally:
                    if 'conn' in locals() and conn:
                        conn.close()
            
            # 將資料庫會員規格注入 Session
            if user:
                session['is_subscribed'] = bool(user.get('is_subscribed'))
                session['subscription_type'] = user.get('subscription_type', 'NONE')
                session['ai_points'] = user.get('ai_points', 0)
                session['has_stock_record'] = bool(user.get('has_stock_record'))
                
                # 注入試用期狀態，以便前端模板進行特別樣式渲染
                if user.get('trial_expires_at'):
                    from datetime import datetime
                    expires_at = user.get('trial_expires_at')
                    if isinstance(expires_at, str):
                        try:
                            expires_at = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            pass
                    if expires_at and datetime.now() < expires_at:
                        session['is_trial_active'] = True
                    else:
                        session['is_trial_active'] = False
                else:
                    session['is_trial_active'] = False

                if user.get('google_spreadsheet_id'):
                    session['spreadsheet_id'] = user.get('google_spreadsheet_id')
                    print(f"Loaded existing spreadsheet_id from TiDB: {user.get('google_spreadsheet_id')}")
            
            # 如果取得 refresh_token，非同步保存至 TiDB，以供離線更新使用
            if creds.refresh_token:
                update_user_refresh_token(user_email, creds.refresh_token)
    except Exception as e:
        print(f"Error handling multi-user context in callback: {e}")
        
    # 背景自動初始化或檢查試算表資料庫
    ensure_user_spreadsheet()
    
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/dev/switch_role', methods=['GET', 'POST'])
def dev_switch_role():
    """沙盒身分模擬切換 API (限本地除錯且多人版啟用時)"""
    # 雙重防安全開線：必須是 Debug 偵錯模式
    if not app.debug:
        return jsonify({"status": "error", "message": "此除錯路由已實體防禦阻斷"}), 403
        
    role = "FREE"
    email = None
    
    if request.method == 'POST':
        data = request.json or {}
        role = data.get('role', 'FREE')
        email = data.get('email')
    else:
        role = request.args.get('role', 'FREE').upper()
        email = request.args.get('email')

    # 映射到三組真實的沙盒信箱與會員特權
    role_mapping = {
        'FREE': {
            'email': 'mina976272866@gmail.com',
            'is_subscribed': False,
            'subscription_type': 'NONE',
            'ai_points': 0,
            'has_stock_record': False
        },
        'BASIC': {
            'email': 'min272866@gmail.com',
            'is_subscribed': True,
            'subscription_type': 'MONTHLY_AI',
            'ai_points': 500,
            'has_stock_record': False
        },
        'PREMIUM': {
            'email': 'inming399@gmail.com',
            'is_subscribed': True,
            'subscription_type': 'YEARLY_AI',
            'ai_points': 1000,
            'has_stock_record': True
        },
        'DEVELOPER': {
            'email': 'ulir976272866@gmail.com',
            'is_subscribed': True,
            'subscription_type': 'YEARLY_AI',
            'ai_points': 9999,
            'has_stock_record': True
        }
    }
    
    target = role_mapping.get(role)
    if not target:
        # 兼容小寫或縮寫
        if role in ['NONE', 'FREE']:
            target = role_mapping['FREE']
        elif role in ['MONTHLY_AI', 'BASIC']:
            target = role_mapping['BASIC']
        elif role in ['YEARLY_AI', 'PREMIUM']:
            target = role_mapping['PREMIUM']
        else:
            return jsonify({"status": "error", "message": "無效的角色參數"}), 400
            
    # 如果傳入了自訂的信箱，覆蓋預設的沙盒信箱，並進行自動註冊
    user_email = email if email else target['email']
    
    # 檢查該自訂信箱在 TiDB 中是否存在，若不存在且非單人模式則進行自動註冊
    if os.getenv("SINGLE_USER_MODE", "false").lower() != "true":
        user = get_user_by_email(user_email)
        if not user:
            try:
                conn = get_db_connection()
                with conn.cursor() as cursor:
                    new_uid = f"uid_{uuid.uuid4().hex[:12]}"
                    is_sub = target['is_subscribed']
                    sub_type = target['subscription_type']
                    points = target['ai_points']
                    from datetime import datetime, timedelta
                    trial_expiry = datetime.now() + timedelta(days=7)
                    cursor.execute(
                        "INSERT INTO users (user_id, email, is_subscribed, subscription_type, ai_points, trial_used, trial_expires_at, has_stock_record) VALUES (%s, %s, %s, %s, %s, TRUE, %s, TRUE);",
                        (new_uid, user_email, is_sub, sub_type, points, trial_expiry)
                    )
                    conn.commit()
                print(f"Successfully registered custom test user via switch_role: {user_email}")
            except Exception as ex:
                print(f"Failed to auto register custom test user via switch_role: {ex}")
            finally:
                if 'conn' in locals() and conn:
                    conn.close()

    # 再次查詢使用者狀態，以獲得寫入資料庫後的精準資料
    user = get_user_by_email(user_email)
    if user:
        session['user_email'] = user.get('email')
        session['is_subscribed'] = bool(user.get('is_subscribed'))
        session['subscription_type'] = user.get('subscription_type', 'NONE')
        session['ai_points'] = user.get('ai_points', 0)
        session['has_stock_record'] = bool(user.get('has_stock_record'))
        
        # 注入試用期狀態
        if user.get('trial_expires_at'):
            from datetime import datetime
            expires_at = user.get('trial_expires_at')
            if isinstance(expires_at, str):
                try:
                    expires_at = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass
            if expires_at and datetime.now() < expires_at:
                session['is_trial_active'] = True
            else:
                session['is_trial_active'] = False
        else:
            session['is_trial_active'] = False

        if user.get('google_spreadsheet_id'):
            session['spreadsheet_id'] = user.get('google_spreadsheet_id')
        else:
            session.pop('spreadsheet_id', None)
    else:
        # 單人模式或資料庫查詢異常時，使用映射的預設沙盒 session
        session['user_email'] = user_email
        session['is_subscribed'] = target['is_subscribed']
        session['subscription_type'] = target['subscription_type']
        session['ai_points'] = target['ai_points']
        session['has_stock_record'] = target['has_stock_record']
        session.pop('spreadsheet_id', None)

    print(f"Developer Switch Role Success! Current mock session email: {session['user_email']}, subscription_type: {session['subscription_type']}")
    
    if request.method == 'GET':
        # GET 請求時直接重導向回首頁，方便手機上點擊連結一步到位！
        return redirect(url_for('index'))
        
    return jsonify({
        "status": "success",
        "message": f"成功切換身份為 {role}",
        "user_email": session['user_email'],
        "subscription_type": session['subscription_type'],
        "ai_points": session['ai_points']
    })


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
        elif user_text in ["投資持股", "查詢持股", "存股明細"]:
            bypass_data = {"type": "query_stock_portfolio"}
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
            health_sheet_id = get_health_sheet_id()
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
        - 股票交易：type: "stock" (ticker: 股票代號如 "TPE:2330"、"NASDAQ:AAPL", name: 股票名稱如 "台積電", tx_type: "買進" 或 "賣出", shares: 交易股數(整數，例如: 一張=1000股，10張=10000股，零股則依實際股數), price: 單價(浮點數), fee: 手續費(浮點數，預設為 0), date: 交易日期 "YYYY-MM-DD")
        - 其他：chat, query_expense_report
        
        【股票代碼自動映射對照】：
        - 台積電 / 2330 -> "TPE:2330"
        - 鴻海 / 2317 -> "TPE:2317"
        - 聯發科 / 2454 -> "TPE:2454"
        - 長榮航 / 2618 -> "TPE:2618"
        - 長榮 / 2603 -> "TPE:2603"
        - 聯電 / 2303 -> "TPE:2303"
        - 富邦金 / 2881 -> "TPE:2881"
        - 國泰金 / 2882 -> "TPE:2882"
        - 蘋果 / Apple / AAPL -> "NASDAQ:AAPL"
        - 輝達 / Nvidia / NVDA -> "NASDAQ:NVDA"
        - 特斯拉 / Tesla / TSLA -> "NASDAQ:TSLA"
        
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
                event['end'].get('dateTime', event['end'].get('date')),
                summary=event.get('summary')
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

        elif intent_type == "query_stock_portfolio":
            spreadsheet_id = get_spreadsheet_id()
            if not spreadsheet_id:
                return jsonify({"status": "error", "message": "尚未連結試算表"})
            report_text = get_stock_portfolio_report_text(spreadsheet_id)
            return jsonify({"status": "success", "type": "chat", "message": report_text})

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

        elif intent_type == "stock":
            user_email = session.get('user_email', '')
            db = get_db_connection()
            try:
                with db.cursor() as cur:
                    cur.execute("SELECT subscription_type FROM users WHERE email = %s", (user_email,))
                    row = cur.fetchone()
                    sub_type = row['subscription_type'] if row else 'NONE'
            except Exception as e:
                print(f"Error checking stock subscription in chat: {e}")
                sub_type = 'NONE'
            finally:
                db.close()
                
            WHITELIST_EMAILS = ['ulir976272866@gmail.com', 'mina.chen.xstar.sg@gmail.com']
            if sub_type != 'YEARLY_AI' and user_email not in WHITELIST_EMAILS:
                return jsonify({
                    "status": "success",
                    "type": "stock_locked",
                    "message": "🔒 「智慧股票投資記帳」為尊榮旗艦版 (YEARLY_AI) 獨享功能，請升級後體驗語音智慧自動填單功能喔！"
                })
                
            ticker = parsed_data.get('ticker')
            name = parsed_data.get('name')
            tx_type = parsed_data.get('tx_type', '買進')
            shares = parsed_data.get('shares', 0)
            price = parsed_data.get('price', 0.0)
            fee = parsed_data.get('fee', 0.0)
            date = parsed_data.get('date') or now.strftime('%Y-%m-%d')
            
            msg = f"📈 偵測到股票交易意圖：\n• 交易類型：{tx_type}\n• 股票：{name} ({ticker})\n• 股數：{shares} 股\n• 單價：${price}\n\n已自動為您預填入新增表單，請核對無誤後確認送出！"
            if ai_response_message:
                msg = f"{ai_response_message}\n\n{msg}"
                
            return jsonify({
                "status": "success",
                "type": "stock_prefill",
                "message": msg,
                "stock_data": {
                    "ticker": ticker,
                    "name": name,
                    "tx_type": tx_type,
                    "shares": shares,
                    "price": price,
                    "fee": fee,
                    "date": date
                }
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
                    'content': row[1],
                    'weather': row[2],
                    'mood': row[3] if len(row) > 3 else '',
                    'time': row[4] if len(row) > 4 else ''
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
        today_start = datetime.combine(now.date(), time.min, tzinfo=TW_TZ).isoformat()
        end_date = now + timedelta(days=days-1)
        today_end = datetime.combine(end_date.date(), time.max, tzinfo=TW_TZ).isoformat()
        
        current_cal_id = session.get('calendar_id', 'primary')

        events_result = service.events().list(
            calendarId=current_cal_id, timeMin=today_start, timeMax=today_end,
            maxResults=50, singleEvents=True, orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
    except Exception as e:
        print(f"Calendar Fetch Error: {e}")
        # 👈 關鍵就在這一行，把角括號換掉，前端才不會變空白
        safe_msg = str(e).replace("<", "[").replace(">", "]")
        
        if "Not Found" in str(e) or "404" in str(e):
            return jsonify({
                "status": "success",
                "type": "chat",
                "message": "⚠️ 讀取行程失敗！請確認日曆共用設定或稍後再試。"
            })
        return jsonify({
            "status": "error",
            "message": f"讀取行事曆失敗，詳細錯誤：{safe_msg}。如果您是第一次使用或剛改版，請點選右上角🚪按鈕登出並重新登入以授權 Google 日曆讀寫權限！"
        })
    
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
        today_end = datetime.combine(now.date(), time.max, tzinfo=TW_TZ).isoformat()
        past_start = datetime.combine((now - timedelta(days=days)).date(), time.min, tzinfo=TW_TZ).isoformat()
        
        events_result = service.events().list(
            calendarId=CALENDAR_ID, timeMin=past_start, timeMax=today_end,
            maxResults=150, singleEvents=True, orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
    except Exception as e:
        print(f"Error fetching past completed events: {e}")
        return jsonify({
            "status": "error",
            "message": f"讀取歷史行程失敗，詳細錯誤：{str(e)}。如果您是第一次使用或剛改版，請點選右上角🚪按鈕登出並重新登入以授權 Google 日曆讀寫權限！"
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
                                          event['end'].get('dateTime', event['end'].get('date')),
                                          summary=event.get('summary'))
            
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
    diary_id = get_diary_sheet_id()
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
    wish_id = get_wish_sheet_id()
        
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
            tab_name = get_wish_tab_name(wish_id)
            append_to_sheet(tab_name, row, spreadsheet_id=wish_id)
            return jsonify({"status": "success", "message": "願望已許下", "id": unique_id})
        except Exception as e:
            return jsonify({"status": "error", "message": f"寫入失敗：{str(e)}"}), 500
    else:
        try:
            tab_name = get_wish_tab_name(wish_id)
            rows = get_sheet_values(tab_name, spreadsheet_id=wish_id)
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
    wish_id = get_wish_sheet_id()
    
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
    tab_name = get_wish_tab_name(wish_id, service)
    # 更新狀態 (E 欄, index 4), 實際價格 (G 欄, index 6), 唯一ID (H 欄, index 7)
    service.spreadsheets().values().update(
        spreadsheetId=wish_id,
        range=f'{tab_name}!E{target_row_idx}:H{target_row_idx}',
        valueInputOption='USER_ENTERED',
        body={'values': [['已圓夢', rows[target_row_idx-1][5] if len(rows[target_row_idx-1]) > 5 else '', actual_price, item_id]]}
    ).execute()
    
    return jsonify({"status": "success", "message": "恭喜圓夢！✨"})

@app.route('/api/wishlist/delete', methods=['POST'])
def delete_wish():
    data = request.json
    item_id = str(data.get('id', ''))
    title = data.get('title', '')
    wish_id = get_wish_sheet_id()
    
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
    tab_name = get_wish_tab_name(wish_id, service)
    # 更新狀態為「已取消」 (E 欄)
    service.spreadsheets().values().update(
        spreadsheetId=wish_id,
        range=f'{tab_name}!E{target_row_idx}',
        valueInputOption='USER_ENTERED',
        body={'values': [['已取消']]}
    ).execute()
    
    return jsonify({"status": "success", "message": f"已斷捨離該願望 (行號: {target_row_idx}) 🍂"})

@app.route('/api/todo', methods=['GET', 'POST'])
def handle_todo():
    todo_id = get_todo_sheet_id()
        
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
    todo_id = get_todo_sheet_id()
    
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
    todo_id = get_todo_sheet_id()
    
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
    wish_id = get_wish_sheet_id()
    
    rows = get_sheet_values('願望清單', spreadsheet_id=wish_id)
    if not rows: return jsonify({"status": "error", "message": "找不到資料"})
    
    # 使用 helper 尋找 ID (第 8 欄, index 7)
    target_row_idx = find_row_by_id(rows, item_id, 7)
    
    if target_row_idx == -1:
        return jsonify({"status": "error", "message": f"找不到 ID 為 {item_id} 的願望"})

    # 分次更新以確保準確
    service = get_sheets_service()
    tab_name = get_wish_tab_name(wish_id, service)
    
    # 1. 更新名稱、價格、備註 (B-D 欄)
    service.spreadsheets().values().update(
        spreadsheetId=wish_id,
        range=f'{tab_name}!B{target_row_idx}:D{target_row_idx}',
        valueInputOption='USER_ENTERED',
        body={'values': [[name, price, note]]}
    ).execute()

    # 2. 更新分類 (F 欄)
    if category:
        service.spreadsheets().values().update(
            spreadsheetId=wish_id,
            range=f'{tab_name}!F{target_row_idx}',
            valueInputOption='USER_ENTERED',
            body={'values': [[category]]}
        ).execute()

    # 3. 更新最後儲存時間 (I 欄)
    service.spreadsheets().values().update(
        spreadsheetId=wish_id,
        range=f'{tab_name}!I{target_row_idx}',
        valueInputOption='USER_ENTERED',
        body={'values': [[datetime.now(TW_TZ).strftime("%H:%M:%S")]]}
    ).execute()
    
    return jsonify({"status": "success", "message": "願望已更新"})

@app.route('/api/todo/update', methods=['POST'])
def update_todo():
    data = request.json
    item_id = str(data.get('id', ''))
    todo_id = get_todo_sheet_id()
    
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
                                      exclude_id=event_id,
                                      summary=event.get('summary'))
        
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
    sheet_id = get_pocket_sheet_id()
    service = get_sheets_service()

    if action == 'list':
        try:
            rows = get_sheet_values('口袋', spreadsheet_id=sheet_id)
            if not rows: return []
            pocket_list = []
            for row in rows[1:]: # 跳過表頭
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
                spreadsheetId=sheet_id, range='口袋!A2',
                valueInputOption='RAW', body=body).execute()
            return True
        except Exception as e:
            print(f"Error adding pocket item: {e}")
            return False

    elif action == 'delete':
        try:
            target_id = data.get('id')
            # 1. 先獲取試算表資訊，找出「口袋」分頁的 sheetId
            spreadsheet_metadata = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
            pocket_sheet_id = None
            for sheet in spreadsheet_metadata['sheets']:
                if sheet['properties']['title'] == '口袋':
                    pocket_sheet_id = sheet['properties']['sheetId']
                    break
            if pocket_sheet_id is None:
                pocket_sheet_id = spreadsheet_metadata['sheets'][0]['properties']['sheetId']

            # 2. 找出 ID 所在的行號 (利用 get_sheet_values 觸發自癒，且定位為 0-based)
            rows = get_sheet_values('口袋', spreadsheet_id=sheet_id)
            row_index = -1
            if rows:
                for i, row in enumerate(rows):
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
                            'sheetId': pocket_sheet_id,
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

            rows = get_sheet_values('口袋', spreadsheet_id=sheet_id)
            row_index = -1
            if rows:
                for i, row in enumerate(rows):
                    if row and row[0] == target_id:
                        row_index = i + 1
                        break

            if row_index == -1:
                return False

            body = {'values': [[new_cat]]}
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id, range=f'口袋!B{row_index}',
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

            rows = get_sheet_values('口袋', spreadsheet_id=sheet_id)
            row_index = -1
            if rows:
                for i, row in enumerate(rows):
                    if row and row[0] == target_id:
                        row_index = i + 1
                        break

            if row_index == -1:
                return False

            # 更新自訂稱呼 (Column F，即 '口袋!F' + row_index)
            body_note = {'values': [[new_note]]}
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id, range=f'口袋!F{row_index}',
                valueInputOption='RAW', body=body_note).execute()

            # 若有傳入主要名稱，更新主要名稱 (Column C，即 '口袋!C' + row_index)
            if new_name is not None:
                body_name = {'values': [[new_name]]}
                service.spreadsheets().values().update(
                    spreadsheetId=sheet_id, range=f'口袋!C{row_index}',
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
    health_id = get_health_sheet_id()
    if not health_id:
        return None
    try:
        rows = get_sheet_values('生理紀錄', spreadsheet_id=health_id)
        if not rows or len(rows) < 2:
            return None
            
        parsed_history = []
        cycles = []
        lengths = []
        
        for row in rows[1:]:
             # 0: 年度, 1: 月份, 2: 開始日期, 3: 結束日期, 4: 經期天數, 5: 週期天數, 6: 備註
             start_d = row[2] if len(row) > 2 else ""
             end_d = row[3] if len(row) > 3 and row[3].strip() else "進行中"
             symptoms = row[6] if len(row) > 6 else ""
             
             if start_d:
                 try:
                     parsed_dt = datetime.strptime(start_d.strip(), "%Y/%m/%d")
                     parsed_history.append({
                         "start": start_d.strip(),
                         "end": end_d.strip(),
                         "symptoms": symptoms.strip(),
                         "dt": parsed_dt
                     })
                 except Exception as e:
                     print(f"Skipping bad date format in row: {row}, error: {e}")
                 
             try:
                 if len(row) > 5 and row[5].strip():
                     cycles.append(int(row[5]))
                 if len(row) > 4 and row[4].strip():
                     lengths.append(int(row[4]))
             except: pass
        
        if not parsed_history:
            return None
            
        # 依開始日期進行降序排列（最新日期在最前面 history[0]），確保 latest_start 始終為最新紀錄，徹底防禦歷史亂序補錄
        parsed_history.sort(key=lambda x: x["dt"], reverse=True)
        history = [{"start": item["start"], "end": item["end"], "symptoms": item["symptoms"]} for item in parsed_history]
                 
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
    health_id = get_health_sheet_id()
    if not health_id:
         return jsonify({"status": "error", "message": "尚未設定 HEALTH_SHEET_ID"})
    try:
        status = get_current_cycle_status()
        if not status:
            return jsonify({
                "status": "success",
                "history": [],
                "avg_cycle": 28,
                "avg_length": 5,
                "days_until_next": 28,
                "next_date": "",
                "current_phase": "安全期 (濾泡期)",
                "phase_desc": "代謝極佳、思緒敏捷。精力充沛、皮膚狀況極佳，適合衝刺事業與高強度鍛鍊！",
                "phase_icon": "🟢",
                "pregnancy_probability": "🍀 不易懷孕 (安全期)",
                "is_cold_start": True
            })
            
        rows = get_sheet_values('生理紀錄', spreadsheet_id=health_id)
        parsed_history = []
        for row in rows[1:]:
             start_d = row[2] if len(row) > 2 else ""
             end_d = row[3] if len(row) > 3 and row[3].strip() else "進行中"
             symptoms = row[6] if len(row) > 6 else ""
             if start_d:
                 try:
                     parsed_dt = datetime.strptime(start_d.strip(), "%Y/%m/%d")
                     parsed_history.append({
                         "start": start_d.strip(),
                         "end": end_d.strip(),
                         "symptoms": symptoms.strip(),
                         "dt": parsed_dt
                     })
                 except:
                     pass
                     
        # 依開始日期降序排列
        parsed_history.sort(key=lambda x: x["dt"], reverse=True)
        history = [{"start": item["start"], "end": item["end"], "symptoms": item["symptoms"]} for item in parsed_history]
        
        # 歷史紀錄小於 2 筆即為冷啟動狀態
        is_cold_start = len(history) < 2
                  
        return jsonify({
            "status": "success",
            "history": history[:3],
            "is_cold_start": is_cold_start,
            **status
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/health/agree_disclaimer', methods=['POST'])
def agree_disclaimer():
    """
    雙重防線存證免責聲明：
    1. 在用戶的 Google 試算表「生理紀錄」中寫入一筆 SYSTEM 屬性的合規簽署紀錄 (Column A=SYSTEM, B=LEGAL, C=SYSTEM_NOTICE, D=AGREED, G=簽署日期與說明)。
    2. 若非單人模式且非開發者模擬，則在 TiDB users 資料庫寫入簽署時間戳記。
    """
    health_id = get_health_sheet_id()
    email = session.get('user_email', '')
    
    now_str = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. 寫入用戶的 Google 試算表（去中心化永久備份）
    if health_id:
        try:
            # 欄位：年度, 月份, 開始日期, 結束日期, 經期天數, 週期天數, 症狀/心情/備註
            row = [
                "SYSTEM", 
                "LEGAL", 
                "SYSTEM_NOTICE", 
                "AGREED", 
                "", 
                "", 
                f"已於 {now_str} 同意醫療暨避孕免責聲明 V1.0"
            ]
            append_to_sheet('生理紀錄', row, spreadsheet_id=health_id)
            print(f"[Google Sheet Consent Log] 成功為使用者 {email} 於試算表寫入簽署存證。")
        except Exception as e:
            print(f"[Google Sheet Consent Log] 寫入試算表失敗: {e}")
            
    # 2. 寫入 TiDB 雲端資料庫（開發者防抵賴存證）
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "false" and email:
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # 🛡️ 自癒式資料庫遷移：嘗試新增欄位（如果欄位不存在）
                try:
                    cursor.execute("ALTER TABLE users ADD COLUMN menstrual_disclaimer_agreed_at TIMESTAMP NULL DEFAULT NULL;")
                    conn.commit()
                    print("[TiDB Consent Log] 成功執行資料庫自動升級，新增 menstrual_disclaimer_agreed_at 欄位。")
                except Exception as db_err:
                    # 若已存在則會報錯，直接忽略即可
                    pass
                
                # 寫入同意時間
                cursor.execute(
                    "UPDATE users SET menstrual_disclaimer_agreed_at = NOW() WHERE email = %s;",
                    (email,)
                )
                conn.commit()
                print(f"[TiDB Consent Log] 成功為使用者 {email} 於 TiDB 寫入簽署時間戳記。")
        except Exception as e:
            print(f"[TiDB Consent Log] 寫入 TiDB 失敗: {e}")
            
    return jsonify({"status": "success", "message": "免責聲明簽署存證寫入成功！"})

@app.route('/api/health/check_disclaimer', methods=['GET'])
def check_disclaimer():
    """
    檢查使用者是否已經同意過免責聲明（雙重保險判定，跨裝置同步）。
    """
    email = session.get('user_email', '')
    
    # 1. 優先從 TiDB 資料庫查詢
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "false" and email:
        try:
            conn = get_db_connection()
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                # 確保欄位存在
                try:
                    cursor.execute("SELECT menstrual_disclaimer_agreed_at FROM users WHERE email = %s;", (email,))
                    res = cursor.fetchone()
                    if res and res.get('menstrual_disclaimer_agreed_at'):
                        print(f"[Check Disclaimer] 從 TiDB 查得 {email} 已同意。")
                        return jsonify({"status": "success", "agreed": True})
                except Exception as db_err:
                    # 欄位尚未建立或發生其他資料庫錯誤
                    pass
        except Exception as e:
            print(f"[Check Disclaimer] 查詢 TiDB 失敗: {e}")
            
    # 2. 如果資料庫查不到，則查詢 Google Sheets 作為第二保險
    health_id = get_health_sheet_id()
    if health_id:
        try:
            rows = get_sheet_values('生理紀錄', spreadsheet_id=health_id)
            if rows:
                for row in rows:
                    if len(row) > 3 and row[2] == "SYSTEM_NOTICE" and row[3] == "AGREED":
                        print(f"[Check Disclaimer] 從 Google Sheets 查得 {email} 已同意。")
                        return jsonify({"status": "success", "agreed": True})
        except Exception as e:
            print(f"[Check Disclaimer] 查詢 Google Sheets 失敗: {e}")
            
    return jsonify({"status": "success", "agreed": False})

def is_premium_user():
    """判斷使用者是否為 YEARLY_AI (Premium) 旗艦版尊榮會員"""
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "true":
        return True  # 本機單人模式完全開放
    
    developer_emails = {'ulir976272866@gmail.com', 'mina.chen.xstar.sg@gmail.com'}
    email = session.get('user_email', '')
    if email and email.lower() in developer_emails:
        return True # 開發者白名單豁免
        
    return session.get('subscription_type') == 'YEARLY_AI'

def check_and_deduct_points(email, cost_points):
    """
    檢查使用者點數是否足夠，若足夠則扣除並同步到資料庫與 session。
    若為單人模式或開發者白名單則無條件通過且不扣點。
    """
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "true":
        return True, 9999
        
    developer_emails = {'ulir976272866@gmail.com', 'mina.chen.xstar.sg@gmail.com'}
    if email and email.lower() in developer_emails:
        return True, 9999
        
    current_points = session.get('ai_points', 0)
    
    # 再次從 TiDB 資料庫中做最終確認，以防併發扣點漏洞
    try:
        conn = get_db_connection()
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT ai_points FROM users WHERE email = %s;", (email,))
            user = cursor.fetchone()
            if user:
                current_points = user.get('ai_points', 0)
    except Exception as e:
        print(f"[Points Check Error] {e}")
        
    if current_points < cost_points:
        return False, current_points
        
    new_points = current_points - cost_points
    session['ai_points'] = new_points
    
    # 更新到 TiDB 資料庫
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("UPDATE users SET ai_points = %s WHERE email = %s;", (new_points, email))
            conn.commit()
            print(f"[Points Deduction] 成功扣除 {email} {cost_points} 點，剩餘 {new_points} 點。")
    except Exception as e:
        print(f"[Points Update Error] {e}")
        
    return True, new_points

def ensure_stock_sheet_exists(spreadsheet_id):
    """
    自癒式股票分頁守衛：
    1. 檢查指定的 spreadsheet 是否有「💰股票投資組合」工作表，如果沒有則自動新建並初始化欄位。
    2. 自動化比照表頭鎖定技術，為「核心表頭 (Row 1)」與「即時市價與損益公式欄位 (Column H & I)」加上 warningOnly 警告保護鎖！
    """
    if not spreadsheet_id:
        return
    service = get_sheets_service()
    try:
        metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = metadata.get('sheets', [])
        titles = [s['properties']['title'] for s in sheets]
        
        if '💰股票投資組合' not in titles:
            print("[Stock Guard] 偵測到用戶試算表缺少「💰股票投資組合」分頁，啟動自動增量升級...")
            # 建立分頁
            req = {'addSheet': {'properties': {'title': '💰股票投資組合'}}}
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': [req]}
            ).execute()
            
            # 初始化表頭
            headers = [['交易日期', '股票代號', '股票名稱', '交易類型', '交易股數', '交易單價', '手續費', '即時市價', '即時損益', '備註']]
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range='💰股票投資組合!A1:J1',
                valueInputOption='USER_ENTERED',
                body={'values': headers}
            ).execute()
            print("[Stock Guard] 成功自動建立並初始化「💰股票投資組合」分頁與表頭！")
            
            # 重新拉取最新元數據以獲得新建分頁的 sheetId
            metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
            sheets = metadata.get('sheets', [])

        # 找到「💰股票投資組合」的 sheet_obj
        sheet_obj = None
        for s in sheets:
            if s['properties']['title'] == '💰股票投資組合':
                sheet_obj = s
                break
                
        if sheet_obj:
            # 1. 獨立的警告保護鎖設定區塊（若因權限不足失敗，不影響公式自癒）
            try:
                sheet_id = sheet_obj['properties']['sheetId']
                protected_ranges = sheet_obj.get('protectedRanges', [])
                
                has_header_protect = any(
                    p.get('range', {}).get('startRowIndex') == 0 and p.get('range', {}).get('endRowIndex') == 1
                    for p in protected_ranges
                )
                has_cols_protect = any(
                    p.get('range', {}).get('startRowIndex') == 1 and p.get('range', {}).get('startColumnIndex') == 7 and p.get('range', {}).get('endColumnIndex') == 9
                    for p in protected_ranges
                )
                
                reqs = []
                if not has_header_protect:
                    reqs.append({
                        "addProtectedRange": {
                            "protectedRange": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "startRowIndex": 0,
                                    "endRowIndex": 1,
                                    "startColumnIndex": 0,
                                    "endColumnIndex": 10
                                },
                                "description": "系統股票投資組合核心表頭，請勿任意變動以防當機",
                                "warningOnly": True
                            }
                        }
                    })
                    
                if not has_cols_protect:
                    reqs.append({
                        "addProtectedRange": {
                            "protectedRange": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "startRowIndex": 1,        # 從第二列開始保護數據行
                                    "startColumnIndex": 7,     # Column H (Index 7: 即時市價)
                                    "endColumnIndex": 9        # Column I (Index 8: 即時損益)
                                },
                                "description": "即時市價與即時損益公式欄位由系統自動運算，請勿手動編輯以免破壞公式",
                                "warningOnly": True
                            }
                        }
                    })
                    
                if reqs:
                    service.spreadsheets().batchUpdate(
                        spreadsheetId=spreadsheet_id,
                        body={'requests': reqs}
                    ).execute()
                    print("[Stock Guard] 成功為「💰股票投資組合」新增表頭與 H/I 即時欄位警告保護鎖！")
            except Exception as lock_err:
                print(f"[Stock Guard] 設定警告保護鎖時發生錯誤（已跳過並繼續公式自癒）: {lock_err}")
                
            # 2. 獨立的實時公式自癒守衛區塊（必定被執行）
            try:
                # 讀取「💰股票投資組合」的原始公式（使用 FORMULA 模式）以進行精確比對
                formula_res = service.spreadsheets().values().get(
                    spreadsheetId=spreadsheet_id,
                    range='💰股票投資組合!A1:J',
                    valueRenderOption='FORMULA'
                ).execute()
                formula_rows = formula_res.get('values', [])
                
                if len(formula_rows) > 1:
                    heal_updates = []
                    for idx, row in enumerate(formula_rows[1:], start=2):
                        # 若為空行或未填寫股票代號，跳過
                        if len(row) < 2 or not str(row[1]).strip():
                            continue
                            
                        # 預期公式
                        expected_h = f'=GOOGLEFINANCE(B{idx}, "price")'
                        expected_i = f'=IF(D{idx}="買進", (H{idx}-F{idx})*E{idx}-G{idx}, (F{idx}-H{idx})*E{idx}-G{idx})'
                        
                        current_h = row[7] if len(row) > 7 else ""
                        current_i = row[8] if len(row) > 8 else ""
                        
                        # 若公式損毀、被手動覆蓋或清空，自動執行單格自癒修復
                        if not str(current_h).strip().startswith('=GOOGLEFINANCE'):
                            heal_updates.append({
                                'range': f'💰股票投資組合!H{idx}',
                                'values': [[expected_h]]
                            })
                        if not str(current_i).strip().startswith('=IF'):
                            heal_updates.append({
                                'range': f'💰股票投資組合!I{idx}',
                                'values': [[expected_i]]
                            })
                            
                    if heal_updates:
                        print(f"[Stock Guard] 偵測到 {len(heal_updates)} 筆損毀的即時公式！啟動自動自癒修復程序...")
                        # 批次更新自癒公式
                        body = {
                            'valueInputOption': 'USER_ENTERED',
                            'data': heal_updates
                        }
                        service.spreadsheets().values().batchUpdate(
                            spreadsheetId=spreadsheet_id,
                            body=body
                        ).execute()
                        print("[Stock Guard] 公式自癒修復完成！已恢復為系統預設即時活公式。")
            except Exception as heal_err:
                print(f"[Stock Guard] 執行公式自癒守衛時發生錯誤: {heal_err}")
                
    except Exception as e:
        print(f"[Stock Guard] 確保股票分頁與保護鎖存在時發生錯誤: {e}")

def ensure_all_sheets_warning_protected(spreadsheet_id, service=None):
    """
    實時全局表頭與警告鎖自癒守衛：
    一次性為該 spreadsheet 的所有核心分頁（生理紀錄、記帳等）進行：
    1. 表頭名稱自癒（若被清空、修改或留白則強行還原）
    2. 自動加上警告保護鎖 (warningOnly: True)
    """
    if not spreadsheet_id:
        return
    try:
        if not service:
            service = get_sheets_service()
        metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = metadata.get('sheets', [])
        
        standard_headers_map = {
            '生理紀錄': ['年度', '月份', '日期', '動作', '症狀/心情', '週期', '備註'],
            '記帳': ['年度', '月份', '日期', '收入項目', '支出項目', '金額', '類別'],
            '待辦': ['建立日期', '事項/內容', '分類', '狀態', '唯一 ID', '建立時間', '優先級'],
            '日記': ['日期', '內容', '天氣', '心情', '時間'],
            '願望': ['建立日期', '商品名稱', '預估價格', '備註/連結', '狀態', '分類', '實際價格', '唯一 ID', '儲存時間'],
            '願望清單': ['建立日期', '商品名稱', '預估價格', '備註/連結', '狀態', '分類', '實際價格', '唯一 ID', '儲存時間'],
            '口袋': ['ID', '分類', '店名', '地址', '地區', '備註', '建立時間', '緯度', '經度'],
            'AI_指令集': ['觸發語句', '執行動作'],
            '💰股票投資組合': ['交易日期', '股票代號', '股票名稱', '交易類型', '交易股數', '交易單價', '手續費', '即時市價', '即時損益', '備註']
        }
        
        reqs = []
        for s in sheets:
            title = s['properties']['title']
            if title in standard_headers_map:
                sheet_id = s['properties']['sheetId']
                protected_ranges = s.get('protectedRanges', [])
                
                # A. 檢查並自癒表頭文字
                standard = standard_headers_map[title]
                try:
                    # 讀取 Row 1 的表頭
                    col_letter = chr(ord('A') + len(standard) - 1)
                    res = service.spreadsheets().values().get(
                        spreadsheetId=spreadsheet_id,
                        range=f"{title}!A1:{col_letter}1"
                    ).execute()
                    current = res.get('values', [[]])[0]
                except Exception:
                    current = []
                
                # 如果表頭留白、長度不對或不一致，啟動自癒覆蓋
                if len(current) != len(standard) or current != standard:
                    print(f"[Global Lock Guard] Detected header mismatch in sheet '{title}': {current} vs {standard}. Healing...")
                    col_letter = chr(ord('A') + len(standard) - 1)
                    service.spreadsheets().values().update(
                        spreadsheetId=spreadsheet_id,
                        range=f"{title}!A1:{col_letter}1",
                        valueInputOption='USER_ENTERED',
                        body={'values': [standard]}
                    ).execute()
                
                # B. 檢查並自癒警告保護鎖
                has_header_protect = any(
                    p.get('range', {}).get('startRowIndex') == 0 and p.get('range', {}).get('endRowIndex') == 1
                    for p in protected_ranges
                )
                if not has_header_protect:
                    reqs.append({
                        "addProtectedRange": {
                            "protectedRange": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "startRowIndex": 0,
                                    "endRowIndex": 1,
                                    "startColumnIndex": 0,
                                    "endColumnIndex": len(standard)
                                },
                                "description": f"系統 {title} 核心表頭，請勿任意變動以防當機",
                                "warningOnly": True
                            }
                        }
                    })
                    
        if reqs:
            print(f"[Global Lock Guard] Found {len(reqs)} sheets missing header warning locks. Restoring...")
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': reqs}
            ).execute()
            print("[Global Lock Guard] All missing header warning locks successfully restored!")
    except Exception as e:
        print(f"[Global Lock Guard Error] Central header/lock healer failed: {e}")

def get_stock_portfolio_report_text(spreadsheet_id):
    """
    獲取最新股票投資組合數據，並格式化為極致精美的對話框文字訊息 (V3 - 股數整數化)。
    """
    ensure_stock_sheet_exists(spreadsheet_id)
    try:
        rows = get_sheet_values('💰股票投資組合', spreadsheet_id=spreadsheet_id)
        if not rows or len(rows) < 2:
            return "📈 **智慧證券持股部位總覽**\n\n目前試算表尚無任何持股交易紀錄。您可點擊左側選單中的「➕ 新增持股」開始建檔登記喔！"
            
        transactions = []
        portfolio = {}
        for row in rows[1:]:
            if len(row) < 7 or not row[1].strip():
                continue
            ticker = row[1].strip().upper()
            name = row[2].strip()
            tx_type = row[3].strip()
            try:
                shares = round(float(row[4]), 2)
                price = float(row[5])
                fee = float(row[6]) if row[6] else 0.0
            except ValueError:
                continue
                
            live_price = 0.0
            if len(row) > 7 and row[7]:
                try:
                    live_price = float(str(row[7]).replace(',', '').strip())
                except ValueError:
                    pass
            
            transactions.append({
                "ticker": ticker,
                "name": name,
                "price": price,
                "live_price": live_price
            })
            
            if ticker not in portfolio:
                portfolio[ticker] = {
                    "ticker": ticker,
                    "name": name,
                    "net_shares": 0,
                    "total_cost": 0.0,
                    "live_price": 0.0,
                    "total_roi": 0.0,
                    "avg_cost": 0.0
                }
            p = portfolio[ticker]
            if tx_type == "買進":
                p["net_shares"] += shares
                p["total_cost"] += (shares * price + fee)
            elif tx_type == "賣出":
                p["net_shares"] -= shares
                p["total_cost"] -= (shares * price - fee)
                
            if live_price > 0:
                p["live_price"] = live_price
                
        active_portfolio = {}
        total_cost = 0.0
        total_value = 0.0
        total_roi = 0.0
        
        for t, p in portfolio.items():
            if p["net_shares"] > 0:
                p["avg_cost"] = round(p["total_cost"] / p["net_shares"], 2)
                if p["live_price"] <= 0:
                    ticker_txs = [tx for tx in transactions if tx["ticker"] == t]
                    if ticker_txs:
                        p["live_price"] = ticker_txs[-1]["price"]
                p["current_value"] = round(p["net_shares"] * p["live_price"], 2)
                p["total_roi"] = round(p["current_value"] - p["total_cost"], 2)
                
                total_cost += p["total_cost"]
                total_value += p["current_value"]
                total_roi += p["total_roi"]
                
                p["total_cost"] = round(p["total_cost"], 2)
                p["live_price"] = round(p["live_price"], 2)
                p["net_shares"] = int(round(p["net_shares"])) # 強制轉為整數顯示！
                active_portfolio[t] = p
                
        if not active_portfolio:
            return '<div style="line-height: 1.6;"><span style="color: #7c2d12; font-weight: bold; font-size: 1.02rem; display: block; margin-bottom: 8px;">📊 智慧證券持股部位總覽</span>目前試算表尚無任何持股交易紀錄。您可點選選單中的「➕ 新增持股」開始建檔登記喔！</div>'
            
        total_roi_rate = round((total_roi / total_cost) * 100, 2) if total_cost > 0 else 0.0
        roi_sign = "+" if total_roi >= 0 else ""
        roi_color = "🟢" if total_roi >= 0 else "🔴"
        roi_color_span = '<span style="color: #16a34a; font-weight: bold;">' if total_roi >= 0 else '<span style="color: #dc2626; font-weight: bold;">'
        
        report = '<div style="line-height: 1.6;">'
        report += '<span style="color: #7c2d12; font-weight: bold; font-size: 1.05rem; display: block; margin-bottom: 8px; border-bottom: 1.5px solid #fed7aa; padding-bottom: 4px;">📊 智慧證券持股部位總覽</span>'
        report += f'🌟 <span style="color: #0f172a; font-weight: bold;">總市值</span>：${int(total_value):,} NTD<br>'
        report += f'🪙 <span style="color: #0f172a; font-weight: bold;">總成本</span>：${int(total_cost):,} NTD<br>'
        report += f'⚖️ <span style="color: #0f172a; font-weight: bold;">總損益</span>：{roi_color} {roi_color_span}{roi_sign}${int(total_roi):,} ({roi_sign}{total_roi_rate}%)</span><br>'
        report += '<div style="border-top: 1px dashed #cbd5e1; margin: 10px 0;"></div>'
        
        for t, p in active_portfolio.items():
            p_roi = p["total_roi"]
            p_roi_rate = round((p_roi / p["total_cost"]) * 100, 2) if p["total_cost"] > 0 else 0.0
            p_roi_sign = "+" if p_roi >= 0 else ""
            p_roi_color = "🟢" if p_roi >= 0 else "🔴"
            p_roi_color_span = '<span style="color: #16a34a; font-weight: bold;">' if p_roi >= 0 else '<span style="color: #dc2626; font-weight: bold;">'
            
            # 換算張/股，將張/股部分高亮為深寶藍色 (#1d4ed8)
            shares = int(p['net_shares'])
            if shares >= 1000:
                sheets = shares // 1000
                rem_shares = shares % 1000
                if rem_shares > 0:
                    shares_str = f'🎟️ <span style="color: #1d4ed8; font-weight: bold;">{sheets}張 {rem_shares}股</span>'
                else:
                    shares_str = f'🎟️ <span style="color: #1d4ed8; font-weight: bold;">{sheets}張</span>'
            else:
                shares_str = f'🌱 <span style="color: #1d4ed8; font-weight: bold;">{shares}股</span>'
                
            report += f'<span style="color: #334155; font-weight: bold;">{p["name"]}</span>：<br>'
            report += f'已持有 {shares_str} / {p_roi_color} {p_roi_color_span}{p_roi_sign}${int(p_roi):,} ({p_roi_sign}{p_roi_rate}%)</span><br>'
            
        report += '<div style="border-top: 1px dashed #cbd5e1; margin: 10px 0;"></div>'
        report += '<span style="color: #64748b; font-size: 0.85rem; font-style: italic; display: block; margin-top: 5px;">💡 溫馨提示：點選選單中的「➕ 新增持股」可以快速登記交易明細或補登歷史部位！</span>'
        report += '</div>'
        return report
    except Exception as e:
        return f"❌ 彙整股票投資組合時發生錯誤：{str(e)}"

@app.route('/api/query_stock_portfolio', methods=['POST'])
def query_stock_portfolio_api():
    """
    一鍵查詢股票部位，並直接將精美報告返回給對話框。
    """
    if not is_premium_user():
        return jsonify({
            "status": "success", 
            "message": "🔒 「智慧股票投資記帳」為尊榮旗艦版 (YEARLY_AI) 獨享功能，請升級後體驗語音與一鍵資產看板功能！"
        })
        
    spreadsheet_id = get_spreadsheet_id()
    if not spreadsheet_id:
        return jsonify({"status": "error", "message": "尚未連結試算表"})
        
    report_text = get_stock_portfolio_report_text(spreadsheet_id)
    return jsonify({"status": "success", "message": report_text})

@app.route('/api/stock/portfolio', methods=['GET'])
def get_stock_portfolio():
    """
    獲取「💰股票投資組合」的交易紀錄，並由後端智慧彙整為證券資產組合。
    """
    # 權限驗證
    if not is_premium_user():
        return jsonify({
            "status": "locked", 
            "message": "💡 旗艦版尊榮功能：一鍵開通智慧股票存股健檢，解鎖零時差資產回報率精算！"
        })
        
    spreadsheet_id = get_spreadsheet_id()
    if not spreadsheet_id:
        return jsonify({"status": "error", "message": "尚未連結試算表"})
        
    # 自癒式保護：確保表單存在
    ensure_stock_sheet_exists(spreadsheet_id)
    
    try:
        # 讀取完整工作表
        rows = get_sheet_values('💰股票投資組合', spreadsheet_id=spreadsheet_id)
        if not rows or len(rows) < 2:
            return jsonify({
                "status": "success",
                "transactions": [],
                "portfolio": {},
                "summary": {
                    "total_cost": 0,
                    "total_value": 0,
                    "total_roi": 0,
                    "total_roi_rate": 0
                }
            })
            
        transactions = []
        portfolio = {}
        
        # 依列遍歷交易
        # headers: ['交易日期', '股票代號', '股票名稱', '交易類型', '交易股數', '交易單價', '手續費', '即時市價', '即時損益', '備註']
        # index:    0         1          2          3          4          5          6         7          8         9
        for i, row in enumerate(rows[1:], start=2):
            if len(row) < 7 or not row[1].strip():
                continue
                
            date_val = row[0].strip()
            ticker = row[1].strip().upper()
            name = row[2].strip()
            tx_type = row[3].strip() # 買進 或 賣出
            try:
                shares = round(float(row[4]), 2)
                price = float(row[5])
                fee = float(row[6]) if row[6] else 0.0
            except ValueError:
                continue
                
            # 讀取 Google Sheets 計算出來的即時價格與單筆損益 (如果存在且格式正確)
            live_price = 0.0
            tx_roi = 0.0
            if len(row) > 7 and row[7]:
                try:
                    live_price = float(str(row[7]).replace(',', '').strip())
                except ValueError:
                    pass
            if len(row) > 8 and row[8]:
                try:
                    tx_roi = float(str(row[8]).replace(',', '').strip())
                except ValueError:
                    pass
                    
            note = row[9].strip() if len(row) > 9 else ""
            
            transactions.append({
                "row_index": i,
                "date": date_val,
                "ticker": ticker,
                "name": name,
                "type": tx_type,
                "shares": shares,
                "price": price,
                "fee": fee,
                "live_price": live_price,
                "roi": tx_roi,
                "note": note
            })
            
            # 彙整投資組合
            if ticker not in portfolio:
                portfolio[ticker] = {
                    "ticker": ticker,
                    "name": name,
                    "net_shares": 0,
                    "total_cost": 0.0,
                    "live_price": 0.0,
                    "total_roi": 0.0,
                    "avg_cost": 0.0,
                    "dividends": 0.0
                }
                
            p = portfolio[ticker]
            if tx_type == "買進":
                p["net_shares"] += shares
                p["total_cost"] += (shares * price + fee)
            elif tx_type == "賣出":
                p["net_shares"] -= shares
                p["total_cost"] -= (shares * price - fee) # 賣出收回資金，減少成本
            elif tx_type in ["股息", "配息"]:
                # 股息收入：不增減股數與部位成本，但計入該檔持股與全域的累計已領股息
                dividend_amt = price * (shares if shares > 0 else 1.0)
                if "dividends" not in p:
                    p["dividends"] = 0.0
                p["dividends"] += dividend_amt
                
            # 保持最新的即時價格
            if live_price > 0:
                p["live_price"] = live_price
                
        # 刪除已出清的持股 (避免除以零且精簡顯示)
        active_portfolio = {}
        total_cost = 0.0
        total_value = 0.0
        total_roi = 0.0
        total_dividends = 0.0
        
        for t, p in portfolio.items():
            # 統計全域已領股息 (包含即使目前已出清的股票所領的股息)
            total_dividends += p.get("dividends", 0.0)
            
            if p["net_shares"] > 0:
                p["avg_cost"] = round(p["total_cost"] / p["net_shares"], 2)
                # 若 Google Sheet 還沒跑出 GOOGLEFINANCE，使用當前交易單價作為預估
                if p["live_price"] <= 0:
                    # 拿最後一筆交易的價格
                    ticker_txs = [tx for tx in transactions if tx["ticker"] == t]
                    if ticker_txs:
                        p["live_price"] = ticker_txs[-1]["price"]
                        
                p["current_value"] = round(p["net_shares"] * p["live_price"], 2)
                p["total_roi"] = round(p["current_value"] - p["total_cost"], 2)
                
                # 加總
                total_cost += p["total_cost"]
                total_value += p["current_value"]
                total_roi += p["total_roi"]
                
                # 四捨五入數值
                p["total_cost"] = round(p["total_cost"], 2)
                p["live_price"] = round(p["live_price"], 2)
                p["net_shares"] = round(p["net_shares"], 2)
                p["dividends"] = round(p.get("dividends", 0.0), 2)
                
                active_portfolio[t] = p
                
        total_roi_rate = round((total_roi / total_cost) * 100, 2) if total_cost > 0 else 0.0
        
        return jsonify({
            "status": "success",
            "transactions": transactions[-10:], # 回傳最後 10 筆明細
            "portfolio": active_portfolio,
            "summary": {
                "total_cost": round(total_cost, 2),
                "total_value": round(total_value, 2),
                "total_roi": round(total_roi, 2),
                "total_roi_rate": total_roi_rate,
                "total_dividends": round(total_dividends, 2)
            }
        })
        
    except Exception as e:
        print(f"[Stock API Error] {e}")
        return jsonify({"status": "error", "message": f"載入證券失敗: {str(e)}"})

@app.route('/api/stock/add_transaction', methods=['POST'])
def add_stock_transaction():
    """
    新增股票交易紀錄（買進 / 賣出），並自動計算 GoogleFinance 算力公式寫入試算表。
    """
    if not is_premium_user():
        return jsonify({"status": "locked", "message": "請先升級 Premium 旗艦版會員"})
        
    spreadsheet_id = get_spreadsheet_id()
    if not spreadsheet_id:
        return jsonify({"status": "error", "message": "尚未連結試算表"})
        
    ensure_stock_sheet_exists(spreadsheet_id)
    
    data = request.json or {}
    ticker = data.get('ticker', '').strip().upper()
    name = data.get('name', '').strip()
    tx_type = data.get('type', '買進').strip() # 買進 或 賣出
    
    try:
        shares = round(float(data.get('shares')), 2)
        price = float(data.get('price'))
        fee = float(data.get('fee', 0.0))
        date_str = data.get('date', datetime.now(TW_TZ).strftime("%Y-%m-%d")).strip()
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "輸入的股數、單價或金額格式不正確"})
        
    if not ticker or not name:
        return jsonify({"status": "error", "message": "請填寫股票代號與股票名稱"})
        
    try:
        # 讀取現有列數，以推算公式的列號 N
        rows = get_sheet_values('💰股票投資組合', spreadsheet_id=spreadsheet_id)
        next_row_index = len(rows) + 1 if rows else 2
        
        # 建立 GOOGLEFINANCE 與損益公式
        # Column H: 即時市價 =GOOGLEFINANCE(B{N}, "price")
        # Column I: 即時損益 =IF(D{N}="買進", (H{N}-F{N})*E{N}-G{N}, (F{N}-H{N})*E{N}-G{N})
        live_price_formula = f'=GOOGLEFINANCE(B{next_row_index}, "price")'
        roi_formula = f'=IF(D{next_row_index}="買進", (H{next_row_index}-F{next_row_index})*E{next_row_index}-G{next_row_index}, (F{next_row_index}-H{next_row_index})*E{next_row_index}-G{next_row_index})'
        
        row = [
            date_str,
            ticker,
            name,
            tx_type,
            shares,
            price,
            fee,
            live_price_formula,
            roi_formula,
            f"手動寫入交易 {tx_type}"
        ]
        
        append_to_sheet('💰股票投資組合', row, spreadsheet_id=spreadsheet_id)
        
        # 🌟 更新 TiDB 的 has_stock_record 標籤做為再行銷依據
        email = session.get('user_email', '')
        if os.getenv("SINGLE_USER_MODE", "false").lower() == "false" and email:
            try:
                conn = get_db_connection()
                with conn.cursor() as cursor:
                    # 確保 has_stock_record 欄位存在
                    try:
                        cursor.execute("UPDATE users SET has_stock_record = TRUE WHERE email = %s;", (email,))
                        conn.commit()
                        print(f"[TiDB Marketing] 已標記 {email} 的 has_stock_record = TRUE")
                    except Exception as e:
                        pass
            except Exception as e:
                print(f"[TiDB Marketing Error] {e}")
                
        return jsonify({"status": "success", "message": f"成功新增股票 {name} {tx_type}交易紀錄！"})
        
    except Exception as e:
        print(f"[Add Stock Tx Error] {e}")
        return jsonify({"status": "error", "message": f"新增股票交易失敗: {str(e)}"})

@app.route('/api/stock/ai_analysis', methods=['POST'])
def analyze_stock_portfolio():
    """
    一鍵 AI 股票資產健檢：
    打包股票工作表的歷史持股清單，消耗 30 點 AI 點數，調用 Gemini AI 進行大數據複雜診斷。
    """
    if not is_premium_user():
        return jsonify({
            "status": "locked", 
            "message": "💡 旗艦版尊榮功能：一鍵開通智慧股票存股健檢，解鎖零時差資產回報率精算！"
        })
        
    email = session.get('user_email', '')
    
    # 1. 扣除 30 點點數
    success, remaining_points = check_and_deduct_points(email, 30)
    if not success:
        return jsonify({
            "status": "error", 
            "message": f"您的 AI 額度不足囉！本次健檢需要 30 點，您目前僅剩 {remaining_points} 點。請前往充值或升級方案！"
        })
        
    spreadsheet_id = get_spreadsheet_id()
    if not spreadsheet_id:
        return jsonify({"status": "error", "message": "尚未連結試算表"})
        
    ensure_stock_sheet_exists(spreadsheet_id)
    
    try:
        # 2. 獲取投資組合數據
        rows = get_sheet_values('💰股票投資組合', spreadsheet_id=spreadsheet_id)
        if not rows or len(rows) < 2:
            return jsonify({
                "status": "success",
                "analysis": "💡 您的投資組合目前沒有持股紀錄，請先新增買進交易後再進行 AI 健檢診斷！",
                "remaining_points": remaining_points
            })
            
        # 整理持股清單
        portfolio_summary = []
        portfolio_map = {}
        for row in rows[1:]:
            if len(row) < 7 or not row[1].strip():
                continue
            ticker = row[1].strip()
            name = row[2].strip()
            tx_type = row[3].strip()
            try:
                shares = int(row[4])
                price = float(row[5])
                fee = float(row[6]) if row[6] else 0.0
            except ValueError:
                continue
                
            if ticker not in portfolio_map:
                portfolio_map[ticker] = {"name": name, "shares": 0, "total_cost": 0.0}
            p = portfolio_map[ticker]
            if tx_type == "買進":
                p["shares"] += shares
                p["total_cost"] += (shares * price + fee)
            elif tx_type == "賣出":
                p["shares"] -= shares
                p["total_cost"] -= (shares * price - fee)
                
        for ticker, p in portfolio_map.items():
            if p["shares"] > 0:
                avg_price = round(p["total_cost"] / p["shares"], 2)
                portfolio_summary.append(f"- 股票: {p['name']} ({ticker}), 持股股數: {p['shares']} 股, 持股均價: {avg_price} 元, 總投入成本: {round(p['total_cost'], 2)} 元")
                
        if not portfolio_summary:
            return jsonify({
                "status": "success",
                "analysis": "💡 您的投資組合目前沒有任何有效持股（已出清），請先新增買進交易後再進行 AI 健檢診斷！",
                "remaining_points": remaining_points
            })
            
        portfolio_text = "\n".join(portfolio_summary)
        
        # 3. 呼叫 Gemini AI 進行診斷
        prompt = f"""
你是一位頂尖的資深證券分析師與智能財富管家。
請為用戶當前的存股投資組合進行全方位的一鍵 AI 投資組合健檢診斷。

用戶目前的持股清單如下：
{portfolio_text}

請從以下幾個維度給出極具專業度、實用度且高端優雅的健檢報告：
1. 【📊 投資組合健康度診斷】：分析資產配置是否過度集中、產業覆蓋度與整體風險防禦能力。
2. 【📈 個股潛力與行情解讀】：對持股清單中的主力股票（如台積電等台股熱門股）進行近期市場行情解析與技術面、基本面展望。
3. 【💡 智慧理財與存股操作建議】：給出具體且溫良有度的資產配置建議（例如加碼、減碼、防守型策略、零成本存股心法）。
4. 【🎯 未來30天行動指南】：列出三條具體、可執行的理財建議。

注意：請使用繁體中文回答，口吻必須高端優雅、條理分明、溫柔而極具智慧與洞察力，字數約 600 - 800 字。
"""
        # 使用專案現有的 Gemini 呼叫方法
        from google.generativeai import GenerativeModel
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        analysis_report = response.text
        
        return jsonify({
            "status": "success",
            "analysis": analysis_report,
            "remaining_points": remaining_points
        })
        
    except Exception as e:
        print(f"[Stock AI Analysis Error] {e}")
        return jsonify({
            "status": "error", 
            "message": f"AI 健檢失敗: {str(e)}"
        })

@app.route('/api/health/record_start', methods=['POST'])
def record_health_start():
    health_id = get_health_sheet_id()
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
        sheet_obj = next(s for s in sh['sheets'] if s['properties']['title'] == '生理紀錄')
        sheet_id = sheet_obj['properties']['sheetId']
        
        # 插入新的一列
        requests = [{
            "insertDimension": {
                "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 1, "endIndex": 2},
                "inheritFromBefore": False
            }
        }]
        
        # 檢查第一列 (Row 1) 是否設有警告保護鎖，若無則一併加入保護請求
        has_protection = any(
            p.get('range', {}).get('startRowIndex') == 0 and p.get('range', {}).get('endRowIndex') == 1
            for p in sheet_obj.get('protectedRanges', [])
        )
        if not has_protection:
            requests.append({
                "addProtectedRange": {
                    "protectedRange": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": 7
                        },
                        "description": "系統生理紀錄核心表頭，請勿任意變動以防當機",
                        "warningOnly": True
                    }
                }
            })
            
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
            
        # 自動實體排序 (將 A2 到最後一列依據 C 欄降序排列，確保最新日期始終在最上方 Row 2)
        try:
            sort_req = {
                "sortRange": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 7},
                    "sortSpecs": [{"dimensionIndex": 2, "sortOrder": "DESCENDING"}]
                }
            }
            service_sheets.spreadsheets().batchUpdate(spreadsheetId=health_id, body={"requests": [sort_req]}).execute()
        except Exception as sort_err:
            print(f"Auto-sorting error in record_health_start: {sort_err}")
        
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
    health_id = get_health_sheet_id()
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

@app.route('/api/health/backfill', methods=['POST'])
def backfill_health():
    health_id = get_health_sheet_id()
    if not health_id:
        return jsonify({"status": "error", "message": "尚未設定 HEALTH_SHEET_ID"})
    try:
        data = request.get_json() or {}
        start_date = data.get('start_date') # YYYY-MM-DD
        end_date = data.get('end_date') # YYYY-MM-DD
        symptoms = data.get('symptoms', '').strip() or "歷史補錄數據"
        
        if not start_date or not end_date:
            return jsonify({"status": "error", "message": "開始日期與結束日期為必填欄位"})
            
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        
        if start_dt > end_dt:
            return jsonify({"status": "error", "message": "開始日期不能大於結束日期"})
            
        # 轉換為標準 %Y/%m/%d 寫入格式
        start_formatted = start_dt.strftime("%Y/%m/%d")
        end_formatted = end_dt.strftime("%Y/%m/%d")
        
        # 經期天數
        period_length = (end_dt - start_dt).days + 1
        
        # 取得年度與月份
        year = str(start_dt.year)
        month = str(start_dt.month)
        
        # 讀取現有生理紀錄，推算此補錄相較於之前最近的開始日期的週期天數
        rows = get_sheet_values('生理紀錄', spreadsheet_id=health_id)
        cycle_days = 28 # 預設
        
        existing_starts = []
        if rows and len(rows) > 1:
            for row in rows[1:]:
                if len(row) > 2 and row[2].strip():
                    try:
                        p_dt = datetime.strptime(row[2].strip(), "%Y/%m/%d")
                        existing_starts.append(p_dt)
                    except:
                        pass
                        
        # 加入本次補錄日期並升序排列，找出前一個最近的開始日期來精算週期
        all_starts = sorted(existing_starts + [start_dt])
        idx = all_starts.index(start_dt)
        if idx > 0:
            cycle_days = (start_dt - all_starts[idx - 1]).days
            
        # 寫入一行完整 7 個欄位: [年度, 月份, 開始日期, 結束日期, 經期天數, 週期天數, 症狀/備註]
        new_row = [year, month, start_formatted, end_formatted, str(period_length), str(cycle_days), symptoms]
        
        # 呼叫標準寫入，插入在第二列（與 record_start 保持一致，使最新紀錄在頂部）
        service_sheets = get_sheets_service()
        sh = service_sheets.spreadsheets().get(spreadsheetId=health_id).execute()
        sheet_obj = next(s for s in sh['sheets'] if s['properties']['title'] == '生理紀錄')
        sheet_id = sheet_obj['properties']['sheetId']
        
        # 插入新的一列
        requests = [{
            "insertDimension": {
                "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 1, "endIndex": 2},
                "inheritFromBefore": False
            }
        }]
        
        # 檢查第一列 (Row 1) 是否設有警告保護鎖，若無則一併加入保護請求
        has_protection = any(
            p.get('range', {}).get('startRowIndex') == 0 and p.get('range', {}).get('endRowIndex') == 1
            for p in sheet_obj.get('protectedRanges', [])
        )
        if not has_protection:
            requests.append({
                "addProtectedRange": {
                    "protectedRange": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": 7
                        },
                        "description": "系統生理紀錄核心表頭，請勿任意變動以防當機",
                        "warningOnly": True
                    }
                }
            })
            
        service_sheets.spreadsheets().batchUpdate(spreadsheetId=health_id, body={"requests": requests}).execute()
        
        # 寫入新資料到 A2
        service_sheets.spreadsheets().values().update(
            spreadsheetId=health_id, range="生理紀錄!A2",
            valueInputOption="USER_ENTERED", body={"values": [new_row]}
        ).execute()
        
        # 自動實體排序 (將 A2 到最後一列依據 C 欄降序排列，確保最新日期始終在最上方 Row 2)
        try:
            sort_req = {
                "sortRange": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 7},
                    "sortSpecs": [{"dimensionIndex": 2, "sortOrder": "DESCENDING"}]
                }
            }
            service_sheets.spreadsheets().batchUpdate(spreadsheetId=health_id, body={"requests": [sort_req]}).execute()
        except Exception as sort_err:
            print(f"Auto-sorting error in backfill_health: {sort_err}")
            
        return jsonify({"status": "success", "message": "歷史生理紀錄補錄成功！🌸"})
    except Exception as e:
        print(f"Error backfilling health records: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/health/symptoms/options', methods=['GET', 'POST', 'DELETE'])
def manage_symptoms_options():
    health_id = get_health_sheet_id()
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
    health_id = get_health_sheet_id()
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
    health_id = get_health_sheet_id()
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
    health_id = get_health_sheet_id()
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

def init_stock_suggestions_table():
    """初始化 TiDB 股票選單聯想庫"""
    print("[Stock DB Guard] 啟動 TiDB 股票選單聯想表檢查與自癒程序...")
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 1. 建立 table (如果不存在)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stock_suggestions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    ticker VARCHAR(50) UNIQUE NOT NULL,
                    name VARCHAR(100) NOT NULL,
                    short_code VARCHAR(50) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # 2. 檢查是否已經有資料，如果沒有則寫入預設的種子熱門股票
            cursor.execute("SELECT COUNT(*) FROM stock_suggestions;")
            res = cursor.fetchone()
            count = res[0] if res else 0
            if count == 0:
                print("[Stock DB Guard] 偵測到選單表為空，開始寫入預設種子熱門證券資產...")
                seeds = [
                    ("TPE:0050", "元大台灣50", "0050"),
                    ("TPE:0056", "元大高股息", "0056"),
                    ("TPE:00878", "國泰永續高股息", "00878"),
                    ("TPE:00919", "群益台灣精選高息", "00919"),
                    ("TPE:00929", "復華台灣科技優息", "00929"),
                    ("TPE:2330", "台積電", "2330"),
                    ("TPE:2317", "鴻海", "2317"),
                    ("TPE:2454", "聯發科", "2454"),
                    ("TPE:2303", "聯電", "2303"),
                    ("TPE:2603", "長榮", "2603"),
                    ("TPE:2618", "長榮航", "2618"),
                    ("TPE:2002", "中鋼", "2002"),
                    ("TPE:2308", "台達電", "2308"),
                    ("TPE:2881", "富邦金", "2881"),
                    ("TPE:2882", "國泰金", "2882"),
                    ("TPE:2884", "玉山金", "2884"),
                    ("TPE:2886", "兆豐金", "2886"),
                    ("TPE:2891", "中信金", "2891"),
                    ("NASDAQ:AAPL", "Apple", "AAPL"),
                    ("NASDAQ:NVDA", "Nvidia", "NVDA"),
                    ("NASDAQ:MSFT", "Microsoft", "MSFT"),
                    ("NASDAQ:TSLA", "Tesla", "TSLA")
                ]
                cursor.executemany(
                    "INSERT INTO stock_suggestions (ticker, name, short_code) VALUES (%s, %s, %s);",
                    seeds
                )
                conn.commit()
                print("[Stock DB Guard] 預設熱門證券種子已成功匯入 TiDB 資料庫！")
        conn.close()
    except Exception as e:
        print(f"[Stock DB Guard Error] 初始化資料庫失敗: {e}")

@app.route('/api/stock/suggestions', methods=['GET'])
def get_stock_suggestions_api():
    """
    從 TiDB Cloud 中模糊查詢匹配的熱門股票代號與名稱
    """
    q = request.args.get('q', '').strip().lower()
    if not q:
        return jsonify([])
        
    try:
        conn = get_db_connection()
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            like_val = f"%{q}%"
            cursor.execute("""
                SELECT ticker, name, short_code FROM stock_suggestions
                WHERE LOWER(ticker) LIKE %s 
                   OR LOWER(name) LIKE %s 
                   OR LOWER(short_code) LIKE %s
                LIMIT 10;
            """, (like_val, like_val, like_val))
            matches = cursor.fetchall()
        conn.close()
        return jsonify(matches)
    except Exception as e:
        print(f"[Stock Suggestions API Error] {e}")
        return jsonify([])

def sync_taiwan_stocks_to_db():
    """
    從台灣證交所 (TWSE) 與櫃買中心 (TPEx) 官方 OpenAPI 抓取最新上市、上櫃股票與 ETF 清單，
    並自動以批次 Upsert 寫入 TiDB 的 stock_suggestions 表，保持代號與名稱隨時最新。
    """
    import requests
    print("[Stock Sync] 啟動全台灣上市上櫃股票/ETF 資料庫實時同步程序...")
    try:
        # 1. 抓取上市股票 (TWSE)
        twse_url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
        twse_res = requests.get(twse_url, timeout=15)
        twse_data = twse_res.json()
        
        # 2. 抓取上櫃股票 (TPEx)
        tpex_url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
        tpex_res = requests.get(tpex_url, timeout=15)
        tpex_data = tpex_res.json()
        
        records = []
        seen = set() # 防止重複
        
        # 處理上市資料
        for item in twse_data:
            code = item.get('Code', '').strip()
            name = item.get('Name', '').strip()
            # 篩選標準：代碼長度小於等於 6 位（過濾掉極長且雜亂的權證與公司債，保留正統股票與 ETF）
            if code and len(code) <= 6 and code not in seen:
                ticker = f"TPE:{code}"
                records.append((ticker, name, code))
                seen.add(code)
                
        # 處理上櫃資料
        for item in tpex_data:
            code = item.get('SecuritiesCompanyCode', '').strip()
            name = item.get('CompanyName', '').strip()
            if code and len(code) <= 6 and code not in seen:
                ticker = f"TPE:{code}"
                records.append((ticker, name, code))
                seen.add(code)
                
        print(f"[Stock Sync] 資料清洗完成，共計 {len(records)} 檔有效標的。開始寫入 TiDB...")
        
        # 3. 寫入 TiDB (使用 ON DUPLICATE KEY UPDATE 增量更新)
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.executemany("""
                INSERT INTO stock_suggestions (ticker, name, short_code) 
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE name = VALUES(name), short_code = VALUES(short_code);
            """, records)
            conn.commit()
        conn.close()
        print(f"[Stock Sync] 同步大成功！共 {len(records)} 檔台灣上市上櫃股票/ETF 已經 100% 寫入您的 TiDB 資料庫！")
        return len(records)
    except Exception as e:
        print(f"[Stock Sync Error] 同步台灣股票時發生錯誤: {e}")
        return 0

@app.route('/api/admin/sync_stocks', methods=['POST'])
def force_sync_stocks_api():
    """
    提供開發者手動點擊或定期 Cron 觸發的全台股票同步端點
    """
    import threading
    # 啟動非同步執行，防止 HTTP 請求阻塞
    threading.Thread(target=sync_taiwan_stocks_to_db, daemon=True).start()
    return jsonify({"status": "success", "message": "已在背景啟動全台上市櫃股票與 ETF 同步作業！🚀"})

if __name__ == '__main__':
    # 確保 TiDB 資料庫選單表已初始化自癒
    init_stock_suggestions_table()
    # 啟動背景執行緒，自動非同步與 TWSE/TPEx 同步全台灣股票與 ETF
    import threading
    threading.Thread(target=sync_taiwan_stocks_to_db, daemon=True).start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)
