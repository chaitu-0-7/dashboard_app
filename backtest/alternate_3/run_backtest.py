import pandas as pd
from datetime import datetime
import logging
import sys
import os

logging.basicConfig(level=logging.INFO, format='%(message)s')

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mock_fyers import MockFyersModel
from data_loader import download_nifty50_data

from optimal_strategy import OptimalCapitalTrader

def run_backtest():
    DATA_START_DATE = "2022-01-01"
    START_DATE = "2023-01-01"
    END_DATE = "2023-12-31"
    INITIAL_BALANCE = 40000
    TRADE_VALUE = 4000  # ₹4000 per trade
    
    temp_trader = OptimalCapitalTrader(None)
    symbols = temp_trader.nifty50_symbols
    
    print("Loading data...")
    data_feed = download_nifty50_data(symbols, DATA_START_DATE, END_DATE)
    
    if not data_feed:
        print("No data loaded. Exiting.")
        return

    mock_fyers = MockFyersModel(data_feed, initial_balance=INITIAL_BALANCE)
    trader = OptimalCapitalTrader(mock_fyers, max_trade_value=TRADE_VALUE)
    
    print(f"Starting backtest from {START_DATE} to {END_DATE}...")
    
    master_symbol = "NSE:RELIANCE-EQ"
    if master_symbol in data_feed:
        master_df = data_feed[master_symbol]
        mask = (master_df['date'] >= START_DATE) & (master_df['date'] <= END_DATE)
        dates = master_df.loc[mask, 'date'].tolist()
    else:
        dates = pd.date_range(start=START_DATE, end=END_DATE, freq='B')
    
    daily_metrics = []
    
    for current_date in dates:
        mock_fyers.set_date(current_date)
        trader.run_daily_strategy()
        
        cash = mock_fyers.balance
        holdings_value = 0
        for symbol, data in mock_fyers.holdings_data.items():
            price = mock_fyers._get_current_price(symbol)
            if price:
                holdings_value += price * data['quantity']
        
        total_value = cash + holdings_value
        
        daily_metrics.append({
            'date': current_date.strftime('%Y-%m-%d'),
            'portfolio_value': total_value,
            'cash_balance': cash,
            'capital_deployed': holdings_value
        })

    final_value = daily_metrics[-1]['portfolio_value']
    total_return = ((final_value - INITIAL_BALANCE) / INITIAL_BALANCE) * 100
    
    values = [d['portfolio_value'] for d in daily_metrics]
    peak = values[0]
    max_drawdown = 0
    for v in values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100
        if dd > max_drawdown:
            max_drawdown = dd

    trades = trader.db_handler.trades
    closed_trades = [t for t in trades if t['action'] == 'SELL']
    winning_trades = [t for t in closed_trades if t.get('profit', 0) > 0]
    win_rate = (len(winning_trades) / len(closed_trades) * 100) if closed_trades else 0

    summary = {
        'initial_balance': INITIAL_BALANCE,
        'final_balance': final_value,
        'total_return_pct': total_return,
        'max_drawdown_pct': max_drawdown,
        'total_trades': len(trades),
        'win_rate': win_rate
    }

    serializable_trades = []
    for t in trades:
        t_copy = t.copy()
        for k, v in t_copy.items():
            if isinstance(v, (datetime, pd.Timestamp)):
                t_copy[k] = v.strftime('%Y-%m-%d %H:%M:%S')
        if '_id' in t_copy:
            del t_copy['_id']
        serializable_trades.append(t_copy)

    output_data = {
        'summary': summary,
        'daily_data': daily_metrics,
        'trades': serializable_trades
    }

    import json
    with open('backtest/alternate_3/backtest_metrics.json', 'w') as f:
        json.dump(output_data, f, indent=4)
    
    print("\n" + "="*30)
    print("OPTIMAL CAPITAL STRATEGY")
    print("="*30)
    print(f"Initial Balance: ₹{INITIAL_BALANCE:,.2f}")
    print(f"Final Value:     ₹{final_value:,.2f}")
    print(f"Total Return:    {total_return:.2f}%")
    print(f"Max Drawdown:    {max_drawdown:.2f}%")
    print(f"Total Trades:    {len(trades)}")
    print(f"Win Rate:        {win_rate:.1f}%")
    
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from report_generator import generate_html_report
    generate_html_report('backtest/alternate_3/backtest_metrics.json', 'backtest/alternate_3/report.html')

if __name__ == "__main__":
    run_backtest()
