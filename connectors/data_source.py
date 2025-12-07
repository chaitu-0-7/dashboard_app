from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
import logging
import pandas as pd
import datetime
import time

try:
    import yfinance as yf
except ImportError:
    yf = None
    logging.error("yfinance not installed. Please install it using 'pip install yfinance'.")

class DataSource(ABC):
    """
    Abstract Base Class for Data Sources.
    Defines the interface for fetching historical data.
    """
    
    @abstractmethod
    def get_historical_data(self, symbol: str, period: str = "30d", interval: str = "1d") -> Dict[str, Any]:
        """
        Fetch historical data for a symbol.
        
        Args:
            symbol (str): The stock symbol (e.g., "NSE:INFY").
            period (str): The data period to download (e.g., "30d", "1mo").
            interval (str): The data interval (e.g., "1d", "1h").
            
        Returns:
            Dict[str, Any]: Standardized response containing candles.
                            Format: {'s': 'ok', 'candles': [[timestamp, open, high, low, close, volume], ...]}
        """
        pass

    @abstractmethod
    def get_latest_price(self, symbol: str) -> float:
        """
        Fetch the latest available price for a symbol.
        Note: Might be delayed depending on the source.
        """
        pass

class YFinanceDataSource(DataSource):
    """
    Implementation of DataSource using yfinance.
    """
    
    def __init__(self):
        if yf is None:
            raise ImportError("yfinance library is required for YFinanceDataSource")
        self.name = "yfinance"

    def _convert_symbol(self, symbol: str) -> str:
        """
        Convert broker symbol format to yfinance format.
        Example: "NSE:INFY" -> "INFY.NS"
                 "NSE:RELIANCE-EQ" -> "RELIANCE.NS"
        """
        # Remove exchange prefix
        if ":" in symbol:
            _, ticker = symbol.split(":")
        else:
            ticker = symbol
            
        # Remove -EQ suffix if present (common in Fyers/Zerodha for equity)
        if ticker.endswith("-EQ"):
            ticker = ticker.replace("-EQ", "")
            
        # Append .NS for NSE stocks
        return f"{ticker}.NS"

    def get_historical_data(self, symbol: str, period: str = "30d", interval: str = "1d") -> Dict[str, Any]:
        """
        Fetch historical data from yfinance.
        """
        yf_symbol = self._convert_symbol(symbol)
        logging.info(f"Fetching historical data for {symbol} (yfinance: {yf_symbol})")
        
        try:
            ticker = yf.Ticker(yf_symbol)
            # Fetch history
            # period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max
            # interval: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo
            
            # Map our period/interval to yfinance compatible ones if needed
            # For now assuming standard inputs like "30d" and "1d" which work fine or need slight adjustment
            
            df = ticker.history(period=period, interval=interval)
            
            if df.empty:
                logging.warning(f"No data found for {yf_symbol}")
                return {"s": "error", "message": "No data found"}
            
            # Reset index to get Date as a column
            df = df.reset_index()
            
            # Normalize to standard format
            # Fyers/Zerodha format: [[timestamp, open, high, low, close, volume], ...]
            candles = []
            for _, row in df.iterrows():
                # Convert date to timestamp
                # yfinance Date can be datetime64[ns]
                if 'Date' in row:
                    dt = row['Date']
                elif 'Datetime' in row:
                    dt = row['Datetime']
                else:
                    continue
                    
                # Convert to epoch timestamp (seconds)
                ts = int(dt.timestamp())
                
                candles.append([
                    ts,
                    row['Open'],
                    row['High'],
                    row['Low'],
                    row['Close'],
                    row['Volume']
                ])
                
            return {
                "s": "ok",
                "candles": candles
            }
            
        except Exception as e:
            logging.error(f"Error fetching data from yfinance for {symbol}: {e}")
            return {"s": "error", "message": str(e)}

    def get_latest_price(self, symbol: str) -> float:
        """
        Fetch latest price from yfinance.
        """
        yf_symbol = self._convert_symbol(symbol)
        try:
            ticker = yf.Ticker(yf_symbol)
            # fast_info is faster and often real-time or near real-time for some markets
            price = ticker.fast_info.last_price
            if price:
                return float(price)
            
            # Fallback to history if fast_info fails
            df = ticker.history(period="1d")
            if not df.empty:
                return float(df['Close'].iloc[-1])
                
            return 0.0
        except Exception as e:
            logging.error(f"Error fetching latest price from yfinance for {symbol}: {e}")
            return 0.0
