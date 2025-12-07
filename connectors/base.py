from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
import datetime

class BrokerConnector(ABC):
    """
    Abstract Base Class for Broker Connectors.
    Defines the standard interface for all broker interactions.
    """
    def __init__(self, api_key: str, api_secret: str, access_token: Optional[str] = None, **kwargs):
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token
        self.name = "generic"

    # --- Authentication ---
    @abstractmethod
    def get_login_url(self, redirect_uri: str) -> str:
        """Returns the URL for the user to initiate OAuth2 login."""
        pass

    @abstractmethod
    def generate_session(self, auth_code: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchanges auth code for access/refresh tokens."""
        pass

    @abstractmethod
    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refreshes the access token using a refresh token."""
        pass

    @abstractmethod
    def is_token_valid(self) -> bool:
        """Checks if the current access token is valid."""
        pass

    # --- Market Data ---
    @abstractmethod
    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """Fetches real-time quote for a symbol."""
        pass

    @abstractmethod
    def get_historical_data(self, symbol: str, resolution: str, from_date: str, to_date: str) -> Dict[str, Any]:
        """Fetches historical candle data."""
        pass

    @abstractmethod
    def get_orderbook(self, symbol: str) -> Dict[str, Any]:
        """Fetches market depth/orderbook."""
        pass

    # --- User Data ---
    @abstractmethod
    def get_holdings(self) -> List[Dict[str, Any]]:
        """Fetches current long-term holdings."""
        pass

    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        """Fetches current day/open positions."""
        pass

    @abstractmethod
    def get_funds(self) -> Dict[str, Any]:
        """Fetches account balance and limits."""
        pass

    @abstractmethod
    def get_profile(self) -> Dict[str, Any]:
        """Fetches user profile details."""
        pass

    # --- Trading ---
    @abstractmethod
    def place_order(self, symbol: str, qty: int, side: str, order_type: str, price: float = 0.0, trigger_price: float = 0.0, **kwargs) -> Dict[str, Any]:
        """Places a buy/sell order."""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancels an open order."""
        pass

    @abstractmethod
    def modify_order(self, order_id: str, new_price: float = 0.0, new_qty: int = 0, **kwargs) -> Dict[str, Any]:
        """Modifies an open order."""
        pass

    @abstractmethod
    def get_orders(self) -> List[Dict[str, Any]]:
        """Fetches order history for the day."""
        pass

    @abstractmethod
    def get_trades(self) -> List[Dict[str, Any]]:
        """Fetches trade history for the day."""
        pass
