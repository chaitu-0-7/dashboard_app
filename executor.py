import subprocess
import sys
import argparse
import os
from pymongo import MongoClient
from datetime import datetime
import uuid
from dotenv import load_dotenv
load_dotenv()
from config import MONGO_DB_NAME, MONGO_ENV
import pytz

# Import Connector
from connectors.fyers import FyersConnector

# Define timezones
UTC = pytz.utc
IST = pytz.timezone('Asia/Kolkata')

def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Execute trading strategy components.")
    parser.add_argument("--run-id", type=str, help="Unique ID for this strategy run.")
    parser.add_argument("--broker-id", type=str, help="Run for specific broker only (optional)")
    args = parser.parse_args()

    run_id = args.run_id if args.run_id else str(uuid.uuid4())
    specific_broker_id = args.broker_id

    script_dir = os.path.dirname(__file__)

    # MongoDB setup
    MONGO_URI = os.getenv('MONGO_URI')
    
    if not MONGO_URI:
        print("[ERROR] MONGO_URI not found in environment variables.")
        return

    try:
        client = MongoClient(MONGO_URI, tz_aware=True, tzinfo=UTC)
        db = client[MONGO_DB_NAME]
        strategy_runs_collection = db[f"strategy_runs_{MONGO_ENV}"]
        broker_accounts = db['broker_accounts']
        print("[INFO] MongoDB connected successfully in executor.py")
    except Exception as e:
        print(f"[ERROR] Could not connect to MongoDB: {e}")
        return

    # Record strategy run start
    try:
        strategy_runs_collection.insert_one({
            "run_id": run_id,
            "run_time": datetime.now(UTC),
            "status": "running",
            "triggered_by": "executor.py"
        })
        print(f"[INFO] Recorded strategy run start with ID: {run_id}")
    except Exception as e:
        print(f"[ERROR] Failed to record strategy run start in MongoDB: {e}")

    # Get brokers to execute
    if specific_broker_id:
        # Run for specific broker only
        brokers = list(broker_accounts.find({"broker_id": specific_broker_id}))
        if not brokers:
            print(f"[ERROR] Broker with ID '{specific_broker_id}' not found")
            return
    else:
        # Run for all enabled brokers
        brokers = list(broker_accounts.find({"enabled": True}))
    
    if not brokers:
        print("[WARNING] No enabled brokers found. Nothing to execute.")
        return
    
    print(f"\n{'='*60}")
    print(f"Found {len(brokers)} broker(s) to execute")
    print(f"{'='*60}\n")
    
    overall_status = "completed"
    
    for broker in brokers:
        broker_id = broker.get('broker_id')
        display_name = broker.get('display_name')
        broker_type = broker.get('broker_type')
        trading_mode = broker.get('trading_mode', 'NORMAL')
        username = broker.get('username', 'chaitu_shop') # Default for legacy
        
        print(f"\n{'─'*60}")
        print(f"🔗 Broker: {display_name} ({broker_type})")
        print(f"   ID: {broker_id}")
        print(f"   User: {username}")
        print(f"   Mode: {trading_mode}")
        print(f"{'─'*60}\n")
        
        # Skip if paused
        if trading_mode == 'PAUSED':
            print(f"⏸️  Skipping {display_name} - Trading mode is PAUSED")
            continue
        
        try:
            # --- Token Refresh Logic ---
            if broker_type == 'fyers':
                api_key = broker.get('api_key')
                api_secret = broker.get('api_secret')
                pin = broker.get('pin', '')
                refresh_token = broker.get('refresh_token')
                access_token = broker.get('access_token')
                
                if not all([api_key, api_secret, access_token]):
                    print(f"[ERROR] Incomplete credentials for {display_name}")
                    overall_status = "failed"
                    continue
                
                connector = FyersConnector(
                    api_key=api_key,
                    api_secret=api_secret,
                    access_token=access_token,
                    pin=pin
                )
                
                # Check validity and refresh if needed
                if not connector.is_token_valid():
                    print("[INFO] Access token invalid/expired. Attempting refresh...")
                    try:
                        refreshed_tokens = connector.refresh_token(refresh_token)
                        # Update broker account with new tokens
                        broker_accounts.update_one(
                            {"broker_id": broker_id},
                            {"$set": {
                                "access_token": refreshed_tokens["access_token"],
                                "refresh_token": refreshed_tokens.get("refresh_token", refresh_token),
                                "token_generated_at": datetime.now(UTC),
                                "token_status": "valid"
                            }}
                        )
                        print("[INFO] Token refreshed successfully.")
                    except Exception as e:
                        print(f"[ERROR] Token refresh failed for {display_name}: {e}")
                        broker_accounts.update_one(
                            {"broker_id": broker_id},
                            {"$set": {"token_status": "expired"}}
                        )
                        overall_status = "failed"
                        continue
                else:
                    print("[INFO] Access token is valid.")
            
            elif broker_type == 'zerodha':
                # Zerodha tokens are session-based, no refresh needed
                print("[INFO] Zerodha token check (session-based, no refresh)")
            
            # --- Run Strategy for this broker ---
            live_strategy_path = os.path.join(script_dir, "live_stratergy.py")
            cmd = [sys.executable, live_strategy_path, "--run-id", run_id, "--broker-id", broker_id, "--username", username]
            
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True
            )
            
            if result.stdout:
                print(f"[SUBPROCESS OUTPUT] {result.stdout}")
            if result.stderr:
                print(f"[SUBPROCESS ERROR] {result.stderr}")
                
            print(f"✅ Strategy completed for {display_name}")
            
            # Update last_run_at
            broker_accounts.update_one(
                {"broker_id": broker_id},
                {"$set": {"last_run_at": datetime.now(UTC)}}
            )
            
        except subprocess.CalledProcessError as e:
            print(f"❌ Strategy execution failed for {display_name}")
            print(f"   Error: {e}")
            if e.stdout:
                print(f"   Output: {e.stdout}")
            if e.stderr:
                print(f"   Error output: {e.stderr}")
            overall_status = "failed"
        except Exception as e:
            print(f"❌ Unexpected error for {display_name}: {e}")
            overall_status = "failed"
    
    # Update strategy run status
    try:
        end_time = datetime.now(UTC)
        run_doc = strategy_runs_collection.find_one({"run_id": run_id})
        start_time = run_doc.get("run_time") if run_doc else None

        if start_time and start_time.tzinfo is None:
            start_time = UTC.localize(start_time)

        update_fields = {"end_time": end_time, "status": overall_status}
        if start_time:
            duration_delta = end_time - start_time
            update_fields["duration_seconds"] = duration_delta.total_seconds()

        strategy_runs_collection.update_one(
            {"run_id": run_id},
            {"$set": update_fields}
        )
        print(f"\n[INFO] Updated strategy run {run_id} with status: {overall_status}")
    except Exception as e:
        print(f"[ERROR] Failed to update strategy run status in MongoDB: {e}")

if __name__ == "__main__":
    main()