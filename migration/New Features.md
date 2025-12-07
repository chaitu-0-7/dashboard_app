# Nifty Shop - New Features Specification

This document outlines the roadmap for the next major version of Nifty Shop, focusing on user control, flexibility, and reliability.

## 1. Graceful Exit Strategy (Panic Mode / Wind Down)

**Goal**: Allow users to stop new entries while managing existing positions to closure.

### Functionality
- **Mode Toggle**: A simple "Exit Strategy" toggle on the Dashboard.
- **Behavior**:
    - **New Buys**: BLOCKED. The bot will not initiate any fresh positions.
    - **Sells**: ACTIVE. The bot will continue to monitor and sell positions when they hit the target profit.
    - **Averaging (Optional)**: A sub-setting "Allow Averaging in Exit Mode".
        - If `True`: The bot can buy more of *existing* positions to bring down the average price, facilitating a faster exit.
        - If `False`: Strictly no buying. Only sells allowed.

### Implementation Logic
- Add a `status` flag in the `UserConfig` (e.g., `trading_mode`: `NORMAL` | `EXIT_ONLY` | `PAUSED`).
- In `live_stratergy.py`, wrap entry logic with:
  ```python
  if user_config.trading_mode == 'NORMAL':
      # Scan for new entries
  ```

## 2. Dynamic Settings Page

**Goal**: Move hardcoded configuration variables into a user-friendly UI, allowing real-time adjustments without code changes.

### Configurable Parameters
The following parameters (currently in `config.py` or constants) will be editable per user:

| Parameter | Description | Default |
| :--- | :--- | :--- |
| **Capital Allocation** | Total capital assigned to the bot. | ₹1,00,000 |
| **Trade Amount** | Amount to use for a single initial entry. | ₹2,000 |
| **Max Open Positions** | Maximum number of concurrent positions. | 10 |
| **MA Period** | Moving Average length (e.g., 20, 50). | 20 |
| **Entry Threshold** | % drop below MA to trigger buy (e.g., -2%). | -2.0% |
| **Averaging Threshold** | % drop from last buy price to trigger average. | -3.0% |
| **Target Profit** | % profit to trigger exit. | 5.0% |
| **Stop Loss** | (Optional) Hard stop loss percentage. | - |

### UI Implementation
- New Route: `/settings`
- Form with validation for each field.
- "Save" button updates the `user_settings` collection in MongoDB.
- "Reset to Defaults" button.

## 3. Multi-Broker Connectivity

**Goal**: Enable a single user to connect multiple broker accounts and run the strategy across them simultaneously or selectively.

### User Flow
1.  **Add Broker**: User goes to "Profile" -> "Connect Broker".
2.  **Select Broker**: Choose from Fyers, Zerodha, Dhan, etc.
3.  **Auth**: Enter API Key/Secret and complete the login flow.
4.  **Portfolio Selection**: When starting the bot, user selects which "Account" to run on (or "All").

### Backend Architecture
- **Broker Registry**: A system to manage active sessions for multiple brokers.
- **Execution Loop**:
  ```python
  # Pseudo-code for executor
  for broker_session in active_sessions:
      strategy.run(broker=broker_session)
  ```
- **Unified Dashboard**: The dashboard will show a dropdown to switch views between different broker accounts or show a "Consolidated" view.

## 4. Email-Based Alerts

**Goal**: Proactively notify the user when manual intervention is required, ensuring high availability.

### Trigger Events
1.  **Token Expiry**: When the API token is invalid and auto-refresh fails.
    - *Subject*: "Action Required: Re-login to [Broker Name]"
    - *Body*: "Your access token for [Broker] has expired. Please log in to the dashboard to reconnect."
2.  **Order Failure**: If an order is rejected by the broker (e.g., insufficient funds).
3.  **System Error**: If the bot crashes or encounters an unhandled exception.

### Implementation
- **Service**: Use SMTP (Gmail) or a transactional email service (SendGrid/AWS SES).
- **Configuration**: User provides email in Settings (or uses login email).
- **Rate Limiting**: Ensure we don't spam the user (e.g., max 1 alert per hour for the same error).

---

## Technical Roadmap

1.  **Database Schema Update**: Create `UserSettings` and `UserBrokers` collections.
2.  **Backend Refactor**:
    - Implement `BrokerConnector` (from Migration Plan).
    - Update `live_stratergy.py` to read from DB config instead of `config.py`.
3.  **Frontend**: Build `settings.html` and update `dashboard.html` for multi-broker view.
4.  **Alert System**: Create a utility module `notifier.py` for email dispatch.
