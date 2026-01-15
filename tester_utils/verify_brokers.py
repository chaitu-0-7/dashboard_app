from pymongo import MongoClient
import os
from dotenv import load_dotenv
import pytz

load_dotenv()
mongo_uri = os.getenv('MONGO_URI')
db_name = os.getenv('MONGO_DB_NAME', 'nifty_shop') # Default to nifty_shop

if not mongo_uri:
    print("No MONGO_URI in .env")
    exit()

client = MongoClient(mongo_uri)
db = client[db_name]

print(f"Connected to {db_name}")

if 'broker_accounts' in db.list_collection_names():
    print("\n--- broker_accounts ---")
    brokers = list(db.broker_accounts.find())
    for b in brokers:
        print(f"ID: {b.get('broker_id')}, Type: {b.get('broker_type')}, Name: {b.get('display_name')}")
        print(f"   Token Status: {b.get('token_status')}")
        print(f"   Gen At: {b.get('token_generated_at')}")
        print("-" * 20)
else:
    print("broker_accounts collection does NOT exist.")

print("\n--- Legacy Collections ---")
if 'zerodha_tokens' in db.list_collection_names():
    print("zerodha_tokens:", db.zerodha_tokens.find_one())
if 'fyers_tokens' in db.list_collection_names():
    print("fyers_tokens:", db.fyers_tokens.find_one())
