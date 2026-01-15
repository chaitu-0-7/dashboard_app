
import os
from pymongo import MongoClient
from dotenv import load_dotenv
import pprint

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'nifty_shop')
ENV = os.getenv('ENV', 'prod')

client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]
collection = db[f'strategy_runs_{ENV}']

run_id = "manual_debug_1"

print(f"Checking run_id: {run_id} in {f'strategy_runs_{ENV}'}...")
doc = collection.find_one({"run_id": run_id})

if doc:
    pprint.pprint(doc)
else:
    print("Run NOT found.")
    
# Also check if there are any logs for this run
logs_col = db[f'logs_{ENV}']
log_count = logs_col.count_documents({"run_id": run_id})
print(f"Log count for this run: {log_count}")
