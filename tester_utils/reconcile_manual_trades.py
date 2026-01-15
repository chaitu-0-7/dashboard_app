from pymongo import MongoClient
import os
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv

# Add parent directory to path to import local modules if needed (e.g. fyers_apiv3)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

# Config
MONGO_URI = os.getenv('MONGO_URI')
DB_NAME = 'nifty_shop'
ENV = os.getenv('ENV', 'prod')

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
trades_coll = db[f"trades_{ENV}"]
tokens_coll = db['fyers_tokens'] # Assuming Fyers mostly
accounts_coll = db['broker_accounts']

UTC = timezone.utc

def authenticate_broker(broker_config):
    """Authenticate and return broker instance."""
    b_type = broker_config.get('broker_type', broker_config.get('broker'))
    b_id = broker_config['broker_id']

    if b_type == 'fyers':
        # Try finding by broker_id logic first
        token_doc = tokens_coll.find_one({'broker_id': b_id})
        
        # Fallback: Try finding ANY token if specific one fails (Legacy Support)
        if not token_doc:
             print(f"Warning: No specific token for {b_id}, trying latest.")
             token_doc = tokens_coll.find_one(sort=[('generated_at', -1)])
             
        if token_doc and token_doc.get('access_token'):
            try:
                from fyers_apiv3 import fyersModel
                # log_path needs to be writable
                return fyersModel.FyersModel(
                    client_id=broker_config.get('client_id', broker_config.get('api_key')), 
                    token=token_doc['access_token'], 
                    log_path=os.getcwd()
                )
            except ImportError:
                print("Error: fyers_apiv3 not installed?")
                return None
    # Add Zerodha if needed
    return None

def reconcile_trades():
    print(f"--- Reconciling Trades (Hard Reset) for ENV: {ENV} ---")
    
    # 1. Get Active Brokers
    brokers = list(accounts_coll.find({'mode': {'$ne': 'paper'}}))
    
    for b_conf in brokers:
        b_id = b_conf['broker_id']
        b_name = b_conf.get('display_name', b_id)
        print(f"\nPROCESSING BROKER: {b_name} ({b_id})")
        
        # 2. Fetch Real Holdings (K)
        broker_api = authenticate_broker(b_conf)
        if not broker_api:
            print(f"Skipping {b_id}: Could not authenticate.")
            continue
            
        real_holdings = {} # Symbol -> Qty
        try:
            resp = broker_api.holdings()
            if resp.get('s') == 'ok':
                for h in resp.get('holdings', []):
                    real_holdings[h['symbol']] = h['quantity']
                print(f"Fetched {len(real_holdings)} real holdings.")
            else:
                print(f"Failed to fetch holdings: {resp}")
                continue
        except Exception as e:
            print(f"API Error: {e}")
            continue

        # 3. Analyze DB Positions (N Buys, M Sells) with FIFO Logic
        distinct_symbols = trades_coll.distinct('symbol', {'broker_id': b_id})
        
        for symbol in distinct_symbols:
            # Fetch ALL trades for this symbol, sorted by DATE ASC
            all_trades = list(trades_coll.find({
                'broker_id': b_id,
                'symbol': symbol,
                'filled': True,
                'order_id': {'$ne': 'MANUAL'} # Ignore old manuals
            }).sort('date', 1))
            
            if not all_trades: continue

            # Separate into Buys and Sells
            buys = [] 
            sells = []
            for t in all_trades:
                if t['action'] == 'BUY':
                    # We track remaining qty for each buy
                    t['remaining_qty'] = t['quantity']
                    buys.append(t)
                elif t['action'] == 'SELL':
                    sells.append(t)
            
            # FIFO Matching: Deduct Sells from Buys
            for sell in sells:
                sell_qty_left = sell['quantity']
                for buy in buys:
                    if sell_qty_left <= 0: break
                    if buy['remaining_qty'] > 0:
                        deduct = min(buy['remaining_qty'], sell_qty_left)
                        buy['remaining_qty'] -= deduct
                        sell_qty_left -= deduct
            
            # Identify Theoretically Open Buys (N - M)
            open_buys = [b for b in buys if b['remaining_qty'] > 0]
            net_system_qty = sum(b['remaining_qty'] for b in open_buys)
            
            if net_system_qty <= 0: continue

            # Get Real Holding (K)
            real_k = 0
            for r_sym, r_qty in real_holdings.items():
                if symbol == r_sym or (symbol in r_sym and 'NSE:' not in symbol):
                    real_k = r_qty
                    break
            
            # Determine Gap
            gap = net_system_qty - real_k
            
            if gap > 0:
                print(f"  > {symbol}: System Open={net_system_qty}, Real={real_k} => GAP={gap}")
                
                # HARD CLEANUP: Delete existing manuals
                del_res = trades_coll.delete_many({
                    'broker_id': b_id,
                    'symbol': symbol,
                    'order_id': 'MANUAL'
                })
                if del_res.deleted_count > 0:
                    print(f"    - Deleted {del_res.deleted_count} existing manual rows.")

                # ATTRIBUTE GAP TO SPECIFIC BUYS (FIFO)
                # If we hold K, we hold the LATEST K (Last In, Still Here).
                # So the OLDEST (First In) open buys are the ones missing (Sold).
                # Logic: Iterate open_buys from start. Accumulate 'missing_needed' = gap.
                
                missing_needed = gap
                for buy in open_buys:
                    if missing_needed <= 0: break
                    
                    available_in_buy = buy['remaining_qty']
                    # We assume this buy is part of the missing lot
                    qty_to_mark = min(available_in_buy, missing_needed)
                    
                    # Create Manual Sell for this specific Buy
                    # User requested 'timestamp should be the trade opening time'
                    # We will set 'date' = Buy's Date
                    
                    new_trade = {
                        'broker_id': b_id,
                        'symbol': symbol,
                        'action': 'SELL',
                        'quantity': qty_to_mark,
                        'price': 0.0, # Unknown close price
                        'avg_price': buy['price'], # The original Buy Price
                        'date': buy['date'], # Setting to Buy Date as requested
                        'order_id': 'MANUAL',
                        'status': 'PENDING_MANUAL_PRICE',
                        'filled': True,
                        'profit': 0.0,
                        'profit_pct': 0.0,
                        'comment': f"Manual Close of Buy from {buy['date'].strftime('%Y-%m-%d %H:%M')}"
                    }
                    trades_coll.insert_one(new_trade)
                    print(f"    - Linked Manual Sell to Buy Date {buy['date']} (Qty: {qty_to_mark})")
                    
                    missing_needed -= qty_to_mark

    print("\n--- Reconciliation Complete ---")

if __name__ == "__main__":
    reconcile_trades()
