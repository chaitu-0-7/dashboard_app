import os
import sys
from pymongo import MongoClient
from dotenv import load_dotenv
import pytz
from datetime import datetime
import uuid

# Add parent dir to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'nifty_shop')
UTC = pytz.utc

if not MONGO_URI:
    print("❌ MONGO_URI not found in .env")
    exit(1)

client = MongoClient(MONGO_URI, tz_aware=True, tzinfo=UTC)
db = client[MONGO_DB_NAME]

def migrate_zerodha():
    print("🔄 Starting Zerodha Legacy Migration...")

    # 1. Check if Zerodha already exists in broker_accounts
    existing = db.broker_accounts.find_one({"broker_type": "zerodha"})
    if existing:
        print(f"✅ Zerodha broker already exists in broker_accounts (ID: {existing.get('broker_id')})")
        return

    # 2. Get Legacy Token Data
    legacy_coll = db['zerodha_tokens']
    legacy_data = legacy_coll.find_one({"_id": "zerodha_token_data"})

    if not legacy_data:
        print("⚠️ No legacy Zerodha data found. Skipping migration.")
        return

    print("Found legacy data. Migrating...")

    # 3. Get Credentials from Environment (since they aren't fully in db token doc usually)
    api_key = os.getenv('ZERODHA_API_KEY')
    api_secret = os.getenv('ZERODHA_API_SECRET')

    if not api_key or not api_secret:
        print("❌ ZERODHA_API_KEY or ZERODHA_API_SECRET not found in .env. Cannot create broker account.")
        return

    # 4. Prepare New Document
    # Preserving 'generated_at' and tokens
    
    generated_at = legacy_data.get('generated_at')
    # Ensure timezone awareness
    if generated_at and hasattr(generated_at, 'tzinfo') and generated_at.tzinfo is None:
        generated_at = UTC.localize(generated_at)

    new_broker = {
        "broker_id": f"zerodha_{uuid.uuid4().hex[:8]}",
        "broker_type": "zerodha",
        "display_name": "Zerodha (Migrated)",
        "enabled": True,
        "is_default": False,
        "trading_mode": "NORMAL",
        "created_at": datetime.now(UTC),
        
        # Credentials
        "api_key": api_key,
        "api_secret": api_secret,
        
        # Token Data
        "access_token": legacy_data.get('access_token'),
        "public_token": legacy_data.get('public_token'),
        "user_id": legacy_data.get('user_id'),
        "refresh_token": legacy_data.get('refresh_token'),
        
        # Status
        "token_generated_at": generated_at,
        "token_status": "valid" # Assume valid initially, app will check
    }

    # 5. Insert
    db.broker_accounts.insert_one(new_broker)
    print("✅ Successfully migrated Zerodha to broker_accounts!")

if __name__ == "__main__":
    migrate_zerodha()
