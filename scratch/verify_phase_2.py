import os
from dotenv import load_dotenv
from googleapiclient.discovery import build
import json

# Load environments
load_dotenv('/Users/yinmin/0_Ai coding/私人行事曆安排/ai-personal-secretary/.env')

# Setup google sheets service
import sys
sys.path.append('/Users/yinmin/0_Ai coding/私人行事曆安排/ai-personal-secretary')
from app import get_user_by_email, CLIENT_ID, CLIENT_SECRET
from google.oauth2.credentials import Credentials as OAuthCredentials

creds_user = None
email = "ulir976272866@gmail.com"
try:
    user = get_user_by_email(email)
    if user and user.get('google_refresh_token'):
        creds_user = OAuthCredentials(
            token=None,
            refresh_token=user['google_refresh_token'],
            token_uri='https://oauth2.googleapis.com/token',
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive.file']
        )
        print("Success: Loaded user credentials from TiDB database.")
except Exception as ex:
    print(f"Error loading user credentials from TiDB: {ex}")

creds_sa = None
if not creds_user:
    from google.oauth2 import service_account
    sa_path = '/Users/yinmin/0_Ai coding/私人行事曆安排/ai-personal-secretary/service_account.json'
    if os.path.exists(sa_path):
        try:
            creds_sa = service_account.Credentials.from_service_account_file(
                sa_path,
                scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
            )
            print("Success: Loaded service account credentials.")
        except Exception as e:
            print(f"Error loading service account: {e}")

if not creds_user and not creds_sa:
    print("Failed to load any credentials, cannot run sheet test.")
    exit(1)

sheets_service = build('sheets', 'v4', credentials=creds_user or creds_sa)
spreadsheet_id = os.getenv('GOOGLE_SHEET_ID')

print(f"Targeting Spreadsheet: {spreadsheet_id}")

try:
    # 1. Fetch spreadsheet metadata to check if tab exists
    sheet_meta = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    titles = [s['properties']['title'] for s in sheet_meta.get('sheets', [])]
    print(f"Existing tabs before check: {titles}")
    
    # 2. Check missing sheets
    required_sheets = {
        '記帳分類習慣': [['關鍵字', '母分類', '子分類', '收支類型', '使用次數']]
    }
    
    missing_sheets = [title for title in required_sheets.keys() if title not in titles]
    if missing_sheets:
        print(f"Missing sheet '{missing_sheets}' detected. Running self-healing...")
        # Create sheet
        add_requests = [{'addSheet': {'properties': {'title': title}}} for title in missing_sheets]
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={'requests': add_requests}
        ).execute()
        
        # Write headers
        for title in missing_sheets:
            header_values = required_sheets[title]
            range_name = f"{title}!A1"
            sheets_service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption='USER_ENTERED',
                body={'values': header_values}
            ).execute()
            print(f"Restored sheet '{title}' and headers successfully!")
            
        # Re-fetch metadata
        sheet_meta = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        titles = [s['properties']['title'] for s in sheet_meta.get('sheets', [])]
        print(f"Existing tabs after creation: {titles}")
    else:
        print("記帳分類習慣 tab already exists! Self-healing works.")
        
    # 3. Check and apply warning locks for '記帳分類習慣'
    target_sheet = next(s for s in sheet_meta.get('sheets', []) if s['properties']['title'] == '記帳分類習慣')
    s_id = target_sheet['properties']['sheetId']
    has_protection = any(
        p.get('range', {}).get('startRowIndex') == 0 and p.get('range', {}).get('endRowIndex') == 1
        for p in target_sheet.get('protectedRanges', [])
    )
    
    if not has_protection:
        print("Applying Warning Protection Lock on '記帳分類習慣' Row 1...")
        protect_request = {
            "addProtectedRange": {
                "protectedRange": {
                    "range": {
                        "sheetId": s_id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": 5
                    },
                    "description": "系統 記帳分類習慣 核心表頭，請勿任意變動以防當機",
                    "warningOnly": True
                }
            }
        }
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={'requests': [protect_request]}
        ).execute()
        print("Warning Protection Lock successfully applied!")
    else:
        print("Warning Protection Lock already applied on '記帳分類習慣' Row 1.")
        
except Exception as e:
    print(f"Execution failed: {e}")
