This project is a web-based application built with Flask that serves as a dashboard and control center for an algorithmic trading system integrated with the Fyers API. It provides functionalities for user authentication, Fyers API token management, viewing trading logs and performance, and managing the execution of trading strategies.

### Project Structure and File Descriptions:

*   **`app.py`**:
    The main Flask application file. It sets up the web server, handles routing for various pages (login, home, performance, logs, token refresh, strategy runs), manages user sessions, interacts with MongoDB for data storage (users, Fyers tokens, trading logs, trades, strategy run history), integrates with the Fyers API for token management, and schedules the periodic execution of trading strategies via `executor.py`. It also provides API endpoints for fetching logs.

*   **`auth.py`**:
    Contains the `AuthManager` class and a `login_required` decorator. The `AuthManager` handles all aspects of user authentication, including creating users, verifying passwords, managing user sessions, tracking failed login attempts, and locking accounts for security. The `login_required` decorator is used to protect Flask routes, ensuring only authenticated users can access them.

*   **`executor.py`**:
    A utility script responsible for orchestrating the execution of core trading logic. When run, it first executes `token_refresh.py` to ensure valid Fyers API tokens are available, and then proceeds to execute `live_stratergy.py` (the main algorithmic trading strategy script). It captures and logs the output of these subprocesses, associating them with a unique run ID.

*   **`token_refresh.py`**:
    A standalone script dedicated to managing the lifecycle of Fyers API access and refresh tokens. It handles token generation, validation, and refreshing. It interacts with MongoDB to securely store and load token data, ensuring that the trading system always has valid credentials to communicate with the Fyers API. It also includes a manual authentication code flow for initial token setup or when refresh tokens expire.

*   **`live_stratergy.py`**:
    (Not provided in the current context, but referenced by `executor.py`) This is presumably the core script containing the actual algorithmic trading strategy logic. It would interact with the Fyers API using the tokens managed by `token_refresh.py` to place trades, manage positions, and execute trading decisions.

*   **`templates/`**:
    This directory contains the HTML templates rendered by the Flask application to provide the user interface.
    *   **`index.html`**: The main dashboard page, displaying daily trading logs and summaries of executed and cancelled trades.
    *   **`login.html`**: The user login interface.
    *   **`logs.html`**: A dedicated page for viewing detailed application logs.
    *   **`performance.html`**: Displays trading performance metrics, including current open positions and historical closed trades.
    *   **`run_strategy.html`**: Allows users to view the history of strategy runs and manually trigger a new strategy execution.
    *   **`token_refresh.html`**: Provides an interface for users to manage and refresh their Fyers API tokens.

*   **`.env`**:
    (Environment configuration file) Contains sensitive environment variables such as the MongoDB connection URI, Flask secret key, Fyers API client ID, secret ID, PIN, and redirect URI. These are loaded by the application at startup.

*   **`.gitignore`**:
    Specifies files and directories that Git should ignore, such as temporary files, environment variables, and Python bytecode.