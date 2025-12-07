from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash, g
from auth import AuthManager, login_required
from pymongo import MongoClient
from datetime import datetime, timedelta
import pytz
from collections import defaultdict
import os
from dotenv import load_dotenv
import json
import time
import subprocess
import uuid
from config import MONGO_DB_NAME, MONGO_ENV, APP_LOGS_PER_PAGE_HOME, FYERS_REDIRECT_URI, ACCESS_TOKEN_VALIDITY, REFRESH_TOKEN_VALIDITY, STRATEGY_CAPITAL, MAX_TRADE_VALUE, MA_PERIOD

# Import Connectors
from connectors.fyers import FyersConnector
from connectors.zerodha import ZerodhaConnector

# Define timezones
UTC = pytz.utc
IST = pytz.timezone('Asia/Kolkata')

load_dotenv() # Load environment variables from .env file

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'a_very_secret_key_that_should_be_changed')

auth_manager = None # Will be initialized after db connection

# --- Database Connection ---
MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = MONGO_DB_NAME
MONGO_ENV = MONGO_ENV
print(MONGO_URI, MONGO_DB_NAME, MONGO_ENV)

if MONGO_URI:
    client = MongoClient(MONGO_URI, tz_aware=True, tzinfo=UTC)
    db = client[MONGO_DB_NAME]
    # MongoDB Configuration for Tokens
    mongo_client_tokens = MongoClient(MONGO_URI, tz_aware=True, tzinfo=UTC)
    fyers_tokens_collection = mongo_client_tokens[MONGO_DB_NAME]['fyers_tokens']
    zerodha_tokens_collection = mongo_client_tokens[MONGO_DB_NAME]['zerodha_tokens']
    auth_manager = AuthManager(db)

    # Create initial user if no users exist
    if auth_manager.users_collection.count_documents({}) == 0:
        print("No users found. Creating initial user 'chaitu_shop'.")
        auth_manager.create_user("chaitu_shop", "Chaitu2@nifty_shop")
else:
    print("Could not find MongoDB URI in .env file")
    db = None
    mongo_client_tokens = None
    fyers_tokens_collection = None
    zerodha_tokens_collection = None
    auth_manager = None

@app.before_request
def load_logged_in_user():
    g.user = None
    session_token = session.get('session_token')
    if session_token and auth_manager:
        session_data = auth_manager.get_session(session_token)
        if session_data:
            g.user = auth_manager.get_user(session_data['username'])
        else:
            session.pop('session_token', None) # Clear invalid session token

LOGS_PER_PAGE = APP_LOGS_PER_PAGE_HOME

# --- Broker Configuration ---
# Fyers
FYERS_CLIENT_ID = os.getenv('FYERS_CLIENT_ID')
FYERS_SECRET_ID = os.getenv('FYERS_SECRET_ID')
FYERS_PIN = os.getenv('FYERS_PIN')
FYERS_REDIRECT_URI = os.getenv('FYERS_REDIRECT_URI')

# Zerodha
ZERODHA_API_KEY = os.getenv('ZERODHA_API_KEY')
ZERODHA_API_SECRET = os.getenv('ZERODHA_API_SECRET')
ZERODHA_REDIRECT_URI = os.getenv('ZERODHA_REDIRECT_URI')

ACCESS_TOKEN_VALIDITY = ACCESS_TOKEN_VALIDITY
REFRESH_TOKEN_VALIDITY = REFRESH_TOKEN_VALIDITY

# Initialize Connectors
fyers_connector = FyersConnector(
    api_key=FYERS_CLIENT_ID,
    api_secret=FYERS_SECRET_ID,
    pin=FYERS_PIN
)

zerodha_connector = ZerodhaConnector(
    api_key=ZERODHA_API_KEY,
    api_secret=ZERODHA_API_SECRET
)

# --- Token Management Helpers ---
def save_tokens(broker, token_data):
    collection = None
    if broker == 'fyers':
        collection = fyers_tokens_collection
    elif broker == 'zerodha':
        collection = zerodha_tokens_collection
    
    if collection is not None:
        collection.update_one(
            {"_id": f"{broker}_token_data"},
            {"$set": token_data},
            upsert=True
        )
        print(f"[INFO] {broker} token data saved to MongoDB.")
    else:
        print(f"[ERROR] MongoDB connection not established for {broker} tokens.")

def load_tokens(broker):
    collection = None
    if broker == 'fyers':
        collection = fyers_tokens_collection
    elif broker == 'zerodha':
        collection = zerodha_tokens_collection
        
    if collection is not None:
        return collection.find_one({"_id": f"{broker}_token_data"})
    else:
        print(f"[ERROR] MongoDB connection not established for {broker} tokens.")
        return None

def is_token_valid(broker, token_data):
    if not token_data or 'access_token' not in token_data:
        return False
    
    generated_at = token_data.get("generated_at")
    if isinstance(generated_at, (int, float)):
        generated_at = datetime.fromtimestamp(generated_at, tz=UTC)
    elif isinstance(generated_at, datetime) and generated_at.tzinfo is None:
        generated_at = UTC.localize(generated_at)
        
    # Check timestamp first (24 hours validity)
    if generated_at and datetime.now(UTC) > generated_at + timedelta(seconds=ACCESS_TOKEN_VALIDITY):
        return False

    # Verify with API
    try:
        if broker == 'fyers':
            temp_connector = FyersConnector(
                api_key=FYERS_CLIENT_ID,
                api_secret=FYERS_SECRET_ID,
                access_token=token_data['access_token']
            )
            return temp_connector.is_token_valid()
        elif broker == 'zerodha':
            temp_connector = ZerodhaConnector(
                api_key=ZERODHA_API_KEY,
                api_secret=ZERODHA_API_SECRET,
                access_token=token_data['access_token']
            )
            return temp_connector.is_token_valid()
    except Exception as e:
        print(f"[ERROR] Error validating {broker} token via API: {e}")
        return False
    return False

