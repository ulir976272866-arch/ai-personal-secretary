import os
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'service_account.json'
SPREADSHEET_ID = '1RkhMRiRBIn7zYJKuT0Qr4tXCx-VxjBF3c6AuYOR3mgg'

def setup_foundation():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build('sheets', 'v4', credentials=creds)
    
    # 1. 獲取試算表資訊，確認分頁是否存在
    spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    sheet_names = [sheet['properties']['title'] for sheet in spreadsheet['sheets']]

    requests = []

    # 2. 建立「生理紀錄」分頁
    if "生理紀錄" not in sheet_names:
        requests.append({
            'addSheet': {
                'properties': {
                    'title': '生理紀錄',
                    'gridProperties': {'rowCount': 200, 'columnCount': 10}
                }
            }
        })

    # 3. 建立「AI_指令集」分頁
    if "AI_指令集" not in sheet_names:
        requests.append({
            'addSheet': {
                'properties': {
                    'title': 'AI_指令集',
                    'gridProperties': {'rowCount': 100, 'columnCount': 5}
                }
            }
        })

    if requests:
        body = {'requests': requests}
        service.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body=body).execute()
        print("Success: Created missing worksheets.")

    # 4. 寫入標題與歷史數據
    history_data = [
        ["年度", "月份", "開始日期", "結束日期", "經期天數", "週期天數", "備註"],
        ["2025", "04", "2025/04/30", "", "", "", "目前進行中"],
        ["2025", "03", "2025/03/27", "2025/04/29", "14", "34", "匯入自 PDF"],
        ["2025", "03", "2025/03/08", "2025/03/26", "9", "19", "匯入自 PDF"],
        ["2025", "02", "2025/02/07", "2025/03/07", "9", "29", "匯入自 PDF"],
        ["2025", "01", "2025/01/11", "2025/02/06", "9", "27", "匯入自 PDF"],
        ["2024", "12", "2024/12/09", "2025/01/10", "8", "33", "匯入自 PDF"],
        ["2024", "11", "2024/11/11", "2024/12/08", "9", "28", "匯入自 PDF"],
        ["2024", "10", "2024/10/14", "2024/11/10", "9", "28", "匯入自 PDF"],
        ["2024", "09", "2024/09/16", "2024/10/13", "8", "28", "匯入自 PDF"],
        ["2024", "08", "2024/08/20", "2024/09/15", "11", "27", "匯入自 PDF"],
        ["2024", "07", "2024/07/27", "2024/08/19", "7", "24", "匯入自 PDF"],
        ["2024", "06", "2024/06/20", "2024/07/26", "7", "37", "匯入自 PDF"]
    ]

    # 寫入 AI 指令集標題
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID, range="AI_指令集!A1:C1",
        valueInputOption="USER_ENTERED", body={"values": [["當我說", "期望行為", "備註"]]}
    ).execute()

    # 寫入生理紀錄
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID, range="生理紀錄!A1:G14",
        valueInputOption="USER_ENTERED", body={"values": history_data}
    ).execute()
    
    print("Success: Imported 12 months of historical data to '生理紀錄'.")

if __name__ == "__main__":
    setup_foundation()
