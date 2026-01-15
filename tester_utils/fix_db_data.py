
import os
from dotenv import load_dotenv
from pymongo import MongoClient
import pytz
from config import MONGO_DB_NAME

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
FYERS_PIN = os.getenv('FYERS_PIN')
FYERS_REDIRECT_URI = os.getenv('FYERS_REDIRECT_URI')

if not MONGO_URI:
    print("Error: MONGO_URI not found in .env")
    exit(1)

client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]

# Find the Fyers broker
broker = db['broker_accounts'].find_one({'broker_type': 'fyers'})

if broker:
    print(f"Found Fyers broker: {broker.get('broker_id')}")
    
    updates = {}
    if not broker.get('pin') and FYERS_PIN:
        updates['pin'] = FYERS_PIN
        print(f"Queueing PIN update.")
    
    if not broker.get('redirect_uri') and FYERS_REDIRECT_URI:
        updates['redirect_uri'] = FYERS_REDIRECT_URI
        print(f"Queueing Redirect URI update.")
        
    if updates:
        result = db['broker_accounts'].update_one(
            {'broker_id': broker['broker_id']},
            {'$set': updates}
        )
        print(f"Updated {result.modified_count} document(s).")
    else:
        print("No updates needed (fields already exist or env vars missing).")
else:
    print("No Fyers broker found in DB.")
