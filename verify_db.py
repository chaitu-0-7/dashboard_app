from pymongo import MongoClient
import os
from dotenv import load_dotenv
from config import MONGO_DB_NAME, MONGO_ENV

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')

if MONGO_URI:
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB_NAME]

    print(f"--- Trades (trades_{MONGO_ENV}) ---")
    for trade in db[f'trades_{MONGO_ENV}'].find():
        print(trade)

    print(f"\n--- Logs (logs_{MONGO_ENV}) ---")
    for log in db[f'logs_{MONGO_ENV}'].find():
        print(log)
else:
    print("Could not find MongoDB URI in .env file")
