import os
import sys
from flask import session 
from pymongo import MongoClient
import uuid
from datetime import datetime
import pytz

# Ensure correct WD
sys.path.append(os.getcwd())

# Force Prod Env
os.environ['ENV'] = 'prod'
os.environ['MONGO_ENV'] = 'prod'

# DB Setup for Session Creation
from dotenv import load_dotenv
load_dotenv()
mongo_uri = os.getenv('MONGO_URI')
client = MongoClient(mongo_uri)
db = client['nifty_shop']

# Create a Real Session for 'chaitu_shop'
sessions = db['sessions']
token = str(uuid.uuid4())
sessions.insert_one({
    'username': 'chaitu_shop',
    'session_token': token,
    'created_at': datetime.now(pytz.utc),
    'expires_at': datetime.now(pytz.utc) + getattr(datetime, 'timedelta', None)(days=30) if hasattr(datetime, 'timedelta') else None 
})
# Fix timedelta import if needed, assuming standard import
from datetime import timedelta
sessions.update_one({'session_token': token}, {'$set': {'expires_at': datetime.now(pytz.utc) + timedelta(days=30)}})

print(f"🔑 Created dummy session: {token}")

# Import App (will Trigger DB connection again, which is fine)
from app import app

print("🚀 Starting Full Stack Debug Test...")
app.config['TESTING'] = True
app.config['DEBUG'] = True
app.config['SECRET_KEY'] = 'dev' # Ensure secret key for sessions

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['session_token'] = token
    
    print("📡 Requesting Dashboard (GET /) with valid session...")
    try:
        response = client.get('/', follow_redirects=True)
        print(f"✅ Status Code: {response.status_code}")
        
        if response.status_code == 500:
            print("❌ 500 Error Detected!")
            print(response.data.decode('utf-8'))
        elif response.status_code == 200:
            print("✅ Dashboard Rendered Successfully!")
        else:
            print(f"⚠️ Unexpected Status: {response.status_code}")
            # print(response.data.decode('utf-8')[:500])

    except Exception as e:
        print("❌ Exception caught during request execution:")
        import traceback
        traceback.print_exc()

# Cleanup
sessions.delete_one({'session_token': token})
print("🧹 Cleanup done.")
