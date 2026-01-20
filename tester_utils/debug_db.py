
import os
from dotenv import load_dotenv
from pymongo import MongoClient
import pytz

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = 'nifty_shop'

if not MONGO_URI or not MONGO_DB_NAME:
    print("❌ Env vars missing")
    exit(1)

client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]
collection = db['broker_accounts']

print(f"Connected to {MONGO_DB_NAME}.broker_accounts")
print(f"Total Docs: {collection.count_documents({})}")

for doc in collection.find({}):
    print(f"User: {doc.get('username')}, Broker: {doc.get('broker_type')}, Enabled: {doc.get('enabled')}, ID: {doc.get('broker_id')}")
