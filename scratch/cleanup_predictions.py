import os
import sys
from datetime import datetime
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, get_calendar_service, CALENDAR_ID, TW_TZ

def cleanup():
    with app.app_context():
        print("Starting cleanup of future period predictions from Google Calendar...")
        service_cal = get_calendar_service()
        now_time_min = datetime.now(TW_TZ).isoformat()
        
        print(f"Calendar ID: {CALENDAR_ID}")
        print("Fetching future predicted period events...")
        pred_events = service_cal.events().list(
            calendarId=CALENDAR_ID, 
            timeMin=now_time_min, 
            q="🌸 (預測)"
        ).execute()
        
        items = pred_events.get('items', [])
        print(f"Found {len(items)} matching events.")
        
        deleted_count = 0
        for event in items:
            summary = event.get('summary', '')
            if "🌸 (預測)" in summary:
                print(f"Deleting event: {summary} on {event.get('start', {}).get('date') or event.get('start', {}).get('dateTime')}")
                service_cal.events().delete(calendarId=CALENDAR_ID, eventId=event['id']).execute()
                deleted_count += 1
                
        print(f"Successfully cleaned up {deleted_count} prediction events.")

if __name__ == '__main__':
    cleanup()
