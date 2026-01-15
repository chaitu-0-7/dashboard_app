
import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'nifty_shop')
ENV = os.getenv('ENV', 'prod')

client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]
collection = db[f'trades_{ENV}']

count = collection.count_documents({})
print(f"Total trades in trades_{ENV}: {count}")

if count > 0:
    print("Sample trade:")
    print(collection.find_one())
