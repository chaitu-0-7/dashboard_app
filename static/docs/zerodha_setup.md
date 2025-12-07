# How to Setup Zerodha (Kite Connect)

Follow these steps to generate your API credentials.
*Note: Kite Connect is a paid API provided by Zerodha (~₹2000/month).*

### Step 1: Login to Developer Console
1. Go to the [Kite Connect Developer Portal](https://developers.kite.trade/).
2. Sign up or Login.

### Step 2: Create a New App
1. You may need to add credits to your account first if you haven't already.
2. Click **Create New App**.
3. Fill in the details:
   * **App Name**: `Nifty Shop`.
   * **Zerodha Client ID**: Your specialized Zerodha User ID.
   * **Redirect URL**: You can use `http://localhost:8080` or the URL of this app. 
     * *Note: For this web-based login flow, the Redirect URL is handled dynamically, but Zerodha requires a valid URL in settings.*
   * **Description**: "Trading Bot".
4. Click **Create**.

### Step 3: Get Your Credentials
1. Click on your newly created app in the dashboard.
2. You will see:
   * **API Key**: A public alphanumeric key.
   * **API Secret**: A private secret key.

### Step 4: Connect
1. Copy the **API Key** and paste it into the **API Key** field in Nifty Shop.
2. Copy the **API Secret** and paste it into the **API Secret** field in Nifty Shop.
3. Click **Connect Zerodha Account**.
4. You will be redirected to the Kite login page to authorize the session.
