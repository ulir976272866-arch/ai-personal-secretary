import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

SERVICE_ACCOUNT_FILE = 'service_account.json'
SPREADSHEET_ID = '1RkhMRiRBIn7zYJKuT0Qr4tXCx-VxjBF3c6AuYOR3mgg'

def add_pocket_tab():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    service = build('sheets', 'v4', credentials=creds)

    # 1. 新增分頁
    try:
        body = {
            'requests': [
                {
                    'addSheet': {
                        'properties': {
                            'title': '口袋名單'
                        }
                    }
                }
            ]
        }
        service.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body=body).execute()
        print('Added "口袋名單" tab.')
    except Exception as e:
        if "already exists" in str(e):
            print('Tab "口袋名單" already exists.')
        else:
            raise e

    # 2. 設定表頭
    values = [['名稱', '地點', '備註', '類別']]
    body = {'values': values}
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID, range='口袋名單!A1',
        valueInputOption='RAW', body=body).execute()
    print('Headers set in "口袋名單" tab.')

if __name__ == '__main__':
    add_pocket_tab()
