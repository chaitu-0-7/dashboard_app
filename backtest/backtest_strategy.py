import sys
import os
import logging
import pandas as pd
from typing import List, Dict

# Add parent directory to path to import live_stratergy
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live_stratergy import SimpleNiftyTrader, DatabaseHandler

class MockDatabaseHandler:
    def __init__(self):
        self.trades = []
        self.logs = []
        self.env = 'backtest'

    def get_trades_collection(self):
        return self

    def get_logs_collection(self):
        return self

    # Mock MongoDB methods
    def find(self, query):
        # Simple filter implementation for backtest
        if 'filled' in query:
            return [t for t in self.trades if t.get('filled') == query['filled']]
        return self.trades

    def insert_one(self, data):
        data['_id'] = f"TRADE_{len(self.trades) + 1}"
        self.trades.append(data)
        class Result:
            inserted_id = data['_id']
        return Result()

    def update_one(self, query, update):
        # Find trade by ID
        trade_id = query.get('_id')
        for trade in self.trades:
            if trade['_id'] == trade_id:
                if '$set' in update:
                    for k, v in update['$set'].items():
                        trade[k] = v
                return

    def aggregate(self, pipeline):
        return []

class BacktestTrader(SimpleNiftyTrader):
    def __init__(self, mock_fyers, max_trade_value=2000):
        self.fyers = mock_fyers
        self.db_handler = MockDatabaseHandler()
        self.rate_limiter = None # No rate limit needed for mock
        
        # Strategy parameters (same as live)
        self.ma_period = 20
        self.entry_threshold = -5.0
        self.exit_threshold = 5
        self.averaging_threshold = -3.0
        self.max_stocks_to_buy = 2
        self.max_stocks_to_scan = 5
        self.max_trade_value = max_trade_value
        
        self.trades = [] # In-memory trades
        
        # NIFTY 50 symbols (same as live)
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

    # Override methods that use rate_limiter or need specific mocking
    
    def get_order_status(self, order_id: str) -> Dict:
        # Mock always returns filled
        return {'status': 2} 

    def verify_and_update_order(self, trade_doc_id, order_id: str) -> bool:
        # Always true in mock
        self.db_handler.update_one(
            {'_id': trade_doc_id},
            {'$set': {'filled': True}}
        )
        return True

    def get_current_positions(self):
        # Use mock fyers holdings
        response = self.fyers.holdings()
        positions = {}
        for pos in response['holdings']:
            symbol = pos['symbol']
            qty = pos['quantity']
            if qty > 0:
                positions[symbol] = {
                    'quantity': qty,
                    'avg_price': pos['costPrice'],
                    'current_price': pos['ltp'],
                    'pnl': pos['pl'],
                    'pnl_pct': 0.0 
                }
        return positions, True

    def get_historical_data(self, symbol: str, days: int = 25):
        # Use mock fyers history
        # We need to calculate start date based on current simulation date
        # But MockFyersModel.history handles the filtering based on self.fyers.current_date
        return pd.DataFrame(self.fyers.history({'symbol': symbol})['candles'], 
                            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

    def get_current_price(self, symbol: str) -> float:
        # Use mock fyers quotes
        return self.fyers.quotes({'symbols': symbol})['d'][0]['v']['lp']

    def place_buy_order(self, symbol: str, quantity: int) -> Dict:
        return self.fyers.place_order({
            'symbol': symbol,
            'qty': quantity,
            'side': 1
        })

    def place_sell_order(self, symbol: str, quantity: int) -> Dict:
        return self.fyers.place_order({
            'symbol': symbol,
            'qty': quantity,
            'side': -1
        })
    
    def get_account_balance(self) -> float:
        return self.fyers.funds()['fund_limit'][0]['equityAmount']

    # Override run_daily_strategy to avoid logging to file/mongo and just run logic
    def run_daily_strategy(self):
        # We can just call the parent method, but we need to suppress some logging or ensure it goes to console
        # The parent uses 'logging' module, which we can configure in run_backtest.py
        super().run_daily_strategy()

    def scan_for_opportunities(self) -> List[Dict]:
        candidates = super().scan_for_opportunities()
        print(f"[DEBUG] Found {len(candidates)} candidates.")
        if candidates:
            print(f"[DEBUG] Top candidate: {candidates[0]}")
        return candidates
