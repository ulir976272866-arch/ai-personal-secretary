import os
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv('.env')

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'service_account.json'

def inspect_recent():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    sheets_service = build('sheets', 'v4', credentials=creds)
    spreadsheet_id = os.getenv('GOOGLE_SHEET_ID')
    
    if not spreadsheet_id:
        print("Error: GOOGLE_SHEET_ID not found in .env")
        return

    try:
        res = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range='記帳!A:G'
        ).execute()
        rows = res.get('values', [])
        print(f"Total rows in '記帳' tab: {len(rows)}")
        print("\nLast 15 rows:")
        header = rows[0] if rows else []
        print(f"Header: {header}")
        print("-" * 80)
        for i, row in enumerate(rows[-15:], max(1, len(rows) - 14)):
            print(f"Row {i}: {row}")
    except Exception as e:
        print(f"Error reading sheets: {e}")

if __name__ == "__main__":
    inspect_recent()
