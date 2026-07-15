import os
import socket
# 🛠️ macOS IPv6/IPv4 DNS 優先權優化：強制 Python socket 僅使用 AF_INET (IPv4)
# 解決 macOS 環境下 socket 連線優先嘗試 IPv6 導致的 10 秒+ 網路請求逾時問題
orig_getaddrinfo = socket.getaddrinfo
def getaddrinfo_ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
    return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = getaddrinfo_ipv4_only

# 本地開發允許使用 HTTP 進行 OAuth 驗證 (防止 InsecureTransportError)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
# 允許 OAuth Token 範圍變更 (防止 Scope has changed Warning 導致崩潰)
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
import json
import uuid
import hashlib
import urllib.parse
import math
import requests
import pymysql
from datetime import datetime, time, timedelta, timezone

# ============================================================
# 🏦 綠界科技（ECPay）金流串接設定
# ============================================================
ECPAY_MERCHANT_ID = os.getenv('ECPAY_MERCHANT_ID', '2000132')
ECPAY_HASH_KEY    = os.getenv('ECPAY_HASH_KEY', '5294y06JbISpM5x9')   # 預設為官方測試 HashKey
ECPAY_HASH_IV     = os.getenv('ECPAY_HASH_IV', 'v77hoKGq4kWxNNIS')     # 預設為官方測試 HashIV
ECPAY_API_URL     = os.getenv('ECPAY_API_URL', 'https://payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5')


def generate_check_mac_value(params: dict) -> str:
    """
    依照綠界官方規範計算 CheckMacValue：
    1. 排序（參數名稱 ASCII 升冪）
    2. 組成字串：HashKey={key}&k1=v1&...&HashIV={iv}
    3. URL Encode（UrlEncode 規範）後轉小寫
    4. SHA256 雜湊後轉大寫
    """
    # Step 1：依參數名稱升冪排序
    sorted_params = sorted(params.items(), key=lambda x: x[0].lower())
    # Step 2：組成待簽章字串
    raw = f"HashKey={ECPAY_HASH_KEY}&" + "&".join(f"{k}={v}" for k, v in sorted_params) + f"&HashIV={ECPAY_HASH_IV}"
    # Step 3：URL Encode 後轉小寫（符合 .NET UrlEncode 規範）
    encoded = urllib.parse.quote_plus(raw).lower()
    # Step 4：SHA256 雜湊後轉大寫（EncryptType=1 使用 SHA256）
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest().upper()

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
        res = self.get_inner_tz().dst(naive_dt)
        return res if res is not None else timedelta(0)

TW_TZ = DynamicTimezone()

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_from_directory, make_response
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
app.jinja_env.globals.update(os=os)
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
        if 'user_email' in session:
            try:
                user = get_user_by_email(session['user_email'])
                if user and user.get('google_refresh_token'):
                    session['credentials'] = {
                        'token': None,
                        'refresh_token': user['google_refresh_token'],
                        'token_uri': 'https://oauth2.googleapis.com/token',
                        'client_id': CLIENT_ID,
                        'client_secret': CLIENT_SECRET,
                        'scopes': SCOPES
                    }
                    session.modified = True
                    print(f"Dynamically reconstructed credentials from TiDB Cloud for {session['user_email']}")
                else:
                    return None
            except Exception as ex:
                print(f"Failed to reconstruct credentials from TiDB: {ex}")
                return None
        else:
            return None
    creds_data = session['credentials']
    # 解析 expiry 字串回 datetime 物件，讓 creds.expired 能正確判斷過期狀態
    expiry_dt = None
    expiry_str = creds_data.get('expiry')
    if expiry_str:
        try:
            from datetime import datetime as _dt
            expiry_dt = _dt.fromisoformat(expiry_str)
        except Exception:
            pass
    creds = OAuthCredentials(
        token=creds_data.get('token'),
        refresh_token=creds_data.get('refresh_token'),
        token_uri=creds_data.get('token_uri'),
        client_id=creds_data.get('client_id'),
        client_secret=creds_data.get('client_secret'),
        scopes=creds_data.get('scopes')
    )
    if expiry_dt:
        creds.expiry = expiry_dt
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

    # 強制刷新條件：token 已過期、token 為 None（session 重建後沒有有效 token），或偵測到明確過期
    needs_refresh = (
        (creds.expired) or
        (not creds.token) or
        (creds_data.get('token') is None)
    )
    if needs_refresh and creds.refresh_token:
        try:
            creds.refresh(Request())
            session['credentials'] = {
                'token': creds.token,
                'refresh_token': creds.refresh_token,
                'token_uri': creds.token_uri,
                'client_id': creds.client_id,
                'client_secret': creds.client_secret,
                'scopes': creds.scopes,
                'expiry': creds.expiry.isoformat() if creds.expiry else None
            }
            session.modified = True
            print(f"[OAuth] Token refreshed successfully for {session.get('user_email', 'unknown')}")
        except Exception as e:
            print(f"Error refreshing OAuth credentials: {e}")
            # 刷新失敗時清除過期憑證，避免帶著失效 token 繼續執行
            session.pop('credentials', None)
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
        import requests
        headers = {'Authorization': f'Bearer {creds.token}'}
        res = requests.get('https://www.googleapis.com/oauth2/v2/userinfo', headers=headers, timeout=10)
        if res.status_code == 200:
            return res.json()
        else:
            print(f"Error getting user info: HTTP {res.status_code} - {res.text}")
            return None
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
    # 🌟 智慧相容 macOS 與 Google Cloud Run (Linux Debian) SSL 憑證路徑
    ssl_config = {}
    for path in ["/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt"]:
        if os.path.exists(path):
            ssl_config = {"ssl_ca": path}
            break
    return pymysql.connect(
        host=TIDB_HOST,
        user=TIDB_USER,
        password=TIDB_PASSWORD,
        port=TIDB_PORT,
        database=TIDB_DATABASE,
        ssl=ssl_config if ssl_config else {"ssl": {}}
    )

def is_payment_allowed():
    """強制開放全網點數儲值與訂閱功能，便於統一金流測試"""
    return True

def get_user_by_email(email):
    """從 TiDB 查詢使用者，若為單人模式或開發者白名單信箱則直接回傳開發者模擬 VIP 帳號"""
    user = None
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT * FROM users WHERE email = %s;", (email,))
            user = cursor.fetchone()

            if user:
                # 🌟 誤遷移試用用戶自動反向自癒還原 🌟
                # 如果使用者的 subscription_expires_at 與註冊時間相差小於等於 8 天，說明這是個 7天試用帳戶，先前被誤遷移成了正式訂閱。我們必須將其還原為試用狀態！
                if user.get('subscription_expires_at') and user.get('created_at'):
                    from datetime import datetime, timedelta
                    sub_exp = user.get('subscription_expires_at')
                    created_at = user.get('created_at')
                    if isinstance(sub_exp, str):
                        try: sub_exp = datetime.strptime(sub_exp, "%Y-%m-%d %H:%M:%S")
                        except ValueError: pass
                    if isinstance(created_at, str):
                        try: created_at = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                        except ValueError: pass
                    
                    if sub_exp and created_at and (sub_exp - created_at).days <= 8:
                        print(f"[TiDB Self-Healing] 偵測到誤遷移的試用用戶 {email}，正在自動將其還原為試用狀態...")
                        cursor.execute(
                            "UPDATE users SET trial_expires_at = %s, subscription_expires_at = NULL WHERE email = %s;",
                            (sub_exp, email)
                        )
                        conn.commit()
                        # 重新獲取還原後的最新資料
                        cursor.execute("SELECT * FROM users WHERE email = %s;", (email,))
                        user = cursor.fetchone()

                # 🌟 補救手動修改資料庫漏填時間的自癒守衛 🌟
                # 如果是訂閱狀態，但資料庫中「正式到期日」與「試用到期日」皆為空，說明是手動變更權限時漏填了時間。
                # 系統會自動以註冊時間 (created_at) 為基礎，自癒補填對應天數（基礎版補 30 天，旗艦版補 365 天）！
                if user.get('is_subscribed') and user.get('subscription_type') in ['YEARLY_AI', 'MONTHLY_AI', 'PREMIUM_MONTHLY'] and not user.get('subscription_expires_at') and not user.get('trial_expires_at'):
                    from datetime import datetime, timedelta
                    created_at = user.get('created_at') or datetime.now()
                    if isinstance(created_at, str):
                        try: created_at = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                        except ValueError: created_at = datetime.now()
                    
                    if user.get('subscription_type') == 'YEARLY_AI':
                        healed_exp = created_at + timedelta(days=365)
                    elif user.get('subscription_type') == 'PREMIUM_MONTHLY':
                        healed_exp = created_at + timedelta(days=30)
                    else:
                        healed_exp = created_at + timedelta(days=30)
                    
                    print(f"[TiDB Self-Healing] 偵測到用戶 {email} 訂閱欄位漏填到期時間，正在自動自癒補填為 {healed_exp}...")
                    cursor.execute(
                        "UPDATE users SET subscription_expires_at = %s WHERE email = %s;",
                        (healed_exp, email)
                    )
                    conn.commit()
                    # 重新獲取自癒後的最新資料
                    cursor.execute("SELECT * FROM users WHERE email = %s;", (email,))
                    user = cursor.fetchone()

                # 🌟 舊用戶正式訂閱屬性自動遷移自癒 (如果 subscription_expires_at 為 NULL 且是訂閱用戶) 🌟
                if user.get('is_subscribed') and user.get('subscription_type') in ['YEARLY_AI', 'MONTHLY_AI', 'PREMIUM_MONTHLY'] and not user.get('subscription_expires_at'):
                    from datetime import datetime, timedelta
                    old_expiry = user.get('trial_expires_at')
                    if old_expiry and isinstance(old_expiry, str):
                        try:
                            old_expiry = datetime.strptime(old_expiry, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            pass
                    
                    # 只有當舊的試用日期大於「現在時間 + 30 天」時，才代表這是舊系統用來充當正式訂閱的遙遠未來 mock 日期（如 2028-12-31）
                    # 如果是小於等於 30 天（例如註冊贈送的 7天試用），則【絕對不能】誤遷移成正式訂閱！
                    new_sub_expiry = None
                    if old_expiry and old_expiry > datetime.now() + timedelta(days=30):
                        new_sub_expiry = old_expiry
                    
                    if new_sub_expiry:
                        # 將舊的試用到期日強制重設為已過期 (防止卡在試用狀態)，並更新正式訂閱時間
                        expired_trial = datetime.now() - timedelta(days=1)
                        print(f"[TiDB Migration] 自動自癒！將舊用戶 {email} 遷移至正式訂閱。到期日: {new_sub_expiry}")
                        cursor.execute(
                            "UPDATE users SET subscription_expires_at = %s, trial_expires_at = %s WHERE email = %s;",
                            (new_sub_expiry, expired_trial, email)
                        )
                        conn.commit()
                        # 重新獲取自癒後的最新資料，避免後續屬性錯誤
                        cursor.execute("SELECT * FROM users WHERE email = %s;", (email,))
                        user = cursor.fetchone()
                
                # 🌟 7天旗艦版免費試用過期安全降級守衛 🌟
                if user.get('trial_expires_at'):
                    from datetime import datetime
                    expires_at = user.get('trial_expires_at')
                    if isinstance(expires_at, str):
                        try:
                            expires_at = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            pass
                    
                    # 檢查使用者是否處於有效的正式訂閱期內，若是，則不受試用過期影響
                    is_formally_subscribed = False
                    if user.get('subscription_expires_at'):
                        sub_exp = user.get('subscription_expires_at')
                        if isinstance(sub_exp, str):
                            try:
                                sub_exp = datetime.strptime(sub_exp, "%Y-%m-%d %H:%M:%S")
                            except ValueError:
                                pass
                        if sub_exp and datetime.now() < sub_exp:
                            is_formally_subscribed = True
                    
                    # 如果試用期限已過，且使用者目前的 subscription_type 不是 NONE，且使用者「沒有」處於有效的正式訂閱期內，則降級為免費版
                    if expires_at and datetime.now() > expires_at and user.get('subscription_type') != 'NONE' and not is_formally_subscribed:
                        print(f"[TiDB Guard] 使用者 {email} 的 7天試用已過期！自動安全降級為免費基礎版 (NONE)")
                        cursor.execute(
                            "UPDATE users SET is_subscribed = FALSE, subscription_type = 'NONE', ai_points = 0 WHERE email = %s;",
                            (email,)
                        )
                        conn.commit()
                        # 重新拉取已降級的最新資料
                        cursor.execute("SELECT * FROM users WHERE email = %s;", (email,))
                        user = cursor.fetchone()

                # 🌟 正式訂閱過期安全降級守衛 🌟
                if user.get('subscription_expires_at'):
                    from datetime import datetime
                    sub_expires_at = user.get('subscription_expires_at')
                    if isinstance(sub_expires_at, str):
                        try:
                            sub_expires_at = datetime.strptime(sub_expires_at, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            pass
                    
                    # 如果訂閱期限已過，且使用者目前的 subscription_type 不是 NONE，則降級為免費版
                    if sub_expires_at and datetime.now() > sub_expires_at and user.get('subscription_type') != 'NONE':
                        print(f"[TiDB Guard] 使用者 {email} 的正式訂閱已過期！自動安全降級為免費基礎版 (NONE)")
                        cursor.execute(
                            "UPDATE users SET is_subscribed = FALSE, subscription_type = 'NONE', ai_points = 0 WHERE email = %s;",
                            (email,)
                        )
                        conn.commit()
                        # 重新拉取已降級的最新資料
                        cursor.execute("SELECT * FROM users WHERE email = %s;", (email,))
                        user = cursor.fetchone()
    except Exception as e:
        print(f"Error handling user guards for {email}: {e}")
    finally:
        if conn:
            conn.close()

    if not user:
        developer_emails = {'ulir976272866@gmail.com'}
        if os.getenv("SINGLE_USER_MODE", "false").lower() == "true" or (email and email.lower() in developer_emails):
            from datetime import datetime, timedelta
            user = {
                "user_id": "uid_owner",
                "email": email,
                "is_subscribed": True,
                "subscription_type": "YEARLY_AI",
                "ai_points": 9999,
                "has_stock_record": True,
                "subscription_expires_at": datetime.now() + timedelta(days=365)
            }
            
    return user

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

def _is_admin_context():
    """判斷目前請求是否為管理者（SINGLE_USER_MODE 或 開發者信箱）"""
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "true":
        return True
    try:
        user_info = get_user_info()
        if user_info and user_info.get('email') == os.getenv("GOOGLE_CALENDAR_ID"):
            return True
    except Exception:
        pass
    return False

def get_diary_sheet_id():
    """日記分頁所在試算表 ID：管理者使用統一的 GOOGLE_SHEET_ID，一般用戶使用其個人試算表"""
    if _is_admin_context():
        return os.getenv("GOOGLE_SHEET_ID")
    return session.get('spreadsheet_id') or os.getenv("GOOGLE_SHEET_ID")

def get_todo_sheet_id():
    """待辦分頁所在試算表 ID：管理者使用統一的 GOOGLE_SHEET_ID，一般用戶使用其個人試算表"""
    if _is_admin_context():
        return os.getenv("GOOGLE_SHEET_ID")
    return session.get('spreadsheet_id') or os.getenv("GOOGLE_SHEET_ID")

def get_wish_sheet_id():
    """願望分頁所在試算表 ID：管理者使用統一的 GOOGLE_SHEET_ID，一般用戶使用其個人試算表"""
    if _is_admin_context():
        return os.getenv("GOOGLE_SHEET_ID")
    return session.get('spreadsheet_id') or os.getenv("GOOGLE_SHEET_ID")

def get_pocket_sheet_id():
    """口袋名單分頁所在試算表 ID：管理者使用統一的 GOOGLE_SHEET_ID，一般用戶使用其個人試算表"""
    if _is_admin_context():
        return os.getenv("GOOGLE_SHEET_ID")
    return session.get('spreadsheet_id') or os.getenv("GOOGLE_SHEET_ID")

def get_health_sheet_id():
    """生理紀錄分頁所在試算表 ID：管理者使用統一的 GOOGLE_SHEET_ID，一般用戶使用其個人試算表"""
    if _is_admin_context():
        return os.getenv("GOOGLE_SHEET_ID")
    return session.get('spreadsheet_id') or os.getenv("GOOGLE_SHEET_ID")

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
    
    required_titles = ['記帳', '💰股票投資組合', '日記', '待辦', '願望', '口袋', '生理紀錄', 'AI_指令集', '生理症狀紀錄']
    has_all_gids = gids and all(
        (t in gids) or 
        (t == '口袋' and '口袋名單' in gids) or 
        (t == '願望' and '願望清單' in gids) 
        for t in required_titles
    )
    
    if (not has_all_gids) and spreadsheet_id:
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
        
        # 尋找對應的分頁 GID，若快取中不存在則主動重新向 Google 查詢以自癒快取
        if title not in gids:
            try:
                service = get_sheets_service()
                meta = service.spreadsheets().get(spreadsheetId=current_sheet_id).execute()
                for s in meta.get('sheets', []):
                    title_name = s.get('properties', {}).get('title')
                    sheet_gid = s.get('properties', {}).get('sheetId')
                    gids[title_name] = sheet_gid
                session['sheet_gids'] = gids
            except Exception as e:
                print(f"Force fetch GIDs failed for {title}: {e}")
                
        gid = gids.get(title)
        
        # 口袋名單別名雙向相容
        if gid is None and title == '口袋':
            gid = gids.get('口袋名單')
        elif gid is None and title == '口袋名單':
            gid = gids.get('口袋')
            
        # 願望清單別名雙向相容
        if gid is None and title == '願望':
            gid = gids.get('願望清單')
        elif gid is None and title == '願望清單':
            gid = gids.get('願望')

        if gid is not None:
            return f"https://docs.google.com/spreadsheets/d/{current_sheet_id}/edit#gid={gid}"
        return f"https://docs.google.com/spreadsheets/d/{current_sheet_id}/edit"
        
    # 所有分頁皆使用統一的 spreadsheet_id（管理者：GOOGLE_SHEET_ID；一般用戶：個人試算表）
    # 不再傳入舊的獨立 Sheet ID 作為 default_sheet_id，避免正式環境誤抓廢棄的雲端檔案
    return {
        "finance_sheet_url": get_url_with_gid('記帳'),
        "stock_sheet_url": get_url_with_gid('💰股票投資組合'),
        "diary_sheet_url": get_url_with_gid('日記'),
        "todo_sheet_url": get_url_with_gid('待辦'),
        "wish_sheet_url": get_url_with_gid('願望'),
        "pocket_sheet_url": get_url_with_gid('口袋'),
        "health_sheet_url": get_url_with_gid('生理紀錄'),
        "symptom_sheet_url": get_url_with_gid('生理症狀紀錄'),
        "training_sheet_url": get_url_with_gid('AI_指令集'),
        "bill_split_sheet_url": get_url_with_gid('代墊待收款')
    }
def bg_spreadsheet_self_healing(spreadsheet_id, user_email, creds):
    """
    背景執行主動式缺頁自癒與表頭保護鎖設定，不阻塞主登入執行緒。
    """
    try:
        if creds:
            sheets_service = build('sheets', 'v4', credentials=creds)
        else:
            sheets_service = build('sheets', 'v4')
        if not sheets_service:
            return
            
        sheet_meta = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        existing_titles = [s['properties']['title'] for s in sheet_meta.get('sheets', [])]
        
        # 1. 檢查是否存在「固定開銷」且不存在「固定支出」。若是，則自動重命名為「固定支出」。
        if '固定開銷' in existing_titles and '固定支出' not in existing_titles:
            print("[BG Self-Healing] Detected '固定開銷' tab, renaming to '固定支出'...")
            fixed_expenses_sheet_id = None
            for s in sheet_meta.get('sheets', []):
                if s['properties']['title'] == '固定開銷':
                    fixed_expenses_sheet_id = s['properties']['sheetId']
                    break
            if fixed_expenses_sheet_id is not None:
                try:
                    rename_request = {
                        'updateSheetProperties': {
                            'properties': {
                                'sheetId': fixed_expenses_sheet_id,
                                'title': '固定支出'
                            },
                            'fields': 'title'
                        }
                    }
                    sheets_service.spreadsheets().batchUpdate(
                        spreadsheetId=spreadsheet_id,
                        body={'requests': [rename_request]}
                    ).execute()
                    print("[BG Self-Healing] Renamed '固定開銷' to '固定支出' successfully!")
                    existing_titles = [t if t != '固定開銷' else '固定支出' for t in existing_titles]
                    for s in sheet_meta.get('sheets', []):
                        if s['properties']['title'] == '固定開銷':
                            s['properties']['title'] = '固定支出'
                except Exception as rename_err:
                    print(f"[BG Self-Healing] Error renaming '固定開銷' to '固定支出': {rename_err}")

        required_sheets = {
            '記帳': [['年度', '月份', '日期', '收入項目', '支出項目', '金額', '類別', '子分類']],
            '待辦': [['建立日期', '事項/內容', '分類', '狀態', '唯一 ID', '建立時間', '優先級']],
            '日記': [['日期', '內容', '天氣', '心情', '時間']],
            '願望': [['建立日期', '商品名稱', '預估價格', '備註/連結', '狀態', '分類', '實際價格', '唯一 ID', '儲存時間']],
            '生理紀錄': [['年度', '月份', '日期', '動作', '症狀/心情', '週期', '備註']],
            '口袋': [['ID', '分類', '店名', '地址', '地區', '備註', '建立時間', '緯度', '經度', '常用']],
            'AI_指令集': [['觸發語句', '執行動作']],
            '💰股票投資組合': [['交易日期', '股票代號', '股票名稱', '交易類型', '交易股數', '交易單價', '手續費', '即時市價', '即時損益', '備註']],
            '生理症狀紀錄': [['日期', '症狀', '備註', '寫入時間']],
            '固定支出': [['建立日期', '項目名稱', '類別設定', '子分類', '金額設定', '每月自動執行日', '最後執行月份', '唯一 ID', '開始日期', '結束日期']],
            '代墊待收款': [['建立日期', '帳目描述', '總金額', '墊款人', '分攤人(逗號分隔)', '各分攤明細(JSON/描述)', '狀態', '唯一 ID', '建立時間']],
            '資產帳戶': [['帳戶名稱', '帳戶類型', '當前餘額', '唯一 ID', '更新時間', '備註']],
            '會員卡包': [['卡片ID', '使用者ID', '商家名稱', '卡號', '條碼類型', '備註', '品牌顏色', '建立時間', '更新時間', '卡片分類']]
        }
        
        if '願望' in existing_titles or '願望清單' in existing_titles:
            if '願望' in required_sheets:
                del required_sheets['願望']
        
        if '口袋' in existing_titles or '口袋名單' in existing_titles:
            if '口袋' in required_sheets:
                del required_sheets['口袋']
                
        missing_sheets = [title for title in required_sheets.keys() if title not in existing_titles]
        
        if missing_sheets:
            print(f"[BG Self-Healing] Missing sheets detected: {missing_sheets}. Repairing...")
            add_requests = [{'addSheet': {'properties': {'title': title}}} for title in missing_sheets]
            sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': add_requests}
            ).execute()
            
            for title in missing_sheets:
                header_values = required_sheets[title]
                range_name = f"{title}!A1"
                sheets_service.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    valueInputOption='USER_ENTERED',
                    body={'values': header_values}
                ).execute()
                print(f"[BG Self-Healing] Successfully restored sheet '{title}' and headers!")
                
                if title == '資產帳戶':
                    from datetime import datetime
                    now_time = datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M:%S')
                    default_rows = [
                        ["國泰活儲", "活儲", "0", str(uuid.uuid4()), now_time, "預設帳戶"],
                        ["郵局活儲", "活儲", "0", str(uuid.uuid4()), now_time, "預設帳戶"],
                        ["玉山定存", "定存", "0", str(uuid.uuid4()), now_time, "預設帳戶"],
                        ["緊急備用金", "緊急備用金", "0", str(uuid.uuid4()), now_time, "預設帳戶"],
                        ["現金口袋", "現金", "0", str(uuid.uuid4()), now_time, "預設帳戶"],
                        ["證券交割戶", "證券", "0", str(uuid.uuid4()), now_time, "預設帳戶"]
                    ]
                    sheets_service.spreadsheets().values().append(
                        spreadsheetId=spreadsheet_id,
                        range='資產帳戶!A2:F',
                        valueInputOption='USER_ENTERED',
                        body={'values': default_rows}
                    ).execute()
                    print("[BG Self-Healing] Successfully populated default asset accounts!")
                    
            sheet_meta = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
            
        try:
            record_header_res = sheets_service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range='記帳!A1:H1'
            ).execute()
            header_vals = record_header_res.get('values', [[]])[0]
            if '子分類' not in header_vals:
                print("[BG Self-Healing] '子分類' header not found in '記帳' sheet, adding to H1...")
                sheets_service.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range='記帳!H1',
                    valueInputOption='USER_ENTERED',
                    body={'values': [['子分類']]}
                ).execute()
        except Exception as header_err:
            print(f"[BG Self-Healing] Error ensuring '子分類' header: {header_err}")
            
        protect_requests = []
        for s in sheet_meta.get('sheets', []):
            title = s['properties']['title']
            s_id = s['properties']['sheetId']
            has_protection = any(
                p.get('range', {}).get('startRowIndex') == 0 and p.get('range', {}).get('endRowIndex') == 1
                for p in s.get('protectedRanges', [])
            )
            if not has_protection:
                col_count = 10
                if title in required_sheets:
                    col_count = len(required_sheets[title][0])
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
        if protect_requests:
            try:
                sheets_service.spreadsheets().batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={'requests': protect_requests}
                ).execute()
                print(f"[BG Self-Healing] Added protection locks to {len(protect_requests)} sheets.")
            except Exception as protect_err:
                print(f"[BG Self-Healing] Error adding protection locks: {protect_err}")
        print(f"[BG Self-Healing] Completed successfully for {user_email}")
    except Exception as ex:
        print(f"[BG Self-Healing] Error in sheet self-healing bg thread: {ex}")

def ensure_user_spreadsheet():
    """
    檢查使用者雲端硬碟是否有 AI_Personal_Secretary_Data。
    若無則自動在使用者個人雲端硬碟建立一組全新的資料表並初始化所有欄位。
    """
    spreadsheet_id = None
    
    # 1. 優先嘗試從 session 獲取
    if 'spreadsheet_id' in session:
        spreadsheet_id = session['spreadsheet_id']
    else:
        # 2. 如果是創作者本人的 Email 登入，直接回傳最原始的歷史資料表，避免新建空白表！
        try:
            email = session.get('user_email')
            if not email:
                user_info = get_user_info()
                if user_info:
                    email = user_info.get('email')
            
            # Developer emails
            developer_emails = {'ulir976272866@gmail.com', 'mina.chen.xstar.sg@gmail.com'}
            owner_email = os.getenv("GOOGLE_CALENDAR_ID")
            if owner_email:
                developer_emails.add(owner_email.lower())
                
            if email and email.lower() in developer_emails:
                spreadsheet_id = os.getenv("GOOGLE_SHEET_ID")
                session['spreadsheet_id'] = spreadsheet_id
                print(f"Owner/Developer ({email}) logged in. Reusing existing original spreadsheet: {spreadsheet_id}")
        except Exception as e:
            print(f"Error checking owner email in ensure_user_spreadsheet: {e}")

    # 3. 如果非創作者且尚未找到，則透過 Google Drive 尋找
    if not spreadsheet_id:
        creds = get_valid_credentials()
        if not creds:
            spreadsheet_id = os.getenv("GOOGLE_SHEET_ID")
            session['spreadsheet_id'] = spreadsheet_id
        else:
            try:
                drive_service = get_drive_service()
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
            except Exception as e:
                print(f"Error checking user drive for spreadsheet: {e}")
                spreadsheet_id = os.getenv("GOOGLE_SHEET_ID")
                session['spreadsheet_id'] = spreadsheet_id

    # 4. 🛡️ 若已有 resolved 的 spreadsheet_id，非同步背景執行缺頁與表頭自癒
    if spreadsheet_id:
        if not session.get('self_healing_done'):
            try:
                creds = get_valid_credentials()
                import threading
                threading.Thread(
                    target=bg_spreadsheet_self_healing,
                    args=(spreadsheet_id, session.get('user_email'), creds)
                ).start()
                session['self_healing_done'] = True
                session.modified = True
            except Exception as bg_err:
                print(f"Error starting background sheet self-healing: {bg_err}")
        return spreadsheet_id

    # 5. 若仍無 spreadsheet_id，則代表需要新建並初始化一個全新試算表
    try:
        sheets_service = get_sheets_service()
        spreadsheet_name = "AI_Personal_Secretary_Data"
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
            '記帳!A1:H1': [['年度', '月份', '日期', '收入項目', '支出項目', '金額', '類別', '子分類']],
            '待辦!A1:F1': [['唯一 ID', '事項/內容', '優先級', '分類', '狀態', '建立時間']],
            '日記!A1:E1': [['日期', '內容', '天氣', '心情', '時間']],
            '願望!A1:F1': [['唯一 ID', '願望名稱', '預算', '狀態', '實際花費', '建立時間']],
            '生理紀錄!A1:G1': [['年度', '月份', '日期', '動作', '症狀/心情', '週期', '備註']],
            '口袋!A1:J1': [['ID', '分類', '店名', '地址', '地區', '備註', '建立時間', '緯度', '經度', '常用']],
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
            col_count = 8
            if title == '待辦': col_count = 7
            elif title == '日記': col_count = 5
            elif title == '願望': col_count = 9
            elif title == '口袋': col_count = 10
            elif title == 'AI_指令集': col_count = 2
            elif title == '固定支出': col_count = 10
            elif title == '代墊待收款': col_count = 9
            elif title == '💰股票投資組合': col_count = 10
            elif title == '資產帳戶': col_count = 6
            elif title == '會員卡包': col_count = 10
            
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

def self_heal_missing_sheet_values(range_name, spreadsheet_id, service, original_err):
    # 取得工作表名稱
    sheet_title = range_name.split('!')[0] if '!' in range_name else range_name
    
    # 核心通用自癒對照表
    standard_headers_map = {
        '生理紀錄': ['年度', '月份', '日期', '動作', '症狀/心情', '週期', '備註'],
        '記帳': ['年度', '月份', '日期', '收入項目', '支出項目', '金額', '類別', '子分類'],
        '待辦': ['建立日期', '事項/內容', '分類', '狀態', '唯一 ID', '建立時間', '優先級'],
        '日記': ['日期', '內容', '天氣', '心情', '時間'],
        '願望': ['建立日期', '商品名稱', '預估價格', '備註/連結', '狀態', '分類', '實際價格', '唯一 ID', '儲存時間'],
        '願望清單': ['建立日期', '商品名稱', '預估價格', '備註/連結', '狀態', '分類', '實際價格', '唯一 ID', '儲存時間'],
        '口袋': ['ID', '分類', '店名', '地址', '地區', '備註', '建立時間', '緯度', '經度', '常用'],
        '口袋名單': ['ID', '類別', '名稱', '地點', '地點區域', '備註', '建立時間', '緯度', '經度', '常用'],
        'AI_指令集': ['觸發語句', '執行動作'],
        '💰股票投資組合': ['交易日期', '股票代號', '股票名稱', '交易類型', '交易股數', '交易單價', '手續費', '即時市價', '即時損益', '備註'],
        '生理症狀紀錄': ['日期', '症狀', '備註', '寫入時間']
    }
    
    err_msg = str(original_err)
    is_range_error = "400" in err_msg or "Unable to parse range" in err_msg or "not found" in err_msg.lower()
    
    if is_range_error and sheet_title in standard_headers_map:
        print(f"[Real-Time Self-Healing] 檢測到核心分頁 '{sheet_title}' 不存在或被誤刪！正在為您即時建立並寫入表頭...")
        try:
            # 1. 建立分頁
            body = {
                'requests': [{
                    'addSheet': {
                        'properties': {
                            'title': sheet_title
                        }
                    }
                }]
            }
            service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()
            
            # 2. 寫入標準表頭
            headers = standard_headers_map[sheet_title]
            col_letter = chr(ord('A') + len(headers) - 1)
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"{sheet_title}!A1:{col_letter}1",
                valueInputOption='USER_ENTERED',
                body={'values': [headers]}
            ).execute()
            
            # 3. 立即重試讀取並傳回數據
            result = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=range_name
            ).execute()
            
            # 4. 清除 Session 中的 GIDs 快取，促使重新生成最新 GID (V11.2)
            try:
                from flask import session as flask_session
                if flask_session:
                    flask_session.pop('sheet_gids', None)
                    flask_session.modified = True
                    print(f"[Real-Time Self-Healing] 核心分頁 '{sheet_title}' 重建成功，已成功清除 GID 快取以實時同步！")
            except Exception as session_err:
                print(f"[Real-Time Self-Healing GID Cache Warning] 清除 session 快取失敗: {session_err}")

            return result.get('values', [])
        except Exception as heal_err:
            print(f"[Real-Time Self-Healing Error] 重建分頁 '{sheet_title}' 失敗: {heal_err}")
            raise original_err
    else:
        raise original_err

