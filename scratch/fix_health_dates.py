import os
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv('.env')

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'service_account.json'

def fix_dates():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    sheets_service = build('sheets', 'v4', credentials=creds)
    health_sheet_id = os.getenv('HEALTH_SHEET_ID')
    
    if not health_sheet_id:
        print("Error: HEALTH_SHEET_ID not found in .env")
        return

    # 正確的 2025~2026 年資料
    correct_data = [
        ["年度", "月份", "開始日期", "結束日期", "經期天數", "週期天數", "備註"],
        ["2026", "04", "2026/04/30", "", "", "", "目前進行中"],
        ["2026", "03", "2026/03/27", "2026/04/29", "14", "34", "匯入自 PDF"],
        ["2026", "03", "2026/03/08", "2026/03/26", "9", "19", "匯入自 PDF"],
        ["2026", "02", "2026/02/07", "2026/03/07", "9", "29", "匯入自 PDF"],
        ["2026", "01", "2026/01/11", "2026/02/06", "9", "27", "匯入自 PDF"],
        ["2025", "12", "2025/12/09", "2026/01/10", "8", "33", "匯入自 PDF"],
        ["2025", "11", "2025/11/11", "2025/12/08", "9", "28", "匯入自 PDF"],
        ["2025", "10", "2025/10/14", "2025/11/10", "9", "28", "匯入自 PDF"],
        ["2025", "09", "2025/09/16", "2025/10/13", "8", "28", "匯入自 PDF"],
        ["2025", "08", "2025/08/20", "2025/09/15", "11", "27", "匯入自 PDF"],
        ["2025", "07", "2025/07/27", "2025/08/19", "8", "26", "匯入自 PDF"], # 修正從 PDF 讀取到的正確資料
        ["2025", "06", "2025/06/30", "2025/07/24", "9", "25", "匯入自 PDF"],
        ["2025", "06", "2025/06/03", "2025/06/29", "8", "27", "匯入自 PDF"],
        ["2025", "05", "2025/05/05", "2025/06/02", "6", "29", "匯入自 PDF"],
        ["2025", "04", "2025/04/10", "2025/05/04", "8", "25", "匯入自 PDF"],
    ]
    
    # 寫入覆蓋前 16 行
    sheets_service.spreadsheets().values().update(
        spreadsheetId=health_sheet_id, range="生理紀錄!A1:G16",
        valueInputOption="USER_ENTERED", body={"values": correct_data}
    ).execute()
    print("Success: 已經修正 Google Sheet 中的年份錯誤！")

if __name__ == "__main__":
    fix_dates()
