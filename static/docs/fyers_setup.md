# How to Setup Fyers API

Follow these steps to generate your API credentials.

### Step 1: Login to Fyers API Dashboard
1. Go to the [Fyers API Dashboard](https://myapi.fyers.in/dashboard).
2. Login using your standard Fyers trading credentials (User ID, Password, PIN/OTP).

### Step 2: Create a New App
1. Once logged in, look for the **+ Create App** button (usually on the dashboard or "My Apps" section).
2. Fill in the details:
   * **App Name**: `Nifty Shop` (or any name you prefer).
   * **Redirect URI**: **Copy the URI shown in the form on the right/below**. 
     * *Note: This is critical. Authentication will fail if this does not match exactly.*
   * **Description**: "Algo Trading Bot" (optional).
   * **Redirect URL**: Same as Redirect URI.
   * **Permissions/Scopes**: Ensure you select permissions for **Orders**, **Holdings**, **Positions**, and **Profile**. If unsure, select all available.

### Step 3: Get Your Credentials
1. After creating the app, you will see it listed in your dashboard.
2. Click on the app to view details.
3. You will see an **App ID** and a **Secret ID**.
   * **Client ID**: The App ID (e.g., `XPxxxxx`).
   * **Secret ID**: The long alphanumeric string (click the "eye" icon to reveal if hidden).

### Step 4: Connect
1. Copy the **App ID** and paste it into the **Client ID** field in Nifty Shop.
2. Copy the **Secret ID** and paste it into the **Secret ID** field in Nifty Shop.
3. Click **Connect Fyers Account**.
4. You will be redirected to Fyers to authorize the app. Click "Continue" or "Authorize" if prompted.
