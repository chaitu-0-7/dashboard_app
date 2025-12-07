"""
Update broker trading mode
"""
import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'nifty_shop')

if not MONGO_URI:
    print("❌ MONGO_URI not found")
    exit(1)

client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]

broker_id = "fyers_20251207132517"

# Update the broker's trading mode
result = db['broker_accounts'].update_one(
    {"broker_id": broker_id},
    {"$set": {"trading_mode": "EXIT_ONLY"}}
)

if result.modified_count > 0:
    print(f"✅ Updated broker {broker_id} to EXIT_ONLY mode")
    
    # Verify
    broker = db['broker_accounts'].find_one({"broker_id": broker_id})
    print(f"   Display Name: {broker.get('display_name')}")
    print(f"   Trading Mode: {broker.get('trading_mode')}")
else:
    print(f"❌ Failed to update broker {broker_id}")
