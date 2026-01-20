
import os
import sys
import logging
from datetime import datetime, timedelta, date
import pytz
from pymongo import MongoClient, UpdateOne
from dotenv import load_dotenv
import time

# Load env vars
load_dotenv()

from config import MONGO_DB_NAME, MONGO_ENV
from connectors.fyers import FyersConnector

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Timezones
UTC = pytz.utc
IST = pytz.timezone('Asia/Kolkata')

# NIFTY 50 Symbols (Centralized List)
NIFTY50_SYMBOLS = [
    "NSE:RELIANCE-EQ", "NSE:TCS-EQ", "NSE:HDFCBANK-EQ", "NSE:INFY-EQ",
    "NSE:HINDUNILVR-EQ", "NSE:ICICIBANK-EQ", "NSE:KOTAKBANK-EQ", 
    "NSE:SBIN-EQ", "NSE:BHARTIARTL-EQ", "NSE:BAJFINANCE-EQ",
    "NSE:ASIANPAINT-EQ", "NSE:MARUTI-EQ", "NSE:AXISBANK-EQ",
    "NSE:LT-EQ", "NSE:TITAN-EQ", "NSE:ULTRACEMCO-EQ",
    "NSE:SUNPHARMA-EQ", "NSE:NESTLEIND-EQ", "NSE:POWERGRID-EQ",
    "NSE:NTPC-EQ", "NSE:BAJAJFINSV-EQ", "NSE:HCLTECH-EQ",
    "NSE:WIPRO-EQ", "NSE:DIVISLAB-EQ", "NSE:TECHM-EQ",
    "NSE:CIPLA-EQ", "NSE:COALINDIA-EQ", "NSE:DRREDDY-EQ",
    "NSE:EICHERMOT-EQ", "NSE:JSWSTEEL-EQ", "NSE:BRITANNIA-EQ",
    "NSE:GRASIM-EQ", "NSE:INDUSINDBK-EQ",
    "NSE:TATASTEEL-EQ", "NSE:APOLLOHOSP-EQ", "NSE:BAJAJ-AUTO-EQ",
    "NSE:HEROMOTOCO-EQ", "NSE:ONGC-EQ", "NSE:BPCL-EQ",
    "NSE:SBILIFE-EQ", "NSE:HDFCLIFE-EQ", "NSE:ADANIPORTS-EQ",
    "NSE:TATACONSUM-EQ", "NSE:UPL-EQ", "NSE:HINDALCO-EQ",
    "NSE:SHREECEM-EQ", "NSE:ADANIENT-EQ", "NSE:LTIM-EQ",
    "NSE:TRENT-EQ"
]

class MarketDataManager:
    def __init__(self):
        self.mongo_uri = os.getenv('MONGO_URI')
        if not self.mongo_uri:
            raise ValueError("MONGO_URI not found in env")
            
        self.client = MongoClient(self.mongo_uri)
        self.db = self.client[MONGO_DB_NAME]
        self.candles_collection = self.db[f'market_candles_{MONGO_ENV}']
        self.broker_accounts = self.db['broker_accounts']
        
        # Ensure Index for fast lookups
        self.candles_collection.create_index([("symbol", 1), ("date", -1)], unique=True)
        
    def get_valid_fyers_token(self):
        """Find any valid Fyers access token, prioritizing admin."""
        # priority 1: chaitu_shop
        admin = self.broker_accounts.find_one({"username": "chaitu_shop", "broker_type": "fyers", "token_status": "valid"})
        if admin:
            logging.info("🔑 Using Admin (chaitu_shop) Fyers Token")
            return admin
            
        # priority 2: any valid fyers user
        any_user = self.broker_accounts.find_one({"broker_type": "fyers", "token_status": "valid"})
        if any_user:
            logging.info(f"🔑 Using User ({any_user.get('username')}) Fyers Token")
            return any_user
            
        logging.error("❌ No valid Fyers token found in the system!")
        return None

    def fetch_history_from_broker(self, connector, symbol, start_date, end_date):
        """Fetch historical data from Fyers."""
        try:
            # Fyers wants YYYY-MM-DD
            s_str = start_date.strftime('%Y-%m-%d')
            e_str = end_date.strftime('%Y-%m-%d')
            
            logging.info(f"   Fetching {symbol} from {s_str} to {e_str}")
            
            data = connector.get_historical_data(
                symbol=symbol,
                resolution="D", # Daily
                from_date=s_str,
                to_date=e_str
            )
            
            if data and data.get('s') == 'ok':
                return data.get('candles', [])
            else:
                logging.warning(f"   ⚠️ Fyers API returned error/empty: {data}")
                return []
                
        except Exception as e:
            logging.error(f"   ❌ Error fetching history: {e}")
            return []

    def sync_daily_data(self):
        """Main sync function."""
        logging.info("🚀 Starting Global Market Data Sync...")
        
        token_doc = self.get_valid_fyers_token()
        if not token_doc:
            return False

        connector = FyersConnector(
            api_key=token_doc['api_key'],
            api_secret=token_doc['api_secret'],
            access_token=token_doc['access_token'],
            pin=token_doc.get('pin')
        )

        today = datetime.now(IST).date()

        for symbol in NIFTY50_SYMBOLS:
            try:
                # 1. Check Last Date in DB
                last_candle = self.candles_collection.find_one(
                    {"symbol": symbol},
                    sort=[("date", -1)]
                )
                
                if last_candle:
                    last_date = last_candle['date'].date()
                    # User Request: Fetch from last_date (inclusive) to handle holidays/corrections
                    start_date = last_date 
                else:
                    logging.info(f"🆕 No data for {symbol}. Fetching last 60 days.")
                    start_date = today - timedelta(days=60)

                # 2. Check if we need to fetch
                if start_date > today:
                    logging.info(f"✅ {symbol} is up to date ({last_date}).")
                    continue
                
                logging.info(f"🔄 Syncing {symbol}...")
                
                # 3. Fetch Data
                candles = self.fetch_history_from_broker(connector, symbol, start_date, today)
                
                if not candles:
                    continue

                # 4. Process and Bulk Write
                bulk_ops = []
                for candle in candles:
                    # Fyers Candle: [timestamp, open, high, low, close, volume]
                    ts = candle[0]
                    # Convert TS to datetime (IST aware then to UTC or naive? Let's stick to simple date for daily)
                    c_date = datetime.fromtimestamp(ts, pytz.timezone('Asia/Kolkata'))
                    
                    doc = {
                        "symbol": symbol,
                        "date": c_date, # MongoDB stores as ISODate
                        "open": candle[1],
                        "high": candle[2],
                        "low": candle[3],
                        "close": candle[4],
                        "volume": candle[5],
                        "updated_at": datetime.now(UTC)
                    }
                    
                    # Upsert based on symbol + date
                    bulk_ops.append(
                        UpdateOne(
                            {"symbol": symbol, "date": c_date},
                            {"$set": doc},
                            upsert=True
                        )
                    )
                
                if bulk_ops:
                    result = self.candles_collection.bulk_write(bulk_ops)
                    logging.info(f"   💾 Saved {result.upserted_count + result.modified_count} candles for {symbol}")
                
                # Rate limit safety
                time.sleep(0.2)

            except Exception as e:
                logging.error(f"❌ Error syncing {symbol}: {e}")

        logging.info("✨ Market Data Sync Completed.")
        return True

if __name__ == "__main__":
    manager = MarketDataManager()
    manager.sync_daily_data()
