from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash, g
from auth import AuthManager, login_required
from pymongo import MongoClient
from datetime import datetime, timedelta
from collections import defaultdict
import os
from dotenv import load_dotenv
import json
import time
import hashlib
import requests
from fyers_apiv3 import fyersModel
from apscheduler.schedulers.background import BackgroundScheduler
import uuid
import subprocess
import random

load_dotenv() # Load environment variables from .env file

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'a_very_secret_key_that_should_be_changed')

auth_manager = None # Will be initialized after db connection

# --- Database Connection ---
MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'nifty_shop')
MONGO_ENV = os.getenv('MONGO_ENV', 'test')
print(MONGO_URI, MONGO_DB_NAME, MONGO_ENV)

if MONGO_URI:
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB_NAME]
    # MongoDB Configuration for Fyers tokens
    mongo_client_fyers = MongoClient(MONGO_URI)
    fyers_tokens_collection = mongo_client_fyers[MONGO_DB_NAME]['fyers_tokens']
    auth_manager = AuthManager(db)

    # Create initial user if no users exist
    if auth_manager.users_collection.count_documents({}) == 0:
        print("No users found. Creating initial user 'chaitu_shop'.")
        auth_manager.create_user("chaitu_shop", "Chaitu2@nifty_shop")
else:
    print("Could not find MongoDB URI in .env file")
    db = None
    mongo_client_fyers = None
    fyers_tokens_collection = None
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

LOGS_PER_PAGE = int(os.getenv('APP_LOGS_PER_PAGE_HOME', 10)) # Number of trading days to show per page

# --- Fyers API Configuration (from token_refresh.py) ---
CLIENT_ID = os.getenv('FYERS_CLIENT_ID')           # Your Fyers client ID
SECRET_ID = os.getenv('FYERS_SECRET_ID')               # Your Fyers secret key
PIN = os.getenv('FYERS_PIN')                          # Your 4-digit PIN for token refresh and generation
REDIRECT_URI = os.getenv('FYERS_REDIRECT_URI')  # Must match your Fyers app config

REFRESH_TOKEN_URL = "https://api-t1.fyers.in/api/v3/validate-refresh-token"

ACCESS_TOKEN_VALIDITY = 24 * 60 * 60        # 1 day
REFRESH_TOKEN_VALIDITY = 15 * ACCESS_TOKEN_VALIDITY  # 15 days

# Initialize Fyers session model
fyers_session = fyersModel.SessionModel(
    client_id=CLIENT_ID,
    secret_key=SECRET_ID,
    redirect_uri=REDIRECT_URI,
    response_type="code",
    grant_type="authorization_code"
)

def save_tokens(token_data):
    if fyers_tokens_collection is not None:
        fyers_tokens_collection.update_one(
            {"_id": "fyers_token_data"},
            {"$set": token_data},
            upsert=True
        )
        print("[INFO] Token data saved to MongoDB.")
    else:
        print("[ERROR] MongoDB connection not established for Fyers tokens. Cannot save tokens.")

def load_tokens():
    if fyers_tokens_collection is not None:
        return fyers_tokens_collection.find_one({"_id": "fyers_token_data"})
    else:
        print("[ERROR] MongoDB connection not established for Fyers tokens. Cannot load tokens.")
        return None

def is_access_token_valid(generated_at):
    if generated_at is None:
        return False
    token_time = datetime.fromtimestamp(generated_at)
    return datetime.now() < token_time + timedelta(seconds=ACCESS_TOKEN_VALIDITY)

def is_refresh_token_valid(generated_at):
    if generated_at is None:
        return False
    token_time = datetime.fromtimestamp(generated_at)
    return datetime.now() < token_time + timedelta(seconds=REFRESH_TOKEN_VALIDITY)

