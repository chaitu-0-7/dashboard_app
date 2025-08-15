# Nifty Shop - Algorithmic Trading Bot

Nifty Shop is a web-based algorithmic trading bot designed to automate trading strategies on the Fyers stockbroking platform. It provides a user-friendly interface to monitor trading activity, manage API tokens, and execute trading strategies.

## User Interface

### Mobile-Friendly Navbar

The application features a mobile-friendly navbar that collapses into a hamburger menu on smaller screens, ensuring a seamless user experience across all devices.

## Functionalities

This document outlines the core functionalities of the Nifty Shop application, explaining the purpose of each component and how they contribute to the overall system.

### 1. Authentication

The application implements a secure authentication system to protect user data and control access to the trading bot's functionalities. The `auth.py` file contains the logic for this system.

- **Login/Logout:** Users are required to log in with a username and password to access the application. A logout feature is provided to securely terminate the user session.
- **Password Hashing:** The application uses `werkzeug.security` to hash passwords, ensuring that they are not stored in plain text.
- **Session Management:** The application uses session tokens to maintain user sessions, ensuring that only authenticated users can access protected routes.
- **Security:** To prevent brute-force attacks, the application locks user accounts after a configurable number of failed login attempts. It also limits the number of concurrent sessions per user.
- **`login_required` Decorator:** A decorator is provided to easily protect routes that require authentication.

### 2. Dashboard

The Dashboard is the main landing page after a user logs in. It provides a quick overview of the trading bot's current status and recent activity.

- **Key Performance Indicators (KPIs):** The dashboard displays essential metrics such as:
    - **Holdings P&L:** The total profit or loss from current holdings.
    - **Open Positions:** The number of currently open trades.
    - **Recent Trades (Today):** The number of trades executed on the current day.
- **Recent Trading Activity:** The dashboard presents a chronological view of recent trading activities, separated by day. For each day, it shows:
    - **Executed Trades:** A list of successfully executed trades, including details like action (BUY/SELL), quantity, symbol, price, and profit/loss.
    - **Cancelled Orders:** A list of orders that were canceled.
    - **Logs:** Access to the application logs for that specific day.

### 3. Trading Overview

The Trading Overview page provides a more in-depth analysis of the trading performance.

- **Current Positions:** This section displays a detailed list of all currently open positions, including the symbol, quantity, average price, current price, and the real-time profit or loss (P&L) for each position.
- **Closed Trades:** This section shows a history of all closed trades, providing information on the symbol, action, quantity, price, date, and the final profit or loss for each trade.
- **Performance Metrics:** The page calculates and displays key performance metrics to evaluate the effectiveness of the trading strategy:
    - **Total P&L:** The cumulative profit or loss from all closed trades.
    - **Win/Loss Ratio:** The ratio of winning trades to losing trades.
    - **Average Winning Trade:** The average profit from all winning trades.
    - **Average Losing Trade:** The average loss from all losing trades.

### 4. Logs

The Logs page offers a centralized and searchable interface for viewing all application logs. This is crucial for debugging and monitoring the bot's behavior.

- **Log Filtering:** Users can filter logs by:
    - **Search Query:** A free-text search to find specific log messages.
    - **Log Level:** Filtering by log severity (e.g., INFO, WARNING, ERROR).
    - **Date:** Viewing logs for a specific date.
- **Infinite Scrolling:** The page uses infinite scrolling to efficiently load and display a large number of logs without overwhelming the user.

### 5. Fyers API Token Management

This section is dedicated to managing the authentication tokens required to interact with the Fyers API. The `token_refresh.py` script handles this functionality.

- **Token Storage:** The Fyers API tokens are stored in a MongoDB collection called `fyers_tokens`.
- **Token Status:** The page displays the current status of the Fyers API access token (e.g., VALID, EXPIRED).
- **Token Refresh:** It provides a mechanism to automatically refresh expired access tokens using a refresh token.
- **Manual Token Generation:** If the refresh token also expires, the user can manually generate a new access token by following a guided process.

### 6. Strategy Execution

The Strategy page allows the user to control the execution of the trading strategy.

- **Manual Execution:** Users can manually trigger the execution of the trading strategy at any time.
- **Strategy Run History:** The page displays a history of all strategy runs, including the time of execution and the trigger type (manual or scheduled).
- **Run-Specific Logs:** For each strategy run, users can view the detailed logs generated during that specific execution, which is useful for analyzing the behavior of the strategy in different market conditions.

### 7. Trading Strategy

The core of the Nifty Shop bot is its mean-reversion trading strategy, which is implemented in the `live_stratergy.py` file.

- **Strategy:** The bot trades NIFTY 50 stocks based on a mean-reversion strategy. It calculates a moving average for each stock and looks for opportunities to buy when the price deviates significantly below the moving average.
- **Entry and Exit Logic:**
    - **Entry:** The bot enters a position when a stock's price is below its moving average by a certain percentage (defined by `entry_threshold` in the code).
    - **Exit:** The bot exits a position when the profit for that position reaches a predefined percentage (defined by `exit_threshold` in the code).
