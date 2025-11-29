import yfinance as yf
import pandas as pd
import os
from datetime import datetime, timedelta

def download_nifty50_data(symbols, start_date, end_date, data_dir='backtest/data'):
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    data_feed = {}
    
    print(f"Downloading data for {len(symbols)} symbols...")
    
    for symbol in symbols:
        # Fyers symbol format: NSE:RELIANCE-EQ -> Yahoo format: RELIANCE.NS
        yahoo_symbol = symbol.replace('NSE:', '').replace('-EQ', '') + '.NS'
        file_path = os.path.join(data_dir, f"{yahoo_symbol}.csv")
        
        if os.path.exists(file_path):
            df = pd.read_csv(file_path)
            df['date'] = pd.to_datetime(df['date'])
        else:
            print(f"Fetching {yahoo_symbol}...")
            try:
                df = yf.download(yahoo_symbol, start=start_date, end=end_date, progress=False)
                if df.empty:
                    print(f"Warning: No data for {yahoo_symbol}")
                    continue
                
                # Handle MultiIndex columns (Price, Ticker)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                
                # Reset index to make Date a column
                df = df.reset_index()
                
                # Rename columns to match what we need (lowercase)
                df.columns = [c.lower() for c in df.columns]
                # Ensure 'date' column exists (yf might return 'Date')
                
                # Save to CSV
                df.to_csv(file_path, index=False)
            except Exception as e:
                print(f"Error fetching {yahoo_symbol}: {e}")
                continue

        # Clean up data for backtest
        # We need: date, open, high, low, close, volume
        # Ensure date is datetime
        df['date'] = pd.to_datetime(df['date'])
        # Sort by date
        df = df.sort_values('date')
        
        data_feed[symbol] = df
        
    return data_feed
