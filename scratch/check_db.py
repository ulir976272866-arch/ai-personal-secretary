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

print("Host:", TIDB_HOST)
print("Port:", TIDB_PORT)
print("User:", TIDB_USER)
print("DB:", TIDB_DATABASE)

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
    print("Connected successfully!")
    with conn.cursor() as cursor:
        cursor.execute("SHOW TABLES;")
        tables = cursor.fetchall()
        print("Tables in database:", tables)
        
        # Check users table if it exists
        try:
            cursor.execute("DESCRIBE users;")
            columns = cursor.fetchall()
            print("Columns in users table:")
            for col in columns:
                print(col)
            
            cursor.execute("SELECT user_id, email, subscription_type, ai_points, role FROM users;")
            users = cursor.fetchall()
            print("Users in database:")
            for u in users:
                print(u)
        except Exception as e:
            print("Error checking users table:", e)
            
except Exception as e:
    print("Failed to connect:", e)
