# NIFTY 50 Constituents Management System

## 📋 Overview

Automated system for managing NIFTY 50 constituents list with:
- **Weekly auto-updates** (every Tuesday before strategy runs)
- **Dual-source fetching** (NSE India API → Fyers API fallback)
- **Symbol validation** (Fyers → YFinance price check)
- **Admin management UI** (view, add, remove symbols)
- **Email notifications** (update results, action required)
- **Strategy integration** (only trade active NIFTY 50 symbols)

---

## 🚀 Features

### 1. Automated Weekly Updates
- **When**: Every Tuesday at 3:10 PM IST (before strategy runs)
- **Sources**: 
  - Primary: NSE India API
  - Backup: Fyers API
- **Validation**: Check if symbols exist and have valid prices
- **Fallback**: Use existing DB data if both sources fail

### 2. Smart Change Detection
```
New symbols in NIFTY 50 → Auto-ADD to DB
Removed symbols → Mark as "pending_removal" (don't delete)
Email admin → Summary of changes + action required
```

### 3. Strategy Integration
- **Entry Scans**: Only scan symbols in active NIFTY 50 list
- **Averaging**: Only average on symbols with `status: active`
- **Removed Symbols**: Existing positions remain open until normal exit (5% profit)

### 4. Admin Management
- **View**: Full list with status (active/pending_removal)
- **Add**: Manually add symbols (with validation)
- **Remove**: Mark symbols for pending removal
- **Restore**: Restore removed symbols to active
- **Export**: Download CSV of current list

---

## 📁 Files Created/Modified

### New Files:
```
utils/nifty50_manager.py              # Core management logic
utils/email.py (send_nifty50_update_email)  # Email notifications
templates/admin/nifty_constituents.html     # Admin UI
NIFTY50_CONSTITUENTS_GUIDE.md         # This documentation
```

### Modified Files:
```
app.py                                # Added admin routes
global_executor.py                    # Tuesday update integration
live_stratergy.py                     # Use dynamic list + averaging checks
```

---

## 🗄️ Database Schema

### Collection: `nifty50_constituents`
```javascript
{
  "_id": "current_list",
  "symbols": [
    {
      "symbol": "NSE:RELIANCE-EQ",
      "company_name": "RELIANCE",
      "status": "active",  // or "pending_removal"
      "added_date": ISODate("2024-01-01T00:00:00Z"),
      "removed_date": null  // Set when marked for removal
    }
  ],
  "last_updated": ISODate("2026-03-25T09:00:00Z"),
  "source": "NSE"  // or "FYERS"
}
```

### Collection: `nifty50_update_logs`
```javascript
{
  "update_date": ISODate("2026-03-25T09:00:00Z"),
  "status": "completed",  // or "failed", "partial"
  "source_used": "NSE",
  "symbols_added": ["NSE:XYZ-EQ", "NSE:PQR-EQ"],
  "symbols_removed": ["NSE:ABC-EQ", "NSE:DEF-EQ"],
  "validation_failed": [],  // Symbols that failed validation
  "error": null,
  "email_sent": true
}
```

---

## 🔧 Configuration

### Environment Variables (.env)
```bash
# Admin Email (for update notifications)
ADMIN_EMAIL=chaitu2@gmail.com

# SMTP Settings (for sending emails)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_EMAIL=your-email@gmail.com
SMTP_PASSWORD=your-app-password

# MongoDB
MONGO_URI=mongodb://localhost:27017

# Fyers API (for backup source & validation)
FYERS_CLIENT_ID=your-client-id
FYERS_SECRET_ID=your-secret-id
FYERS_ACCESS_TOKEN=your-access-token
```

---

## 📊 Admin UI

### Access
```
URL: http://localhost:8080/admin/nifty-constituents
Permissions: Admin only
```

### Features
1. **Stats Dashboard**
   - Active symbols count
   - Pending removal count
   - Recently added (last 7 days)
   - Days since last update

2. **Symbol Management**
   - View all symbols with status
   - Add new symbols (with validation)
   - Mark for removal
   - Restore removed symbols
   - Validate symbol (check price)
   - Export to CSV

3. **Force Update**
   - Manual trigger for immediate update
   - Bypasses Tuesday-only schedule

---

## 📧 Email Notifications

### Triggers
1. **Weekly Update Completed** (every Tuesday)
   - Summary: Added/Removed counts
   - List of new symbols
   - List of removed symbols
   - Positions in removed stocks (if any)
   - Warning if only backup source was available

2. **Update Failed**
   - Error details
   - Reassurance: Using existing list
   - Next attempt: Next Tuesday

3. **Single Source Warning**
   - NSE API failed, using Fyers
   - Recommendation: Monitor for next update

### Email Template Sections
```
✅ Update Completed Summary
├── Added Symbols (with checkmarks)
├── Removed Symbols (pending review)
├── Existing Positions in Removed Stocks
├── Validation Failures (if any)
└── [Review in Admin Panel] Button

❌ Update Failed
├── Error Message
├── Impact Assessment
└── Next Steps
```

---

## 🔄 Execution Flow

### Tuesday Strategy Run
```
1. Global Executor starts (3:10 PM IST)
2. Check if Tuesday → YES
3. Run Nifty50Manager.update_constituents()
   ├─ Fetch from NSE API
   ├─ If fails, fetch from Fyers API
   ├─ Validate all symbols (price check)
   ├─ Compare with existing list
   ├─ Add new symbols (auto)
   ├─ Mark removed as pending_removal
   ├─ Log to nifty50_update_logs
   └─ Send email to admin
4. Continue with market data sync
5. Run strategy with updated list
```

