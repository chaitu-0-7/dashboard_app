import os
import sys
from pymongo import MongoClient
from dotenv import load_dotenv
import pytz
from datetime import datetime

# Add parent dir to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from connectors.fyers import FyersConnector
    from connectors.zerodha import ZerodhaConnector
except ImportError:
    print("Could not import connectors. Running from wrong dir?")

load_dotenv()
mongo_uri = os.getenv('MONGO_URI')
db_name = os.getenv('MONGO_DB_NAME', 'nifty_shop')
UTC = pytz.utc

client = MongoClient(mongo_uri)
db = client[db_name]

def verify_app_logic():
    print("--- Simulating App Logic ---")
    active_connectors = []
    db_brokers = list(db['broker_accounts'].find({"enabled": True}))
    
    print(f"Found {len(db_brokers)} enabled brokers.")
    
    for broker in db_brokers:
        b_type = broker.get('broker_type')
        b_name = broker.get('display_name', b_type)
        print(f"\nChecking {b_name} ({b_type})...")
        
        # Check Validity
        gen_at = broker.get('token_generated_at')
        if isinstance(gen_at, (int, float)): gen_at = datetime.fromtimestamp(gen_at, tz=UTC)
        elif gen_at and gen_at.tzinfo is None: gen_at = UTC.localize(gen_at)
        
        is_valid = False
        if gen_at:
            age = (datetime.now(UTC) - gen_at).total_seconds()
            print(f"   Token Age: {age/3600:.2f} hours")
            if b_type == 'zerodha':
                 if age < 86400: is_valid = True
            elif b_type == 'fyers':
                 # Assuming ACCESS_TOKEN_VALIDITY is imported, but let's say 24h for test
                 if age < 86400: is_valid = True
        
        if not is_valid:
            print(f"   ❌ Token Expired (or missing gen_at).")
            continue
        else:
            print(f"   ✅ Token Valid.")

        # Init Connector
        try:
            connector = None
            if b_type == 'fyers':
                 client_id = broker.get('client_id') or broker.get('api_key')
                 secret_id = broker.get('secret_id') or broker.get('api_secret')
                 if not client_id:
                     print("   ❌ Missing client_id/api_key")
                     continue
                 print(f"   Init Fyers with ID: {client_id}")
                 connector = FyersConnector(
                     api_key=client_id, 
                     api_secret=secret_id, 
                     access_token=broker.get('access_token'),
                     pin=broker.get('pin')
                 )
            elif b_type == 'zerodha':
                 api_key = broker.get('api_key')
                 if not api_key:
                     print("   ❌ Missing api_key")
                     continue
                 print(f"   Init Zerodha with API Key: {api_key}")
                 connector = ZerodhaConnector(
                     api_key=api_key,
                     api_secret=broker.get('api_secret'),
                     access_token=broker.get('access_token')
                 )
            
            if connector:
                print("   ✅ Connector Initialized.")
                # Don't actually call network to avoid rate limits/errors during test, 
                # or call lightweight profile
                # if connector.is_token_valid():
                #     print("   ✅ API Ping Success")
                # else:
                #     print("   ⚠️ API Ping Failed (might be expired or network)")

        except Exception as e:
            print(f"   ❌ Init Failed: {e}")

if __name__ == "__main__":
    verify_app_logic()
