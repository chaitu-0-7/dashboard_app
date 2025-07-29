import os
import json
import time
import hashlib
import requests
from datetime import datetime, timedelta
from fyers_apiv3 import fyersModel
from urllib.parse import urlencode
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

# ---- Your Fyers app credentials here ----
CLIENT_ID = os.getenv('FYERS_CLIENT_ID')           # Your Fyers client ID
SECRET_ID = os.getenv('FYERS_SECRET_ID')               # Your Fyers secret key
PIN = os.getenv('FYERS_PIN')                          # Your 4-digit PIN for token refresh and generation
REDIRECT_URI = os.getenv('FYERS_REDIRECT_URI')  # must match app config

# MongoDB Configuration
MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'nifty_shop')

# Connect to MongoDB
if MONGO_URI:
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[MONGO_DB_NAME]
    fyers_tokens_collection = db['fyers_tokens']
else:
    print("Could not find MongoDB URI in .env file. Token storage will not work.")
    mongo_client = None
    db = None
    fyers_tokens_collection = None

# Fyers API URLs (auth URL base is used by fyersModel, refresh is custom)
REFRESH_TOKEN_URL = "https://api-t1.fyers.in/api/v3/validate-refresh-token"

# Token validity (seconds)
ACCESS_TOKEN_VALIDITY = 24 * 60 * 60        # 1 day
REFRESH_TOKEN_VALIDITY = 15 * ACCESS_TOKEN_VALIDITY  # 15 days

# Initialize Fyers session model
session = fyersModel.SessionModel(
    client_id=CLIENT_ID,
    secret_key=SECRET_ID,
    redirect_uri=REDIRECT_URI,
    response_type="code",
    grant_type="authorization_code"
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
    token_time = datetime.fromtimestamp(generated_at)
    return datetime.now() < token_time + timedelta(seconds=ACCESS_TOKEN_VALIDITY)


def is_refresh_token_valid(generated_at):
    token_time = datetime.fromtimestamp(generated_at)
    return datetime.now() < token_time + timedelta(seconds=REFRESH_TOKEN_VALIDITY)


def refresh_access_token_custom(refresh_token, client_id, secret_id, pin):
    """
    Refresh access token using the exact format provided in the CURL example.

    Returns dict with new tokens on success, or None on failure.
    """
    app_id_hash = hashlib.sha256(f"{client_id}:{secret_id}".encode()).hexdigest()
    headers = {"Content-Type": "application/json"}
    payload = {
        "grant_type": "refresh_token",
        "appIdHash": app_id_hash,
        "refresh_token": refresh_token,
        "pin": pin
    }

    print("[INFO] Sending refresh token request to Fyers API...")
    resp = requests.post(REFRESH_TOKEN_URL, json=payload, headers=headers)

    if resp.status_code == 200:
        data = resp.json()
        if data.get("code") == 200 and "access_token" in data:
            print("[SUCCESS] Access token refreshed successfully.")
            # Save new tokens with current timestamp
            token_data = {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token", refresh_token),  # Fyers may or may not return new refresh token
                "generated_at": int(time.time())
            }
            save_tokens(token_data)
            return token_data
        else:
            print("[ERROR] Unexpected response JSON during refresh:", data)
    else:
        print(f"[ERROR] Failed refresh request. HTTP {resp.status_code}: {resp.text}")

    return None


def manual_auth_code_flow():
    """
    Guide the user through manual auth code generation using Fyers SDK SessionModel.
    User must open auth url, login, complete 2FA, and paste `code` parameter.
    Then exchanges auth code for tokens and saves them.
    """
    auth_url = session.generate_authcode()
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

    session.set_token(auth_code)
    print("[INFO] Exchanging authorization code for access and refresh tokens...")
    token_response = session.generate_token()

    if token_response.get("access_token"):
        token_response["generated_at"] = int(time.time())
        save_tokens(token_response)
        print("[SUCCESS] Tokens generated and saved.")
        return token_response
    else:
        print("[ERROR] Failed to generate tokens. Response:", token_response)
        return None


def main():
    tokens = load_tokens()

    if tokens:
        gen_time = tokens.get("generated_at", 0)
        if is_access_token_valid(gen_time):
            # manual_auth_code_flow()
            print("[INFO] Access token is valid.")
            print(f"Access Token: {tokens['access_token']}")
        else:
            print("[INFO] Access token expired. Attempting refresh token flow...")
            if is_refresh_token_valid(gen_time):
                refreshed = refresh_access_token_custom(tokens["refresh_token"], CLIENT_ID, SECRET_ID, PIN)
                if refreshed:
                    print(f"New Access Token: {refreshed['access_token']}")
                else:
                    print("[ERROR] Refresh token failed, manual auth code flow required.")
                    manual_auth_code_flow()
            else:
                print("[WARNING] Refresh token expired or invalid. Manual auth code flow required.")
                manual_auth_code_flow()
    else:
        print("[INFO] No tokens found locally. Starting manual auth code generation flow.")
        manual_auth_code_flow()


if __name__ == "__main__":
    main()
