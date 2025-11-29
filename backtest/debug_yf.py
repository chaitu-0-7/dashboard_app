import yfinance as yf
import pandas as pd

symbol = "RELIANCE.NS"
print(f"Downloading {symbol}...")
df = yf.download(symbol, start="2023-01-01", end="2023-01-05", progress=False)
print("Columns:", df.columns)
print("First row:", df.head(1))
print("Column types:", type(df.columns))
if len(df.columns) > 0:
    print("First col type:", type(df.columns[0]))
