import os
import sys
import json
import base64
import hashlib
import time
from dotenv import load_dotenv

# Ensure import paths are set correctly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load env variables
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'), override=True)

# Import targets from app.py
from app import (
    app,
    get_fernet_for_email,
    get_learning_rules_prompt,
    save_or_update_habit,
    sync_diary_to_drive,
    get_spreadsheet_id
)
from flask import session

def test_fernet_derivation():
    print("\n--- [Test 1] Deterministic Fernet Key Derivation ---")
    email1 = "test@example.com"
    email2 = "Test@Example.com "
    
    fernet1 = get_fernet_for_email(email1)
    fernet2 = get_fernet_for_email(email2)
    
    test_msg = "Hello secure secret world!"
    enc_msg = fernet1.encrypt(test_msg.encode('utf-8'))
    
    dec_msg = fernet2.decrypt(enc_msg).decode('utf-8')
    print(f"Original: {test_msg}")
    print(f"Decrypted: {dec_msg}")
    assert test_msg == dec_msg, "Fernet encryption/decryption failed!"
    print("✅ Deterministic Fernet check passed!")

def test_learning_prompt(email):
    print("\n--- [Test 2] Rule Merge & Prompt Generation ---")
    prompt_str = get_learning_rules_prompt(email)
    print("Generated learning prompt preview:")
    print(prompt_str[:500] + "...")
    print("✅ Learning rules prompt generated successfully!")

def test_save_habit(email):
    print("\n--- [Test 3] Habit Updating (Google Sheet + TiDB) ---")
    save_or_update_habit(
        email=email,
        keyword="壽司測試",
        category="食",
        sub_category="晚餐",
        expense_type="expense"
    )
    print("✅ save_or_update_habit executed without exceptions!")

def test_drive_sync(email):
    print("\n--- [Test 4] Google Drive Encryption & structured Sync ---")
    spreadsheet_id = get_spreadsheet_id()
    print(f"Using Spreadsheet ID: {spreadsheet_id}")
    if spreadsheet_id:
        from app import get_sheets_service, get_valid_credentials, get_or_create_drive_folder
        from googleapiclient.discovery import build
        service_sheets = get_sheets_service()
        
        # 1. 寫入一列臨時日記資料，用於測試同步
        print("Writing a temporary test diary row to '日記' sheet...")
        test_row = ['2026-06-10', '測試日記：今天完成了第四到第六階段的聯調驗證！', '晴', '高興', '12:00:00']
        service_sheets.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range='日記!A:E',
            valueInputOption='USER_ENTERED',
            body={'values': [test_row]}
        ).execute()
        
        # 2. 觸發同步
        creds = get_valid_credentials()
        sync_diary_to_drive(email, spreadsheet_id, creds=creds)
        print("✅ sync_diary_to_drive background task triggered successfully!")
        
        # 3. 等待同步執行完畢
        print("⏳ Waiting 5 seconds for Drive upload task to finish...")
        time.sleep(5)
        
        # 4. 查詢 Google Drive 並列出該資料夾底下的檔案以驗證上傳
        print("Querying Google Drive to list files in 'AI_秘書_日記備份' folder...")
        try:
            service_drive = build('drive', 'v3', credentials=creds)
            folder_id = get_or_create_drive_folder(service_drive, "AI_秘書_日記備份")
            results = service_drive.files().list(
                q=f"'{folder_id}' in parents and trashed = false", 
                fields="files(id, name, mimeType, modifiedTime)"
            ).execute()
            
            files = results.get('files', [])
            print(f"Found {len(files)} files in 'AI_秘書_日記備份' folder:")
            for f in files:
                print(f"  - {f['name']} ({f['mimeType']}) | Modified: {f['modifiedTime']} | ID: {f['id']}")
            assert len(files) >= 2, "Failed to find both structured and encrypted files on Google Drive!"
            print("✅ Google Drive upload verification passed!")
        except Exception as ex:
            print(f"❌ Google Drive verification query failed: {ex}")
        
        # 5. 清除臨時寫入的日記資料，還原試算表狀態 (Self-cleaning)
        try:
            res = service_sheets.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range='日記!A:E'
            ).execute()
            rows = res.get('values', [])
            if len(rows) > 1:
                last_row_idx = len(rows)
                service_sheets.spreadsheets().values().clear(
                    spreadsheetId=spreadsheet_id,
                    range=f'日記!A{last_row_idx}:E{last_row_idx}'
                ).execute()
                print("🧹 Cleaned up temporary test diary row successfully!")
        except Exception as ex:
            print(f"Failed to clean up temp row: {ex}")
    else:
        print("❌ SPREADSHEET_ID not found, skipping sync test.")

if __name__ == "__main__":
    print("==================================================")
    print("🧪 Running V4.0 Core Features Verification Script")
    print("==================================================")
    
    with app.test_request_context():
        email = "ulir976272866@gmail.com"
        session['user_email'] = email
        session['spreadsheet_id'] = os.getenv("GOOGLE_SHEET_ID")
        
        test_fernet_derivation()
        test_learning_prompt(email)
        test_save_habit(email)
        test_drive_sync(email)
        
    print("\n==================================================")
    print("🎉 All test executions completed successfully!")
    print("==================================================")
