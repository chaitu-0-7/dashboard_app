import subprocess
import sys
import argparse
import os

def main():
    parser = argparse.ArgumentParser(description="Execute trading strategy components.")
    parser.add_argument("--run-id", type=str, help="Unique ID for this strategy run.")
    args = parser.parse_args()

    run_id = args.run_id if args.run_id else "unknown_run"

    script_dir = os.path.dirname(__file__)

    # Run token_refresh.py (assuming it doesn't need run_id for logging)
    token_refresh_path = os.path.join(script_dir, "token_refresh.py")
    subprocess.run([sys.executable, token_refresh_path], check=True)

    # Run live_stratergy.py and pass the run_id
    live_strategy_path = os.path.join(script_dir, "live_stratergy.py")
    subprocess.run([sys.executable, live_strategy_path, "--run-id", run_id], check=True)

if __name__ == "__main__":
    main()