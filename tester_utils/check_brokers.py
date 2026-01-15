
import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'nifty_shop')

client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]
collection = db['broker_accounts']

print(f"Connected to {MONGO_DB_NAME} - broker_accounts\n")

brokers = list(collection.find({}))

for broker in brokers:
    print(f"Name: {broker.get('display_name')}")
    print(f"ID: {broker.get('broker_id')}")
    print(f"Type: {broker.get('broker_type')}")
    print(f"Enabled: {broker.get('enabled')}")
    print(f"Mode: {broker.get('trading_mode')}")
    print("-" * 30)
