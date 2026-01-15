import os
import sys
from pymongo import MongoClient
from dotenv import load_dotenv
import pprint

# Add parent dir to sys.path to find config/env
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'nifty_shop')

if not MONGO_URI:
    print("❌ MONGO_URI not found in .env")
    exit(1)

client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]

def print_collection_schema(coll_name):
    print(f"\n{'='*20} {coll_name} {'='*20}")
    if coll_name not in db.list_collection_names():
        print(f"❌ Collection '{coll_name}' does not exist.")
        return

    count = db[coll_name].count_documents({})
    print(f"Count: {count}")
    
    if count > 0:
        # Sample one document
        doc = db[coll_name].find_one()
        print("\n--- Sample Document (Keys & Types) ---")
        for k, v in doc.items():
            print(f"{k}: {type(v).__name__} = {str(v)[:50]}...")
            
        print("\n--- Full Sample ---")
        pprint.pprint(doc)
    else:
        print("⚠️ Collection is empty.")

if __name__ == "__main__":
    print(f"Connected to DB: {MONGO_DB_NAME}")
    
    # Check the key collections
    print_collection_schema('broker_accounts')
    print_collection_schema('fyers_tokens')
    print_collection_schema('zerodha_tokens')
    print_collection_schema('user_settings')
