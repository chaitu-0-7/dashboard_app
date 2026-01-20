import os
import sys
from dotenv import load_dotenv
from pymongo import MongoClient
import pytz

# Add current dir to path to find config
sys.path.append(os.getcwd())
try:
    from config import MONGO_DB_NAME, MONGO_ENV
except ImportError:
    print("❌ Could not import config. Using defaults.")
    MONGO_DB_NAME = 'nifty_shop'
    MONGO_ENV = 'prod'

load_dotenv()
MONGO_URI = os.getenv('MONGO_URI')

if not MONGO_URI:
    print("❌ MONGO_URI not found.")
    exit(1)

client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]

print(f"Connected to DB: {MONGO_DB_NAME} (Env: {MONGO_ENV})")

print("\n--- Users ---")
users = list(db['users'].find({}, {'username': 1, 'role': 1}))
for u in users:
    print(f"User: {u.get('username')}, Role: {u.get('role')}")

print(f"\n--- Trades ({MONGO_ENV}) ---")
trades = db[f'trades_{MONGO_ENV}']
total = trades.count_documents({})
print(f"Total Trades: {total}")

user_counts = list(trades.aggregate([
    {"$group": {"_id": "$username", "count": {"$sum": 1}}}
]))
for r in user_counts:
    print(f"User: '{r['_id']}' | Trades: {r['count']}")

# Check logs
print(f"\n--- Logs ({MONGO_ENV}) ---")
logs = db[f'logs_{MONGO_ENV}']
user_log_counts = list(logs.aggregate([
    {"$group": {"_id": "$username", "count": {"$sum": 1}}}
]))
for r in user_log_counts:
    print(f"User: '{r['_id']}' | Logs: {r['count']}")

# Verify specific user
CHECK_USER = 'chaitu_shop'
print(f"\n--- Checking '{CHECK_USER}' ---")
user_trades = trades.count_documents({'username': CHECK_USER})
print(f"Trades for {CHECK_USER}: {user_trades}")

print("\n--- Broker Accounts ---")
brokers = list(db['broker_accounts'].find({}))
for b in brokers:
    print(f"Broker: {b.get('broker_id')} | User: {b.get('username', 'MISSING')} | Type: {b.get('broker_type')}")