def refresh_access_token_custom(refresh_token, client_id, secret_id, pin):
    app_id_hash = hashlib.sha256(f"{client_id}:{secret_id}".encode()).hexdigest()
    headers = {"Content-Type": "application/json"}
    payload = {
        "grant_type": "refresh_token",
        "appIdHash": app_id_hash,
        "refresh_token": refresh_token,
        "pin": pin
    }
    resp = requests.post(REFRESH_TOKEN_URL, json=payload, headers=headers)
    if resp.status_code == 200:
        data = resp.json()
        if data.get("code") == 200 and "access_token" in data:
            token_data = {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token", refresh_token),
                "generated_at": int(time.time())
            }
            save_tokens(token_data)
            return token_data
    return None

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

    # Calculate dashboard metrics
    holdings_pnl = 0.0
    open_positions_count = 0
    recent_trades_count = 0 # This will now be for today's trades only

    try:
        token_data = load_tokens()
        access_token = token_data.get("access_token") if token_data else ""
        if access_token and is_access_token_valid(token_data.get("generated_at")):
            fyers = fyersModel.FyersModel(client_id=CLIENT_ID, token=access_token, log_path='./')
            holdings_response = fyers.holdings()
            if holdings_response.get('s') == 'ok':
                raw_positions = holdings_response.get('holdings', [])
                for p in raw_positions:
                    if p.get('quantity', 0) != 0:
                        holdings_pnl += p.get('pl', 0)
                        open_positions_count += 1
    except Exception as e:
        print(f"Error fetching holdings/positions for dashboard: {e}")

    # Fetch today's executed trades for the dashboard metric
    today = datetime.now().date()
    start_of_today = datetime(today.year, today.month, today.day, 0, 0, 0)
    end_of_today = datetime(today.year, today.month, today.day, 23, 59, 59)
    
    today_trades = list(db[f"trades_{MONGO_ENV}"].find({
        "date": {"$gte": start_of_today, "$lte": end_of_today},
        "filled": True
    }))
    recent_trades_count = len(today_trades)

    return render_template('dashboard.html',
                           active_page='dashboard',
                           holdings_pnl=holdings_pnl,
                           open_positions_count=open_positions_count,
                           recent_trades_count=recent_trades_count)

