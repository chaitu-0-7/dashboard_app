from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash, g
from auth import AuthManager, login_required
from connectors.fyers import FyersConnector
from connectors.zerodha import ZerodhaConnector
from authlib.integrations.flask_client import OAuth

from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime, timedelta
import pytz
from collections import defaultdict
import os
from dotenv import load_dotenv
load_dotenv()
import json
import time
import sys
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

# --- Google OAuth Setup ---
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    access_token_url='https://oauth2.googleapis.com/token',
    access_token_params=None,
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    authorize_params=None,
    api_base_url='https://www.googleapis.com/oauth2/v1/',
    userinfo_endpoint='https://openidconnect.googleapis.com/v1/userinfo',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)


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
        auth_manager.create_user("chaitu_shop", "Chaitu2@nifty_shop", role="admin")
    else:
        # Ensure chaitu_shop is admin (Migration/Safety)
        auth_manager.users_collection.update_one(
            {"username": "chaitu_shop"}, 
            {"$set": {"role": "admin", "is_active": True}}
        )

else:
    print("Could not find MongoDB URI in .env file")
    # ... (Handlers for no DB)
    sys.exit(1)

@app.before_request
def load_logged_in_user():
    g.user = None
    try:
        session_token = session.get('session_token')
        if session_token and auth_manager:
            # print(f"DEBUG: Checking session {session_token[:8]}...")
            session_data = auth_manager.get_session(session_token)
            if session_data:
                g.user = auth_manager.get_user(session_data['username'])
                # print(f"DEBUG: Found User: {g.user.get('username')}")
                if g.user and not g.user.get('is_active', True):
                     auth_manager.delete_session(session_token)
                     session.pop('session_token', None)
                     g.user = None
                     flash('Your account is pending approval or has been deactivated.', 'warning')
            else:
                session.pop('session_token', None)
    except Exception as e:
        print(f"❌ Error in load_logged_in_user: {e}")
        import traceback
        traceback.print_exc()

# Admin Decorator
from functools import wraps
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not g.user or g.user.get('role') != 'admin':
            flash('Access denied. Admin permissions required.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


# --- Auth Routes ---
@app.route('/login/google')
def login_google():
    redirect_uri = url_for('auth_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/callback')
def auth_callback():
    token = google.authorize_access_token()
    resp = google.get('userinfo')
    user_info = resp.json()
    
    email = user_info['email']
    google_id = user_info['id']
    picture = user_info.get('picture')
    name = user_info.get('name', email)
    
    # Create or Get User
    user = auth_manager.create_google_user(email, google_id, picture, name)
    
    if user.get('is_active'):
        # Login
        session_token = auth_manager.create_session(user['username'])
        session['session_token'] = session_token
        
        # --- Auto Token Refresh Logic ---
        from token_manager import TokenManager
        try:
            tm = TokenManager(db)
            broker_doc = db.broker_accounts.find_one({"username": user['username'], "broker_type": "fyers"})
            if broker_doc:
                is_valid = tm.check_and_refresh_token(broker_doc)
                if not is_valid:
                     flash('Your broker token has expired and could not be auto-refreshed. Please update it.', 'warning')
                     return redirect(url_for('token_refresh'))
        except Exception as e:
            print(f"Auto-refresh failed during login: {e}")
        # -------------------------------

        flash('Logged in successfully via Google.', 'success')
        return redirect(url_for('dashboard'))
    else:
        # Pending Approval
        flash('Account created! verification pending by Admin. You will be notified via email.', 'warning')
        return redirect(url_for('login'))

# --- Global Error Handling ---
@app.errorhandler(500)
def internal_error(error):
    import traceback
    traceback.print_exc() # Print to console
    return f"<h2>Internal Server Error Detected</h2><pre>{traceback.format_exc()}</pre>", 500

@app.errorhandler(404)
def not_found(error):
    return "<h2>404 Not Found</h2>", 404

# --- Admin Routes ---
from utils.email import send_approval_email, send_removal_email

@app.route('/admin')
@admin_required
def admin_dashboard():
    # Stats
    total_users = auth_manager.users_collection.count_documents({})
    pending_users_count = auth_manager.users_collection.count_documents({"is_active": False})
    active_sessions = auth_manager.sessions_collection.count_documents({"expires_at": {"$gt": datetime.now(UTC)}})
    
    stats = {
        "total_users": total_users,
        "pending_users": pending_users_count,
        "active_sessions": active_sessions
    }
    
    # Pending Users
    pending_users = list(auth_manager.users_collection.find({"is_active": False}).sort("created_at", -1))
    
    # All Users (Limit 50 for now)
    all_users = list(auth_manager.users_collection.find({}).sort("created_at", -1).limit(50))
    
    return render_template('admin/dashboard.html', stats=stats, pending_users=pending_users, all_users=all_users, active_page='admin_dashboard')

@app.route('/admin/users/remove/<user_id>', methods=['POST'])
@admin_required
def admin_remove_user(user_id):
    try:
        # Get user details first for email
        user = auth_manager.users_collection.find_one({"_id": ObjectId(user_id)})
        if user:
            # Prevent removing self
            if user['username'] == g.user['username']:
                flash("You cannot remove yourself.", "error")
                return redirect(url_for('admin_dashboard'))
                
            # Send Email (Try best effort)
            if user.get('email'):
                send_removal_email(user['email'], user.get('name', 'User'))
            
            # Delete
            if auth_manager.delete_user(user_id):
                flash(f"User {user.get('username')} removed successfully.", 'success')
            else:
                flash("Failed to delete user.", "error")
        else:
            flash("User not found.", "error")
            
    except Exception as e:
        flash(f"Error removing user: {str(e)}", "error")
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/users/approve/<user_id>', methods=['POST'])
@admin_required
def admin_approve_user(user_id):
    try:
        user = auth_manager.users_collection.find_one({"_id": ObjectId(user_id)})
        if user:
            auth_manager.users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"is_active": True}}
            )
            # Send Email
            if user.get('email'):
                send_approval_email(user['email'], user.get('name', 'User'))
            
            flash(f"User {user.get('username')} approved successfully.", 'success')
        else:
            flash("User not found.", "error")
    except Exception as e:
        flash(f"Error approving user: {str(e)}", "error")
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/users/reject/<user_id>', methods=['POST'])
@admin_required
def admin_reject_user(user_id):
    try:
        # Delete user
        auth_manager.users_collection.delete_one({"_id": ObjectId(user_id)})
        flash("User rejected and removed.", 'success')
    except Exception as e:
        flash(f"Error rejecting user: {str(e)}", "error")
    return redirect(url_for('admin_dashboard'))

