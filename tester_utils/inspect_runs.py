
import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'nifty_shop')
MONGO_ENV = os.getenv('MONGO_ENV', 'prod')

client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]
collection = db[f"strategy_runs_{MONGO_ENV}"]

print(f"Connected to {MONGO_DB_NAME} - {f'strategy_runs_{MONGO_ENV}'}")

# Find runs where total_pnl is missing
missing_pnl_runs = list(collection.find({"total_pnl": {"$exists": False}}).sort("run_time", -1).limit(5))

print(f"\nFound {len(missing_pnl_runs)} runs with missing 'total_pnl':")
for run in missing_pnl_runs:
    print(f"\nID: {run.get('run_id')}")
    print(f"Status: {run.get('status')}")
    print(f"Keys: {list(run.keys())}")
    if 'error' in run:
        print(f"Error: {run['error']}")

# Find runs where total_pnl exists (for comparison)
valid_runs = list(collection.find({"total_pnl": {"$exists": True}}).sort("run_time", -1).limit(1))
if valid_runs:
    print(f"\nValid Run Example keys: {list(valid_runs[0].keys())}")