@app.route('/trading-overview')
@login_required
def trading_overview():
    if db is None:
        return "Database connection failed. Please check your MongoDB URI in files.txt"

    # --- Existing performance logic ---
    token_data = load_tokens()
    access_token = token_data.get("access_token") if token_data else ""

    if not access_token or not is_access_token_valid(token_data.get("generated_at")):
        flash("Access token is invalid or expired. Please refresh it.", "warning")
        return redirect(url_for('token_refresh'))

    fyers = fyersModel.FyersModel(client_id=CLIENT_ID, token=access_token, log_path='./')

    try:
        holdings_response = fyers.holdings()
        
        if holdings_response.get('s') == 'ok':
            raw_positions = holdings_response.get('holdings', [])
            current_positions = []
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
        else:
            current_positions = []
            flash(f"Failed to fetch holdings: {holdings_response.get('message', 'Unknown error')}", "danger")
    except Exception as e:
        current_positions = []
        flash(f"An error occurred while fetching holdings: {e}", "danger")

    all_filled_trades = list(db[f"trades_{MONGO_ENV}"].find({"filled": True}).sort("date", -1))

    open_position_symbols = {pos['symbol'] for pos in current_positions}

    open_trades = []
    closed_trades = []

    trades_by_symbol = defaultdict(list)
    for trade in all_filled_trades:
        trades_by_symbol[trade['symbol']].append(trade)

    for symbol, trades in trades_by_symbol.items():
        if symbol in open_position_symbols:
            latest_buy = max((t for t in trades if t.get('action') == 'BUY'), key=lambda x: x['date'], default=None)
            if latest_buy:
                open_trades.append(latest_buy)
        else:
            closed_trades.extend(trades)

    closed_trades.sort(key=lambda x: x['date'], reverse=True)

    for trade in closed_trades:
        if 'profit' not in trade:
            trade['profit'] = 0.0
        if 'profit_pct' not in trade:
            trade['profit_pct'] = 0.0

    total_pnl = sum(trade.get('profit', 0.0) for trade in closed_trades)
    winning_trades = [trade for trade in closed_trades if trade.get('profit', 0.0) > 0]
    losing_trades = [trade for trade in closed_trades if trade.get('profit', 0.0) < 0]

    win_loss_ratio = len(winning_trades) / len(losing_trades) if len(losing_trades) > 0 else (1 if len(winning_trades) > 0 else 0)
    average_winning_trade = sum(trade['profit'] for trade in winning_trades) / len(winning_trades) if len(winning_trades) > 0 else 0
    average_losing_trade = sum(trade['profit'] for trade in losing_trades) / len(losing_trades) if len(losing_trades) > 0 else 0

    # --- New daily activity logic from old home route ---
    page = request.args.get('page', 1, type=int)
    skip_days = (page - 1) * LOGS_PER_PAGE

    distinct_log_dates = db[f"logs_{MONGO_ENV}"].distinct("timestamp", {"timestamp": {"$ne": None}})
    distinct_trade_dates = db[f"trades_{MONGO_ENV}"].distinct("date", {"date": {"$ne": None}})

    all_distinct_dates = sorted(list(set([d.date() for d in distinct_log_dates] + [d.date() for d in distinct_trade_dates])), reverse=True)

    total_days = len(all_distinct_dates)
    has_more_days = total_days > (skip_days + LOGS_PER_PAGE)

    current_page_dates = all_distinct_dates[skip_days : skip_days + LOGS_PER_PAGE]

    daily_data = {}

    for date_obj in current_page_dates:
        start_of_day = datetime(date_obj.year, date_obj.month, date_obj.day, 0, 0, 0)
        end_of_day = datetime(date_obj.year, date_obj.month, date_obj.day, 23, 59, 59)

        logs_for_day = list(db[f"logs_{MONGO_ENV}"].find({
            "timestamp": {"$gte": start_of_day, "$lte": end_of_day}
        }).sort("timestamp", -1))

        trades_for_day = list(db[f"trades_{MONGO_ENV}"].find({
            "date": {"$gte": start_of_day, "$lte": end_of_day}
        }).sort("date", -1))

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

    return render_template('trading_overview.html',
                           current_positions=current_positions,
                           closed_trades=closed_trades,
                           active_page='trading_overview',
                           total_pnl=total_pnl,
                           win_loss_ratio=win_loss_ratio,
                           average_winning_trade=average_winning_trade,
                           average_losing_trade=average_losing_trade,
                           daily_data=daily_data,
                           page=page,
                           has_more_days=has_more_days,
                           total_days=total_days)

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
            start_of_day = datetime.strptime(log_date, '%Y-%m-%d')
            end_of_day = start_of_day + timedelta(days=1) - timedelta(microseconds=1)
            query['timestamp'] = {'$gte': start_of_day, '$lte': end_of_day}
        except ValueError:
            pass # Invalid date format, ignore filter

    all_logs = list(db[f"logs_{MONGO_ENV}"].find(query).sort("timestamp", -1).skip(skip_logs).limit(logs_per_page))
    total_logs = db[f"logs_{MONGO_ENV}"].count_documents({})

    has_more = total_logs > (skip_logs + len(all_logs))

    # Convert ObjectId and datetime objects to strings for JSON serialization
    for log in all_logs:
        log['_id'] = str(log['_id'])
        log['timestamp'] = log['timestamp'].strftime('%Y-%m-%d %H:%M:%S')

    return jsonify({"logs": all_logs, "has_more": has_more, "next_page": page + 1})

@app.route('/token-refresh')
@login_required
def token_refresh():
    token_status = "UNKNOWN"
    auth_url = fyers_session.generate_authcode() # Always generate auth_url
    tokens = load_tokens()

    if tokens:
        generated_at = tokens.get("generated_at")
        if is_access_token_valid(generated_at):
            token_status = "VALID"
        else:
            if is_refresh_token_valid(generated_at):
                token_status = "EXPIRED_ACCESS_TOKEN_REFRESHABLE"
            else:
                token_status = "EXPIRED_REFRESH_TOKEN_MANUAL_REQUIRED"
    else:
        token_status = "NO_TOKENS_FOUND"
    
    return render_template('token_refresh.html', token_status=token_status, auth_url=auth_url, active_page='token_refresh', generated_at=tokens.get("generated_at") if tokens else None)

@app.route('/token-callback')
@login_required
def token_callback():
    auth_code = request.args.get('code')
    if auth_code:
        fyers_session.set_token(auth_code)
        token_response = fyers_session.generate_token()
        if token_response.get("access_token"):
            token_response["generated_at"] = int(time.time())
            save_tokens(token_response)
            return redirect(url_for('token_refresh', status='success'))
        else:
            return redirect(url_for('token_refresh', status='failed', message=token_response.get('message', 'Unknown error')))
    else:
        return redirect(url_for('token_refresh', status='failed', message='No authorization code received.'))

