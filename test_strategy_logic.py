"""
Test Script for Strategy Logic Verification

This script tests the entry vs averaging logic WITHOUT placing real trades.
It will show you exactly what the strategy would do based on current market data.

Usage:
    python test_strategy_logic.py --broker-id <YOUR_BROKER_ID> --dry-run
"""

import os
import sys
from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime
import pytz

load_dotenv()

from config import MONGO_DB_NAME, MONGO_ENV, MA_PERIOD, MAX_TRADE_VALUE
from live_stratergy import DatabaseHandler, SimpleNiftyTrader
from connectors.fyers import FyersConnector
from connectors.data_source import YFinanceDataSource

UTC = pytz.utc
IST = pytz.timezone('Asia/Kolkata')

def test_strategy_logic(broker_id=None, dry_run=True):
    """Test the strategy logic without placing real trades"""
    
    print("="*70)
    print("🧪 STRATEGY LOGIC TEST (DRY RUN)")
    print("="*70)
    
    # MongoDB Setup
    mongo_uri = os.getenv('MONGO_URI')
    if not mongo_uri:
        print("❌ MONGO_URI not found in .env")
        return
    
    db_handler = DatabaseHandler(mongo_uri, MONGO_DB_NAME, MONGO_ENV)
    broker_accounts = db_handler.db['broker_accounts']
    
    # Get Broker Config
    if broker_id:
        broker_config = broker_accounts.find_one({"broker_id": broker_id})
    else:
        broker_config = broker_accounts.find_one({"is_default": True})
    
    if not broker_config:
        print("❌ Broker not found")
        return
    
    print(f"\n🔗 Testing for: {broker_config.get('display_name')}")
    print(f"   Username: {broker_config.get('username')}")
    print(f"   Trading Mode: {broker_config.get('trading_mode', 'NORMAL')}")
    
    # Get Settings
    settings = {
        'ma_period': int(broker_config.get('ma_period', MA_PERIOD)),
        'trade_amount': float(broker_config.get('trade_amount', MAX_TRADE_VALUE)),
        'max_positions': int(broker_config.get('max_positions', 10)),
        'entry_threshold': float(broker_config.get('entry_threshold', -2.0)),
        'target_profit': float(broker_config.get('target_profit', 5.0)),
        'averaging_threshold': float(broker_config.get('averaging_threshold', -3.0)),
        'trading_mode': 'PAUSED' if dry_run else broker_config.get('trading_mode', 'NORMAL')
    }
    
    print(f"\n⚙️  Strategy Settings:")
    print(f"   MA Period: {settings['ma_period']}")
    print(f"   Entry Threshold: {settings['entry_threshold']}%")
    print(f"   Target Profit: {settings['target_profit']}%")
    print(f"   Max Trade Value: ₹{settings['trade_amount']:,.0f}")
    print(f"   Max Positions: {settings['max_positions']}")
    
    # Initialize Components (but won't place trades)
    try:
        broker_connector = FyersConnector(
            api_key=broker_config.get('api_key'),
            api_secret=broker_config.get('api_secret'),
            access_token=broker_config.get('access_token'),
            pin=broker_config.get('pin', '')
        )
    except Exception as e:
        print(f"⚠️  Could not initialize broker connector: {e}")
        print("   Continuing with mock data for testing...")
        broker_connector = None
    
    data_source = YFinanceDataSource()
    
    # Create trader instance
    trader = SimpleNiftyTrader(
        broker=broker_connector if broker_connector else type('MockBroker', (), {
            'get_holdings': lambda: [],
            'get_funds': lambda: [{'equityAmount': 50000}],
            'get_quote': lambda s: {'s': 'ok', 'd': [{'v': {'lp': 100}}]},
            'get_orders': lambda: [],
            'place_order': lambda **k: {'s': 'error', 'message': 'DRY RUN'}
        })(),
        data_source=data_source,
        db_handler=db_handler,
        settings=settings,
        run_id="TEST_RUN",
        broker_id=broker_config.get('broker_id'),
        username=broker_config.get('username')
    )
    
    # Mock the execute methods to prevent real trades
    original_execute_buy = trader.execute_buy
    original_execute_sell = trader.execute_sell
    
    def mock_execute_buy(symbol, price, is_averaging=False):
        print(f"\n💰 [MOCK] Would BUY: {symbol} @ ₹{price:.2f} (averaging={is_averaging})")
        return True
    
    def mock_execute_sell(symbol, price, quantity, avg_price):
        profit = (price - avg_price) * quantity
        print(f"\n💰 [MOCK] Would SELL: {symbol} @ ₹{price:.2f}, Profit: ₹{profit:.2f}")
        return True
    
    trader.execute_buy = mock_execute_buy
    trader.execute_sell = mock_execute_sell
    
    # Run the strategy logic
    print("\n" + "="*70)
    print("🚀 RUNNING STRATEGY LOGIC")
    print("="*70)
    
    try:
        # Get current positions
        current_positions, success = trader.get_current_positions()
        
        if not success:
            print("⚠️  Could not fetch positions (this is OK for testing)")
            current_positions = {}
        
        print(f"\n📊 Current Positions: {len(current_positions)}")
        for symbol, pos in current_positions.items():
            pnl_pct = ((pos['current_price'] - pos['avg_price']) / pos['avg_price']) * 100
            print(f"   {symbol}: {pos['quantity']} @ ₹{pos['avg_price']:.2f} (P&L: {pnl_pct:+.1f}%)")
        
        # Check exits
        exit_candidates = trader.check_exit_conditions(current_positions)
        if exit_candidates:
            print(f"\n🎯 Exit Candidates: {len(exit_candidates)}")
            for ex in exit_candidates:
                print(f"   {ex['symbol']}: {ex['profit_pct']:.1f}% profit")
        else:
            print(f"\n🎯 No exit candidates (none at {settings['target_profit']}% profit)")
        
        # Scan for entries
        print(f"\n🔍 Scanning for entry opportunities...")
        entry_candidates = trader.scan_for_opportunities()
        
        new_candidates = [c for c in entry_candidates if c['symbol'] not in current_positions]
        
        print(f"\n📋 Entry Candidates: {len(entry_candidates)} total, {len(new_candidates)} new")
        for i, cand in enumerate(new_candidates[:5], 1):
            print(f"   {i}. {cand['symbol']}: {cand['deviation']:.2f}% below MA (₹{cand['price']:.2f})")
        
        # Check max positions
        if settings['max_positions'] != -1 and len(current_positions) >= settings['max_positions']:
            print(f"\n🚫 Max positions ({settings['max_positions']}) reached")
            new_candidates = []
        
        # Simulate entry logic
        best_entry = None
        available_balance = 50000  # Mock balance
        
        print(f"\n💰 Available Balance: ₹{available_balance:,.2f}")
        
        for candidate in new_candidates:
            quantity = int(settings['trade_amount'] / candidate['price'])
            required_amount = candidate['price'] * quantity
            
            print(f"\n  Checking {candidate['symbol']}:")
            print(f"    Quantity: {quantity}, Required: ₹{required_amount:,.2f}")
            
            if quantity <= 0:
                print(f"    ❌ REJECTED: quantity={quantity} (price too high)")
                continue
            
            if required_amount > available_balance:
                print(f"    ❌ REJECTED: Insufficient balance")
                continue
            
            print(f"    ✅ SELECTED as best entry")
            best_entry = candidate
            break
        
        # Final decision
        print("\n" + "="*70)
        print("📊 FINAL DECISION")
        print("="*70)
        
        if best_entry:
            print(f"✅ ACTION: Execute BUY for {best_entry['symbol']}")
            print(f"   Reason: New candidate available ({best_entry['deviation']:.1f}% below MA)")
        elif new_candidates:
            print(f"⚠️  ACTION: No trade (candidates exist but can't purchase)")
            print(f"   Reason: Balance/quantity issues")
        elif current_positions:
            print(f"🔄 ACTION: Check for averaging opportunities")
            print(f"   Reason: No new candidates, have existing positions")
        else:
            print(f"⏸️  ACTION: Stand by (no candidates, no positions)")
        
        print("\n" + "="*70)
        print("✅ TEST COMPLETED")
        print("="*70)
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test strategy logic without real trades")
    parser.add_argument("--broker-id", type=str, help="Broker ID to test")
    parser.add_argument("--dry-run", action="store_true", help="Run without placing orders (default)")
    
    args = parser.parse_args()
    
    test_strategy_logic(broker_id=args.broker_id, dry_run=args.dry_run or True)
