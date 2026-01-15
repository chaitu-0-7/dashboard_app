
import os
from pymongo import MongoClient
from dotenv import load_dotenv
import pprint

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'nifty_shop')

client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]
collection = db['broker_accounts']

print("Sample Broker Config:")
pprint.pprint(collection.find_one({"enabled": True}))
