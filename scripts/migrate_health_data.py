import os
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = 'service_account.json'
OLD_SPREADSHEET_ID = '1RkhMRiRBIn7zYJKuT0Qr4tXCx-VxjBF3c6AuYOR3mgg'

def migrate():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)
    
    # 1. 搜尋目標資料夾「私人秘書專用」
    print("Searching for target folder...")
    folder_query = "name = '私人秘書專用' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    folder_results = drive_service.files().list(q=folder_query, spaces='drive').execute()
    folders = folder_results.get('files', [])
    
    parent_id = None
    if not folders:
        print("Warning: Folder '私人秘書專用' not found. Creating it in root.")
        # 如果沒找到，先試著找「01 AI coding」
        # 這裡為了保險，我們直接建立一個，或是您可以稍後手動搬移
        folder_metadata = {
            'name': '私人秘書專用',
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = drive_service.files().create(body=folder_metadata, fields='id').execute()
        parent_id = folder.get('id')
    else:
        parent_id = folders[0]['id']
        print(f"Success: Found folder ID: {parent_id}")

    # 2. 建立新的試算表「AI秘書-生理健康」
    print("Creating new spreadsheet...")
    file_metadata = {
        'name': 'AI秘書-生理健康',
        'mimeType': 'application/vnd.google-apps.spreadsheet',
        'parents': [parent_id]
    }
    new_sh = drive_service.files().create(body=file_metadata, fields='id').execute()
    new_sh_id = new_sh.get('id')
    print(f"Success: Created new spreadsheet ID: {new_sh_id}")

    # 3. 在新文件中初始化分頁與數據
    print("Initializing worksheets and data...")
    # 建立「生理紀錄」
    history_data = [
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
        ["2025", "07", "2025/07/25", "2025/08/19", "8", "26", "匯入自 PDF"],
        ["2025", "06", "2025/06/30", "2025/07/24", "9", "25", "匯入自 PDF"],
        ["2025", "06", "2025/06/03", "2025/06/29", "8", "27", "匯入自 PDF"],
        ["2025", "05", "2025/05/05", "2025/06/02", "6", "29", "匯入自 PDF"],
        ["2025", "04", "2025/04/10", "2025/05/04", "8", "25", "匯入自 PDF"]
    ]

    requests = [
        {
            'addSheet': {
                'properties': {
                    'title': '生理紀錄',
                    'gridProperties': {'rowCount': 200, 'columnCount': 10}
                }
            }
        },
        {
            'addSheet': {
                'properties': {
                    'title': 'AI_指令集',
                    'gridProperties': {'rowCount': 100, 'columnCount': 5}
                }
            }
        }
    ]
    sheets_service.spreadsheets().batchUpdate(spreadsheetId=new_sh_id, body={'requests': requests}).execute()
    
    # 寫入數據
    sheets_service.spreadsheets().values().update(
        spreadsheetId=new_sh_id, range="生理紀錄!A1:G16",
        valueInputOption="USER_ENTERED", body={"values": history_data}
    ).execute()
    
    sheets_service.spreadsheets().values().update(
        spreadsheetId=new_sh_id, range="AI_指令集!A1:C1",
        valueInputOption="USER_ENTERED", body={"values": [["當我說", "期望行為", "備註"]]}
    ).execute()

    # 4. 清理舊的試算表分頁
    print("Cleaning up old spreadsheet...")
    old_sh = sheets_service.spreadsheets().get(spreadsheetId=OLD_SPREADSHEET_ID).execute()
    old_sheet_ids = {s['properties']['title']: s['properties']['sheetId'] for s in old_sh['sheets']}
    
    delete_requests = []
    if "生理紀錄" in old_sheet_ids:
        delete_requests.append({'deleteSheet': {'sheetId': old_sheet_ids['生理紀錄']}})
    if "AI_指令集" in old_sheet_ids:
        delete_requests.append({'deleteSheet': {'sheetId': old_sheet_ids['AI_指令集']}})
    
    if delete_requests:
        sheets_service.spreadsheets().batchUpdate(spreadsheetId=OLD_SPREADSHEET_ID, body={'requests': delete_requests}).execute()
        print("Success: Cleaned up old worksheets.")

    print(f"\n--- Migration Complete ---")
    print(f"New Health Sheet ID: {new_sh_id}")
    print(f"URL: https://docs.google.com/spreadsheets/d/{new_sh_id}/edit")

if __name__ == "__main__":
    migrate()