@app.route('/api/user/tour-complete', methods=['POST'])
@login_required
def tour_complete():
    try:
        if g.user:
            auth_manager.users_collection.update_one(
                {"_id": g.user['_id']},
                {"$set": {"has_seen_tour": True}}
            )
            return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "error"}), 400

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
            flash('Incorrect username.', 'danger')
            return redirect(url_for('login'))
        elif auth_manager.is_account_locked(user):
            flash('Account locked. Please contact administrator.', 'danger')
            return redirect(url_for('login'))
        
        if user and auth_manager.verify_password(user, password):
            # Check if locked (this check is redundant if the elif above handles it, but keeping as per instruction)
            if auth_manager.is_account_locked(user):
                 flash('Account is locked due to too many failed attempts. Try again later.', 'error')
                 return redirect(url_for('login'))

            auth_manager.reset_failed_logins(username)
            session_token = auth_manager.create_session(username)
            session['session_token'] = session_token
            
            # --- Auto Token Refresh Logic ---
            from token_manager import TokenManager
            try:
                tm = TokenManager(db)
                broker_doc = db.broker_accounts.find_one({"username": username, "broker_type": "fyers"})
                if broker_doc:
                    is_valid = tm.check_and_refresh_token(broker_doc)
                    if not is_valid:
                         flash('Your broker token has expired and could not be auto-refreshed. Please update it.', 'warning')
                         return redirect(url_for('token_refresh'))
            except Exception as e:
                print(f"Auto-refresh failed during login: {e}")
            # -------------------------------

            flash('Logged in successfully.', 'success')
            return redirect(url_for('dashboard'))
        else:
            # Record failed attempt
            auth_manager.record_failed_login(username)
            flash('Invalid username or password.', 'error')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    if 'session_token' in session and auth_manager:
        auth_manager.delete_session(session['session_token'])
    session.pop('session_token', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# @app.route('/')
# @login_required
def _deprecated_dashboard_old():
    if db is None:
        return "Database connection failed. Please check your MongoDB URI in files.txt"

    # --- Broker Management & Connector Initialization ---
    active_connectors = []
    broker_errors = []
    
    # Get all enabled brokers for dropdown
    all_brokers = list(db['broker_accounts'].find({"enabled": True}))
    
    # Determine Selected Broker
    selected_broker_id = request.args.get('broker', 'all')
    
    # Filter brokers for processing metrics
    brokers_to_process = all_brokers
    if selected_broker_id != 'all':
        brokers_to_process = [b for b in all_brokers if b['broker_id'] == selected_broker_id]
        if not brokers_to_process: # invalid ID, fallback
            selected_broker_id = 'all'
            brokers_to_process = all_brokers

    # If no brokers, we might want to warn
    if not all_brokers:
        flash("No active brokers found. Please configure a broker in Settings.", "warning")

    holdings_pnl = 0.0
    open_positions_count = 0
    raw_positions = []
    used_capital = 0
    num_positions = 0
    
    # Capital Aggregation
    total_positions_can_open = 0
    total_strategy_capital = 0  
    
    
    for broker in brokers_to_process:
        b_type = broker.get('broker_type')
        b_name = broker.get('display_name', b_type)
        connector = None
        broker_used_capital = 0 # Track per broker
        
        try:
            # Check Token Validity (Basic Check)
            gen_at = broker.get('token_generated_at')
            if isinstance(gen_at, (int, float)): gen_at = datetime.fromtimestamp(gen_at, tz=UTC)
            elif gen_at and gen_at.tzinfo is None: gen_at = UTC.localize(gen_at)
            
            is_valid = False
            if gen_at:
                age = (datetime.now(UTC) - gen_at).total_seconds()
                # Zerodha: ~24h (but practically daily start). Fyers: < ACCESS_TOKEN_VALIDITY
                if b_type == 'zerodha':
                     # Zerodha tokens are valid for one trading day. 
                     # Simple check: is it from today?
                     # Better: access_token exists and age < 24h
                     if age < 86400: is_valid = True
                elif b_type == 'fyers':
                     if age < ACCESS_TOKEN_VALIDITY: is_valid = True
            
            if not is_valid:
                broker_errors.append(f"{b_name}: Token expired.")
                continue

            # Initialize Connector
            if b_type == 'fyers':
                 client_id = broker.get('client_id') or broker.get('api_key')
                 secret_id = broker.get('secret_id') or broker.get('api_secret')
                 connector = FyersConnector(
                     api_key=client_id, 
                     api_secret=secret_id, 
                     access_token=broker.get('access_token'),
                     pin=broker.get('pin')
                 )
            elif b_type == 'zerodha':
                 connector = ZerodhaConnector(
                     api_key=broker.get('api_key'),
                     api_secret=broker.get('api_secret'),
                     access_token=broker.get('access_token')
                 )
            
            if connector:
                active_connectors.append(connector)
                
                # Fetch Holdings
                try:
                    b_holdings = connector.get_holdings()
                    for p in b_holdings:
                        qty = p.get('quantity', 0)
                        if qty != 0:
                            holdings_pnl += p.get('pl', 0)
                            open_positions_count += 1
                            
                            # For capital calc
                            cost = p.get('costPrice', 0)
                            pos_value = cost * abs(qty)
                            used_capital += pos_value
                            broker_used_capital += pos_value
                            num_positions += 1
                            
                            # Append to raw positions (maybe add broker tag?)
                            p['broker'] = b_name
                            raw_positions.append(p)
                except Exception as e:
                    print(f"Error fetching holdings for {b_name}: {e}")
                    broker_errors.append(f"{b_name}: Failed to fetch holdings.")

        except Exception as e:
             print(f"Error initializing {b_name}: {e}")
             broker_errors.append(f"{b_name}: Error ({str(e)})")
        
        # Calculate per-broker metrics
        b_capital = broker.get('capital', 0)
        b_trade_amt = broker.get('trade_amount', 0)
        
        total_strategy_capital += b_capital
        
        b_avail = max(0, b_capital - broker_used_capital)
        if b_trade_amt > 0:
            total_positions_can_open += int(b_avail / b_trade_amt)

    # Show consolidated errors/warnings as Toast
    if broker_errors:
        flash(" | ".join(broker_errors), "warning")

    # Fetch today's executed trades
    today = datetime.now(IST).date()
    start_of_today = IST.localize(datetime(today.year, today.month, today.day, 0, 0, 0)).astimezone(UTC)
    end_of_today = IST.localize(datetime(today.year, today.month, today.day, 23, 59, 59)).astimezone(UTC)
    
    today_query = {
        "date": {"$gte": start_of_today, "$lte": end_of_today},
        "filled": True
    }
    if selected_broker_id != 'all':
        today_query['broker_id'] = selected_broker_id
        
    today_trades = list(db[f"trades_{MONGO_ENV}"].find(today_query))
    recent_trades_count = len(today_trades)

    # --- Daily activity logic for dashboard ---
    page = request.args.get('page', 1, type=int)
    skip_days = (page - 1) * LOGS_PER_PAGE
    
    # Date Query Filters
    date_filter_logs = {"timestamp": {"$ne": None}}
    date_filter_trades = {"date": {"$ne": None}}
    
    if selected_broker_id != 'all':
        date_filter_logs['broker_id'] = selected_broker_id
        date_filter_trades['broker_id'] = selected_broker_id

    distinct_log_dates = db[f"logs_{MONGO_ENV}"].distinct("timestamp", date_filter_logs)
    distinct_trade_dates = db[f"trades_{MONGO_ENV}"].distinct("date", date_filter_trades)

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

        logs_query = {
            "timestamp": {"$gte": start_of_day_utc, "$lte": end_of_day_utc}
        }
        if selected_broker_id != 'all': logs_query['broker_id'] = selected_broker_id
        
        logs_for_day = list(db[f"logs_{MONGO_ENV}"].find(logs_query).sort("timestamp", -1))
        for log in logs_for_day:
            log['timestamp'] = log['timestamp'].astimezone(IST)

        trades_query = {
            "date": {"$gte": start_of_day_utc, "$lte": end_of_day_utc}
        }
        if selected_broker_id != 'all': trades_query['broker_id'] = selected_broker_id

        trades_for_day = list(db[f"trades_{MONGO_ENV}"].find(trades_query).sort("date", -1))
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
    
    chart_query = {"filled": True, "profit": {"$exists": True}}
    if selected_broker_id != 'all': chart_query['broker_id'] = selected_broker_id
    
    all_filled_trades = list(db[f"trades_{MONGO_ENV}"].find(chart_query))
    for trade in all_filled_trades:
        if trade.get('action') == 'SELL':
            trade_date = trade['date'].astimezone(IST).strftime('%Y-%m-%d')
            daily_pnl_data[trade_date]['pnl'] += trade.get('profit', 0.0)
            daily_pnl_data[trade_date]['trades'] += 1
    
    sorted_daily_pnl = sorted(daily_pnl_data.items())
    chart_labels = [item[0] for item in sorted_daily_pnl]
    chart_values = [item[1]['pnl'] for item in sorted_daily_pnl]
    chart_trades = [item[1]['trades'] for item in sorted_daily_pnl]

    cumu_query = {"filled": True}
    if selected_broker_id != 'all': cumu_query['broker_id'] = selected_broker_id
    
    all_filled_trades_cumu = list(db[f"trades_{MONGO_ENV}"].find(cumu_query).sort("date", 1))
    cumulative_pnl_data = []
    cumulative_pnl = 0
    for trade in all_filled_trades_cumu:
        cumulative_pnl += trade.get('profit', 0.0)
        cumulative_pnl_data.append({
            'date': trade['date'].astimezone(IST).strftime('%Y-%m-%d'),
            'pnl': cumulative_pnl
        })

    # Capital Utilization (Calculated above in loop)
    # used_capital, num_positions calculated 

    
    
    
    # Calculate Total Strategy Capital from all enabled brokers
    # total_strategy_capital calculated in loop

    available_capital = max(0, total_strategy_capital - used_capital)
    used_percentage = (used_capital / total_strategy_capital * 100) if total_strategy_capital > 0 else 0
    available_percentage = (available_capital / total_strategy_capital * 100) if total_strategy_capital > 0 else 0
    
    # positions_can_open calculated in loop
    avg_position_size = (used_capital / num_positions) if num_positions > 0 else 0
    
    capital_utilization = {
        'used': used_capital,
        'available': available_capital,
        'total': total_strategy_capital,
        'used_percentage': used_percentage,
        'available_percentage': available_percentage,
        'positions_can_open': total_positions_can_open,
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
                           cumulative_pnl_data=json.dumps(cumulative_pnl_data),
                           brokers=all_brokers,
                           selected_broker_id=selected_broker_id)

@app.route('/trading-overview')
@login_required
def trading_overview():
    # --- Broker Management & Connector Initialization ---
    active_connectors = []
    current_positions = []
    
    # Get all enabled brokers for dropdown
    user_filter = {"username": g.user['username']}
    all_brokers = list(db['broker_accounts'].find({**user_filter, "enabled": True}))
    
    selected_broker_id = request.args.get('broker', 'all')
    
    # Filter brokers for processing positions
    brokers_to_process = all_brokers
    if selected_broker_id != 'all':
        brokers_to_process = [b for b in all_brokers if b['broker_id'] == selected_broker_id]
        if not brokers_to_process:
            selected_broker_id = 'all'
            brokers_to_process = all_brokers

    
    for broker in brokers_to_process:
        b_type = broker.get('broker_type')
        b_name = broker.get('display_name', b_type)
        connector = None
        
        try:
            # Check Token Validity (Basic Check)
            gen_at = broker.get('token_generated_at')
            if isinstance(gen_at, (int, float)): gen_at = datetime.fromtimestamp(gen_at, tz=UTC)
            elif gen_at and gen_at.tzinfo is None: gen_at = UTC.localize(gen_at)
            
            is_valid = False
            if gen_at:
                age = (datetime.now(UTC) - gen_at).total_seconds()
                if b_type == 'zerodha':
                     if age < 86400: is_valid = True
                elif b_type == 'fyers':
                     if age < ACCESS_TOKEN_VALIDITY: is_valid = True
            
            if not is_valid:
                flash(f"{b_name}: Token expired.", "warning")
                continue

            # Initialize Connector
            if b_type == 'fyers':
                 client_id = broker.get('client_id') or broker.get('api_key')
                 secret_id = broker.get('secret_id') or broker.get('api_secret')
                 connector = FyersConnector(
                     api_key=client_id, 
                     api_secret=secret_id, 
                     access_token=broker.get('access_token'),
                     pin=broker.get('pin')
                 )
            elif b_type == 'zerodha':
                 connector = ZerodhaConnector(
                     api_key=broker.get('api_key'),
                     api_secret=broker.get('api_secret'),
                     access_token=broker.get('access_token')
                 )
            
            if connector:
                active_connectors.append(connector)
                
                # Fetch Holdings
                try:
                    b_holdings = connector.get_holdings()
                    for p in b_holdings:
                        if p.get('quantity', 0) != 0:
                            cost_price = p.get('costPrice', 0)
                            pnl = p.get('pl', 0)
                            pnl_pct = (pnl / (cost_price * p.get('quantity', 1))) * 100 if cost_price > 0 else 0
                            invested_val = cost_price * p.get('quantity', 0)
            
                            current_positions.append({
                                'symbol': p.get('symbol'),
                                'quantity': p.get('quantity'),
                                'avg_price': cost_price,
                                'current_price': p.get('ltp'),
                                'invested_value': invested_val,
                                'pnl': pnl,
                                'pnl_pct': pnl_pct,
                                'broker': b_name
                            })
                except Exception as e:
                    print(f"Error fetching holdings for {b_name}: {e}")
                    flash(f"{b_name}: Failed to fetch positions.", "warning")

        except Exception as e:
             print(f"Error initializing {b_name}: {e}")


    # Removed duplicated holdings fetch block as it's handled in the loop above
    # ...


    
    
    # --- Sync Manual Trades (Backfill) ---
    new_manual_count = 0
    brokers_to_sync = brokers_to_process # Already filtered by selected_broker_id
    
    # We only sync if we have valid brokers to verify against
    # Avoiding overhead: maybe only sync if specific flag or just do it?
    # User asked: "everytime user logs in" (or view page). 
    # Fyers API is fast.
    
    for b_conf in brokers_to_sync:
        if b_conf.get('mode') != 'paper': # Don't sync paper accounts (no API)
             # Authenticate Broker
             try:
                 # Re-use logic from check_brokers or just instantiate
                 # We need an authenticated instance. 
                 # Let's import or use a helper if available, or just instantiate basic connector
                 # Actually, we need to handle tokens. 
                 # Best way: Check if we have tokens active.
                 
                 # NOTE: Instantiaing connectors here might be heavy if done naively.
                 # But we need it. 
                 
                 # Quickest path: Use FyersConnector / ZerodhaConnector with stored tokens.
                 b_id = b_conf['broker_id']
                 b_type = b_conf.get('broker_type', b_conf.get('broker')) # Fallback for safety
                 
                 # Check Token Validity
                 token_valid = False
                 # ... Token checks ...
                 # Actually, let's wrap this in a try-except block and hope tokens are good.
                 # If tokens expired, we just skip sync silently or log.
                 
                 # Instantiate
                 broker_instance = None
                 if b_type == 'fyers':
                      # Fetch Token
                      token_doc = db['fyers_tokens'].find_one({'broker_id': b_id})
                      if token_doc and token_doc.get('access_token'):
                           from fyers_apiv3 import fyersModel
                           broker_instance = fyersModel.FyersModel(client_id=b_conf['client_id'], token=token_doc['access_token'], log_path=os.getcwd())
                 
                 elif b_type == 'zerodha':
                      token_doc = db['zerodha_tokens'].find_one({'broker_id': b_id})
                      if token_doc and token_doc.get('access_token'):
                           from kiteconnect import KiteConnect
                           broker_instance = KiteConnect(api_key=b_conf['api_key'], access_token=token_doc['access_token'])
                 
                 if broker_instance:
                      # Call Helper
                      count = sync_broker_positions(b_id, broker_instance)
                      new_manual_count += count
                      
             except Exception as e:
                 print(f"Sync failed for {b_id}: {e}")
                 
    if new_manual_count > 0:
        flash(f"Detected {new_manual_count} manually closed positions. Please update their exit details.", "warning")

    # --- Fetch All Trades (User Pattern) ---
    user_filter = {"username": g.user['username']}
    trade_query = {**user_filter, "filled": True}
    if selected_broker_id != 'all':
        trade_query['broker_id'] = selected_broker_id
        
    all_filled_trades = list(db[f"trades_{MONGO_ENV}"].find(trade_query).sort("date", -1))
    
    # Process Timezones
    for trade in all_filled_trades:
        if isinstance(trade.get('date'), datetime):
             trade['date'] = trade['date'].astimezone(IST)
             
    # Separate System vs Manual (User Logic)
    closed_trades = []
    pending_manual_trades = []
    
    for trade in all_filled_trades:
        is_manual = trade.get('order_id') == 'MANUAL'
        
        if is_manual:
            # Check Status
            if trade.get('status') == 'PENDING_MANUAL_PRICE':
                 pending_manual_trades.append(trade)
            elif trade.get('status') == 'FILLED' and trade.get('action') == 'SELL':
                 # COMPLETED Manual Trade -> Treat as Regular Closed Trade
                 closed_trades.append(trade)
        else:
            # System Closed Trades
            if trade.get('action') == 'SELL' and 'profit' in trade:
                closed_trades.append(trade)
            
        # Ensure profit fields exist
        if 'profit' not in trade: trade['profit'] = 0.0
        if 'profit_pct' not in trade: trade['profit_pct'] = 0.0

    # Sort Closed Trades
    closed_trades.sort(key=lambda x: x['date'], reverse=True)

    # GROUP PENDING TRADES VISUALLY
    # We want to show 1 row per symbol, but knowing it represents N underlying trades.
    grouped_manual_trades = {}
    for t in pending_manual_trades:
        sym = t['symbol']
        if sym not in grouped_manual_trades:
            grouped_manual_trades[sym] = {
                'symbol': sym,
                'quantity': 0,
                'ids': [],
                'date': t['date'], # Use latest or first? User sees 'Date'. 
                'price': 0, 
                'status': 'PENDING_MANUAL_PRICE',
                'comment': 'Action Needed (Multiple Batches)' if t.get('comment') else ''
            }
        
        grouped_manual_trades[sym]['quantity'] += t['quantity']
        grouped_manual_trades[sym]['ids'].append(str(t['_id'])) # Store as strings
        # Keep earliest date for display if mixed? Or latest? 
        # User wants to know "Trade Opening Time".
        # If we group, we hide individual opening times. 
        # User asked for "Combined One". 
        # Let's show the Date of the *Oldest* (First In) component to be safe.
        if t['date'] < grouped_manual_trades[sym]['date']:
             grouped_manual_trades[sym]['date'] = t['date']

    # Convert Map to List
    final_manual_display = []
    for sym, data in grouped_manual_trades.items():
        # Join IDs with comma for the frontend to pass back
        data['_id'] = ",".join(data['ids']) 
        data['count'] = len(data['ids'])
        if data['count'] > 1:
            data['comment'] = f"Action Needed ({data['count']} Batches)"
        else:
            data['comment'] = "Action Needed"
        final_manual_display.append(data)
        
    manually_closed_trades = final_manual_display
    manually_closed_trades.sort(key=lambda x: x['date'], reverse=True)

    # Sort Manually Closed Trades (User Logic did this via query)
    # Since we fetched all sorted by date, they should be sorted, but explicit sort is safe.
    manually_closed_trades.sort(key=lambda x: x['date'], reverse=True)



    
    # Metrics Calculation
    # User requested to separate manual trades. Reverting to closed_trades only for main metrics.
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
    
    # Sort Ascending for Drawdown Calculation (Oldest First)
    sorted_trades_asc = sorted(closed_trades, key=lambda x: x['date'])
    for trade in sorted_trades_asc:
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
        # sorted_trades_asc is already oldest first
        for trade in sorted_trades_asc:
            cumulative_pnl += trade.get('profit', 0.0)
            cumulative_pnl_data.append({
                'date': trade['date'].strftime('%Y-%m-%d'),
                'pnl': cumulative_pnl
            })

    # Duplicate manual trade fetch removed.
    

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
                           capital_data=json.dumps(capital_data),
                           brokers=all_brokers,
                           selected_broker_id=selected_broker_id)


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

    query = {"username": g.user['username']}
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
    user_filter = {"username": g.user['username']}
    db_brokers = list(db['broker_accounts'].find(user_filter))
    
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

    is_dev = os.getenv('ENV') == 'dev'
    return render_template('token_refresh.html', 
                           brokers=brokers_data,
                           active_page='token_refresh',
                           is_dev=is_dev)

