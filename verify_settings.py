"""
Quick script to check what settings are stored in the database
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

print("=" * 60)
print("Current Settings in Database")
print("=" * 60)

settings = db['user_settings'].find_one({'_id': 'global_settings'})

if settings:
    print("\n✅ Settings found:")
    print(f"   MA Period: {settings.get('ma_period')}")
    print(f"   Entry Threshold: {settings.get('entry_threshold')}%")
    print(f"   Target Profit: {settings.get('target_profit')}%")
    print(f"   Averaging Threshold: {settings.get('averaging_threshold')}%")
    print(f"   Trade Amount: ₹{settings.get('trade_amount')}")
    print(f"   Max Positions: {settings.get('max_positions')}")
    print(f"   Trading Mode: {settings.get('trading_mode', 'Not set')}")
    print(f"   Capital: ₹{settings.get('capital', 'Not set')}")
    print(f"   Alert Email: {settings.get('alert_email', 'Not set')}")
else:
    print("\n❌ No settings found in database!")
    print("   The strategy will use hardcoded defaults.")

print("\n" + "=" * 60)
