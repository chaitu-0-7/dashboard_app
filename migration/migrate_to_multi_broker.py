"""
Migration script to create broker_accounts collection and migrate existing Fyers token.

This script:
1. Creates the broker_accounts collection
2. Migrates existing fyers_tokens data to the new schema
3. Sets the migrated Fyers account as default and enabled
"""

import os
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv
import pytz

load_dotenv()

UTC = pytz.utc

# MongoDB Configuration
MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'nifty_shop')

# Fyers credentials
FYERS_CLIENT_ID = os.getenv('FYERS_CLIENT_ID')
FYERS_SECRET_ID = os.getenv('FYERS_SECRET_ID')

def migrate_to_multi_broker():
    """Migrate existing Fyers token to new broker_accounts schema"""
    
    if not MONGO_URI:
        print("❌ MONGO_URI not found in .env file")
        return False
    
    try:
        client = MongoClient(MONGO_URI, tz_aware=True, tzinfo=UTC)
        db = client[MONGO_DB_NAME]
        
        print("🔄 Starting multi-broker migration...")
        
        # Check if broker_accounts collection already exists
        if 'broker_accounts' in db.list_collection_names():
            print("⚠️  broker_accounts collection already exists")
            response = input("Do you want to continue? This will not overwrite existing brokers. (y/n): ")
            if response.lower() != 'y':
                print("Migration cancelled")
                return False
        
        # Load existing Fyers token
        fyers_tokens_collection = db['fyers_tokens']
        existing_token = fyers_tokens_collection.find_one({"_id": "fyers_token_data"})
        
        if not existing_token:
            print("⚠️  No existing Fyers token found in fyers_tokens collection")
            print("Creating empty broker_accounts collection...")
            db.create_collection('broker_accounts')
            print("✅ broker_accounts collection created")
            return True
        
        # Create broker_accounts collection
        broker_accounts = db['broker_accounts']
        
        # Check if Fyers broker already exists
        existing_fyers = broker_accounts.find_one({"broker_type": "fyers"})
        if existing_fyers:
            print("⚠️  Fyers broker already exists in broker_accounts")
            print(f"   Display Name: {existing_fyers.get('display_name')}")
            print(f"   Broker ID: {existing_fyers.get('broker_id')}")
            return True
        
        # Prepare broker account document
        broker_id = f"fyers_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        broker_account = {
            "broker_id": broker_id,
            "broker_type": "fyers",
            "display_name": "Fyers - Main",
            "is_default": True,
            "enabled": True,
            "trading_mode": "NORMAL",
            
            # Credentials
            "api_key": FYERS_CLIENT_ID,
            "api_secret": FYERS_SECRET_ID,
            
            # Token data
            "access_token": existing_token.get("access_token"),
            "refresh_token": existing_token.get("refresh_token"),
            "token_generated_at": existing_token.get("generated_at"),
            "token_status": "valid",  # Will be checked at runtime
            
            # Metadata
            "created_at": datetime.now(UTC),
            "last_run_at": None
        }
        
        # Insert the broker account
        result = broker_accounts.insert_one(broker_account)
        
        print("✅ Migration successful!")
        print(f"   Broker ID: {broker_id}")
        print(f"   Display Name: Fyers - Main")
        print(f"   Status: Default & Enabled")
        print(f"   Trading Mode: NORMAL")
        
        print("\n📝 Note: The old fyers_tokens collection is still intact.")
        print("   You can safely delete it after verifying the migration.")
        
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def verify_migration():
    """Verify the migration was successful"""
    
    if not MONGO_URI:
        print("❌ MONGO_URI not found")
        return
    
    try:
        client = MongoClient(MONGO_URI, tz_aware=True, tzinfo=UTC)
        db = client[MONGO_DB_NAME]
        
        broker_accounts = db['broker_accounts']
        count = broker_accounts.count_documents({})
        
        print(f"\n📊 Verification:")
        print(f"   Total broker accounts: {count}")
        
        if count > 0:
            print("\n   Broker Accounts:")
            for broker in broker_accounts.find():
                print(f"   - {broker.get('display_name')} ({broker.get('broker_type')})")
                print(f"     ID: {broker.get('broker_id')}")
                print(f"     Default: {broker.get('is_default')}")
                print(f"     Enabled: {broker.get('enabled')}")
                print(f"     Mode: {broker.get('trading_mode')}")
                print()
        
    except Exception as e:
        print(f"❌ Verification failed: {e}")

if __name__ == "__main__":
    print("=" * 60)
    print("Multi-Broker Migration Script")
    print("=" * 60)
    
    success = migrate_to_multi_broker()
    
    if success:
        verify_migration()
        print("\n✅ Migration complete!")
    else:
        print("\n❌ Migration failed!")
