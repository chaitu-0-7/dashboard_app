# Alternate Strategy 1: Disciplined Mean Reversion

## Key Improvements:

### 1. **Strict Entry Threshold (-5%)**
- Only buy when price is at least 5% below MA
- Reduces false signals and overtrading

### 2. **Hard Stop Loss (-10%)**
- Exit position if loss exceeds 10%
- Prevents catastrophic losses like UPL (-7.2%)

### 3. **Smarter Averaging**
- Average down with SAME position size (₹2000)
- Only average once at -5% loss
- Doubles position size to meaningfully lower average

### 4. **Position Limits**
- Max 5 open positions at once
- Prevents over-diversification
- Ensures adequate capital per trade

### 5. **Reduced Exit Threshold (3%)**
- Take profits faster at 3% instead of 5%
- Reduces exposure time and risk

### 6. **Max Hold Period (30 days)**
- Force exit after 30 days regardless of P&L
- Prevents capital being stuck indefinitely

## Expected Outcomes:
- **Lower drawdown** (stop loss protection)
- **Higher win rate** (stricter entries)
- **Lower brokerage** (fewer trades)
- **Better capital efficiency** (position limits)
