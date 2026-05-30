import sys
import os
from dotenv import load_dotenv

# Load env
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'), override=True)

import pymysql

TIDB_HOST = os.getenv("TIDB_HOST")
TIDB_PORT = int(os.getenv("TIDB_PORT", 4000))
TIDB_USER = os.getenv("TIDB_USER")
TIDB_PASSWORD = os.getenv("TIDB_PASSWORD")
TIDB_DATABASE = os.getenv("TIDB_DATABASE", "unitask_db")

ssl_config = {}
for path in ["/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt"]:
    if os.path.exists(path):
        ssl_config = {"ssl_ca": path}
        break

try:
    conn = pymysql.connect(
        host=TIDB_HOST,
        user=TIDB_USER,
        password=TIDB_PASSWORD,
        port=TIDB_PORT,
        database=TIDB_DATABASE,
        ssl=ssl_config if ssl_config else {"ssl": {}}
    )
    print("Connected to database successfully!")
    with conn.cursor() as cursor:
        # 1. Delete old test data
        cursor.execute("DELETE FROM users WHERE email IN ('inming399@gmail.com', 'mina976272866@gmail.com', 'min272866@gmail.com');")
        conn.commit()
        print("Deleted existing sandbox users if any.")

        # 2. Insert sandbox users A, B, C
        # Note: We'll set subscription_expires_at to a date in the future for subscribed ones
        from datetime import datetime, timedelta
        future_date = (datetime.now() + timedelta(days=365)).strftime('%Y-%m-%d %H:%M:%S')
        past_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
        
        # User A: MONTHLY_AI, 500 points, subscribed
        cursor.execute(
            "INSERT INTO users (user_id, email, is_subscribed, subscription_type, ai_points, trial_used, trial_expires_at, subscription_expires_at, role) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);",
            ('uid_inming', 'inming399@gmail.com', True, 'MONTHLY_AI', 500, True, past_date, future_date, 'USER')
        )
        
        # User B: YEARLY_AI, 1000 points, subscribed, has_stock_record = True
        cursor.execute(
            "INSERT INTO users (user_id, email, is_subscribed, subscription_type, ai_points, trial_used, trial_expires_at, subscription_expires_at, role, has_stock_record) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);",
            ('uid_min', 'min272866@gmail.com', True, 'YEARLY_AI', 1000, True, past_date, future_date, 'USER', True)
        )
        
        # User C: NONE, 0 points, not subscribed
        cursor.execute(
            "INSERT INTO users (user_id, email, is_subscribed, subscription_type, ai_points, trial_used, trial_expires_at, subscription_expires_at, role) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);",
            ('uid_mina', 'mina976272866@gmail.com', False, 'NONE', 0, True, past_date, None, 'USER')
        )
        
        conn.commit()
        print("Successfully seeded sandbox users!")
        
        # Verify the seeding
        cursor.execute("SELECT user_id, email, subscription_type, ai_points, is_subscribed, has_stock_record FROM users WHERE email IN ('inming399@gmail.com', 'mina976272866@gmail.com', 'min272866@gmail.com');")
        rows = cursor.fetchall()
        for r in rows:
            print(r)
            
except Exception as e:
    print("Database seeding failed:", e)