### Other Days (Mon, Wed-Fri)
```
1. Global Executor starts (3:10 PM IST)
2. Check if Tuesday → NO
3. Skip NIFTY 50 update
4. Continue with market data sync
5. Run strategy with existing list
```

---

## 🧪 Testing

### Manual Test (Any Day)
```bash
# Test update logic
cd "C:\Users\CHAITNYA\Desktop\algo trading\nifty shop"
python utils/nifty50_manager.py
```

### Expected Output
```
============================================================
NIFTY 50 Manager - Manual Test
============================================================
📡 Fetching NIFTY 50 from NSE India API...
✅ Fetched 50 symbols from NSE
📋 Fetched 50 symbols from NSE
📋 Current DB has 50 active symbols
📊 Changes detected: +2 added, -2 removed
🔍 Validating 2 symbols (timeout: 120s)...
  ✅ NSE:XYZ-EQ: ₹1234.50 (fyers)
  ✅ NSE:PQR-EQ: ₹567.80 (fyers)
✅ Validated 2/2 symbols
✅ Database updated with 50 symbols
📧 Email sent to chaitu2@gmail.com
✨ NIFTY 50 update completed successfully

============================================================
Update Result:
  Status: completed
  Source: NSE
  Added: 2
  Removed: 2
  Email Sent: True
============================================================
```

### Admin UI Test
1. Login as admin
2. Navigate to `/admin/nifty-constituents`
3. Verify stats cards show correct counts
4. Click "Add Symbol" → Enter `NSE:TATASTEEL-EQ`
5. Verify symbol appears in table
6. Click "Mark for Removal" on a symbol
7. Verify status changes to "⚠️ Pending Removal"
8. Click "Restore" to revert
9. Click "Export CSV" → Verify download

---

## 🛠️ Troubleshooting

### Issue: Update fails every Tuesday
**Symptoms**: Email shows "Update Failed"

**Solutions**:
1. Check NSE API accessibility:
   ```bash
   curl -I "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050"
   ```
2. Verify Fyers credentials in .env
3. Check MongoDB connection
4. Review logs in `nifty50_update_logs` collection

### Issue: Symbols not validating
**Symptoms**: Validation shows "Invalid" for all symbols

**Solutions**:
1. Check Fyers API token validity
2. Verify YFinance is installed: `pip show yfinance`
3. Test symbol format: Should be `NSE:SYMBOL-EQ`
4. Check network connectivity

### Issue: Email not sending
**Symptoms**: Update completes but no email

**Solutions**:
1. Verify SMTP credentials in .env
2. Check if Gmail app password is correct
3. Test SMTP connection:
   ```python
   import smtplib
   server = smtplib.SMTP('smtp.gmail.com', 587)
   server.starttls()
   server.login('your-email@gmail.com', 'your-password')
   ```
4. Check spam folder

### Issue: Strategy not using updated list
**Symptoms**: Strategy trades old symbols

**Solutions**:
1. Verify `nifty50_constituents` collection has latest data
2. Check `live_stratergy.py` logs for "Using dynamic NIFTY 50 list"
3. Ensure Nifty50Manager can connect to MongoDB
4. Restart Flask app if running in production

---

## 📈 Future Enhancements

### Planned Features
1. **Multiple Indices Support**
   - NIFTY NEXT 50
   - NIFTY BANK
   - Custom baskets

2. **Advanced Validation**
   - Volume checks (minimum liquidity)
   - Trading status (not suspended)
   - Corporate actions (splits, mergers)

3. **Automated Rebalancing**
   - Auto-close positions in removed stocks (optional)
   - Gradual position reduction

4. **Backtesting Integration**
   - Historical constituents list
   - Accurate backtests with correct symbols per date

5. **Webhook Notifications**
   - Slack/Discord alerts
   - SMS notifications for critical updates

---

## 🎯 Key Design Decisions

### Why pending_removal instead of delete?
- **Safety**: Prevents accidental data loss
- **Audit Trail**: Track what was removed and when
- **Reversibility**: Admin can restore if needed
- **Position Management**: Existing positions remain tracked

### Why Tuesday 3:10 PM IST?
- **After Market Hours**: NSE data is final
- **Before Strategy Run**: Fresh list for the week
- **GitHub Actions Schedule**: Existing cron runs Mon-Fri

### Why dual-source validation?
- **Reliability**: If one source fails, other works
- **Accuracy**: Cross-verify symbol existence
- **Price Verification**: Ensure symbols are actively trading

### Why no sector/weight data?
- **Simplicity**: User requested minimal schema
- **Flexibility**: Easier to add later
- **Performance**: Faster queries, less storage

---

## 📞 Support

For issues or questions:
1. Check logs in MongoDB collections
2. Review email notifications for details
3. Test manually with `python utils/nifty50_manager.py`
4. Verify admin UI shows correct data

---

## ✅ Checklist for Production

- [ ] Set ADMIN_EMAIL in .env
- [ ] Configure SMTP credentials
- [ ] Verify Fyers API credentials
- [ ] Test manual update (`python utils/nifty50_manager.py`)
- [ ] Verify admin UI loads correctly
- [ ] Test email notifications
- [ ] Confirm GitHub Actions schedule (Mon-Fri 3:10 PM IST)
- [ ] Monitor first Tuesday update
- [ ] Review update logs in MongoDB

---

**Last Updated**: 2026-03-25  
**Version**: 1.0  
**Author**: Nifty Shop Development Team
