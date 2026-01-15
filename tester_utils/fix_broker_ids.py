from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

# Config
MONGO_URI = os.getenv('MONGO_URI')
DB_NAME = 'nifty_shop'
ENV = os.getenv('ENV', 'prod')

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
trades_coll = db[f'trades_{ENV}']
accounts_coll = db['broker_accounts']

def fix_broker_ids():
    print(f"--- Migrating Trades in trades_{ENV} ---")
    
    # 1. Get Default Broker (usually Fyers)
    default_broker = accounts_coll.find_one({'broker_type': 'fyers', 'is_default': True})
    if not default_broker:
        default_broker = accounts_coll.find_one({'broker_type': 'fyers'})
        
    if not default_broker:
        print("CRITICAL: No Fyers broker found to assign legacy trades to!")
        return

    default_id = default_broker['broker_id']
    print(f"Target Default Broker: {default_broker['display_name']} ({default_id})")
    
    # 2. Update Trades without broker_id
    query = {'broker_id': {'$exists': False}}
    count = trades_coll.count_documents(query)
    
    print(f"Found {count} trades missing broker_id.")
    
    if count > 0:
        result = trades_coll.update_many(
            query, 
            {'$set': {'broker_id': default_id}}
        )
        print(f"✅ Updated {result.modified_count} trades with broker_id='{default_id}'")
    else:
        print("No migration needed.")

    # 3. Verify
    distinct_brokers = trades_coll.distinct('broker_id')
    print(f"Distinct Broker IDs in DB: {distinct_brokers}")

if __name__ == "__main__":
    fix_broker_ids()
