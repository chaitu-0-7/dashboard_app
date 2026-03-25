"""
NIFTY 50 Constituents Manager

Handles fetching, validating, and updating NIFTY 50 constituents list.
Runs every Tuesday before strategy execution.

Sources:
1. NSE India API (Primary)
2. Fyers API (Backup)
"""

import os
import sys
import logging
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from pymongo import MongoClient
import pytz

from dotenv import load_dotenv
load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import MONGO_DB_NAME, MONGO_ENV

UTC = pytz.utc
IST = pytz.timezone('Asia/Kolkata')

# Admin Email
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'chaitu2@gmail.com')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)


class Nifty50Manager:
    """Manages NIFTY 50 constituents list"""
    
    def __init__(self, mongo_uri: str = None):
        """Initialize Nifty50Manager"""
        self.mongo_uri = mongo_uri or os.getenv('MONGO_URI')
        if not self.mongo_uri:
            raise ValueError("MONGO_URI not found")
        
        self.client = MongoClient(self.mongo_uri, tz_aware=True, tzinfo=UTC)
        self.db = self.client[MONGO_DB_NAME]
        self.collection = self.db['nifty50_constituents']
        self.logs_collection = self.db['nifty50_update_logs']
        
        # Fyers credentials (for backup source)
        self.fyers_api_key = os.getenv('FYERS_CLIENT_ID')
        self.fyers_api_secret = os.getenv('FYERS_SECRET_ID')
        self.fyers_access_token = os.getenv('FYERS_ACCESS_TOKEN')
        
        # Admin email
        self.admin_email = ADMIN_EMAIL
        
        # Validation timeout (seconds)
        self.validation_timeout = 120  # 2 minutes total
    
    def get_current_constituents(self) -> List[str]:
        """Get current list of NIFTY 50 symbols"""
        doc = self.collection.find_one({"_id": "current_list"})
        
        if not doc:
            logging.warning("No NIFTY 50 list found in DB. Using hardcoded fallback.")
            return self._get_hardcoded_symbols()
        
        # Return only active symbols
        symbols = [s['symbol'] for s in doc.get('symbols', []) if s.get('status') == 'active']
        logging.info(f"Loaded {len(symbols)} active symbols from DB")
        return symbols
    
    def get_all_constituents_with_status(self) -> List[Dict]:
        """Get all symbols with their status (for admin UI)"""
        doc = self.collection.find_one({"_id": "current_list"})
        
        if not doc:
            return []
        
        return doc.get('symbols', [])
    
    def _get_hardcoded_symbols(self) -> List[str]:
        """Fallback hardcoded NIFTY 50 symbols"""
        return [
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
    
    def fetch_from_nse(self) -> Optional[List[Dict]]:
        """
        Fetch NIFTY 50 constituents from NSE India API
        
        Returns: List of dicts with 'symbol' key, or None if failed
        """
        logging.info("📡 Fetching NIFTY 50 from NSE India API...")
        
        try:
            # NSE India endpoint for index constituents
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'en-US,en;q=0.9',
            }
            
            session = requests.Session()
            session.headers.update(headers)
            
            # First, visit homepage to set cookies
            session.get('https://www.nseindia.com', timeout=10)
            
            # Fetch index constituents
            url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050"
            response = session.get(url, timeout=15)
            
            if response.status_code != 200:
                logging.error(f"NSE API returned status {response.status_code}")
                return None
            
            data = response.json()
            
            if not data or 'data' not in data:
                logging.error("NSE API returned invalid data structure")
                return None
            
            # Parse constituents
            symbols = []
            for stock in data.get('data', []):
                symbol = stock.get('symbol', '').strip()
                if symbol:
                    # Convert to Fyers format: NSE:SYMBOL-EQ
                    # NSE returns just the symbol name, we need to format it
                    fyers_symbol = f"NSE:{symbol}-EQ"
                    symbols.append({
                        'symbol': fyers_symbol,
                        'company_name': stock.get('symbol', ''),
                        'source': 'NSE'
                    })
            
            logging.info(f"✅ Fetched {len(symbols)} symbols from NSE")
            return symbols if symbols else None
            
        except Exception as e:
            logging.error(f"Failed to fetch from NSE: {e}")
            return None
    
    def fetch_from_fyers(self) -> Optional[List[Dict]]:
        """
        Fetch NIFTY 50 constituents from Fyers API (backup)
        
        Returns: List of dicts with 'symbol' key, or None if failed
        """
        logging.info("📡 Fetching from Fyers API (backup)...")
        
        try:
            from connectors.fyers import FyersConnector
            
            if not all([self.fyers_api_key, self.fyers_api_secret, self.fyers_access_token]):
                logging.error("Fyers credentials not available")
                return None
            
            connector = FyersConnector(
                api_key=self.fyers_api_key,
                api_secret=self.fyers_api_secret,
                access_token=self.fyers_access_token
            )
            
            # Get all symbols from Fyers
            data = connector.get_data()
            
            if data.get('s') != 'ok':
                logging.error("Fyers API returned error")
                return None
            
            all_symbols = data.get('data', {}).get('symbols', [])
            
            # Filter for NIFTY 50 (we'll use our existing list as reference)
            # and validate they exist in Fyers
            current_list = self._get_hardcoded_symbols()
            fyers_symbols = []
            
            for sym_data in all_symbols:
                sym = sym_data.get('symbol', '')
                if sym in current_list:
                    fyers_symbols.append({
                        'symbol': sym,
                        'company_name': sym.replace('NSE:', '').replace('-EQ', ''),
                        'source': 'FYERS'
                    })
            
            logging.info(f"✅ Found {len(fyers_symbols)} symbols from Fyers")
            return fyers_symbols if len(fyers_symbols) > 40 else None
            
        except Exception as e:
            logging.error(f"Failed to fetch from Fyers: {e}")
            return None
    
    def validate_symbol(self, symbol: str) -> Tuple[bool, Optional[float]]:
        """
        Validate if a symbol exists and get its current price
        
        Returns: (is_valid, current_price)
        """
        try:
            # Try Fyers first
            from connectors.fyers import FyersConnector
            
            if all([self.fyers_api_key, self.fyers_api_secret, self.fyers_access_token]):
                connector = FyersConnector(
                    api_key=self.fyers_api_key,
                    api_secret=self.fyers_api_secret,
                    access_token=self.fyers_access_token
                )
                
                quote = connector.get_quote(symbol)
                
                if quote.get('s') == 'ok' and 'd' in quote and len(quote['d']) > 0:
                    price = float(quote['d'][0]['v'].get('lp', 0))
                    if price > 0:
                        return (True, price)
            
            # Fallback to YFinance
            try:
                import yfinance as yf
                
                # Convert symbol format: NSE:SYMBOL-EQ -> SYMBOL.NS
                ticker_symbol = symbol.replace('NSE:', '').replace('-EQ', '')
                yf_symbol = f"{ticker_symbol}.NS"
                
                ticker = yf.Ticker(yf_symbol)
                price = ticker.fast_info.last_price
                
                if price and price > 0:
                    return (True, float(price))
                    
            except Exception:
                pass
            
            return (False, None)
            
        except Exception as e:
            logging.error(f"Validation failed for {symbol}: {e}")
            return (False, None)
    
    def validate_all_symbols(self, symbols: List[str]) -> Dict[str, Dict]:
        """
        Validate all symbols with timeout
        
        Returns: {symbol: {'valid': bool, 'price': float, 'source': str}}
        """
        logging.info(f"🔍 Validating {len(symbols)} symbols (timeout: {self.validation_timeout}s)...")
        
        results = {}
        start_time = datetime.now()
        
        for i, symbol in enumerate(symbols):
            # Check timeout
            elapsed = (datetime.now() - start_time).total_seconds()
            if elapsed > self.validation_timeout:
                logging.warning(f"⏱️ Validation timeout after {elapsed:.1f}s. Remaining symbols marked invalid.")
                # Mark remaining as invalid
                for remaining in symbols[i:]:
                    results[remaining] = {'valid': False, 'price': None, 'source': 'timeout'}
                break
            
            is_valid, price = self.validate_symbol(symbol)
            source = 'fyers' if price else 'yfinance'
            
            results[symbol] = {
                'valid': is_valid,
                'price': price,
                'source': source if is_valid else 'failed'
            }
            
            if is_valid:
                logging.debug(f"  ✅ {symbol}: ₹{price:.2f} ({source})")
            else:
                logging.warning(f"  ❌ {symbol}: Invalid")
        
        valid_count = sum(1 for r in results.values() if r['valid'])
        logging.info(f"✅ Validated {valid_count}/{len(symbols)} symbols")
        
        return results
    
    def update_constituents(self, force: bool = False) -> Dict:
        """
        Update NIFTY 50 constituents list
        
        Args:
            force: If True, update even if not Tuesday
        
        Returns: Update result dict
        """
        today = datetime.now(IST)
        is_tuesday = today.weekday() == 1  # Monday=0, Tuesday=1
        
        if not is_tuesday and not force:
            logging.info("Not Tuesday. Skipping NIFTY 50 update.")
            return {
                'status': 'skipped',
                'reason': 'Not Tuesday',
                'next_update': 'Next Tuesday'
            }
        
        logging.info(f"🚀 Starting NIFTY 50 update (Date: {today.strftime('%Y-%m-%d %H:%M')})")
        
        result = {
            'status': 'completed',
            'update_date': datetime.now(UTC),
            'symbols_added': [],
            'symbols_removed': [],
            'validation_failed': [],
            'source_used': None,
            'email_sent': False,
            'error': None
        }
        
        try:
            # Step 1: Fetch from sources
            nse_data = self.fetch_from_nse()
            source_used = 'NSE'
            
            if not nse_data:
                logging.warning("NSE fetch failed, trying Fyers...")
                nse_data = self.fetch_from_fyers()
                source_used = 'FYERS'
            
            if not nse_data:
                logging.error("Both sources failed!")
                result['status'] = 'failed'
                result['error'] = 'Both NSE and Fyers APIs failed'
                self._log_update(result)
                self._send_email(result)
                return result
            
            result['source_used'] = source_used
            
            # Step 2: Extract symbol list
            new_symbols = [s['symbol'] for s in nse_data]
            logging.info(f"📋 Fetched {len(new_symbols)} symbols from {source_used}")
            
            # Step 3: Get current list from DB
            current_doc = self.collection.find_one({"_id": "current_list"})
            current_symbols = []
            
            if current_doc:
                current_symbols = [
                    s['symbol'] for s in current_doc.get('symbols', [])
                    if s.get('status') == 'active'
                ]
            
            logging.info(f"📋 Current DB has {len(current_symbols)} active symbols")
            
            # Step 4: Find differences
            added = [s for s in new_symbols if s not in current_symbols]
            removed = [s for s in current_symbols if s not in new_symbols]
            
            logging.info(f"📊 Changes detected: +{len(added)} added, -{len(removed)} removed")
            
            # Step 5: Validate new symbols
            if added:
                validation_results = self.validate_all_symbols(added)
                
                valid_added = [s for s in added if validation_results.get(s, {}).get('valid', False)]
                invalid_added = [s for s in added if not validation_results.get(s, {}).get('valid', False)]
                
                result['symbols_added'] = valid_added
                result['validation_failed'] = invalid_added
                
                if invalid_added:
                    logging.warning(f"⚠️ {len(invalid_added)} new symbols failed validation")
            else:
                result['symbols_added'] = []
            
            # Step 6: Prepare symbols list for DB
            updated_symbols = []
            
            # Keep existing active symbols (excluding removed ones)
            for sym in current_symbols:
                if sym not in removed:
                    updated_symbols.append({
                        'symbol': sym,
                        'status': 'active',
                        'added_date': self._get_symbol_added_date(current_doc, sym),
                        'removed_date': None
                    })
            
            # Add new symbols
            for sym in result['symbols_added']:
                updated_symbols.append({
                    'symbol': sym,
                    'status': 'active',
                    'added_date': datetime.now(UTC),
                    'removed_date': None
                })
            
            # Mark removed symbols as pending_removal (don't delete)
            for sym in removed:
                updated_symbols.append({
                    'symbol': sym,
                    'status': 'pending_removal',
                    'added_date': self._get_symbol_added_date(current_doc, sym),
                    'removed_date': datetime.now(UTC)
                })
            
            result['symbols_removed'] = removed
            
            # Step 7: Update DB
            self.collection.update_one(
                {"_id": "current_list"},
                {
                    "$set": {
                        "symbols": updated_symbols,
                        "last_updated": datetime.now(UTC),
                        "source": source_used
                    }
                },
                upsert=True
            )
            
            logging.info(f"✅ Database updated with {len(updated_symbols)} symbols")
            
            # Step 8: Log update
            self._log_update(result)
            
            # Step 9: Send email
            self._send_email(result)
            result['email_sent'] = True
            
            logging.info("✨ NIFTY 50 update completed successfully")
            
        except Exception as e:
            logging.error(f"❌ Update failed: {e}", exc_info=True)
            result['status'] = 'failed'
            result['error'] = str(e)
            self._log_update(result)
            self._send_email(result)
        
        return result
    
    def _get_symbol_added_date(self, current_doc: Optional[Dict], symbol: str) -> datetime:
        """Get the date when a symbol was first added"""
        if not current_doc:
            return datetime.now(UTC)
        
        for s in current_doc.get('symbols', []):
            if s['symbol'] == symbol:
                return s.get('added_date', datetime.now(UTC))
        
        return datetime.now(UTC)
    
    def _log_update(self, result: Dict):
        """Log update to logs collection"""
        self.logs_collection.insert_one({
            'update_date': result.get('update_date', datetime.now(UTC)),
            'status': result['status'],
            'source_used': result.get('source_used'),
            'symbols_added': result.get('symbols_added', []),
            'symbols_removed': result.get('symbols_removed', []),
            'validation_failed': result.get('validation_failed', []),
            'error': result.get('error'),
            'email_sent': result.get('email_sent', False)
        })
    
    def _send_email(self, result: Dict):
        """Send email notification to admin"""
        try:
            from utils.email_notifications import send_nifty50_update_email
            
            # Get current positions for removed symbols (to notify user)
            positions_in_removed = []
            
            if result.get('symbols_removed'):
                # Check if user has positions in removed stocks
                try:
                    from connectors.fyers import FyersConnector
                    
                    if all([self.fyers_api_key, self.fyers_api_secret, self.fyers_access_token]):
                        connector = FyersConnector(
                            api_key=self.fyers_api_key,
                            api_secret=self.fyers_api_secret,
                            access_token=self.fyers_access_token
                        )
                        
                        holdings = connector.get_holdings()
                        
                        for removed_sym in result['symbols_removed']:
                            for holding in holdings:
                                if holding.get('symbol') == removed_sym:
                                    qty = holding.get('quantity', 0)
                                    if qty > 0:
                                        positions_in_removed.append({
                                            'symbol': removed_sym,
                                            'quantity': qty,
                                            'avg_price': holding.get('costPrice', 0)
                                        })
                except Exception as e:
                    logging.error(f"Failed to check positions: {e}")
            
            send_nifty50_update_email(
                to_email=self.admin_email,
                result=result,
                positions_in_removed=positions_in_removed
            )
            
            logging.info(f"📧 Email sent to {self.admin_email}")
            
        except Exception as e:
            logging.error(f"Failed to send email: {e}")
    
    def add_symbol(self, symbol: str, company_name: str = None) -> Dict:
        """
        Manually add a symbol (admin function)
        
        Returns: {'success': bool, 'message': str}
        """
        try:
            # Validate symbol first
            is_valid, price = self.validate_symbol(symbol)
            
            if not is_valid:
                return {
                    'success': False,
                    'message': f'Symbol {symbol} is not valid (no price found)'
                }
            
            # Check if already exists
            current = self.collection.find_one({"_id": "current_list"})
            
            if current:
                for s in current.get('symbols', []):
                    if s['symbol'] == symbol and s['status'] == 'active':
                        return {
                            'success': False,
                            'message': f'Symbol {symbol} already exists'
                        }
            
            # Add symbol
            self.collection.update_one(
                {"_id": "current_list"},
                {
                    "$push": {
                        "symbols": {
                            "symbol": symbol,
                            "company_name": company_name or symbol.replace('NSE:', '').replace('-EQ', ''),
                            "status": "active",
                            "added_date": datetime.now(UTC),
                            "removed_date": None,
                            "source": "manual"
                        }
                    },
                    "$set": {
                        "last_updated": datetime.now(UTC)
                    }
                }
            )
            
            logging.info(f"✅ Manually added symbol: {symbol}")
            
            return {
                'success': True,
                'message': f'Symbol {symbol} added successfully'
            }
            
        except Exception as e:
            logging.error(f"Failed to add symbol: {e}")
            return {
                'success': False,
                'message': str(e)
            }
    
    def remove_symbol(self, symbol: str) -> Dict:
        """
        Manually remove a symbol (admin function)
        Marks as pending_removal instead of deleting
        
        Returns: {'success': bool, 'message': str}
        """
        try:
            current = self.collection.find_one({"_id": "current_list"})
            
            if not current:
                return {
                    'success': False,
                    'message': 'No NIFTY 50 list found'
                }
            
            # Find and mark as pending_removal
            found = False
            updated_symbols = []
            
            for s in current.get('symbols', []):
                if s['symbol'] == symbol:
                    if s['status'] == 'pending_removal':
                        return {
                            'success': False,
                            'message': f'Symbol {symbol} is already marked for removal'
                        }
                    
                    s['status'] = 'pending_removal'
                    s['removed_date'] = datetime.now(UTC)
                    found = True
                
                updated_symbols.append(s)
            
            if not found:
                return {
                    'success': False,
                    'message': f'Symbol {symbol} not found in list'
                }
            
            self.collection.update_one(
                {"_id": "current_list"},
                {
                    "$set": {
                        "symbols": updated_symbols,
                        "last_updated": datetime.now(UTC)
                    }
                }
            )
            
            logging.info(f"✅ Marked symbol for removal: {symbol}")
            
            return {
                'success': True,
                'message': f'Symbol {symbol} marked for removal'
            }
            
        except Exception as e:
            logging.error(f"Failed to remove symbol: {e}")
            return {
                'success': False,
                'message': str(e)
            }
    
    def is_symbol_in_nifty50(self, symbol: str) -> bool:
        """
        Check if a symbol is currently in NIFTY 50 (active status)
        
        Returns: True if symbol is in active NIFTY 50 list
        """
        doc = self.collection.find_one({"_id": "current_list"})
        
        if not doc:
            # If no list exists, use hardcoded fallback
            return symbol in self._get_hardcoded_symbols()
        
        for s in doc.get('symbols', []):
            if s['symbol'] == symbol and s.get('status') == 'active':
                return True
        
        return False


def main():
    """Main function for manual testing"""
    logging.info("="*60)
    logging.info("NIFTY 50 Manager - Manual Test")
    logging.info("="*60)
    
    manager = Nifty50Manager()
    
    # Test update
    result = manager.update_constituents(force=True)
    
    logging.info("\n" + "="*60)
    logging.info("Update Result:")
    logging.info(f"  Status: {result['status']}")
    logging.info(f"  Source: {result.get('source_used')}")
    logging.info(f"  Added: {len(result.get('symbols_added', []))}")
    logging.info(f"  Removed: {len(result.get('symbols_removed', []))}")
    logging.info(f"  Email Sent: {result.get('email_sent', False)}")
    if result.get('error'):
        logging.info(f"  Error: {result['error']}")
    logging.info("="*60)


if __name__ == "__main__":
    main()
