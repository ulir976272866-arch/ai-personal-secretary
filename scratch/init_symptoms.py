import os
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv('.env')

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'service_account.json'

def init_symptom_sheet():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    sheets_service = build('sheets', 'v4', credentials=creds)
    health_sheet_id = os.getenv('HEALTH_SHEET_ID')
    
    if not health_sheet_id:
        print("Error: HEALTH_SHEET_ID not found in .env")
        return

    # Check if sheet already exists
    sh = sheets_service.spreadsheets().get(spreadsheetId=health_sheet_id).execute()
    sheet_exists = any(s['properties']['title'] == '症狀選項' for s in sh['sheets'])
    
    if not sheet_exists:
        requests = [{
            'addSheet': {
                'properties': {
                    'title': '症狀選項',
                    'gridProperties': {'rowCount': 100, 'columnCount': 2}
                }
            }
        }]
        sheets_service.spreadsheets().batchUpdate(spreadsheetId=health_sheet_id, body={'requests': requests}).execute()
        print("Created '症狀選項' sheet.")
    else:
        print("'症狀選項' sheet already exists.")
        
    # Write defaults
    defaults = [["症狀名稱"], ["經痛"], ["頭痛"], ["情緒起伏"], ["長痘痘"], ["腰酸背痛"], ["嗜睡"]]
    sheets_service.spreadsheets().values().update(
        spreadsheetId=health_sheet_id, range="症狀選項!A1:A7",
        valueInputOption="USER_ENTERED", body={"values": defaults}
    ).execute()
    print("Default symptoms written.")

if __name__ == "__main__":
    init_symptom_sheet()
