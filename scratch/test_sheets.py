import os
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'service_account.json'

def test_sheet(sheet_id, range_name):
    print(f"Testing Sheet ID: {sheet_id}, Range: {range_name}")
    try:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        service = build('sheets', 'v4', credentials=creds)
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=range_name
        ).execute()
        values = result.get('values', [])
        print(f"Success! Found {len(values)} rows.")
        if values:
            print(f"Headers: {values[0]}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    todo_id = os.getenv('TODO_SHEET_ID')
    wish_id = os.getenv('WISH_SHEET_ID')
    
    test_sheet(todo_id, '待辦!A:F')
    test_sheet(wish_id, '願望清單!A:I')
