from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'nifty_shop')

client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]

print("Scanning broker_accounts...")
brokers = list(db.broker_accounts.find({}))

for b in brokers:
    print(f"\nBroker: {b.get('display_name', 'Unknown')}")
    print(f"Type: {b.get('broker_type')}")
    print(f"Keys: {list(b.keys())}")
    if b.get('broker_type') == 'fyers':
         print(f"Has client_id? {'client_id' in b}")
         print(f"Has api_key? {'api_key' in b}")
