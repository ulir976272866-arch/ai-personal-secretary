import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

SERVICE_ACCOUNT_FILE = 'service_account.json'
POCKET_SHEET_ID = '131OAfDjrf_5rA7Rjezye2aogyub7fSs4OnJltqU36tY'

def upgrade_pocket_sheet():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    service = build('sheets', 'v4', credentials=creds)

    # 設定全新的標頭：ID, 類別, 名稱, 地點, 備註, 建立時間
    values = [['ID', '類別', '名稱', '地點', '備註', '建立時間']]
    body = {'values': values}
    try:
        service.spreadsheets().values().update(
            spreadsheetId=POCKET_SHEET_ID, range='A1',
            valueInputOption='RAW', body=body).execute()
        print('Spreadsheet upgraded with ID and new headers.')
    except Exception as e:
        print(f"Error upgrading headers: {e}")

if __name__ == '__main__':
    upgrade_pocket_sheet()
