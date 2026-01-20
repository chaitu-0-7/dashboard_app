from pymongo import MongoClient
import os
from dotenv import load_dotenv
import pytz
from datetime import datetime

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'nifty_shop')
MONGO_ENV = os.getenv('MONGO_ENV', 'prod')

if not MONGO_URI:
    print("MONGO_URI not found.")
    exit(1)

client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]

TARGET_USER = "chaitu_shop"

def migrate_collection(coll_name, filter_query={}):
    coll = db[coll_name]
    result = coll.update_many(
        filter_query,
        {"$set": {"username": TARGET_USER}}
    )
    print(f"[{coll_name}] Updated {result.modified_count} documents.")

def migrate_broker_accounts():
    # Only update if username is missing
    coll = db['broker_accounts']
    result = coll.update_many(
        {"username": {"$exists": False}},
        {"$set": {"username": TARGET_USER}}
    )
    print(f"[broker_accounts] Updated {result.modified_count} documents.")

def migrate_tokens():
    # Legacy collections if any
    for coll in ['fyers_tokens', 'zerodha_tokens']:
        if coll in db.list_collection_names():
             migrate_collection(coll)

if __name__ == "__main__":
    print(f"Starting Migration to link data to user: {TARGET_USER}")
    
    # 1. Update Trades
    migrate_collection(f'trades_{MONGO_ENV}')
    
    # 2. Update Logs
    migrate_collection(f'logs_{MONGO_ENV}')
    
    # 3. Update Strategy Runs
    migrate_collection(f'strategy_runs_{MONGO_ENV}')
    
    # 4. Update Broker Accounts
    migrate_broker_accounts()
    
    # 5. Update Legacy Token Collections (if they persist)
    migrate_tokens()
    
    print("Migration Completed.")