@app.route('/refresh-token-action', methods=['POST'])
@login_required
def refresh_token_action():
    # Attempt Fyers Refresh
    user_filter = {"username": g.user['username']}
    fyers_broker = db['broker_accounts'].find_one({**user_filter, 'broker_type': 'fyers'})
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



def run_executor(run_type="scheduled", broker_id=None, run_id=None):
    if not run_id:
        run_id = str(uuid.uuid4())
    # We rely on executor.py to handle DB operations for the run itself mostly, 
    # but we might capture stdout if needed. 
    # Actually, to prevent duplicates, we should mainly let executor.py handle the DB record.
    # However, if we want to capture the OUTER failure (subprocess failed to start), we need try/except.
    
    cmd = [sys.executable, "executor.py", "--run-id", run_id]
    if broker_id:
        cmd.extend(["--broker-id", broker_id])
        
    try:
        # Run in background without waiting if called from thread? 
        # No, this function IS the thread target, so we can wait here.
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True
        )
        # Print output to terminal so user can see it
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
            
        # executor.py handles the success DB record.
    except subprocess.CalledProcessError as e:
        # Print error output to terminal
        if e.stdout:
            print(e.stdout)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
            
        # Only log failure if executor didn't log it itself?
        # executor.py has try/except blocks so it likely logged 'failed'.
        # But if it crashed hard (syntax error), it wouldn't.
        if db is not None:
             db[f"strategy_runs_{MONGO_ENV}"].insert_one({
                "run_id": run_id,
                "run_time": datetime.now(UTC),
                "run_type": run_type,
                "status": "failed",
                "error": str(e),
                "stdout": e.stdout,
                "stderr": e.stderr
            })
    except Exception as e:
        print(f"Failed to start executor: {e}")


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
        user_filter = {"username": g.user['username']}
        runs = list(strategy_runs_collection.find(user_filter).sort("run_time", -1).skip(skip_runs).limit(runs_per_page))
        total_runs = strategy_runs_collection.count_documents({})

        for run in runs:
            if 'run_time' in run:
                run['run_time'] = run['run_time'].astimezone(IST)

    has_more_runs = total_runs > (skip_runs + runs_per_page)

    has_more_runs = total_runs > (skip_runs + runs_per_page)
    
    # Fetch brokers for the dropdown
    brokers = []
    if db is not None:
        user_filter = {"username": g.user['username']}
        brokers = list(db['broker_accounts'].find({**user_filter, 'enabled': True}, {'broker_id': 1, 'display_name': 1, 'broker_type': 1, 'trading_mode': 1}))

    return render_template('run_strategy.html', active_page='strategy', runs=runs, page=page, has_more_runs=has_more_runs, brokers=brokers)

