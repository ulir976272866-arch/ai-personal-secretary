import os
import re
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv('.env')

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'service_account.json'

CATEGORY_EMOJI_MAP = {
    "食": "🍔", "衣": "👔", "住": "🏠", "行": "🚗", "育": "📚", "樂": "🎬", "醫": "🏥", "投資": "📈", "公益": "💖", "未分類": "❓",
    "薪資": "💰", "獎金": "🧧", "投資獲利": "💹", "退款": "🔙", "其他進帳": "🪙"
}

def format_category_with_emoji(category, is_income=False):
    if not category:
        return "❓ 未分類"
        
    category_clean = str(category).strip()
    
    if ' ' in category_clean:
        parts = category_clean.split(' ', 1)
        if len(parts) == 2 and len(parts[0]) > 0:
            return category_clean
            
    for cat_name, emoji in CATEGORY_EMOJI_MAP.items():
        if cat_name in category_clean:
            return f"{emoji} {cat_name}"
            
    default_emoji = "💰" if is_income else "📝"
    return f"{default_emoji} {category_clean}"

def cleanup_sheet_categories():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    sheets_service = build('sheets', 'v4', credentials=creds)
    spreadsheet_id = os.getenv('GOOGLE_SHEET_ID')
    
    if not spreadsheet_id:
        print("Error: GOOGLE_SHEET_ID not found in .env")
        return

    # Read the sheet range
    res = sheets_service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range='記帳!A:G'
    ).execute()
    rows = res.get('values', [])
    
    if not rows:
        print("No rows found.")
        return

    updates = []
    
    for idx, row in enumerate(rows[1:], start=2): # Row 1 is header, 1-indexed
        if len(row) >= 7:
            current_cat = row[6]
            # Detect if it's income or expense based on D column
            is_income = len(row) > 3 and row[3].strip() != ""
            formatted = format_category_with_emoji(current_cat, is_income)
            
            if formatted != current_cat:
                print(f"Row {idx}: Updating '{current_cat}' -> '{formatted}'")
                updates.append({
                    'range': f'記帳!G{idx}',
                    'values': [[formatted]]
                })
        elif len(row) == 6:
            # Missing category column, set to 未分類
            is_income = len(row) > 3 and row[3].strip() != ""
            formatted = "❓ 未分類"
            print(f"Row {idx}: Missing category. Setting to '{formatted}'")
            updates.append({
                'range': f'記帳!G{idx}',
                'values': [[formatted]]
            })

    if updates:
        body = {
            'valueInputOption': 'USER_ENTERED',
            'data': updates
        }
        sheets_service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id, body=body
        ).execute()
        print(f"Successfully cleaned up {len(updates)} rows in Google Sheets! 🎉")
    else:
        print("All rows are already using correct emoji category formats.")

if __name__ == "__main__":
    cleanup_sheet_categories()
