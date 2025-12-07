import os
from pymongo import MongoClient
from kiteconnect import KiteConnect
from dotenv import load_dotenv
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)

# Load env
load_dotenv()

# Config
MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = "nifty_shop"
ZERODHA_API_KEY = os.getenv('ZERODHA_API_KEY')

def test_permissions():
    if not MONGO_URI or not ZERODHA_API_KEY:
        print("❌ Missing configuration")
        return

    # Load token
    try:
        client = MongoClient(MONGO_URI)
        db = client[MONGO_DB_NAME]
        token_data = db['zerodha_tokens'].find_one({"_id": "zerodha_token_data"})
        
        if not token_data or 'access_token' not in token_data:
            print("❌ No Zerodha token found in MongoDB")
            return
            
        access_token = token_data['access_token']
        print(f"✅ Found access token: {access_token[:10]}...")
        
    except Exception as e:
        print(f"❌ Error loading token: {e}")
        return

    # Initialize Kite
    try:
        kite = KiteConnect(api_key=ZERODHA_API_KEY)
        kite.set_access_token(access_token)
        print("✅ KiteConnect initialized")
    except Exception as e:
        print(f"❌ Error initializing Kite: {e}")
        return

    # Test Margins (Funds)
    print(f"\nTesting Margins (Funds)...")
    try:
        margins = kite.margins()
        print(f"✅ Margins Response: {margins}")
    except Exception as e:
        print(f"❌ Error fetching Margins: {e}")

    # Test Orders (Just fetch, don't place)
    print(f"\nTesting Orders (Fetch)...")
    try:
        orders = kite.orders()
        print(f"✅ Orders Response: {len(orders)} orders found")
    except Exception as e:
        print(f"❌ Error fetching Orders: {e}")

if __name__ == "__main__":
    test_permissions()
