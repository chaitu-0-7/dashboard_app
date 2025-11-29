import pandas as pd
import numpy as np
import math
from datetime import datetime, timedelta
import logging
import pytz
import time

# Define timezones
UTC = pytz.utc
IST = pytz.timezone('Asia/Kolkata')
from fyers_apiv3 import fyersModel
from typing import Dict, List
import os
from pymongo import MongoClient
from bson.objectid import ObjectId
from dotenv import load_dotenv
from config import MONGO_DB_NAME, MONGO_ENV, MAX_TRADE_VALUE, MA_PERIOD

# --- Database Handler ---
class DatabaseHandler:
    def __init__(self, uri: str, db_name: str = 'nifty_shop', env: str = 'test'):
        self.client = MongoClient(uri)
        self.db = self.client[db_name]
        self.env = env

    def get_trades_collection(self):
        return self.db[f'trades_{self.env}']

    def get_logs_collection(self):
        return self.db[f'logs_{self.env}']

# --- Mongo Log Handler ---
class MongoLogHandler(logging.Handler):
    def __init__(self, db_handler: DatabaseHandler, run_id: str = None):
        super().__init__()
        self.logs_collection = db_handler.get_logs_collection()
        self.run_id = run_id

    def emit(self, record):
        log_entry = {
            'timestamp': datetime.now(UTC),
            'level': record.levelname,
            'message': self.format(record)
        }
        if self.run_id:
            log_entry['run_id'] = self.run_id
        self.logs_collection.insert_one(log_entry)