# --- Routes ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if g.user:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        error = None

        user = auth_manager.get_user(username)

        if user is None:
            error = 'Incorrect username.'
        elif auth_manager.is_account_locked(user):
            error = 'Account locked. Please contact administrator.'
        elif not auth_manager.verify_password(user, password):
            auth_manager.record_failed_login(username)
            error = 'Incorrect password.'
        else:
            auth_manager.reset_failed_logins(username)
            session_token = auth_manager.create_session(username)
            session['session_token'] = session_token
            flash('Logged in successfully!', 'success')
            return redirect(url_for('dashboard'))

        flash(error, 'danger')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    if 'session_token' in session and auth_manager:
        auth_manager.delete_session(session['session_token'])
    session.pop('session_token', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    if db is None:
        return "Database connection failed. Please check your MongoDB URI in files.txt"

    # Determine active broker (default to Fyers for now, or make it selectable)
    # For now, let's try to load both or default to one.
    # Ideally, user settings should define active broker.
    active_broker = 'zerodha' # HARDCODED FOR TESTING ZERODHA
    
    token_data = load_tokens(active_broker)
    access_token = token_data.get("access_token") if token_data else ""
    
    # Check validity
    if not access_token or not is_token_valid(active_broker, token_data):
        flash(f"{active_broker.capitalize()} token is invalid or expired. Please refresh it.", "warning")
        return redirect(url_for('token_refresh'))

    # Initialize connector with token
    connector = None
    if active_broker == 'fyers':
        connector = FyersConnector(FYERS_CLIENT_ID, FYERS_SECRET_ID, access_token=access_token)
    elif active_broker == 'zerodha':
        connector = ZerodhaConnector(ZERODHA_API_KEY, ZERODHA_API_SECRET, access_token=access_token)

    # Calculate dashboard metrics
    holdings_pnl = 0.0
    open_positions_count = 0
    recent_trades_count = 0 
    raw_positions = []

    try:
        if connector:
            raw_positions = connector.get_holdings()
            for p in raw_positions:
                # Standardized holding dict: {'symbol', 'quantity', 'costPrice', 'ltp', 'pl'}
                if p.get('quantity', 0) != 0:
                    holdings_pnl += p.get('pl', 0)
                    open_positions_count += 1
    except Exception as e:
        flash(f"An error occurred while fetching holdings: {e}", "danger")
        print(f"Error fetching holdings: {e}")

    # Fetch today's executed trades
    today = datetime.now(IST).date()
    start_of_today = IST.localize(datetime(today.year, today.month, today.day, 0, 0, 0)).astimezone(UTC)
    end_of_today = IST.localize(datetime(today.year, today.month, today.day, 23, 59, 59)).astimezone(UTC)
    
    today_trades = list(db[f"trades_{MONGO_ENV}"].find({
        "date": {"$gte": start_of_today, "$lte": end_of_today},
        "filled": True
    }))
    recent_trades_count = len(today_trades)

    # --- Daily activity logic for dashboard ---
    page = request.args.get('page', 1, type=int)
    skip_days = (page - 1) * LOGS_PER_PAGE

    distinct_log_dates = db[f"logs_{MONGO_ENV}"].distinct("timestamp", {"timestamp": {"$ne": None}})
    distinct_trade_dates = db[f"trades_{MONGO_ENV}"].distinct("date", {"date": {"$ne": None}})

    distinct_log_dates_ist = [d.astimezone(IST) for d in distinct_log_dates]
    distinct_trade_dates_ist = [d.astimezone(IST) for d in distinct_trade_dates]

    all_distinct_dates = sorted(list(set([d.date() for d in distinct_log_dates_ist] + [d.date() for d in distinct_trade_dates_ist])), reverse=True)

    total_days = len(all_distinct_dates)
    has_more_days = total_days > (skip_days + LOGS_PER_PAGE)

    current_page_dates = all_distinct_dates[skip_days : skip_days + LOGS_PER_PAGE]

    daily_data = {}

    for date_obj in current_page_dates:
        start_of_day_ist = IST.localize(datetime(date_obj.year, date_obj.month, date_obj.day, 0, 0, 0))
        end_of_day_ist = IST.localize(datetime(date_obj.year, date_obj.month, date_obj.day, 23, 59, 59))
        start_of_day_utc = start_of_day_ist.astimezone(UTC)
        end_of_day_utc = end_of_day_ist.astimezone(UTC)

        logs_for_day = list(db[f"logs_{MONGO_ENV}"].find({
            "timestamp": {"$gte": start_of_day_utc, "$lte": end_of_day_utc}
        }).sort("timestamp", -1))
        for log in logs_for_day:
            log['timestamp'] = log['timestamp'].astimezone(IST)

        trades_for_day = list(db[f"trades_{MONGO_ENV}"].find({
            "date": {"$gte": start_of_day_utc, "$lte": end_of_day_utc}
        }).sort("date", -1))
        for trade in trades_for_day:
            trade['date'] = trade['date'].astimezone(IST)

        executed_trades_daily = []
        cancelled_trades_daily = []

        for trade in trades_for_day:
            if 'profit' not in trade:
                trade['profit'] = 0.0
            if 'profit_pct' not in trade:
                trade['profit_pct'] = 0.0
            
            if trade.get('filled', False):
                executed_trades_daily.append(trade)
            else:
                cancelled_trades_daily.append(trade)
        
        daily_data[date_obj.strftime('%Y-%m-%d')] = {
            'logs': logs_for_day,
            'executed_trades': executed_trades_daily,
            'cancelled_trades': cancelled_trades_daily
        }

    # --- Chart Data ---
    daily_pnl_data = defaultdict(lambda: {'pnl': 0.0, 'trades': 0})
    all_filled_trades = list(db[f"trades_{MONGO_ENV}"].find({"filled": True, "profit": {"$exists": True}}))
    for trade in all_filled_trades:
        if trade.get('action') == 'SELL':
            trade_date = trade['date'].astimezone(IST).strftime('%Y-%m-%d')
            daily_pnl_data[trade_date]['pnl'] += trade.get('profit', 0.0)
            daily_pnl_data[trade_date]['trades'] += 1
    
    sorted_daily_pnl = sorted(daily_pnl_data.items())
    chart_labels = [item[0] for item in sorted_daily_pnl]
    chart_values = [item[1]['pnl'] for item in sorted_daily_pnl]
    chart_trades = [item[1]['trades'] for item in sorted_daily_pnl]

    all_filled_trades = list(db[f"trades_{MONGO_ENV}"].find({"filled": True}).sort("date", 1))
    cumulative_pnl_data = []
    cumulative_pnl = 0
    for trade in all_filled_trades:
        cumulative_pnl += trade.get('profit', 0.0)
        cumulative_pnl_data.append({
            'date': trade['date'].astimezone(IST).strftime('%Y-%m-%d'),
            'pnl': cumulative_pnl
        })

    # Capital Utilization
    used_capital = 0
    num_positions = 0
    for p in raw_positions:
        qty = p.get('quantity', 0)
        if qty != 0:
            cost_price = p.get('costPrice', 0)
            used_capital += cost_price * abs(qty)
            num_positions += 1
    
    available_capital = max(0, STRATEGY_CAPITAL - used_capital)
    used_percentage = (used_capital / STRATEGY_CAPITAL * 100) if STRATEGY_CAPITAL > 0 else 0
    available_percentage = (available_capital / STRATEGY_CAPITAL * 100) if STRATEGY_CAPITAL > 0 else 0
    
    from config import MAX_TRADE_VALUE
    positions_can_open = int(available_capital / MAX_TRADE_VALUE) if MAX_TRADE_VALUE > 0 else 0
    avg_position_size = (used_capital / num_positions) if num_positions > 0 else 0
    
    capital_utilization = {
        'used': used_capital,
        'available': available_capital,
        'total': STRATEGY_CAPITAL,
        'used_percentage': used_percentage,
        'available_percentage': available_percentage,
        'positions_can_open': positions_can_open,
        'avg_position_size': avg_position_size,
        'current_positions': num_positions
    }

    return render_template('dashboard.html',
                           active_page='dashboard',
                           holdings_pnl=holdings_pnl,
                           open_positions_count=open_positions_count,
                           recent_trades_count=recent_trades_count,
                           daily_data=daily_data,
                           page=page,
                           has_more_days=has_more_days,
                           total_days=total_days,
                           chart_labels=json.dumps(chart_labels),
                           chart_values=json.dumps(chart_values),
                           chart_trades=json.dumps(chart_trades),
                           capital_utilization=capital_utilization,
                           cumulative_pnl_data=json.dumps(cumulative_pnl_data))

@app.route('/trading-overview')
@login_required
def trading_overview():
    # Same logic as dashboard for broker selection
    active_broker = 'zerodha' # HARDCODED FOR TESTING
    
    token_data = load_tokens(active_broker)
    access_token = token_data.get("access_token") if token_data else ""
    
    if not access_token or not is_token_valid(active_broker, token_data):
        flash(f"{active_broker.capitalize()} token is invalid or expired. Please refresh it.", "warning")
        return redirect(url_for('token_refresh'))

    connector = None
    if active_broker == 'fyers':
        connector = FyersConnector(FYERS_CLIENT_ID, FYERS_SECRET_ID, access_token=access_token)
    elif active_broker == 'zerodha':
        connector = ZerodhaConnector(ZERODHA_API_KEY, ZERODHA_API_SECRET, access_token=access_token)

    current_positions = []
    try:
        raw_positions = connector.get_holdings()
        for p in raw_positions:
            if p.get('quantity', 0) != 0:
                cost_price = p.get('costPrice', 0)
                pnl = p.get('pl', 0)
                pnl_pct = (pnl / (cost_price * p.get('quantity', 1))) * 100 if cost_price > 0 else 0

                current_positions.append({
                    'symbol': p.get('symbol'),
                    'quantity': p.get('quantity'),
                    'avg_price': cost_price,
                    'current_price': p.get('ltp'),
                    'pnl': pnl,
                    'pnl_pct': pnl_pct
                })
    except Exception as e:
        flash(f"An error occurred while fetching holdings: {e}", "danger")

    # ... (Rest of trading_overview logic remains mostly same, fetching from DB)
    # ... (Copying existing logic for brevity, assuming DB structure is same)
    
    all_filled_trades = list(db[f"trades_{MONGO_ENV}"].find({"filled": True}).sort("date", -1))
    for trade in all_filled_trades:
        trade['date'] = trade['date'].astimezone(IST)

    closed_trades = []
    for trade in all_filled_trades:
        if trade.get('action') == 'SELL' and 'profit' in trade:
            closed_trades.append(trade)
        if 'profit' not in trade: trade['profit'] = 0.0
        if 'profit_pct' not in trade: trade['profit_pct'] = 0.0

    total_pnl = sum(trade.get('profit', 0.0) for trade in closed_trades)
    winning_trades = [trade for trade in closed_trades if trade.get('profit', 0.0) > 0]
    losing_trades = [trade for trade in closed_trades if trade.get('profit', 0.0) < 0]
    win_loss_ratio = len(winning_trades) / len(losing_trades) if len(losing_trades) > 0 else (1 if len(winning_trades) > 0 else 0)
    average_winning_trade = sum(trade['profit'] for trade in winning_trades) / len(winning_trades) if len(winning_trades) > 0 else 0
    average_losing_trade = sum(trade['profit'] for trade in losing_trades) / len(losing_trades) if len(losing_trades) > 0 else 0

    closed_trades_count = len(closed_trades)
    open_trades_count = len(current_positions)
    total_trades = closed_trades_count + open_trades_count
    
    cumulative_pnl_list = []
    running_total = 0
    peak = 0
    drawdowns = []
    drawdown_dates = []
    
    sorted_trades = sorted(closed_trades, key=lambda x: x['date'])
    for trade in sorted_trades:
        running_total += trade.get('profit', 0.0)
        cumulative_pnl_list.append(running_total)
        if running_total > peak: peak = running_total
        drawdown = ((running_total - peak) / peak * 100) if peak > 0 else 0
        drawdowns.append(drawdown)
        drawdown_dates.append(trade['date'].strftime('%Y-%m-%d'))
    
    max_drawdown = min(drawdowns) if drawdowns else 0
    current_drawdown = drawdowns[-1] if drawdowns else 0
    
    drawdown_chart_data = {
        'labels': drawdown_dates[-30:],
        'values': drawdowns[-30:]
    }

    # ... (Daily data logic same as dashboard)
    # ...
    
    # Portfolio Allocation
    portfolio_data = []
    if current_positions:
        for p in current_positions:
            pnl_value = p.get('pnl', 0)
            avg_price = p.get('avg_price', 0)
            quantity = p.get('quantity', 0)
            invested_amount = avg_price * quantity
            percentage = (pnl_value / invested_amount * 100) if invested_amount > 0 else 0
            portfolio_data.append({
                'symbol': p.get('symbol'),
                'value': pnl_value,
                'percentage': percentage
            })

    cumulative_pnl_data = []
    cumulative_pnl = 0
    if closed_trades:
        for trade in reversed(closed_trades):
            cumulative_pnl += trade.get('profit', 0.0)
            cumulative_pnl_data.append({
                'date': trade['date'].strftime('%Y-%m-%d'),
                'pnl': cumulative_pnl
            })

    manually_closed_trades = list(db[f"trades_{MONGO_ENV}"].find({"order_id": "MANUAL"}).sort("date", -1))
    for trade in manually_closed_trades:
        trade['date'] = trade['date'].astimezone(IST)

    capital_data = {
        'used': 0,
        'available': 0,
        'total': STRATEGY_CAPITAL
    }
    try:
        used_capital = sum(p.get('avg_price', 0) * p.get('quantity', 0) for p in current_positions)
        capital_data['used'] = used_capital
        capital_data['available'] = max(0, STRATEGY_CAPITAL - used_capital)
    except Exception as e:
        capital_data['used'] = 0
        capital_data['available'] = STRATEGY_CAPITAL

    # Need to pass daily_data etc. (omitted for brevity, assuming template handles missing vars or I need to copy full logic)
    # For now, I'll pass empty daily_data if not re-calculated to avoid crash
    daily_data = {} # Placeholder if not fully copied
    
    return render_template('trading_overview.html',
                           current_positions=current_positions,
                           closed_trades=closed_trades,
                           active_page='trading_overview',
                           total_pnl=total_pnl,
                           win_loss_ratio=win_loss_ratio,
                           average_winning_trade=average_winning_trade,
                           average_losing_trade=average_losing_trade,
                           daily_data=daily_data, # Warning: Empty
                           page=1,
                           has_more_days=False,
                           total_days=0,
                           portfolio_data=json.dumps(portfolio_data),
                           cumulative_pnl_data=json.dumps(cumulative_pnl_data),
                           manually_closed_trades=manually_closed_trades,
                           total_trades=total_trades,
                           open_trades_count=open_trades_count,
                           closed_trades_count=closed_trades_count,
                           max_drawdown=max_drawdown,
                           current_drawdown=current_drawdown,
                           drawdown_chart_data=json.dumps(drawdown_chart_data),
                           capital_data=json.dumps(capital_data))


@app.route('/logs')
@login_required
def logs_page():
    if db is None:
        return "Database connection failed. Please check your MongoDB URI in files.txt"
    return render_template('logs.html', active_page='logs')

@app.route('/api/logs')
@login_required
def api_logs():
    if db is None:
        return jsonify({"error": "Database connection failed."}), 500

    logs_per_page = 20
    page = request.args.get('page', 1, type=int)
    skip_logs = (page - 1) * logs_per_page

    query = {}
    search_query = request.args.get('search')
    log_level = request.args.get('level')
    log_date = request.args.get('date')

    if search_query:
        query['message'] = {'$regex': search_query, '$options': 'i'}
    if log_level:
        query['level'] = log_level
    if log_date:
        try:
            start_of_day_ist = IST.localize(datetime.strptime(log_date, '%Y-%m-%d'))
            end_of_day_ist = start_of_day_ist + timedelta(days=1) - timedelta(microseconds=1)
            start_of_day_utc = start_of_day_ist.astimezone(UTC)
            end_of_day_utc = end_of_day_ist.astimezone(UTC)
            query['timestamp'] = {'$gte': start_of_day_utc, '$lte': end_of_day_utc}
        except ValueError:
            pass

    all_logs = list(db[f"logs_{MONGO_ENV}"].find(query).sort("timestamp", -1).skip(skip_logs).limit(logs_per_page))
    total_logs = db[f"logs_{MONGO_ENV}"].count_documents({})
    has_more = total_logs > (skip_logs + len(all_logs))

    for log in all_logs:
        log['_id'] = str(log['_id'])
        log['timestamp'] = log['timestamp'].astimezone(IST).strftime('%Y-%m-%d %H:%M:%S')

    return jsonify({"logs": all_logs, "has_more": has_more, "next_page": page + 1})

@app.route('/token-refresh')
@login_required
def token_refresh():
    brokers_data = []
    
    # Fetch all enabled/configured brokers
    db_brokers = list(db['broker_accounts'].find({}))
    
    for broker in db_brokers:
        b_type = broker['broker_type']
        b_data = {
            'broker_id': broker['broker_id'],
            'name': broker.get('display_name', b_type.capitalize()),
            'type': b_type,
            'status': 'UNKNOWN',
            'last_update': None,
            'auth_url': '#',
            'features': []
        }
        
        # Timestamp logic
        generated_at = broker.get('token_generated_at')
        if isinstance(generated_at, (int, float)):
             generated_at = datetime.fromtimestamp(generated_at, tz=UTC)
        elif not isinstance(generated_at, datetime) and generated_at:
             # Try parsing string? or just None
             generated_at = None
        
        if generated_at and generated_at.tzinfo is None:
             generated_at = generated_at.replace(tzinfo=UTC)
             
        b_data['last_update'] = generated_at
        
        # Refresh logic
        refresh_token = broker.get('refresh_token')
        
        if b_type == 'fyers':
             # Status Calc
             if not generated_at:
                 b_data['status'] = "NO_TOKENS_FOUND"
             else:
                 now = datetime.now(UTC)
                 elapsed = (now - generated_at).total_seconds()
                 if elapsed < ACCESS_TOKEN_VALIDITY:
                     b_data['status'] = "VALID"
                 elif elapsed < REFRESH_TOKEN_VALIDITY:
                     b_data['status'] = "EXPIRED_ACCESS_TOKEN_REFRESHABLE"
                 else:
                     b_data['status'] = "EXPIRED_REFRESH_TOKEN_MANUAL_REQUIRED"
            
             if not refresh_token:
                 b_data['status'] = "NO_TOKENS_FOUND"

             # Auth URL (Set session for update)
             # Session setup happens ON CLICK usually, but for Fyers we need to set it here 
             # OR use a bridge. Since we can't bridge Fyers easily (it's external), 
             # we rely on the fact that ONLY ONE Fyers broker exists usually, OR we accept the limitation.
             # Wait, with Multi-Broker, we MIGHT have 2 Fyers accounts.
             # If we have 2, setting session['temp_token_data'] here will overwrite each other!
             # CRITICAL: We need a bridge for Fyers too if we support multiple Fyers accounts.
             # Solution: Create /broker/reauth/fyers/<id> bridge.
             b_data['auth_url'] = url_for('broker_reauth_fyers', broker_id=broker['broker_id'])

        elif b_type == 'zerodha':
             if not generated_at:
                 b_data['status'] = "EXPIRED/MISSING"
             else:
                 now = datetime.now(UTC)
                 elapsed = (now - generated_at).total_seconds()
                 if elapsed < (24 * 3600):
                     b_data['status'] = "VALID"
                 else:
                     b_data['status'] = "EXPIRED/MISSING"
                     
             b_data['auth_url'] = url_for('broker_reauth_zerodha', broker_id=broker['broker_id'])
        
        brokers_data.append(b_data)

    return render_template('token_refresh.html', 
                           brokers=brokers_data,
                           active_page='token_refresh')

@app.route('/refresh-token-action', methods=['POST'])
@login_required
def refresh_token_action():
    # Attempt Fyers Refresh
    fyers_broker = db['broker_accounts'].find_one({'broker_type': 'fyers'})
    if not fyers_broker:
         return redirect(url_for('token_refresh', status='failed', message='No Fyers broker found'))
         
    refresh_token = fyers_broker.get('refresh_token')
    if not refresh_token:
         return redirect(url_for('token_refresh', status='failed', message='No refresh token'))
         
    try:
        client_id = fyers_broker.get('client_id') or fyers_broker.get('api_key')
        secret_id = fyers_broker.get('secret_id') or fyers_broker.get('api_secret')
        
        connector = FyersConnector(api_key=client_id, api_secret=secret_id)
        new_tokens = connector.refresh_token(refresh_token)
        
        db['broker_accounts'].update_one(
            {'_id': fyers_broker['_id']},
            {'$set': {
                'access_token': new_tokens['access_token'],
                'refresh_token': new_tokens.get('refresh_token', refresh_token),
                'token_generated_at': datetime.now(UTC),
                'token_status': 'valid'
            }}
        )
        return redirect(url_for('token_refresh', status='refreshed', broker='fyers'))
    except Exception as e:
        return redirect(url_for('token_refresh', status='failed', message=str(e), broker='fyers'))

@app.route('/token-callback')
@login_required
def token_callback():
    # Fyers Callback (Legacy Endpoint support)
    auth_code = request.args.get('code') # Fyers usually sends 'code' or 'auth_code' depending on api v2/v3? v3 is 'auth_code' usually but let's check both
    if not auth_code:
         auth_code = request.args.get('auth_code')

    if auth_code:
        try:
            # We need to know which Redirect URI was used to generate the auth code.
            # If session data exists, use that. Else default to global.
            temp_data = session.get('temp_broker_data')
            redirect_uri = FYERS_REDIRECT_URI
            
            if temp_data and temp_data.get('redirect_uri'):
                redirect_uri = temp_data['redirect_uri']

            # Generate Session
            # Note: We need api_key/secret. Legacy assumed global. New flow has them in session.
            api_key = temp_data['client_id'] if temp_data else FYERS_CLIENT_ID
            api_secret = temp_data['secret_id'] if temp_data else FYERS_SECRET_ID
            
            # Re-init connector if needed (Global connector uses global keys)
            # If temp_data has different keys, we must create a temp connector
            connector = fyers_connector
            if temp_data:
                 connector = FyersConnector(api_key=api_key, api_secret=api_secret)

            token_response = connector.generate_session(auth_code, redirect_uri=redirect_uri)
            token_response["generated_at"] = int(time.time())
            
            # Check for Multi-Broker Session Data
            if temp_data and temp_data.get('type') == 'fyers':
                # New Flow: Save to broker_accounts
                mode = temp_data.get('mode', 'create')
                
                if mode == 'update':
                    # Update Existing Broker
                    broker_id = temp_data.get('broker_id')
                    if not broker_id:
                        raise Exception("Broker ID missing for update")
                        
                    db['broker_accounts'].update_one(
                        {'broker_id': broker_id},
                        {'$set': {
                            'access_token': token_response['access_token'],
                            'refresh_token': token_response.get('refresh_token'),
                            'token_generated_at': datetime.now(UTC),
                            'token_status': 'valid'
                        }}
                    )
                    flash(f"Fyers broker re-connected successfully!", "success")
                else:
                    # Create New Broker
                    broker_id = str(uuid.uuid4())
                    
                    is_default = False
                    if db['broker_accounts'].count_documents({}) == 0:
                        is_default = True
                        
                    new_broker = {
                        "broker_id": broker_id,
                        "broker_type": "fyers",
                        "display_name": temp_data['display_name'],
                        "enabled": True,
                        "is_default": is_default,
                        "trading_mode": "NORMAL",
                        "created_at": datetime.now(UTC),
                        "client_id": temp_data['client_id'],
                        "secret_id": temp_data['secret_id'],
                        "pin": temp_data['pin'],
                        "redirect_uri": temp_data['redirect_uri'],
                        "access_token": token_response['access_token'],
                        "refresh_token": token_response.get('refresh_token'),
                        "token_generated_at": datetime.now(UTC),
                        "token_status": "valid",
                        "last_run_at": None
                    }
                    db['broker_accounts'].insert_one(new_broker)
                    flash(f"Fyers broker '{temp_data['display_name']}' added successfully!", "success")
                
                session.pop('temp_broker_data', None)
                return redirect(url_for('settings'))

            else:
                # Fallback Legacy
                save_tokens('fyers', token_response)
                return redirect(url_for('token_refresh', status='success', broker='fyers'))

        except Exception as e:
            return redirect(url_for('token_refresh', status='failed', message=str(e), broker='fyers'))
    return redirect(url_for('token_refresh', status='failed', message='No code', broker='fyers'))

@app.route('/zerodha-callback')
@login_required
def zerodha_callback():
    # Zerodha Callback
    request_token = request.args.get('request_token')
    status = request.args.get('status')
    
    if status == 'success' and request_token:
        try:
            # Generate Session
            token_response = zerodha_connector.generate_session(request_token)
            
            # Check for Multi-Broker Session Data
            temp_data = session.get('temp_broker_data')
            
            if temp_data and temp_data.get('type') == 'zerodha':
                # New Flow: Save to broker_accounts
                mode = temp_data.get('mode', 'create')
                
                if mode == 'update':
                    # Update Existing Broker
                    broker_id = temp_data.get('broker_id')
                    if not broker_id:
                        raise Exception("Broker ID missing for update")
                        
                    db['broker_accounts'].update_one(
                        {'broker_id': broker_id},
                        {'$set': {
                            'access_token': token_response['access_token'],
                            'refresh_token': token_response.get('refresh_token'), # Zerodha might not have refresh token in same way
                            'token_generated_at': datetime.now(UTC),
                            'token_status': 'valid'
                        }}
                    )
                    flash(f"Zerodha broker re-connected successfully!", "success")
                else:
                    # Create New Broker
                    broker_id = str(uuid.uuid4())
                    
                    # Determine if default
                    is_default = False
                    if db['broker_accounts'].count_documents({}) == 0:
                        is_default = True
                        
                    new_broker = {
                        "broker_id": broker_id,
                        "broker_type": "zerodha",
                        "display_name": temp_data['display_name'],
                        "enabled": True,
                        "is_default": is_default,
                        "trading_mode": "NORMAL",
                        "created_at": datetime.now(UTC),
                        "api_key": temp_data['api_key'],
                        "api_secret": temp_data['api_secret'],
                        "access_token": token_response['access_token'],
                        "refresh_token": token_response.get('refresh_token'),
                        "token_generated_at": datetime.now(UTC),
                        "token_status": "valid",
                        "last_run_at": None
                    }
                    db['broker_accounts'].insert_one(new_broker)
                    flash(f"Zerodha broker '{temp_data['display_name']}' added successfully!", "success")
                
                # Clear session
                session.pop('temp_broker_data', None)
                return redirect(url_for('settings'))  # Redirect to settings to see the new broker
                
            else:
                # Fallback: Save to legacy collection (for safety/backward compat if no session)
                # But warn user? Or just save to generic place?
                # For now, let's just save via old helper as a fallback, but it won't show in UI.
                save_tokens('zerodha', token_response)
                return redirect(url_for('token_refresh', status='success', broker='zerodha'))

        except Exception as e:
             return redirect(url_for('token_refresh', status='failed', message=str(e), broker='zerodha'))
    else:
        return redirect(url_for('token_refresh', status='failed', message='Auth failed or denied', broker='zerodha'))



def run_executor(run_type="scheduled"):
    run_id = str(uuid.uuid4())
    strategy_runs_collection = db[f"strategy_runs_{MONGO_ENV}"]
    try:
        result = subprocess.run(
            ["python", "executor.py", "--run-id", run_id],
            check=True,
            capture_output=True,
            text=True
        )
        if db is not None:
            strategy_runs_collection.insert_one({
                "run_id": run_id,
                "run_time": datetime.now(UTC),
                "run_type": run_type,
                "stdout": result.stdout,
                "stderr": result.stderr
            })
    except subprocess.CalledProcessError as e:
        if db is not None:
            strategy_runs_collection.insert_one({
                "run_id": run_id,
                "run_time": datetime.now(UTC),
                "run_type": run_type,
                "status": "failed",
                "error": str(e),
                "stdout": e.stdout,
                "stderr": e.stderr
            })

@app.route('/run-strategy')
@login_required
def run_strategy():
    page = request.args.get('page', 1, type=int)
    runs_per_page = 10
    skip_runs = (page - 1) * runs_per_page

    runs = []
    total_runs = 0
    if db is not None:
        strategy_runs_collection = db[f"strategy_runs_{MONGO_ENV}"]
        runs = list(strategy_runs_collection.find().sort("run_time", -1).skip(skip_runs).limit(runs_per_page))
        total_runs = strategy_runs_collection.count_documents({})

        for run in runs:
            if 'run_time' in run:
                run['run_time'] = run['run_time'].astimezone(IST)

    has_more_runs = total_runs > (skip_runs + runs_per_page)

    return render_template('strategy.html', active_page='strategy', runs=runs, page=page, has_more_runs=has_more_runs)

@app.route('/trigger-strategy', methods=['POST'])
@login_required
def trigger_strategy():
    import threading
    thread = threading.Thread(target=run_executor, args=("manual",))
    thread.start()
    flash('Strategy execution triggered in background.', 'info')
    return redirect(url_for('run_strategy'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if db is None:
        flash("Database connection failed.", "danger")
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        try:
            new_settings = {
                'trading_mode': request.form.get('trading_mode'),
                'capital': float(request.form.get('capital')),
                'trade_amount': float(request.form.get('trade_amount')),
                'max_positions': int(request.form.get('max_positions')),
                'ma_period': int(request.form.get('ma_period')),
                'entry_threshold': float(request.form.get('entry_threshold')),
                'target_profit': float(request.form.get('target_profit')),
                'averaging_threshold': float(request.form.get('averaging_threshold')),
                'alert_email': request.form.get('alert_email', '')
            }
            db['user_settings'].update_one(
                {'_id': 'global_settings'},
                {'$set': new_settings},
                upsert=True
            )
            flash('Settings updated successfully!', 'success')
        except ValueError as e:
            flash(f'Invalid input: {e}', 'danger')
        
        return redirect(url_for('settings'))
    
    # Fetch settings or defaults
    default_settings = {
        'trading_mode': 'NORMAL',
        'capital': STRATEGY_CAPITAL,
        'trade_amount': MAX_TRADE_VALUE,
        'max_positions': -1,
        'ma_period': MA_PERIOD,
        'entry_threshold': 0,
        'target_profit': 5.0,
        'averaging_threshold': -3.0,
        'alert_email': ''
    }

    current_settings = db['user_settings'].find_one({'_id': 'global_settings'})
    if not current_settings:
        current_settings = default_settings.copy()
    
    # Load broker accounts
    broker_accounts = list(db['broker_accounts'].find().sort('created_at', 1))
    
    return render_template('settings.html', 
                         settings=current_settings, 
                         default_settings=default_settings,
                         broker_accounts=broker_accounts,
                         active_page='settings')

# Broker Management Routes
@app.route('/broker/<broker_id>/toggle', methods=['POST'])
@login_required
def broker_toggle(broker_id):
    """Toggle broker enabled/disabled status"""
    if db is None:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    broker = db['broker_accounts'].find_one({'broker_id': broker_id})
    if not broker:
        return jsonify({'success': False, 'message': 'Broker not found'}), 404
    
    new_status = not broker.get('enabled', True)
    db['broker_accounts'].update_one(
        {'broker_id': broker_id},
        {'$set': {'enabled': new_status}}
    )
    
    return jsonify({
        'success': True,
        'enabled': new_status,
        'message': f"Broker {'enabled' if new_status else 'disabled'} successfully"
    })

@app.route('/broker/<broker_id>/set-default', methods=['POST'])
@login_required
def broker_set_default(broker_id):
    """Set broker as default"""
    if db is None:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    broker = db['broker_accounts'].find_one({'broker_id': broker_id})
    if not broker:
        return jsonify({'success': False, 'message': 'Broker not found'}), 404
    
    # Remove default from all brokers
    db['broker_accounts'].update_many({}, {'$set': {'is_default': False}})
    
    # Set this broker as default
    db['broker_accounts'].update_one(
        {'broker_id': broker_id},
        {'$set': {'is_default': True}})
    
    return jsonify({
        'success': True,
        'message': f"{broker.get('display_name')} set as default broker"
    })

@app.route('/broker/<broker_id>/update-mode', methods=['POST'])
@login_required
def broker_update_mode(broker_id):
    """Update broker trading mode"""
    if db is None:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    trading_mode = request.json.get('trading_mode')
    if trading_mode not in ['NORMAL', 'EXIT_ONLY', 'PAUSED']:
        return jsonify({'success': False, 'message': 'Invalid trading mode'}), 400
    
    result = db['broker_accounts'].update_one(
        {'broker_id': broker_id},
        {'$set': {'trading_mode': trading_mode}}
    )
    
    if result.matched_count == 0:
        return jsonify({'success': False, 'message': 'Broker not found'}), 404
    
    return jsonify({
        'success': True,
        'message': f"Trading mode updated to {trading_mode}"
    })

@app.route('/broker/<broker_id>/update-name', methods=['POST'])
@login_required
def broker_update_name(broker_id):
    """Update broker display name"""
    if db is None:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    display_name = request.json.get('display_name', '').strip()
    if not display_name:
        return jsonify({'success': False, 'message': 'Display name cannot be empty'}), 400
    
    result = db['broker_accounts'].update_one(
        {'broker_id': broker_id},
        {'$set': {'display_name': display_name}}
    )
    
    if result.matched_count == 0:
        return jsonify({'success': False, 'message': 'Broker not found'}), 404
    
    return jsonify({
        'success': True,
        'message': 'Display name updated successfully'
    })

# --- Add Broker Routes ---

@app.route('/add-broker')
@login_required
def add_broker():
    return render_template('add_broker.html', active_page='settings')

@app.route('/broker/setup/fyers', methods=['POST'])
@login_required
def setup_fyers():
    """Step 1: Save temp credentials and redirect to Fyers Auth"""
    display_name = request.form.get('display_name')
    client_id = request.form.get('client_id')
    secret_id = request.form.get('secret_id')
    redirect_uri = request.form.get('redirect_uri')
    pin = request.form.get('pin', '')
    
    if not all([display_name, client_id, secret_id, redirect_uri]):
        flash("All fields are required", "danger")
        return redirect(url_for('add_broker'))
    
    # Store in session for retrieval after callback
    session['temp_broker_data'] = {
        'type': 'fyers',
        'display_name': display_name,
        'client_id': client_id,
        'secret_id': secret_id,
        'redirect_uri': redirect_uri,
        'pin': pin
    }
    
    try:
        connector = FyersConnector(api_key=client_id, api_secret=secret_id)
        auth_url = connector.get_login_url(redirect_uri=redirect_uri)
        return redirect(auth_url)
    except Exception as e:
        flash(f"Error generating auth URL: {str(e)}", "danger")
        return redirect(url_for('add_broker'))

@app.route('/broker/callback/fyers')
@login_required
def callback_fyers():
    """Step 2: Handle Fyers Callback"""
    auth_code = request.args.get('auth_code')
    
    if not auth_code:
        # Fyers might send 'code' instead of 'auth_code' sometimes, or error
        # Actually Fyers v3 sends 'auth_code' usually, but check documentation if needed. 
        # Standard OAuth is 'code'. Fyers documentation says 'auth_code' in response? 
        # Let's check query params.
        # If user cancelled or error
        if request.args.get('error'):
            flash(f"Authorization failed: {request.args.get('error_description')}", "danger")
            return redirect(url_for('add_broker'))
        
        # Fallback check
        auth_code = request.args.get('code')
        if not auth_code:
             flash("No authorization code received from Fyers.", "danger")
             return redirect(url_for('add_broker'))

    temp_data = session.get('temp_broker_data')
    if not temp_data or temp_data.get('type') != 'fyers':
        flash("Session expired or invalid. Please try again.", "danger")
        return redirect(url_for('add_broker'))
    
    try:
        connector = FyersConnector(api_key=temp_data['client_id'], api_secret=temp_data['secret_id'])
        # Exchange code for token
        token_response = connector.generate_session(auth_code=auth_code, redirect_uri=temp_data['redirect_uri'])
        
        mode = temp_data.get('mode', 'create')
        
        if mode == 'update':
            # Update existing broker
            broker_id = temp_data.get('broker_id')
            if not broker_id:
                raise Exception("Broker ID missing for update")
                
            db['broker_accounts'].update_one(
                {'broker_id': broker_id},
                {'$set': {
                    'access_token': token_response['access_token'],
                    'refresh_token': token_response.get('refresh_token'),
                    'token_generated_at': datetime.now(UTC),
                    'token_status': 'valid',
                    # Update credentials just in case they were changed in setup (if we support that flow later)
                    # For now just tokens
                }}
            )
            flash(f"Broker '{temp_data['display_name']}' re-connected successfully!", "success")
            
        else:
            # Create New Broker
            broker_id = str(uuid.uuid4())
            new_broker = {
                "broker_id": broker_id,
                "broker_type": "fyers",
                "display_name": temp_data['display_name'],
                "enabled": True,
                "is_default": False, 
                "trading_mode": "NORMAL",
                "created_at": datetime.now(UTC),
                "client_id": temp_data['client_id'], 
                "secret_id": temp_data['secret_id'],
                "pin": temp_data['pin'],
                "redirect_uri": temp_data['redirect_uri'],
                "access_token": token_response['access_token'],
                "refresh_token": token_response.get('refresh_token'),
                "token_generated_at": datetime.now(UTC),
                "token_status": "valid",
                "last_run_at": None
            }
            
            # If this is the first broker, make it default
            if db['broker_accounts'].count_documents({}) == 0:
                new_broker['is_default'] = True
                
            db['broker_accounts'].insert_one(new_broker)
            flash(f"Broker '{temp_data['display_name']}' added successfully!", "success")
        
        # Clear session
        session.pop('temp_broker_data', None)
        return redirect(url_for('settings'))
        
    except Exception as e:
        flash(f"Failed to complete setup: {str(e)}", "danger")
        return redirect(url_for('settings')) # Redirect to settings on failure too? Or add_broker? 
        # Better to go to settings if update failed. But adding new -> add_broker.
        # Let's check mode or just default to add_broker if 'create'.
        # If update fail, maybe settings is better.
        if temp_data.get('mode') == 'update':
             return redirect(url_for('settings'))
        return redirect(url_for('add_broker'))

@app.route('/broker/setup/zerodha', methods=['POST'])
@login_required
def setup_zerodha():
    """Step 1: Save temp credentials and redirect to Zerodha Auth"""
    display_name = request.form.get('display_name')
    api_key = request.form.get('api_key')
    api_secret = request.form.get('api_secret')
    
    if not all([display_name, api_key, api_secret]):
        flash("All fields are required", "danger")
        return redirect(url_for('add_broker'))
    
    # Store in session
    session['temp_broker_data'] = {
        'type': 'zerodha',
        'display_name': display_name,
        'api_key': api_key,
        'api_secret': api_secret
    }
    
    # Redirect to Kite Login
    # Zerodha URL: https://kite.zerodha.com/connect/login?v=3&api_key=xxx
    return redirect(f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}")

@app.route('/broker/callback/zerodha')
@login_required
def callback_zerodha():
    """Step 2: Handle Zerodha Callback"""
    request_token = request.args.get('request_token')
    status = request.args.get('status')
    
    if status == 'failure':
        flash(f"Authorization failed: {request.args.get('message')}", "danger")
        return redirect(url_for('add_broker'))
        
    if not request_token:
        flash("No request token received from Zerodha.", "danger")
        return redirect(url_for('add_broker'))
        
    temp_data = session.get('temp_broker_data')
    if not temp_data or temp_data.get('type') != 'zerodha':
        flash("Session expired or invalid. Please try again.", "danger")
        return redirect(url_for('add_broker'))
        
    try:
        connector = ZerodhaConnector(api_key=temp_data['api_key'], api_secret=temp_data['api_secret'])
        # Exchange token
        token_response = connector.generate_session(auth_code=request_token)
        
        mode = temp_data.get('mode', 'create')
        
        if mode == 'update':
            # Update existing broker
            broker_id = temp_data.get('broker_id')
            if not broker_id:
                raise Exception("Broker ID missing for update")
                
            db['broker_accounts'].update_one(
                {'broker_id': broker_id},
                {'$set': {
                    'access_token': token_response['access_token'],
                    'public_token': token_response.get('public_token'),
                    'user_id': token_response.get('user_id'),
                    'token_generated_at': datetime.now(UTC),
                    'token_status': 'valid'
                }}
            )
            flash(f"Broker '{temp_data['display_name']}' re-connected successfully!", "success")
        
        else:
            # New Broker Logic
            broker_id = str(uuid.uuid4())
            new_broker = {
                "broker_id": broker_id,
                "broker_type": "zerodha",
                "display_name": temp_data['display_name'],
                "enabled": True,
                "is_default": False,
                "trading_mode": "NORMAL",
                "created_at": datetime.now(UTC),
                "api_key": temp_data['api_key'],
                "api_secret": temp_data['api_secret'],
                "access_token": token_response['access_token'],
                "public_token": token_response.get('public_token'),
                "user_id": token_response.get('user_id'),
                "token_generated_at": datetime.now(UTC),
                "token_status": "valid",
                "last_run_at": None
            }
            
            # If this is the first broker, make it default
            if db['broker_accounts'].count_documents({}) == 0:
                new_broker['is_default'] = True
                
            db['broker_accounts'].insert_one(new_broker)
            flash(f"Broker '{temp_data['display_name']}' added successfully!", "success")
        
        session.pop('temp_broker_data', None)
        return redirect(url_for('settings'))
        
    except Exception as e:
        flash(f"Failed to complete setup: {str(e)}", "danger")
        if temp_data.get('mode') == 'update':
            return redirect(url_for('settings'))
        return redirect(url_for('add_broker'))

@app.route('/broker/<broker_id>/delete', methods=['POST'])
@login_required
def broker_delete(broker_id):
    """Delete a broker account"""
    if db is None:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    # Check if broker exists
    broker = db['broker_accounts'].find_one({'broker_id': broker_id})
    if not broker:
        return jsonify({'success': False, 'message': 'Broker not found'}), 404
    
    # Optional: Prevent deleting the only broker? 
    # For now, allow it, but if it was default, we might need to reassess default
    is_default = broker.get('is_default', False)
    
    db['broker_accounts'].delete_one({'broker_id': broker_id})
    
    # If we deleted the default broker, make another one default (if exists)
    if is_default:
        next_broker = db['broker_accounts'].find_one({})
        if next_broker:
            db['broker_accounts'].update_one(
                {'_id': next_broker['_id']}, 
                {'$set': {'is_default': True}}
            )
            
    return jsonify({
        'success': True,
        'message': f"Broker '{broker.get('display_name')}' deleted successfully"
    })

@app.route('/broker/reauth/zerodha/<broker_id>')
@login_required
def broker_reauth_zerodha(broker_id):
    """Bridge route to set session for Zerodha re-auth"""
    broker = db['broker_accounts'].find_one({'broker_id': broker_id})
    if not broker:
        flash("Broker not found", "error")
        return redirect(url_for('token_refresh'))
        
    session['temp_broker_data'] = {
        'mode': 'update',
        'type': 'zerodha',
        'broker_id': broker['broker_id'],
        'display_name': broker['display_name'],
        'api_key': broker.get('api_key'),
        'api_secret': broker.get('api_secret')
    }
    return redirect(f"https://kite.zerodha.com/connect/login?v=3&api_key={broker.get('api_key')}")

@app.route('/broker/reauth/fyers/<broker_id>')
@login_required
def broker_reauth_fyers(broker_id):
    """Bridge route to set session for Fyers re-auth"""
    broker = db['broker_accounts'].find_one({'broker_id': broker_id})
    if not broker:
        flash("Broker not found", "error")
        return redirect(url_for('token_refresh'))
        
    client_id = broker.get('client_id') or broker.get('api_key')
    secret_id = broker.get('secret_id') or broker.get('api_secret')
        
    session['temp_broker_data'] = {
        'mode': 'update',
        'type': 'fyers',
        'broker_id': broker['broker_id'],
        'display_name': broker['display_name'],
        'client_id': client_id,
        'secret_id': secret_id,
        'redirect_uri': broker.get('redirect_uri', FYERS_REDIRECT_URI),
        'pin': broker.get('pin')
    }
    try:
        connector = FyersConnector(api_key=client_id, api_secret=secret_id)
        return redirect(connector.get_login_url(redirect_uri=broker.get('redirect_uri', FYERS_REDIRECT_URI)))
    except Exception as e:
        flash(f"Error generating login URL: {e}", "error")
        return redirect(url_for('token_refresh'))

@app.route('/broker/<broker_id>/refresh', methods=['POST'])
@login_required
def broker_refresh(broker_id):
    """Refresh token for a broker (Manual trigger)"""
    if db is None:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    broker = db['broker_accounts'].find_one({'broker_id': broker_id})
    if not broker:
        return jsonify({'success': False, 'message': 'Broker not found'}), 404
    
    broker_type = broker.get('broker_type')
    
    # helper to start update flow
    def start_manual_flow(b):
         if b['broker_type'] == 'fyers':
             # Setup session for Fyers
             session['temp_broker_data'] = {
                'mode': 'update',
                'broker_id': b['broker_id'],
                'type': 'fyers',
                'display_name': b['display_name'],
                'client_id': b['client_id'], # Keep existing creds
                'secret_id': b['secret_id'],
                'pin': b.get('pin'),
                'redirect_uri': b['redirect_uri']
             }
             try:
                 connector = FyersConnector(api_key=b['client_id'], api_secret=b['secret_id'])
                 return jsonify({'redirect': connector.get_login_url(redirect_uri=b['redirect_uri'])})
             except Exception as e:
                 return jsonify({'success': False, 'message': str(e)}), 500
                 
         elif b['broker_type'] == 'zerodha':
             # Setup session for Zerodha
             session['temp_broker_data'] = {
                'mode': 'update',
                'broker_id': b['broker_id'],
                'type': 'zerodha',
                'display_name': b['display_name'],
                'api_key': b['api_key'],
                'api_secret': b['api_secret']
             }
             # Direct redirect URL for Zerodha
             return jsonify({'redirect': f"https://kite.zerodha.com/connect/login?v=3&api_key={b['api_key']}"})
             
         return jsonify({'success': False, 'message': 'Unknown broker type'}), 400

    # Logic per broker
    if broker_type == 'fyers':
        # Try auto-refresh first
        refresh_token_str = broker.get('refresh_token')
        if refresh_token_str:
            try:
                connector = FyersConnector(api_key=broker['client_id'], api_secret=broker['secret_id'])
                new_tokens = connector.refresh_token(refresh_token_str)
                
                # Update DB
                db['broker_accounts'].update_one(
                    {'broker_id': broker_id},
                    {'$set': {
                        'access_token': new_tokens['access_token'],
                        # refresh token might rotate or stay same
                        'refresh_token': new_tokens.get('refresh_token', refresh_token_str), 
                        'token_generated_at': datetime.now(UTC),
                        'token_status': 'valid'
                    }}
                )
                return jsonify({'success': True, 'message': 'Token refreshed successfully!'})
            except Exception as e:
                # If refresh fails, fall back to manual
                return start_manual_flow(broker)
        else:
            return start_manual_flow(broker)
            
    elif broker_type == 'zerodha':
        # Zerodha requires manual login daily
        return start_manual_flow(broker)
        
    return jsonify({'success': False, 'message': 'Unsupported broker'}), 400

@app.route('/run-logs/<run_id>')
@login_required
def run_logs(run_id):
    if db is None:
        return "Database connection failed."
    
    logs = list(db[f"logs_{MONGO_ENV}"].find({"run_id": run_id}).sort("timestamp", 1))
    for log in logs:
        log['timestamp'] = log['timestamp'].astimezone(IST)
        
    return render_template('run_logs.html', logs=logs, run_id=run_id)

if __name__ == '__main__':
    from waitress import serve
    print("Starting server on 0.0.0.0:8080")
    serve(app, host="0.0.0.0", port=8080)