- **Averaging Down:** If a position's loss exceeds a certain percentage (defined by `averaging_threshold` in the code), the bot will consider buying more of that stock to average down the entry price.
- **Scanning:** The bot scans a predefined list of NIFTY 50 stocks for trading opportunities.
- **Order Verification:** After placing an order, the bot verifies that the order is filled before updating its internal records.
- **Manual Override:** The bot can detect if a position has been manually closed on the Fyers platform and will record it as a manual trade.

### 8. Database Verification

The `verify_db.py` script is a utility to connect to the MongoDB database and print the contents of the `trades` and `logs` collections. This script is useful for developers to quickly verify that data is being stored correctly in the database.

### 9. Scheduled Execution

The trading strategy is automatically executed on a schedule using a GitHub Actions workflow defined in the `.github/workflows/run-cron-script.yml` file.

- **Schedule:** The workflow is scheduled to run at 9:40 AM UTC (3:10 PM IST) on weekdays (Monday to Friday).
- **Manual Trigger:** The workflow can also be triggered manually from the GitHub Actions tab.
- **Execution Steps:** The workflow performs the following steps:
    1. Checks out the latest code from the repository.
    2. Sets up the Python environment.
    3. Installs the required dependencies from the `requirements.txt` file.
    4. Runs the `executor.py` script to execute the trading strategy.
- **Secrets Management:** The workflow uses GitHub secrets to securely store and use sensitive information like API keys and the MongoDB URI.

### 10. Production Deployment

The `run_prod.py` script is used to run the Flask application in a production environment.

- **WSGI Server:** It uses the `waitress` WSGI server, which is a production-quality server for Python web applications.
- **Host and Port:** The application is served on all available network interfaces (`0.0.0.0`) on port `8080`.

## Configuration

The application's behavior can be customized through the `config.py` file.

- **`MONGO_DB_NAME`:** The name of the MongoDB database used by the application.
- **`MONGO_ENV`:** The environment for the application, which can be set to 'prod' for production or other values for development or testing.
- **`APP_LOGS_PER_PAGE_HOME`:** The number of days of trading activity to display on the dashboard.
- **`FYERS_REDIRECT_URI`:** The redirect URI used for Fyers API authentication.
- **`MAX_TRADE_VALUE`:** The maximum amount of money to be used for a single trade.
- **`MA_PERIOD`:** The period (in days) used for calculating the moving average in the trading strategy.
- **`ACCESS_TOKEN_VALIDITY`:** The duration (in seconds) for which the Fyers API access token is valid.
- **`REFRESH_TOKEN_VALIDITY`:** The duration (in seconds) for which the Fyers API refresh token is valid.

## Project Structure

The project is organized into the following key files:

- **`app.py`:** The main Flask application file that defines the routes and core logic of the web interface.
- **`auth.py`:** Handles user authentication, session management, and security.
- **`config.py`:** Contains configuration variables for the application.
- **`executor.py`:** The main entry point for running the trading strategy. It handles token refreshing and calls the `live_stratergy.py` script.
- **`live_stratergy.py`:** Contains the core trading logic, including the mean-reversion strategy, order placement, and position management.
- **`token_refresh.py`:** Manages the refreshing of Fyers API tokens.
- **`verify_db.py`:** A script to verify the database connection.
- **`run_prod.py`:** The script to run the application in a production environment.
- **`.github/workflows/run-cron-script.yml`:** The GitHub Actions workflow file for scheduled execution of the trading strategy.
- **`templates/`:** This directory contains all the HTML files that render the web pages.
- **`requirements.txt`:** Lists the Python dependencies for the project.
- **`.gitignore`:** Specifies which files and directories to ignore in version control.

## Dependencies

The project relies on the following Python libraries, which are listed in the `requirements.txt` file:

- **`flask`:** A micro web framework for Python.
- **`pymongo`:** A Python driver for MongoDB.
- **`fyers_apiv3`:** The official Python library for the Fyers API.
- **`requests`:** A simple and elegant HTTP library for Python.
- **`APScheduler`:** A library for scheduling tasks in Python.
- **`python-dotenv`:** A library for managing environment variables.
- **`waitress`:** A production-quality WSGI server.
- **`Werkzeug`:** A WSGI utility library, used by Flask.
- **`pandas`:** A powerful data analysis and manipulation library.
- **`numpy`:** The fundamental package for scientific computing with Python.
- **`pytz`:** A library for working with timezones in Python.

## Ignored Files

The `.gitignore` file is configured to exclude the following types of files and directories from version control:

- Compiled Python files (`__pycache__/`, `*.pyc`, `*.pyd`, `*.so`)
- Fyers log files (`fyers_logs/`)
- Virtual environment directories (`.venv/`, `venv/`, `env/`)
- Environment variable files (`.env`)
- Editor-specific configuration files (`.vscode/`, `.idea/`, etc.)
- Log files (`*.log`)
- Database files (`*.sqlite3`, `*.db`)
- Project-specific text files (`files.txt`, `ideas.txt`, `PRD.md`)
- OS-specific files (`.DS_Store`, `Thumbs.db`)