import os
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '../ai-personal-secretary/.env'))

SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
SERVICE_ACCOUNT_FILE = os.path.join(os.path.dirname(__file__), '../ai-personal-secretary/service_account.json')

def check_sheet_title(spreadsheet_id, label):
    if not spreadsheet_id:
        print(f"{label}: ID is missing")
        return
    try:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        service = build('sheets', 'v4', credentials=creds)
        spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = spreadsheet.get('sheets', [])
        titles = [s['properties']['title'] for s in sheets]
        print(f"{label} ({spreadsheet_id}): {titles}")
    except Exception as e:
        print(f"{label} ({spreadsheet_id}): Error - {e}")

ids = {
    "Expense (GOOGLE_SHEET_ID)": os.getenv('GOOGLE_SHEET_ID'),
    "Diary (DIARY_SHEET_ID)": os.getenv('DIARY_SHEET_ID'),
    "Todo (TODO_SHEET_ID)": os.getenv('TODO_SHEET_ID'),
    "Wish (WISH_SHEET_ID)": os.getenv('WISH_SHEET_ID')
}

for label, sid in ids.items():
    check_sheet_title(sid, label)
