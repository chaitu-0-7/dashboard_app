import pandas as pd
import logging

class MockFyersModel:
    def __init__(self, data_feed, initial_balance=100000):
        self.data_feed = data_feed  # Dictionary {symbol: DataFrame}
        self.current_date = None
        self.balance = initial_balance
        self.holdings_data = {}  # {symbol: {quantity, avg_price}}
        self.orders = []
        self.brokerage_fee = 20.0

    def set_date(self, date):
        self.current_date = date

    def funds(self):
        return {
            's': 'ok',
            'fund_limit': [{'equityAmount': self.balance}]
        }

    def holdings(self):
        holdings_list = []
        for symbol, data in self.holdings_data.items():
            current_price = self._get_current_price(symbol)
            pnl = (current_price - data['avg_price']) * data['quantity']
            holdings_list.append({
                'symbol': symbol,
                'quantity': data['quantity'],
                'costPrice': data['avg_price'],
                'ltp': current_price,
                'pl': pnl
            })
        return {'s': 'ok', 'holdings': holdings_list}

    def orderbook(self, data=None):
        # In this mock, orders are filled immediately, so we just return them
        return {'s': 'ok', 'orderBook': self.orders}

    def positions(self):
        # For simplicity, we'll just map holdings to positions format if needed
        # But the strategy mainly uses holdings()
        return {'s': 'ok', 'netPositions': []}

    def quotes(self, data):
        # data = {"symbols": "NSE:RELIANCE-EQ"}
        symbol = data['symbols']
        price = self._get_current_price(symbol)
        return {
            's': 'ok',
            'd': [{'v': {'lp': price}}]
        }

    def history(self, data):
        # data = {symbol, range_from, range_to, ...}
        # In backtest, we might need to return data up to current_date
        # But the strategy calls history() to calculate MA.
        # We should return data from the data_feed up to self.current_date
        
        symbol = data['symbol']
        if symbol not in self.data_feed:
            return {'s': 'error', 'message': 'Data not found'}

        df = self.data_feed[symbol]
        
        # Filter data up to current_date (exclusive of current date to simulate "past" data for MA)
        # Actually, for MA calculation, we usually include the current candle if it's closed, 
        # but here we are simulating "live" decision making at a specific time.
        # Let's assume we are running this at market close or during the day.
        # If we run at market close, we have today's data.
        
        mask = df['date'] < self.current_date
        filtered_df = df.loc[mask].copy()
        
        # Format for Fyers response
        # candles = [[timestamp, open, high, low, close, volume], ...]
        candles = []
        for _, row in filtered_df.iterrows():
            candles.append([
                int(row['date'].timestamp()),
                row['open'],
                row['high'],
                row['low'],
                row['close'],
                row['volume']
            ])
            
        return {'s': 'ok', 'candles': candles}

    def place_order(self, data):
        # data = {symbol, qty, side (1=Buy, -1=Sell), ...}
        symbol = data['symbol']
        qty = data['qty']
        side = data['side']
        
        price = self._get_current_price(symbol)
        if price is None:
            return {'s': 'error', 'message': 'Price not available'}

        order_id = f"ORD_{len(self.orders) + 1}"
        
        if side == 1: # BUY
            cost = price * qty
            if self.balance >= cost + self.brokerage_fee:
                self.balance -= (cost + self.brokerage_fee)
                
                # Update holdings
                if symbol in self.holdings_data:
                    old_qty = self.holdings_data[symbol]['quantity']
                    old_avg = self.holdings_data[symbol]['avg_price']
                    new_qty = old_qty + qty
                    new_avg = ((old_qty * old_avg) + (qty * price)) / new_qty
                    self.holdings_data[symbol] = {'quantity': new_qty, 'avg_price': new_avg}
                else:
                    self.holdings_data[symbol] = {'quantity': qty, 'avg_price': price}
                
                self.orders.append({
                    'id': order_id,
                    'symbol': symbol,
                    'qty': qty,
                    'side': 1,
                    'price': price,
                    'status': 2, # Filled
                    'orderDateTime': self.current_date.strftime("%d-%b-%Y %H:%M:%S")
                })
                return {'s': 'ok', 'id': order_id}
            else:
                return {'s': 'error', 'message': 'Insufficient funds'}

        elif side == -1: # SELL
            if symbol in self.holdings_data and self.holdings_data[symbol]['quantity'] >= qty:
                revenue = price * qty
                self.balance += (revenue - self.brokerage_fee)
                
                self.holdings_data[symbol]['quantity'] -= qty
                if self.holdings_data[symbol]['quantity'] == 0:
                    del self.holdings_data[symbol]
                
                self.orders.append({
                    'id': order_id,
                    'symbol': symbol,
                    'qty': qty,
                    'side': -1,
                    'price': price,
                    'status': 2, # Filled
                    'orderDateTime': self.current_date.strftime("%d-%b-%Y %H:%M:%S")
                })
                return {'s': 'ok', 'id': order_id}
            else:
                return {'s': 'error', 'message': 'Insufficient holdings'}

    def _get_current_price(self, symbol):
        if symbol not in self.data_feed:
            return None
        df = self.data_feed[symbol]
        row = df[df['date'] == self.current_date]
        if not row.empty:
            return row.iloc[0]['close'] # Assuming we trade at Close price of the day
        return None
