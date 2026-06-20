import pymysql
import os
import uuid
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load env variables
load_dotenv()

TIDB_HOST = os.getenv('TIDB_HOST')
TIDB_PORT = int(os.getenv('TIDB_PORT', 4000))
TIDB_USER = os.getenv('TIDB_USER')
TIDB_PASSWORD = os.getenv('TIDB_PASSWORD')
TIDB_DATABASE = os.getenv('TIDB_DATABASE')

def get_db_connection():
    ssl_config = {}
    for path in ["/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt"]:
        if os.path.exists(path):
            ssl_config = {"ssl_ca": path}
            break
    return pymysql.connect(
        host=TIDB_HOST,
        user=TIDB_USER,
        password=TIDB_PASSWORD,
        port=TIDB_PORT,
        database=TIDB_DATABASE,
        ssl=ssl_config if ssl_config else {"ssl": {}}
    )

test_emails = [
    "A7708665@gmail.com",
    "ganniniangno2@gmail.com"
]

conn = get_db_connection()
try:
    with conn.cursor() as cursor:
        for email in test_emails:
            # Check if user exists
            cursor.execute("SELECT * FROM users WHERE email = %s;", (email,))
            row = cursor.fetchone()
            
            # 999 days expires timestamp
            expires_at = datetime.now() + timedelta(days=999)
            expires_str = expires_at.strftime('%Y-%m-%d %H:%M:%S')
            
            if row:
                print(f"User {email} exists. Updating subscription and AI points...")
                cursor.execute(
                    """UPDATE users 
                       SET is_subscribed = 1, 
                           subscription_type = 'YEARLY_AI', 
                           ai_points = 100, 
                           subscription_expires_at = %s,
                           trial_expires_at = NULL
                       WHERE email = %s;""",
                    (expires_str, email)
                )
            else:
                print(f"User {email} does not exist. Creating new user...")
                user_id = str(uuid.uuid4())
                cursor.execute(
                    """INSERT INTO users 
                       (user_id, email, is_subscribed, subscription_type, ai_points, trial_used, trial_expires_at, has_stock_record, subscription_expires_at) 
                       VALUES (%s, %s, 1, 'YEARLY_AI', 100, 1, NULL, 1, %s);""",
                    (user_id, email, expires_str)
                )
        conn.commit()
        print("Success! Both test users registered/updated successfully.")
finally:
    conn.close()
