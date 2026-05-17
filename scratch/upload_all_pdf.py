import os
import csv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv('.env')

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'service_account.json'

def upload_records():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    sheets_service = build('sheets', 'v4', credentials=creds)
    health_sheet_id = os.getenv('HEALTH_SHEET_ID')
    
    if not health_sheet_id:
        print("Error: HEALTH_SHEET_ID not found in .env")
        return

    records = []
    with open('parsed_records.csv', 'r') as f:
        reader = csv.reader(f)
        for row in reader:
            records.append(row)
            
    print(f"Uploading {len(records)} rows to Google Sheet...")
    
    # 寫入覆蓋
    sheets_service.spreadsheets().values().update(
        spreadsheetId=health_sheet_id, range=f"生理紀錄!A1:G{len(records)}",
        valueInputOption="USER_ENTERED", body={"values": records}
    ).execute()
    print("Success: 已經成功匯入所有歷史紀錄！")

if __name__ == "__main__":
    upload_records()
