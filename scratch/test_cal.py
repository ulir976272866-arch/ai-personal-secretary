import os
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
import app # To reuse creds and CALENDAR_ID

def test():
    print("Calendar ID:", app.CALENDAR_ID)
    try:
        service = build('calendar', 'v3', credentials=app.creds)
        events_result = service.events().list(
            calendarId=app.CALENDAR_ID, maxResults=10, orderBy='startTime', singleEvents=True
        ).execute()
        events = events_result.get('items', [])
        print(f"Found {len(events)} events:")
        for e in events:
            print(f"- Title: {e.get('summary')}, ID: {e.get('id')}")
    except Exception as e:
        print("Error listing events:", e)

if __name__ == "__main__":
    test()
