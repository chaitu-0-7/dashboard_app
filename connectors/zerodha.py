import logging
from typing import Dict, List, Optional, Any
import pandas as pd
from datetime import datetime
import os
from .base import BrokerConnector

try:
    from kiteconnect import KiteConnect
except ImportError:
    KiteConnect = None

try:
    import yfinance as yf
except ImportError:
    yf = None

class ZerodhaConnector(BrokerConnector):
    def __init__(self, api_key: str, api_secret: str, access_token: Optional[str] = None, **kwargs):
        super().__init__(api_key, api_secret, access_token, **kwargs)
        self.name = "zerodha"
        self.kite = None
        
        if KiteConnect is None:
            logging.error("kiteconnect library not installed. Please install it using 'pip install kiteconnect'.")
            return

        self.kite = KiteConnect(api_key=self.api_key)

        if access_token:
            self.kite.set_access_token(access_token)
            self.access_token = access_token

    def get_login_url(self, redirect_uri: str, **kwargs) -> str:
        """Generate the login URL for Zerodha."""
        if not self.kite:
            return ""
        return self.kite.login_url()

    def generate_session(self, auth_code: str, **kwargs) -> Dict[str, Any]:
        """
        Exchange request_token (auth_code) for access_token.
        Zerodha uses 'request_token' as the auth code.
        """
        if not self.kite:
            raise Exception("KiteConnect not initialized")
        
        try:
            data = self.kite.generate_session(request_token=auth_code, api_secret=self.api_secret)
            self.access_token = data["access_token"]
            self.kite.set_access_token(self.access_token)
            
            # Return standardized token dict
            return {
                "access_token": self.access_token,
                "refresh_token": data.get("refresh_token", ""),
                "public_token": data.get("public_token"),
                "user_id": data.get("user_id"),
                "generated_at": datetime.now()
            }
        except Exception as e:
            logging.error(f"Error generating Zerodha session: {e}")
            raise

    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """
        Refresh access token using refresh token.
        Note: Zerodha access tokens are valid for one day. Standard Kite Connect 
        typically requires daily login.
        """
        if not self.kite:
            raise Exception("KiteConnect not initialized")
        raise NotImplementedError("Zerodha tokens typically require daily login. Please re-authenticate.")

    def get_holdings(self) -> List[Dict[str, Any]]:
        """Fetch holdings and normalize to standard format."""
        if not self.kite:
            return []
        
        try:
            holdings = self.kite.holdings()
            normalized_holdings = []
            for h in holdings:
                normalized_holdings.append({
                    "symbol": f"NSE:{h['tradingsymbol']}",
                    "quantity": h['quantity'],
                    "costPrice": h['average_price'],
                    "ltp": h['last_price'],
                    "pl": h['pnl'],
                })
            return normalized_holdings
        except Exception as e:
            logging.error(f"Error getting Zerodha holdings: {e}")
            return []

    def get_orders(self) -> List[Dict[str, Any]]:
        """Fetch orders and normalize."""
        if not self.kite:
            return []
        
        try:
            orders = self.kite.orders()
            normalized_orders = []
            for o in orders:
                status_map = {
                    "COMPLETE": 2,
                    "CANCELLED": 1,
                    "REJECTED": 5,
                    "OPEN": 6,
                    "AMO REQ RECEIVED": 6
                }
                
                normalized_orders.append({
                    "id": o['order_id'],
                    "symbol": f"NSE:{o['tradingsymbol']}",
                    "qty": o['quantity'],
                    "filled_qty": o['filled_quantity'],
                    "side": 1 if o['transaction_type'] == 'BUY' else -1,
                    "type": 1 if o['order_type'] == 'LIMIT' else 2,
                    "status": status_map.get(o['status'], 0),
                    "original_status": o['status'],
                    "order_time": o['order_timestamp']
                })
            return normalized_orders
        except Exception as e:
            logging.error(f"Error getting Zerodha orders: {e}")
            return []

    def place_order(self, symbol: str, qty: int, side: str, order_type: str, productType: str = "CNC", **kwargs) -> Dict[str, Any]:
        """
        Place an order.
        symbol: e.g. "NSE:INFY"
        side: "BUY" or "SELL"
        order_type: "MARKET" or "LIMIT"
        """
        if not self.kite:
            return {"s": "error", "message": "Kite not initialized"}

        try:
            # Parse symbol: "NSE:INFY-EQ" -> exchange="NSE", tradingsymbol="INFY"
            # Zerodha doesn't use -EQ suffix
            if ":" in symbol:
                exchange, tradingsymbol = symbol.split(":")
            else:
                exchange = "NSE"
                tradingsymbol = symbol
            
            if tradingsymbol.endswith("-EQ"):
                tradingsymbol = tradingsymbol.replace("-EQ", "")

            transaction_type = self.kite.TRANSACTION_TYPE_BUY if side.upper() == "BUY" else self.kite.TRANSACTION_TYPE_SELL
            
            if order_type.upper() == "MARKET":
                k_order_type = self.kite.ORDER_TYPE_MARKET
            elif order_type.upper() == "LIMIT":
                k_order_type = self.kite.ORDER_TYPE_LIMIT
            else:
                k_order_type = self.kite.ORDER_TYPE_MARKET

            if productType.upper() == "CNC":
                k_product = self.kite.PRODUCT_CNC
            elif productType.upper() == "INTRADAY" or productType.upper() == "MIS":
                k_product = self.kite.PRODUCT_MIS
            else:
                k_product = self.kite.PRODUCT_CNC

            order_id = self.kite.place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=exchange,
                tradingsymbol=tradingsymbol,
                transaction_type=transaction_type,
                quantity=qty,
                product=k_product,
                order_type=k_order_type,
                price=kwargs.get('price'),
                tag="nifty_shop"
            )
            
            return {
                "s": "ok",
                "id": order_id,
                "message": "Order placed successfully"
            }

        except Exception as e:
            logging.error(f"Error placing Zerodha order: {e}")
            return {"s": "error", "message": str(e)}

    def get_historical_data(self, symbol: str, resolution: str, from_date: str, to_date: str, **kwargs) -> Dict[str, Any]:
        """
        Get historical data.
        resolution: "D" (Fyers) -> "day" (Zerodha)
        """
        if not self.kite:
            return {"s": "error", "message": "Kite not initialized"}

        try:
            # Normalize symbol for Zerodha (strip -EQ)
            z_symbol = symbol.replace("-EQ", "")
            
            quote = self.kite.quote(z_symbol)
            if z_symbol not in quote:
                 return {"s": "error", "message": "Symbol not found"}
            
            instrument_token = quote[z_symbol]['instrument_token']

            res_map = {
                "D": "day",
                "1D": "day",
                "1": "minute",
                "5": "5minute",
                "15": "15minute",
                "30": "30minute",
                "60": "60minute"
            }
            interval = res_map.get(resolution, "day")

            records = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval=interval
            )
            
            candles = []
            for r in records:
                ts = int(r['date'].timestamp())
                candles.append([
                    ts,
                    r['open'],
                    r['high'],
                    r['low'],
                    r['close'],
                    r['volume']
                ])

            return {
                "s": "ok",
                "candles": candles
            }

        except Exception as e:
            logging.error(f"Error getting Zerodha historical data: {e}")
            return {"s": "error", "message": str(e)}

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """Get quote using yfinance (fallback for restricted Zerodha API)."""
        if not self.kite:
            return {}
        
        try:
            # Normalize symbol for Zerodha (strip -EQ)
            z_symbol = symbol.replace("-EQ", "")
            
            # Use yfinance for LTP
            # Convert to yfinance format: NSE:INFY -> INFY.NS
            if ":" in z_symbol:
                _, ticker = z_symbol.split(":")
            else:
                ticker = z_symbol
            
            yf_symbol = f"{ticker}.NS"
            
            lp = 0.0
            if yf:
                try:
                    ticker_obj = yf.Ticker(yf_symbol)
                    # Try fast_info first
                    lp = ticker_obj.fast_info.last_price
                    if not lp:
                        # Fallback to history
                        hist = ticker_obj.history(period="1d")
                        if not hist.empty:
                            lp = float(hist['Close'].iloc[-1])
                except Exception as e:
                    logging.error(f"Error fetching yfinance price for {yf_symbol}: {e}")

            if lp > 0:
                return {
                    "s": "ok",
                    "d": [{
                        "v": {
                            "lp": lp,
                            "volume": 0,
                            "open_price": 0,
                            "high_price": 0,
                            "low_price": 0,
                            "prev_close_price": 0
                        }
                    }]
                }
            
            # Fallback to Zerodha API (which might fail)
            # Try LTP first (lighter, less permissions needed)
            ltp_response = self.kite.ltp(z_symbol)
            
            if z_symbol in ltp_response:
                lp = ltp_response[z_symbol]['last_price']
                return {
                    "s": "ok",
                    "d": [{
                        "v": {
                            "lp": lp,
                            "volume": 0, # LTP doesn't give volume
                            "open_price": 0,
                            "high_price": 0,
                            "low_price": 0,
                            "prev_close_price": 0
                        }
                    }]
                }
            
            # Fallback to full quote if LTP fails or returns empty
            quote = self.kite.quote(z_symbol)
            if z_symbol in quote:
                lp = quote[z_symbol]['last_price']
                return {
                    "s": "ok",
                    "d": [{
                        "v": {
                            "lp": lp,
                            "volume": quote[z_symbol]['volume'],
                            "open_price": quote[z_symbol]['ohlc']['open'],
                            "high_price": quote[z_symbol]['ohlc']['high'],
                            "low_price": quote[z_symbol]['ohlc']['low'],
                            "prev_close_price": quote[z_symbol]['ohlc']['close']
                        }
                    }]
                }
            return {}
        except Exception as e:
            logging.error(f"Error getting Zerodha quote: {e}")
            return {}

    def get_funds(self) -> List[Dict[str, Any]]:
        """Get funds."""
        if not self.kite:
            return []
        
        try:
            margins = self.kite.margins()
            equity_balance = margins.get('equity', {}).get('available', {}).get('live_balance', 0.0)
            
            return [{
                "equityAmount": equity_balance
            }]
        except Exception as e:
            logging.error(f"Error getting Zerodha funds: {e}")
            return []

    def is_token_valid(self) -> bool:
        """Check if token is valid by making a lightweight call."""
        if not self.kite or not self.access_token:
            return False
        try:
            self.kite.profile()
            return True
        except Exception:
            return False

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an open order."""
        if not self.kite:
            return {"s": "error", "message": "Kite not initialized"}
        try:
            self.kite.cancel_order(variety=self.kite.VARIETY_REGULAR, order_id=order_id)
            return {"s": "ok", "message": "Order cancelled successfully"}
        except Exception as e:
            logging.error(f"Error cancelling Zerodha order: {e}")
            return {"s": "error", "message": str(e)}

    def modify_order(self, order_id: str, new_price: float = 0.0, new_qty: int = 0, **kwargs) -> Dict[str, Any]:
        """Modify an open order."""
        if not self.kite:
            return {"s": "error", "message": "Kite not initialized"}
        try:
            params = {"variety": self.kite.VARIETY_REGULAR, "order_id": order_id}
            if new_price > 0:
                params["price"] = new_price
            if new_qty > 0:
                params["quantity"] = new_qty
            self.kite.modify_order(**params)
            return {"s": "ok", "message": "Order modified successfully"}
        except Exception as e:
            logging.error(f"Error modifying Zerodha order: {e}")
            return {"s": "error", "message": str(e)}

    def get_orderbook(self, symbol: str) -> Dict[str, Any]:
        """Get market depth/orderbook."""
        if not self.kite:
            return {}
        try:
            depth = self.kite.quote(symbol)
            if symbol in depth:
                return {
                    "s": "ok",
                    "depth": depth[symbol].get('depth', {})
                }
            return {}
        except Exception as e:
            logging.error(f"Error getting Zerodha orderbook: {e}")
            return {}

    def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch current day/open positions."""
        if not self.kite:
            return []
        try:
            positions = self.kite.positions()
            net_positions = positions.get('net', [])
            normalized_positions = []
            for p in net_positions:
                if p['quantity'] != 0:
                    normalized_positions.append({
                        "symbol": f"NSE:{p['tradingsymbol']}",
                        "quantity": p['quantity'],
                        "costPrice": p['average_price'],
                        "ltp": p['last_price'],
                        "pl": p['pnl']
                    })
            return normalized_positions
        except Exception as e:
            logging.error(f"Error getting Zerodha positions: {e}")
            return []

    def get_profile(self) -> Dict[str, Any]:
        """Fetch user profile."""
        if not self.kite:
            return {}
        try:
            profile = self.kite.profile()
            return {
                "s": "ok",
                "data": profile
            }
        except Exception as e:
            logging.error(f"Error getting Zerodha profile: {e}")
            return {}

    def get_trades(self) -> List[Dict[str, Any]]:
        """Fetch trade history for the day."""
        if not self.kite:
            return []
        try:
            trades = self.kite.trades()
            normalized_trades = []
            for t in trades:
                normalized_trades.append({
                    "trade_id": t['trade_id'],
                    "order_id": t['order_id'],
                    "symbol": f"NSE:{t['tradingsymbol']}",
                    "qty": t['quantity'],
                    "price": t['average_price'],
                    "side": "BUY" if t['transaction_type'] == 'BUY' else "SELL",
                    "trade_time": t['fill_timestamp']
                })
            return normalized_trades
        except Exception as e:
            logging.error(f"Error getting Zerodha trades: {e}")
            return []

    def get_funds(self) -> List[Dict[str, Any]]:
        """Fetch account balance and limits."""
        if not self.kite:
            return []
        try:
            margins = self.kite.margins()
            # Zerodha returns {'equity': {...}, 'commodity': {...}}
            equity_margins = margins.get('equity', {})
            
            # Normalize to match Fyers format (list of dicts) or just return what strategy expects
            # Strategy expects list of dicts with 'equityAmount'
            return [{
                "equityAmount": equity_margins.get('net', 0.0),
                "availableBalance": equity_margins.get('available', {}).get('cash', 0.0)
            }]
        except Exception as e:
            logging.error(f"Error getting Zerodha funds: {e}")
            return []
