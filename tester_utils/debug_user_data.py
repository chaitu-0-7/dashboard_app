import os
from dotenv import load_dotenv
from pymongo import MongoClient
import pytz

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME')
MONGO_ENV = os.getenv('MONGO_ENV', 'prod')

if not MONGO_URI:
    print("❌ MONGO_URI not found.")
    exit(1)

client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]

print(f"Connected to DB: {MONGO_DB_NAME} (Env: {MONGO_ENV})")

# 1. Check Users
print("\n--- Users ---")
users = list(db['users'].find({}, {'username': 1, 'email': 1, 'role': 1}))
for u in users:
    print(f"User: {u.get('username')} | Email: {u.get('email')} | Role: {u.get('role')}")

# 2. Check Trades
print(f"\n--- Trades ({MONGO_ENV}) ---")
trades_coll = db[f'trades_{MONGO_ENV}']
total_trades = trades_coll.count_documents({})
print(f"Total Trades: {total_trades}")

# Group by username
pipeline = [
    {"$group": {"_id": "$username", "count": {"$sum": 1}}}
]
results = list(trades_coll.aggregate(pipeline))
if not results:
    print("No trades found or aggregation failed.")
else:
    for r in results:
        print(f"Username: '{r['_id']}' | Count: {r['count']}")

# Check some sample trades for username field existence
print("\n--- Sample Trade ---")
sample = trades_coll.find_one()
if sample:
    print(f"ID: {sample['_id']}")
    print(f"Username key exists: {'username' in sample}")
    print(f"Username value: {sample.get('username')}")
else:
    print("No trades found.")

# 3. Check Brokers
print("\n--- Broker Accounts ---")
brokers = list(db['broker_accounts'].find({}, {'broker_id': 1, 'username': 1, 'display_name': 1}))
for b in brokers:
    print(f"Broker: {b.get('display_name')} | Username: {b.get('username')}")