@app.route('/refresh-token-action', methods=['POST'])
@login_required
def refresh_token_action():
    tokens = load_tokens()
    if tokens and is_refresh_token_valid(tokens.get("generated_at")):
        refreshed_tokens = refresh_access_token_custom(tokens["refresh_token"], CLIENT_ID, SECRET_ID, PIN)
        if refreshed_tokens:
            return redirect(url_for('token_refresh', status='refreshed'))
        else:
            return redirect(url_for('token_refresh', status='refresh_failed', message='Failed to refresh token.'))
    else:
        return redirect(url_for('token_refresh', status='refresh_failed', message='Refresh token invalid or not found.'))

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
        print(f"Successfully ran executor.py (run_id: {run_id}, triggered by: {run_type})")
        print(f"Executor stdout: {result.stdout}")
        print(f"Executor stderr: {result.stderr}")
        if db is not None:
            strategy_runs_collection.insert_one({
                "run_id": run_id,
                "run_time": datetime.now(),
                "run_type": run_type,
                "stdout": result.stdout,
                "stderr": result.stderr
            })
    except subprocess.CalledProcessError as e:
        print(f"Error running executor.py: {e}")
        print(f"Executor stdout (on error): {e.stdout}")
        print(f"Executor stderr (on error): {e.stderr}")
        if db is not None:
            strategy_runs_collection.insert_one({
                "run_id": run_id,
                "run_time": datetime.now(),
                "run_type": run_type,
                "status": "failed",
                "error": str(e),
                "stdout": e.stdout,
                "stderr": e.stderr
            })

scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(run_executor, 'cron', hour=15, minute=20, timezone='Asia/Kolkata')

def self_ping():
    delay = random.randint(5 * 60, 7 * 60) # Random delay between 5 and 7 minutes
    print(f"[INFO] Next self-ping in {delay / 60:.2f} minutes.")
    time.sleep(delay)
    try:
        # Use the internal URL for the dashboard endpoint
        # Assuming the app is accessible at http://localhost:5000 or similar in deployment
        # For Render, this would be the app's public URL
        # For simplicity, we'll use the root path, which will hit the dashboard
        requests.get("http://127.0.0.1:8080/") # Or your deployed app's URL
        print("[INFO] Self-ping successful.")
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Self-ping failed: {e}")

scheduler.add_job(self_ping, 'interval', minutes=random.randint(5, 7))
scheduler.start()

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
        runs = list(strategy_runs_collection.find({}).sort("run_time", -1).skip(skip_runs).limit(runs_per_page))
        total_runs = strategy_runs_collection.count_documents({})

    for run in runs:
        run_id = run['run_id']
        # Fetch trades for this run
        trades_for_run = list(db[f"trades_{MONGO_ENV}"].find({"run_id": run_id, "filled": True}))
        run['executed_trades_count'] = len(trades_for_run)
        run['total_pnl'] = sum(trade.get('profit', 0.0) for trade in trades_for_run)
        run['status'] = run.get('status', 'completed') # Default to completed if not explicitly set

    has_more_runs = total_runs > (skip_runs + len(runs))

    return render_template('run_strategy.html', runs=runs, page=page, has_more_runs=has_more_runs, active_page='run_strategy')


@app.route('/api/run-logs/<run_id>')
def api_run_logs(run_id):
    if db is None:
        return jsonify({"error": "Database connection failed."}), 500

    logs = list(db[f"logs_{MONGO_ENV}"].find({"run_id": run_id}).sort("timestamp", 1))

    for log in logs:
        log['_id'] = str(log['_id'])
        log['timestamp'] = log['timestamp'].strftime('%Y-%m-%d %H:%M:%S')

    return jsonify({"logs": logs})


@app.route('/execute-strategy', methods=['POST'])
def execute_strategy():
    run_executor(run_type="manual")
    return redirect(url_for('run_strategy', status='success'))

if __name__ == '__main__':
    app.run(debug=True)