def get_sheet_values(range_name, spreadsheet_id=None):
    if not spreadsheet_id:
        spreadsheet_id = get_spreadsheet_id()
    service = get_sheets_service()
    
    # 智慧地自動匹配「願望清單」與「願望」分頁名，以及「口袋名單」與「口袋」分頁名以防讀取報錯
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
                return self_heal_missing_sheet_values(range_name, spreadsheet_id, service, e)
        elif '願望' in range_name:
            new_range = range_name.replace('願望', '願望清單')
            try:
                result = service.spreadsheets().values().get(
                    spreadsheetId=spreadsheet_id,
                    range=new_range
                ).execute()
                range_name = new_range
            except Exception:
                return self_heal_missing_sheet_values(range_name, spreadsheet_id, service, e)
        elif '口袋名單' in range_name:
            new_range = range_name.replace('口袋名單', '口袋')
            try:
                result = service.spreadsheets().values().get(
                    spreadsheetId=spreadsheet_id,
                    range=new_range
                ).execute()
                range_name = new_range
            except Exception:
                return self_heal_missing_sheet_values(range_name, spreadsheet_id, service, e)
        elif '口袋' in range_name:
            new_range = range_name.replace('口袋', '口袋名單')
            try:
                result = service.spreadsheets().values().get(
                    spreadsheetId=spreadsheet_id,
                    range=new_range
                ).execute()
                range_name = new_range
            except Exception:
                return self_heal_missing_sheet_values(range_name, spreadsheet_id, service, e)
        else:
            return self_heal_missing_sheet_values(range_name, spreadsheet_id, service, e)
            
    values = result.get('values', [])
    
    # 🛡️ 全局主動式表頭自癒安全護盾 (Proactive Header Self-Healing Shield)
    try:
        if values and len(values) > 0:
            sheet_title = range_name.split('!')[0] if '!' in range_name else range_name
            
            standard_headers_map = {
                '生理紀錄': ['年度', '月份', '日期', '動作', '症狀/心情', '週期', '備註'],
                '記帳': ['年度', '月份', '日期', '收入項目', '支出項目', '金額', '類別', '子分類'],
                '待辦': ['建立日期', '事項/內容', '分類', '狀態', '唯一 ID', '建立時間', '優先級'],
                '日記': ['日期', '內容', '天氣', '心情', '時間'],
                '願望': ['建立日期', '商品名稱', '預估價格', '備註/連結', '狀態', '分類', '實際價格', '唯一 ID', '儲存時間'],
                '願望清單': ['建立日期', '商品名稱', '預估價格', '備註/連結', '狀態', '分類', '實際價格', '唯一 ID', '儲存時間'],
                '口袋': ['ID', '分類', '店名', '地址', '地區', '備註', '建立時間', '緯度', '經度', '常用'],
                '口袋名單': ['ID', '類別', '名稱', '地點', '地點區域', '備註', '建立時間', '緯度', '經度', '常用'],
                'AI_指令集': ['觸發語句', '執行動作'],
                '💰股票投資組合': ['交易日期', '股票代號', '股票名稱', '交易類型', '交易股數', '交易單價', '手續費', '即時市價', '即時損益', '備註'],
                '生理症狀紀錄': ['日期', '症狀', '備註', '寫入時間']
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

# 收入母子分類硬編碼對照表
INCOME_SUB_CATEGORIES = {
    "薪資": ["正職薪水", "兼職時薪", "小費進帳"],
    "獎金": ["年終獎金", "績效/三節", "專案分紅"],
    "投資獲利": ["股票股利/價差", "基金配息", "定存利息", "加密貨幣"],
    "副業收入": ["諮詢服務", "個人項目", "團購/分潤", "諮詢隨喜/小費"],
    "變更/退款": ["購物退款", "代墊款收回", "其他雜項"]
}

# 記帳分類與 Emoji 映射對照表 (確保雲端與本地端都有超高顏值 Emoji 符號)
CATEGORY_EMOJI_MAP = {
    # 支出分類
    "食": "🍔", "衣": "👔", "住": "🏠", "行": "🚗", "育": "📚", "樂": "🎬", "醫": "🏥", "保險費": "🛡️", "貸款": "🏦", "儲蓄/投資": "💰", "宗教/公益": "💖", "未分類": "❓",
    # 收入分類
    "薪資": "💼", "獎金": "🧧", "投資獲利": "💹", "副業收入": "🔮", "變更/退款": "↩️"
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
        lifetime_expense = 0
        lifetime_income = 0
        category_totals = {}
        
        for row in rows[1:]:
            if len(row) >= 6:
                try:
                    amt = float(str(row[5]).replace(',', ''))
                    is_income = len(row) > 3 and row[3].strip() != ""
                    
                    # 累計所有歷史收支
                    if is_income:
                        lifetime_income += amt
                    else:
                        lifetime_expense += amt
                    
                    # 累計當月收支
                    r_year = str(row[0]).replace("'", "")
                    r_month = str(row[1]).replace("'", "").zfill(2)
                    if r_year == cur_year and r_month == cur_month:
                        if is_income:
                            monthly_income += amt
                        else:
                            monthly_expense += amt
                            cat = row[6] if len(row) > 6 else "未分類"
                            category_totals[cat] = category_totals.get(cat, 0) + amt
                except:
                    pass
        
        lifetime_balance = lifetime_income - lifetime_expense
        
        cat_report = ""
        # 按金額排序
        sorted_cats = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
        for cat, total in sorted_cats:
            percentage = (total / monthly_expense * 100) if monthly_expense > 0 else 0
            cat_report += f"🔹 {cat}: ${int(total):,} ({percentage:.1f}%)\n"
            
        summary = f"💸 本月支出：${int(monthly_expense):,}\n"
        summary += f"⚖️ 剩餘結餘 (歷史累計)：${int(lifetime_balance):,}\n"
            
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

@app.route('/sw.js')
def serve_sw():
    response = make_response(send_from_directory('static/js', 'sw.js'))
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Service-Worker-Allowed'] = '/'
    return response

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
            allow_payment=is_payment_allowed(),
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
            
            # 🚀 確保 session 中最新的會員規格與試用期狀態隨時與資料庫同步！
            user_email = session.get('user_email') or (user_info.get('email') if user_info else None)
            if user_email:
                session['user_email'] = user_email
                user = get_user_by_email(user_email)
                if user:
                    session['is_subscribed'] = bool(user.get('is_subscribed'))
                    session['subscription_type'] = user.get('subscription_type', 'NONE')
                    session['ai_points'] = user.get('ai_points', 0)
                    session['has_stock_record'] = bool(user.get('has_stock_record'))
                    
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
                            session['trial_expires_at'] = expires_at.strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            session['is_trial_active'] = False
                            session['trial_expires_at'] = None
                    else:
                        session['is_trial_active'] = False
                        session['trial_expires_at'] = None

                    # 注入訂閱過期時間
                    if user.get('subscription_expires_at'):
                        from datetime import datetime
                        sub_expires_at = user.get('subscription_expires_at')
                        if isinstance(sub_expires_at, str):
                            try:
                                sub_expires_at = datetime.strptime(sub_expires_at, "%Y-%m-%d %H:%M:%S")
                            except ValueError:
                                pass
                        if sub_expires_at:
                            session['subscription_expires_at'] = sub_expires_at.strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            session['subscription_expires_at'] = None
                    else:
                        session['subscription_expires_at'] = None

                    if user.get('google_spreadsheet_id'):
                        session['spreadsheet_id'] = user.get('google_spreadsheet_id')
            
            # 印出目前 session 用於除錯
            print("[DEBUG INDEX SESSION] Current session keys and values:")
            for k, v in dict(session).items():
                if k != 'credentials': # 避免印出敏感 token
                    print(f"  {k}: {v}")
            
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
        allow_payment=is_payment_allowed(),
        **urls
    )

@app.route('/login')
def login():
    # 請求 offline 權限以取得 refresh_token，並強制要求 consent 彈窗確認
    flow = get_flow()
    print(f"[DEBUG LOGIN] generated redirect_uri: {flow.redirect_uri}")
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    session['state'] = state
    # 將 PKCE code_verifier 存入 session，以便在 callback 路由中跨請求還原驗證
    session['code_verifier'] = flow.code_verifier
    print(f"[DEBUG LOGIN] authorization_url: {authorization_url}")
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
    # 將 OAuth 金鑰資料保存至 Session 中（含 expiry，讓 creds.expired 能正確判斷）
    creds = flow.credentials
    session['credentials'] = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': creds.scopes,
        'expiry': creds.expiry.isoformat() if creds.expiry else None
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
                            "INSERT INTO users (user_id, email, is_subscribed, subscription_type, ai_points, trial_used, trial_expires_at, has_stock_record, subscription_expires_at) VALUES (%s, %s, TRUE, 'YEARLY_AI', 100, TRUE, %s, TRUE, NULL);",
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
                        session['trial_expires_at'] = expires_at.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        session['is_trial_active'] = False
                        session['trial_expires_at'] = None
                else:
                    session['is_trial_active'] = False
                    session['trial_expires_at'] = None

                # 注入訂閱過期時間
                if user.get('subscription_expires_at'):
                    from datetime import datetime
                    sub_expires_at = user.get('subscription_expires_at')
                    if isinstance(sub_expires_at, str):
                        try:
                            sub_expires_at = datetime.strptime(sub_expires_at, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            pass
                    if sub_expires_at:
                        session['subscription_expires_at'] = sub_expires_at.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        session['subscription_expires_at'] = None
                else:
                    session['subscription_expires_at'] = None

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

    # 映射到真實的沙盒信箱與會員特權
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
            'subscription_type': 'PREMIUM_MONTHLY',
            'ai_points': 1000,
            'has_stock_record': True
        },
        'YEARLY': {
            'email': 'yearly.premium@gmail.com',
            'is_subscribed': True,
            'subscription_type': 'YEARLY_AI',
            'ai_points': 1000,
            'has_stock_record': True
        },
        'TRIAL': {
            'email': 'trial.chen.xstar.sg@gmail.com',
            'is_subscribed': True,
            'subscription_type': 'YEARLY_AI',
            'ai_points': 650,
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
        elif role in ['PREMIUM_MONTHLY', 'PREMIUM']:
            target = role_mapping['PREMIUM']
        elif role in ['YEARLY_AI', 'YEARLY']:
            target = role_mapping['YEARLY']
        elif role == 'TRIAL':
            target = role_mapping['TRIAL']
        else:
            return jsonify({"status": "error", "message": "無效的角色參數"}), 400
            
    # 如果傳入了自訂的信箱，覆蓋預設的沙盒信箱，並進行自動註冊
    user_email = email if email else target['email']
    
    # 檢查該自訂信箱在 TiDB 中是否存在，若不存在且非單人模式則進行自動註冊與狀態覆寫，確保測試順利
    if os.getenv("SINGLE_USER_MODE", "false").lower() != "true":
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # 確保自癒新增 subscription_expires_at 欄位
                try:
                    cursor.execute("ALTER TABLE users ADD COLUMN subscription_expires_at TIMESTAMP NULL DEFAULT NULL;")
                    conn.commit()
                except Exception:
                    pass

                cursor.execute("SELECT * FROM users WHERE email = %s;", (user_email,))
                user_exists = cursor.fetchone()
                
                is_sub = target['is_subscribed']
                sub_type = target['subscription_type']
                points = target['ai_points']
                
                from datetime import datetime, timedelta
                now = datetime.now()
                if role == 'TRIAL':
                    sub_expires = None
                    trial_expiry = now + timedelta(days=7)
                else:
                    if sub_type in ['MONTHLY_AI', 'PREMIUM_MONTHLY']:
                        sub_expires = now + timedelta(days=30) # 精準 30 天
                    elif sub_type == 'YEARLY_AI':
                        sub_expires = now + timedelta(days=365)
                    else:
                        sub_expires = None

                    # 支援自訂天數參數，以利測試即將到期之警告狀態
                    days_arg = request.args.get('days') or (request.json.get('days') if request.json else None)
                    if days_arg and is_sub:
                        try:
                            sub_expires = now + timedelta(days=int(days_arg))
                        except ValueError:
                            pass

                    # 若是測試訂閱身分，試用設為已結束/過期，確保呈現訂閱版計時器
                    trial_expiry = now - timedelta(days=1) if is_sub else now + timedelta(days=7)

                if not user_exists:
                    new_uid = f"uid_{uuid.uuid4().hex[:12]}"
                    cursor.execute(
                        "INSERT INTO users (user_id, email, is_subscribed, subscription_type, ai_points, trial_used, trial_expires_at, has_stock_record, subscription_expires_at) VALUES (%s, %s, %s, %s, %s, TRUE, %s, TRUE, %s);",
                        (new_uid, user_email, is_sub, sub_type, points, trial_expiry, sub_expires)
                    )
                    conn.commit()
                    print(f"Successfully registered custom test user via switch_role: {user_email}")
                else:
                    # 覆寫已有帳號的權限與到期日，以利完整測試不同 UI
                    cursor.execute(
                        "UPDATE users SET is_subscribed = %s, subscription_type = %s, ai_points = %s, trial_expires_at = %s, subscription_expires_at = %s WHERE email = %s;",
                        (is_sub, sub_type, points, trial_expiry, sub_expires, user_email)
                    )
                    conn.commit()
                    print(f"Successfully updated custom test user state via switch_role: {user_email}")
        except Exception as ex:
            print(f"Failed to manage test user state via switch_role: {ex}")
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
                session['trial_expires_at'] = expires_at.strftime("%Y-%m-%d %H:%M:%S")
            else:
                session['is_trial_active'] = False
                session['trial_expires_at'] = None
        else:
            session['is_trial_active'] = False
            session['trial_expires_at'] = None

        # 注入訂閱過期時間
        if user.get('subscription_expires_at'):
            from datetime import datetime
            sub_expires_at = user.get('subscription_expires_at')
            if isinstance(sub_expires_at, str):
                try:
                    sub_expires_at = datetime.strptime(sub_expires_at, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass
            if sub_expires_at:
                session['subscription_expires_at'] = sub_expires_at.strftime("%Y-%m-%d %H:%M:%S")
            else:
                session['subscription_expires_at'] = None
        else:
            session['subscription_expires_at'] = None

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


@app.route('/api/subscription/upgrade_preview', methods=['GET'])
def upgrade_preview():
    """計算基礎版中途補差價直升旗艦版所需之天數折算、折抵金額與應付金額"""
    email = session.get('user_email')
    if not email:
        return jsonify({"status": "error", "message": "尚未登入"}), 401
    
    user = get_user_by_email(email)
    if not user:
        return jsonify({"status": "error", "message": "找不到該用戶"}), 404
        
    sub_type = user.get('subscription_type', 'NONE')
    if sub_type != 'MONTHLY_AI':
        return jsonify({
            "status": "error", 
            "message": "只有基礎版訂閱用戶才可以補差價直升旗艦版喔！"
        }), 400
        
    sub_exp = user.get('subscription_expires_at')
    if not sub_exp:
        return jsonify({"status": "error", "message": "無效的訂閱到期日"}), 400
        
    from datetime import datetime
    if isinstance(sub_exp, str):
        try:
            sub_exp = datetime.strptime(sub_exp, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
            
    now = datetime.now()
    diff_days = 0
    if sub_exp > now:
        diff_days = (sub_exp - now).days + 1
        
    # 剩餘天數日均價值： 119 元 / 30 天 = 3.9667
    discount = round(diff_days * (119.0 / 30.0))
    # 應付差額 = max(100, 1990 - discount)
    price = max(100, 1990 - discount)
    
    return jsonify({
        "status": "success",
        "remaining_days": diff_days,
        "discount": discount,
        "upgrade_price": price
    })


@app.route('/mock/checkout', methods=['GET'])
def mock_checkout():
    if not is_payment_allowed():
        return "<h3>系統當前已關閉儲值與訂閱交易功能。造成您的不便，敬請見諒！</h3>", 403

    tier = request.args.get('tier', 'BASIC')
    email = request.args.get('email', '')
    
    # 防呆：若沒傳入 email，自動取 session 登入之信箱
    if not email:
        email = session.get('user_email', '')
        
    price = 119
    product_name = "基礎版"
    product_desc = "全面解鎖行程、備忘錄與經期看板，並獲得 500 點 AI 額度！"
    
    if tier == 'PREMIUM_MONTHLY':
        price = 199
        product_name = "旗艦版"
        product_desc = "解鎖「智慧存股損益」、尊榮一鍵 AI 健檢與 650 點 AI 額度！"
    elif tier == 'PREMIUM':
        price = 1990
        product_name = "尊榮版"
        product_desc = "解鎖全部功能！包含「智慧存股損益」、AI 一鍵健檢與 650 點 AI 額度！採年繳計費超划算！"
    elif tier == 'PREMIUM_UPGRADE':
        # 進行伺服器端補差價計算
        from datetime import datetime
        user = get_user_by_email(email)
        sub_exp = user.get('subscription_expires_at') if user else None
        
        if sub_exp:
            if isinstance(sub_exp, str):
                try: sub_exp = datetime.strptime(sub_exp, "%Y-%m-%d %H:%M:%S")
                except ValueError: pass
                
            now = datetime.now()
            diff_days = 0
            if sub_exp > now:
                diff_days = (sub_exp - now).days + 1
            
            discount = round(diff_days * (119.0 / 30.0))
            price = max(100, 1990 - discount)
        else:
            price = 1990
            
        product_name = "直升尊榮版"
        product_desc = "折抵您基礎方案未用完天數價值，今日補差價直升尊榮版，即刻享有全功能並加贈 650 點 AI 額度！"
    elif tier == 'POINTS_300':
        price = 70
        product_name = "AI 智慧點數 300 點加購"
        product_desc = "為您的生活與秘書助理充值 300 點 AI 智慧對話額度，永不過期！"
    elif tier == 'POINTS_600':
        price = 120
        product_name = "AI 智慧點數 600 點加購"
        product_desc = "為您的生活與秘書助理充值 600 點 AI 智慧對話額度，極致劃算，永不過期！"
        
    is_recurring = request.args.get('recurring', '0') == '1'
        
    return render_template(
        'checkout.html',
        tier=tier,
        email=email,
        price=price,
        product_name=product_name,
        product_desc=product_desc,
        is_recurring=is_recurring
    )


@app.route('/api/mock/payment/process', methods=['POST'])
def api_mock_payment_process():
    data = request.json or {}
    email = data.get('email', '')
    tier = data.get('tier', 'BASIC')
    payment_status = data.get('payment_status', '')
    
    if not email:
        return jsonify({"status": "error", "message": "缺少用戶信箱"}), 400
        
    if payment_status != 'success':
        return jsonify({"status": "error", "message": "付款未完成"}), 400
        
    try:
        conn = get_db_connection()
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            # 獲取當前用戶狀態
            cursor.execute("SELECT * FROM users WHERE email = %s;", (email,))
            user = cursor.fetchone()
            if not user:
                return jsonify({"status": "error", "message": "找不到該用戶"}), 404
                
            current_points = user.get('ai_points', 0)
            current_sub_type = user.get('subscription_type', 'NONE')
            
            from datetime import datetime, timedelta
            now = datetime.now()
            
            # 根據購買的商品做處理
            if tier == 'BASIC':
                is_sub = 1
                sub_type = 'MONTHLY_AI'
                new_points = current_points + 500
                sub_expires = now + timedelta(days=30)
                
                cursor.execute(
                    "UPDATE users SET is_subscribed = %s, subscription_type = %s, ai_points = %s, subscription_expires_at = %s WHERE email = %s;",
                    (is_sub, sub_type, new_points, sub_expires, email)
                )
            elif tier == 'PREMIUM_MONTHLY':
                is_sub = 1
                sub_type = 'PREMIUM_MONTHLY'
                new_points = current_points + 650
                sub_expires = now + timedelta(days=30)
                
                cursor.execute(
                    "UPDATE users SET is_subscribed = %s, subscription_type = %s, ai_points = %s, subscription_expires_at = %s WHERE email = %s;",
                    (is_sub, sub_type, new_points, sub_expires, email)
                )
            elif tier in ['PREMIUM', 'PREMIUM_UPGRADE']:
                is_sub = 1
                sub_type = 'YEARLY_AI'
                new_points = current_points + 650
                sub_expires = now + timedelta(days=365)
                
                cursor.execute(
                    "UPDATE users SET is_subscribed = %s, subscription_type = %s, ai_points = %s, subscription_expires_at = %s WHERE email = %s;",
                    (is_sub, sub_type, new_points, sub_expires, email)
                )
            elif tier == 'POINTS_300':
                new_points = current_points + 300
                cursor.execute(
                    "UPDATE users SET ai_points = %s WHERE email = %s;",
                    (new_points, email)
                )
                is_sub = user.get('is_subscribed', 0)
                sub_type = current_sub_type
                sub_expires = user.get('subscription_expires_at')
            elif tier == 'POINTS_600':
                new_points = current_points + 600
                cursor.execute(
                    "UPDATE users SET ai_points = %s WHERE email = %s;",
                    (new_points, email)
                )
                is_sub = user.get('is_subscribed', 0)
                sub_type = current_sub_type
                sub_expires = user.get('subscription_expires_at')
            else:
                return jsonify({"status": "error", "message": "不支援的購買方案"}), 400
                
            conn.commit()
            
            # 更新 session，確保回到首頁立即生效！
            if session.get('user_email') == email:
                session['is_subscribed'] = bool(is_sub)
                session['subscription_type'] = sub_type
                session['ai_points'] = new_points
                if sub_expires:
                    if isinstance(sub_expires, str):
                        session['subscription_expires_at'] = sub_expires
                    else:
                        session['subscription_expires_at'] = sub_expires.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    session['subscription_expires_at'] = None
                    
            print(f"[Gold Payment Success] 用戶 {email} 購買 {tier} 成功！AI點數增至 {new_points}，訂閱期更新。")
            return jsonify({"status": "success", "message": "付款處理成功！"})
            
    except Exception as e:
        print(f"[Gold Payment Error] 處理付款失敗: {e}")
        return jsonify({"status": "error", "message": f"資料庫處理異常: {str(e)}"}), 500
    finally:
        if 'conn' in locals() and conn:
            conn.close()


@app.route('/api/admin/refund', methods=['POST'])
def api_admin_refund():
    """
    [Admin] 退款與特權回收機制
    自動依使用天數計算比例退款，並扣除「原價的 5% 金流交易手續費」後得出實際應退款金額。
    接受參數: { email, tier }
    """
    # 限制只有開發者本人信箱可呼叫退費 API
    current_user_email = session.get('user_email', '')
    if current_user_email != 'ulir976272866@gmail.com':
        return jsonify({"status": "error", "message": "無此操作權限！"}), 403

    data = request.json or {}
    email = data.get('email', '').strip()
    tier = data.get('tier', 'BASIC').strip()  # BASIC, PREMIUM_MONTHLY, PREMIUM, POINTS_300, POINTS_600

    if not email:
        return jsonify({"status": "error", "message": "缺少用戶信箱"}), 400

    # 取得不同方案的原價與對應天數
    tier_prices = {
        'BASIC': (119, 30),
        'PREMIUM_MONTHLY': (199, 30),
        'PREMIUM': (1990, 365),
        'POINTS_300': (70, 0),
        'POINTS_600': (120, 0)
    }

    if tier not in tier_prices:
        return jsonify({"status": "error", "message": "不支援的退款方案"}), 400

    original_price, total_days = tier_prices[tier]

    try:
        conn = get_db_connection()
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT * FROM users WHERE email = %s;", (email,))
            user = cursor.fetchone()
            if not user:
                return jsonify({"status": "error", "message": "找不到該用戶"}), 404

            current_points = user.get('ai_points', 0)
            
            # 計算退款金額
            calculated_refund = 0
            processing_fee = round(original_price * 0.05)  # 5% 金流手續費

            if total_days > 0:
                # 訂閱類別：按天數比例退費
                sub_expires = user.get('subscription_expires_at')
                from datetime import datetime, timedelta
                if sub_expires:
                    if isinstance(sub_expires, str):
                        try: sub_expires = datetime.strptime(sub_expires, "%Y-%m-%d %H:%M:%S")
                        except ValueError: pass
                    
                    now = datetime.now()
                    # 統一為 naive datetime 進行比較
                    if sub_expires.tzinfo is not None:
                        sub_expires_naive = sub_expires.replace(tzinfo=None)
                    else:
                        sub_expires_naive = sub_expires
                        
                    now_naive = now.replace(tzinfo=None)
                    
                    # 計算購買時間
                    purchase_date = sub_expires_naive - timedelta(days=total_days)
                    days_since_purchase = (now_naive - purchase_date).days
                    
                    if sub_expires_naive > now_naive:
                        if days_since_purchase <= 7:
                            # 7日無條件退費 (扣除 5% 手續費)
                            calculated_refund = max(0, original_price - processing_fee)
                            print(f"[Admin Refund Calc] {email} {tier}: 於購買 7 日內申請無條件退款, 原價 NT${original_price}, 手續費 NT${processing_fee}, 實際退還 NT${calculated_refund}")
                        else:
                            # 超過 7 日，依政策不予退費
                            return jsonify({"status": "error", "message": "該用戶方案已購買超過 7 日，不符合退費資格。"}), 400
                    else:
                        return jsonify({"status": "error", "message": "該用戶方案已過期，無法退費"}), 400
                else:
                    return jsonify({"status": "error", "message": "找不到該用戶的訂閱到期時間，無法計算比例"}), 400
            else:
                # 點數購買退款（若點數沒用，則扣除 5% 手續費後全退，否則不予退費）
                points_volume = 300 if tier == 'POINTS_300' else 600
                if current_points >= points_volume:
                    calculated_refund = max(0, original_price - processing_fee)
                else:
                    return jsonify({"status": "error", "message": "用戶點數已部分使用，無法進行點數加購退費"}), 400

            # 1. 回收訂閱特權或扣回點數
            if tier in ['BASIC', 'PREMIUM_MONTHLY', 'PREMIUM']:
                points_to_deduct = 500 if tier == 'BASIC' else 650
                new_points = max(0, current_points - points_to_deduct)
                cursor.execute(
                    "UPDATE users SET is_subscribed = 0, subscription_type = 'NONE', subscription_expires_at = NULL, ai_points = %s WHERE email = %s;",
                    (new_points, email)
                )
            elif tier == 'POINTS_300':
                new_points = max(0, current_points - 300)
                cursor.execute("UPDATE users SET ai_points = %s WHERE email = %s;", (new_points, email))
            elif tier == 'POINTS_600':
                new_points = max(0, current_points - 600)
                cursor.execute("UPDATE users SET ai_points = %s WHERE email = %s;", (new_points, email))

            conn.commit()

            # 2. 如果退款用戶剛好是當前登入者，同步重設 session
            if session.get('user_email') == email:
                session['is_subscribed'] = False
                session['subscription_type'] = 'NONE'
                session['subscription_expires_at'] = None
                session['ai_points'] = new_points

            print(f"[Admin Refund Success] 用戶 {email} 方案 {tier} 已退款。扣除後AI點數: {new_points}，實際應退款金額: NT${calculated_refund}")
            return jsonify({
                "status": "success", 
                "message": f"退款權限回收完成！已回收 AI 額度並取消方案。本次「退款金額」(已扣除 5% 手續費 NT${processing_fee}) 計算結果為：NT$ {calculated_refund} 元。請手動至統一金流後台執行此金額退款。"
            })

    except Exception as e:
        print(f"[Admin Refund Error] 退款處理失敗: {e}")
        return jsonify({"status": "error", "message": f"退款處理失敗: {str(e)}"}), 500
    finally:
        if 'conn' in locals() and conn:
            conn.close()

@app.route('/api/user/agree_refund_policy', methods=['POST'])
def api_user_agree_refund_policy():
    """
    [User] 記錄使用者同意合理退款政策之時間戳記
    ---
    Response: { status, message }
    """
    email = session.get('user_email')
    if not email:
        return jsonify({"status": "error", "message": "尚未登入，無法記錄"}), 401

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            from datetime import datetime
            now_time = datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(
                "UPDATE users SET refund_policy_agreed_at = %s WHERE email = %s;",
                (now_time, email)
            )
            conn.commit()
            print(f"[Refund Policy Policy] 用戶 {email} 於 {now_time} 點選確認並同意合理退費政策與服務條款。")
            return jsonify({"status": "success", "message": "已成功記錄同意時間。"})
    except Exception as e:
        print(f"[Refund Policy Error] 記錄用戶同意時間失敗: {e}")
        return jsonify({"status": "error", "message": f"伺服器記錄失敗: {str(e)}"}), 500
    finally:
        if 'conn' in locals() and conn:
            conn.close()


# ============================================================
# 🏦 綠界科技（ECPay）金流串接路由 (測試環境)
# ============================================================

def _ecpay_get_price_for_tier(tier: str, email: str) -> tuple:
    """依 tier 回傳 (price, product_name, trade_desc)，供 /ecpay/checkout 使用"""
    if tier == 'PREMIUM':
        return 1990, "尊榮版", "UniTask 尊榮版訂閱 - 解鎖全功能與 650 點 AI 額度"
    elif tier == 'PREMIUM_MONTHLY':
        return 199, "旗艦版", "UniTask 旗艦版月費訂閱 - 解鎖智慧存股與 650 點 AI 額度"
    elif tier == 'PREMIUM_UPGRADE':
        user = get_user_by_email(email)
        sub_exp = user.get('subscription_expires_at') if user else None
        if sub_exp:
            if isinstance(sub_exp, str):
                try:
                    sub_exp = datetime.strptime(sub_exp, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass
            now = datetime.now()
            diff_days = max(0, (sub_exp - now).days + 1) if sub_exp > now else 0
            discount = round(diff_days * (119.0 / 30.0))
            price = max(100, 1990 - discount)
        else:
            price = 1990
        return price, "直升尊榮版", "UniTask 基礎版中途直升尊榮版 - 即刻享全功能與 650 點 AI 額度"
    elif tier == 'POINTS_300':
        return 70, "AI智慧點數300點", "UniTask-AI智慧點數300點加購-永不過期"
    elif tier == 'POINTS_600':
        return 120, "AI智慧點數600點", "UniTask-AI智慧點數600點加購-極致划算永不過期"
    else:
        return 119, "基礎版", "UniTask 基礎版月費訂閱 - 解鎖行程備忘錄與 500 點 AI 額度"


@app.route('/ecpay/checkout', methods=['POST'])
def ecpay_checkout():
    """
    接收前端 JSON，計算 CheckMacValue 並回傳自動送出的隱藏表單 HTML，
    瀏覽器注入後立即 submit 至綠界測試 API。
    """
    if not is_payment_allowed():
        return jsonify({"status": "error", "message": "目前系統已關閉儲值與訂閱功能，目前不開放交易。"}), 403

    data = request.json or {}
    email = data.get('email', session.get('user_email', ''))
    tier  = data.get('tier', 'BASIC')

    price, product_name, trade_desc = _ecpay_get_price_for_tier(tier, email)

    # 產生唯一訂單號（格式：UTK + yyyymmddHHMMSS + 4位亂數，≤ 20 碼）
    now_str = datetime.now().strftime('%Y%m%d%H%M%S')
    rand4   = uuid.uuid4().hex[:4].upper()
    trade_no = f"UTK{now_str}{rand4}"  # 22 chars total... trim to 20
    trade_no = trade_no[:20]

    trade_date = datetime.now().strftime('%Y/%m/%d %H:%M:%S')

    # 本地測試：OrderResultURL 使用 127.0.0.1；ReturnURL 需公開 IP，暫用佔位
    # 生產環境：可由環境變數設定真實網址，例如 BASE_URL=https://unitask.yourdomain.com
    base_url = os.getenv('BASE_URL', request.host_url.rstrip('/'))
    order_result_url = f"{base_url}/ecpay/result"
    # ReturnURL 本地測試時綠界無法回調，填入 localhost 佔位（不影響前端流程）
    return_url = f"{base_url}/ecpay/return"


    is_recurring = data.get('is_recurring', False)

    params = {
        'MerchantID':        ECPAY_MERCHANT_ID,
        'MerchantTradeNo':   trade_no,
        'MerchantTradeDate': trade_date,
        'PaymentType':       'aio',
        'TotalAmount':       str(price),
        'TradeDesc':         trade_desc,   # 純文字！URL Encode 由 generate_check_mac_value 統一處理
        'ItemName':          product_name,
        'ReturnURL':         return_url,
        'OrderResultURL':    order_result_url,
        'ChoosePayment':     'Credit',
        'EncryptType':       '1',
        'CustomField1':      email,
        'CustomField2':      tier,
    }

    if is_recurring:
        period_type = 'Y' if tier in ['PREMIUM', 'PREMIUM_UPGRADE'] else 'M'
        exec_times = '9' if period_type == 'Y' else '99'
        params.update({
            'PeriodAmount':    str(price),
            'PeriodType':      period_type,
            'Frequency':       '1',
            'ExecTimes':       exec_times,
            'PeriodReturnURL': f"{base_url}/ecpay/period_return"
        })

    check_mac = generate_check_mac_value(params)
    params['CheckMacValue'] = check_mac

    # 動態產生含所有欄位的隱藏表單，前端注入後立即 submit
    fields_html = '\n'.join(
        f'<input type="hidden" name="{k}" value="{v}">'
        for k, v in params.items()
    )
    form_html = f'''
    <form id="ecpay-auto-form" method="POST" action="{ECPAY_API_URL}" style="display:none;">
        {fields_html}
    </form>
    '''
    print(f"[ECPay Checkout] 訂單 {trade_no} 建立，金額 NT${price}，方案 {tier}，Email {email}")
    return form_html, 200, {'Content-Type': 'text/html; charset=utf-8'}


@app.route('/ecpay/return', methods=['POST'])
def ecpay_return():
    """
    綠界伺服器背景通知（ReturnURL）。
    本地測試時綠界無法主動回調此路由；此路由為生產環境預留。
    必須回傳純文字 '1|OK' 讓綠界確認已收到通知。
    """
    data = request.form.to_dict()
    rtn_code = data.get('RtnCode', '')
    trade_no = data.get('MerchantTradeNo', '')
    amount   = data.get('TradeAmt', '')
    print(f"[ECPay ReturnURL] 收到背景通知 | 訂單: {trade_no} | 金額: {amount} | RtnCode: {rtn_code}")
    print(f"[ECPay ReturnURL] 完整參數: {data}")
    return '1|OK', 200


@app.route('/ecpay/period_return', methods=['POST'])
def ecpay_period_return():
    """
    綠界定期定額背景扣款通知（PeriodReturnURL）。
    每期自動扣款成功後，綠界會發送 POST 到此網址。
    必須回傳 '1|OK'。
    """
    data = request.form.to_dict()
    rtn_code = data.get('RtnCode', '')
    trade_no = data.get('MerchantTradeNo', '')
    amount = data.get('Amount', '')
    email = data.get('CustomField1', '')
    tier = data.get('CustomField2', 'BASIC')

    print(f"[ECPay PeriodReturn] 收到定期定額扣款通知 | 訂單: {trade_no} | 金額: {amount} | RtnCode: {rtn_code} | 用戶: {email}")

    # 驗證檢查碼
    received_mac = data.get('CheckMacValue', '')
    params_for_mac = {k: v for k, v in data.items() if k != 'CheckMacValue'}
    calculated_mac = generate_check_mac_value(params_for_mac)

    if received_mac != calculated_mac:
        print(f"[ECPay PeriodReturn Error] 檢查碼驗證失敗！收到: {received_mac} | 計算: {calculated_mac}")
        return '0|CheckMacValueVerifyFail', 200

    if rtn_code == '1':
        # 扣款成功，自動展延
        try:
            conn = get_db_connection()
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("SELECT * FROM users WHERE email = %s;", (email,))
                user = cursor.fetchone()
                if user:
                    current_points = user.get('ai_points', 0)
                    current_sub_exp = user.get('subscription_expires_at')
                    
                    from datetime import datetime, timedelta
                    now = datetime.now()
                    
                    # 若現有到期日在未來，以原到期日累加；否則以現在起算
                    if current_sub_exp:
                        if isinstance(current_sub_exp, str):
                            try:
                                current_sub_exp = datetime.strptime(current_sub_exp, "%Y-%m-%d %H:%M:%S")
                            except ValueError:
                                pass
                        
                        start_time = current_sub_exp if current_sub_exp > now else now
                    else:
                        start_time = now

                    # 依方案給予對應天數與 AI 點數
                    if tier in ['BASIC']:
                        sub_type = 'MONTHLY_AI'
                        new_points = current_points + 500
                        sub_expires = start_time + timedelta(days=30)
                    elif tier in ['PREMIUM_MONTHLY']:
                        sub_type = 'PREMIUM_MONTHLY'
                        new_points = current_points + 650
                        sub_expires = start_time + timedelta(days=30)
                    elif tier in ['PREMIUM', 'PREMIUM_UPGRADE']:
                        sub_type = 'YEARLY_AI'
                        new_points = current_points + 650
                        sub_expires = start_time + timedelta(days=365)
                    else:
                        sub_type = 'MONTHLY_AI'
                        new_points = current_points + 500
                        sub_expires = start_time + timedelta(days=30)

                    cursor.execute(
                        "UPDATE users SET is_subscribed=1, subscription_type=%s, ai_points=%s, subscription_expires_at=%s WHERE email=%s;",
                        (sub_type, new_points, sub_expires, email)
                    )
                    conn.commit()
                    print(f"[ECPay PeriodReturn Success] 定期扣款成功！已為 {email} 自動續訂方案 {tier}，新到期日為 {sub_expires}。")
                else:
                    print(f"[ECPay PeriodReturn Error] 找不到對應的用戶: {email}")
        except Exception as e:
            print(f"[ECPay PeriodReturn Error] DB 更新失敗: {e}")
        finally:
            if 'conn' in locals() and conn:
                conn.close()

    return '1|OK', 200


@app.route('/ecpay/result', methods=['GET', 'POST'])
def ecpay_result():
    """
    綠界付款完成後將使用者導回此頁（OrderResultURL）。
    解析 RtnCode，若成功（=1）則更新 DB 訂閱狀態並重導回 /?payment=success。
    """
    # 綠界以 POST form 或 GET querystring 導回
    data = request.form.to_dict() if request.method == 'POST' else request.args.to_dict()
    rtn_code = data.get('RtnCode', '')
    rtn_msg  = data.get('RtnMsg', '')
    trade_no = data.get('MerchantTradeNo', '')
    email    = data.get('CustomField1', '')
    tier     = data.get('CustomField2', 'BASIC')

    print(f"[ECPay Result] 訂單: {trade_no} | RtnCode: {rtn_code} | RtnMsg: {rtn_msg} | Email: {email} | Tier: {tier}")

    if rtn_code == '1':
        # 付款成功 → 複用既有的 DB 更新邏輯
        try:
            conn = get_db_connection()
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("SELECT * FROM users WHERE email = %s;", (email,))
                user = cursor.fetchone()
                if user:
                    current_points = user.get('ai_points', 0)
                    current_sub    = user.get('subscription_type', 'NONE')
                    now = datetime.now()

                    if tier in ['BASIC']:
                        sub_type   = 'MONTHLY_AI'
                        new_points = current_points + 500
                        sub_expires = now + timedelta(days=30)
                        cursor.execute(
                            "UPDATE users SET is_subscribed=1, subscription_type=%s, ai_points=%s, subscription_expires_at=%s WHERE email=%s;",
                            (sub_type, new_points, sub_expires, email)
                        )
                    elif tier in ['PREMIUM_MONTHLY']:
                        sub_type   = 'PREMIUM_MONTHLY'
                        new_points = current_points + 650
                        sub_expires = now + timedelta(days=30)
                        cursor.execute(
                            "UPDATE users SET is_subscribed=1, subscription_type=%s, ai_points=%s, subscription_expires_at=%s WHERE email=%s;",
                            (sub_type, new_points, sub_expires, email)
                        )
                    elif tier in ['PREMIUM', 'PREMIUM_UPGRADE']:
                        sub_type   = 'YEARLY_AI'
                        new_points = current_points + 650
                        sub_expires = now + timedelta(days=365)
                        cursor.execute(
                            "UPDATE users SET is_subscribed=1, subscription_type=%s, ai_points=%s, subscription_expires_at=%s WHERE email=%s;",
                            (sub_type, new_points, sub_expires, email)
                        )
                    elif tier == 'POINTS_300':
                        new_points = current_points + 300
                        sub_type   = current_sub
                        sub_expires = user.get('subscription_expires_at')
                        cursor.execute("UPDATE users SET ai_points=%s WHERE email=%s;", (new_points, email))
                    elif tier == 'POINTS_600':
                        new_points = current_points + 600
                        sub_type   = current_sub
                        sub_expires = user.get('subscription_expires_at')
                        cursor.execute("UPDATE users SET ai_points=%s WHERE email=%s;", (new_points, email))

                    conn.commit()

                    # 同步更新 session（若為當前登入用戶）
                    if session.get('user_email') == email:
                        session['is_subscribed'] = True
                        session['subscription_type'] = sub_type
                        session['ai_points'] = new_points
                        if sub_expires:
                            session['subscription_expires_at'] = (
                                sub_expires if isinstance(sub_expires, str)
                                else sub_expires.strftime("%Y-%m-%d %H:%M:%S")
                            )
                    print(f"[ECPay Result] 付款成功！用戶 {email} 方案 {tier} 已更新。")
        except Exception as e:
            print(f"[ECPay Result Error] DB 更新失敗: {e}")
        finally:
            if 'conn' in locals() and conn:
                conn.close()

        return redirect('/?payment=success')
    else:
        print(f"[ECPay Result] 付款失敗或取消。RtnCode={rtn_code}, RtnMsg={rtn_msg}")
        return redirect('/?payment=fail')


@app.route('/api/sync_profile', methods=['POST'])
def sync_profile():
    """同步前端設定的性別、生理期啟用狀態與時區，並自動執行固定支出檢查"""
    data = request.json or {}
    gender = data.get('gender', 'girl')
    enable_period = data.get('enable_period', True)
    timezone_str = data.get('timezone', 'Asia/Taipei')
    
    session['user_gender'] = gender
    session['enable_period'] = enable_period
    session['timezone'] = timezone_str
    
    # 執行固定支出自動補記檢查
    executed_items = []
    spreadsheet_id = get_spreadsheet_id()
    if spreadsheet_id:
        try:
            service = get_sheets_service()
            executed_items = check_and_execute_fixed_expenses(service, spreadsheet_id)
        except Exception as e:
            print(f"[sync_profile] Fixed expenses execution error: {e}")

    print(f"Profile synced: gender={gender}, enable_period={enable_period}, timezone={timezone_str}, executed={executed_items}")
    return jsonify({
        "status": "success",
        "gender": gender,
        "enable_period": enable_period,
        "timezone": timezone_str,
        "executed_items": executed_items
    })



VALID_EXPENSE_SUB_CATEGORIES = {
    "食": ["早餐", "午餐", "晚餐", "飲料／咖啡", "外送", "超商／零食", "聚餐", "其他"],
    "衣": ["上衣／褲子", "鞋子", "包包／配件", "保養／化妝品", "洗頭", "美甲", "做臉", "美容／理美髮", "其他"],
    "住": ["房租", "水費", "電費", "瓦斯費", "管理費", "手機費", "網路費", "修繕／家具", "清潔用品", "其他"],
    "行": ["油錢／加油", "停車費", "大眾交通", "Uber／計程車", "高鐵／火車", "機票", "其他"],
    "育": ["書籍", "課程／學費", "補習", "文具", "其他"],
    "樂": ["電影／演唱會", "KTV", "旅遊", "遊戲", "訂閱娛樂", "放鬆按摩", "SPA", "油壓／指壓", "其他"],
    "醫": ["掛號／看診", "藥品", "健保", "保健品", "推拿／整脊", "復健", "其他"],
    "保險費": ["壽險", "醫療險", "車險", "產險", "其他保費", "其他"],
    "貸款": ["信貸", "車貸", "房貸", "商品貸", "其他"],
    "儲蓄/投資": ["緊急備用金", "定存", "活儲", "投資型保單", "股票", "基金", "外匯", "其他衍生性商品", "其他"],
    "宗教/公益": ["其他"],
    "其他雜支": ["其他"]
}

VALID_INCOME_SUB_CATEGORIES = {
    "薪資": ["正職薪水", "兼職時薪", "小費進帳", "其他"],
    "獎金": ["年終獎金", "績效/三節", "專案分紅", "其他"],
    "投資獲利": ["股票股利/價差", "基金配息", "定存利息", "加密貨幣", "其他"],
    "副業收入": ["諮詢服務", "個人項目", "團購/分潤", "諮詢隨喜/小費", "其他"],
    "變更/退款": ["購物退款", "代墊款收回", "其他雜項", "其他"],
    "儲蓄/投資": ["緊急備用金", "定存", "活儲", "投資型保單", "股票", "基金", "外匯", "其他衍生性商品", "其他"],
    "貸款": ["信貸", "車貸", "房貸", "商品貸", "其他"]
}

def normalize_sub_category(category, sub_cat, is_income=False):
    sub_cat = (sub_cat or "").strip()
    if not sub_cat:
        return "其他"
        
    mapping = VALID_INCOME_SUB_CATEGORIES if is_income else VALID_EXPENSE_SUB_CATEGORIES
    
    if category not in mapping:
        return "其他"
        
    valid_list = mapping[category]
    
    def clean_str(s):
        return s.replace('／', '/').replace(' ', '').lower()
        
    cleaned_sub_cat = clean_str(sub_cat)
    
    # First pass: exact clean match
    for valid_item in valid_list:
        if clean_str(valid_item) == cleaned_sub_cat:
            return valid_item
            
    # Second pass: substring match (excluding "其他")
    for valid_item in valid_list:
        if valid_item == "其他":
            continue
        cv = clean_str(valid_item)
        if cleaned_sub_cat in cv or cv in cleaned_sub_cat:
            return valid_item
            
    return "其他"

def rule_based_expense_parser(text, email=None):
    import re
    # Split by common conjunctions
    parts = re.split(r'然後|跟|和|，|、|\+|且|以及', text)
    expenses = []
    
    # Simple category keyword map
    cat_keywords = {
        '食': ['餐', '便當', '飯', '麵', '壽司', '火鍋', '餐廳', '點心', '麵包', '宵夜', '水果', '超商', '飲料', '咖啡', '茶', '奶茶', '冰', '麥當勞', '肯德基', '早餐', '午餐', '晚餐', '吃', '喝', '雞排', '茶'],
        '行': ['捷運', '公車', '計程車', '火車', '高鐵', '加油', '停車', '機車', '汽車', '悠遊卡', 'uber', '車票', '機票', '油錢', '客運', '輕軌', '租車'],
        '住': ['房租', '水費', '電費', '瓦斯', '網路', '管理費', '衛生紙', '洗面乳', '沐浴乳', '日用品', '生活百貨', '水電', '租金', '裝潢', '傢俱', '家電'],
        '衣': ['衣服', '褲子', '鞋子', '外套', '襪子', '襯衫', '帽子', '裙子', '西裝', '服飾', '買衣', '洗頭', '美甲', '美睫', '做臉', '美容', '理髮', '剪髮', '染髮'],
        '育': ['書', '課', '學費', '文具', '雜誌', '報紙', '演講', '補習', '教材', '原子筆'],
        '樂': ['電影', '遊戲', '唱歌', '玩具', '旅遊', '門票', '展覽', '密室', '打電動', '遊樂園', '住宿', '機票', '玩樂', '追劇', 'netflix', 'spotify', '按摩', 'spa', '油壓', '指壓'],
        '醫': ['看病', '門診', '藥', '醫院', '診所', '口罩', '感冒', '牙醫', '掛號', '醫療', '保健食品', '推拿', '整脊', '整骨', '復健'],
        '儲蓄/投資': ['股票', '基金', '定存', '理財', '投資', '買股', '證券', '美股', '台股'],
        '宗教/公益': ['捐款', '發票', '捐贈', '慈善', '公益', '愛心', '捐錢', '拜拜', '香油錢', '安太歲', '法會', '廟', '宗教']
    }
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
        
        # Match pattern: item name followed by numbers, optional "元" or "塊" or "元元" at the end
        match = re.search(r'^([^\d]+?)(?:花了|支出|買)?\s*(\d+)\s*(?:元|塊)?$', part)
        if match:
            item = match.group(1).strip()
            amount = int(match.group(2))
            
            category = None
            sub_category = None
            
            # Predefined sub-category mapping rules based on keywords
            if not category or not sub_category:
                category = '食' # default fallback
                sub_category = '其他'
                
                # Check category keywords
                for cat, keywords in cat_keywords.items():
                    if any(keyword in item for keyword in keywords):
                        category = cat
                        break
                
                sub_cat_rules = {
                    '食': [
                        ('早餐', '早餐'),
                        ('午餐', '午餐'),
                        ('中餐', '午餐'),
                        ('晚餐', '晚餐'),
                        ('便當', '午餐'),
                        ('宵夜', '晚餐'),
                        ('飲料', '飲料／咖啡'),
                        ('咖啡', '飲料／咖啡'),
                        ('茶', '飲料／咖啡'),
                        ('奶茶', '飲料／咖啡'),
                        ('外送', '外送'),
                        ('超商', '超商／零食'),
                        ('零食', '超商／零食'),
                        ('聚餐', '聚餐'),
                    ],
                    '行': [
                        ('計程車', 'Uber／計程車'),
                        ('小黃', 'Uber／計程車'), # wait, Uber／計程車
                        ('uber', 'Uber／計程車'),
                        ('捷運', '大眾交通'),
                        ('公車', '大眾交通'),
                        ('火車', '高鐵／火車'),
                        ('高鐵', '高鐵／火車'),
                        ('飛機', '機票'),
                        ('機票', '機票'),
                        ('悠遊卡', '大眾交通'),
                        ('加油', '油錢／加油'),
                        ('油錢', '油錢／加油'),
                        ('停車', '停車費'),
                    ],
                    '住': [
                        ('房租', '房租'),
                        ('租金', '房租'),
                        ('水費', '水費'),
                        ('電費', '電費'),
                        ('瓦斯', '瓦斯費'),
                        ('管理費', '管理費'),
                        ('手機', '手機費'),
                        ('電話費', '手機費'),
                        ('網路', '網路費'),
                        ('修繕', '修繕／家具'),
                        ('家具', '修繕／家具'),
                        ('清潔', '清潔用品'),
                    ],
                    '衣': [
                        ('衣服', '上衣／褲子'),
                        ('褲子', '上衣／褲子'),
                        ('外套', '上衣／褲子'),
                        ('襯衫', '上衣／褲子'),
                        ('裙子', '上衣／褲子'),
                        ('鞋', '鞋子'),
                        ('包包', '包包／配件'),
                        ('配件', '包包／配件'),
                        ('保養', '保養／化妝品'),
                        ('化妝', '保養／化妝品'),
                        ('洗頭', '洗頭'),
                        ('美甲', '美甲'),
                        ('做臉', '做臉'),
                        ('美容', '美容／理美髮'),
                        ('美髮', '美容／理美髮'),
                        ('理髮', '美容／理美髮'),
                        ('剪髮', '美容／理美髮'),
                        ('染髮', '美容／理美髮'),
                    ],
                    '育': [
                        ('書', '書籍'),
                        ('課程', '課程／學費'),
                        ('學費', '課程／學費'),
                        ('補習', '補習'),
                        ('文具', '文具'),
                    ],
                    '樂': [
                        ('電影', '電影／演唱會'),
                        ('演唱會', '電影／演唱會'),
                        ('ktv', 'KTV'),
                        ('唱歌', 'KTV'),
                        ('旅遊', '旅遊'),
                        ('住宿', '旅遊'),
                        ('遊戲', '遊戲'),
                        ('電動', '遊戲'),
                        ('訂閱', '訂閱娛樂'),
                        ('按摩', '放鬆按摩'),
                        ('spa', 'SPA'),
                        ('SPA', 'SPA'),
                        ('油壓', '油壓／指壓'),
                        ('指壓', '油壓／指壓'),
                    ],
                    '醫': [
                        ('看病', '掛號／看診'),
                        ('門診', '掛號／看診'),
                        ('掛號', '掛號／看診'),
                        ('診所', '掛號／看診'),
                        ('藥', '藥品'),
                        ('感冒', '藥品'),
                        ('健保', '健保'),
                        ('保健品', '保健品'),
                        ('維他命', '保健品'),
                        ('推拿', '推拿／整脊'),
                        ('整脊', '推拿／整脊'),
                        ('整骨', '推拿／整脊'),
                        ('復健', '復健'),
                    ],
                    '儲蓄/投資': [
                        ('緊急備用金', '緊急備用金'),
                        ('備用金', '緊急備用金'),
                        ('定存', '定存'),
                        ('活儲', '活儲'),
                        ('活期', '活儲'),
                        ('存款', '活儲'),
                        ('投資型保單', '投資型保單'),
                        ('保單', '投資型保單'),
                        ('股票', '股票'),
                        ('買股', '股票'),
                        ('基金', '基金'),
                        ('外匯', '外匯'),
                        ('衍生性商品', '其他衍生性商品'),
                    ],
                    '宗教/公益': [
                        ('捐款', '其他'),
                        ('公益', '其他'),
                        ('拜拜', '其他'),
                        ('香油錢', '其他'),
                        ('安太歲', '其他'),
                        ('法會', '其他'),
                    ]
                }
                
                # Apply sub-category rules for the detected category
                if category in sub_cat_rules:
                    for kw, sub_cat in sub_cat_rules[category]:
                        if kw in item:
                            sub_category = sub_cat
                            break
                            
            # Ensure normalization
            sub_category = normalize_sub_category(category, sub_category, is_income=False)
            
            # Strip verb prefix if any
            for prefix in ['買', '吃', '喝', '付', '繳']:
                if item.startswith(prefix) and len(item) > len(prefix):
                    item = item[len(prefix):]
            
            expenses.append({
                'type': 'expense',
                'item': item,
                'amount': amount,
                'category': category,
                'sub_category': sub_category
            })
            
    return expenses

def rule_based_calendar_parser(text, now):
    import re
    text_clean = text.strip()
    if not any(kw in text_clean for kw in ["行程", "日曆", "行事曆", "新增", "安排", "唱歌", "約會", "開會", "會議"]):
        return None
        
    start_time = None
    title = "約會/活動"
    location = ""
    
    # 1. 日期解析
    date_match = re.search(r'(\d+)\s*月\s*(\d+)\s*[號日]', text_clean)
    if date_match:
        month = int(date_match.group(1))
        day = int(date_match.group(2))
        try:
            start_dt = now.replace(month=month, day=day, hour=12, minute=0, second=0, microsecond=0)
            start_time = start_dt.isoformat()
        except:
            pass
            
    if not start_time:
        if "今天" in text_clean:
            start_time = now.replace(hour=12, minute=0, second=0, microsecond=0).isoformat()
        elif "明天" in text_clean:
            start_time = (now + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0).isoformat()
        elif "後天" in text_clean:
            start_time = (now + timedelta(days=2)).replace(hour=12, minute=0, second=0, microsecond=0).isoformat()
            
    time_match = re.search(r'(\d+)\s*點\s*(\d+)?\s*分?', text_clean)
    if time_match and start_time:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        if any(kw in text_clean for kw in ["下午", "晚上", "pm"]) and hour < 12:
            hour += 12
        try:
            dt = datetime.fromisoformat(start_time)
            start_time = dt.replace(hour=hour, minute=minute).isoformat()
        except:
            pass
            
    if not start_time:
        start_time = (now + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0).isoformat()

    # 2. 地點解析
    loc_match = re.search(r'地點(?:是|在)\s*([^，。\s]+)', text_clean)
    if loc_match:
        location = loc_match.group(1).strip()
    else:
        loc_match2 = re.search(r'在\s*([^，。去新增時間地點在是\s]{2,15})', text_clean)
        if loc_match2:
            location = loc_match2.group(1).strip()
            
    # 3. 標題解析
    title_match = re.search(r'去\s*([^，。地點是在\s]{2,10})', text_clean)
    if title_match:
        title = title_match.group(1).strip()
    else:
        temp_title = text_clean
        temp_title = re.sub(r'新增|安排|行程|日曆|行事曆', '', temp_title)
        temp_title = re.sub(r'\d+\s*月\s*\d+\s*[號日]|今天|明天|後天', '', temp_title)
        temp_title = re.sub(r'\d+\s*點\s*(\d+\s*分)?', '', temp_title)
        temp_title = re.sub(r'下午|晚上|上午|中午', '', temp_title)
        if location:
            temp_title = temp_title.replace(location, '')
        temp_title = re.sub(r'地點(?:是|在)|是在|在|的|去', '', temp_title)
        temp_title = temp_title.replace('，', '').replace('。', '').strip()
        if len(temp_title) >= 2:
            title = temp_title
            
    if location and location in title:
        title = title.replace(location, '').strip()
        
    if not title:
        title = "約會/活動"
        
    return {
        "type": "calendar",
        "title": title,
        "location": location,
        "start_time": start_time,
        "end_time": (datetime.fromisoformat(start_time) + timedelta(hours=1)).isoformat()
    }

@app.route('/chat', methods=['POST'])
@app.route('/api/chat', methods=['POST'])
def chat():
    """處理前端送來的對話訊息 (支援文字與圖片)"""
    email = session.get('user_email', '')
    developer_emails = {'ulir976272866@gmail.com', 'mina.chen.xstar.sg@gmail.com'}
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "false" and email:
        sub_type = session.get('subscription_type', 'NONE')
        # 如果不是無限點數方案且不在開發者白名單中
        if sub_type not in ['YEARLY_AI', 'PREMIUM_MONTHLY'] and email.lower() not in developer_emails:
            current_points = session.get('ai_points', 0)
            conn = None
            try:
                conn = get_db_connection()
                with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                    cursor.execute("SELECT ai_points FROM users WHERE email = %s;", (email,))
                    user = cursor.fetchone()
                    if user:
                        current_points = user.get('ai_points', 0)
            except Exception as e:
                print(f"[Points Check Error in Chat] {e}")
            finally:
                if conn:
                    conn.close()
            
            if current_points <= 0:
                return jsonify({
                    "status": "error",
                    "message": "🚨 您的 AI 智慧對話點數不足！您的對話額度已用完 (0點)，請立即儲值加購點數，或升級為無限對話的尊榮會員方案！",
                    "points_depleted": True
                })

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
        elif user_text in ["投資持股", "查詢持股", "存股明細", "啟動股票導航", "股票導航"]:
            bypass_data = {"type": "query_stock_portfolio"}
        elif user_text == "開啟記帳表單":
            bypass_data = {"type": "open_spreadsheet"}
        elif user_text in ["查詢代墊", "代墊查詢", "代墊款", "待收代墊款"]:
            bypass_data = {"type": "query_bill_splits"}
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
        expense_categories = ["食", "衣", "住", "行", "育", "樂", "醫", "保險費", "貸款", "儲蓄/投資", "宗教/公益"]
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
        - 如果是收據或發票：
          1. 必須以「使用者實際支付的總金額（真正從口袋掏出或行動支付、信用卡付出的總額）」為準！
          2. 注意：有些收據上會包含「代售/代收商品/代收款項」（例如 2 元的垃圾袋、兩用袋或代售車票）。店家的發票明細「實付金額」或「應稅/免稅小計」可能只列出商店開立發票的金額（如 114 元），但下方會另有「代收/代售合計」或在支付明細顯示「掃碼付_街口」、「LINE Pay」、「信用卡」、「實付/合計」為 116 元。此時你【必須選擇包含代收商品在內的最終實際總支付金額 116 元】，千萬不要漏掉用戶實際付出的任何一毛錢！
          3. 金額優先順序：用戶實際支付的最終總額（如「掃碼付_街口」、「行動支付明細」、「信用卡/現金實付總計」、「合計」包含代收費用後的金額） > 店家發票發行小計。
        - 如果是行程：提取標題、時間與地點。
        
        【意圖判斷】：
        - 記帳：type: "expense" (item, amount, category: {cat_list_str}, sub_category: "對應的子分類", expense_type: "income" 或 "expense")
        - 糾錯/刪除上一筆：type: "correct_intent" (不需要其他欄位)
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
        
        【特別規則 (支出母子分類映射)】：
        如果是支出，並且 category 與 sub_category 必須配對正確的項目：
        - "食" -> "早餐"、"午餐"、"晚餐"、"飲料／咖啡"、"外送"、"超商／零食"、"聚餐"、"其他"
        - "衣" -> "上衣／褲子"、"鞋子"、"包包／配件"、"保養／化妝品"、"洗頭"、"美甲"、"做臉"、"美容／理美髮"、"其他"
        - "住" -> "房租"、"水費"、"電費"、"瓦斯費"、"管理費"、"手機費"、"網路費"、"修繕／家具"、"清潔用品"、"其他"
        - "行" -> "油錢／加油"、"停車費"、"大眾交通"、"Uber／計程車"、"高鐵／火車"、"機票"、"其他"
        - "育" -> "書籍"、"課程／學費"、"補習"、"文具"、"其他"
        - "樂" -> "電影／演唱會"、"KTV"、"旅遊"、"遊戲"、"訂閱娛樂"、"放鬆按摩"、"SPA"、"油壓／指壓"、"其他"
        - "醫" -> "掛號／看診"、"藥品"、"健保"、"保健品"、"推拿／整脊"、"復健"、"其他"
        - "保險費" -> "壽險"、"醫療險"、"車險"、"產險"、"其他保費"、"其他"
        - "貸款" -> "信貸"、"車貸"、"房貸"、"商品貸"、"其他"
        - "儲蓄/投資" -> "緊急備用金"、"定存"、"活儲"、"投資型保單"、"股票"、"基金"、"外匯"、"其他衍生性商品"、"其他"
        - "宗教/公益" -> "其他"
        - "其他雜支" -> "其他"
        
        【特別規則 (收入母子分類映射)】：
        如果是領錢、薪水、進帳、退款、中獎等屬於「收入」，請將 expense_type 設為 "income"。
        並且 category 只能從以下五大母分類挑選，且必須配對正確的 sub_category：
        1. "薪資" -> sub_category: "正職薪水"、"兼職時薪"、"小費進帳"
        2. "獎金" -> sub_category: "年終獎金"、"績效/三節"、"專案分紅"
        3. "投資獲利" -> sub_category: "股票股利/價差"、"基金配息"、"定存利息"、"加密貨幣"
        4. "副業收入" -> sub_category: "諮詢服務"、"個人項目"、"團購/分潤"、"諮詢隨喜/小費"
        5. "變更/退款" -> sub_category: "購物退款"、"代墊款收回"
        * 關鍵提示：當使用者說「收到諮詢隨喜」或「小費」時，請對應到 category: "副業收入", sub_category: "諮詢隨喜/小費" 或 category: "薪資", sub_category: "小費進帳"。
        * 「其他」回退規則：如果此項支出/收入在各母分類的預設子分類中沒有對應項目，請將 sub_category 設定為 "其他"。
        {ai_rules_str}
        
        【格式要求】：
        - 請務必返回 JSON。
        - 如果是多個意圖或多個項目，請返回 JSON 陣列 (List of dicts)。例如，輸入「晚餐壽司170然後飲料50」應返回包含兩個 expense 物件的 JSON 陣列。
        - 如果是單一意圖，可返回單個 JSON 物件。
        """

        try:
            model = genai.GenerativeModel('gemini-3.1-flash-lite')
            contents = [prompt]
            if user_text: contents.append(f"使用者：{user_text}")
            if image_file: contents.append(Image.open(image_file))
            
            response = model.generate_content(contents)
            raw_text = response.text.strip()
            
            # 使用 Regex 強力提取 JSON，防止 Extra Data 錯誤
            import re
            json_text = raw_text
            markdown_match = re.search(r'```json\s*(.*?)\s*```', raw_text, re.DOTALL | re.IGNORECASE)
            if markdown_match:
                json_text = markdown_match.group(1).strip()
            else:
                # 尋找最外圍的方括號 [ ]
                array_match = re.search(r'(\[.*\])', raw_text, re.DOTALL)
                if array_match:
                    json_text = array_match.group(1).strip()
                else:
                    # 尋找最外圍的花括號 { }
                    obj_match = re.search(r'(\{.*\})', raw_text, re.DOTALL)
                    if obj_match:
                        json_text = obj_match.group(1).strip()
                        
            data = json.loads(json_text)
            if isinstance(data, list):
                if len(data) == 0:
                    raise Exception("AI returned empty list")
                elif len(data) == 1:
                    parsed_data = data[0]
                else:
                    parsed_data = data
            else:
                parsed_data = data
            print(f"Parsed AI response: {parsed_data}")
            
            # 扣除 1 點 AI 對話點數 (非無限版且非 bypass)
            if os.getenv("SINGLE_USER_MODE", "false").lower() == "false" and email:
                sub_type = session.get('subscription_type', 'NONE')
                if sub_type not in ['YEARLY_AI', 'PREMIUM_MONTHLY'] and email.lower() not in developer_emails:
                    check_and_deduct_points(email, 1)
        except Exception as e:
            print(f"Gemini AI Error: {e}")
            cal_fallback = rule_based_calendar_parser(user_text, now) if user_text else None
            if cal_fallback:
                parsed_data = cal_fallback
                session['ai_fallback_warning'] = True
            else:
                fallback_parsed = rule_based_expense_parser(user_text, email) if user_text else []
                if fallback_parsed:
                    parsed_data = fallback_parsed if len(fallback_parsed) > 1 else fallback_parsed[0]
                    session['ai_fallback_warning'] = True
                else:
                    err_msg = str(e)
                    if "API key was reported as leaked" in err_msg or "API_KEY_INVALID" in err_msg or "403" in err_msg or "prepayment credits" in err_msg:
                        return jsonify({
                            "status": "error",
                            "message": "⚠️ 目前系統對話模組進行維護中，暫時無法處理此類型指令。請稍後再試！"
                        })
                    return jsonify({"status": "error", "message": "AI 處理失敗，請稍後再試。"})

    ai_response_message = None
    if isinstance(parsed_data, list):
        # 批次處理模式 (多意圖/複合記帳)
        cleaned_intents = []
        for item in parsed_data:
            if isinstance(item, dict):
                for k in ["response", "reply", "message"]:
                    if k in item:
                        val = item.pop(k)
                        if val and not ai_response_message:
                            ai_response_message = val
                if "data" in item and isinstance(item["data"], dict):
                    nested_data = item.pop("data")
                    for k in ["response", "reply", "message"]:
                        if k in nested_data and not ai_response_message:
                            ai_response_message = nested_data.pop(k)
                    item.update(nested_data)
                if item.get('type') == 'expense':
                    item['sub_category'] = normalize_sub_category(
                        item.get('category'),
                        item.get('sub_category'),
                        is_income=(item.get('expense_type') == 'income')
                    )
                cleaned_intents.append(item)
                
        expenses = [x for x in cleaned_intents if x.get('type') == 'expense']
        calendars = [x for x in cleaned_intents if x.get('type') == 'calendar']
        correct_intents = [x for x in cleaned_intents if x.get('type') == 'correct_intent']
        others = [x for x in cleaned_intents if x.get('type') not in ['expense', 'calendar', 'correct_intent']]
        
        success_messages = []
        error_messages = []
        chart_data = None
        has_charity = False
        
        if expenses:
            try:
                service = get_sheets_service()
                values_to_append = []
                for exp in expenses:
                    is_income = exp.get('expense_type') == 'income'
                    category = exp.get('category')
                    if category in ['公益', '宗教/公益']:
                        has_charity = True
                    values_to_append.append([
                        str(now.year), 
                        f"'{now.month:02d}", 
                        now.strftime("%Y/%m/%d"), 
                        exp.get('item') if is_income else "", 
                        "" if is_income else exp.get('item'), 
                        exp.get('amount'), 
                        format_category_with_emoji(category, is_income),
                        exp.get('sub_category', '')
                    ])
                
                # 單次寫入 (V3.8 Step 3)
                append_res = service.spreadsheets().values().append(
                    spreadsheetId=SPREADSHEET_ID, 
                    range='記帳!A:H', 
                    valueInputOption='USER_ENTERED', 
                    body={'values': values_to_append}
                ).execute()
                
                updated_range = append_res.get('updates', {}).get('updatedRange', '')
                import re
                match = re.search(r'A(\d+):', updated_range)
                start_row = int(match.group(1)) if match else None
                
                _, cat_report, cat_dict, _ = get_monthly_report(service, now)
                chart_data = cat_dict
                
                # 更新習慣與資產連動 (V3.8 Step 3)
                for idx, exp in enumerate(expenses):
                    is_income = exp.get('expense_type') == 'income'
                    emoji = "💰" if is_income else "💸"
                    label = "收入" if is_income else "支出"
                    category = exp.get('category')
                    sub_category = exp.get('sub_category', '')
                    amount = int(exp.get('amount') or 0)
                    item = exp.get('item')
                    
                    row_num = start_row + idx if start_row else None
                    success_msg_item = f"{emoji} 已記{label}：{item} ${amount}"
                    
                    # 匹配與更新餘額
                    if category in ['儲蓄/投資', '貸款'] and row_num:
                        try:
                            ensure_user_spreadsheet()
                            res_accts = service.spreadsheets().values().get(
                                spreadsheetId=SPREADSHEET_ID,
                                range='資產帳戶!A:F'
                            ).execute()
                            rows_accts = res_accts.get('values', [])
                            accounts = []
                            if len(rows_accts) > 1:
                                for idx_a, row_a in enumerate(rows_accts[1:]):
                                    while len(row_a) < 6:
                                        row_a.append('')
                                    try:
                                        bal_a = int(float(row_a[2])) if row_a[2] else 0
                                    except ValueError:
                                        bal_a = 0
                                    accounts.append({
                                        "name": row_a[0].strip(),
                                        "type": row_a[1].strip(),
                                        "balance": bal_a,
                                        "id": row_a[3].strip(),
                                        "updated_time": row_a[4].strip(),
                                        "remark": row_a[5].strip()
                                    })
                            
                            candidates = []
                            user_text_clean = (user_text or "").lower()
                            item_clean = (item or "").lower()
                            sub_cat_clean = (sub_category or "").lower()
                            
                            for acct in accounts:
                                acct_name = acct['name'].lower()
                                if acct_name in user_text_clean or acct_name in item_clean or acct_name in sub_cat_clean:
                                    candidates.append(acct)
                                elif (item_clean and item_clean in acct_name) or (sub_cat_clean and sub_cat_clean in acct_name):
                                    if len(item_clean) >= 2 or len(sub_cat_clean) >= 2:
                                        candidates.append(acct)
                                else:
                                    for keyword in ["國泰", "郵局", "玉山", "緊急備用金", "備用金", "現金", "口袋", "交割戶"]:
                                        if keyword in acct_name and (keyword in user_text_clean or keyword in item_clean):
                                            if acct not in candidates:
                                                candidates.append(acct)
                                                
                            amount_change = -amount if is_income else amount
                            
                            if len(candidates) == 1:
                                current_time = datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M:%S')
                                acct_name, old_bal, new_bal = update_linked_asset_balance(
                                    service, SPREADSHEET_ID, candidates[0]['id'], amount_change, current_time
                                )
                                success_msg_item += f" 🏦 (已自動連動更新「{acct_name}」餘額：{old_bal:,} → {new_bal:,})"
                            elif len(candidates) > 1:
                                buttons_html = []
                                for c in candidates:
                                    btn_text = f"🏦 {c['name']}" if c['type'] == '活儲' else (f"📉 {c['name']}" if c['type'] == '貸款' or '信貸' in c['name'] else f"💰 {c['name']}")
                                    buttons_html.append(
                                        f'<button onclick="window.linkTransactionToAsset({row_num}, \'{c["id"]}\', {amount_change}, this)" class="disambiguation-btn" style="padding: 6px 12px; border-radius: 12px; border: 1px solid #e2e8f0; background: #fff; color: #1e293b; font-size: 0.8rem; font-weight: 700; cursor: pointer; transition: all 0.2s;">{btn_text}</button>'
                                    )
                                buttons_html.append(
                                    f'<button onclick="window.linkTransactionToAsset({row_num}, \'\', 0, this)" class="disambiguation-btn" style="padding: 6px 12px; border-radius: 12px; border: 1px solid #e2e8f0; background: #f1f5f9; color: #64748b; font-size: 0.8rem; font-weight: 700; cursor: pointer; transition: all 0.2s;">✕ 暫不連動</button>'
                                )
                                
                                card_html = f"""<br>
<div class="disambiguation-card" style="padding: 12px; background: rgba(148, 163, 184, 0.05); border: 1px solid #e2e8f0; border-radius: 16px; margin-top: 4px;">
    <div style="font-size: 0.85rem; color: #64748b; margin-bottom: 8px; font-weight: 700;">💬 偵測到多個匹配的帳戶，請問要連動這筆金額到？</div>
    <div style="display: flex; flex-wrap: wrap; gap: 6px;" id="disambiguation-buttons-{row_num}">
        {" ".join(buttons_html)}
    </div>
</div>
"""
                                success_msg_item += card_html
                        except Exception as ex:
                            print(f"Batch Link Balance Error: {ex}")
                            success_msg_item += f"\n⚠️ 連動更新餘額失敗：{str(ex)}"
                            
                    success_messages.append(success_msg_item)
                    

                success_messages.append(f"\n{cat_report}")
            except Exception as e:
                print(f"[Batch Expense Error] {e}")
                for exp in expenses:
                    error_messages.append(f"❌ {exp.get('item')} ${exp.get('amount')} 記錄失敗：{str(e)}")
                    
        if calendars:
            service_cal = get_calendar_service()
            for cal in calendars:
                try:
                    start_time_str = cal.get('start_time')
                    if not start_time_str:
                        error_messages.append(f"❌ 行事曆「{cal.get('title')}」記錄失敗：缺少開始時間。")
                        continue
                    is_all_day = False
                    if len(start_time_str) <= 10 or 'T' not in start_time_str:
                        is_all_day = True
                        start_date = start_time_str[:10]
                        dt = datetime.strptime(start_date, '%Y-%m-%d')
                        end_date = (dt + timedelta(days=1)).strftime('%Y-%m-%d')
                        event = {
                            'summary': cal.get('title'),
                            'location': cal.get('location', ''),
                            'start': { 'date': start_date, 'timeZone': 'Asia/Taipei' },
                            'end': { 'date': end_date, 'timeZone': 'Asia/Taipei' },
                        }
                    else:
                        is_all_day = False
                        start_str = start_time_str
                        if 'T' in start_str and '+' not in start_str and 'Z' not in start_str:
                            start_str += '+08:00'
                        start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                        
                        end_str = cal.get('end_time')
                        if end_str:
                            if 'T' in end_str and '+' not in end_str and 'Z' not in end_str:
                                end_str += '+08:00'
                            end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                        else:
                            end_dt = start_dt + timedelta(hours=1)
                        event = {
                            'summary': cal.get('title'),
                            'location': cal.get('location', ''),
                            'start': { 'dateTime': start_dt.isoformat(), 'timeZone': 'Asia/Taipei' },
                            'end': { 'dateTime': end_dt.isoformat(), 'timeZone': 'Asia/Taipei' },
                        }
                        
                    conflict_msg = check_conflicts(
                        service_cal, 
                        event['start'].get('dateTime', event['start'].get('date')), 
                        event['end'].get('dateTime', event['end'].get('date')),
                        summary=event.get('summary')
                    )
                    if conflict_msg:
                        error_messages.append(f"❌ 行事曆「{cal.get('title')}」衝突：{conflict_msg}")
                        continue
                        
                    service_cal.events().insert(calendarId=CALENDAR_ID, body=event).execute()
                    cal_msg = format_event_success_message(
                        title=cal.get('title'),
                        start_time_str=start_time_str,
                        location=cal.get('location', ''),
                        is_all_day=is_all_day,
                        is_manual=False
                    )
                    success_messages.append(cal_msg)
                except Exception as e:
                    print(f"[Batch Calendar Error] {e}")
                    error_messages.append(f"❌ 行事曆「{cal.get('title')}」記錄失敗：{str(e)}")
                    
        if correct_intents:
            for ci in correct_intents:
                try:
                    service = get_sheets_service()
                    res = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range='記帳!A:H').execute()
                    rows = res.get('values', [])
                    last_row_index = len(rows)
                    if last_row_index > 1:
                        deleted_data = rows[-1]
                        service.spreadsheets().values().clear(spreadsheetId=SPREADSHEET_ID, range=f'記帳!A{last_row_index}:H{last_row_index}').execute()
                        item = "未知"
                        if len(deleted_data) > 3 and deleted_data[3]:
                            item = deleted_data[3]
                        elif len(deleted_data) > 4 and deleted_data[4]:
                            item = deleted_data[4]
                        amt = deleted_data[5] if len(deleted_data) > 5 else "0"
                        
                        success_messages.append(f"🗑️ 已幫您刪除最後一筆記帳資料：「{item} ${amt}」。")
                    else:
                        success_messages.append("⚠️ 目前記帳表中沒有資料可以刪除。")
                except Exception as e:
                    error_messages.append(f"❌ 修正舊資料失敗：{str(e)}")
                    
        for other in others:
            itype = other.get('type')
            if itype == 'chat':
                success_messages.append(other.get('reply', '收到！'))
            elif itype == 'query_expense_report':
                try:
                    service = get_sheets_service()
                    _, cat_report, cat_dict, _ = get_monthly_report(service, now)
                    success_messages.append(f"📊 本月結算：\n\n{cat_report}")
                    chart_data = cat_dict
                except Exception as e:
                    error_messages.append(f"❌ 查詢報表失敗：{str(e)}")
            else:
                success_messages.append(f"已處理意圖類型「{itype}」。")
                
        final_msg_parts = []
        if ai_response_message:
            final_msg_parts.append(ai_response_message)
        if success_messages:
            final_msg_parts.append("\n".join(success_messages))
        if error_messages:
            if final_msg_parts:
                final_msg_parts.append("\n⚠️ 部分項目處理失敗：")
            final_msg_parts.append("\n".join(error_messages))
            
        final_msg = "\n\n".join(final_msg_parts)
        if has_charity:
            sub_type = session.get('subscription_type', 'NONE')
            if os.getenv("SINGLE_USER_MODE", "false").lower() == "true" or sub_type != 'NONE' or email.lower() in developer_emails:
                final_msg += "<br><br><button onclick='window.triggerChatReceiptUpload()' style='padding: 12px 20px; border-radius: 16px; border: none; background: linear-gradient(135deg, #f43f5e 0%, #e11d48 100%); color: white; font-weight: 800; font-size: 0.9rem; cursor: pointer; box-shadow: 0 4px 15px rgba(225, 29, 72, 0.3); display: flex; align-items: center; justify-content: center; gap: 8px; margin: 10px 0;'>📸 立即拍照上傳收據</button>"
            else:
                final_msg += "<br><br><span style='color: #64748b; font-size: 0.85rem; display: block; border-top: 1px dashed #e2e8f0; padding-top: 10px;'>💡 升級為 <b>尊榮付費會員</b>，即可解鎖「發票收據自動命名歸檔」與「雲端年度報稅管理」特權，五月申報免煩惱！</span>"
                
        
        resp_obj = jsonify({
            "status": "success" if not error_messages else "partial_error",
            "type": "batch",
            "message": final_msg,
            "chart_data": chart_data
        })
    else:
        # 單一處理模式
        if isinstance(parsed_data, dict):
            for k in ["response", "reply", "message"]:
                if k in parsed_data:
                    ai_response_message = parsed_data.pop(k, None)
            if "data" in parsed_data and isinstance(parsed_data["data"], dict):
                nested_data = parsed_data.pop("data")
                for k in ["response", "reply", "message"]:
                    if k in nested_data and not ai_response_message:
                        ai_response_message = nested_data.pop(k)
                parsed_data.update(nested_data)
                
        try:
            response_obj = execute_single_intent_internal(parsed_data, email, now, ai_response_message, user_text=user_text)
            is_success = 1
            try:
                resp_data = json.loads(response_obj.get_data(as_text=True))
                if resp_data.get("status") == "error":
                    is_success = 0
            except Exception:
                pass
            resp_obj = response_obj
        except Exception as e:
            print(f"API 執行錯誤: {e}")
            resp_obj = jsonify({"status": "error", "message": f"執行時發生錯誤：{str(e)}"})

    if session.pop('ai_fallback_warning', False) and resp_obj:
        try:
            resp_data = json.loads(resp_obj.get_data(as_text=True))
            if "message" in resp_data:
                resp_data["message"] += "\n\n💡 (目前伺服器連線忙碌中，已為您自動啟用本地規則完成記帳，您的資料已安全儲存！)"
                resp_obj = jsonify(resp_data)
        except Exception as e:
            print(f"Error appending fallback warning: {e}")
            
    return resp_obj

def execute_single_intent_internal(parsed_data, email, now, ai_response_message=None, user_text=None):
    intent_type = parsed_data.get("type") if isinstance(parsed_data, dict) else None
    developer_emails = {'ulir976272866@gmail.com', 'mina.chen.xstar.sg@gmail.com'}
    
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
        is_income = parsed_data.get('expense_type') == 'income'
        category = parsed_data.get('category')
        sub_category = normalize_sub_category(category, parsed_data.get('sub_category', ''), is_income)
        parsed_data['sub_category'] = sub_category
        amount = int(parsed_data.get('amount') or 0)
        item = parsed_data.get('item')
        
        body = {'values': [[
            str(now.year), 
            f"'{now.month:02d}", 
            now.strftime("%Y/%m/%d"), 
            item if is_income else "", 
            "" if is_income else item, 
            amount, 
            format_category_with_emoji(category, is_income),
            sub_category
        ]]}
        
        append_res = service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID, 
            range='記帳!A:H', 
            valueInputOption='USER_ENTERED', 
            body=body
        ).execute()
        
        updated_range = append_res.get('updates', {}).get('updatedRange', '')
        row_num = None
        import re
        match = re.search(r'A(\d+):', updated_range)
        if match:
            row_num = int(match.group(1))

            
        _, cat_report, cat_dict, _ = get_monthly_report(service, now)
        emoji = "💰" if is_income else "💸"
        label = "收入" if is_income else "支出"
        msg = f"{emoji} 已記{label}：{item} ${amount}\n\n{cat_report}"
        if ai_response_message:
            msg = f"{ai_response_message}\n\n{msg}"
            
        # 連動資產餘額邏輯 (V3.8 Step 3)
        if category == '儲蓄/投資' and row_num:
            try:
                ensure_user_spreadsheet()
                res_accts = service.spreadsheets().values().get(
                    spreadsheetId=SPREADSHEET_ID,
                    range='資產帳戶!A:F'
                ).execute()
                rows_accts = res_accts.get('values', [])
                accounts = []
                if len(rows_accts) > 1:
                    for idx_a, row_a in enumerate(rows_accts[1:]):
                        while len(row_a) < 6:
                            row_a.append('')
                        try:
                            bal_a = int(float(row_a[2])) if row_a[2] else 0
                        except ValueError:
                            bal_a = 0
                        accounts.append({
                            "name": row_a[0].strip(),
                            "type": row_a[1].strip(),
                            "balance": bal_a,
                            "id": row_a[3].strip(),
                            "updated_time": row_a[4].strip(),
                            "remark": row_a[5].strip()
                        })
                
                candidates = []
                user_text_clean = (user_text or "").lower()
                item_clean = (item or "").lower()
                sub_cat_clean = (sub_category or "").lower()
                
                for acct in accounts:
                    acct_name = acct['name'].lower()
                    if acct_name in user_text_clean or acct_name in item_clean or acct_name in sub_cat_clean:
                        candidates.append(acct)
                    elif (item_clean and item_clean in acct_name) or (sub_cat_clean and sub_cat_clean in acct_name):
                        if len(item_clean) >= 2 or len(sub_cat_clean) >= 2:
                            candidates.append(acct)
                    else:
                        for keyword in ["國泰", "郵局", "玉山", "緊急備用金", "備用金", "現金", "口袋", "交割戶"]:
                            if keyword in acct_name and (keyword in user_text_clean or keyword in item_clean):
                                if acct not in candidates:
                                    candidates.append(acct)
                
                amount_change = -amount if is_income else amount
                
                if len(candidates) == 1:
                    current_time = datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M:%S')
                    acct_name, old_bal, new_bal = update_linked_asset_balance(
                        service, SPREADSHEET_ID, candidates[0]['id'], amount_change, current_time
                    )
                    msg += f"\n\n🏦 (已自動連動更新「{acct_name}」餘額：{old_bal:,} → {new_bal:,})"
                elif len(candidates) > 1:
                    buttons_html = []
                    for c in candidates:
                        btn_text = f"🏦 {c['name']}" if c['type'] == '活儲' else (f"📉 {c['name']}" if c['type'] == '貸款' or '信貸' in c['name'] else f"💰 {c['name']}")
                        buttons_html.append(
                            f'<button onclick="window.linkTransactionToAsset({row_num}, \'{c["id"]}\', {amount_change}, this)" class="disambiguation-btn" style="padding: 6px 12px; border-radius: 12px; border: 1px solid #e2e8f0; background: #fff; color: #1e293b; font-size: 0.8rem; font-weight: 700; cursor: pointer; transition: all 0.2s;">{btn_text}</button>'
                        )
                    buttons_html.append(
                        f'<button onclick="window.linkTransactionToAsset({row_num}, \'\', 0, this)" class="disambiguation-btn" style="padding: 6px 12px; border-radius: 12px; border: 1px solid #e2e8f0; background: #f1f5f9; color: #64748b; font-size: 0.8rem; font-weight: 700; cursor: pointer; transition: all 0.2s;">✕ 暫不連動</button>'
                    )
                    
                    card_html = f"""<br><br>
<div class="disambiguation-card" style="padding: 12px; background: rgba(148, 163, 184, 0.05); border: 1px solid #e2e8f0; border-radius: 16px;">
    <div style="font-size: 0.85rem; color: #64748b; margin-bottom: 8px; font-weight: 700;">💬 偵測到多個匹配的帳戶，請問這筆金額要連動到？</div>
    <div style="display: flex; flex-wrap: wrap; gap: 6px;" id="disambiguation-buttons-{row_num}">
        {" ".join(buttons_html)}
    </div>
</div>
"""
                    msg += card_html
            except Exception as ex:
                print(f"Chat Linking Balance Error: {ex}")
                msg += f"\n\n⚠️ 動態連動帳戶餘額失敗：{str(ex)}"
            
        if parsed_data.get('category') in ['公益', '宗教/公益']:
            sub_type = session.get('subscription_type', 'NONE')
            if os.getenv("SINGLE_USER_MODE", "false").lower() == "true" or sub_type != 'NONE' or email.lower() in developer_emails:
                msg += "<br><br><button onclick='window.triggerChatReceiptUpload()' style='padding: 12px 20px; border-radius: 16px; border: none; background: linear-gradient(135deg, #f43f5e 0%, #e11d48 100%); color: white; font-weight: 800; font-size: 0.9rem; cursor: pointer; box-shadow: 0 4px 15px rgba(225, 29, 72, 0.3); display: flex; align-items: center; justify-content: center; gap: 8px; margin: 10px 0;'>📸 立即拍照上傳收據</button>"
            else:
                msg += "<br><br><span style='color: #64748b; font-size: 0.85rem; display: block; border-top: 1px dashed #e2e8f0; padding-top: 10px;'>💡 升級為 <b>尊榮付費會員</b>，即可解鎖「發票收據自動命名歸檔」與「雲端年度報稅管理」特權，五月申報免煩惱！</span>"
        return jsonify({"status": "success", "type": "expense", "message": msg, "chart_data": cat_dict})

    elif intent_type == "correct_intent":
        service = get_sheets_service()
        res = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range='記帳!A:H').execute()
        rows = res.get('values', [])
        last_row_index = len(rows)
        if last_row_index > 1:
            deleted_data = rows[-1]
            service.spreadsheets().values().clear(spreadsheetId=SPREADSHEET_ID, range=f'記帳!A{last_row_index}:H{last_row_index}').execute()
            item = "未知"
            if len(deleted_data) > 3 and deleted_data[3]:
                item = deleted_data[3]
            elif len(deleted_data) > 4 and deleted_data[4]:
                item = deleted_data[4]
            amt = deleted_data[5] if len(deleted_data) > 5 else "0"
            
            msg = f"🗑️ 已幫您刪除最後一筆記帳資料：「{item} ${amt}」。請您重新輸入正確的記帳內容！"
            if ai_response_message:
                msg = f"{ai_response_message}\n\n{msg}"
            return jsonify({"status": "success", "type": "chat", "message": msg})
        else:
            return jsonify({"status": "success", "type": "chat", "message": "⚠️ 目前記帳表中沒有資料可以刪除。"})

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
        return jsonify({"status": "success", "type": "query_stock_portfolio", "message": report_text})

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
            
        if sub_type not in ['YEARLY_AI', 'PREMIUM_MONTHLY'] and user_email not in developer_emails:
            return jsonify({
                "status": "success",
                "type": "stock_locked",
                "message": "🔒 「智慧股票投資記帳」為尊榮旗艦版獨享功能，請升級後體驗語音智慧自動填單功能喔！"
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

    elif intent_type == "query_bill_splits":
        spreadsheet_id = get_spreadsheet_id()
        if not spreadsheet_id:
            return jsonify({"status": "error", "message": "尚未設定 GOOGLE_SHEET_ID"})
        rows = get_sheet_values('代墊待收款', spreadsheet_id=spreadsheet_id)
        data_list = []
        if rows and len(rows) > 1:
            for row in rows[1:]:
                while len(row) < 9:
                    row.append('')
                data_list.append({
                    "date": row[0],
                    "description": row[1],
                    "total_amount": row[2],
                    "payer": row[3],
                    "friends": row[4].split(',') if row[4] else [],
                    "breakdown": json.loads(row[5]) if row[5] else {},
                    "status": row[6],
                    "id": row[7],
                    "time": row[8]
                })
        data_list.reverse()
        return jsonify({
            "status": "success",
            "type": "query_bill_splits",
            "data": data_list,
            "message": "已為您查詢到最新的代墊款清單："
        })

    elif intent_type == "chat":
        return jsonify({
            "status": "success",
            "type": "chat",
            "message": parsed_data.get("reply", "收到！")
        })
    else:
        return jsonify({"status": "error", "message": "我不確定該怎麼處理這個指令。"})

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

def parse_tx_date(date_str):
    try:
        # e.g., "2026/06/12" or "2026-06-12"
        date_str = str(date_str).replace('/', '-')
        parts = date_str.split(' ')[0].split('-')
        if len(parts) >= 2:
            return int(parts[0]), int(parts[1])
    except:
        pass
    return None, None

@app.route('/api/finance_report/available_dates', methods=['GET'])
def get_finance_report_available_dates():
    try:
        spreadsheet_id = get_spreadsheet_id()
        if not spreadsheet_id:
            return jsonify({"status": "error", "message": "尚未連結試算表"}), 400
            
        service = get_sheets_service()
        try:
            # 讀取「記帳」的 A 和 B 欄 (年度與月份)
            range_name = "'記帳'!A:B"
            rows_result = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=range_name
            ).execute()
            rows = rows_result.get('values', [])
        except Exception as e:
            return jsonify({"status": "error", "message": f"讀取試算表失敗: {str(e)}"}), 500
            
        if not rows or len(rows) < 2:
            # 返回當前年份和月份作為備用
            now = datetime.now(TW_TZ)
            return jsonify({
                "status": "success",
                "dates": {
                    now.strftime('%Y'): [now.strftime('%m')]
                }
            })
            
        # 尋找「年度」與「月份」的欄位索引
        header = [str(x).strip() for x in rows[0]]
        def find_col(possible_names):
            for name in possible_names:
                for idx, h in enumerate(header):
                    if name in h:
                        return idx
            return -1
            
        year_idx = find_col(['年度'])
        month_idx = find_col(['月份'])
        
        if year_idx == -1: year_idx = 0
        if month_idx == -1: month_idx = 1
        
        dates_dict = {} # { "2026": ["05", "06"] }
        
        for row in rows[1:]:
            if len(row) <= max(year_idx, month_idx):
                continue
            r_year = str(row[year_idx]).replace("'", "").strip()
            r_month = str(row[month_idx]).replace("'", "").strip()
            if r_year.isdigit() and r_month.isdigit():
                y_str = str(int(r_year))
                m_str = str(int(r_month)).zfill(2)
                
                if y_str not in dates_dict:
                    dates_dict[y_str] = set()
                dates_dict[y_str].add(m_str)
                
        # 轉成 sorted list
        sorted_dates = {}
        for y in sorted(dates_dict.keys(), reverse=True):
            sorted_dates[y] = sorted(list(dates_dict[y]))
            
        # 若完全無效，預設當前
        if not sorted_dates:
            now = datetime.now(TW_TZ)
            sorted_dates = {now.strftime('%Y'): [now.strftime('%m')]}
            
        return jsonify({
            "status": "success",
            "dates": sorted_dates
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/finance_report', methods=['GET', 'POST'])
def get_finance_report():
    try:
        if request.method == 'POST' and request.is_json:
            data = request.json or {}
            year = data.get('year')
            month = data.get('month')
        else:
            year = request.args.get('year')
            month = request.args.get('month')
            
        if not year or not month:
            return jsonify({"status": "error", "message": "缺少年份或月份參數"}), 400
            
        year = int(year)
        month = int(month)
        
        spreadsheet_id = get_spreadsheet_id()
        if not spreadsheet_id:
            return jsonify({"status": "error", "message": "尚未連結試算表"}), 400
            
        service = get_sheets_service()
        try:
            # 讀取單一的「記帳」分頁資料
            range_name = "'記帳'!A:I"
            rows_result = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=range_name
            ).execute()
            rows = rows_result.get('values', [])
        except Exception as e:
            return jsonify({ "status": "error", "message": f"讀取試算表失敗: {str(e)}" })
            
        if not rows or len(rows) < 1:
            return jsonify({ "status": "no_data", "message": "該月份尚無記帳資料" })
            
        header = [str(x).strip() for x in rows[0]]
        
        def find_col(possible_names):
            for name in possible_names:
                for idx, h in enumerate(header):
                    if name in h:
                        return idx
            return -1
            
        year_idx = find_col(['年度'])
        month_idx = find_col(['月份'])
        date_idx = find_col(['日期', '時間'])
        inc_item_idx = find_col(['收入項目'])
        exp_item_idx = find_col(['支出項目'])
        cat_idx = find_col(['母分類', '類別', '主分類', '項目分類'])
        subcat_idx = find_col(['子分類', '子類別'])
        amt_idx = find_col(['金額', '數值', '價格'])
        note_idx = find_col(['備註', '項目', '說明', '內容'])
        
        # 兜底欄位索引 (若 header 不匹配)
        if year_idx == -1: year_idx = 0
        if month_idx == -1: month_idx = 1
        if date_idx == -1: date_idx = 2
        if inc_item_idx == -1: inc_item_idx = 3
        if exp_item_idx == -1: exp_item_idx = 4
        if amt_idx == -1: amt_idx = 5
        if cat_idx == -1: cat_idx = 6
        if subcat_idx == -1: subcat_idx = 7
        if note_idx == -1: note_idx = 8
            
        total_expense = 0.0
        total_income = 0.0
        category_totals = {}
        subcategory_breakdowns = {}
        income_categories = {}  # 收入項目彙總
        has_matched_data = False
        
        for row in rows[1:]:
            if len(row) <= max(year_idx, month_idx):
                continue
                
            try:
                r_year = str(row[year_idx]).replace("'", "").strip()
                r_month = str(row[month_idx]).replace("'", "").strip()
                
                if not r_year or not r_month:
                    continue
                
                # 比對年份與月份
                is_year_match = r_year == str(year)
                is_month_match = (r_month.zfill(2) == str(month).zfill(2)) or (str(int(r_month)) == str(int(month)))
                
                if not (is_year_match and is_month_match):
                    continue
            except Exception:
                continue
                
            if len(row) <= amt_idx:
                continue
                
            try:
                amt_str = str(row[amt_idx]).replace(',', '').strip()
                if not amt_str:
                    continue
                amt = float(amt_str)
                
                # 依據收入欄位是否有值判定收支類型
                is_income = len(row) > inc_item_idx and str(row[inc_item_idx]).strip() != ""
                
                has_matched_data = True
                
                if is_income:
                    total_income += amt
                    # 收入項目名稱彙總
                    inc_name = str(row[inc_item_idx]).strip() if len(row) > inc_item_idx else "其他收入"
                    if not inc_name:
                        inc_name = "其他收入"
                    income_categories[inc_name] = income_categories.get(inc_name, 0.0) + amt
                else:
                    total_expense += amt
                    cat = str(row[cat_idx]).strip() if len(row) > cat_idx else "未分類"
                    subcat = str(row[subcat_idx]).strip() if (len(row) > subcat_idx and str(row[subcat_idx]).strip()) else "一般"
                    
                    category_totals[cat] = category_totals.get(cat, 0.0) + amt
                    if cat not in subcategory_breakdowns:
                        subcategory_breakdowns[cat] = {}
                    subcategory_breakdowns[cat][subcat] = subcategory_breakdowns[cat].get(subcat, 0.0) + amt
            except:
                continue
                
        if not has_matched_data:
            return jsonify({ "status": "no_data", "message": f"該月份 ({year}-{str(month).zfill(2)}) 尚無記帳資料" })
                
            
        # 尊榮旗艦版股票概覽
        is_premium = is_premium_user()
        stock_expense = 0.0
        stock_unrealized_roi = 0.0
        stock_realized_roi = 0.0
        
        if is_premium:
            try:
                ensure_stock_sheet_exists(spreadsheet_id)
                stock_rows = get_sheet_values('💰股票投資組合', spreadsheet_id=spreadsheet_id)
                
                if stock_rows and len(stock_rows) >= 2:
                    portfolio = {}
                    for row in stock_rows[1:]:
                        if len(row) < 7 or not row[1].strip():
                            continue
                        date_val = row[0].strip()
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
                        tx_roi = 0.0
                        if len(row) > 7 and row[7]:
                            try:
                                live_price = float(str(row[7]).replace(',', '').strip())
                            except:
                                pass
                        if len(row) > 8 and row[8]:
                            try:
                                tx_roi = float(str(row[8]).replace(',', '').strip())
                            except:
                                pass
                                
                        # 統計本月買進支出
                        tx_year, tx_month = parse_tx_date(date_val)
                        if tx_year == year and tx_month == month:
                            if tx_type == "買進":
                                stock_expense += (shares * price + fee)
                                
                        if ticker not in portfolio:
                            portfolio[ticker] = {
                                "ticker": ticker,
                                "name": name,
                                "net_shares": 0.0,
                                "total_cost": 0.0,
                                "live_price": 0.0,
                                "realized_pnl": 0.0,
                                "dividends": 0.0
                            }
                        p = portfolio[ticker]
                        if tx_type == "買進":
                            p["net_shares"] += shares
                            p["total_cost"] += (shares * price + fee)
                        elif tx_type == "賣出":
                            if p["net_shares"] > 0:
                                avg_buy_cost = p["total_cost"] / p["net_shares"]
                                cost_of_sold = shares * avg_buy_cost
                                revenue_from_sold = shares * price - fee
                                realized = revenue_from_sold - cost_of_sold
                                p["realized_pnl"] += realized
                                p["net_shares"] -= shares
                                p["total_cost"] -= cost_of_sold
                                if p["net_shares"] <= 0.001:
                                    p["net_shares"] = 0.0
                                    p["total_cost"] = 0.0
                            else:
                                p["realized_pnl"] += (shares * price - fee)
                        elif tx_type in ["股息", "配息"]:
                            dividend_amt = price * (shares if shares > 0 else 1.0)
                            p["dividends"] += dividend_amt
                        if live_price > 0:
                            p["live_price"] = live_price
                            
                    total_unrealized_roi = 0.0
                    total_realized_pnl = 0.0
                    total_dividends = 0.0
                    
                    for t, p in portfolio.items():
                        total_dividends += p.get("dividends", 0.0)
                        total_realized_pnl += p.get("realized_pnl", 0.0)
                        if p["net_shares"] > 0.001:
                            if p["live_price"] <= 0:
                                # Fallback to last known tx price
                                pass
                            current_value = p["net_shares"] * p["live_price"]
                            unrealized_roi = current_value - p["total_cost"]
                            total_unrealized_roi += unrealized_roi
                            
                    stock_unrealized_roi = total_unrealized_roi
                    stock_realized_roi = total_realized_pnl + total_dividends
            except Exception as se:
                print(f"[Finance Report] Stock portfolio processing error: {se}")
                
        return jsonify({
            "status": "success",
            "year": year,
            "month": month,
            "total_expense": round(total_expense, 2),
            "total_income": round(total_income, 2),
            "balance": round(total_income - total_expense, 2),
            "categories": {k: round(v, 2) for k, v in category_totals.items()},
            "subcategories": {cat: {sub: round(val, 2) for sub, val in subs.items()} for cat, subs in subcategory_breakdowns.items()},
            "income_categories": {k: round(v, 2) for k, v in income_categories.items()},
            "is_premium": is_premium,
            "stock_expense": round(stock_expense, 2),
            "stock_unrealized_roi": round(stock_unrealized_roi, 2),
            "stock_realized_roi": round(stock_realized_roi, 2)
        })
    except Exception as ex:
        return jsonify({"status": "error", "message": f"產生報表時發生錯誤：{str(ex)}"}), 500


def get_schedule_response(days):
    """查詢當前與未來行程的共通回傳格式"""
    now = datetime.now(TW_TZ)
    try:
        service = get_calendar_service()
        today_start = datetime.combine(now.date(), time.min, tzinfo=TW_TZ).isoformat()
        end_date = now + timedelta(days=days-1)
        today_end = datetime.combine(end_date.date(), time.max, tzinfo=TW_TZ).isoformat()
        
        current_cal_id = session.get('calendar_id', 'primary')

        # 動態計算 maxResults 限制，防止大量行程被截斷（例如 1天限30筆，30天限300筆）
        max_results_limit = max(30, days * 10)
        events_result = service.events().list(
            calendarId=current_cal_id, timeMin=today_start, timeMax=today_end,
            maxResults=max_results_limit, singleEvents=True, orderBy='startTime'
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

def update_linked_asset_balance(service, spreadsheet_id, asset_account_id, amount_change, current_time):
    """
    Updates the balance of the target asset account in '資產帳戶' sheet.
    amount_change can be positive or negative.
    """
    res = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range='資產帳戶!A:F'
    ).execute()
    rows = res.get('values', [])
    
    target_row_num = -1
    target_row = None
    for idx, row in enumerate(rows[1:]):
        row_num = idx + 2
        while len(row) < 6:
            row.append('')
        if row[3].strip() == asset_account_id:
            target_row_num = row_num
            target_row = row
            break
            
    if target_row_num == -1 or not target_row:
        raise ValueError(f"找不到對應的資產帳戶 ID: {asset_account_id}")
        
    try:
        old_balance = int(float(target_row[2])) if target_row[2] else 0
    except ValueError:
        old_balance = 0
        
    new_balance = old_balance + amount_change
    
    target_row[2] = str(new_balance)
    target_row[4] = current_time # update time
    
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f'資產帳戶!A{target_row_num}:F{target_row_num}',
        valueInputOption='USER_ENTERED',
        body={'values': [target_row]}
    ).execute()
    
    return target_row[0], old_balance, new_balance

@app.route('/api/link_transaction_asset', methods=['POST'])
def link_transaction_asset():
    """
    對話記帳歧義卡片點擊後，連動更新指定資產帳戶的餘額
    """
    spreadsheet_id = get_spreadsheet_id()
    if not spreadsheet_id:
        return jsonify({"status": "error", "message": "尚未設定 GOOGLE_SHEET_ID"}), 400
        
    data = request.json or {}
    row_num = data.get('row_num')
    asset_account_id = data.get('asset_account_id')
    amount_change = data.get('amount_change')
    
    if not row_num or not asset_account_id or amount_change is None:
        return jsonify({"status": "success", "message": "已設定為不連動資產帳戶！"})
        
    try:
        service = get_sheets_service()
        # 讀取該列，確認記帳明細是否存在
        res = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f'記帳!A{row_num}:H{row_num}'
        ).execute()
        rows = res.get('values', [])
        if not rows:
            return jsonify({"status": "error", "message": "找不到對應的記帳記錄，可能已被刪改"}), 404
            
        current_time = datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M:%S')
        acct_name, old_bal, new_bal = update_linked_asset_balance(
            service, spreadsheet_id, asset_account_id, amount_change, current_time
        )
        
        return jsonify({
            "status": "success",
            "message": f"✅ 已成功為您連動更新「{acct_name}」餘額！\n💰 {old_bal:,} → {new_bal:,}"
        })
    except Exception as e:
        print(f"link_transaction_asset Error: {e}")
        return jsonify({"status": "error", "message": f"連動失敗：{str(e)}"}), 500

@app.route('/api/manual_action', methods=['POST'])
def manual_action():
    """
    接收來自前端 Modal 的手動輸入，直接執行動作，完全不經過 AI。
    """
    data = request.get_json()
    print("[DEBUG MANUAL ACTION] Incoming payload:", data)
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
            # A:Year, B:Month, C:Date, D:IncomeItem, E:ExpenseItem, F:Amount, G:Category, H:SubCategory
            is_income = data.get('expense_type') == 'income'
            sub_category = data.get('sub_category', '').strip()
            category = data.get('category', '').strip()
            amount = int(data.get('amount') or 0)
            asset_account_id = data.get('asset_account_id')
            
            values = [[
                now.strftime('%Y'), 
                f"'{now.strftime('%m')}", 
                now.strftime('%Y/%m/%d'), 
                data.get('item') if is_income else "", # 收入項目
                "" if is_income else data.get('item'), # 支出項目
                amount, 
                format_category_with_emoji(category, is_income),
                sub_category
            ]]
            body = {'values': values}
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range='記帳!A:H',
                valueInputOption='USER_ENTERED',
                body=body
            ).execute()
            
            # 連動資產餘額邏輯 (V3.8 Step 3)
            asset_log = ""
            if category == '儲蓄/投資' and asset_account_id:
                try:
                    amount_change = -amount if is_income else amount
                    current_time = datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M:%S')
                    acct_name, old_bal, new_bal = update_linked_asset_balance(
                        service, SPREADSHEET_ID, asset_account_id, amount_change, current_time
                    )
                    asset_log = f"\n🏦 (已連動更新「{acct_name}」餘額：{old_bal:,} → {new_bal:,})"
                except Exception as ex:
                    print(f"Update Linked Asset Balance Error: {ex}")
                    asset_log = f"\n⚠️ 連動更新帳戶餘額失敗：{str(ex)}"

            # 呼叫小助手計算本月總額
            monthly_total, cat_report, cat_dict, monthly_income = get_monthly_report(service, now)

            return jsonify({
                "status": "success", 
                "message": f"💰 手動記帳成功：{data.get('item')} ${amount}{asset_log}\n\n{cat_report}",
                "chart_data": cat_dict
            })

    except Exception as e:
        print(f"Manual Action Error: {e}")
        return jsonify({"status": "error", "message": f"執行失敗：{str(e)}"}), 500

    return jsonify({"status": "error", "message": "未知的動作類型"}), 400

# =================================================================
# 💸 代墊款智慧拆帳 API (V3.7 Step 4)
# =================================================================

@app.route('/api/bill_split/parse', methods=['POST'])
def parse_bill_split():
    """
    使用 AI 解析自然語言，產出拆帳項目、我的份額、以及朋友分攤明細的結構化 JSON
    """
    data = request.json or {}
    text = data.get('text', '').strip()
    friends = data.get('friends', [])
    
    if not text:
        return jsonify({"status": "error", "message": "請輸入拆帳說明內文"}), 400
        
    if not GEMINI_API_KEY:
        return jsonify({"status": "error", "message": "尚未設定 API Key"}), 400

    now = datetime.now(TW_TZ)
    friends_str = "、".join(friends) if friends else "無指定（請從內文判斷朋友並對齊）"
    
    prompt = f"""
    你是一個精明的代墊款拆帳助理，現在時間是 {now.strftime('%Y-%m-%d %H:%M:%S')}。
    你的任務是解析使用者輸入的複雜「代墊/幫付/我先付」等拆帳場景，並將其轉化為精確的結構化 JSON。

    使用者指定的朋友姓名列表（若無指定，請自行從內文提取，或代表為「朋友1」、「朋友2」等，且優先匹配並保持前後一致）：
    {friends_str}

    請仔細閱讀使用者的原始文字：
    「{text}」

    【解析與分攤規則】：
    1. 提取所有可能的費用項目名稱（如「去程火車票」、「回程火車」、「Uber」等）。
    2. 判斷該交易整體的消費主體類別（category），且必須是以下清單之一：
       ["食", "衣", "住", "行", "育", "樂", "醫", "保險費", "貸款", "儲蓄/投資", "宗教/公益", "未分類"]
       （例如：火車、計程車、機票選「行」；吃飯、外送選「食」；看電影、買遊戲選「樂」；看醫生選「醫」；房租選「住」等等）。
    3. 對於每一筆費用項目，計算：
       - 項目名稱（name）
       - 該項目總金額（total_amount，必須是數值，可以包含小數或整數）
       - 分攤人數說明（split_description，例如「3人均分」、「自己」、「他們」）
       - 我的份額（my_share，表示我自己應負擔的份額。如果是均分項目，為 總金額 / 總人數；如果是專屬我的費用，為該項總額；如果是專屬別人的費用，為 0）
       - 朋友的份額總和（friends_share，表示其他人負擔的總和）
       - 各別成員分攤明細（breakdown，一個字典，鍵為成員姓名，值為該成員負擔金額。注意：只列出除了「自己」之外的其他人！如果使用者指定了朋友名單，優先用指定的名字，否則用內文提及的名字，或者「朋友1」、「朋友2」等）
    4. 計算總金額加總：
       - 我的總支出（my_total_expense）：所有項目我自己應負擔的份額（my_share）之和。
       - 代墊待收款總額（friends_total_receivable）：所有項目中朋友應負擔的份額（friends_share）總和，即別人欠我的錢。
       - 朋友分攤總明細（friend_breakdown）：一個字典，鍵為朋友姓名，值為該朋友累計應歸還我的金額總和。
    5. 狀態判定（status）：
       - 如果幾乎所有項目都成功解析，且數字加總完全對齊吻合，狀態回傳 "success"。
       - 如果有些項目有金額但不確定分攤人數或分攤人，或者少數資訊無法解析，狀態回傳 "partial"。
       - 如果完全無法解析出有意義的費用，狀態回傳 "failed"。

    【回傳格式】：
    請只回傳一個 JSON 物件，格式如下，不要包含 markdown (如 ```json) 或 any 額外文字：
    {{
      "status": "success", 
      "category": "該交易整體的消費主體類別",
      "items": [
        {{
          "name": "項目名稱",
          "total_amount": 項目總金額,
          "split_description": "分攤說明",
          "my_share": 我的份額,
          "friends_share": 朋友份額總和,
          "breakdown": {{
            "朋友姓名1": 朋友1應分攤金額,
            "朋友姓名2": 朋友2應分攤金額
          }}
        }}
      ],
      "my_total_expense": 我的總支出金額,
      "friends_total_receivable": 代墊待收款總額,
      "friend_breakdown": {{
        "朋友姓名1": 朋友1應歸還總金額,
        "朋友姓名2": 朋友2應歸還總金額
      }}
    }}
    """
    
    try:
        model = genai.GenerativeModel('gemini-3.1-flash-lite')
        response = model.generate_content([prompt])
        text_reply = response.text.replace('```json', '').replace('```', '').strip()
        parsed = json.loads(text_reply)
        
        # 進行基本的欄位防呆確保
        if 'status' not in parsed: parsed['status'] = 'success'
        if 'category' not in parsed: parsed['category'] = '未分類'
        if 'items' not in parsed: parsed['items'] = []
        if 'my_total_expense' not in parsed: parsed['my_total_expense'] = 0
        if 'friends_total_receivable' not in parsed: parsed['friends_total_receivable'] = 0
        if 'friend_breakdown' not in parsed: parsed['friend_breakdown'] = {}
        
        return jsonify(parsed)
    except Exception as e:
        print(f"[AI Bill Split Parse Error] {e}")
        return jsonify({
            "status": "failed",
            "message": f"AI 解析出錯: {str(e)}",
            "items": [],
            "my_total_expense": 0,
            "friends_total_receivable": 0,
            "friend_breakdown": {}
        })

@app.route('/api/bill_splits', methods=['GET'])
def get_bill_splits():
    """
    獲取使用者所有的「待收/部分收回」代墊拆帳清單
    """
    spreadsheet_id = get_spreadsheet_id()
    if not spreadsheet_id:
        return jsonify({"status": "error", "message": "尚未設定 GOOGLE_SHEET_ID"}), 400
        
    try:
        rows = get_sheet_values('代墊待收款', spreadsheet_id=spreadsheet_id)
        if not rows or len(rows) <= 1:
            return jsonify({"status": "success", "data": []})
            
        data_list = []
        # 表頭：'建立日期', '帳目描述', '總金額', '墊款人', '分攤人(逗號分隔)', '各分攤明細(JSON/描述)', '狀態', '唯一 ID', '建立時間'
        for idx, row in enumerate(rows[1:]):
            while len(row) < 9:
                row.append('')
            
            # 若為已結清或已收回，則不顯示在清單中
            if row[6] in ['已結清', '已收回']:
                continue
                
            try:
                breakdown = json.loads(row[5])
            except Exception as json_err:
                # 容錯處理：如果不是 JSON，將其當作字串，或者預設空字典
                breakdown = {}
                
            data_list.append({
                "date": row[0],
                "description": row[1],
                "total_amount": row[2],
                "payer": row[3],
                "friends": row[4],
                "breakdown": breakdown,
                "status": row[6],
                "id": row[7],
                "time": row[8]
            })
            
        # 照時間降序排列 (最新在最上面)
        data_list.reverse()
        return jsonify({"status": "success", "data": data_list})
    except Exception as e:
        print(f"[GET Bill Splits Error] {e}")
        return jsonify({"status": "error", "message": f"載入清單失敗: {str(e)}"}), 500

@app.route('/api/bill_split/save', methods=['POST'])
def save_bill_split():
    """
    確認代墊拆帳 (Flow B - 完整流水分攤制)：
    1. 寫入「代墊待收款」分頁 (狀態：待收，分攤明細 JSON 附帶分類儲存)
    2. 自動在「記帳」分頁新增一筆該項目的「總代墊金額」(無條件進位，分類為真實分類，子分類為使用者選定或拆帳分攤)
    """
    spreadsheet_id = get_spreadsheet_id()
    if not spreadsheet_id:
        return jsonify({"status": "error", "message": "尚未設定 GOOGLE_SHEET_ID"}), 400
        
    data = request.json or {}
    description = data.get('description', '').strip()
    total_amount = data.get('total_amount', 0)
    friends = data.get('friends', [])
    breakdown = data.get('breakdown', {})
    my_expense = data.get('my_expense', 0)
    category = data.get('category', '').strip() or '未分類'
    sub_category = data.get('sub_category', '').strip() or '拆帳分攤'
    
    if not description or not breakdown:
        return jsonify({"status": "error", "message": "描述或分攤明細不能為空"}), 400
        
    try:
        service = get_sheets_service()
        now = datetime.now(TW_TZ)
        unique_id = str(uuid.uuid4())
        
        # 1. 寫入「代墊待收款」
        # 額外在 breakdown JSON 中儲存真實分類與子分類，便於還款時精準記為該分類下的「負值支出」
        breakdown['_category'] = category
        breakdown['_sub_category'] = sub_category
        
        friends_comma = ",".join(friends)
        breakdown_json = json.dumps(breakdown, ensure_ascii=False)
        
        bill_split_row = [
            now.strftime('%Y/%m/%d'),
            description,
            total_amount,
            '我',
            friends_comma,
            breakdown_json,
            '待收',
            unique_id,
            now.strftime('%Y-%m-%d %H:%M:%S')
        ]
        
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range='代墊待收款!A:I',
            valueInputOption='USER_ENTERED',
            body={'values': [bill_split_row]}
        ).execute()
        
        # 2. 寫入「總代墊金額」 (墊付總額 + 個人花費) 到記帳本，支援銀行全額流出對帳 (Flow B)
        # 真實新台幣沒有小數點，總額進行無條件進位 (math.ceil)
        gross_expense = math.ceil(float(total_amount) + float(my_expense))
        if gross_expense > 0:
            gross_row = [
                now.strftime('%Y'),
                f"'{now.strftime('%m')}",
                now.strftime('%Y/%m/%d'),
                "", # 收入項目為空
                f"{description} (代墊與個人拆帳總額)",
                gross_expense,
                format_category_with_emoji(category, False),
                sub_category
            ]
            service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range='記帳!A:H',
                valueInputOption='USER_ENTERED',
                body={'values': [gross_row]}
            ).execute()
            
        # 呼叫小助手重新計算本月總額以獲得最新狀態
        _, cat_report, cat_dict, _ = get_monthly_report(service, now)
        
        # 1. Block 1: Core Bookkeeping Sync
        formatted_category = format_category_with_emoji(category, False)
        block1 = f"真實記帳已自動歸位 [{formatted_category}] 類別，金額：${gross_expense} 元 (墊付總額)"

        # 2. Block 2: Debt Ledger Status & Pill buttons
        breakdown_items = []
        for name, details in breakdown.items():
            if name.startswith('_'):
                continue
            owed = details.get('owed', 0)
            received = details.get('received', 0)
            balance = owed - received
            if balance > 0:
                breakdown_items.append(f"👥 {name}: <b>${balance}</b> [ ⏳ 待收 ]")
        
        block2_list = "<br>".join(breakdown_items) if breakdown_items else "• 目前無未結算債務。"
        
        # Full HTML Card Layout with glassmorphism Morandi tints & Compact spacing (V3.9)
        html_message = f"""
<div class="chat-split-card" style="padding: 8px; border-radius: 16px; border: 1.5px solid rgba(244, 63, 94, 0.2); background: linear-gradient(135deg, rgba(244, 63, 94, 0.08) 0%, rgba(244, 63, 94, 0.02) 100%); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); box-shadow: 0 6px 20px 0 rgba(31, 38, 135, 0.04); margin: 4px 0; font-size: 0.85rem;">
    <div style="font-weight: 800; font-size: 0.95rem; margin-bottom: 4px; color: #f43f5e; display: flex; align-items: center; gap: 4px;">
        💸 代墊拆帳成功完成！
    </div>
    <div style="font-size: 0.8rem; line-height: 1.3; color: var(--text-color, #334155); margin-bottom: 4px;">
        <b>項目描述：</b>{description}<br>
        <b>總代墊金額：</b>${total_amount}
    </div>
    <div style="font-size: 0.8rem; line-height: 1.3; color: #f43f5e; font-weight: 700; margin-bottom: 4px; padding: 4px 8px; border-radius: 8px; background: rgba(244, 63, 94, 0.05); border: 1px solid rgba(244, 63, 94, 0.1);">
        🎯 {block1}
    </div>
    <div style="font-size: 0.8rem; line-height: 1.3; color: var(--text-color, #334155); margin-bottom: 4px; padding: 4px 8px; border-radius: 8px; background: rgba(255, 255, 255, 0.4); border: 1px solid rgba(0, 0, 0, 0.03);">
        <b>📋 朋友欠款明細：</b><br>
        {block2_list}
    </div>
    <div class="card-pill-actions" style="display: flex; flex-wrap: wrap; gap: 6px; border-top: 1px dashed rgba(244, 63, 94, 0.15); padding-top: 6px; justify-content: flex-end;">
        <button class="repay-pill-btn" data-id="{unique_id}" style="background: rgba(244, 63, 94, 0.1); border: 1.5px solid rgba(244, 63, 94, 0.3); color: #f43f5e; padding: 4px 10px; border-radius: 10px; font-size: 0.75rem; font-weight: 700; cursor: pointer; transition: all 0.2s ease;">✅ 一鍵收回</button>
    </div>
</div>
""".replace('\n', '')
        
        return jsonify({
            "status": "success",
            "message": html_message,
            "unique_id": unique_id,
            "description": description,
            "my_expense": my_expense,
            "category": category,
            "breakdown": breakdown,
            "friends": friends,
            "total_amount": total_amount,
            "chart_data": cat_dict
        })
    except Exception as e:
        print(f"[Save Bill Split Error] {e}")
        return jsonify({"status": "error", "message": f"儲存失敗: {str(e)}"}), 500

@app.route('/api/bill_split/repay', methods=['POST'])
def repay_bill_split():
    """
    朋友還錢核銷：
    1. 更新該筆代墊拆帳中指定朋友的「received」金額，並更新該行
    2. 自動在「記帳」中記一筆「代墊款回收」收入
    3. 若該筆所有人都還清，更新狀態為「已結清」，並將該行移動到分頁最底部
    """
    spreadsheet_id = get_spreadsheet_id()
    if not spreadsheet_id:
        return jsonify({"status": "error", "message": "尚未設定 GOOGLE_SHEET_ID"}), 400
        
    data = request.json or {}
    unique_id = data.get('id', '').strip()
    friend_name = data.get('friend_name', '').strip() # 可以為 'unnamed' 或特定朋友名字
    
    if not unique_id:
        return jsonify({"status": "error", "message": "ID 不能為空"}), 400
        
    try:
        service = get_sheets_service()
        now = datetime.now(TW_TZ)
        
        # 1. 取得所有代墊款資料並找出 target 行
        rows = get_sheet_values('代墊待收款', spreadsheet_id=spreadsheet_id)
        if not rows:
            return jsonify({"status": "error", "message": "找不到任何代墊資料"}), 404
            
        target_row_idx = -1
        target_row = None
        for idx, row in enumerate(rows[1:]):
            row_num = idx + 2
            while len(row) < 9:
                row.append('')
            if row[7].strip() == unique_id:
                target_row_idx = row_num
                target_row = row
                break
                
        if target_row_idx == -1:
            return jsonify({"status": "error", "message": "找不到該筆代墊拆帳項目"}), 404
            
        # 2. 原地變更時間戳記 (狀態將在確認是否全部還款後更新)
        target_row[8] = now.strftime('%Y-%m-%d %H:%M:%S')
        
        # 3. 計算本次被還款的金額，用於寫入「負支出」對帳
        try:
            breakdown_old = json.loads(rows[target_row_idx - 1][5])
        except:
            breakdown_old = {}
            
        category_from_row = breakdown_old.get('_category', '未分類')
        sub_category_from_row = breakdown_old.get('_sub_category', '拆帳分攤')
        
        repaid_amount = 0
        if friend_name and friend_name in breakdown_old:
            owed = breakdown_old[friend_name].get('owed', 0)
            received = breakdown_old[friend_name].get('received', 0)
            repaid_amount = float(owed) - float(received)
        else:
            for name, details in breakdown_old.items():
                if name.startswith('_'):
                    continue
                owed = details.get('owed', 0)
                received = details.get('received', 0)
                repaid_amount += (float(owed) - float(received))
                
        # 4. 更新 breakdown JSON 將所有人（或指定朋友）設為已結清
        try:
            breakdown = json.loads(target_row[5])
        except:
            breakdown = {}
            
        if friend_name and friend_name in breakdown:
            breakdown[friend_name]['received'] = breakdown[friend_name].get('owed', 0)
        else:
            for name in breakdown:
                if name.startswith('_'):
                    continue
                breakdown[name]['received'] = breakdown[name].get('owed', 0)
                
        target_row[5] = json.dumps(breakdown, ensure_ascii=False)
        
        # 檢查是否所有人都已還清
        all_settled = True
        for name, details in breakdown.items():
            if name.startswith('_'):
                continue
            if float(details.get('owed', 0)) - float(details.get('received', 0)) > 0:
                all_settled = False
                break
                
        if all_settled:
            target_row[6] = "已收回"
        else:
            target_row[6] = "待收"
        
        # 5. 原地安全更新 Google Sheet 代墊分頁 (A:I)
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f'代墊待收款!A{target_row_idx}:I{target_row_idx}',
            valueInputOption='USER_ENTERED',
            body={'values': [target_row]}
        ).execute()
        
        # 6. 自動在「記帳」分頁中新增一筆該分類下的「負值支出」，真實記載代墊款回收 (Flow B)
        # 真實新台幣無小數點，還款進行無條件進位 (math.ceil)
        repaid_ceil = math.ceil(repaid_amount)
        if repaid_ceil > 0:
            repay_row = [
                now.strftime('%Y'),
                f"'{now.strftime('%m')}",
                now.strftime('%Y/%m/%d'),
                "", # 收入項目為空
                f"代墊款回收 - {friend_name if (friend_name and friend_name != 'unnamed') else target_row[1]}", # 支出項目
                -repaid_ceil, # 金額 (負值支出代表還款回收)
                format_category_with_emoji(category_from_row, False),
                sub_category_from_row
            ]
            service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range='記帳!A:H',
                valueInputOption='USER_ENTERED',
                body={'values': [repay_row]}
            ).execute()
        
        # 重新計算本月總額以獲得最新狀態
        _, cat_report, cat_dict, _ = get_monthly_report(service, now)
        
        msg = f"💸 已成功將該筆代墊項目狀態更新為「已收回」，最新時間：{target_row[8]}，並已記錄回收金額 ${repaid_ceil} 元為負支出！"
        return jsonify({
            "status": "success",
            "message": msg,
            "chart_data": cat_dict
        })
    except Exception as e:
        print(f"[Repay Bill Split Error] {e}")
        return jsonify({"status": "error", "message": f"還款核銷失敗: {str(e)}"}), 500

# =================================================================
# ⏰ 每月固定支出自動補記與 CRUD API (V3.8)
# =================================================================

def check_and_execute_fixed_expenses(service, spreadsheet_id):
    """
    檢查「固定支出」分頁，若有項目已到期 (當前日期.day >= 執行日) 且當月未執行 (最後執行月份 != 當月)，
    且當前日期在「開始日期」與「結束日期」的區間內，
    則將其補記至「記帳」分頁中，並將「最後執行月份」更新為當前月份。
    """
    executed_items = []
    try:
        now = datetime.now(TW_TZ)
        current_day = now.day
        current_year = now.strftime('%Y')
        current_month = f"'{now.strftime('%m')}" # 為了維持 GSheet 文字格式，加上單引號
        current_month_str = now.strftime('%Y-%m') # 用於標記最後執行月份，例如 '2026-06'
        current_date_str = now.strftime('%Y/%m/%d')

        # 讀取固定支出 (從 A 欄至 J 欄，J 為結束日期)
        res = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='固定支出!A:J'
        ).execute()
        rows = res.get('values', [])
        if not rows or len(rows) <= 1:
            return executed_items

        def parse_date(date_str):
            if not date_str:
                return None
            date_str = date_str.strip().replace('/', '-')
            try:
                return datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                try:
                    return datetime.strptime(date_str.split()[0], '%Y-%m-%d').date()
                except Exception:
                    return None

        # 表頭對應：建立日期(0), 項目名稱(1), 母分類(2), 子分類(3), 金額(4), 執行日(每月)(5), 最後執行月份(6), 唯一ID(7), 開始日期(8), 結束日期(9)
        for idx, row in enumerate(rows[1:]):
            row_num = idx + 2  # 行號，1-indexed，表頭是 1，所以第一筆資料是 2

            # 補足列長度以防 len(row) 不足
            while len(row) < 10:
                row.append('')

            name = row[1].strip() if row[1] else ""
            category = row[2].strip() if row[2] else ""
            sub_category = row[3].strip() if row[3] else ""
            amount_val = row[4].strip() if row[4] else ""
            execute_day_val = row[5].strip() if row[5] else ""
            last_executed = row[6].strip() if row[6] else ""
            unique_id = row[7].strip() if row[7] else ""
            start_date_str = row[8].strip() if row[8] else ""
            end_date_str = row[9].strip() if row[9] else ""

            if not name or not amount_val or not execute_day_val:
                continue

            try:
                amount = int(float(amount_val))
            except ValueError:
                amount = 0

            try:
                execute_day = int(float(execute_day_val))
            except ValueError:
                execute_day = 1

            if not unique_id:
                unique_id = str(uuid.uuid4())
                service.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=f'固定支出!H{row_num}',
                    valueInputOption='USER_ENTERED',
                    body={'values': [[unique_id]]}
                ).execute()

            # 檢查是否到期且尚未執行
            if current_day >= execute_day and last_executed != current_month_str:
                # 判斷是否在起訖日期區間內
                # 本月份的目標執行日期為該月第 execute_day 天
                try:
                    execution_date = datetime(now.year, now.month, execute_day).date()
                except ValueError:
                    import calendar
                    last_day_of_month = calendar.monthrange(now.year, now.month)[1]
                    execution_date = datetime(now.year, now.month, min(execute_day, last_day_of_month)).date()

                start_date = parse_date(start_date_str)
                end_date = parse_date(end_date_str)

                if start_date and execution_date < start_date:
                    # 還沒開始，跳過
                    continue
                if end_date and execution_date > end_date:
                    # 已經過期，跳過
                    continue

                # 執行補記到「記帳!A:H」
                # 記帳表頭：['年度', '月份', '日期', '收入項目', '支出項目', '金額', '類別', '子分類']
                formatted_category = format_category_with_emoji(category, is_income=False)
                new_transaction = [
                    current_year,
                    current_month,
                    current_date_str,
                    "", # 收入項目
                    name, # 支出項目
                    amount,
                    formatted_category,
                    sub_category
                ]
                
                service.spreadsheets().values().append(
                    spreadsheetId=spreadsheet_id,
                    range='記帳!A:H',
                    valueInputOption='USER_ENTERED',
                    body={'values': [new_transaction]}
                ).execute()

                # 更新固定支出該列的「最後執行月份」為當月
                service.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=f'固定支出!G{row_num}',
                    valueInputOption='USER_ENTERED',
                    body={'values': [[current_month_str]]}
                ).execute()

                executed_items.append({"name": name, "amount": amount})
                
    except Exception as e:
        print(f"[Fixed Expenses Auto Check Error] {e}")
        
    return executed_items

@app.route('/api/fixed_expenses', methods=['GET', 'POST'])
def handle_fixed_expenses():
    spreadsheet_id = get_spreadsheet_id()
    if not spreadsheet_id:
        return jsonify({"status": "error", "message": "尚未設定 GOOGLE_SHEET_ID"}), 400
        
    service = get_sheets_service()
    now = datetime.now(TW_TZ)
    
    def parse_date(date_str):
        if not date_str:
            return None
        date_str = date_str.strip().replace('/', '-')
        try:
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            try:
                return datetime.strptime(date_str.split()[0], '%Y-%m-%d').date()
            except Exception:
                return None
    
    if request.method == 'GET':
        try:
            res = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range='固定支出!A:J'
            ).execute()
            rows = res.get('values', [])
            fixed_expenses = []
            
            if len(rows) > 1:
                # 遍歷資料列
                for idx, row in enumerate(rows[1:]):
                    row_num = idx + 2
                    while len(row) < 10:
                        row.append('')
                    
                    unique_id = row[7].strip()
                    if not unique_id:
                        unique_id = str(uuid.uuid4())
                        service.spreadsheets().values().update(
                            spreadsheetId=spreadsheet_id,
                            range=f'固定支出!H{row_num}',
                            valueInputOption='USER_ENTERED',
                            body={'values': [[unique_id]]}
                        ).execute()
                        row[7] = unique_id
                        
                    try:
                        amount = int(float(row[4])) if row[4] else 0
                    except ValueError:
                        amount = 0
                        
                    try:
                        execute_day = int(float(row[5])) if row[5] else 1
                    except ValueError:
                        execute_day = 1
                        
                    fixed_expenses.append({
                        "created_date": row[0],
                        "name": row[1],
                        "category": row[2],
                        "sub_category": row[3],
                        "amount": amount,
                        "execute_day": execute_day,
                        "last_executed_month": row[6],
                        "id": unique_id,
                        "start_date": row[8].strip(),
                        "end_date": row[9].strip()
                    })
            return jsonify({"status": "success", "fixed_expenses": fixed_expenses})
        except Exception as e:
            return jsonify({"status": "error", "message": f"獲取固定支出失敗: {str(e)}"}), 500
            
    elif request.method == 'POST':
        # 新增一筆固定支出
        data = request.json or {}
        name = data.get('name', '').strip()
        category = data.get('category', '').strip()
        sub_category = data.get('sub_category', '').strip()
        amount = data.get('amount')
        execute_day = data.get('execute_day')
        start_date = data.get('start_date', '').strip()
        end_date = data.get('end_date', '').strip()
        
        if not name or amount is None or execute_day is None:
            return jsonify({"status": "error", "message": "欄位填寫不完整"}), 400
            
        try:
            amount = int(amount)
            execute_day = int(execute_day)
        except ValueError:
            return jsonify({"status": "error", "message": "金額與執行日必須為數字"}), 400
            
        if execute_day < 1 or execute_day > 28:
            return jsonify({"status": "error", "message": "執行日必須在 1 到 28 日之間"}), 400
            
        created_date = now.strftime('%Y/%m/%d')
        unique_id = str(uuid.uuid4())
        
        # 邊界規則：若當前日期已大於等於執行日，且目標執行日落在起訖日期範圍內，當月應立即補記一次
        current_day = now.day
        current_month_str = now.strftime('%Y-%m')
        last_executed_month = ""
        immediate_execute = False
        
        if current_day >= execute_day:
            try:
                execution_date = datetime(now.year, now.month, execute_day).date()
            except ValueError:
                import calendar
                last_day_of_month = calendar.monthrange(now.year, now.month)[1]
                execution_date = datetime(now.year, now.month, min(execute_day, last_day_of_month)).date()

            start_dt = parse_date(start_date)
            end_dt = parse_date(end_date)

            is_valid = True
            if start_dt and execution_date < start_dt:
                is_valid = False
            if end_dt and execution_date > end_dt:
                is_valid = False

            if is_valid:
                last_executed_month = current_month_str
                immediate_execute = True
            
        new_row = [
            created_date,
            name,
            category,
            sub_category,
            amount,
            execute_day,
            last_executed_month,
            unique_id,
            start_date,
            end_date
        ]
        
        try:
            service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range='固定支出!A:J',
                valueInputOption='USER_ENTERED',
                body={'values': [new_row]}
            ).execute()
            
            # 如果符合立即執行補記
            if immediate_execute:
                formatted_category = format_category_with_emoji(category, is_income=False)
                new_transaction = [
                    now.strftime('%Y'),
                    f"'{now.strftime('%m')}",
                    now.strftime('%Y/%m/%d'),
                    "", # 收入項目
                    name, # 支出項目
                    amount,
                    formatted_category,
                    sub_category
                ]
                service.spreadsheets().values().append(
                    spreadsheetId=spreadsheet_id,
                    range='記帳!A:H',
                    valueInputOption='USER_ENTERED',
                    body={'values': [new_transaction]}
                ).execute()
                
            return jsonify({
                "status": "success", 
                "message": "已新增固定支出" + ("，且因當月已到期，系統已自動為您補記一筆！" if immediate_execute else "。"),
                "immediate_execute": immediate_execute
            })
        except Exception as e:
            return jsonify({"status": "error", "message": f"新增失敗: {str(e)}"}), 500

@app.route('/api/fixed_expenses/update', methods=['POST'])
def update_fixed_expense():
    spreadsheet_id = get_spreadsheet_id()
    if not spreadsheet_id:
        return jsonify({"status": "error", "message": "尚未設定 GOOGLE_SHEET_ID"}), 400
        
    service = get_sheets_service()
    data = request.json or {}
    unique_id = data.get('id', '').strip()
    name = data.get('name', '').strip()
    category = data.get('category', '').strip()
    sub_category = data.get('sub_category', '').strip()
    amount = data.get('amount')
    execute_day = data.get('execute_day')
    start_date = data.get('start_date', '').strip()
    end_date = data.get('end_date', '').strip()
    
    if not unique_id or not name or amount is None or execute_day is None:
        return jsonify({"status": "error", "message": "欄位填寫不完整"}), 400
        
    try:
        amount = int(amount)
        execute_day = int(execute_day)
    except ValueError:
        return jsonify({"status": "error", "message": "金額與執行日必須為數字"}), 400
        
    if execute_day < 1 or execute_day > 28:
        return jsonify({"status": "error", "message": "執行日必須在 1 到 28 日之間"}), 400
        
    def parse_date(date_str):
        if not date_str:
            return None
        date_str = date_str.strip().replace('/', '-')
        try:
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            try:
                return datetime.strptime(date_str.split()[0], '%Y-%m-%d').date()
            except Exception:
                return None

    try:
        res = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='固定支出!A:J'
        ).execute()
        rows = res.get('values', [])
        
        target_row_num = -1
        last_executed_month = ""
        for idx, row in enumerate(rows[1:]):
            row_num = idx + 2
            while len(row) < 10:
                row.append('')
            if row[7].strip() == unique_id:
                target_row_num = row_num
                last_executed_month = row[6].strip()
                break
                
        if target_row_num == -1:
            return jsonify({"status": "error", "message": "找不到該固定支出項目"}), 404
            
        now = datetime.now(TW_TZ)
        current_day = now.day
        current_month_str = now.strftime('%Y-%m')
        immediate_execute = False
        
        # 邊界規則：若修改後當前日期已大於等於執行日，且當月尚未執行，以新金額執行補記
        if current_day >= execute_day and last_executed_month != current_month_str:
            try:
                execution_date = datetime(now.year, now.month, execute_day).date()
            except ValueError:
                import calendar
                last_day_of_month = calendar.monthrange(now.year, now.month)[1]
                execution_date = datetime(now.year, now.month, min(execute_day, last_day_of_month)).date()

            start_dt = parse_date(start_date)
            end_dt = parse_date(end_date)

            is_valid = True
            if start_dt and execution_date < start_dt:
                is_valid = False
            if end_dt and execution_date > end_dt:
                is_valid = False

            if is_valid:
                last_executed_month = current_month_str
                immediate_execute = True
            
        # 更新該列
        updated_row = [
            rows[target_row_num - 1][0], # 保持建立日期不變
            name,
            category,
            sub_category,
            amount,
            execute_day,
            last_executed_month,
            unique_id,
            start_date,
            end_date
        ]
        
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f'固定支出!A{target_row_num}:J{target_row_num}',
            valueInputOption='USER_ENTERED',
            body={'values': [updated_row]}
        ).execute()
        
        if immediate_execute:
            formatted_category = format_category_with_emoji(category, is_income=False)
            new_transaction = [
                now.strftime('%Y'),
                f"'{now.strftime('%m')}",
                now.strftime('%Y/%m/%d'),
                "", # 收入項目
                name, # 支出項目
                amount,
                formatted_category,
                sub_category
            ]
            service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range='記帳!A:H',
                valueInputOption='USER_ENTERED',
                body={'values': [new_transaction]}
            ).execute()
            
        return jsonify({
            "status": "success", 
            "message": "修改固定支出成功" + ("，且因當月已到期，系統已自動為您補記一筆！" if immediate_execute else "。"),
            "immediate_execute": immediate_execute
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"修改失敗: {str(e)}"}), 500

@app.route('/api/fixed_expenses/delete', methods=['POST'])
def delete_fixed_expense():
    spreadsheet_id = get_spreadsheet_id()
    if not spreadsheet_id:
        return jsonify({"status": "error", "message": "尚未設定 GOOGLE_SHEET_ID"}), 400
        
    service = get_sheets_service()
    data = request.json or {}
    unique_id = data.get('id', '').strip()
    
    if not unique_id:
        return jsonify({"status": "error", "message": "ID 不能為空"}), 400
        
    try:
        # 1. 獲取固定支出的 sheetId
        spreadsheet_metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        fixed_expenses_sheet_id = None
        for sheet in spreadsheet_metadata['sheets']:
            if sheet['properties']['title'] == '固定支出':
                fixed_expenses_sheet_id = sheet['properties']['sheetId']
                break
                
        if fixed_expenses_sheet_id is None:
            return jsonify({"status": "error", "message": "找不到固定支出分頁"}), 404
            
        # 2. 找到 ID 所在的行號
        res = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='固定支出!A:J'
        ).execute()
        rows = res.get('values', [])
        
        target_row_idx = -1
        for idx, row in enumerate(rows[1:]):
            row_num = idx + 2
            while len(row) < 10:
                row.append('')
            if row[7].strip() == unique_id:
                target_row_idx = row_num - 1 # 0-indexed row index
                break
                
        if target_row_idx == -1:
            return jsonify({"status": "error", "message": "找不到該固定支出項目"}), 404
            
        # 3. 刪除該行
        body = {
            'requests': [{
                'deleteDimension': {
                    'range': {
                        'sheetId': fixed_expenses_sheet_id,
                        'dimension': 'ROWS',
                        'startIndex': target_row_idx,
                        'endIndex': target_row_idx + 1
                    }
                }
            }]
        }
        service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()
        
        return jsonify({"status": "success", "message": "刪除固定支出項目成功"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"刪除失敗: {str(e)}"}), 500


# =================================================================
# 💳 個人資產帳戶管理 API (V3.8)
# =================================================================

def get_stock_total_value_internal(spreadsheet_id):
    try:
        service = get_sheets_service()
        res = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='💰股票投資組合!A:J'
        ).execute()
        rows = res.get('values', [])
        
        if not rows or len(rows) < 2:
            return 0.0
            
        transactions = []
        portfolio = {}
        
        for row in rows[1:]:
            if len(row) < 7 or not row[1].strip():
                continue
                
            ticker = row[1].strip().upper()
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
                "type": tx_type,
                "shares": shares,
                "price": price,
                "fee": fee,
                "live_price": live_price
            })
            
            if ticker not in portfolio:
                portfolio[ticker] = {
                    "net_shares": 0.0,
                    "total_cost": 0.0,
                    "live_price": 0.0
                }
                
            p = portfolio[ticker]
            if tx_type == "買進":
                p["net_shares"] += shares
                p["total_cost"] += (shares * price + fee)
            elif tx_type == "賣出":
                if p["net_shares"] > 0:
                    avg_buy_cost = p["total_cost"] / p["net_shares"]
                    cost_of_sold = shares * avg_buy_cost
                    p["net_shares"] -= shares
                    p["total_cost"] -= cost_of_sold
                    if p["net_shares"] <= 0.001:
                        p["net_shares"] = 0.0
                        p["total_cost"] = 0.0
            if live_price > 0:
                p["live_price"] = live_price
                
        total_unrealized_value = 0.0
        for t, p in portfolio.items():
            if p["net_shares"] > 0.001:
                if p["live_price"] <= 0:
                    ticker_txs = [tx for tx in transactions if tx["ticker"] == t]
                    if ticker_txs:
                        p["live_price"] = ticker_txs[-1]["price"]
                current_value = p["net_shares"] * p["live_price"]
                total_unrealized_value += current_value
                
        return round(total_unrealized_value, 2)
    except Exception as e:
        print(f"[get_stock_total_value_internal Error] {e}")
        return 0.0

@app.route('/api/asset_accounts', methods=['GET', 'POST'])
def handle_asset_accounts():
    # 確保表單存在與自癒
    try:
        spreadsheet_id = ensure_user_spreadsheet()
    except Exception as e:
        print(f"Error in handle_asset_accounts ensuring spreadsheet: {e}")
        spreadsheet_id = get_spreadsheet_id()
        
    if not spreadsheet_id:
        return jsonify({"status": "error", "message": "尚未設定 GOOGLE_SHEET_ID"}), 400
        
    service = get_sheets_service()
    
    # 🛡️ 同步確保「資產帳戶」工作表存在（老帳號自癒補全）
    try:
        meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        existing_titles = [s['properties']['title'] for s in meta.get('sheets', [])]
        if '資產帳戶' not in existing_titles:
            print(f"[handle_asset_accounts] '資產帳戶' sheet missing in {spreadsheet_id}, creating...")
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': [{'addSheet': {'properties': {'title': '資產帳戶'}}}]}
            ).execute()
            # 寫入表頭
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range='資產帳戶!A1:F1',
                valueInputOption='USER_ENTERED',
                body={'values': [['帳戶名稱', '帳戶類型', '當前餘額', '唯一 ID', '更新時間', '備註']]}
            ).execute()
            print(f"[handle_asset_accounts] '資產帳戶' sheet created successfully!")
    except Exception as sheet_err:
        print(f"[handle_asset_accounts] Error checking/creating '資產帳戶' sheet: {sheet_err}")
    

    if request.method == 'GET':
        try:
            res = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range='資產帳戶!A:F'
            ).execute()
            rows = res.get('values', [])
            accounts = []
            
            if len(rows) > 1:
                for idx, row in enumerate(rows[1:]):
                    row_num = idx + 2
                    while len(row) < 6:
                        row.append('')
                    
                    unique_id = row[3].strip()
                    if not unique_id:
                        unique_id = str(uuid.uuid4())
                        service.spreadsheets().values().update(
                            spreadsheetId=spreadsheet_id,
                            range=f'資產帳戶!D{row_num}',
                            valueInputOption='USER_ENTERED',
                            body={'values': [[unique_id]]}
                        ).execute()
                        row[3] = unique_id
                        
                    try:
                        balance = int(float(row[2])) if row[2] else 0
                    except ValueError:
                        balance = 0
                        
                    accounts.append({
                        "name": row[0].strip(),
                        "type": row[1].strip(),
                        "balance": balance,
                        "id": unique_id,
                        "updated_time": row[4].strip(),
                        "remark": row[5].strip()
                    })
            
            stock_value = get_stock_total_value_internal(spreadsheet_id)
            
            return jsonify({
                "status": "success",
                "accounts": accounts,
                "stock_value": stock_value
            })
        except Exception as e:
            return jsonify({"status": "error", "message": f"獲取資產帳戶失敗: {str(e)}"}), 500
            
    elif request.method == 'POST':
        data = request.json or {}
        name = data.get('name', '').strip()
        acct_type = data.get('type', '').strip()
        balance = data.get('balance')
        remark = data.get('remark', '').strip()
        
        if not name or not acct_type or balance is None:
            return jsonify({"status": "error", "message": "欄位填寫不完整"}), 400
            
        try:
            balance = int(balance)
        except ValueError:
            return jsonify({"status": "error", "message": "餘額必須為數字"}), 400
            
        unique_id = str(uuid.uuid4())
        now_time = datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M:%S')
        
        new_row = [
            name,
            acct_type,
            balance,
            unique_id,
            now_time,
            remark
        ]
        
        try:
            service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range='資產帳戶!A:F',
                valueInputOption='USER_ENTERED',
                body={'values': [new_row]}
            ).execute()
            
            return jsonify({"status": "success", "message": "已成功新增資產帳戶"})
        except Exception as e:
            import traceback
            print(f"[Asset Account POST Error] spreadsheet_id={spreadsheet_id}, name={name}, type={acct_type}")
            print(f"[Asset Account POST Error] Detail: {str(e)}")
            print(traceback.format_exc())
            return jsonify({"status": "error", "message": f"新增失敗: {str(e)}"}), 500

@app.route('/api/asset_accounts/update', methods=['POST'])
def update_asset_account():
    spreadsheet_id = get_spreadsheet_id()
    if not spreadsheet_id:
        return jsonify({"status": "error", "message": "尚未設定 GOOGLE_SHEET_ID"}), 400
        
    service = get_sheets_service()
    data = request.json or {}
    unique_id = data.get('id', '').strip()
    name = data.get('name', '').strip()
    acct_type = data.get('type', '').strip()
    balance = data.get('balance')
    remark = data.get('remark', '').strip()
    
    if not unique_id or not name or not acct_type or balance is None:
        return jsonify({"status": "error", "message": "欄位填寫不完整"}), 400
        
    try:
        balance = int(balance)
    except ValueError:
        return jsonify({"status": "error", "message": "餘額必須為數字"}), 400
        
    try:
        res = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='資產帳戶!A:F'
        ).execute()
        rows = res.get('values', [])
        
        target_row_num = -1
        for idx, row in enumerate(rows[1:]):
            row_num = idx + 2
            while len(row) < 6:
                row.append('')
            if row[3].strip() == unique_id:
                target_row_num = row_num
                break
                
        if target_row_num == -1:
            return jsonify({"status": "error", "message": "找不到該資產帳戶"}), 404
            
        now_time = datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M:%S')
        
        updated_row = [
            name,
            acct_type,
            balance,
            unique_id,
            now_time,
            remark
        ]
        
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f'資產帳戶!A{target_row_num}:F{target_row_num}',
            valueInputOption='USER_ENTERED',
            body={'values': [updated_row]}
        ).execute()
        
        return jsonify({"status": "success", "message": "對帳更新成功！"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"更新失敗: {str(e)}"}), 500

@app.route('/api/asset_accounts/delete', methods=['POST'])
def delete_asset_account():
    spreadsheet_id = get_spreadsheet_id()
    if not spreadsheet_id:
        return jsonify({"status": "error", "message": "尚未設定 GOOGLE_SHEET_ID"}), 400
        
    service = get_sheets_service()
    data = request.json or {}
    unique_id = data.get('id', '').strip()
    
    if not unique_id:
        return jsonify({"status": "error", "message": "ID 不能為空"}), 400
        
    try:
        spreadsheet_metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        asset_sheet_id = None
        for sheet in spreadsheet_metadata['sheets']:
            if sheet['properties']['title'] == '資產帳戶':
                asset_sheet_id = sheet['properties']['sheetId']
                break
                
        if asset_sheet_id is None:
            return jsonify({"status": "error", "message": "找不到資產帳戶分頁"}), 404
            
        res = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range='資產帳戶!A:F'
        ).execute()
        rows = res.get('values', [])
        
        target_row_idx = -1
        for idx, row in enumerate(rows[1:]):
            row_num = idx + 2
            while len(row) < 6:
                row.append('')
            if row[3].strip() == unique_id:
                target_row_idx = row_num - 1
                break
                
        if target_row_idx == -1:
            return jsonify({"status": "error", "message": "找不到該資產帳戶"}), 404
            
        body = {
            'requests': [{
                'deleteDimension': {
                    'range': {
                        'sheetId': asset_sheet_id,
                        'dimension': 'ROWS',
                        'startIndex': target_row_idx,
                        'endIndex': target_row_idx + 1
                    }
                }
            }]
        }
        service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()
        
        return jsonify({"status": "success", "message": "刪除帳戶成功"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"刪除失敗: {str(e)}"}), 500

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
        # 雲端非同步同步日記備份
        email = session.get('user_email', '')
        if email:
            creds = get_valid_credentials()
            sync_diary_to_drive(email, diary_id, creds=creds)
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

    # 🔍 動態探測實際工作表名稱 (口袋 或 口袋名單)
    pocket_title = '口袋'
    try:
        spreadsheet_metadata = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        titles = [sheet['properties']['title'] for sheet in spreadsheet_metadata.get('sheets', [])]
        if '口袋名單' in titles:
            pocket_title = '口袋名單'
        elif '口袋' in titles:
            pocket_title = '口袋'
    except Exception as e:
        print(f"Error resolving pocket sheet title: {e}")

    if action == 'list':
        try:
            rows = get_sheet_values(pocket_title, spreadsheet_id=sheet_id)
            if not rows: return []
            pocket_list = []
            for row in rows[1:]: # 跳過表頭
                if len(row) >= 3:
                    loc_val = row[3] if len(row) > 3 else ''
                    area_val = row[4] if len(row) > 4 else ''
                    if not area_val and loc_val:
                        cities = ["台北市", "新北市", "桃園市", "台中市", "台南市", "高雄市", 
                                  "基隆市", "新竹市", "嘉義市", "新竹縣", "苗栗縣", "彰化縣", "南投縣", 
                                  "雲林縣", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣", "台東縣", "澎湖縣", "金門縣", "連江縣",
                                  "臺北市", "臺南市", "臺中市"]
                        for city in cities:
                            if city in loc_val:
                                area_val = city
                                break
                        
                        # 🛡️ 增強行政區解析對應 (解決 Google 格式省略縣市直接呈現行政區的問題)
                        if not area_val:
                            taipei_d = ["萬華區", "信義區", "大安區", "中山區", "松山區", "內湖區", "士林區", "北投區", "文山區", "南港區", "中正區", "大同區"]
                            ntpc_d = ["板橋區", "三重區", "中和區", "永和區", "新莊區", "新店區", "土城區", "蘆洲區", "汐止區", "樹林區", "淡水區", "五股區", "泰山區", "林口區"]
                            for dist in taipei_d:
                                if dist in loc_val:
                                    area_val = "台北市"
                                    break
                            if not area_val:
                                for dist in ntpc_d:
                                    if dist in loc_val:
                                        area_val = "新北市"
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
                        'lng': row[8] if len(row) > 8 else None,
                        'is_fav': row[9] if len(row) > 9 else ''
                    })
            return pocket_list
        except Exception as e:
            print(f"Error listing pocket items: {e}")
            return []

    elif action == 'add':
        try:
            item_id = str(uuid.uuid4())[:8] # 簡短 ID
            category = data.get('category', '其他')
            is_fav = data.get('is_fav', '')
            if category == '常用':
                category = '其他'
                is_fav = '1'
            name = data.get('name', '')
            location = data.get('location', '')
            area = data.get('area', '')
            
            # 智慧解析縣市地區標籤 (從地址字串提取)
            if not area and location:
                cities = ["台北市", "新北市", "桃園市", "台中市", "台南市", "高雄市", 
                          "基隆市", "新竹市", "嘉義市", "新竹縣", "苗栗縣", "彰化縣", "南投縣", 
                          "雲林縣", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣", "台東縣", "澎湖縣", "金門縣", "連江縣",
                          "臺北市", "臺南市", "臺中市"]
                for city in cities:
                    if city in location:
                        area = city
                        break
                
                # 🛡️ 增強行政區解析對應 (解決 Google 格式省略縣市直接呈現行政區的問題)
                if not area:
                    taipei_d = ["萬華區", "信義區", "大安區", "中山區", "松山區", "內湖區", "士林區", "北投區", "文山區", "南港區", "中正區", "大同區"]
                    ntpc_d = ["板橋區", "三重區", "中和區", "永和區", "新莊區", "新店區", "土城區", "蘆洲區", "汐止區", "樹林區", "淡水區", "五股區", "泰山區", "林口區"]
                    for dist in taipei_d:
                        if dist in location:
                            area = "台北市"
                            break
                    if not area:
                        for dist in ntpc_d:
                            if dist in location:
                                area = "新北市"
                                break
            
            note = data.get('note', '')
            create_time = datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')
            
            # 優先使用前端傳來的經緯度，若無則嘗試後端抓取
            lat = data.get('lat')
            lng = data.get('lng')
            if lat is None or lng is None:
                lat, lng = get_lat_lng(location or name)
            
            values = [[item_id, category, name, location, area, note, create_time, lat, lng, is_fav]]
            body = {'values': values}
            service.spreadsheets().values().append(
                spreadsheetId=sheet_id, range=f'{pocket_title}!A2',
                valueInputOption='RAW', body=body).execute()
            return True
        except Exception as e:
            print(f"Error adding pocket item: {e}")
            return False

    elif action == 'delete':
        try:
            target_id = data.get('id')
            # 1. 先獲取試算表資訊，找出工作分頁的 sheetId
            spreadsheet_metadata = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
            pocket_sheet_id = None
            for sheet in spreadsheet_metadata['sheets']:
                if sheet['properties']['title'] == pocket_title:
                    pocket_sheet_id = sheet['properties']['sheetId']
                    break
            if pocket_sheet_id is None:
                pocket_sheet_id = spreadsheet_metadata['sheets'][0]['properties']['sheetId']

            # 2. 找出 ID 所在的行號 (利用 get_sheet_values 觸發自癒，且定位為 0-based)
            rows = get_sheet_values(pocket_title, spreadsheet_id=sheet_id)
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
            new_cat = data.get('category')
            is_fav = data.get('is_fav') # '1' or '' or None

            rows = get_sheet_values(pocket_title, spreadsheet_id=sheet_id)
            row_index = -1
            if rows:
                for i, row in enumerate(rows):
                    if row and row[0] == target_id:
                        row_index = i + 1
                        break

            if row_index == -1:
                return False

            if new_cat is not None:
                body = {'values': [[new_cat]]}
                service.spreadsheets().values().update(
                    spreadsheetId=sheet_id, range=f'{pocket_title}!B{row_index}',
                    valueInputOption='RAW', body=body).execute()

            if is_fav is not None:
                body = {'values': [[is_fav]]}
                service.spreadsheets().values().update(
                    spreadsheetId=sheet_id, range=f'{pocket_title}!J{row_index}',
                    valueInputOption='RAW', body=body).execute()
            return True
        except Exception as e:
            print(f"Error updating pocket item category/fav: {e}")
            return False

    elif action == 'update_note':
        try:
            target_id = data.get('id')
            new_note = data.get('note', '')
            new_name = data.get('name')

            rows = get_sheet_values(pocket_title, spreadsheet_id=sheet_id)
            row_index = -1
            if rows:
                for i, row in enumerate(rows):
                    if row and row[0] == target_id:
                        row_index = i + 1
                        break

            if row_index == -1:
                return False

            # 更新自訂稱呼 (Column F，即 '{pocket_title}!F' + row_index)
            body_note = {'values': [[new_note]]}
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id, range=f'{pocket_title}!F{row_index}',
                valueInputOption='RAW', body=body_note).execute()

            # 若有傳入主要名稱，更新主要名稱 (Column C，即 '{pocket_title}!C' + row_index)
            if new_name is not None:
                body_name = {'values': [[new_name]]}
                service.spreadsheets().values().update(
                    spreadsheetId=sheet_id, range=f'{pocket_title}!C{row_index}',
                    valueInputOption='RAW', body=body_name).execute()

            # 若有傳入 is_fav，更新常用地標狀態 (Column J，即 '{pocket_title}!J' + row_index)
            is_fav = data.get('is_fav')
            if is_fav is not None:
                body_fav = {'values': [[is_fav]]}
                service.spreadsheets().values().update(
                    spreadsheetId=sheet_id, range=f'{pocket_title}!J{row_index}',
                    valueInputOption='RAW', body=body_fav).execute()

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
                
                # 預估下次經期日期（從最後一次開始日加一個平均週期）
                next_dt = last_dt + timedelta(days=avg_cycle)
                
                # 🐛 BUG FIX: 若預測日已是過去日期，持續往後滾動加一個週期，
                # 直到找到未來的下次預測日，避免顯示「0 天」
                while next_dt.date() < now.date():
                    next_dt = next_dt + timedelta(days=avg_cycle)
                
                next_date_str = next_dt.strftime("%Y/%m/%d")
                
                # 依更新後的 next_dt 重新計算排卵日 (下次月經來潮前 14 天)
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
                    # 非進行中 —— next_dt 已確保為未來日期，diff 一定 >= 0
                    diff = (next_dt.date() - now.date()).days
                    days_until_next = diff
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

@app.route('/api/health/diagnose_calendar', methods=['GET'])
def diagnose_calendar():
    try:
        service_cal = get_calendar_service()
        now_time_min = (datetime.now(TW_TZ) - timedelta(days=5)).isoformat()
        time_max = (datetime.now(TW_TZ) + timedelta(days=90)).isoformat()
        events_result = service_cal.events().list(
            calendarId=CALENDAR_ID, 
            timeMin=now_time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        diagnose_list = []
        deleted_list = []
        
        for event in events:
            summary = event.get('summary', '')
            start = event.get('start', {})
            date_val = start.get('date') or start.get('dateTime')
            
            event_info = {
                "id": event.get('id'),
                "summary": summary,
                "date": date_val
            }
            diagnose_list.append(event_info)
            
            if "🌸 (預測)" in summary or "(預測) 生理期" in summary or "預測) 生理期" in summary:
                try:
                    service_cal.events().delete(calendarId=CALENDAR_ID, eventId=event['id']).execute()
                    deleted_list.append(event_info)
                except Exception as del_err:
                    event_info["error"] = str(del_err)
                    
        return jsonify({
            "status": "success",
            "calendar_id": str(CALENDAR_ID),
            "found_count": len(events),
            "deleted_count": len(deleted_list),
            "all_events": diagnose_list,
            "deleted_events": deleted_list
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# --- 🌸 健康與 AI 訓練 API ---
@app.route('/api/health/info', methods=['GET'])
def get_health_info():
    health_id = get_health_sheet_id()
    if not health_id:
         return jsonify({"status": "error", "message": "尚未設定 HEALTH_SHEET_ID"})
    try:
        # 額外清理未來所有的 🌸 (預測) 行程，確保行事曆乾淨 (V15.2 UX Fix)
        try:
            service_cal = get_calendar_service()
            now_time_min = datetime.now(TW_TZ).isoformat()
            pred_events = service_cal.events().list(calendarId=CALENDAR_ID, timeMin=now_time_min, q="🌸 (預測)").execute()
            for event in pred_events.get('items', []):
                if "🌸 (預測)" in event.get('summary', ''):
                    service_cal.events().delete(calendarId=CALENDAR_ID, eventId=event['id']).execute()
        except Exception as cal_clean_err:
            print(f"Silent calendar prediction cleanup error: {cal_clean_err}")

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
        
        # 讀取獨立的生理症狀紀錄
        symptoms_rows = get_sheet_values('生理症狀紀錄', spreadsheet_id=health_id)
        symptoms_dict = {}
        if symptoms_rows and len(symptoms_rows) > 1:
            for r in symptoms_rows[1:]:
                if len(r) >= 2 and r[0].strip():
                    raw_date = r[0].strip()
                    try:
                        parsed_date = datetime.strptime(raw_date.replace('-', '/'), "%Y/%m/%d")
                        date_key = parsed_date.strftime("%Y/%m/%d")
                    except:
                        date_key = raw_date
                    symptoms_dict[date_key] = {
                        "symptoms": r[1].strip(),
                        "note": r[2].strip() if len(r) > 2 else ""
                    }
                    
        # 計算經前症狀預警與貼心提醒
        pms_alert = None
        if parsed_history and symptoms_dict:
            period_starts = [item["dt"] for item in parsed_history]
            pms_symptoms = []
            gap_days_list = []
            
            for date_str, info in symptoms_dict.items():
                try:
                    sym_dt = datetime.strptime(date_str, "%Y/%m/%d")
                    future_starts = [p_start for p_start in period_starts if p_start >= sym_dt]
                    if future_starts:
                        closest_start = min(future_starts)
                        gap = (closest_start - sym_dt).days
                        if 1 <= gap <= 7:
                            gap_days_list.append(gap)
                            pms_symptoms.extend([s.strip() for s in info["symptoms"].split("、") if s.strip()])
                except:
                    pass
            
            if pms_symptoms and gap_days_list:
                from collections import Counter
                counter = Counter(pms_symptoms)
                top_symptoms = [item[0] for item in counter.most_common(2)]
                avg_gap = round(sum(gap_days_list) / len(gap_days_list))
                symptoms_phrase = "、".join(top_symptoms)
                pms_alert = {
                    "has_data": True,
                    "avg_gap": avg_gap,
                    "top_symptoms": symptoms_phrase,
                    "tips": f"根據您的歷史紀錄，生理期前約 {avg_gap} 天您常伴隨「{symptoms_phrase}」等經前症狀，這幾天請多喝溫水、清淡飲食並保持充足睡眠喔！"
                }
                  
        return jsonify({
            "status": "success",
            "history": history[:3],
            "is_cold_start": is_cold_start,
            "symptoms_dict": symptoms_dict,
            "pms_alert": pms_alert,
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
        conn = None
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
        finally:
            if conn:
                conn.close()
            
    return jsonify({"status": "success", "message": "免責聲明簽署存證寫入成功！"})

@app.route('/api/health/check_disclaimer', methods=['GET'])
def check_disclaimer():
    """
    檢查使用者是否已經同意過免責聲明（雙重保險判定，跨裝置同步）。
    """
    email = session.get('user_email', '')
    
    # 1. 優先從 TiDB 資料庫查詢
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "false" and email:
        conn = None
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
        finally:
            if conn:
                conn.close()
            
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
    """判斷使用者是否為 旗艦版 或 年費版 尊榮會員"""
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "true":
        return True  # 本機單人模式完全開放
    
    developer_emails = {'ulir976272866@gmail.com', 'mina.chen.xstar.sg@gmail.com'}
    email = session.get('user_email', '')
    if email and email.lower() in developer_emails:
        return True # 開發者白名單豁免
        
    return session.get('subscription_type') in ['YEARLY_AI', 'PREMIUM_MONTHLY']

def check_and_deduct_points(email, cost_points):
    """
    檢查使用者點數是否足夠，若足夠則扣除並同步到資料庫與 session。
    若為單人模式或開發者白名單則無條件通過且不扣點。
    """
    if os.getenv("SINGLE_USER_MODE", "true").lower() == "true":
        return True, 9999
        
    developer_emails = {'ulir976272866@gmail.com', 'mina.chen.xstar.sg@gmail.com'}
    if email and email.lower() in developer_emails:
        return True, 9999
        
    current_points = session.get('ai_points', 0)
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            # 1. 查詢最新點數
            cursor.execute("SELECT ai_points FROM users WHERE email = %s;", (email,))
            user = cursor.fetchone()
            if user:
                current_points = user.get('ai_points', 0)
            
            if current_points < cost_points:
                return False, current_points
                
            new_points = current_points - cost_points
            session['ai_points'] = new_points
            
            # 2. 扣除點數
            cursor.execute("UPDATE users SET ai_points = %s WHERE email = %s;", (new_points, email))
            conn.commit()
            print(f"[Points Deduction] 成功扣除 {email} {cost_points} 點，剩餘 {new_points} 點。")
            return True, new_points
    except Exception as e:
        print(f"[Points Deduction Error] {e}")
        return False, current_points
    finally:
        if conn:
            conn.close()

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
            '記帳': ['年度', '月份', '日期', '收入項目', '支出項目', '金額', '類別', '子分類'],
            '待辦': ['建立日期', '事項/內容', '分類', '狀態', '唯一 ID', '建立時間', '優先級'],
            '日記': ['日期', '內容', '天氣', '心情', '時間'],
            '願望': ['建立日期', '商品名稱', '預估價格', '備註/連結', '狀態', '分類', '實際價格', '唯一 ID', '儲存時間'],
            '願望清單': ['建立日期', '商品名稱', '預估價格', '備註/連結', '狀態', '分類', '實際價格', '唯一 ID', '儲存時間'],
            '口袋': ['ID', '分類', '店名', '地址', '地區', '備註', '建立時間', '緯度', '經度', '常用'],
            '口袋名單': ['ID', '類別', '名稱', '地點', '地點區域', '備註', '建立時間', '緯度', '經度', '常用'],
            'AI_指令集': ['觸發語句', '執行動作'],
            '💰股票投資組合': ['交易日期', '股票代號', '股票名稱', '交易類型', '交易股數', '交易單價', '手續費', '即時市價', '即時損益', '備註'],
            '生理症狀紀錄': ['日期', '症狀', '備註', '寫入時間']
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
            "message": "🔒 「智慧股票投資記帳」為尊榮旗艦版獨享功能，請升級後體驗語音與一鍵資產看板功能！"
        })
        
    spreadsheet_id = get_spreadsheet_id()
    if not spreadsheet_id:
        return jsonify({"status": "error", "message": "尚未連結試算表"})
        
    report_text = get_stock_portfolio_report_text(spreadsheet_id)
    return jsonify({"status": "success", "type": "query_stock_portfolio", "message": report_text})

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
                    "net_shares": 0.0,
                    "total_cost": 0.0,
                    "live_price": 0.0,
                    "realized_pnl": 0.0,
                    "dividends": 0.0
                }
                
            p = portfolio[ticker]
            if tx_type == "買進":
                p["net_shares"] += shares
                p["total_cost"] += (shares * price + fee)
            elif tx_type == "賣出":
                # 移動平均成本法 (Weighted Average Cost) 精算已實現損益與剩餘庫存成本
                if p["net_shares"] > 0:
                    avg_buy_cost = p["total_cost"] / p["net_shares"]
                    cost_of_sold = shares * avg_buy_cost
                    revenue_from_sold = shares * price - fee
                    realized = revenue_from_sold - cost_of_sold
                    p["realized_pnl"] += realized
                    
                    p["net_shares"] -= shares
                    p["total_cost"] -= cost_of_sold
                    if p["net_shares"] <= 0.001:
                        p["net_shares"] = 0.0
                        p["total_cost"] = 0.0
                else:
                    p["realized_pnl"] += (shares * price - fee)
            elif tx_type in ["股息", "配息"]:
                dividend_amt = price * (shares if shares > 0 else 1.0)
                p["dividends"] += dividend_amt
                
            if live_price > 0:
                p["live_price"] = live_price
                
        active_portfolio = {}
        closed_portfolio = {}
        total_unrealized_cost = 0.0
        total_unrealized_value = 0.0
        total_unrealized_roi = 0.0
        total_realized_pnl = 0.0
        total_dividends = 0.0
        
        for t, p in portfolio.items():
            total_dividends += p.get("dividends", 0.0)
            total_realized_pnl += p.get("realized_pnl", 0.0)
            
            p["realized_pnl"] = round(p.get("realized_pnl", 0.0), 2)
            p["dividends"] = round(p.get("dividends", 0.0), 2)
            
            if p["net_shares"] > 0.001:
                p["avg_cost"] = round(p["total_cost"] / p["net_shares"], 2)
                if p["live_price"] <= 0:
                    ticker_txs = [tx for tx in transactions if tx["ticker"] == t]
                    if ticker_txs:
                        p["live_price"] = ticker_txs[-1]["price"]
                        
                p["current_value"] = round(p["net_shares"] * p["live_price"], 2)
                p["unrealized_roi"] = round(p["current_value"] - p["total_cost"], 2)
                p["total_roi"] = round(p["unrealized_roi"] + p["realized_pnl"] + p["dividends"], 2)
                
                total_unrealized_cost += p["total_cost"]
                total_unrealized_value += p["current_value"]
                total_unrealized_roi += p["unrealized_roi"]
                
                p["total_cost"] = round(p["total_cost"], 2)
                p["live_price"] = round(p["live_price"], 2)
                p["net_shares"] = round(p["net_shares"], 2)
                
                active_portfolio[t] = p
            else:
                # 已結清部位 (Closed Positions)
                p["unrealized_roi"] = 0.0
                p["current_value"] = 0.0
                p["total_roi"] = round(p["realized_pnl"] + p["dividends"], 2)
                p["net_shares"] = 0.0
                p["total_cost"] = 0.0
                p["avg_cost"] = 0.0
                
                ticker_txs = [tx for tx in transactions if tx["ticker"] == t]
                p["close_date"] = ticker_txs[-1]["date"] if ticker_txs else "未知"
                
                closed_portfolio[t] = p

        # 全局總回報率
        global_total_roi = total_unrealized_roi + total_realized_pnl + total_dividends
        global_roi_rate = round((global_total_roi / total_unrealized_cost) * 100, 2) if total_unrealized_cost > 0 else 0.0
        
        return jsonify({
            "status": "success",
            "transactions": transactions[-15:], # 回傳最近 15 筆明細
            "portfolio": active_portfolio,
            "closed_portfolio": closed_portfolio,
            "summary": {
                "total_cost": round(total_unrealized_cost, 2),
                "total_value": round(total_unrealized_value, 2),
                "total_unrealized_roi": round(total_unrealized_roi, 2),
                "total_realized_pnl": round(total_realized_pnl, 2),
                "total_dividends": round(total_dividends, 2),
                "global_total_roi": round(global_total_roi, 2),
                "total_roi_rate": global_roi_rate
            }
        })
        
    except Exception as e:
        print(f"[Stock API Error] {e}")
        return jsonify({"status": "error", "message": f"載入證券失敗: {str(e)}"})

def get_or_create_drive_folder(service, folder_name, parent_id=None):
    """查詢或在 Google Drive 建立指定資料夾"""
    query = f"mimeType = 'application/vnd.google-apps.folder' and name = '{folder_name}' and trashed = false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    else:
        query += " and 'root' in parents"
        
    try:
        results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        files = results.get('files', [])
        if files:
            return files[0]['id']
        
        # 不存在則新增
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        if parent_id:
            file_metadata['parents'] = [parent_id]
            
        folder = service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')
    except Exception as e:
        print(f"[Drive Folder Error] {e}")
        raise e

def count_today_receipts(service, folder_id, today_str):
    """查詢某天在資料夾中已經有多少個收據，以遞增序號"""
    query = f"'{folder_id}' in parents and name contains '{today_str}' and trashed = false"
    try:
        results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        files = results.get('files', [])
        return len(files)
    except Exception as e:
        print(f"[Drive List Error] {e}")
        return 0

@app.route('/api/tax/upload_receipt', methods=['POST'])
def upload_tax_receipt():
    """
    💎 旗艦付費會員專屬特權：
    收據/發票拍照雲端歸檔，自動依格式 YYYYMMDDXX[1-999] 命名，並依交易年度自動歸檔在 Google Drive 主目錄中。
    """
    import random
    import string
    from googleapiclient.http import MediaIoBaseUpload
    import io
    
    # 商業特權防線：非付費會員直接阻斷
    sub_type = session.get('subscription_type', 'NONE')
    email = session.get('user_email', '')
    developer_emails = {'ulir976272866@gmail.com', 'mina.chen.xstar.sg@gmail.com'}
    
    if os.getenv("SINGLE_USER_MODE", "false").lower() == "false":
        if sub_type == 'NONE' and email.lower() not in developer_emails:
            return jsonify({"status": "locked", "message": "報稅雲端歸檔功能為付費版會員特權，請先升級方案！"}), 403
            
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "無上傳檔案"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "未選取檔案"}), 400
        
    try:
        service_drive = get_drive_service()
        if not service_drive:
            return jsonify({"status": "error", "message": "無法取得 Google Drive 雲端服務，請先授權連線！"}), 500
            
        now = datetime.now(TW_TZ)
        today_str = now.strftime("%Y%m%d")
        year_str = now.strftime("%Y")
        
        # 1. 取得或建立主資料夾「報稅宗教與公益收據管理」
        main_folder_id = get_or_create_drive_folder(service_drive, "報稅宗教與公益收據管理")
        
        # 2. 取得或建立年度子資料夾
        year_folder_id = get_or_create_drive_folder(service_drive, year_str, parent_id=main_folder_id)
        
        # 3. 檔名計數自動生成序號 (純流水編號)
        count = count_today_receipts(service_drive, year_folder_id, today_str)
        seq_num = f"{count + 1:02d}"
        
        filename = f"{today_str}{seq_num}.png"
        
        # 4. 上傳二進位資料至雲端硬碟
        file_stream = io.BytesIO(file.read())
        media = MediaIoBaseUpload(file_stream, mimetype='image/png', resumable=True)
        
        file_metadata = {
            'name': filename,
            'parents': [year_folder_id]
        }
        
        uploaded_file = service_drive.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        
        print(f"[Tax Upload] 成功上傳公益收據 {filename} (ID: {uploaded_file.get('id')}) 至年度資料夾 {year_str}")
        return jsonify({
            "status": "success",
            "message": "收據成功上傳並歸檔",
            "filename": filename,
            "year": year_str,
            "id": uploaded_file.get('id')
        })
        
    except Exception as e:
        print(f"[Tax Upload Error] {e}")
        return jsonify({"status": "error", "message": f"雲端上傳失敗: {str(e)}"}), 500

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
        
        # 🌟 反向同步：將股票交易同步寫入記帳試算表 (0 成本免 AI)
        try:
            service_sheets = get_sheets_service()
            tx_is_income = (tx_type == '賣出')
            
            # 總金額計算：買進為 (股數 * 單價) + 手續費；賣出為 (股數 * 單價) - 手續費
            subtotal = shares * price
            total_amount = (subtotal - fee) if tx_is_income else (subtotal + fee)
            
            item_desc = f"股票賣出: {name} ({ticker})" if tx_is_income else f"股票買進: {name} ({ticker})"
            cat_label = "投資獲利" if tx_is_income else "投資"
            
            tx_dt = datetime.strptime(date_str, "%Y-%m-%d")
            
            body_book = {'values': [[
                str(tx_dt.year),
                f"'{tx_dt.month:02d}",
                tx_dt.strftime("%Y/%m/%d"),
                item_desc if tx_is_income else "",
                "" if tx_is_income else item_desc,
                round(total_amount, 2),
                format_category_with_emoji(cat_label, tx_is_income)
            ]]}
            
            service_sheets.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range='記帳!A:G',
                valueInputOption='USER_ENTERED',
                body=body_book
            ).execute()
            print(f"[Stock Reverse Sync] 成功同步回填記帳表：{item_desc} ${total_amount}")
        except Exception as e:
            print(f"[Stock Reverse Sync Error] {e}")
        
        # 🌟 更新 TiDB 的 has_stock_record 標籤做為再行銷依據
        email = session.get('user_email', '')
        if os.getenv("SINGLE_USER_MODE", "false").lower() == "false" and email:
            conn = None
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
            finally:
                if conn:
                    conn.close()
                
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
        
        # 1. 檢查是否已經在進行中 (動態搜尋非 SYSTEM 的進行中紀錄)
        has_ongoing = False
        if len(rows) > 1:
             for row in rows[1:]:
                 if len(row) > 0 and row[0] == "SYSTEM":
                     continue
                 start_str = row[2] if len(row) > 2 else ""
                 if not start_str or start_str == "SYSTEM_NOTICE":
                     continue
                 latest_end = row[3] if len(row) > 3 else ""
                 if latest_end == "進行中" or latest_end.strip() == "":
                     has_ongoing = True
                     break
        if has_ongoing:
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
        
        # 計算週期天數 (動態尋找上一筆非 SYSTEM 的有效生理期紀錄)
        cycle_days = ""
        prev_row_idx = None
        if len(rows) > 1:
             for idx, row in enumerate(rows):
                 if idx == 0:
                     continue
                 if len(row) > 0 and row[0] == "SYSTEM":
                     continue
                 start_str = row[2] if len(row) > 2 else ""
                 if not start_str or start_str == "SYSTEM_NOTICE":
                     continue
                 try:
                     last_dt = datetime.strptime(start_str.strip(), "%Y/%m/%d").replace(tzinfo=TW_TZ)
                     cycle_days = str((now - last_dt).days)
                     prev_row_idx = idx
                     break
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
        
        # 如果有算出週期天數，動態更新上一筆 (插入新列後其在 sheet 中的列號為 prev_row_idx + 2)
        if cycle_days and prev_row_idx is not None:
            prev_sheet_row = prev_row_idx + 2
            service_sheets.spreadsheets().values().update(
                spreadsheetId=health_id, range=f"生理紀錄!F{prev_sheet_row}",
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
        
        # 3. 日曆清理：刪除未來所有殘留的 🌸 (預測) 行程
        # [已移除] 不再自動將生理期排入 Google 行事曆
        try:
            service_cal = get_calendar_service()
            time_min = now.isoformat()
            events_result = service_cal.events().list(calendarId=CALENDAR_ID, timeMin=time_min, q="🌸 (預測)").execute()
            for event in events_result.get('items', []):
                if "🌸 (預測)" in event.get('summary', ''):
                    service_cal.events().delete(calendarId=CALENDAR_ID, eventId=event['id']).execute()
        except Exception as cal_err:
            print(f"Calendar cleanup error in record_start: {cal_err}")
            
        return jsonify({"status": "success", "message": "已記錄開始！🌸"})
        
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
        
        # 動態尋找非 SYSTEM 且動作為進行中或為空的紀錄
        ongoing_row_idx = None
        for idx, row in enumerate(rows):
            if idx == 0:
                continue
            if len(row) > 0 and row[0] == "SYSTEM":
                continue
            start_str = row[2] if len(row) > 2 else ""
            if not start_str or start_str == "SYSTEM_NOTICE":
                continue
            end_val = row[3] if len(row) > 3 else ""
            if end_val == "進行中" or end_val.strip() == "":
                ongoing_row_idx = idx
                break
                
        if ongoing_row_idx is None:
            return jsonify({"status": "error", "message": "沒有找到進行中的生理紀錄，無法結束。"})
             
        start_str = rows[ongoing_row_idx][2]
        now = datetime.now(TW_TZ)
        today_str = now.strftime("%Y/%m/%d")
        
        length_days = ""
        try:
             start_dt = datetime.strptime(start_str.strip(), "%Y/%m/%d").replace(tzinfo=TW_TZ)
             length_days = str((now - start_dt).days + 1)
        except: pass
        
        row_num = ongoing_row_idx + 1
        body = {"values": [[today_str, length_days]]}
        service_sheets.spreadsheets().values().update(
            spreadsheetId=health_id, range=f"生理紀錄!D{row_num}:E{row_num}",
            valueInputOption="USER_ENTERED", body=body
        ).execute()
        
        return jsonify({"status": "success", "message": "已記錄結束，辛苦了！✅"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/health/edit_current', methods=['POST'])
def edit_current_health_record():
    """
    編輯當前最新一次生理期的開始與結束時間，重算長度並同步重置 Google 日曆事件 (V4.2)
    """
    if not is_premium_user():
        return jsonify({"status": "locked", "message": "請先升級 Premium 旗艦版會員"})
        
    health_id = get_health_sheet_id()
    if not health_id:
        return jsonify({"status": "error", "message": "尚未設定 HEALTH_SHEET_ID"})
        
    data = request.json or {}
    original_start = data.get('original_start', '').strip() # 格式: YYYY/MM/DD
    new_start = data.get('new_start', '').strip() # 格式: YYYY-MM-DD
    new_end = data.get('new_end', '').strip() # 格式: YYYY-MM-DD，或者是 "進行中" 或空
    
    if not original_start or not new_start:
        return jsonify({"status": "error", "message": "開始日期為必填欄位"})
        
    try:
        # 解析日期
        new_start_dt = datetime.strptime(new_start.replace('/', '-'), "%Y-%m-%d")
        new_start_formatted = new_start_dt.strftime("%Y/%m/%d")
        
        new_end_formatted = "進行中"
        new_end_dt = None
        if new_end and new_end != "進行中" and new_end.strip() != "":
            new_end_dt = datetime.strptime(new_end.replace('/', '-'), "%Y-%m-%d")
            new_end_formatted = new_end_dt.strftime("%Y/%m/%d")
            if new_start_dt > new_end_dt:
                return jsonify({"status": "error", "message": "開始日期不能大於結束日期"})
                
        # 讀取試算表
        rows = get_sheet_values('生理紀錄', spreadsheet_id=health_id)
        if not rows or len(rows) < 2:
            return jsonify({"status": "error", "message": "找不到生理紀錄"})
            
        # 尋找匹配 original_start 的行
        target_row_idx = None
        for idx, row in enumerate(rows):
            if idx == 0: continue
            if len(row) > 0 and row[0] == "SYSTEM": continue
            start_str = row[2].strip() if len(row) > 2 else ""
            if start_str == original_start:
                target_row_idx = idx + 1 # 1-based index for sheets
                break
                
        if not target_row_idx:
            return jsonify({"status": "error", "message": f"找不到開始日期為 {original_start} 的紀錄"})
            
        # 計算長度與更新欄位
        length_days = ""
        if new_end_dt:
            length_days = str((new_end_dt - new_start_dt).days + 1)
            
        year = str(new_start_dt.year)
        month = str(new_start_dt.month)
        
        # 讀取該行的原有備註與週期 (Column F=Row[5], G=Row[6])
        orig_row = rows[target_row_idx - 1]
        cycle_days = orig_row[5] if len(orig_row) > 5 else ""
        symptoms = orig_row[6] if len(orig_row) > 6 else ""
        
        # 準備更新的資料列
        updated_row = [
            year,
            month,
            new_start_formatted,
            new_end_formatted,
            length_days,
            cycle_days,
            symptoms
        ]
        
        # 寫回試算表
        service_sheets = get_sheets_service()
        service_sheets.spreadsheets().values().update(
            spreadsheetId=health_id, range=f"生理紀錄!A{target_row_idx}:G{target_row_idx}",
            valueInputOption="USER_ENTERED", body={"values": [updated_row]}
        ).execute()
        
        # 實體排序以防修改日期後亂序
        try:
            sh = service_sheets.spreadsheets().get(spreadsheetId=health_id).execute()
            sheet_obj = next(s for s in sh['sheets'] if s['properties']['title'] == '生理紀錄')
            sheet_id = sheet_obj['properties']['sheetId']
            sort_req = {
                "sortRange": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 7},
                    "sortSpecs": [{"dimensionIndex": 2, "sortOrder": "DESCENDING"}]
                }
            }
            service_sheets.spreadsheets().batchUpdate(spreadsheetId=health_id, body={"requests": [sort_req]}).execute()
        except Exception as sort_err:
            print(f"Auto-sorting error in edit_current: {sort_err}")
            
        # 日曆清理：刪除原本的生理期事件與所有殘留預測事件
        # [已移除] 不再自動將生理期重新排入 Google 行事曆
        try:
            service_cal = get_calendar_service()
            # 刪除原本的生理期事件 (在 original_start 上下 14 天內尋找並刪除 🌸 相關事件)
            orig_start_dt = datetime.strptime(original_start, "%Y/%m/%d")
            time_min = (orig_start_dt - timedelta(days=5)).isoformat() + "Z"
            time_max = (orig_start_dt + timedelta(days=20)).isoformat() + "Z"
            events_result = service_cal.events().list(
                calendarId=CALENDAR_ID, timeMin=time_min, timeMax=time_max, q="🌸"
            ).execute()
            for event in events_result.get('items', []):
                if "🌸 生理期" in event.get('summary', ''):
                    service_cal.events().delete(calendarId=CALENDAR_ID, eventId=event['id']).execute()
            # 也清除未來所有的 🌸 (預測) 行程
            now_time_min = datetime.now(TW_TZ).isoformat()
            pred_events = service_cal.events().list(calendarId=CALENDAR_ID, timeMin=now_time_min, q="🌸 (預測)").execute()
            for event in pred_events.get('items', []):
                if "🌸 (預測)" in event.get('summary', ''):
                    service_cal.events().delete(calendarId=CALENDAR_ID, eventId=event['id']).execute()
        except Exception as cal_err:
            print(f"Calendar cleanup error in edit_current: {cal_err}")
            
        return jsonify({"status": "success", "message": "生理期時間已成功更新！🌸"})
        
    except Exception as e:
        print(f"Edit current health record error: {e}")
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
    note_str = request.json.get('note', '').strip()
    target_date = request.json.get('date', '').strip()
    
    # 確保日期格式為 YYYY/MM/DD
    try:
        parsed_dt = datetime.strptime(target_date.replace('-', '/'), "%Y/%m/%d")
        target_date = parsed_dt.strftime("%Y/%m/%d")
    except:
        target_date = datetime.now(TW_TZ).strftime("%Y/%m/%d")
        
    now_str = datetime.now(TW_TZ).strftime("%Y/%m/%d %H:%M:%S")
    
    try:
        service = get_sheets_service()
        # 讀取現有生理症狀紀錄
        rows = get_sheet_values('生理症狀紀錄', spreadsheet_id=health_id)
        
        header = ['日期', '症狀', '備註', '寫入時間']
        data_rows = []
        
        # 提取現有數據行 (過濾表頭)
        if rows and len(rows) > 0:
            for r in rows:
                if len(r) > 0 and r[0].strip() == '日期':
                    header = [x.strip() for x in r]
                    continue
                if len(r) > 0 and r[0].strip():
                    # 確保資料列長度至少有 4 列，以防解析崩潰
                    padded_row = r + [""] * (4 - len(r))
                    data_rows.append(padded_row)
                    
        # 尋找是否已存在該日期的紀錄 (透過 datetime 解析比較，進行 Upsert)
        existing_idx = None
        target_dt = None
        try:
            target_dt = datetime.strptime(target_date.strip().replace('-', '/'), "%Y/%m/%d")
        except:
            pass
            
        if target_dt:
            for idx, r in enumerate(data_rows):
                try:
                    row_dt = datetime.strptime(r[0].strip().replace('-', '/'), "%Y/%m/%d")
                    if row_dt == target_dt:
                        existing_idx = idx
                        break
                except:
                    if r[0].strip() == target_date:
                        existing_idx = idx
                        break
                        
        new_row = [target_date, symptoms_str, note_str, now_str]
        if existing_idx is not None:
            data_rows[existing_idx] = new_row
        else:
            data_rows.append(new_row)
            
        # 依照日期進行降序排列 (越接近當下的時間，即日期越大，在最上面)
        def get_row_date(row):
            try:
                return datetime.strptime(row[0].strip().replace('-', '/'), "%Y/%m/%d")
            except:
                return datetime.min
                
        data_rows.sort(key=get_row_date, reverse=True)
        
        # 合併表頭與排序後的資料
        all_values = [header] + data_rows
        
        # 覆寫整個工作表，以保持排序一致且防止殘留數據
        service.spreadsheets().values().clear(
            spreadsheetId=health_id, range="生理症狀紀錄!A:D"
        ).execute()
        
        service.spreadsheets().values().update(
            spreadsheetId=health_id, range="生理症狀紀錄!A1",
            valueInputOption="USER_ENTERED", body={"values": all_values}
        ).execute()
        
        return jsonify({"status": "success", "message": f"{target_date} 症狀已記錄！🩺"})
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

# ============================================================
# 🧠 Dynamic Learning System, Token Guard & Drive Backup System
# ============================================================
import base64
import io
from cryptography.fernet import Fernet

def get_fernet_for_email(email):
    """根據使用者的 Email 決定性派生 AES-256 (Fernet) 金鑰"""
    h = hashlib.sha256(email.lower().strip().encode('utf-8')).digest()
    key = base64.urlsafe_b64encode(h)
    return Fernet(key)

def upload_or_update_drive_file(service, folder_id, filename, mime_type, content):
    """上傳或更新 Google Drive 中的檔案"""
    from googleapiclient.http import MediaIoBaseUpload
    query = f"'{folder_id}' in parents and name = '{filename}' and trashed = false"
    try:
        results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        files = results.get('files', [])
        
        fh = io.BytesIO(content)
        media = MediaIoBaseUpload(fh, mimetype=mime_type, resumable=True)
        
        if files:
            file_id = files[0]['id']
            service.files().update(
                fileId=file_id,
                media_body=media
            ).execute()
            print(f"[Drive File Guard] 檔案 {filename} (ID: {file_id}) 更新成功。")
        else:
            file_metadata = {
                'name': filename,
                'parents': [folder_id]
            }
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            print(f"[Drive File Guard] 檔案 {filename} (ID: {file.get('id')}) 新建成功。")
    except Exception as e:
        print(f"[Drive File Guard Error] 上傳/更新 {filename} 失敗: {e}")
        raise e

def sync_diary_to_drive(email, spreadsheet_id, creds=None):
    """將日記備忘非同步同步至 Google Drive (包含明文結構化 JSON 與 AES 加密 Bin 檔)"""
    if not email:
        return
        
    def _run():
        try:
            from googleapiclient.discovery import build
            if creds:
                service_sheets = build('sheets', 'v4', credentials=creds)
                service_drive = build('drive', 'v3', credentials=creds)
            else:
                if creds_sa:
                    service_sheets = build('sheets', 'v4', credentials=creds_sa)
                    service_drive = build('drive', 'v3', credentials=creds_sa)
                else:
                    service_sheets = build('sheets', 'v4')
                    service_drive = build('drive', 'v3')

            res = service_sheets.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range='日記!A:E'
            ).execute()
            rows = res.get('values', [])
            if not rows or len(rows) <= 1:
                print("[Drive Sync] 日記為空，無需同步。")
                return
                
            header = [h.strip() for h in rows[0]]
            memos = []
            for row in rows[1:]:
                if not any(row):
                    continue
                padded = row + [""] * (len(header) - len(row))
                memos.append({
                    'date': padded[0],
                    'content': padded[1],
                    'weather': padded[2],
                    'mood': padded[3],
                    'time': padded[4] if len(padded) > 4 else ''
                })
                
            json_data = json.dumps(memos, ensure_ascii=False, indent=2)
            
            fernet = get_fernet_for_email(email)
            encrypted_data = fernet.encrypt(json_data.encode('utf-8'))
            
            folder_id = get_or_create_drive_folder(service_drive, "AI_秘書_日記備份")
            
            upload_or_update_drive_file(
                service=service_drive,
                folder_id=folder_id,
                filename="notebook_structured.json",
                mime_type="application/json",
                content=json_data.encode('utf-8')
            )
            
            upload_or_update_drive_file(
                service=service_drive,
                folder_id=folder_id,
                filename="notebook_encrypted.bin",
                mime_type="application/octet-stream",
                content=encrypted_data
            )
            print(f"[Drive Sync] 日記同步成功！email={email}")
        except Exception as e:
            print(f"[Drive Sync Error] 日記同步失敗: {e}")
            
    import threading
    threading.Thread(target=_run, daemon=True).start()


def init_users_table_migration():
    """初始化並自癒升級 users 資料表，新增 subscription_expires_at, last_ad_rewarded_at, daily_ad_rewards_count 欄位"""
    print("[Subscription DB Guard] 啟動 TiDB 使用者表訂閱與廣告過期欄位檢查與自癒程序...")
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 嘗試新增 subscription_expires_at 欄位
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN subscription_expires_at TIMESTAMP NULL DEFAULT NULL;")
                conn.commit()
                print("[Subscription DB Guard] 成功自癒升級！已為 users 表新增 subscription_expires_at 欄位。")
            except Exception:
                pass
            
            # 嘗試新增 last_ad_rewarded_at 欄位
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN last_ad_rewarded_at TIMESTAMP NULL DEFAULT NULL;")
                conn.commit()
                print("[Subscription DB Guard] 成功自癒升級！已為 users 表新增 last_ad_rewarded_at 欄位。")
            except Exception:
                pass
                
            # 嘗試新增 daily_ad_rewards_count 欄位
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN daily_ad_rewards_count INT DEFAULT 0;")
                conn.commit()
                print("[Subscription DB Guard] 成功自癒升級！已為 users 表新增 daily_ad_rewards_count 欄位。")
            except Exception:
                pass

            # 嘗試新增 refund_policy_agreed_at 欄位
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN refund_policy_agreed_at TIMESTAMP NULL DEFAULT NULL;")
                conn.commit()
                print("[Subscription DB Guard] 成功自癒升級！已為 users 表新增 refund_policy_agreed_at 欄位。")
            except Exception:
                pass
    except Exception as e:
        print(f"[Subscription DB Guard Error] 欄位檢查與自癒程序發生異常: {e}")
    finally:
        if conn:
            conn.close()



def init_stock_suggestions_table():
    """初始化 TiDB 股票選單聯想庫"""
    print("[Stock DB Guard] 啟動 TiDB 股票選單聯想表檢查與自癒程序...")
    conn = None
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
    except Exception as e:
        print(f"[Stock DB Guard Error] 初始化資料庫失敗: {e}")
    finally:
        if conn:
            conn.close()

@app.route('/api/stock/suggestions', methods=['GET'])
def get_stock_suggestions_api():
    """
    從 TiDB Cloud 中模糊查詢匹配的熱門股票代號與名稱
    """
    q = request.args.get('q', '').strip().lower()
    if not q:
        return jsonify([])
        
    conn = None
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
        return jsonify(matches)
    except Exception as e:
        print(f"[Stock Suggestions API Error] {e}")
        return jsonify([])
    finally:
        if conn:
            conn.close()

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
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.executemany("""
                    INSERT INTO stock_suggestions (ticker, name, short_code) 
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE name = VALUES(name), short_code = VALUES(short_code);
                """, records)
                conn.commit()
            print(f"[Stock Sync] 同步大成功！共 {len(records)} 檔台灣上市上櫃股票/ETF 已經 100% 寫入您的 TiDB 資料庫！")
            return len(records)
        finally:
            if conn:
                conn.close()
    except Exception as e:
        print(f"[Stock Sync Error] 同步台灣股票時發生錯誤: {e}")
        return 0

def init_shopee_links_table():
    """初始化 TiDB 蝦皮分潤輪播連結表，並寫入 10 筆測試種子資料"""
    print("[Shopee DB Guard] 啟動 TiDB 蝦皮連結表檢查與自癒程序...")
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 1. 建立 table (如果不存在)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shopee_links (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    url VARCHAR(500) NOT NULL,
                    image_url VARCHAR(500) DEFAULT NULL,
                    click_count INT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # 2. 檢查是否已經有資料，如果沒有則寫入預設的 10 筆商品連結
            cursor.execute("SELECT COUNT(*) FROM shopee_links;")
            res = cursor.fetchone()
            count = res[0] if res else 0
            if count == 0:
                print("[Shopee DB Guard] 偵測到蝦皮連結表為空，開始寫入預設測試分潤商品...")
                # 使用熱門蝦皮品類與 dummy/測試連結，以及 Unsplash 高清商品縮圖
                seeds = [
                    ("限時特惠 📱 3C智慧配件超值選", "https://shopee.tw/", "https://images.unsplash.com/photo-1546868871-7041f2a55e12?w=500&auto=format&fit=crop&q=60"),
                    ("美妝保養 🌸 明星保濕補水精華", "https://shopee.tw/", "https://images.unsplash.com/photo-1526947425960-945c6e72858f?w=500&auto=format&fit=crop&q=60"),
                    ("居家必備 ☕ 雙層防燙隔熱玻璃杯", "https://shopee.tw/", "https://images.unsplash.com/photo-1514432324607-a09d9b4aefdd?w=500&auto=format&fit=crop&q=60"),
                    ("時尚穿搭 👟 莫蘭迪Morandi運動慢跑鞋", "https://shopee.tw/", "https://images.unsplash.com/photo-1491553895911-0055eca6402d?w=500&auto=format&fit=crop&q=60"),
                    ("質感生活 🕯️ 天然香氛大豆蠟燭", "https://shopee.tw/", "https://images.unsplash.com/photo-1603006905003-be475563bc59?w=500&auto=format&fit=crop&q=60"),
                    ("日常辦公 💻 機械式鍵盤免運促銷", "https://shopee.tw/", "https://images.unsplash.com/photo-1587829741301-dc798b83add3?w=500&auto=format&fit=crop&q=60"),
                    ("美味零食 🍪 團購熱銷海鹽餅乾", "https://shopee.tw/", "https://images.unsplash.com/photo-1559181567-c3190ca9959b?w=500&auto=format&fit=crop&q=60"),
                    ("生理呵護 🌿 草本舒緩暖宮貼", "https://shopee.tw/", "https://images.unsplash.com/photo-1556228720-195a672e8a03?w=500&auto=format&fit=crop&q=60"),
                    ("智慧存股 📊 實戰投資組合手冊", "https://shopee.tw/", "https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?w=500&auto=format&fit=crop&q=60"),
                    ("手動好物 📝 簡約無印風子彈筆記本", "https://shopee.tw/", "https://images.unsplash.com/photo-1531346878377-a5be20888e57?w=500&auto=format&fit=crop&q=60")
                ]
                cursor.executemany(
                    "INSERT INTO shopee_links (name, url, image_url) VALUES (%s, %s, %s);",
                    seeds
                )
                conn.commit()
                print("[Shopee DB Guard] 10 筆預設測試商品已成功匯入 TiDB 資料庫！")
    except Exception as e:
        print(f"[Shopee DB Guard Error] 初始化蝦皮連結表失敗: {e}")
    finally:
        if conn:
            conn.close()

@app.route('/go/shopee')
def shopee_redirect():
    """
    隨機或依序重導向至 10 筆蝦皮分潤商品網址，累加 click_count 後跳轉
    """
    conn = None
    target_url = "https://shopee.tw/"
    try:
        conn = get_db_connection()
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            # 查詢所有蝦皮分潤連結
            cursor.execute("SELECT id, name, url FROM shopee_links;")
            links = cursor.fetchall()
            if links:
                # 這裡採用完全隨機輪播
                import random
                chosen = random.choice(links)
                target_url = chosen['url']
                link_id = chosen['id']
                
                # 累加點擊次數
                cursor.execute("UPDATE shopee_links SET click_count = click_count + 1 WHERE id = %s;", (link_id,))
                conn.commit()
                print(f"[Shopee Redirect] 成功導向至 {chosen['name']} (ID: {link_id})，累加點擊次數。")
    except Exception as e:
        print(f"[Shopee Redirect Error] 重導向失敗: {e}")
    finally:
        if conn:
            conn.close()
            
    return redirect(target_url)

@app.route('/api/shopee/ads', methods=['GET'])
def get_shopee_ads():
    """
    獲取目前所有的蝦皮分潤廣告資訊，供前端輪播看板使用
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT id, name, url, image_url FROM shopee_links LIMIT 10;")
            links = cursor.fetchall()
            return jsonify(links)
    except Exception as e:
        print(f"[Shopee Ads API Error] 獲取廣告失敗: {e}")
        return jsonify([])
    finally:
        if conn:
            conn.close()

@app.route('/api/shopee/click', methods=['POST'])
def record_shopee_click():
    """
    前端點擊看板廣告時發送 POST，累加 click_count 數據
    """
    data = request.json or {}
    link_id = data.get('id')
    if not link_id:
        return jsonify({"status": "error", "message": "缺少廣告 ID"}), 400
        
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("UPDATE shopee_links SET click_count = click_count + 1 WHERE id = %s;", (link_id,))
            conn.commit()
            return jsonify({"status": "success", "message": "已記錄點擊數據！"})
    except Exception as e:
        print(f"[Shopee Click API Error] 累加點擊次數失敗: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/user/ad_reward', methods=['POST'])
def handle_ad_reward():
    """
    看廣告賺點數發放路由，限制每日最多加點 5 次，每次加 1 點
    """
    email = session.get('user_email', '')
    if not email:
        return jsonify({"status": "error", "message": "請先登入帳號"}), 401
        
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT * FROM users WHERE email = %s;", (email,))
            user = cursor.fetchone()
            if not user:
                return jsonify({"status": "error", "message": "找不到該使用者資料"}), 404
                
            current_points = user.get('ai_points', 0)
            last_ad_rewarded_at = user.get('last_ad_rewarded_at')
            daily_count = user.get('daily_ad_rewards_count', 0)
            
            # 檢查今日日期是否與 last_ad_rewarded_at 相同
            from datetime import datetime
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            
            is_same_day = False
            if last_ad_rewarded_at:
                if isinstance(last_ad_rewarded_at, str):
                    is_same_day = last_ad_rewarded_at.startswith(today_str)
                else:
                    is_same_day = last_ad_rewarded_at.strftime("%Y-%m-%d") == today_str
            
            if is_same_day:
                if daily_count >= 5:
                    return jsonify({
                        "status": "error", 
                        "message": "🚨 您今日看廣告賺點數的次數已達上限 (5次)，請明天再來吧！"
                    }), 400
                new_daily_count = daily_count + 1
            else:
                # 跨日重設
                new_daily_count = 1
                
            new_points = current_points + 1
            session['ai_points'] = new_points
            
            # 更新資料庫
            cursor.execute("""
                UPDATE users 
                SET ai_points = %s, last_ad_rewarded_at = NOW(), daily_ad_rewards_count = %s 
                WHERE email = %s;
            """, (new_points, new_daily_count, email))
            conn.commit()
            
            print(f"[Ad Reward Success] 使用者 {email} 觀看廣告成功，今日次數: {new_daily_count}/5，點數增加為 {new_points}")
            return jsonify({
                "status": "success", 
                "message": "恭喜獲得 1 點 AI 額度！💎",
                "ai_points": new_points,
                "daily_count": new_daily_count
            })
            
    except Exception as e:
        print(f"[Ad Reward API Error] 點數發放異常: {e}")
        return jsonify({"status": "error", "message": "伺服器處理點數發放時出錯"}), 500
    finally:
        if conn:
            conn.close()

# ================================================================
# ===          MEMBER CARD MODULE - 會員卡包功能模組            ===
# ===  新增時間: 2026-07-10  |  架構: 內嵌單體路由區塊         ===
# ===  依賴: googleapiclient (已存在), uuid, re, time           ===
# ================================================================

MEMBER_SHEET_NAME = '會員卡包'
MEMBER_HEADERS = ['卡片ID', '使用者ID', '商家名稱', '卡號',
                   '條碼類型', '備註', '品牌顏色', '建立時間', '更新時間', '卡片分類']

# 統一品牌配置資料庫（用於前後端一致的推薦、顏色與分類判定）
MEMBER_PRESET_BRANDS = [
    {
        'key': '7-11', 'store': '7-11', 'category': '超商',
        'color': 'linear-gradient(135deg,#007236 0%,#00813A 60%,#F15A24 60%,#F15A24 100%)',
        'brandColor': '#00813A', 'type': 'CODE128',
        'chipLines': ['7'], 'chipSize': '1.1rem'
    },
    {
        'key': '全家', 'store': '全家', 'category': '超商',
        'color': 'linear-gradient(135deg,#0062A8,#0079C1)',
        'brandColor': '#0079C1', 'type': 'CODE128',
        'chipLines': ['全家'], 'chipSize': '0.62rem'
    },
    {
        'key': '萊爾富', 'store': '萊爾富', 'category': '超商',
        'color': 'linear-gradient(135deg,#C0171C,#E5171B)',
        'brandColor': '#E5171B', 'type': 'CODE128',
        'chipLines': ['萊爾', '富'], 'chipSize': '0.55rem'
    },
    {
        'key': 'OK超商', 'store': 'OK超商', 'category': '超商',
        'color': 'linear-gradient(135deg,#E65C00,#FF6B00)',
        'brandColor': '#FF6B00', 'type': 'CODE128',
        'chipLines': ['OK'], 'chipSize': '0.85rem'
    },
    {
        'key': '屈臣氏', 'store': '屈臣氏', 'category': '藥妝',
        'color': 'linear-gradient(135deg,#007BB5,#00AEEF)',
        'brandColor': '#00AEEF', 'type': 'EAN13',
        'chipLines': ['W'], 'chipSize': '1.1rem'
    },
    {
        'key': '康是美', 'store': '康是美', 'category': '藥妝',
        'color': 'linear-gradient(135deg,#C0171C,#E5171B)',
        'brandColor': '#E5171B', 'type': 'EAN13',
        'chipLines': ['康是', '美'], 'chipSize': '0.5rem'
    },
    {
        'key': '寶雅', 'store': '寶雅', 'category': '藥妝',
        'color': 'linear-gradient(135deg,#A0006B,#D4006E)',
        'brandColor': '#D4006E', 'type': 'EAN13',
        'chipLines': ['PO', 'YA'], 'chipSize': '0.55rem'
    },
    {
        'key': 'SOGO', 'store': 'SOGO', 'category': '百貨',
        'color': 'linear-gradient(135deg,#700000,#8B0000)',
        'brandColor': '#8B0000', 'type': 'CODE39',
        'chipLines': ['SO', 'GO'], 'chipSize': '0.55rem'
    },
    {
        'key': '新光三越', 'store': '新光三越', 'category': '百貨',
        'color': 'linear-gradient(135deg,#111,#333)',
        'brandColor': '#222222', 'type': 'CODE39',
        'chipLines': ['新光', '三越'], 'chipSize': '0.45rem'
    },
    {
        'key': '遠東百貨', 'store': '遠東百貨', 'category': '百貨',
        'color': 'linear-gradient(135deg,#002266,#003087)',
        'brandColor': '#003087', 'type': 'CODE39',
        'chipLines': ['遠東'], 'chipSize': '0.62rem'
    },
    {
        'key': '微風廣場', 'store': '微風廣場', 'category': '百貨',
        'color': 'linear-gradient(135deg,#4A3227,#5D4037)',
        'brandColor': '#5D4037', 'type': 'CODE39',
        'chipLines': ['微風'], 'chipSize': '0.62rem'
    },
    {
        'key': '星巴克', 'store': '星巴克', 'category': '餐飲',
        'color': 'linear-gradient(135deg,#005C39,#00704A)',
        'brandColor': '#00704A', 'type': 'QR_CODE',
        'chipLines': ['★'], 'chipSize': '1.0rem'
    },
    {
        'key': '路易莎', 'store': '路易莎', 'category': '餐飲',
        'color': 'linear-gradient(135deg,#8C3015,#B5451B)',
        'brandColor': '#B5451B', 'type': 'QR_CODE',
        'chipLines': ['Lo'], 'chipSize': '0.75rem'
    },
    {
        'key': '全聯', 'store': '全聯', 'category': '超市',
        'color': 'linear-gradient(135deg,#9E0000,#C62828)',
        'brandColor': '#C62828', 'type': 'EAN13',
        'chipLines': ['全聯'], 'chipSize': '0.62rem'
    }
]

def _member_infer_category(store_name: str) -> str:
    """根據商家名稱自動推測分類，優先比對預設品牌列表，否則做關鍵字比對"""
    import re
    n = (store_name or '').strip().lower()

    # 1. 優先比對統一品牌配置
    for brand in MEMBER_PRESET_BRANDS:
        if brand['store'].lower() in n or n in brand['store'].lower() or brand['key'].lower() in n:
            return brand['category']

    # 2. 備用的關鍵字模糊比對（容錯）
    if re.search(r'7-11|7-eleven|全家|萊爾富|ok超商|ok mart|便利商店', n):
        return '超商'
    if re.search(r'屈臣氏|watsons|康是美|cosmed|寶雅|poya|美妝|藥妝', n):
        return '藥妝'
    if re.search(r'新光三越|sogo|遠東|微風|統一時代|漢神|大遠百|百貨|購物中心|mall', n):
        return '百貨'
    if re.search(r'星巴克|starbucks|路易莎|louisa|麥當勞|mcdonald|肯德基|kfc|85度c|咖啡|餐飲|餐廳', n):
        return '餐飲'
    if re.search(r'全聯|家樂福|carrefour|大潤發|愛買|超市|量販', n):
        return '超市'
    if re.search(r'nike|adidas|under armour|迪卡儂|decathlon|運動|健身', n):
        return '運動'
    return '其他'


# 商家品牌色對照表（前端卡片配色用）
MEMBER_BRAND_COLORS = {
    '7-ELEVEN': '#00813A', '7-11': '#00813A',
    '全家': '#1B4799', '全家 FamilyMart': '#1B4799', 'FamilyMart': '#1B4799',
    '萊爾富': '#E5171B', '萊爾富 Hi-Life': '#E5171B',
    'OK超商': '#E8B21A',
    '新光三越': '#C8002D',
    '遠東百貨': '#003087',
    'SOGO': '#B02224',
    '微風': '#003865',
    '誠品': '#1A1A1A', '誠品書店': '#1A1A1A',
    '屈臣氏': '#00ADEF', "屈臣氏 Watson's": '#00ADEF',
    '康是美': '#D71920',
    '寶雅': '#E2001A', '寶雅 POYA': '#E2001A',
    '家樂福': '#003C8F',
    '好市多': '#E31837', '好市多 Costco': '#E31837',
    '路易莎': '#6B3A2A', '路易莎 Louisa': '#6B3A2A',
    '85度C': '#C8102E',
    '星巴克': '#00704A', '星巴克 Starbucks': '#00704A'
}

# 商家建議條碼類型對照表
MEMBER_BARCODE_TYPES = {
    '7-ELEVEN': 'CODE128', '7-11': 'CODE128',
    '全家': 'CODE128', '全家 FamilyMart': 'CODE128',
    '萊爾富': 'CODE128',
    'OK超商': 'CODE128',
    '新光三越': 'CODE39',
    '遠東百貨': 'CODE39',
    'SOGO': 'CODE39',
    '屈臣氏': 'EAN13',
    '康是美': 'EAN13',
    '寶雅': 'EAN13',
    '星巴克': 'QR_CODE', '星巴克 Starbucks': 'QR_CODE',
    '85度C': 'QR_CODE'
}

# 5分鐘 TTL 讀取快取（防止 Google Sheets API Rate Limit 429）
_members_cache = {}
_MEMBERS_CACHE_TTL = 300  # 秒


def _member_get_spreadsheet_id():
    """取得會員卡包所在的試算表 ID（沿用現有邏輯）"""
    return get_spreadsheet_id()


def _member_ensure_sheet(sheets_service, spreadsheet_id):
    """
    確保「會員卡包」工作表存在，若不存在則自動建立並寫入表頭。
    整合現有自癒守衛機制的設計模式。
    """
    try:
        sheet_meta = sheets_service.spreadsheets().get(
            spreadsheetId=spreadsheet_id
        ).execute()
        existing_titles = [s['properties']['title'] for s in sheet_meta.get('sheets', [])]

        if MEMBER_SHEET_NAME not in existing_titles:
            print(f"[Member Module] '{MEMBER_SHEET_NAME}' 工作表不存在，正在自動建立...")
            sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': [{'addSheet': {'properties': {'title': MEMBER_SHEET_NAME}}}]}
            ).execute()
            # 寫入表頭
            sheets_service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"{MEMBER_SHEET_NAME}!A1",
                valueInputOption='RAW',
                body={'values': [MEMBER_HEADERS]}
            ).execute()
            # 為表頭加上警告保護鎖（與現有模組一致）
            updated_meta = sheets_service.spreadsheets().get(
                spreadsheetId=spreadsheet_id
            ).execute()
            member_sheet_id = None
            for s in updated_meta.get('sheets', []):
                if s['properties']['title'] == MEMBER_SHEET_NAME:
                    member_sheet_id = s['properties']['sheetId']
                    break
            if member_sheet_id is not None:
                sheets_service.spreadsheets().batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={'requests': [{
                        'addProtectedRange': {
                            'protectedRange': {
                                'range': {
                                    'sheetId': member_sheet_id,
                                    'startRowIndex': 0, 'endRowIndex': 1,
                                    'startColumnIndex': 0, 'endColumnIndex': len(MEMBER_HEADERS)
                                },
                                'description': '系統 會員卡包 核心表頭，請勿任意變動以防當機',
                                'warningOnly': True
                            }
                        }
                    }]}
                ).execute()
            print(f"[Member Module] '{MEMBER_SHEET_NAME}' 工作表建立完成，表頭與保護鎖已設定。")
    except Exception as e:
        print(f"[Member Module] _member_ensure_sheet error: {e}")


def _member_sanitize_card_number(card_number: str) -> str:
    """
    後端卡號二次防禦過濾（前端正則已驗，後端再確認）。
    只允許英數字與連字號，長度上限 100 字元。
    """
    import re as _re
    if not _re.match(r'^[A-Za-z0-9\-]+$', str(card_number).strip()):
        raise ValueError('無效的卡號格式，只允許英數字與連字號')
    if len(card_number) > 100:
        raise ValueError('卡號長度超過 100 字元上限')
    return str(card_number).strip()


def _member_get_user_id():
    """取得目前 Session 的使用者識別碼（IDOR 防護核心）"""
    return session.get('user_email', session.get('user_id', 'default_user'))


def _member_read_all_from_sheet(sheets_service, spreadsheet_id, user_id):
    """
    從 Google Sheets 讀取指定 user_id 的所有會員卡記錄。
    使用 5 分鐘快取機制防止 API Rate Limit。
    Returns: (list, from_cache: bool)
    """
    import time as _time
    cache_key = f"{spreadsheet_id}:{user_id}"
    now = _time.time()
    cached = _members_cache.get(cache_key)
    if cached and (now - cached['ts']) < _MEMBERS_CACHE_TTL:
        return cached['data'], True

    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{MEMBER_SHEET_NAME}!A2:J"
        ).execute()
        rows = result.get('values', [])
        records = []
        for row in rows:
            # 補齊短行（防止欄位缺失）
            while len(row) < len(MEMBER_HEADERS):
                row.append('')
            record = dict(zip(MEMBER_HEADERS, row))
            
            # 對應前端所需的英文 key 回傳，避免改動前端程式碼
            mapped_record = {
                'card_id': record.get('卡片ID'),
                'user_id': record.get('使用者ID'),
                'store_name': record.get('商家名稱'),
                'card_number': record.get('卡號'),
                'barcode_type': record.get('條碼類型'),
                'note': record.get('備註'),
                'brand_color': record.get('品牌顏色'),
                'created_at': record.get('建立時間'),
                'updated_at': record.get('更新時間'),
                'category': record.get('卡片分類') or _member_infer_category(record.get('商家名稱', ''))
            }
            
            # 只回傳屬於該 user 的卡片（IDOR 防護）
            if mapped_record.get('user_id') == user_id and mapped_record.get('card_id'):
                records.append(mapped_record)
        _members_cache[cache_key] = {'data': records, 'ts': now}
        return records, False
    except Exception as e:
        print(f"[Member Module] _member_read_all_from_sheet error: {e}")
        # 快取失敗時回傳空清單
        return [], False


def _member_invalidate_cache(spreadsheet_id, user_id):
    """寫入/修改/刪除後立即清除快取，確保下次查詢取得最新資料"""
    cache_key = f"{spreadsheet_id}:{user_id}"
    _members_cache.pop(cache_key, None)


@app.route('/api/members', methods=['GET'])
def member_get_all():
    """
    [P2] 取得目前登入使用者的所有會員卡列表。
    快取命中時回傳 from_cache: true，不消耗 Google API 配額。
    ---
    Response: { success, data: [...], from_cache: bool, brand_colors: {...}, barcode_types: {...} }
    """
    user_id = _member_get_user_id()
    spreadsheet_id = _member_get_spreadsheet_id()
    if not spreadsheet_id:
        return jsonify({'success': False, 'message': '無法取得試算表 ID，請先登入'}), 401
    try:
        sheets_service = get_sheets_service()
        _member_ensure_sheet(sheets_service, spreadsheet_id)
        records, from_cache = _member_read_all_from_sheet(sheets_service, spreadsheet_id, user_id)
        return jsonify({
            'success': True,
            'data': records,
            'from_cache': from_cache,
            'brand_colors': MEMBER_BRAND_COLORS,
            'barcode_types': MEMBER_BARCODE_TYPES,
            'preset_brands': MEMBER_PRESET_BRANDS
        })
    except Exception as e:
        print(f"[Member Module] GET /api/members error: {e}")
        return jsonify({'success': False, 'message': f'讀取會員卡失敗: {str(e)}'}), 500


@app.route('/api/members', methods=['POST'])
def member_add():
    """
    [P2] 新增一張會員卡。
    卡號採用 RAW 模式寫入，搭配單引號前綴強制文字格式，防止前導零（如電話型卡號）被 Sheets 自動截斷。
    ---
    Request JSON: { store_name, card_number, barcode_type, note?, brand_color? }
    Response: { success, card_id, message }
    """
    user_id = _member_get_user_id()
    spreadsheet_id = _member_get_spreadsheet_id()
    if not spreadsheet_id:
        return jsonify({'success': False, 'message': '無法取得試算表 ID，請先登入'}), 401

    data = request.get_json() or {}
    store_name = str(data.get('store_name', '')).strip()
    card_number_raw = str(data.get('card_number', '')).strip()
    barcode_type = str(data.get('barcode_type', 'CODE128')).strip()
    note = str(data.get('note', '')).strip()
    brand_color = str(data.get('brand_color', '')).strip()
    category = str(data.get('category', '其他')).strip()

    # 必填欄位驗證
    if not store_name:
        return jsonify({'success': False, 'message': '商家名稱為必填'}), 400
    if not card_number_raw:
        return jsonify({'success': False, 'message': '卡號為必填'}), 400

    # 卡號後端安全過濾
    try:
        card_number = _member_sanitize_card_number(card_number_raw)
    except ValueError as ve:
        return jsonify({'success': False, 'message': str(ve)}), 400

    # 條碼類型白名單驗證
    allowed_barcode_types = {'CODE128', 'EAN13', 'CODE39', 'QR_CODE'}
    if barcode_type not in allowed_barcode_types:
        barcode_type = 'CODE128'

    # 若未傳品牌色，嘗試從對照表自動推斷
    if not brand_color:
        brand_color = MEMBER_BRAND_COLORS.get(store_name, '#C9B8A8')

    card_id = f"card_{datetime.now(TW_TZ).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
    now_str = datetime.now(TW_TZ).isoformat()

    # ⚠️ 卡號強制文字格式：前綴單引號 + RAW 寫入，防止 Sheets 自動將數字型卡號轉為整數
    row = [
        card_id,
        user_id,
        store_name,
        f"'{card_number}",   # 強制文字格式
        barcode_type,
        note,
        brand_color,
        now_str,
        now_str,
        category
    ]

    try:
        sheets_service = get_sheets_service()
        _member_ensure_sheet(sheets_service, spreadsheet_id)
        sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{MEMBER_SHEET_NAME}!A2",
            valueInputOption='RAW',
            body={'values': [row]}
        ).execute()
        _member_invalidate_cache(spreadsheet_id, user_id)
        print(f"[Member Module] 新增會員卡成功: {card_id} ({store_name}) for {user_id}")
        return jsonify({'success': True, 'card_id': card_id, 'message': f'{store_name} 的會員卡已成功新增！🎴'})
    except Exception as e:
        print(f"[Member Module] POST /api/members error: {e}")
        return jsonify({'success': False, 'message': f'新增會員卡失敗: {str(e)}'}), 500


@app.route('/api/members/<card_id>', methods=['PUT'])
def member_update(card_id):
    """
    [P2] 更新指定 card_id 的會員卡資料。
    透過逐列比對 card_id 與 user_id 雙重驗證，防止越權修改他人資料（IDOR 防護）。
    ---
    Request JSON: { store_name?, card_number?, barcode_type?, note?, brand_color? }
    Response: { success, message }
    """
    user_id = _member_get_user_id()
    spreadsheet_id = _member_get_spreadsheet_id()
    if not spreadsheet_id:
        return jsonify({'success': False, 'message': '無法取得試算表 ID，請先登入'}), 401

    data = request.get_json() or {}

    try:
        sheets_service = get_sheets_service()
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{MEMBER_SHEET_NAME}!A2:J"
        ).execute()
        rows = result.get('values', [])

        target_row_index = None
        for i, row in enumerate(rows):
            while len(row) < len(MEMBER_HEADERS):
                row.append('')
            record = dict(zip(MEMBER_HEADERS, row))
            # 雙重驗證：卡片ID 正確 且 使用者ID 吻合（IDOR 防護）
            if record.get('卡片ID') == card_id and record.get('使用者ID') == user_id:
                target_row_index = i
                break

        if target_row_index is None:
            return jsonify({'success': False, 'message': '找不到該會員卡，或您沒有權限修改'}), 404

        # 取得現有資料後做部分更新（未傳的欄位保留原值）
        old_row = rows[target_row_index]
        while len(old_row) < len(MEMBER_HEADERS):
            old_row.append('')
        old = dict(zip(MEMBER_HEADERS, old_row))

        store_name = str(data.get('store_name', old['商家名稱'])).strip() or old['商家名稱']
        barcode_type = str(data.get('barcode_type', old['條碼類型'])).strip() or old['條碼類型']
        note = data.get('note', old['備註'])
        brand_color = str(data.get('brand_color', old['品牌顏色'])).strip()
        category = str(data.get('category', old.get('卡片分類', '其他'))).strip()
        if not brand_color:
            brand_color = MEMBER_BRAND_COLORS.get(store_name, old.get('品牌顏色', '#C9B8A8'))

        # 卡號更新（若有傳新卡號才更新）
        if 'card_number' in data:
            try:
                new_card_number = _member_sanitize_card_number(str(data['card_number']))
                card_number_cell = f"'{new_card_number}"  # 強制文字格式
            except ValueError as ve:
                return jsonify({'success': False, 'message': str(ve)}), 400
        else:
            card_number_cell = old['卡號']  # 保留原值（含原本 the 單引號前綴）

        # 條碼類型白名單驗證
        allowed_barcode_types = {'CODE128', 'EAN13', 'CODE39', 'QR_CODE'}
        if barcode_type not in allowed_barcode_types:
            barcode_type = 'CODE128'

        updated_row = [
            card_id,
            user_id,
            store_name,
            card_number_cell,
            barcode_type,
            note,
            brand_color,
            old['建立時間'],
            datetime.now(TW_TZ).isoformat(),
            category
        ]

        # 計算實際行號（試算表 Row 1 = 表頭，資料從 Row 2 開始）
        sheet_row_number = target_row_index + 2
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{MEMBER_SHEET_NAME}!A{sheet_row_number}:J{sheet_row_number}",
            valueInputOption='RAW',
            body={'values': [updated_row]}
        ).execute()
        _member_invalidate_cache(spreadsheet_id, user_id)
        print(f"[Member Module] 更新會員卡成功: {card_id} for {user_id}")
        return jsonify({'success': True, 'message': '會員卡資料已成功更新！✅'})
    except Exception as e:
        print(f"[Member Module] PUT /api/members/{card_id} error: {e}")
        return jsonify({'success': False, 'message': f'更新會員卡失敗: {str(e)}'}), 500


@app.route('/api/members/<card_id>', methods=['DELETE'])
def member_delete(card_id):
    """
    [P2] 刪除指定 card_id 的會員卡。
    採用「清空列內容」策略（而非刪除整列），避免影響其他列的行號計算。
    透過 card_id + user_id 雙重驗證防止越權刪除（IDOR 防護）。
    ---
    Response: { success, message }
    """
    user_id = _member_get_user_id()
    spreadsheet_id = _member_get_spreadsheet_id()
    if not spreadsheet_id:
        return jsonify({'success': False, 'message': '無法取得試算表 ID，請先登入'}), 401

    try:
        sheets_service = get_sheets_service()
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{MEMBER_SHEET_NAME}!A2:J"
        ).execute()
        rows = result.get('values', [])

        target_row_index = None
        for i, row in enumerate(rows):
            while len(row) < len(MEMBER_HEADERS):
                row.append('')
            record = dict(zip(MEMBER_HEADERS, row))
            if record.get('卡片ID') == card_id and record.get('使用者ID') == user_id:
                target_row_index = i
                break

        if target_row_index is None:
            return jsonify({'success': False, 'message': '找不到該會員卡，或您沒有權限刪除'}), 404

        # 取得試算表中的 sheetId（用於 deleteDimension）
        sheet_meta = sheets_service.spreadsheets().get(
            spreadsheetId=spreadsheet_id
        ).execute()
        member_sheet_id = None
        for s in sheet_meta.get('sheets', []):
            if s['properties']['title'] == MEMBER_SHEET_NAME:
                member_sheet_id = s['properties']['sheetId']
                break

        if member_sheet_id is None:
            return jsonify({'success': False, 'message': '找不到會員卡包工作表'}), 500

        # 採用 deleteDimension 真正刪除整列，避免空白列殘留
        actual_row_index = target_row_index + 1  # +1 因為 index 0 = Row 1 表頭，資料從 index 1 開始
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={'requests': [{
                'deleteDimension': {
                    'range': {
                        'sheetId': member_sheet_id,
                        'dimension': 'ROWS',
                        'startIndex': actual_row_index,
                        'endIndex': actual_row_index + 1
                    }
                }
            }]}
        ).execute()
        _member_invalidate_cache(spreadsheet_id, user_id)
        print(f"[Member Module] 刪除會員卡成功: {card_id} for {user_id}")
        return jsonify({'success': True, 'message': '會員卡已成功刪除！🗑️'})
    except Exception as e:
        print(f"[Member Module] DELETE /api/members/{card_id} error: {e}")
        return jsonify({'success': False, 'message': f'刪除會員卡失敗: {str(e)}'}), 500


@app.route('/api/members/brands', methods=['GET'])
def member_get_brands():
    """
    [P2] 取得商家品牌資料庫（品牌色 + 建議條碼類型），供前端表單自動填入使用。
    ---
    Response: { success, brand_colors: {...}, barcode_types: {...} }
    """
    return jsonify({
        'success': True,
        'brand_colors': MEMBER_BRAND_COLORS,
        'barcode_types': MEMBER_BARCODE_TYPES,
        'preset_brands': MEMBER_PRESET_BRANDS
    })


# ===              END OF MEMBER CARD MODULE                    ===
# ================================================================

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
    # 確保 users 表訂閱過期欄位已初始化自癒
    init_users_table_migration()
    # 確保蝦皮分潤連結表已初始化自癒
    init_shopee_links_table()

    # 啟動背景執行緒，自動非同步與 TWSE/TPEx 同步全台灣股票與 ETF
    import threading
    threading.Thread(target=sync_taiwan_stocks_to_db, daemon=True).start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)

