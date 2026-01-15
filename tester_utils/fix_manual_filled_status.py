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

def fix_manual_trades():
    print(f"--- Fixing Manual Trades in trades_{ENV} ---")
    
    # Update criteria: order_id is MANUAL
    query = {'order_id': 'MANUAL'}
    
    # 1. Update filled=True
    # Also set status to PENDING_MANUAL_PRICE if it doesn't have a status or is just 'FILLED' without price
    # Actually, let's just ensure they are visible.
    
    # Fetch sample to see
    count = trades_coll.count_documents(query)
    print(f"Found {count} manual trades.")
    
    if count > 0:
        # We want to enable them for the UI.
        # The UI looks for: filled=True (fetched by app.py)
        # And status='PENDING_MANUAL_PRICE' for the amber highlight.
        
        # Strategy:
        # 1. Set filled=True for ALL manual trades.
        # 2. Set status='PENDING_MANUAL_PRICE' ONLY IF price is 0. 
        #    If price > 0, it means user already updated it (maybe via older UI), so keep it 'FILLED'.
        
        # Batch update for filled=True
        res_filled = trades_coll.update_many(
            {'order_id': 'MANUAL', 'filled': False},
            {'$set': {'filled': True}}
        )
        print(f"✅ Set filled=True for {res_filled.modified_count} trades.")
        
        # Batch update for Status
        res_status = trades_coll.update_many(
            {'order_id': 'MANUAL', 'price': 0, 'status': {'$ne': 'PENDING_MANUAL_PRICE'}},
            {'$set': {'status': 'PENDING_MANUAL_PRICE'}}
        )
        print(f"✅ Set status='PENDING_MANUAL_PRICE' for {res_status.modified_count} trades (price=0).")
        
    else:
        print("No manual trades found.")

if __name__ == "__main__":
    fix_manual_trades()
