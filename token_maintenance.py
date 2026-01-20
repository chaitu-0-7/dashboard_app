
import os
import sys
import logging
from datetime import datetime
from dotenv import load_dotenv

# Load env vars
load_dotenv()

from token_manager import TokenManager
from utils.email import send_token_expiry_alert

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

def run_daily_maintenance():
    logging.info("🛡️ Starting Daily Token Maintenance Guard...")
    
    try:
        manager = TokenManager()
        
        # Get all enabled Fyers users
        users = list(manager.broker_accounts.find({"broker_type": "fyers", "enabled": True}))
        
        logging.info(f"   Found {len(users)} users to check.")
        
        for user_doc in users:
            username = user_doc.get('username')
            email = user_doc.get('email') # Ensure email exists in user_doc or link to users collection
            
            # If email missing in broker_doc, try to find in users collection
            if not email:
                user_record = manager.db.users.find_one({"username": username})
                if user_record:
                    email = user_record.get('email')
            
            logging.info(f"   👉 Checking {username}...")
            
            # Check & Refresh
            is_valid = manager.check_and_refresh_token(user_doc)
            
            if not is_valid:
                logging.warning(f"   ⚠️ Token for {username} is DEAD.")
                if email:
                    logging.info(f"   📧 Sending Alert to {email}...")
                    send_token_expiry_alert(email, username)
                else:
                    logging.error(f"   ❌ No email found for {username}. Cannot send alert.")
            else:
                logging.info(f"   ✅ {username} is good.")
                
        logging.info("🛡️ Daily Maintenance Completed.")

    except Exception as e:
        logging.error(f"❌ Maintenance Script Failed: {e}")

if __name__ == "__main__":
    run_daily_maintenance()
