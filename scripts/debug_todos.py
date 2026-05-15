import os
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'service_account.json'
TODO_SHEET_ID = os.getenv('TODO_SHEET_ID')

creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build('sheets', 'v4', credentials=creds)

def get_sheet_values(range_name, spreadsheet_id):
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name
    ).execute()
    return result.get('values', [])

print(f"Checking Todo Sheet: {TODO_SHEET_ID}")
rows = get_sheet_values('待辦!A:G', TODO_SHEET_ID)
if not rows:
    print("No data found.")
else:
    headers = rows[0]
    print(f"Headers: {headers}")
    for i, row in enumerate(rows[1:], start=2):
        print(f"Row {i}: {row}")
