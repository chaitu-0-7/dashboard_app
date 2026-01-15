import os

# MongoDB Configuration
MONGO_DB_NAME = 'nifty_shop'
MONGO_ENV = os.getenv('ENV', 'prod') # Defaults to 'prod' if not set
print(f"DEBUG: Config loaded. ENV={os.getenv('ENV')}, MONGO_ENV={MONGO_ENV}")

# Application Logging & UI
APP_LOGS_PER_PAGE_HOME = 10

# Fyers API Configuration
FYERS_REDIRECT_URI = 'https://trade.fyers.in/api-login/redirect-uri/index.html' # Replace with your actual redirect URI

# Strategy Parameters
STRATEGY_CAPITAL = 40000 # Total capital allocated for this strategy

MAX_TRADE_VALUE = 4000

MA_PERIOD = 30

# Token Validity (in seconds)
ACCESS_TOKEN_VALIDITY = 24 * 60 * 60        # 1 day
REFRESH_TOKEN_VALIDITY = 15 * ACCESS_TOKEN_VALIDITY  # 15 days
