
import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'nifty_shop')
MONGO_ENV = os.getenv('MONGO_ENV', 'prod')

client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]
logs_collection = db[f"logs_{MONGO_ENV}"]

run_id = "463d0e6c-191e-45cc-97d7-c199405da8e7"

print(f"Connected to {MONGO_DB_NAME} - logs_{MONGO_ENV}")
print(f"Searching for logs with run_id: {run_id}\n")

logs = list(logs_collection.find({"run_id": run_id}))
print(f"Found {len(logs)} logs.")

if logs:
    print("\nSample Log:")
    print(logs[0])
else:
    print("\nChecking latest 5 logs to see if they have ANY run_id:")
    recent_logs = list(logs_collection.find().sort("timestamp", -1).limit(5))
    for log in recent_logs:
        print(log)
