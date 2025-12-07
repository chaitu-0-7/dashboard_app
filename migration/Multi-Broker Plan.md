# Multi-Broker Connectivity - Implementation Plan (v3)

## User Scenarios

### Scenario 1: Migration Mode
> "Run strategy on 2 brokers - EXIT_ONLY on one, NORMAL on another"

### Scenario 2: Parallel Accounts
> "Run strategy on 2 accounts simultaneously"

### Scenario 3: Explore Mode
> "Added broker to explore, but don't run strategy on it"

---

## Design Decisions

| Decision | Choice |
|----------|--------|
| **Settings approach** | Hybrid: Global + per-broker `trading_mode` |
| **Add Broker flow** | Dedicated page with documentation |
| **Dashboard view** | Broker switcher (one at a time) |
| **Broker naming** | User-defined display names |
| **Enable/Disable** | Toggle per broker for strategy execution |
| **Default Broker** | Primary broker for dashboard/token checks |

---

## Data Model

### Collection: `broker_accounts`
```javascript
{
  "_id": ObjectId(),
  "broker_id": "zerodha_abc123",
  "broker_type": "zerodha",               // fyers | zerodha
  "display_name": "Zerodha - Main",
  "is_default": true,                     // Primary broker for dashboard
  "enabled": true,                        // Run strategy on this broker?
  "trading_mode": "NORMAL",               // NORMAL | EXIT_ONLY | PAUSED
  
  "api_key": "xxx",
  "api_secret": "xxx",
  "access_token": "...",
  "token_generated_at": ISODate(),
  "token_status": "valid",                // valid | expired
  
  "created_at": ISODate(),
  "last_run_at": ISODate()
}
```

---

## Token Refresh Flow (Improved UX)

### Current Behavior (Problem)
- Token expired → Hard redirect to `/token_refresh` → User stuck until refreshed

### New Behavior
```
┌─────────────────────────────────────────────────────────────┐
│                         LOGIN                               │
├─────────────────────────────────────────────────────────────┤
│  1. User logs in                                            │
│  2. Check default broker token status                       │
│  3. If expired → Redirect to token refresh                  │
│  4. If valid → Continue to dashboard                        │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    ANY PAGE NAVIGATION                       │
├─────────────────────────────────────────────────────────────┤
│  1. User on token_refresh page, wants to go elsewhere       │
│  2. Allow navigation (no blocking)                          │
│  3. Show persistent warning toast:                          │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ ⚠️ Warning                                      [X] │   │
│  │ Dashboard data may be incomplete.                   │   │
│  │ Token not refreshed for: Zerodha - Main             │   │
│  │ [Go to Token Refresh]                               │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  4. Toast stays until user clicks [X] or refreshes token   │
└─────────────────────────────────────────────────────────────┘
```

---

## Broker List UI (Settings Page)

```
┌─────────────────────────────────────────────────────────────┐
│ 🔗 Broker Accounts                              [+ Add New] │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌────────────────────────────────────────────────────┐    │
│  │ ⭐ Zerodha - Main                  [Default]       │    │
│  │ Mode: NORMAL  │  Token: ✓ Valid                   │    │
│  │ [Disable] [Edit] [Set Default] [Disconnect]       │    │
│  └────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌────────────────────────────────────────────────────┐    │
│  │    Fyers - Old Account             [Disabled]      │    │
│  │ Mode: EXIT_ONLY  │  Token: ✓ Valid                │    │
│  │ [Enable] [Edit] [Set Default] [Disconnect]        │    │
│  └────────────────────────────────────────────────────┘    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation Phases

### Phase 1: Database & Core
- [ ] Create `broker_accounts` collection schema
- [ ] Migrate existing Fyers token to new schema
- [ ] Add `is_default` and `enabled` fields
- [ ] Update `live_stratergy.py` to accept `--broker-id`
- [ ] Update `executor.py` to iterate through enabled brokers only

### Phase 2: Token Refresh UX
- [ ] Check default broker token at login
- [ ] Remove hard redirect blocking
- [ ] Add persistent warning toast in `base.html`
- [ ] Toast closes only on user click or token refresh

### Phase 3: Broker Setup UI
- [ ] Create `/broker/add` with broker type selection
- [ ] Zerodha setup wizard with documentation
- [ ] Fyers setup wizard with documentation
- [ ] OAuth callback handlers

### Phase 4: Settings Integration
- [ ] Add broker list section to settings
- [ ] Enable/Disable toggle per broker
- [ ] Set Default button
- [ ] Edit modal (display name, trading_mode)

### Phase 5: Dashboard Integration
- [ ] Broker switcher dropdown
- [ ] Filter trades/positions by selected broker

---

## Routes

| Route | Purpose |
|-------|---------|
| `/broker/add` | Choose broker type |
| `/broker/add/zerodha` | Zerodha setup wizard |
| `/broker/add/fyers` | Fyers setup wizard |
| `/broker/callback/<type>` | OAuth callback |
| `/broker/<id>/edit` | Edit broker settings |
| `/broker/<id>/toggle` | Enable/Disable |
| `/broker/<id>/set-default` | Set as default |
| `/broker/<id>/refresh` | Manual token refresh |
| `/broker/<id>/delete` | Remove broker |

---

## Summary

**Key Features:**
1. Multiple broker accounts with enable/disable
2. Default broker for dashboard and token checks
3. Per-broker `trading_mode` (NORMAL/EXIT_ONLY/PAUSED)
4. Improved token refresh: warning toast, no hard blocking
5. Dedicated setup pages with step-by-step documentation
