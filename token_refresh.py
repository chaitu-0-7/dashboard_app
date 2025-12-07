import os
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from config import MONGO_DB_NAME, ACCESS_TOKEN_VALIDITY, REFRESH_TOKEN_VALIDITY, FYERS_REDIRECT_URI
from pymongo import MongoClient
import pytz

from connectors.fyers import FyersConnector

# Define timezones
UTC = pytz.utc

load_dotenv()

# ---- Your Fyers app credentials here ----
CLIENT_ID = os.getenv('FYERS_CLIENT_ID')           # Your Fyers client ID
SECRET_ID = os.getenv('FYERS_SECRET_ID')               # Your Fyers secret key
PIN = os.getenv('FYERS_PIN')                          # Your 4-digit PIN for token refresh and generation
REDIRECT_URI = FYERS_REDIRECT_URI

# MongoDB Configuration
MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = MONGO_DB_NAME

# Connect to MongoDB
if MONGO_URI:
    mongo_client = MongoClient(MONGO_URI, tz_aware=True, tzinfo=UTC)
    db = mongo_client[MONGO_DB_NAME]
    fyers_tokens_collection = db['fyers_tokens']
else:
    print("Could not find MongoDB URI in .env file. Token storage will not work.")
    mongo_client = None
    db = None
    fyers_tokens_collection = None

# Initialize Connector (without token initially)
connector = FyersConnector(
    api_key=CLIENT_ID,
    api_secret=SECRET_ID,
    pin=PIN
)

def save_tokens(token_data):
    if fyers_tokens_collection is not None:
        # Use upsert to insert if not exists, or update if exists
        fyers_tokens_collection.update_one(
            {"_id": "fyers_token_data"}, # Use a fixed ID for the single token document
            {"$set": token_data},
            upsert=True
        )
        print("[INFO] Token data saved to MongoDB.")
    else:
        print("[ERROR] MongoDB connection not established. Cannot save tokens.")


def load_tokens():
    if fyers_tokens_collection is not None:
        return fyers_tokens_collection.find_one({"_id": "fyers_token_data"})
    else:
        print("[ERROR] MongoDB connection not established. Cannot load tokens.")
        return None


def is_access_token_valid(generated_at):
    if generated_at is None:
        return False
    return datetime.now(UTC) < generated_at + timedelta(seconds=ACCESS_TOKEN_VALIDITY)


def is_refresh_token_valid(generated_at):
    if generated_at is None:
        return False
    return datetime.now(UTC) < generated_at + timedelta(seconds=REFRESH_TOKEN_VALIDITY)


def manual_auth_code_flow():
    """
    Guide the user through manual auth code generation using FyersConnector.
    """
    auth_url = connector.get_login_url(redirect_uri=REDIRECT_URI)
    print("\n========= Manual Token Generation =========")
    print("1) Please open this URL in your web browser:\n")
    print(auth_url)
    print(
        "\n2) Login with your Fyers credentials, enter PIN and TOTP as needed."
        "\n3) After successful login, you will be redirected to your redirect URI with a URL param 'code'."
    )
    print("   Example: https://your_redirect_uri?code=AUTH_CODE_HERE\n")
    auth_code = input("4) Copy the 'code' parameter from the URL and paste it here: ").strip()

    if not auth_code:
        print("[ERROR] No authorization code entered. Aborting.")
        return None

    try:
        print("[INFO] Exchanging authorization code for access and refresh tokens...")
        token_response = connector.generate_session(auth_code, redirect_uri=REDIRECT_URI)
        
        token_response["generated_at"] = datetime.now(UTC)
        save_tokens(token_response)
        print("[SUCCESS] Tokens generated and saved.")
        return token_response
    except Exception as e:
        print(f"[ERROR] Failed to generate tokens: {e}")
        return None


def main():
    tokens = load_tokens()

    if tokens:
        gen_time = tokens.get("generated_at")
        # Ensure gen_time is a timezone-aware datetime object
        if isinstance(gen_time, (int, float)):
            gen_time = datetime.fromtimestamp(gen_time, tz=UTC)
        elif isinstance(gen_time, datetime) and gen_time.tzinfo is None:
            gen_time = UTC.localize(gen_time)

        if is_access_token_valid(gen_time):
            print("[INFO] Access token is valid.")
        else:
            print("[INFO] Access token expired. Attempting refresh token flow...")
            if is_refresh_token_valid(gen_time):
                try:
                    # Update connector with current refresh token
                    refreshed = connector.refresh_token(tokens["refresh_token"])
                    
                    # Save new tokens
                    token_data = {
                        "access_token": refreshed["access_token"],
                        "refresh_token": refreshed.get("refresh_token", tokens["refresh_token"]),
                        "generated_at": datetime.now(UTC)
                    }
                    save_tokens(token_data)
                    print(f"New Access Token: ***** ")
                except Exception as e:
                    print(f"[ERROR] Refresh token failed: {e}")
                    print("Manual auth code flow required.")
                    manual_auth_code_flow()
            else:
                print("[WARNING] Refresh token expired or invalid. Manual auth code flow required.")
                manual_auth_code_flow()
    else:
        print("[INFO] No tokens found locally. Starting manual auth code generation flow.")
        manual_auth_code_flow()


if __name__ == "__main__":
    main()
