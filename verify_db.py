from pymongo import MongoClient
import os
from pymongo import MongoClient
from dotenv import load_dotenv
import pprint

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'nifty_shop')

if not MONGO_URI:
    print("Error: MONGO_URI not found.")
    exit(1)

client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]

print(f"Connected to DB: {MONGO_DB_NAME}")
print("-" * 50)
print("Checking 'broker_accounts' collection...")

brokers = list(db['broker_accounts'].find())
print(f"Total Brokers Found: {len(brokers)}")

for i, broker in enumerate(brokers, 1):
    print(f"\n[Broker #{i}]")
    pprint.pprint(broker)

print("-" * 50)
