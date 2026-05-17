import os
import re
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv('.env')

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'service_account.json'

def strip_emojis(text):
    # Regex to strip emojis and trailing/leading spaces
    res = re.sub(r'[^\w\s,，]', '', text)
    return res.strip()

def clean_data_validation():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    sheets_service = build('sheets', 'v4', credentials=creds)
    spreadsheet_id = os.getenv('GOOGLE_SHEET_ID')
    
    if not spreadsheet_id:
        print("Error: GOOGLE_SHEET_ID not found in .env")
        return

    # Fetch spreadsheet with validation rules
    # We want to see metadata about sheets, particularly validation rules
    res = sheets_service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        includeGridData=True
    ).execute()
    
    sheet = res['sheets'][0]  # Assuming the first sheet '記帳'
    sheet_id = sheet['properties']['sheetId']
    
    # We will search for any dataValidation rules in the grid data
    requests = []
    
    data = sheet.get('data', [])
    if not data:
        print("No grid data found.")
        return
        
    row_data = data[0].get('rowData', [])
    print(f"Inspecting {len(row_data)} rows for validation rules...")
    
    # Let's see if there are validation rules on columns
    # In Sheets API v4, validation rules are set per cell.
    # Often, they are set on the whole G column (index 6).
    # We'll search rows to see if index 6 has data validation.
    
    found_rule = False
    for r_idx, row in enumerate(row_data):
        values = row.get('values', [])
        if len(values) > 6:
            cell = values[6]
            rule = cell.get('dataValidation')
            if rule:
                found_rule = True
                print(f"Found validation rule on row {r_idx + 1}: {rule}")
                
                # Check if it is a list of values
                condition = rule.get('condition')
                if condition and condition.get('type') == 'ONE_OF_LIST':
                    values_list = condition.get('values', [])
                    new_values = []
                    changed = False
                    for val_obj in values_list:
                        user_entered_value = val_obj.get('userEnteredValue', '')
                        cleaned = strip_emojis(user_entered_value)
                        if cleaned != user_entered_value:
                            changed = True
                        new_values.append({'userEnteredValue': cleaned})
                    
                    if changed:
                        print(f"Updating validation values from {[v['userEnteredValue'] for v in values_list]} to {[v['userEnteredValue'] for v in new_values]}")
                        # Prepare update request
                        rule['condition']['values'] = new_values
                        
                        # We will apply this validation rule to the entire column G (G2:G1000)
                        requests.append({
                            'setDataValidation': {
                                'range': {
                                    'sheetId': sheet_id,
                                    'startRowIndex': 1, # Row 2 onwards
                                    'startColumnIndex': 6, # Column G
                                    'endColumnIndex': 7
                                },
                                'rule': rule
                            }
                        })
                        break # One rule update is enough since we apply it to the whole range
                        
    if requests:
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={'requests': requests}
        ).execute()
        print("Successfully updated Google Sheets Data Validation rules! 🎉")
    else:
        if found_rule:
            print("Validation rules were already clean or not of type ONE_OF_LIST.")
        else:
            print("No validation rules found on Column G.")

if __name__ == "__main__":
    clean_data_validation()
