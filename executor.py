import subprocess
import sys
import argparse
import os
from pymongo import MongoClient
from datetime import datetime
import uuid
from config import MONGO_DB_NAME, MONGO_ENV
from dotenv import load_dotenv
import pytz

# Define timezones
UTC = pytz.utc
IST = pytz.timezone('Asia/Kolkata')

def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Execute trading strategy components.")
    parser.add_argument("--run-id", type=str, help="Unique ID for this strategy run.")
    args = parser.parse_args()

    run_id = args.run_id if args.run_id else str(uuid.uuid4())

    script_dir = os.path.dirname(__file__)

    # MongoDB setup
    MONGO_URI = os.getenv('MONGO_URI')
    db = None
    strategy_runs_collection = None

    if MONGO_URI:
        try:
            client = MongoClient(MONGO_URI)
            db = client[MONGO_DB_NAME]
            strategy_runs_collection = db[f"strategy_runs_{MONGO_ENV}"]
            print("[INFO] MongoDB connected successfully in executor.py")
        except Exception as e:
            print(f"[ERROR] Could not connect to MongoDB: {e}")
            db = None
            strategy_runs_collection = None
    else:
        print("[ERROR] MONGO_URI not found in environment variables. Strategy run logging will be disabled.")

    # Record strategy run start
    if strategy_runs_collection is not None:
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

    run_status = "failed" # Default to failed, update to completed on success
    if strategy_runs_collection is not None:
        try:
            # Run token_refresh.py (assuming it doesn't need run_id for logging)
            token_refresh_path = os.path.join(script_dir, "token_refresh.py")
            subprocess.run([sys.executable, token_refresh_path], check=True)

            # Run live_stratergy.py and pass the run_id
            live_strategy_path = os.path.join(script_dir, "live_stratergy.py")
            subprocess.run([sys.executable, live_strategy_path, "--run-id", run_id], check=True)
            run_status = "completed"
        except Exception as e:
            print(f"[ERROR] Strategy execution failed: {e}")
            run_status = "failed"
        finally:
            if strategy_runs_collection is not None:
                try:
                    end_time = datetime.now(UTC)
                    run_doc = strategy_runs_collection.find_one({"run_id": run_id})
                    start_time = run_doc.get("run_time") if run_doc else None

                    if start_time and start_time.tzinfo is None:
                        start_time = UTC.localize(start_time)

                    update_fields = {"end_time": end_time, "status": run_status}
                    if start_time:
                        duration_delta = end_time - start_time
                        update_fields["duration_seconds"] = duration_delta.total_seconds()

                    strategy_runs_collection.update_one(
                        {"run_id": run_id},
                        {"$set": update_fields}
                    )
                    print(f"[INFO] Updated strategy run {run_id} with status: {run_status}")
                except Exception as e:
                    print(f"[ERROR] Failed to update strategy run status in MongoDB: {e}")

if __name__ == "__main__":
    main()