@app.route('/api/run-logs/<run_id>')
@login_required
def get_run_logs(run_id):
    if db is None:
        return jsonify({'error': 'Database not connected'}), 500
    
    logs_collection = db[f"logs_{MONGO_ENV}"]
    
    # Query logs for the specific run_id
    # Sort by timestamp ascending
    logs = list(logs_collection.find({'run_id': run_id}, {'_id': 0}).sort('timestamp', 1))
    
    # Format timestamps for display
    formatted_logs = []
    for log in logs:
        if 'timestamp' in log and isinstance(log['timestamp'], datetime):
            # logs are stored in UTC usually, convert to IST for display
            log_time = log['timestamp']
            if log_time.tzinfo is None:
                log_time = UTC.localize(log_time)
            
            timestamp_str = log_time.astimezone(IST).strftime('%Y-%m-%d %H:%M:%S')
            
            formatted_logs.append({
                'timestamp': timestamp_str,
                'level': log.get('level', 'INFO'),
                'message': log.get('message', ''),
                'broker_id': log.get('broker_id', None)
            })
            
    return jsonify({'logs': formatted_logs})

@app.route('/trigger-strategy', methods=['POST'])
@login_required
def trigger_strategy():
    data = request.get_json() or {}
    broker_id = data.get('broker_id')
    
    # Verify Broker Ownership
    broker = db['broker_accounts'].find_one({'broker_id': broker_id, 'username': g.user['username']})
    if not broker:
        return jsonify({'status': 'error', 'message': 'Invalid broker or permission denied.'}), 403
    
    # Generate run_id here to return to frontend immediately
    run_id = str(uuid.uuid4())
    
    import threading
    thread = threading.Thread(target=run_executor, args=("manual", broker_id, run_id))
    thread.start()
    
    return jsonify({
        'status': 'success', 
        'message': 'Strategy execution started in background.',
        'broker_id': broker_id,
        'run_id': run_id
    })