# --- Rate Limit Handler (No Change) ---
class RateLimitHandler:
    """Handle API rate limits"""
    
    def __init__(self, max_retries=3, base_delay=1.0, max_delay=60.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.last_request_time = 0
        
    def wait_if_needed(self):
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < 0.1:
            time.sleep(0.1 - time_since_last)
            
        self.last_request_time = time.time()
        
    def retry_with_backoff(self, func, *args, **kwargs):
        for attempt in range(self.max_retries):
            try:
                self.wait_if_needed()
                result = func(*args, **kwargs)
                
                if isinstance(result, dict) and result.get('s') == 'error':
                    error_code = result.get('code', 0)
                    if error_code in [429, 10006, 10007]:
                        delay = min(self.base_delay * (2 ** attempt), self.max_delay)
                        time.sleep(delay)
                        continue
                        
                return result
                
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise
                
                delay = min(self.base_delay * (2 ** attempt), self.max_delay)
                time.sleep(delay)
                
        return None

class SimpleNiftyTrader:
    """Simplified NIFTY 50 mean reversion trader"""
    
    def __init__(self, client_id: str, access_token: str, db_handler: DatabaseHandler, max_trade_value: float, ma_period: int = 20, exit_threshold: int = 5):
        self.client_id = client_id
        self.access_token = access_token
        self.db_handler = db_handler
        self.fyers = fyersModel.FyersModel(
            client_id=client_id,
            token=access_token,
            log_path="./"
        )
        
        self.rate_limiter = RateLimitHandler()
        
        # Strategy parameters
        self.ma_period = ma_period
        self.entry_threshold = -5.0
        self.exit_threshold = exit_threshold
        self.averaging_threshold = -3.0
        self.max_stocks_to_buy = 2
        self.max_stocks_to_scan = 5
        
        self.max_trade_value = max_trade_value
        
        # Load trades history from DB
        self.trades = self.load_trades()
        
        # NIFTY 50 symbols
        self.nifty50_symbols = [
            "NSE:RELIANCE-EQ", "NSE:TCS-EQ", "NSE:HDFCBANK-EQ", "NSE:INFY-EQ",
            "NSE:HINDUNILVR-EQ", "NSE:ICICIBANK-EQ", "NSE:KOTAKBANK-EQ", 
            "NSE:SBIN-EQ", "NSE:BHARTIARTL-EQ", "NSE:BAJFINANCE-EQ",
            "NSE:ASIANPAINT-EQ", "NSE:MARUTI-EQ", "NSE:AXISBANK-EQ",
            "NSE:LT-EQ", "NSE:TITAN-EQ", "NSE:ULTRACEMCO-EQ",
            "NSE:SUNPHARMA-EQ", "NSE:NESTLEIND-EQ", "NSE:POWERGRID-EQ",
            "NSE:NTPC-EQ", "NSE:BAJAJFINSV-EQ", "NSE:HCLTECH-EQ",
            "NSE:WIPRO-EQ", "NSE:DIVISLAB-EQ", "NSE:TECHM-EQ",
            "NSE:CIPLA-EQ", "NSE:COALINDIA-EQ", "NSE:DRREDDY-EQ",
            "NSE:EICHERMOT-EQ", "NSE:JSWSTEEL-EQ", "NSE:BRITANNIA-EQ",
            "NSE:GRASIM-EQ", "NSE:TATAMOTORS-EQ", "NSE:INDUSINDBK-EQ",
            "NSE:TATASTEEL-EQ", "NSE:APOLLOHOSP-EQ", "NSE:BAJAJ-AUTO-EQ",
            "NSE:HEROMOTOCO-EQ", "NSE:ONGC-EQ", "NSE:BPCL-EQ",
            "NSE:SBILIFE-EQ", "NSE:HDFCLIFE-EQ", "NSE:ADANIPORTS-EQ",
            "NSE:TATACONSUM-EQ", "NSE:UPL-EQ", "NSE:HINDALCO-EQ",
            "NSE:SHREECEM-EQ", "NSE:ADANIENT-EQ", "NSE:LTIM-EQ",
            "NSE:TRENT-EQ"
        ]
    
    def load_trades(self) -> List:
        """Load only FILLED trades from database"""
        try:
            trades_collection = self.db_handler.get_trades_collection()
            return list(trades_collection.find({'filled': True}))
        except Exception as e:
            logging.error(f"Error loading trades from DB: {e}")
            return []
    
    def save_trade(self, trade_data: Dict) -> any:
        """Save a single trade to the database and return its document ID."""
        try:
            trades_collection = self.db_handler.get_trades_collection()
            trade_data['created_at'] = datetime.now(UTC)
            if 'filled' not in trade_data:
                trade_data['filled'] = False  # Default to not filled
            if 'status' not in trade_data:
                trade_data['status'] = 'OPEN' # Default status
            result = trades_collection.insert_one(trade_data)
            return result.inserted_id
        except Exception as e:
            logging.error(f"Error saving trade to DB: {e}")
            return None

    def get_order_status(self, order_id: str) -> Dict:
        """Get the status of a specific order."""
        def _get_orders():
            data = {"id": order_id}
            return self.fyers.orderbook(data)

        try:
            response = self.rate_limiter.retry_with_backoff(_get_orders)
            if response and response.get('s') == 'ok' and response.get('orderBook'):
                return response['orderBook'][0]
        except Exception as e:
            logging.error(f"Error getting order status for {order_id}: {e}")
        return {}

    def verify_and_update_order(self, trade_doc_id, order_id: str) -> bool:
        """Verify if an order is filled and update the database."""
        trades_collection = self.db_handler.get_trades_collection()
        for i in range(3):  # Retry 3 times
            try:
                order_details = self.get_order_status(order_id)
                # Status 2 indicates a fully traded/filled order in Fyers API
                if order_details and order_details.get('status') == 2:
                    trades_collection.update_one(
                        {'_id': trade_doc_id},
                        {'$set': {'filled': True}}
                    )
                    logging.info(f"✅ Order {order_id} confirmed as FILLED.")
                    return True
                else:
                    status = order_details.get('status', 'UNKNOWN')
                    logging.warning(f"Order {order_id} not filled yet. Status: {status}. Retrying... ({i+1}/3)")
                    time.sleep(5)  # Wait 5 seconds before retrying

            except Exception as e:
                logging.error(f"Exception while verifying order {order_id}: {e}")
                time.sleep(5)

        logging.error(f"❌ Order {order_id} could not be confirmed as filled after 3 attempts.")
        trades_collection.update_one(
            {'_id': trade_doc_id},
            {'$set': {'comment': 'FAILED TO CONFIRM FILL'}}
        )
        return False

    def get_order_book(self) -> List:
        """Get order book from Fyers API."""
        def _get_orders():
            return self.fyers.orderbook()

        try:
            response = self.rate_limiter.retry_with_backoff(_get_orders)
            if response and response.get('s') == 'ok':
                return response.get('orderBook', [])
            else:
                logging.error(f"Failed to get orderbook, API response: {response}")
                return []
        except Exception as e:
            logging.error(f"Error getting orderbook: {e}")
            return []

    def get_current_positions(self):
        """Get current holdings from Fyers API. Returns a tuple: (positions, is_successful)"""
        def _get_holdings():
            return self.fyers.holdings()
        
        try:
            response = self.rate_limiter.retry_with_backoff(_get_holdings)
            

            if response and response.get('s') == 'ok':
                print(f"[DEBUG] Fyers Holdings API Response: {response}")
                positions = {}
                
                # The .holdings() API returns a list under the 'holdings' key
                for pos in response.get('holdings', []):
                    symbol = pos['symbol']
                    qty = int(pos['quantity'])
                    if qty > 0:
                        positions[symbol] = {
                            'quantity': qty,
                            'avg_price': float(pos['costPrice']),
                            'current_price': float(pos.get('ltp', 0.0)), # Use LTP from holdings
                            'pnl': float(pos.get('pl', 0.0)),
                            'pnl_pct': 0.0 # Will be calculated later based on updated current_price
                        }
                            
                return positions, True # Success
            else:
                logging.error(f"Failed to get holdings, API response: {response}")
                return {}, False # Failure

        except Exception as e:
            logging.error(f"Error getting holdings: {e}")
            return {}, False # Failure

    def get_historical_data(self, symbol: str, days: int = 25) -> pd.DataFrame:
        """Get historical data for MA calculation"""
        def _fetch_data():
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            data = {
                "symbol": symbol,
                "resolution": "D",
                "date_format": "1",
                "range_from": start_date.strftime("%Y-%m-%d"),
                "range_to": end_date.strftime("%Y-%m-%d"),
                "cont_flag": "1"
            }
            return self.fyers.history(data)
        
        try:
            response = self.rate_limiter.retry_with_backoff(_fetch_data)
            
            if response and response.get('s') == 'ok':
                df = pd.DataFrame(response['candles'],
                                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['date'] = pd.to_datetime(df['timestamp'], unit='s')
                df = df.sort_values('date').reset_index(drop=True)
                return df
        except Exception as e:
            logging.error(f"Error getting historical data for {symbol}: {e}")
            return pd.DataFrame()
        
        return pd.DataFrame()

    def calculate_moving_average(self, prices: pd.Series) -> float:
        """Calculate moving average"""
        if len(prices) >= self.ma_period:
            return prices.tail(self.ma_period).mean()
        return None

    def place_buy_order(self, symbol: str, quantity: int) -> Dict:
        """Place buy order"""
        if self.db_handler.env == 'test':
            logging.info(f"TEST MODE: Buy order for {quantity} {symbol} would be placed here.")
            return {"s": "error", "message": "REJECTED_IN_TEST_ENV"}

        def _place_order():
            data = {
            "symbol": symbol,
            "qty": quantity,
            "type": 2,
            "side": 1,
            "productType": "CNC",
            "limitPrice": 0,
            "stopPrice": 0,
            "validity": "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
            "orderTag": "niftyShop"
            }
            return self.fyers.place_order(data)
        
        try:
            response = self.rate_limiter.retry_with_backoff(_place_order)
            return response
        except Exception as e:
            logging.error(f"Error placing buy order for {symbol}: {e}")
            return {"s": "error", "message": str(e)}

    def place_sell_order(self, symbol: str, quantity: int) -> Dict:
        """Place sell order"""
        if self.db_handler.env == 'test':
            logging.info(f"TEST MODE: Sell order for {quantity} {symbol} would be placed here.")
            return {"s": "error", "message": "REJECTED_IN_TEST_ENV"}
            
        def _place_order():
            data = {
                "symbol": symbol,
                "qty": quantity,
                "type": 2,
                "side": -1,
                "productType": "CNC",
                "limitPrice": 0,
                "stopPrice": 0,
                "validity": "DAY",
                "disclosedQty": 0,
                "offlineOrder": False,
                "orderTag": "niftyShop"
            }
            return self.fyers.place_order(data)
        
        try:
            response = self.rate_limiter.retry_with_backoff(_place_order)
            return response
        except Exception as e:
            logging.error(f"Error placing sell order for {symbol}: {e}")
            return {"s": "error", "message": str(e)}

    def get_account_balance(self) -> float:
        """Get available balance"""
        def _get_funds():
            return self.fyers.funds()
        
        try:
            response = self.rate_limiter.retry_with_backoff(_get_funds)
            if response and response.get('s') == 'ok':
                return float(response['fund_limit'][0]['equityAmount'])
        except Exception as e:
            logging.error(f"Error getting account balance: {e}")
            return 0.0
        return 0.0

    def scan_for_opportunities(self) -> List[Dict]:
        """Scan for entry opportunities"""
        candidates = []
        
        for symbol in self.nifty50_symbols:
            try:
                df = self.get_historical_data(symbol, days=self.ma_period + 15)
                if df.empty: continue
                
                ma = self.calculate_moving_average(df['close'])
                if ma is None: continue
                
                current_price = self.get_current_price(symbol) # This is the correct call for scanning
                if current_price <= 0: continue
                
                if current_price >= ma: continue
                
                deviation = ((current_price - ma) / ma) * 100
                
                candidates.append({
                    'symbol': symbol,
                    'price': current_price,
                    'ma': ma,
                    'deviation': deviation
                })
                
            except Exception as e:
                logging.warning(f"Could not scan {symbol}: {e}")
                continue
        
        candidates.sort(key=lambda x: x['deviation'])
        return candidates[:self.max_stocks_to_scan]

    def check_exit_conditions(self, positions: Dict) -> List[Dict]:
        """Check for exit conditions"""
        exit_candidates = []
        
        for symbol, position in positions.items():
            try:
                current_price = position['current_price']
                if current_price <= 0: continue
                
                profit_pct = ((current_price - position['avg_price']) / position['avg_price']) * 100
                
                if profit_pct >= self.exit_threshold:
                    exit_candidates.append({
                        'symbol': symbol,
                        'current_price': current_price,
                        'quantity': position['quantity'],
                        'avg_buy_price': position['avg_price'],
                        'profit_pct': profit_pct
                    })
                    
            except Exception as e:
                logging.warning(f"Could not check exit for {symbol}: {e}")
                continue
        
        exit_candidates.sort(key=lambda x: x['profit_pct'], reverse=True)
        return exit_candidates

    def execute_buy(self, symbol: str, current_price: float, is_averaging: bool = False) -> bool:
        """Execute buy trade and verify fill."""
        try:
            quantity = 1 if is_averaging else math.floor(self.max_trade_value / current_price)
            if quantity <= 0: return False

            available_balance = self.get_account_balance()
            required_amount = current_price * quantity

            if required_amount > available_balance:
                logging.info(f"Insufficient balance to buy {symbol}")
                return False

            order_response = self.place_buy_order(symbol, quantity)

            if order_response.get('s') == 'ok' and order_response.get('id'):
                order_id = order_response['id']
                trade_data = {
                    'symbol': symbol,
                    'action': 'BUY',
                    'price': current_price,
                    'quantity': quantity,
                    'date': datetime.now(UTC),
                    'order_id': order_id,
                    'is_averaging': is_averaging,
                    'comment': 'PENDING FILL'
                }
                trade_doc_id = self.save_trade(trade_data)

                if trade_doc_id and self.verify_and_update_order(trade_doc_id, order_id):
                    comment = 'AVERAGING' if is_averaging else 'NEW ENTRY'
                    self.db_handler.get_trades_collection().update_one(
                        {'_id': trade_doc_id},
                        {'$set': {'comment': comment}}
                    )
                    self.trades = self.load_trades()
                    logging.info(f"✅ BUY executed and filled for {quantity} {symbol} at ₹{current_price:.2f}")
                    return True
                else:
                    logging.error(f"BUY order for {symbol} was placed but not confirmed as filled.")
                    return False
            else:
                logging.error(f"Failed to place buy order for {symbol}: {order_response}")
                return False

        except Exception as e:
            logging.error(f"Exception in execute_buy for {symbol}: {e}")
            return False

    def execute_sell(self, symbol: str, current_price: float, quantity: int, avg_price: float) -> bool:
        """Execute sell trade and verify fill."""
        try:
            order_response = self.place_sell_order(symbol, quantity)

            if order_response.get('s') == 'ok' and order_response.get('id'):
                order_id = order_response['id']
                profit = (current_price - avg_price) * quantity
                profit_pct = ((current_price - avg_price) / avg_price) * 100

                trade_data = {
                    'symbol': symbol,
                    'action': 'SELL',
                    'price': current_price,
                    'quantity': quantity,
                    'date': datetime.now(UTC),
                    'order_id': order_id,
                    'profit': profit,
                    'profit_pct': profit_pct,
                    'comment': 'PENDING FILL'
                }
                trade_doc_id = self.save_trade(trade_data)

                if trade_doc_id and self.verify_and_update_order(trade_doc_id, order_id):
                    comment = f'PROFIT EXIT: {profit_pct:.1f}%'
                    self.db_handler.get_trades_collection().update_one(
                        {'_id': trade_doc_id},
                        {'$set': {'comment': comment}}
                    )
                    self.trades = self.load_trades()
                    logging.info(f"💰 SOLD and filled: {quantity} {symbol} at ₹{current_price:.2f}, Profit: ₹{profit:.2f}")
                    return True
                else:
                    logging.error(f"SELL order for {symbol} was placed but not confirmed as filled.")
                    return False
            else:
                logging.error(f"Failed to place sell order for {symbol}: {order_response}")
                return False

        except Exception as e:
            logging.error(f"Exception in execute_sell for {symbol}: {e}")
            return False

    def check_for_closed_positions(self, current_positions: Dict, positions_fetch_success: bool):
        """Check for manually closed positions and create a placeholder sell trade for manual update."""
        if not positions_fetch_success:
            logging.warning("Skipping check for closed positions because fetching positions failed.")
            return

        try:
            # Get all filled buy trades that don't have a corresponding sell trade yet.
            # This is a simplified view of open positions from our DB's perspective.
            pipeline = [
                {'$match': {'filled': True}},
                {'$group': {
                    '_id': '$symbol',
                    'total_bought': {'$sum': {'$cond': [{'$eq': ['$action', 'BUY']}, '$quantity', 0]}},
                    'total_sold': {'$sum': {'$cond': [{'$eq': ['$action', 'SELL']}, '$quantity', 0]}},
                    'buy_trades': {'$push': {'$cond': [{'$eq': ['$action', 'BUY']}, '$ROOT', None]}}
                }},
                {'$project': {
                    'symbol': '$_id',
                    'balance': {'$subtract': ['$total_bought', '$total_sold']},
                    'buy_trades': {
                        '$filter': {
                            'input': '$buy_trades',
                            'as': 'trade',
                            'cond': {'$ne': ['$trade', None]}
                        }
                    }
                }},
                {'$match': {'balance': {'$gt': 0}}}
            ]
            open_positions_db = list(self.db_handler.get_trades_collection().aggregate(pipeline))

            for pos in open_positions_db:
                symbol = pos['symbol']
                if symbol not in current_positions:
                    # Position is closed on Fyers, but we think it's open.
                    # Create a placeholder SELL trade.
                    
                    # Check if a placeholder already exists
                    if self.db_handler.get_trades_collection().find_one({'symbol': symbol, 'status': 'PENDING_MANUAL_PRICE'}):
                        continue

                    remaining_qty = pos['balance']
                    buy_trades = pos['buy_trades']
                    
                    # Safety check: filter out None values that might slip through the aggregation
                    buy_trades = [t for t in buy_trades if t is not None]
                    
                    if not buy_trades:
                        logging.warning(f"No valid buy trades found for {symbol}, skipping placeholder creation.")
                        continue
                    
                    total_bought_qty = sum(t['quantity'] for t in buy_trades)
                    avg_buy_price = sum(t['price'] * t['quantity'] for t in buy_trades) / total_bought_qty

                    trade_data = {
                        'symbol': symbol,
                        'action': 'SELL',
                        'price': 0, # To be updated by user
                        'quantity': remaining_qty,
                        'date': datetime.now(UTC), # To be updated by user
                        'order_id': 'MANUAL',
                        'profit': 0, # Will be recalculated on update
                        'comment': 'Manually closed position. Please update price and date.',
                        'status': 'PENDING_MANUAL_PRICE',
                        'filled': True 
                    }
                    
                    trade_doc_id = self.save_trade(trade_data)
                    if trade_doc_id:
                        logging.info(f"📝 Created placeholder SELL for manually closed position {symbol}.")
                        self.trades = self.load_trades()

        except Exception as e:
            logging.error(f"Error checking for closed positions: {e}", exc_info=True)

    def get_current_price(self, symbol: str) -> float:
        """Get current market price for a given symbol using Fyers quotes API."""
        def _get_quote():
            data = {"symbols": symbol}
            return self.fyers.quotes(data)
        
        try:
            response = self.rate_limiter.retry_with_backoff(_get_quote)
            if response and response.get('s') == 'ok' and 'd' in response and len(response['d']) > 0:
                return float(response['d'][0]['v']['lp'])
        except Exception as e:
            logging.error(f"Error getting current price for {symbol}: {e}")
        return 0.0

    def try_averaging_down(self, positions: Dict):
        """Try averaging down on worst performer"""
        if not positions:
            return

        worst_performer = None
        worst_performance = float('inf')

        for symbol, position in positions.items():
            try:
                current_price = position['current_price']
                if current_price <= 0:
                    continue

                performance = ((current_price - position['avg_price']) / position['avg_price']) * 100

                if performance <= self.averaging_threshold and performance < worst_performance:
                    worst_performance = performance
                    worst_performer = {
                        'symbol': symbol,
                        'price': current_price,
                        'performance': performance
                    }
            except Exception as e:
                logging.warning(f"Could not check averaging for {symbol}: {e}")
                continue

        if worst_performer:
            logging.info(f"🔄 AVERAGING DOWN: {worst_performer['symbol']} at {worst_performer['performance']:.1f}% loss")
            self.execute_buy(worst_performer['symbol'], worst_performer['price'], is_averaging=True)

    def run_daily_strategy(self):
        """Main daily strategy execution"""
        logging.info("🚀 Starting daily strategy...")
        
        try:
            # self.trades is now only filled trades
            current_positions, positions_fetch_success = self.get_current_positions()
            self.check_for_closed_positions(current_positions, positions_fetch_success)
            
            # Get fresh positions after checking for manual closes
            current_positions, positions_fetch_success = self.get_current_positions()

            if not positions_fetch_success:
                logging.error("Could not fetch current positions. Aborting strategy for this run.")
                return

            for symbol, position in current_positions.items():
                # current_price is already populated from holdings API in get_current_positions
                # Recalculate P&L based on the current_price from holdings
                position['pnl'] = (position['current_price'] - position['avg_price']) * position['quantity']
                position['pnl_pct'] = ((position['current_price'] - position['avg_price']) / position['avg_price']) * 100 if position['avg_price'] > 0 else 0
            
            exit_candidates = self.check_exit_conditions(current_positions)
            
            if exit_candidates:
                best_exit = exit_candidates[0]
                logging.info(f"🎯 EXIT OPPORTUNITY: {best_exit['symbol']} with {best_exit['profit_pct']:.1f}% profit")
                
                if self.execute_sell(
                    best_exit['symbol'],
                    best_exit['current_price'],
                    best_exit['quantity'],
                    best_exit['avg_buy_price']
                ):
                    # Position will be removed on the next run when get_current_positions is called
                    pass
            
            # Get fresh positions again before making buy decisions
            current_positions, positions_fetch_success = self.get_current_positions()
            if not positions_fetch_success:
                logging.warning("Could not refresh positions before buying. Proceeding with potentially stale data.")

            entry_candidates = self.scan_for_opportunities()
            new_candidates = [c for c in entry_candidates if c['symbol'] not in current_positions]
            for candidate in new_candidates:
                logging.info(f"Eligible candidate: {candidate['symbol']} (Deviation: {candidate['deviation']:.2f}%) - Price: ₹{candidate['price']:.2f}, MA: ₹{candidate['ma']:.2f})")
            
            best_entry = None
            available_balance = self.get_account_balance()
            
            for candidate in new_candidates:
                quantity = math.floor(self.max_trade_value / candidate['price'])
                required_amount = candidate['price'] * quantity
                
                if required_amount <= available_balance and quantity > 0:
                    best_entry = candidate
                    break
            
            if best_entry:
                logging.info(f"🎯 ENTRY OPPORTUNITY: {best_entry['symbol']} at {best_entry['deviation']:.1f}% below MA")
                self.execute_buy(best_entry['symbol'], best_entry['price'])
            else:
                if not best_entry and current_positions:
                    self.try_averaging_down(current_positions)
            
            self.print_current_status(current_positions)
            
        except Exception as e:
            logging.error(f"❌ Error in strategy execution: {e}")
        
        logging.info("✅ Daily strategy completed")

    def print_current_status(self, positions: Dict):
        """Print current portfolio status"""
        print("\n" + "="*60)
        print("📊 CURRENT PORTFOLIO STATUS")
        print("="*60)
        
        if positions:
            total_investment = 0
            total_current_value = 0
            
            for symbol, position in positions.items():
                investment = position['avg_price'] * position['quantity']
                current_value = position['current_price'] * position['quantity']
                
                total_investment += investment
                total_current_value += current_value
                
                print(f"{symbol}: {position['quantity']} @ ₹{position['avg_price']:.2f} "
                      f"(Current: ₹{position['current_price']:.2f}, "
                      f"P&L: ₹{position['pnl']:.2f} ({position['pnl_pct']:+.1f}%))")
            
            total_pnl = total_current_value - total_investment
            total_pnl_pct = (total_pnl / total_investment * 100) if total_investment > 0 else 0
            
            print(f"\n💰 Total Investment: ₹{total_investment:,.2f}")
            print(f"💰 Current Value: ₹{total_current_value:,.2f}")
            print(f"💰 Total P&L: ₹{total_pnl:,.2f} ({total_pnl_pct:+.1f}%)")
        else:
            print("📝 No current holdings")
        
        print(f"\n📈 RECENT TRADES (Last 5 Filled):")
        recent_trades = self.trades[-5:]
        for trade in recent_trades:
            trade_date = trade['date'].strftime('%Y-%m-%d %H:%M')
            action = trade['action']
            symbol = trade['symbol']
            price = trade['price']
            qty = trade['quantity']
            comment = trade.get('comment', '')
            
            if action == 'SELL' and 'profit' in trade:
                profit = trade['profit']
                print(f"  {trade_date} | {action} {qty} {symbol} @ ₹{price:.2f} | Profit: ₹{profit:.2f} | {comment}")
            else:
                print(f"  {trade_date} | {action} {qty} {symbol} @ ₹{price:.2f} | {comment}")
        
        balance = self.get_account_balance()
        print(f"\n💳 Available Balance: ₹{balance:,.2f}")

def main():
    """Main function for daily execution"""
    import argparse

    parser = argparse.ArgumentParser(description="Run the Nifty Shop trading strategy.")
    parser.add_argument("--run-id", type=str, help="Unique ID for this strategy run.", default=None)
    args = parser.parse_args()

    run_id = args.run_id

    # --- Configuration ---
    load_dotenv()

    CLIENT_ID = os.getenv('FYERS_CLIENT_ID')
    
    # MongoDB connection for Fyers tokens
    mongo_client_fyers = MongoClient(os.getenv('MONGO_URI'))
    fyers_tokens_collection = mongo_client_fyers[MONGO_DB_NAME]['fyers_tokens']

    token_data = fyers_tokens_collection.find_one({"_id": "fyers_token_data"})
    ACCESS_TOKEN = token_data.get("access_token") if token_data else ""
    MONGO_URI = os.getenv('MONGO_URI')
    MAX_TRADE_VALUE_CONFIG = MAX_TRADE_VALUE
    MA_PERIOD_CONFIG = MA_PERIOD
    DB_NAME = MONGO_DB_NAME
    ENV = MONGO_ENV # or 'prod'

    if not all([CLIENT_ID, ACCESS_TOKEN, MONGO_URI]) or fyers_tokens_collection is None:
        print("❌ Please update configuration values.")
        return

    # --- Setup Database and Logging ---
    db_handler = DatabaseHandler(MONGO_URI, DB_NAME, ENV)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        handlers=[
            MongoLogHandler(db_handler, run_id=run_id),
            logging.StreamHandler()
        ]
    )
    
    try:
        trader = SimpleNiftyTrader(
            client_id=CLIENT_ID,
            access_token=ACCESS_TOKEN,
            db_handler=db_handler,
            max_trade_value=MAX_TRADE_VALUE_CONFIG,
            ma_period=MA_PERIOD_CONFIG
        )
        trader.run_daily_strategy()
        
    except Exception as e:
        logging.error(f"❌ Error in main execution: {e}")

if __name__ == "__main__":
    main()
