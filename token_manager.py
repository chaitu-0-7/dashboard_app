
import os
import logging
from datetime import datetime
import pytz
from pymongo import MongoClient
from connectors.fyers import FyersConnector
from dotenv import load_dotenv

load_dotenv()

from config import MONGO_DB_NAME
MONGO_URI = os.getenv('MONGO_URI')

UTC = pytz.utc

class TokenManager:
    def __init__(self, db=None):
        if db is not None:
            self.db = db
        elif MONGO_URI:
            client = MongoClient(MONGO_URI, tz_aware=True, tzinfo=UTC)
            self.db = client[MONGO_DB_NAME]
        else:
            raise ValueError("Database connection required for TokenManager")
        
        self.broker_accounts = self.db['broker_accounts']

    def check_and_refresh_token(self, broker_doc):
        """
        Checks if the token in the broker_doc is valid.
        If not, attempts to refresh it.
        Returns: True (Valid/Refreshed), False (Failed)
        """
        username = broker_doc.get('username', 'Unknown')
        broker_id = broker_doc.get('broker_id')
        
        logging.info(f"🔍 Checking token for user: {username} ({broker_id})")

        api_key = broker_doc.get('api_key')
        api_secret = broker_doc.get('api_secret')
        pin = broker_doc.get('pin')
        access_token = broker_doc.get('access_token')
        refresh_token = broker_doc.get('refresh_token')

        if not all([api_key, api_secret, access_token]):
            logging.error(f"   ❌ Missing credentials for {username}")
            return False

        # Initialize Connector
        connector = FyersConnector(
            api_key=api_key, 
            api_secret=api_secret, 
            access_token=access_token,
            pin=pin
        )

        # 1. Check Validity
        if connector.is_token_valid():
            logging.info(f"   ✅ Token is valid for {username}")
            # Ensure DB status is valid
            if broker_doc.get('token_status') != 'valid':
                 self.update_token_status(broker_id, 'valid')
            return True

        # 2. Attempt Refresh
        logging.info(f"   ⚠️ Token expired for {username}. Attempting refresh...")
        if not refresh_token:
            logging.error(f"   ❌ No refresh token available for {username}")
            self.update_token_status(broker_id, 'expired')
            return False

        try:
            new_tokens = connector.refresh_token(refresh_token)
            
            # Update DB
            self.broker_accounts.update_one(
                {"broker_id": broker_id},
                {"$set": {
                    "access_token": new_tokens["access_token"],
                    "refresh_token": new_tokens.get("refresh_token", refresh_token),
                    "token_generated_at": datetime.now(UTC),
                    "token_status": "valid"
                }}
            )
            logging.info(f"   ✨ Token refreshed successfully for {username}")
            return True

        except Exception as e:
            logging.error(f"   ❌ Refresh failed for {username}: {e}")
            self.update_token_status(broker_id, 'expired')
            return False

    def update_token_status(self, broker_id, status):
        self.broker_accounts.update_one(
            {"broker_id": broker_id},
            {"$set": {"token_status": status}}
        )

if __name__ == "__main__":
    # Test Run
    logging.basicConfig(level=logging.INFO)
    manager = TokenManager()
    users = list(manager.broker_accounts.find({"broker_type": "fyers", "enabled": True}))
    for user in users:
        manager.check_and_refresh_token(user)
