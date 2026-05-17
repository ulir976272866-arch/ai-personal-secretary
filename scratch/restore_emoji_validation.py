import os
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv('.env')

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'service_account.json'

def apply_beautiful_data_validation():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    sheets_service = build('sheets', 'v4', credentials=creds)
    spreadsheet_id = os.getenv('GOOGLE_SHEET_ID')
    
    if not spreadsheet_id:
        print("Error: GOOGLE_SHEET_ID not found in .env")
        return

    # Fetch sheet ID for '記帳'
    res = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet = res['sheets'][0]
    sheet_id = sheet['properties']['sheetId']

    # New beautiful emoji categories list
    emoji_categories = [
        "🍔 食",
        "👔 衣",
        "🏠 住",
        "🚗 行",
        "📚 育",
        "🎬 樂",
        "🏥 醫",
        "📈 投資",
        "💖 公益",
        "❓ 未分類",
        "💰 薪資",
        "🧧 獎金",
        "💹 投資獲利",
        "🔙 退款",
        "🪙 其他進帳"
    ]

    # Create the ONE_OF_LIST validation rule
    rule = {
        'condition': {
            'type': 'ONE_OF_LIST',
            'values': [{'userEnteredValue': cat} for cat in emoji_categories]
        },
        'strict': True,
        'showCustomUi': True
    }

    requests = [{
        'setDataValidation': {
            'range': {
                'sheetId': sheet_id,
                'startRowIndex': 1, # Row 2 onwards
                'startColumnIndex': 6, # Column G (0-indexed)
                'endColumnIndex': 7
            },
            'rule': rule
        }
    }]

    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={'requests': requests}
    ).execute()
    print("Successfully restored and beautified emoji validation rules in Google Sheets! 🎉")

if __name__ == "__main__":
    apply_beautiful_data_validation()