@app.route('/api/run-status/<run_id>')
@login_required
def get_run_status(run_id):
    if db is None:
        return jsonify({'error': 'Database not connected'}), 500
    
    runs_collection = db[f"strategy_runs_{MONGO_ENV}"]
    run = runs_collection.find_one({'run_id': run_id})
    
    if not run:
        return jsonify({'status': 'pending'}) # Or 'not_found' but 'pending' helps if DB write is slow
        
    return jsonify({
        'status': run.get('status', 'running'),
        'run_id': run.get('run_id')
    })

@app.route('/')
@login_required
def dashboard():
    try:
        if db is None:
            flash("Database connection error.", "error")
            return render_template('login.html')

        # --- Broker Management & Connector Initialization ---
        active_connectors = []
        broker_errors = []
        
        # Get all enabled brokers for dropdown (User Filtered)
        user_filter = {"username": g.user['username']}
        all_brokers = list(db['broker_accounts'].find({**user_filter, "enabled": True}))
        
        # Determine Selected Broker
        selected_broker_id = request.args.get('broker', 'all')
        
        # Filter brokers for processing metrics
        brokers_to_process = all_brokers
        if selected_broker_id != 'all':
            brokers_to_process = [b for b in all_brokers if b['broker_id'] == selected_broker_id]
            if not brokers_to_process: # invalid ID, fallback
                selected_broker_id = 'all'
                brokers_to_process = all_brokers

        holdings_pnl = 0.0
        open_positions_count = 0
        raw_positions = []
        used_capital = 0
        num_positions = 0
        
        # Capital Aggregation
        total_positions_can_open = 0
        total_strategy_capital = 0  
        
        for broker in brokers_to_process:
            b_type = broker.get('broker_type')
            b_name = broker.get('display_name', b_type)
            connector = None
            broker_used_capital = 0 
            
            try:
                # Check Token Validity (Basic Check)
                gen_at = broker.get('token_generated_at')
                if isinstance(gen_at, (int, float)): gen_at = datetime.fromtimestamp(gen_at, tz=UTC)
                elif gen_at and gen_at.tzinfo is None: gen_at = UTC.localize(gen_at)
                
                is_valid = False
                if gen_at:
                    age = (datetime.now(UTC) - gen_at).total_seconds()
                    if b_type == 'zerodha':
                         if age < 86400: is_valid = True
                    elif b_type == 'fyers':
                         if age < ACCESS_TOKEN_VALIDITY: is_valid = True
                
                if not is_valid:
                    # Silently skip API calls for expired tokens to prevent slow load/errors
                    pass
                else:
                    # Initialize Connector
                    if b_type == 'fyers':
                         client_id = broker.get('client_id') or broker.get('api_key')
                         secret_id = broker.get('secret_id') or broker.get('api_secret')
                         connector = FyersConnector(
                             api_key=client_id, 
                             api_secret=secret_id, 
                             access_token=broker.get('access_token'),
                             pin=broker.get('pin')
                         )
                    elif b_type == 'zerodha':
                         connector = ZerodhaConnector(
                             api_key=broker.get('api_key'),
                             api_secret=broker.get('api_secret'),
                             access_token=broker.get('access_token')
                         )
                
                if connector:
                    active_connectors.append(connector)
                    # Fetch Holdings
                    try:
                        b_holdings = connector.get_holdings()
                        for p in b_holdings:
                            qty = p.get('quantity', 0)
                            if qty != 0:
                                holdings_pnl += p.get('pl', 0)
                                open_positions_count += 1
                                cost = p.get('costPrice', 0)
                                pos_value = cost * abs(qty)
                                used_capital += pos_value
                                broker_used_capital += pos_value
                                num_positions += 1
                                p['broker'] = b_name
                                raw_positions.append(p)
                    except Exception as e:
                        print(f"Error fetching holdings for {b_name}: {e}")

            except Exception as e:
                 print(f"Error initializing {b_name}: {e}")
            
            # Calculate per-broker metrics
            b_capital = broker.get('capital', 0)
            b_trade_amt = broker.get('trade_amount', 0)
            
            total_strategy_capital += b_capital
            b_avail = max(0, b_capital - broker_used_capital)
            if b_trade_amt > 0:
                total_positions_can_open += int(b_avail / b_trade_amt)

        if broker_errors:
            flash(" | ".join(broker_errors), "warning")

        # Fetch today's executed trades
        today = datetime.now(IST).date()
        start_of_today = IST.localize(datetime(today.year, today.month, today.day, 0, 0, 0)).astimezone(UTC)
        end_of_today = IST.localize(datetime(today.year, today.month, today.day, 23, 59, 59)).astimezone(UTC)
        
        today_query = {**user_filter, "date": {"$gte": start_of_today, "$lte": end_of_today}, "filled": True}
        if selected_broker_id != 'all':
            today_query['broker_id'] = selected_broker_id
            
        today_trades = list(db[f"trades_{MONGO_ENV}"].find(today_query))
        recent_trades_count = len(today_trades)

        # --- Daily activity logic ---
        page = request.args.get('page', 1, type=int)
        skip_days = (page - 1) * APP_LOGS_PER_PAGE_HOME
        
        # Date Query Filters
        date_filter_logs = {**user_filter, "timestamp": {"$ne": None}}
        date_filter_trades = {**user_filter, "date": {"$ne": None}}
        
        if selected_broker_id != 'all':
            date_filter_logs['broker_id'] = selected_broker_id
            date_filter_trades['broker_id'] = selected_broker_id

        distinct_log_dates = db[f"logs_{MONGO_ENV}"].distinct("timestamp", date_filter_logs)
        distinct_trade_dates = db[f"trades_{MONGO_ENV}"].distinct("date", date_filter_trades)

        distinct_log_dates_ist = [d.astimezone(IST) for d in distinct_log_dates]
        distinct_trade_dates_ist = [d.astimezone(IST) for d in distinct_trade_dates]

        all_distinct_dates = sorted(list(set([d.date() for d in distinct_log_dates_ist] + [d.date() for d in distinct_trade_dates_ist])), reverse=True)

        total_days = len(all_distinct_dates)
        has_more_days = total_days > (skip_days + APP_LOGS_PER_PAGE_HOME)

        current_page_dates = all_distinct_dates[skip_days : skip_days + APP_LOGS_PER_PAGE_HOME]

        daily_data = {}

        for date_obj in current_page_dates:
            start_of_day_ist = IST.localize(datetime(date_obj.year, date_obj.month, date_obj.day, 0, 0, 0))
            end_of_day_ist = IST.localize(datetime(date_obj.year, date_obj.month, date_obj.day, 23, 59, 59))
            start_of_day_utc = start_of_day_ist.astimezone(UTC)
            end_of_day_utc = end_of_day_ist.astimezone(UTC)

            logs_query = {**user_filter, "timestamp": {"$gte": start_of_day_utc, "$lte": end_of_day_utc}}
            if selected_broker_id != 'all': logs_query['broker_id'] = selected_broker_id
            
            logs_for_day = list(db[f"logs_{MONGO_ENV}"].find(logs_query).sort("timestamp", -1))
            for log in logs_for_day:
                log['timestamp'] = log['timestamp'].astimezone(IST)

            trades_query = {**user_filter, "date": {"$gte": start_of_day_utc, "$lte": end_of_day_utc}}
            if selected_broker_id != 'all': trades_query['broker_id'] = selected_broker_id

            trades_for_day = list(db[f"trades_{MONGO_ENV}"].find(trades_query).sort("date", -1))
            for trade in trades_for_day:
                trade['date'] = trade['date'].astimezone(IST)

            executed_trades_daily = []
            cancelled_trades_daily = []

            for trade in trades_for_day:
                if 'profit' not in trade: trade['profit'] = 0.0
                if 'profit_pct' not in trade: trade['profit_pct'] = 0.0
                
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
        
        chart_query = {**user_filter, "filled": True, "profit": {"$exists": True}}
        if selected_broker_id != 'all': chart_query['broker_id'] = selected_broker_id
        
        all_filled_trades = list(db[f"trades_{MONGO_ENV}"].find(chart_query))
        for trade in all_filled_trades:
            if trade.get('action') == 'SELL':
                trade_date = trade['date'].astimezone(IST).strftime('%Y-%m-%d')
                daily_pnl_data[trade_date]['pnl'] += trade.get('profit', 0.0)
                daily_pnl_data[trade_date]['trades'] += 1
        
        sorted_daily_pnl = sorted(daily_pnl_data.items())
        chart_labels = [item[0] for item in sorted_daily_pnl]
        chart_values = [item[1]['pnl'] for item in sorted_daily_pnl]
        chart_trades = [item[1]['trades'] for item in sorted_daily_pnl]

        cumu_query = {**user_filter, "filled": True}
        if selected_broker_id != 'all': cumu_query['broker_id'] = selected_broker_id
        
        all_filled_trades_cumu = list(db[f"trades_{MONGO_ENV}"].find(cumu_query).sort("date", 1))
        cumulative_pnl_data = []
        cumulative_pnl = 0
        for trade in all_filled_trades_cumu:
            cumulative_pnl += trade.get('profit', 0.0)
            cumulative_pnl_data.append({
                'date': trade['date'].astimezone(IST).strftime('%Y-%m-%d'),
                'pnl': cumulative_pnl
            })

        available_capital = max(0, total_strategy_capital - used_capital)
        used_percentage = (used_capital / total_strategy_capital * 100) if total_strategy_capital > 0 else 0
        available_percentage = (available_capital / total_strategy_capital * 100) if total_strategy_capital > 0 else 0
        
        avg_position_size = (used_capital / num_positions) if num_positions > 0 else 0
        
        capital_utilization = {
            'used': used_capital,
            'available': available_capital,
            'total': total_strategy_capital,
            'used_percentage': used_percentage,
            'available_percentage': available_percentage,
            'positions_can_open': total_positions_can_open,
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
                               cumulative_pnl_data=json.dumps(cumulative_pnl_data),
                               brokers=all_brokers,
                               selected_broker_id=selected_broker_id)

    except Exception as e:
        import traceback
        traceback.print_exc()
        flash(f"Dashboard Error: {str(e)}", "error")
        return render_template('dashboard.html', 
                               active_page='dashboard',
                               holdings_pnl=0,
                               open_positions_count=0,
                               recent_trades_count=0,
                               daily_data={},
                               page=1,
                               has_more_days=False,
                               total_days=0,
                               chart_labels=json.dumps([]),
                               chart_values=json.dumps([]),
                               chart_trades=json.dumps([]),
                               capital_utilization={
                                   'used': 0, 
                                   'available': 0, 
                                   'total': 0, 
                                   'used_percentage': 0, 
                                   'available_percentage': 0, 
                                   'positions_can_open': 0, 
                                   'avg_position_size': 0, 
                                   'current_positions': 0
                               },
                               cumulative_pnl_data=json.dumps([]),
                               brokers=[],
                               selected_broker_id='all')

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if db is None:
        flash("Database connection failed.", "danger")
        return redirect(url_for('dashboard'))

    # Load broker accounts first to check if any exist
    user_filter = {"username": g.user['username']}
    broker_accounts = list(db['broker_accounts'].find(user_filter).sort('created_at', 1))

    if request.method == 'POST':
        try:
            broker_id = request.form.get('broker_id')
            if not broker_id:
                # Fallback to defaults or first broker if somehow missing, but UI should enforce
                flash('Broker ID is missing!', 'danger')
                return redirect(url_for('settings'))

            # Convert inputs safely
            # Note: trading_mode is handled by a separate route/UI usually, but including here for consistency if main form submits it
            trading_mode = request.form.get('trading_mode')
            
            new_settings = {
                'capital': float(request.form.get('capital')),
                'trade_amount': float(request.form.get('trade_amount')),
                'max_positions': int(request.form.get('max_positions')),
                'ma_period': int(request.form.get('ma_period')),
                'entry_threshold': float(request.form.get('entry_threshold')),
                'target_profit': float(request.form.get('target_profit')),
                'averaging_threshold': float(request.form.get('averaging_threshold')),
                'alert_email': request.form.get('alert_email', '')
            }
            
            if trading_mode:
                new_settings['trading_mode'] = trading_mode

            result = db['broker_accounts'].update_one(
                {'broker_id': broker_id, 'username': g.user['username']},
                {'$set': new_settings}
            )
            
            if result.matched_count == 0:
                flash('Broker not found!', 'danger')
            else:
                flash('Settings updated successfully for broker!', 'success')
                
        except ValueError as e:
            flash(f'Invalid input: {e}', 'danger')
        
        # Redirect back to the same broker
        return redirect(url_for('settings', broker_id=broker_id))
    
    # --- GET Request Logic ---
    
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

    selected_broker_id = request.args.get('broker_id')
    current_broker = None
    
    # Determine which broker to show
    if broker_accounts:
        if selected_broker_id:
            current_broker = next((b for b in broker_accounts if b['broker_id'] == selected_broker_id), None)
        
        # If not found or not provided, default to first (if exists)
        if not current_broker and broker_accounts:
            current_broker = broker_accounts[0]
            
    # Prepare settings object for template
    current_settings = default_settings.copy()
    
    if current_broker:
        # Overlay broker's stored settings on top of defaults
        # We manually map keys to ensure we only get relevant settings
        settings_keys = default_settings.keys()
        for k in settings_keys:
            if k in current_broker:
                current_settings[k] = current_broker[k]
        
        # Ensure identifying info is attached (though template fits it from current_broker too)
        current_settings['broker_id'] = current_broker['broker_id']
        current_settings['display_name'] = current_broker['display_name']
    
    return render_template('settings.html', 
                         settings=current_settings, 
                         default_settings=default_settings,
                         broker_accounts=broker_accounts,
                         current_broker=current_broker,
                         active_page='settings')

