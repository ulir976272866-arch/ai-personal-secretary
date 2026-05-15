import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

# 設定憑證
SERVICE_ACCOUNT_FILE = 'service_account.json'
USER_EMAIL = 'ulir976272866@gmail.com'

def create_pocket_sheet():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    )
    
    # 1. 建立試算表
    sheets_service = build('sheets', 'v4', credentials=creds)
    spreadsheet = {
        'properties': {
            'title': '私人助理-口袋名單'
        }
    }
    spreadsheet = sheets_service.spreadsheets().create(body=spreadsheet, fields='spreadsheetId').execute()
    spreadsheet_id = spreadsheet.get('spreadsheetId')
    print(f'Created Spreadsheet ID: {spreadsheet_id}')

    # 2. 設定表頭
    values = [['名稱', '地點', '備註', '類別']]
    body = {'values': values}
    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range='Sheet1!A1',
        valueInputOption='RAW', body=body).execute()
    print('Headers set.')

    # 3. 分享給使用者
    drive_service = build('drive', 'v3', credentials=creds)
    user_permission = {
        'type': 'user',
        'role': 'writer',
        'emailAddress': USER_EMAIL
    }
    drive_service.permissions().create(
        fileId=spreadsheet_id,
        body=user_permission,
        fields='id'
    ).execute()
    print(f'Shared with {USER_EMAIL}')

    return spreadsheet_id

if __name__ == '__main__':
    new_id = create_pocket_sheet()
    print(f'SUCCESS_ID:{new_id}')
