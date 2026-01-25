import os
import tempfile
import requests
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from fyers_apiv3 import fyersModel
import pytz

from .base import BrokerConnector

UTC = pytz.utc

class FyersConnector(BrokerConnector):
    def __init__(self, api_key: str, api_secret: str, access_token: Optional[str] = None, pin: Optional[str] = None, **kwargs):
        super().__init__(api_key, api_secret, access_token, **kwargs)
        self.pin = pin
        self.name = "fyers"
        self.fyers = None
        if access_token:
            self._initialize_fyers_model()

    def _initialize_fyers_model(self):
        """Initializes the FyersModel instance with the current access token."""
        if self.access_token:
            log_path = os.path.join(tempfile.gettempdir(), "fyers_logs")
            if not os.path.exists(log_path):
                os.makedirs(log_path, exist_ok=True)
                
            self.fyers = fyersModel.FyersModel(
                client_id=self.api_key,
                token=self.access_token,
                log_path=log_path
            )
        else:
            self.fyers = None

    # --- Authentication ---
    def get_login_url(self, redirect_uri: str) -> str:
        session = fyersModel.SessionModel(
            client_id=self.api_key,
            secret_key=self.api_secret,
            redirect_uri=redirect_uri,
            response_type="code",
            grant_type="authorization_code"
        )
        return session.generate_authcode()

    def generate_session(self, auth_code: str, redirect_uri: str) -> Dict[str, Any]:
        session = fyersModel.SessionModel(
            client_id=self.api_key,
            secret_key=self.api_secret,
            redirect_uri=redirect_uri,
            response_type="code",
            grant_type="authorization_code"
        )
        session.set_token(auth_code)
        response = session.generate_token()
        
        if response.get("access_token"):
            self.access_token = response["access_token"]
            self._initialize_fyers_model()
            return response
        else:
            raise Exception(f"Failed to generate token: {response}")

    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        # Custom refresh logic from token_refresh.py
        app_id_hash = hashlib.sha256(f"{self.api_key}:{self.api_secret}".encode()).hexdigest()
        url = "https://api-t1.fyers.in/api/v3/validate-refresh-token"
        headers = {"Content-Type": "application/json"}
        payload = {
            "grant_type": "refresh_token",
            "appIdHash": app_id_hash,
            "refresh_token": refresh_token,
            "pin": self.pin
        }

        resp = requests.post(url, json=payload, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 200 and "access_token" in data:
                self.access_token = data["access_token"]
                self._initialize_fyers_model()
                return data
            else:
                raise Exception(f"Refresh failed: {data}")
        else:
            raise Exception(f"Refresh HTTP failed: {resp.text}")

    def is_token_valid(self) -> bool:
        # This is a heuristic. Ideally we check expiry time if stored.
        # Or we can make a lightweight API call.
        if not self.fyers:
            return False
        try:
            self.fyers.get_profile()
            return True
        except:
            return False

    # --- Market Data ---
    def get_quote(self, symbol: str) -> Dict[str, Any]:
        data = {"symbols": symbol}
        return self.fyers.quotes(data)

    def get_historical_data(self, symbol: str, resolution: str, from_date: str, to_date: str) -> Dict[str, Any]:
        data = {
            "symbol": symbol,
            "resolution": resolution,
            "date_format": "1",
            "range_from": from_date,
            "range_to": to_date,
            "cont_flag": "1"
        }
        return self.fyers.history(data)

    def get_orderbook(self, symbol: str) -> Dict[str, Any]:
        # Fyers orderbook API usually takes no args for full depth or specific symbol
        # The generic interface asks for symbol, but Fyers might return all?
        # Let's check live_stratergy.py usage: self.fyers.orderbook(data) where data={"symbol":...}
        data = {"symbol": symbol, "ohlcv_flag": "1"}
        return self.fyers.orderbook(data)

    # --- User Data ---
    def get_holdings(self) -> List[Dict[str, Any]]:
        response = self.fyers.holdings()
        if response.get("code") == 200:
            return response.get("holdings", [])
        else:
            raise Exception(f"Failed to fetch holdings: {response}")

    def get_positions(self) -> List[Dict[str, Any]]:
        response = self.fyers.positions()
        if response.get("code") == 200:
            return response.get("netPositions", [])
        else:
            raise Exception(f"Failed to fetch positions: {response}")

    def get_funds(self) -> Dict[str, Any]:
        response = self.fyers.funds()
        if response.get("code") == 200:
            return response.get("fund_limit", [])
        else:
            raise Exception(f"Failed to fetch funds: {response}")

    def get_profile(self) -> Dict[str, Any]:
        return self.fyers.get_profile()

    # --- Trading ---
    def place_order(self, symbol: str, qty: int, side: str, order_type: str, price: float = 0.0, trigger_price: float = 0.0, **kwargs) -> Dict[str, Any]:
        # Map generic side to Fyers side
        fyers_side = 1 if side.upper() == "BUY" else -1
        
        # Map generic type to Fyers type (1: Limit, 2: Market, 3: Stop, 4: StopLimit)
        type_map = {
            "LIMIT": 1,
            "MARKET": 2,
            "STOP_LOSS_MARKET": 3,
            "STOP_LOSS_LIMIT": 4
        }
        fyers_type = type_map.get(order_type.upper(), 2) # Default to Market

        data = {
            "symbol": symbol,
            "qty": qty,
            "type": fyers_type,
            "side": fyers_side,
            "productType": kwargs.get("productType", "INTRADAY"), # CNC or INTRADAY
            "limitPrice": price,
            "stopPrice": trigger_price,
            "validity": "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
        }
        return self.fyers.place_order(data)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        data = {"id": order_id}
        return self.fyers.cancel_order(data)

    def modify_order(self, order_id: str, new_price: float = 0.0, new_qty: int = 0, **kwargs) -> Dict[str, Any]:
        # This needs careful mapping as Fyers modify takes specific dict
        # For now, basic implementation
        data = {"id": order_id}
        if new_price > 0:
            data["limitPrice"] = new_price
        if new_qty > 0:
            data["qty"] = new_qty
        return self.fyers.modify_order(data)

    def get_orders(self) -> List[Dict[str, Any]]:
        response = self.fyers.orderbook()
        if response.get("code") == 200:
            return response.get("orderBook", [])
        else:
            raise Exception(f"Failed to fetch orders: {response}")

    def get_trades(self) -> List[Dict[str, Any]]:
        response = self.fyers.tradebook()
        if response.get("code") == 200:
            return response.get("tradeBook", [])
        else:
            raise Exception(f"Failed to fetch trades: {response}")