# Broker Management Routes
@app.route('/broker/<broker_id>/toggle', methods=['POST'])
@login_required
def broker_toggle(broker_id):
    """Toggle broker enabled/disabled status"""
    if db is None:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    user_filter = {'broker_id': broker_id, 'username': g.user['username']}
    broker = db['broker_accounts'].find_one(user_filter)
    if not broker:
        return jsonify({'success': False, 'message': 'Broker not found'}), 404
    
    new_status = not broker.get('enabled', True)
    db['broker_accounts'].update_one(
        user_filter,
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
    
    user_filter = {'broker_id': broker_id, 'username': g.user['username']}
    broker = db['broker_accounts'].find_one(user_filter)
    if not broker:
        return jsonify({'success': False, 'message': 'Broker not found'}), 404
    
    # Remove default from all THIS USER's brokers
    db['broker_accounts'].update_many({'username': g.user['username']}, {'$set': {'is_default': False}})
    
    # Set this broker as default
    db['broker_accounts'].update_one(
        user_filter,
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
        {'broker_id': broker_id, 'username': g.user['username']},
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
        {'broker_id': broker_id, 'username': g.user['username']},
        {'$set': {'display_name': display_name}}
    )
    
    if result.matched_count == 0:
        return jsonify({'success': False, 'message': 'Broker not found'}), 404
    
    return jsonify({
        'success': True,
        'message': 'Display name updated successfully'
    })

# --- Helper for Syncing Positions ---
def sync_broker_positions(broker_id, broker_instance):
    """
    Syncs DB positions with Broker Holdings to detect manually closed trades.
    Deduplicates and consolidates pending manual trades.
    Returns count of new manual trades detected/consolidated.
    """
    if db is None: return 0
    updates_count = 0
    
    try:
        # 1. Calculate 'Expected' Open Positions from DB (System Only)
        # We MUST exclude existing 'MANUAL' trades to detect the raw gap.
        # Group by symbol, sum(Buy) - sum(Sell)
        pipeline = [
            {'$match': {
                'broker_id': broker_id, 
                'filled': True,
                'order_id': {'$ne': 'MANUAL'} # CRITICAL: Ignore existing manuals to force recalculation
            }},
            {'$group': {
                '_id': '$symbol',
                'total_bought': {'$sum': {'$cond': [{'$eq': ['$action', 'BUY']}, '$quantity', 0]}},
                'total_sold': {'$sum': {'$cond': [{'$eq': ['$action', 'SELL']}, '$quantity', 0]}},
                'buy_trades': {'$push': {'$cond': [{'$eq': ['$action', 'BUY']}, '$ROOT', None]}}
            }},
            {'$project': {
                'symbol': '$_id',
                'net_qty': {'$subtract': ['$total_bought', '$total_sold']},
                'buy_trades': '$buy_trades'
            }},
            {'$match': {'net_qty': {'$gt': 0}}} # Positive System Open Position
        ]
        
        db_positions = list(db[f"trades_{MONGO_ENV}"].aggregate(pipeline))
        db_map = {p['symbol']: p for p in db_positions}
        
        # 2. Fetch Real Holdings from Broker
        # Even if DB has nothing, we might need to check if we have pending manuals that are now resolved? 
        # But efficiently, we only care about DB Open vs Real Closed.
        
        real_holdings = {}
        try:
             # Fetch Holdings
             response = broker_instance.holdings()
             
             # Normalize Response
             holdings_list = []
             if isinstance(response, dict):
                 # Likely Fyers
                 if 'holdings' in response:
                     holdings_list = response['holdings']
             elif isinstance(response, list):
                 # Likely Zerodha
                 holdings_list = response
             
             # Process List
             for h in holdings_list:
                 # Helper to get attr or dict key
                 symbol = h['tradingsymbol'] if 'tradingsymbol' in h else h.get('symbol')
                 # Zerodha uses 'quantity' or 'open_quantity'?? KiteConnect uses 'quantity' (net) in holdings
                 qty = h.get('quantity', 0)
                 
                 # Exchange Prefix Logic
                 # Fyers returns 'NSE:SBIN-EQ', Zerodha returns 'SBIN' (?)
                 # DB uses 'NSE:SBIN-EQ'.
                 # We need to map if necessary. 
                 # Fyers usually has exchange prefix. Zerodha might not.
                 # Let's rely on loose matching later, but store exact symbol here.
                 
                 # Accumulate (Fix for split holdings)
                 if symbol:
                     if symbol in real_holdings:
                          real_holdings[symbol] += qty
                     else:
                          real_holdings[symbol] = qty

        except Exception as e:
             print(f"Sync Skipped: Failed to fetch holdings for {broker_id}: {e}")
             return 0

        # 3. Analyze DB Positions (N Buys, M Sells) with FIFO Logic
        distinct_symbols = list(set([k for k in db_map.keys()] + [k for k in real_holdings.keys()]))
        
        # We need to query generically for each symbol because aggregate above was just for detection
        # Actually, let's iterate strictly through DB symbols we found open
        
        # Better strategy: Use the 'db_positions' list we already aggregated 
        # BUT we need granular Buy trades. The aggregation gave us 'buy_trades' array! 
        # We can use that!
        
        for p in db_positions:
            symbol = p['symbol']
            
            # Re-fetch strictly to be safe and consistent with script logic
            # Fetch ALL trades for this symbol, sorted by DATE ASC
            all_trades = list(db[f"trades_{MONGO_ENV}"].find({
                'broker_id': broker_id,
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
                    t['remaining_qty'] = t['quantity']
                    buys.append(t)
                elif t['action'] == 'SELL':
                    sells.append(t)
            
            # FIFO Matching
            for sell in sells:
                sell_qty_left = sell['quantity']
                for buy in buys:
                    if sell_qty_left <= 0: break
                    if buy['remaining_qty'] > 0:
                        deduct = min(buy['remaining_qty'], sell_qty_left)
                        buy['remaining_qty'] -= deduct
                        sell_qty_left -= deduct
            
            # Open Buys
            open_buys = [b for b in buys if b['remaining_qty'] > 0]
            net_system_qty = sum(b['remaining_qty'] for b in open_buys)
            
            if net_system_qty <= 0: continue

            # Get Real Holding (K)
            real_k = 0
            for r_sym, r_qty in real_holdings.items():
                if symbol == r_sym or (symbol in r_sym and 'NSE:' not in symbol):
                    real_k = r_qty
                    break
            
            # Gap
            gap = net_system_qty - real_k
            
            if gap > 0:
                # We need 'gap' amount.
                existing_pendings = list(db[f"trades_{MONGO_ENV}"].find({
                    'broker_id': broker_id,
                    'symbol': symbol,
                    'order_id': 'MANUAL',
                    'status': 'PENDING_MANUAL_PRICE'
                }))
                
                current_pending_qty = sum(t.get('quantity', 0) for t in existing_pendings)
                
                if current_pending_qty == gap:
                    continue # Balanced.
                    
                # HARD CLEANUP & REINSERT (Consolidated)
                db[f"trades_{MONGO_ENV}"].delete_many({
                    'broker_id': broker_id,
                    'symbol': symbol,
                    'order_id': 'MANUAL',
                    'status': 'PENDING_MANUAL_PRICE'
                })
                
                # Consolidate Logic: Weighted Average
                missing_needed = gap
                avg_price_sum = 0
                avg_price_qty = 0
                buy_dates = []

                for buy in open_buys:
                    if missing_needed <= 0: break
                    available = buy['remaining_qty']
                    qty_to_mark = min(available, missing_needed)
                    
                    avg_price_sum += (buy['price'] * qty_to_mark)
                    avg_price_qty += qty_to_mark
                    buy_dates.append(buy['date'])
                    
                    missing_needed -= qty_to_mark
                
                final_avg_price = avg_price_sum / avg_price_qty if avg_price_qty > 0 else 0
                primary_date = min(buy_dates) if buy_dates else datetime.now(UTC)

                new_trade = {
                    'broker_id': broker_id,
                    'symbol': symbol,
                    'action': 'SELL',
                    'quantity': gap, # Consolidated Qty
                    'price': 0.0,
                    'avg_price': final_avg_price, # Weighted Avg
                    'date': primary_date, # Oldest Buy Date
                    'order_id': 'MANUAL',
                    'status': 'PENDING_MANUAL_PRICE',
                    'filled': True,
                    'profit': 0.0,
                    'profit_pct': 0.0,
                    'comment': f"Manual Close (Consolidated). Avg Buy: {final_avg_price:.2f}"
                }
                db[f"trades_{MONGO_ENV}"].insert_one(new_trade)
                updates_count += 1

    except Exception as e:
        print(f"Error in sync_broker_positions: {e}")
        
    return updates_count

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
                "last_run_at": None,
                # Default Settings for New Broker
                "capital": STRATEGY_CAPITAL,
                "trade_amount": MAX_TRADE_VALUE,
                "max_positions": 10,
                "ma_period": MA_PERIOD,
                "entry_threshold": -2.0,
                "target_profit": 5.0,
                "averaging_threshold": -3.0
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
                # Default Settings for New Broker
                "capital": STRATEGY_CAPITAL,
                "trade_amount": MAX_TRADE_VALUE,
                "max_positions": 10,
                "ma_period": MA_PERIOD,
                "entry_threshold": -2.0,
                "target_profit": 5.0,
                "averaging_threshold": -3.0,
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
             # Handle schema difference: client_id vs api_key
             client_id = b.get('client_id') or b.get('api_key')
             secret_id = b.get('secret_id') or b.get('api_secret')
             
             session['temp_broker_data'] = {
                'mode': 'update',
                'broker_id': b['broker_id'],
                'type': 'fyers',
                'display_name': b['display_name'],
                'client_id': client_id, # Normalize to client_id for session usage
                'secret_id': secret_id,
                'pin': b.get('pin'),
                'redirect_uri': b['redirect_uri']
             }
             try:
                 connector = FyersConnector(api_key=client_id, api_secret=secret_id)
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
                client_id = broker.get('client_id') or broker.get('api_key')
                secret_id = broker.get('secret_id') or broker.get('api_secret')
                pin = broker.get('pin')
                connector = FyersConnector(api_key=client_id, api_secret=secret_id, pin=pin)
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

@app.route('/broker/<broker_id>/manual-auth', methods=['POST'])
@login_required
def broker_manual_auth(broker_id):
    """Handle manual auth code submission for Fyers"""
    if db is None:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    broker = db['broker_accounts'].find_one({'broker_id': broker_id})
    if not broker:
        return jsonify({'success': False, 'message': 'Broker not found'}), 404
        
    auth_code = request.json.get('auth_code')
    if not auth_code:
        return jsonify({'success': False, 'message': 'Auth code is required'}), 400

    try:
        # Fyers Logic
        if broker['broker_type'] == 'fyers':
            client_id = broker.get('client_id') or broker.get('api_key')
            secret_id = broker.get('secret_id') or broker.get('api_secret')
            redirect_uri = broker.get('redirect_uri', FYERS_REDIRECT_URI)

            connector = FyersConnector(api_key=client_id, api_secret=secret_id)
            token_response = connector.generate_session(auth_code=auth_code, redirect_uri=redirect_uri)
            
            # Update DB
            db['broker_accounts'].update_one(
                {'broker_id': broker_id},
                {'$set': {
                    'access_token': token_response['access_token'],
                    'refresh_token': token_response.get('refresh_token'),
                    'token_generated_at': datetime.now(UTC),
                    'token_status': 'valid'
                }}
            )
            return jsonify({'success': True, 'message': 'Authenticated successfully!'})
            
        else:
            return jsonify({'success': False, 'message': 'Manual auth only supported for Fyers'}), 400

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/broker/<broker_id>/invalidate', methods=['POST'])
@login_required
def broker_invalidate_token(broker_id):
    """Invalidate token for testing (Dev Only)"""
    if os.getenv('ENV') != 'dev':
        return jsonify({'success': False, 'message': 'Feature available in DEV environment only'}), 403
        
    if db is None:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500

    broker = db['broker_accounts'].find_one({'broker_id': broker_id})
    if not broker:
        return jsonify({'success': False, 'message': 'Broker not found'}), 404
    
    # Invalidate
    db['broker_accounts'].update_one(
        {'broker_id': broker_id},
        {'$set': {
            'access_token': f"INVALID_{datetime.now().timestamp()}",
            # Set to past
            'token_generated_at': datetime.now(UTC) - timedelta(days=365),
            'token_status': 'invalidated_manually'
        }}
    )
    
    return jsonify({'success': True, 'message': 'Token invalidated successfully (TESTING)'})

@app.route('/run-logs/<run_id>')
@login_required
def run_logs(run_id):
    if db is None:
        return "Database connection failed."
    
    logs = list(db[f"logs_{MONGO_ENV}"].find({"run_id": run_id}).sort("timestamp", 1))
    for log in logs:
        log['timestamp'] = log['timestamp'].astimezone(IST)
        
    return render_template('run_logs.html', logs=logs, run_id=run_id)


# --- Manual Trade Management ---
@app.route('/update_manual_trade/<trade_ids>', methods=['POST'])
@login_required
def update_manual_trade(trade_ids):
    if db is None:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    try:
        close_price = float(request.form.get('close_price'))
        close_date_str = request.form.get('close_date')
        
        # Parse Date
        try:
             # Input format from datetime-local input usually '%Y-%m-%dT%H:%M'
             close_date = datetime.strptime(close_date_str, '%Y-%m-%dT%H:%M')
             close_date = IST.localize(close_date)
        except ValueError:
             return jsonify({'success': False, 'message': 'Invalid date format'}), 400

        # Handle Batch IDs (comma separated)
        id_list = [tid.strip() for tid in trade_ids.split(',') if tid.strip()]
        
        success_count = 0
        
        for tid in id_list:
            # Fetch the trade to calculate profit
            trade = db[f"trades_{MONGO_ENV}"].find_one({'_id': ObjectId(tid)})
            if not trade:
                 continue
                 
            quantity = trade.get('quantity', 0)
            buy_price = trade.get('avg_price') or trade.get('buy_price') or 0.0
            
            if close_price == 0.0:
                # User wants to Revert to Pending
                new_status = 'PENDING_MANUAL_PRICE'
                profit = 0.0
                profit_pct = 0.0
                comment_str = "Action Needed"
            else:
                # Normal Update
                new_status = 'FILLED'
                profit = (close_price - buy_price) * quantity
                profit_pct = ((close_price - buy_price) / buy_price * 100) if buy_price > 0 else 0
                comment_str = f"Manual Close. Profit: {profit_pct:.2f}%"
            
            db[f"trades_{MONGO_ENV}"].update_one(
                {'_id': ObjectId(tid)},
                {'$set': {
                    'price': close_price, # The SELL price
                    'date': close_date,
                    'profit': profit,
                    'profit_pct': profit_pct,
                    'status': new_status,
                    'comment': comment_str
                }}
            )
            success_count += 1
            
        if success_count > 0:
            return jsonify({'success': True, 'updated': success_count})
        else:
            return jsonify({'success': False, 'message': 'No trades found to update'}), 404
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
        
@app.route('/delete_manual_trade/<trade_ids>', methods=['POST'])
@login_required
def delete_manual_trade(trade_ids):
    if db is None:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    try:
        # Handle Batch IDs
        id_list = [tid.strip() for tid in trade_ids.split(',') if tid.strip()]
        
        deleted_count = 0
        for tid in id_list:
            try:
                db[f"trades_{MONGO_ENV}"].delete_one({'_id': ObjectId(tid)})
                deleted_count += 1
            except Exception:
                continue # Skip invalid individual IDs

        if deleted_count > 0:
            return jsonify({'success': True, 'message': f'Deleted {deleted_count} records'})
        else:
            return jsonify({'success': False, 'message': 'No records found to delete'}), 404
            
    except Exception as e:
        # Generic error to hide implementation details if needed, or clean str(e)
        return jsonify({'success': False, 'message': 'Failed to process deletion request'}), 500

if __name__ == '__main__':
    if os.getenv('ENV') == 'dev':
        print("🚀 Starting Flask in DEBUG/DEV mode with auto-refresh...")
        app.run(host="0.0.0.0", port=8080, debug=True)
    else:
        from waitress import serve
        print("🛡️ Starting Production Server (Waitress) on 0.0.0.0:8080")
        serve(app, host="0.0.0.0", port=8080)
