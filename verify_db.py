from pymongo import MongoClient
import os
from dotenv import load_dotenv
from config import MONGO_DB_NAME, MONGO_ENV
from datetime import datetime
import pytz

# Define timezones
UTC = pytz.utc
IST = pytz.timezone('Asia/Kolkata')

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')

if MONGO_URI:
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB_NAME]

    print(f"--- Trades (trades_{MONGO_ENV}) ---")
    for trade in db[f'trades_{MONGO_ENV}'].find():
        if 'date' in trade and trade['date'].tzinfo is None:
            trade['date'] = UTC.localize(trade['date']).astimezone(IST)
        elif 'date' in trade:
            trade['date'] = trade['date'].astimezone(IST)
        print(trade)

    print(f"\n--- Logs (logs_{MONGO_ENV}) ---")
    for log in db[f'logs_{MONGO_ENV}'].find():
        if 'timestamp' in log and log['timestamp'].tzinfo is None:
            log['timestamp'] = UTC.localize(log['timestamp']).astimezone(IST)
        elif 'timestamp' in log:
            log['timestamp'] = log['timestamp'].astimezone(IST)
        print(log)
else:
    print("Could not find MongoDB URI in .env file")
