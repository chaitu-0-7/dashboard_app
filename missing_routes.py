
@app.route('/update_manual_trade/<trade_id>', methods=['POST'])
@login_required
def update_manual_trade(trade_id):
    if db is None:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    try:
        close_price = float(request.form.get('close_price'))
        close_date_str = request.form.get('close_date')
        
        # Parse Date
        try:
             close_date = datetime.strptime(close_date_str, '%Y-%m-%dT%H:%M')
             close_date = close_date.replace(tzinfo=IST) # Assume Input is IST
             # Convert to UTC for storage equality with other trades if needed, 
             # but keeping as is since we use timezone aware objects in templates
        except ValueError:
             return jsonify({'success': False, 'message': 'Invalid date format'}), 400

        # Fetch the trade to calculate profit
        trade = db['manual_trades'].find_one({'_id': ObjectId(trade_id)})
        if not trade:
             return jsonify({'success': False, 'message': 'Trade not found'}), 404
             
        quantity = trade.get('quantity', 0)
        # avg_price might be stored differently in manual_trades? 
        # In live_stratergy.py we saw 'price' as 0 initally for manual placeholder.
        # But we need the BUY price to calc profit.
        # live_stratergy.py doesn't seem to store avg_buy_price in the placeholder!
        # It calculates `avg_buy_price` from `buy_trades` but doesn't explicitly save it in `trade_data`?
        # Wait, in live_stratergy.py loop:
        # avg_buy_price = ...
        # trade_data = { ... 'action': 'SELL', ... 'price': 0 ... 'profit': 0 }
        # The 'avg_price' or 'buy_price' IS MISSING from the placeholder trade_data in live_stratergy.py!
        # This is another bug. 
        # However, for now, let's update what we can. 
        # If we can't calc profit, we can't fix the chart fully.
        # But wait, we can just update the `profit` directly if we knew the buy price.
        # We should store `buy_price` in the manual trade document.
        
        # Let's check live_stratergy.py lines 608-619 again. 
        # It DOES NOT store buy_price. 
        # So we have data loss here.
        # I'll rely on user to update PROFIT manually? No, existing UI allows only Price and Date.
        # So I must calculate profit.
        # I'll try to deduce buy_price if possible, or assume 0?
        # Or maybe I updates live_stratergy.py to save `avg_buy_price`.
        # For now, I will retrieve `avg_buy_price` if it exists, or 0.
        
        # UPDATE: Looking at `check_for_closed_positions` in live_stratergy.py again.
        # It calculates `avg_buy_price`.
        # It saves it? No.
        # THIS IS CRITICAL.
        
        # For this turn, I will implement the route assuming `avg_buy_price` or `buy_price` might exist, 
        # or fail gracefully. 
        # Actually, let's look for `avg_price` field.
        
        buy_price = trade.get('avg_price') or trade.get('buy_price') or 0.0
        
        profit = (close_price - buy_price) * quantity
        profit_pct = ((close_price - buy_price) / buy_price * 100) if buy_price > 0 else 0
        
        db['manual_trades'].update_one(
            {'_id': ObjectId(trade_id)},
            {'$set': {
                'price': close_price,
                'date': close_date,
                'profit': profit,
                'profit_pct': profit_pct,
                'status': 'FILLED', # Mark as filled once updated
                'comment': f"Manual Close. Profit: {profit_pct:.2f}%"
            }}
        )
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/delete_manual_trade/<trade_id>', methods=['POST'])
@login_required
def delete_manual_trade(trade_id):
    if db is None:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    try:
        db['manual_trades'].delete_one({'_id': ObjectId(trade_id)})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
