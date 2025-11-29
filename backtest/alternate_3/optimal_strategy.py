import sys
import os
import logging
import pandas as pd
from typing import List, Dict
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from live_stratergy import SimpleNiftyTrader

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backtest_strategy import MockDatabaseHandler

class OptimalCapitalTrader(SimpleNiftyTrader):
    """₹4k per trade, 10 max positions, average with 1 qty"""
    
    def __init__(self, mock_fyers, max_trade_value=4000):
        self.fyers = mock_fyers
        self.db_handler = MockDatabaseHandler()
        self.rate_limiter = None
        
        # Strategy parameters - ONLY user's changes
        self.ma_period = 20
        self.entry_threshold = -2.0      # Entry at -2%
        self.exit_threshold = 5          # Exit at 5%
        self.averaging_threshold = -3.0  # Average at -3%
        self.max_positions = 10          # 10 max positions
        self.max_stocks_to_scan = 5
        
        self.max_trade_value = max_trade_value  # ₹4000 per trade
        self.trades = []
        
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

    def get_order_status(self, order_id: str) -> Dict:
        return {'status': 2}

    def verify_and_update_order(self, trade_doc_id, order_id: str) -> bool:
        self.db_handler.update_one({'_id': trade_doc_id}, {'$set': {'filled': True}})
        return True

    def get_current_positions(self):
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
        return pd.DataFrame(self.fyers.history({'symbol': symbol})['candles'], 
                            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

    def get_current_price(self, symbol: str) -> float:
        return self.fyers.quotes({'symbols': symbol})['d'][0]['v']['lp']

    def place_buy_order(self, symbol: str, quantity: int) -> Dict:
        return self.fyers.place_order({'symbol': symbol, 'qty': quantity, 'side': 1})

    def place_sell_order(self, symbol: str, quantity: int) -> Dict:
        return self.fyers.place_order({'symbol': symbol, 'qty': quantity, 'side': -1})
    
    def get_account_balance(self) -> float:
        return self.fyers.funds()['fund_limit'][0]['equityAmount']

    def scan_for_opportunities(self) -> List[Dict]:
        """Scan for stocks below -2% threshold"""
        candidates = []
        
        for symbol in self.nifty50_symbols:
            try:
                df = self.get_historical_data(symbol, days=self.ma_period + 15)
                if df.empty: continue
                
                ma = self.calculate_moving_average(df['close'])
                if ma is None: continue
                
                current_price = self.get_current_price(symbol)
                if current_price <= 0: continue
                
                deviation = ((current_price - ma) / ma) * 100
                
                if deviation <= self.entry_threshold:
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
        """Check for profit target only"""
        exit_candidates = []
        
        for symbol, position in positions.items():
            try:
                current_price = position['current_price']
                if current_price <= 0: continue
                
                profit_pct = ((current_price - position['avg_price']) / position['avg_price']) * 100
                
                # Only profit target exit
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

    def execute_sell(self, symbol: str, current_price: float, quantity: int, avg_price: float) -> bool:
        """Execute sell"""
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
                    'date': datetime.now(),
                    'order_id': order_id,
                    'profit': profit,
                    'profit_pct': profit_pct,
                    'comment': f'PROFIT EXIT: {profit_pct:.1f}%'
                }
                trade_doc_id = self.save_trade(trade_data)

                if trade_doc_id and self.verify_and_update_order(trade_doc_id, order_id):
                    self.trades = self.load_trades()
                    logging.info(f"💰 SOLD: {quantity} {symbol} at ₹{current_price:.2f}, Profit: ₹{profit:.2f}")
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

    def try_averaging_down(self, positions: Dict):
        """Average with 1 qty only (as per user request)"""
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
            # Average with 1 qty only
            logging.info(f"🔄 AVERAGING: {worst_performer['symbol']} at {worst_performer['performance']:.1f}% with 1 share")
            self.execute_buy(worst_performer['symbol'], worst_performer['price'], is_averaging=True, quantity=1)

    def execute_buy(self, symbol: str, current_price: float, is_averaging: bool = False, quantity: int = None) -> bool:
        """Execute buy"""
        try:
            if quantity is None:
                quantity = max(1, int(self.max_trade_value / current_price))
            
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
                    'date': datetime.now(),
                    'order_id': order_id,
                    'is_averaging': is_averaging,
                    'comment': 'AVERAGING' if is_averaging else 'NEW ENTRY'
                }
                trade_doc_id = self.save_trade(trade_data)

                if trade_doc_id and self.verify_and_update_order(trade_doc_id, order_id):
                    self.trades = self.load_trades()
                    logging.info(f"✅ BUY: {quantity} {symbol} at ₹{current_price:.2f}")
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

    def run_daily_strategy(self):
        """Strategy: ₹4k per trade, 10 max positions, average with 1 qty"""
        logging.info("🚀 Starting strategy...")
        
        try:
            current_positions, positions_fetch_success = self.get_current_positions()

            if not positions_fetch_success:
                logging.error("Could not fetch current positions. Aborting.")
                return

            for symbol, position in current_positions.items():
                position['pnl'] = (position['current_price'] - position['avg_price']) * position['quantity']
                position['pnl_pct'] = ((current_price - position['avg_price']) / position['avg_price']) * 100 if position['avg_price'] > 0 else 0
            
            # Check exits
            exit_candidates = self.check_exit_conditions(current_positions)
            
            if exit_candidates:
                best_exit = exit_candidates[0]
                logging.info(f"🎯 EXIT: {best_exit['symbol']} with {best_exit['profit_pct']:.1f}% profit")
                
                if self.execute_sell(
                    best_exit['symbol'],
                    best_exit['current_price'],
                    best_exit['quantity'],
                    best_exit['avg_buy_price']
                ):
                    pass
            
            # Refresh positions
            current_positions, positions_fetch_success = self.get_current_positions()
            if not positions_fetch_success:
                logging.warning("Could not refresh positions.")

            # Position limit check
            if len(current_positions) >= self.max_positions:
                logging.info(f"⚠️ Max positions ({self.max_positions}) reached.")
            else:
                entry_candidates = self.scan_for_opportunities()
                new_candidates = [c for c in entry_candidates if c['symbol'] not in current_positions]
                
                for candidate in new_candidates:
                    logging.info(f"Candidate: {candidate['symbol']} ({candidate['deviation']:.2f}%)")
                
                best_entry = None
                available_balance = self.get_account_balance()
                
                for candidate in new_candidates:
                    quantity = max(1, int(self.max_trade_value / candidate['price']))
                    required_amount = candidate['price'] * quantity
                    
                    if required_amount <= available_balance and quantity > 0:
                        best_entry = candidate
                        break
                
                if best_entry:
                    logging.info(f"🎯 ENTRY: {best_entry['symbol']} at {best_entry['deviation']:.1f}% below MA")
                    self.execute_buy(best_entry['symbol'], best_entry['price'])
                else:
                    if current_positions:
                        self.try_averaging_down(current_positions)
            
            self.print_current_status(current_positions)
            
        except Exception as e:
            logging.error(f"❌ Error: {e}")
        
        logging.info("✅ Strategy completed")
