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

from typing import Dict, List, Optional
import os
from pymongo import MongoClient
from bson.objectid import ObjectId
from dotenv import load_dotenv
from config import MONGO_DB_NAME, MONGO_ENV, MAX_TRADE_VALUE, MA_PERIOD

# Import Generic Connector
from connectors.base import BrokerConnector
from connectors.fyers import FyersConnector
from connectors.data_source import DataSource, YFinanceDataSource

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
                
                # Check for common error structures (this might need adaptation per broker)
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
    
    def __init__(self, broker: BrokerConnector, data_source: DataSource, db_handler: DatabaseHandler, settings: Dict):
        self.broker = broker
        self.data_source = data_source
        self.db_handler = db_handler
        self.settings = settings
        
        self.rate_limiter = RateLimitHandler()
        
        # Strategy parameters from Settings
        self.ma_period = int(settings.get('ma_period', 20))
        self.entry_threshold = float(settings.get('entry_threshold', -2.0))
        self.exit_threshold = float(settings.get('target_profit', 5.0))
        self.averaging_threshold = float(settings.get('averaging_threshold', -3.0))
        
        self.max_stocks_to_buy = 2 # Still hardcoded or could be added to settings
        self.max_stocks_to_scan = 5
        
        self.max_trade_value = float(settings.get('trade_amount', 2000))
        self.max_open_positions = int(settings.get('max_positions', 10))
        
        # Trading mode (NORMAL, EXIT_ONLY, PAUSED)
        self.trading_mode = settings.get('trading_mode', 'NORMAL')
        
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
            "NSE:GRASIM-EQ", "NSE:INDUSINDBK-EQ",
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
            # The generic interface might need adjustment if get_orderbook doesn't filter by ID
            # But FyersConnector.get_orderbook(symbol) returns all orders if symbol is None?
            # Let's assume we fetch all orders and filter in memory for now, or use broker specific method if exposed
            # Ideally, BrokerConnector should have get_order(order_id)
            # For now, we use get_orders() and filter.
            all_orders = self.broker.get_orders()
            for order in all_orders:
                if order.get('id') == order_id:
                    return order
            return {}

        try:
            response = self.rate_limiter.retry_with_backoff(_get_orders)
            return response
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
                # We need to standardize this status check in the Connector eventually
                # For now, assuming FyersConnector returns raw Fyers response which uses 'status': 2
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
        """Get order book from Broker."""
        def _get_orders():
            return self.broker.get_orders()

        try:
            response = self.rate_limiter.retry_with_backoff(_get_orders)
            return response
        except Exception as e:
            logging.error(f"Error getting orderbook: {e}")
            return []

    def get_current_positions(self):
        """Get current holdings from Broker. Returns a tuple: (positions, is_successful)"""
        def _get_holdings():
            return self.broker.get_holdings()
        
        try:
            holdings_list = self.rate_limiter.retry_with_backoff(_get_holdings)
            
            # BrokerConnector.get_holdings returns a List[Dict]
            # We need to convert it to the dict format expected by the strategy
            # Expected format: {symbol: {quantity, avg_price, current_price, pnl, pnl_pct}}
            
            if holdings_list is not None:
                # print(f"[DEBUG] Holdings API Response: {holdings_list}")
                positions = {}
                
                for pos in holdings_list:
                    # FyersConnector returns raw Fyers holdings objects
                    symbol = pos.get('symbol')
                    qty = int(pos.get('quantity', 0))
                    if qty > 0:
                        positions[symbol] = {
                            'quantity': qty,
                            'avg_price': float(pos.get('costPrice', 0.0)),
                            'current_price': float(pos.get('ltp', 0.0)),
                            'pnl': float(pos.get('pl', 0.0)),
                            'pnl_pct': 0.0 # Will be calculated later
                        }
                            
                return positions, True # Success
            else:
                logging.error(f"Failed to get holdings.")
                return {}, False # Failure

        except Exception as e:
            logging.error(f"Error getting holdings: {e}")
            return {}, False # Failure

    def get_historical_data(self, symbol: str, days: int = 25) -> pd.DataFrame:
        """Get historical data for MA calculation"""
        def _fetch_data():
            # Use data source for historical data
            return self.data_source.get_historical_data(
                symbol=symbol,
                period=f"{days}d",
                interval="1d"
            )
        
        try:
            response = self.rate_limiter.retry_with_backoff(_fetch_data)
            
            # FyersConnector returns raw Fyers response dict
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
            return self.broker.place_order(
                symbol=symbol,
                qty=quantity,
                side="BUY",
                order_type="MARKET",
                productType="CNC" # This might need to be configurable
            )
        
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
            return self.broker.place_order(
                symbol=symbol,
                qty=quantity,
                side="SELL",
                order_type="MARKET",
                productType="CNC"
            )
        
        try:
            response = self.rate_limiter.retry_with_backoff(_place_order)
            return response
        except Exception as e:
            logging.error(f"Error placing sell order for {symbol}: {e}")
            return {"s": "error", "message": str(e)}

    def get_account_balance(self) -> float:
        """Get available balance"""
        def _get_funds():
            return self.broker.get_funds()
        
        try:
            # FyersConnector returns fund_limit list
            funds_list = self.rate_limiter.retry_with_backoff(_get_funds)
            if funds_list and len(funds_list) > 0:
                return float(funds_list[0].get('equityAmount', 0.0))
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
                if self.db_handler.env == 'dev':
                    logging.info(f"⚠️ DEV MODE: Bypassing insufficient balance check for {symbol}")
                else:
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
        """Get current market price for a given symbol using Broker quotes API with fallback."""
        price = 0.0
        
        # 1. Try Broker (Real-time)
        def _get_quote():
            return self.broker.get_quote(symbol)
        
        try:
            response = self.rate_limiter.retry_with_backoff(_get_quote)
            # FyersConnector/ZerodhaConnector returns standardized response
            if response and response.get('s') == 'ok' and 'd' in response and len(response['d']) > 0:
                price = float(response['d'][0]['v']['lp'])
        except Exception as e:
            logging.error(f"Error getting current price from broker for {symbol}: {e}")
            
        # 2. Fallback to Data Source (yfinance) if broker failed
        if price <= 0:
            # logging.info(f"⚠️ Falling back to data source for {symbol} price")
            try:
                price = self.data_source.get_latest_price(symbol)
            except Exception as e:
                logging.error(f"Error getting fallback price for {symbol}: {e}")
                
        return price

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
        
        # Check trading mode
        mode_messages = {
            'NORMAL': '✅ Trading Mode: NORMAL - Full trading enabled (Buy & Sell)',
            'EXIT_ONLY': '⚠️  Trading Mode: EXIT_ONLY - Looking for exit opportunities only (No new buys)',
            'PAUSED': '🛑 Trading Mode: PAUSED - All trading disabled'
        }
        logging.info(mode_messages.get(self.trading_mode, f'⚠️  Unknown trading mode: {self.trading_mode}'))
        
        # If PAUSED, skip all trading
        if self.trading_mode == 'PAUSED':
            logging.info("🛑 Trading is paused. Skipping all operations.")
            return
        
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

            # Skip buying logic if in EXIT_ONLY mode
            if self.trading_mode == 'EXIT_ONLY':
                logging.info("⚠️  EXIT_ONLY mode: Skipping entry and averaging opportunities")
                self.print_current_status(current_positions)
                logging.info("✅ Daily strategy completed")
                return

            entry_candidates = self.scan_for_opportunities()
            new_candidates = [c for c in entry_candidates if c['symbol'] not in current_positions]
            
            # Check Max Open Positions Limit
            if self.max_open_positions != -1 and len(current_positions) >= self.max_open_positions:
                logging.info(f"🚫 Max open positions ({self.max_open_positions}) reached. Skipping {len(new_candidates)} new entries.")
                new_candidates = []

            for candidate in new_candidates:
                logging.info(f"Eligible candidate: {candidate['symbol']} (Deviation: {candidate['deviation']:.2f}%) - Price: ₹{candidate['price']:.2f}, MA: ₹{candidate['ma']:.2f})")
            
            best_entry = None
            available_balance = self.get_account_balance()
            
            for candidate in new_candidates:
                quantity = math.floor(self.max_trade_value / candidate['price'])
                required_amount = candidate['price'] * quantity
                
                if (required_amount <= available_balance or self.db_handler.env == 'dev') and quantity > 0:
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
    parser.add_argument("--broker-id", type=str, help="Broker ID to run strategy for", default=None)
    args = parser.parse_args()

    run_id = args.run_id
    broker_id = args.broker_id

    # --- Configuration ---
    load_dotenv()

    MONGO_URI = os.getenv('MONGO_URI')
    
    if not MONGO_URI:
        print("❌ MONGO_URI not found in .env file")
        return

    # Connect to MongoDB
    mongo_client = MongoClient(MONGO_URI, tz_aware=True, tzinfo=UTC)
    db = mongo_client[MONGO_DB_NAME]
    
    # --- Load Broker Configuration ---
    broker_accounts = db['broker_accounts']
    
    if broker_id:
        # Load specific broker by ID
        broker_config = broker_accounts.find_one({"broker_id": broker_id})
        if not broker_config:
            print(f"❌ Broker with ID '{broker_id}' not found")
            return
    else:
        # Load default broker
        broker_config = broker_accounts.find_one({"is_default": True})
        if not broker_config:
            print("❌ No default broker found. Please set a default broker or specify --broker-id")
            return
    
    # Check if broker is enabled
    if not broker_config.get('enabled', True):
        print(f"⚠️  Broker '{broker_config.get('display_name')}' is disabled. Skipping execution.")
        return
    
    print(f"🔗 Running strategy for: {broker_config.get('display_name')} ({broker_config.get('broker_type')})")
    print(f"   Broker ID: {broker_config.get('broker_id')}")
    print(f"   Trading Mode: {broker_config.get('trading_mode', 'NORMAL')}")
    
    # --- Fetch Settings from DB ---
    user_settings_collection = db['user_settings']
    settings = user_settings_collection.find_one({'_id': 'global_settings'})
    
    if not settings:
        logging.warning("No user settings found. Using defaults.")
        settings = {
            'ma_period': MA_PERIOD,
            'trade_amount': MAX_TRADE_VALUE,
            'max_positions': 10,
            'entry_threshold': -2.0,
            'target_profit': 5.0,
            'averaging_threshold': -3.0,
            'trading_mode': 'NORMAL'
        }
    
    # Override trading_mode with broker-specific mode
    settings['trading_mode'] = broker_config.get('trading_mode', settings.get('trading_mode', 'NORMAL'))

    # --- Setup Database and Logging ---
    ENV = 'dev'  # Forced dev mode for testing
    db_handler = DatabaseHandler(MONGO_URI, MONGO_DB_NAME, ENV)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            MongoLogHandler(db_handler, run_id)
        ]
    )

    # --- Initialize Connector based on broker type ---
    broker_type = broker_config.get('broker_type')
    
    if broker_type == 'zerodha':
        from connectors.zerodha import ZerodhaConnector
        
        api_key = broker_config.get('api_key')
        api_secret = broker_config.get('api_secret')
        access_token = broker_config.get('access_token')
        
        if not all([api_key, api_secret, access_token]):
            logging.error("❌ Zerodha credentials incomplete in broker config")
            return
        
        broker_connector = ZerodhaConnector(
            api_key=api_key,
            api_secret=api_secret,
            access_token=access_token
        )
        logging.info("✅ Using Zerodha connector")
        
    elif broker_type == 'fyers':
        api_key = broker_config.get('api_key')
        api_secret = broker_config.get('api_secret')
        access_token = broker_config.get('access_token')
        
        if not all([api_key, api_secret, access_token]):
            logging.error("❌ Fyers credentials incomplete in broker config")
            return
        
        broker_connector = FyersConnector(
            api_key=api_key,
            api_secret=api_secret,
            access_token=access_token,
            pin=broker_config.get('pin', '')  # PIN may be needed for some operations
        )
        logging.info("✅ Using Fyers connector")
    
    else:
        logging.error(f"❌ Unsupported broker type: {broker_type}")
        return

    # --- Initialize Data Source ---
    data_source = YFinanceDataSource()
    logging.info("✅ Using yfinance for historical data")

    # --- Initialize Trader ---
    trader = SimpleNiftyTrader(
        broker=broker_connector,
        data_source=data_source,
        db_handler=db_handler,
        settings=settings
    )
    
    trader.run_daily_strategy()

if __name__ == "__main__":
    main()
