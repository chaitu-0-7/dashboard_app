# Multi-Broker Connector Migration Plan

## Objective
Migrate the existing Nifty Shop application from a single-broker (Fyers) dependency to a multi-broker architecture. This will allow users to connect different brokers (e.g., Zerodha, Angel One) and manage multiple portfolios.

## Current State
The application is tightly coupled with the Fyers API v3.
- **Auth**: `token_refresh.py` handles Fyers-specific OAuth2 flow and custom token refresh logic.
- **Trading**: `live_stratergy.py` directly instantiates `fyersModel` and calls Fyers-specific methods (`place_order`, `orderbook`, etc.).
- **Dashboard**: `app.py` uses `fyersModel` to fetch holdings and positions.
- **Configuration**: Credentials are loaded from environment variables specific to Fyers (`FYERS_CLIENT_ID`, etc.).

## Proposed Architecture

We will introduce a `BrokerConnector` abstract base class (ABC) that defines the standard interface for all broker interactions.

### 1. Abstract Base Class (`BrokerConnector`)

```python
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any

class BrokerConnector(ABC):
    def __init__(self, api_key: str, api_secret: str, access_token: Optional[str] = None, **kwargs):
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token

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
```

### 2. Data Normalization
Each broker returns data in different formats. The connector must normalize this into a standard format used by the app.

**Example: Standard Position Object**
```python
{
    "symbol": "NSE:SBIN-EQ",
    "qty": 50,
    "avg_price": 500.0,
    "ltp": 505.0,
    "pnl": 250.0,
    "product_type": "INTRADAY", # Normalized from CNC/MIS/BO/CO
    "side": "BUY" # Normalized from 1/-1 or BUY/SELL
}
```

### 3. Configuration Management
We need a new configuration structure to support multiple brokers per user.

**Proposed `user_brokers` Collection in MongoDB:**
```json
{
    "user_id": "user_123",
    "broker_name": "fyers",
    "credentials": {
        "client_id": "...",
        "secret_id": "...",
        "pin": "..."
    },
    "tokens": {
        "access_token": "...",
        "refresh_token": "...",
        "generated_at": "..."
    },
    "is_active": true
}
```

## Migration Steps

1.  **Define Interface**: Create `connectors/base.py` with the `BrokerConnector` class.
2.  **Implement Fyers**: Create `connectors/fyers.py` implementing `BrokerConnector` using existing logic from `token_refresh.py` and `live_stratergy.py`.
3.  **Refactor Auth**: Update `auth.py` and `token_refresh.py` to use the new `BrokerConnector` for login and token management.
4.  **Refactor Strategy**: Update `live_stratergy.py` to accept a `BrokerConnector` instance instead of `fyersModel`.
5.  **Refactor Dashboard**: Update `app.py` to use the connector for fetching data.
6.  **Add New Broker**: Once the abstraction is stable, implement `connectors/zerodha.py` (or others).

## API Mapping (Fyers -> Generic)

| Generic Method | Fyers API Method | Notes |
| :--- | :--- | :--- |
| `get_login_url` | `session.generate_authcode()` | |
| `generate_session` | `session.generate_token()` | |
| `refresh_token` | `requests.post(validate-refresh-token)` | Custom implementation in `token_refresh.py` |
| `get_holdings` | `fyers.holdings()` | |
| `get_positions` | `fyers.positions()` | |
| `get_funds` | `fyers.funds()` | |
| `place_order` | `fyers.place_order()` | Needs param mapping (e.g. `side` 1/-1 -> BUY/SELL) |
| `get_quote` | `fyers.quotes()` | |
| `get_orderbook` | `fyers.orderbook()` | |

## Zerodha (Kite Connect) Integration

**Status**: Paid API (₹2000/month).
**Constraint**: User prefers using `yfinance` for historical data to avoid potential extra costs or API limits, though recent updates suggest history might be included. We will support a **Hybrid Data Mode**.

### API Mapping (Zerodha -> Generic)

| Generic Method | Kite Connect Method | Notes |
| :--- | :--- | :--- |
| `get_login_url` | `kite.login_url()` | |
| `generate_session` | `kite.generate_session()` | Returns `access_token` and `public_token` |
| `refresh_token` | N/A | Kite tokens are valid for 1 day. Re-login required daily. No refresh token flow like Fyers. |
| `get_holdings` | `kite.holdings()` | |
| `get_positions` | `kite.positions()` | Returns `net` and `day` positions. Use `net`. |
| `get_funds` | `kite.margins()` | |
| `place_order` | `kite.place_order()` | |
| `get_quote` | `kite.quote()` | |
| `get_orderbook` | `kite.orders()` | Kite returns all orders. Filter by order_id for specific book? Or just use orders list. |

### Hybrid Data Strategy

To support the user's request for free data sources (like `yfinance`) while using the broker for execution, we will add a `DataSource` abstraction.

**Proposed `DataSource` Interface:**
```python
class DataSource(ABC):
    @abstractmethod
    def get_historical_data(self, symbol: str, resolution: str, from_date: str, to_date: str) -> pd.DataFrame:
        pass
    
    @abstractmethod
    def get_quote(self, symbol: str) -> float:
        pass
```

**Configuration Update:**
The `UserBrokerConfig` will now have a `data_source` field.
```json
{
    "broker": "zerodha",
    "data_source": "yfinance", # or "broker"
    ...
}
```

If `data_source == "yfinance"`, the `BrokerConnector.get_historical_data` will delegate to a `YFinanceConnector` instead of the broker's API.

## Dhan (DhanHQ) Integration

**Status**: Free API (for trading).
**Library**: `dhanhq` (Official Python Client).

### API Mapping (Dhan -> Generic)

| Generic Method | DhanHQ Method | Notes |
| :--- | :--- | :--- |
| `get_login_url` | N/A | Dhan uses Client ID + Access Token directly. No OAuth2 flow needed for personal use? *Verify if OAuth is needed for multi-user app.* |
| `generate_session` | N/A | Access Token is long-lived or generated via portal. |
| `refresh_token` | N/A | Tokens are managed via Dhan web portal. |
| `get_holdings` | `dhan.get_holdings()` | |
| `get_positions` | `dhan.get_positions()` | |
| `get_funds` | `dhan.get_fund_limits()` | |
| `place_order` | `dhan.place_order()` | |
| `get_quote` | N/A | DhanHQ might not have a direct "quote" method in the same way. Might need to use websocket or specific market feed API if available. |
| `get_orderbook` | `dhan.get_order_list()` | |

**Note on Dhan Auth**: DhanHQ for individual users typically uses a fixed Access Token generated from their web portal. For a multi-user app (if we are building a platform), we might need their "Connect" (OAuth) flow. For now, we assume users will provide their Access Token directly.


