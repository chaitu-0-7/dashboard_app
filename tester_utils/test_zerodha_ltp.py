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
MONGO_DB_NAME = "nifty_shop" # Hardcoded as per config
ZERODHA_API_KEY = os.getenv('ZERODHA_API_KEY')

def test_ltp():
    if not MONGO_URI or not ZERODHA_API_KEY:
        print("❌ Missing configuration (MONGO_URI or ZERODHA_API_KEY)")
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

    # Test LTP
    symbol = "NSE:TATAMOTORS"
    print(f"\nTesting LTP for {symbol}...")
    try:
        ltp = kite.ltp(symbol)
        print(f"✅ LTP Response: {ltp}")
    except Exception as e:
        print(f"❌ Error fetching LTP: {e}")

    # Test Quote (to compare)
    print(f"\nTesting Quote for {symbol}...")
    try:
        quote = kite.quote(symbol)
        print(f"✅ Quote Response: {quote}")
    except Exception as e:
        print(f"❌ Error fetching Quote: {e}")

    # Test Direct API Call (Curl equivalent)
    import requests
    print(f"\nTesting Direct API Call for {symbol}...")
    try:
        headers = {
            "X-Kite-Version": "3",
            "Authorization": f"token {ZERODHA_API_KEY}:{access_token}"
        }
        url = f"https://api.kite.trade/quote/ltp?i={symbol}"
        response = requests.get(url, headers=headers)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"❌ Error making direct API call: {e}")

if __name__ == "__main__":
    test_ltp()
