import os
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv('.env')

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'service_account.json'

def inspect_sheets():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    sheets_service = build('sheets', 'v4', credentials=creds)
    spreadsheet_id = os.getenv('GOOGLE_SHEET_ID')
    
    if not spreadsheet_id:
        print("Error: GOOGLE_SHEET_ID not found in .env")
        return

    sh = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    print("Sheets available:")
    for s in sh['sheets']:
        print(f"- {s['properties']['title']} (ID: {s['properties']['sheetId']})")

if __name__ == "__main__":
    inspect_sheets()
