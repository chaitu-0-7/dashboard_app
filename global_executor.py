
import sys
import os
import argparse
import logging
from datetime import datetime
import pytz
from pymongo import MongoClient
from dotenv import load_dotenv

# Load env vars
load_dotenv()

from config import MONGO_DB_NAME, MONGO_ENV
from market_data_manager import MarketDataManager
from live_stratergy import SimpleNiftyTrader, DatabaseHandler, MongoLogHandler
from connectors.fyers import FyersConnector
from connectors.data_source import YFinanceDataSource 

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

UTC = pytz.utc

def main():
    parser = argparse.ArgumentParser(description="Global Executor: Syncs Data & Runs Strategy for All Users.")
    parser.add_argument("--dry-run", action="store_true", help="Run without placing orders")
    args = parser.parse_args()

    logging.info("🌍 Starting Global Executor...")

    # 1. Sync Market Data (The Data Warehouse)
    logging.info("📡 Phase 1: Syncing Market Data...")
    manager = MarketDataManager()
    if not manager.sync_daily_data():
        logging.error("❌ Market Data Sync failed! Aborting run to prevent trading on stale data.")
        return

    # 2. Iterate Users
    logging.info("👥 Phase 2: Executing for Users...")
    
    mongo_uri = os.getenv('MONGO_URI')
    client = MongoClient(mongo_uri)
    db = client[MONGO_DB_NAME]
    broker_accounts = db['broker_accounts']
    
    # Find active users
    users = list(broker_accounts.find({"enabled": True}))
    
    logging.info(f"   Found {len(users)} enabled users.")
    
    for user_doc in users:
        username = user_doc.get('username')
        logging.info(f"   👉 Processing User: {username}")
        
        mongo_handler = None
        try:
            # Initialize Components for this User
            db_handler = DatabaseHandler(mongo_uri, MONGO_DB_NAME, MONGO_ENV)
            
            # Setup User-Specific Mongo Logging
            mongo_handler = MongoLogHandler(db_handler, username=username, broker_id=str(user_doc.get('_id')))
            mongo_handler.setLevel(logging.INFO)
            logging.getLogger().addHandler(mongo_handler)
            
            # Initialize Connector
            if user_doc.get('broker_type') == 'fyers':
                broker = FyersConnector(
                    api_key=user_doc.get('api_key'),
                    api_secret=user_doc.get('api_secret'),
                    access_token=user_doc.get('access_token'),
                    pin=user_doc.get('pin')
                )
            else:
                logging.warning(f"   ⚠️ Skipping {username}: Unsupported broker {user_doc.get('broker_type')}")
                continue

            # Data Source (Dummy/Reuse)
            data_source = YFinanceDataSource() 
            
            # User Settings
            settings = {
                'ma_period': int(user_doc.get('ma_period', 30)),
                'trade_amount': float(user_doc.get('trade_amount', 2000)),
                'max_positions': int(user_doc.get('max_positions', 10)),
                'entry_threshold': -2.0, 
                'target_profit': 5.0,
                'trading_mode': user_doc.get('trading_mode', 'NORMAL')
            }
            
            if args.dry_run:
                settings['trading_mode'] = 'PAUSED'
                logging.info("   ⚠️ DRY RUN: Trading Mode enforced to PAUSED")

            # Initialize and Run Strategy
            trader = SimpleNiftyTrader(
                broker=broker, 
                data_source=data_source, 
                db_handler=db_handler, 
                settings=settings,
                username=username,
                broker_id=str(user_doc.get('_id'))
            )
            
            trader.run_daily_strategy()
            logging.info(f"   ✅ Completed for {username}")

        except Exception as e:
            logging.error(f"   ❌ Failed for {username}: {e}")
        finally:
            # CRITICAL: Remove handler
            if mongo_handler:
                logging.getLogger().removeHandler(mongo_handler)

    logging.info("🏁 Global Execution Completed.")

if __name__ == "__main__":
    main()
