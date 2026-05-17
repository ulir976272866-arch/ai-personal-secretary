import os
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv('.env')

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'service_account.json'

def fix_misplaced_cycle():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    sheets_service = build('sheets', 'v4', credentials=creds)
    health_sheet_id = os.getenv('HEALTH_SHEET_ID')
    
    if not health_sheet_id:
        print("Error: HEALTH_SHEET_ID not found in .env")
        return

    # 讀取前 3 行
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=health_sheet_id, range="生理紀錄!A1:G4"
    ).execute()
    rows = result.get('values', [])
    
    if len(rows) >= 3:
        # Row 1 is header. Row 2 is latest (e.g., 5/18). Row 3 is previous (e.g., 4/30).
        row2 = rows[1]
        row3 = rows[2]
        
        # 檢查 row2 是否有週期天數 (誤寫入的)
        if len(row2) > 5 and row2[5].strip() != "":
            misplaced_cycle = row2[5].strip()
            print(f"Found misplaced cycle {misplaced_cycle} on Row 2.")
            
            # 清除 Row 2 的 F 欄 (週期)
            sheets_service.spreadsheets().values().update(
                spreadsheetId=health_sheet_id, range="生理紀錄!F2",
                valueInputOption="USER_ENTERED", body={"values": [[""]]}
            ).execute()
            print("Cleared Row 2's cycle field.")
            
            # 將它寫入 Row 3 的 F 欄
            sheets_service.spreadsheets().values().update(
                spreadsheetId=health_sheet_id, range="生理紀錄!F3",
                valueInputOption="USER_ENTERED", body={"values": [[misplaced_cycle]]}
            ).execute()
            print(f"Moved cycle {misplaced_cycle} to Row 3.")
        else:
            print("No misplaced cycle found on Row 2.")
    else:
        print("Not enough rows to check.")

if __name__ == "__main__":
    fix_misplaced_cycle()
