import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

try:
    from connectors.base import BrokerConnector
    from connectors.fyers import FyersConnector
    print("Imports successful.")
    
    # Try instantiating with dummy data
    connector = FyersConnector(api_key="test", api_secret="test", access_token="test_token")
    print(f"Instantiated connector: {connector.name}")
    print("Verification passed.")
except Exception as e:
    print(f"Verification failed: {e}")
    import traceback
    traceback.print_exc()
