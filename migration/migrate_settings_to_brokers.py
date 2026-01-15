import os
import sys
from pymongo import MongoClient
from dotenv import load_dotenv

# Add parent dir to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'nifty_shop')

if not MONGO_URI:
    print("❌ MONGO_URI not found in .env")
    exit(1)

client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]

def migrate_settings():
    print("🔄 Starting Settings Migration...")

    # 1. Get Global Settings
    global_settings = db['user_settings'].find_one({'_id': 'global_settings'})
    
    if not global_settings:
        print("⚠️ No global settings found. Using defaults.")
        # Default values matching config.py usually
        global_settings = {
            'capital': 100000,
            'trade_amount': 2000,
            'max_positions': 10,
            'ma_period': 20,
            'entry_threshold': -2.0,
            'target_profit': 5.0,
            'averaging_threshold': -3.0
        }
    else:
        print("✅ Found global settings.")

    # 2. Get All Brokers
    brokers = list(db['broker_accounts'].find({}))
    print(f"Found {len(brokers)} brokers to update.")

    # 3. Update Each Broker
    for broker in brokers:
        print(f"   Updating {broker.get('display_name', 'Unknown')} ({broker.get('broker_id')})...")
        
        update_fields = {}
        
        # Only set if not already present (preserve existing broker-level overrides if any, though unlikely)
        fields_to_migrate = [
            'capital', 'trade_amount', 'max_positions', 'ma_period', 
            'entry_threshold', 'target_profit', 'averaging_threshold'
        ]
        
        for field in fields_to_migrate:
            if field not in broker:
                val = global_settings.get(field)
                if val is not None:
                    update_fields[field] = val
        
        if update_fields:
            db['broker_accounts'].update_one(
                {'broker_id': broker.get('broker_id')},
                {'$set': update_fields}
            )
            print(f"      Set: {list(update_fields.keys())}")
        else:
            print("      No updates needed.")

    print("✅ Migration Completed!")

if __name__ == "__main__":
    migrate_settings()
