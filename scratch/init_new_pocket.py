import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

SERVICE_ACCOUNT_FILE = 'service_account.json'
POCKET_SHEET_ID = '131OAfDjrf_5rA7Rjezye2aogyub7fSs4OnJltqU36tY'

def init_new_pocket_sheet():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    service = build('sheets', 'v4', credentials=creds)

    # 設定表頭
    values = [['名稱', '地點', '備註', '類別']]
    body = {'values': values}
    try:
        service.spreadsheets().values().update(
            spreadsheetId=POCKET_SHEET_ID, range='A1',
            valueInputOption='RAW', body=body).execute()
        print('Headers set in the NEW pocket sheet.')
    except Exception as e:
        print(f"Error setting headers: {e}")

if __name__ == '__main__':
    init_new_pocket_sheet()
