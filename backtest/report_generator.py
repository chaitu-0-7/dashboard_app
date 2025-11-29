import json
import pandas as pd
import os
from datetime import datetime

def generate_html_report(metrics_file='backtest/backtest_metrics.json', output_file='backtest/report.html'):
    if not os.path.exists(metrics_file):
        print(f"Metrics file {metrics_file} not found.")
        return

    with open(metrics_file, 'r') as f:
        data = json.load(f)

    daily_data = data['daily_data']
    trades = data['trades']
    summary = data['summary']

    # Convert daily data to JS format for charts
    dates = [d['date'] for d in daily_data]
    portfolio_values = [d['portfolio_value'] for d in daily_data]
    capital_deployed = [d['capital_deployed'] for d in daily_data]
    cash_balance = [d['cash_balance'] for d in daily_data]

    # Process trades to create "Trade Cycles"
    cycles = []
    open_positions = {} # symbol -> {qty, avg_price, buys: [], total_cost}

    for trade in trades:
        symbol = trade['symbol']
        action = trade['action']
        qty = trade['quantity']
        price = trade['price']
        date = trade['date']
        
        if action == 'BUY':
            if symbol not in open_positions:
                open_positions[symbol] = {'qty': 0, 'total_cost': 0, 'buys': [], 'avg_price': 0}
            
            pos = open_positions[symbol]
            pos['qty'] += qty
            pos['total_cost'] += (qty * price)
            pos['avg_price'] = pos['total_cost'] / pos['qty']
            pos['buys'].append({'date': date, 'price': price, 'qty': qty, 'type': trade.get('comment', 'BUY')})
            
        elif action == 'SELL':
            if symbol in open_positions:
                pos = open_positions[symbol]
                
                # Calculate hold days from first buy to sell
                entry_date = pd.to_datetime(pos['buys'][0]['date'])
                exit_date = pd.to_datetime(date)
                hold_days = (exit_date - entry_date).days
                
                cycle = {
                    'symbol': symbol,
                    'entry_date': pos['buys'][0]['date'],
                    'exit_date': date,
                    'avg_buy_price': pos['avg_price'],
                    'sell_price': price,
                    'quantity': qty,
                    'pnl': (price - pos['avg_price']) * qty,
                    'pnl_pct': ((price - pos['avg_price']) / pos['avg_price']) * 100,
                    'num_averages': len(pos['buys']) - 1,
                    'hold_days': hold_days
                }
                cycles.append(cycle)
                
                # Update position (reduce qty)
                pos['qty'] -= qty
                pos['total_cost'] -= (qty * pos['avg_price'])
                
                if pos['qty'] <= 0.0001:
                    del open_positions[symbol]

    # Calculate total brokerage (20 Rs per trade)
    total_brokerage = len(trades) * 20

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Nifty Shop Backtest Report</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background-color: #f4f4f9; }}
            .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            h1, h2 {{ color: #333; }}
            .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }}
            .metric-card {{ background: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 4px solid #007bff; }}
            .metric-value {{ font-size: 24px; font-weight: bold; color: #007bff; }}
            .metric-label {{ color: #666; font-size: 14px; }}
            .chart-container {{ position: relative; height: 400px; margin-bottom: 40px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background-color: #007bff; color: white; }}
            tr:hover {{ background-color: #f1f1f1; }}
            .profit {{ color: green; }}
            .loss {{ color: red; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Nifty Shop Strategy Backtest</h1>
            <p>Period: {daily_data[0]['date']} to {daily_data[-1]['date']}</p>
            
            <div class="metrics-grid">
                <div class="metric-card">
                    <div class="metric-label">Total Return</div>
                    <div class="metric-value" style="color: {'green' if summary['total_return_pct'] >= 0 else 'red'}">
                        {summary['total_return_pct']:.2f}%
                    </div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Final Balance</div>
                    <div class="metric-value">₹{summary['final_balance']:,.2f}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Max Drawdown</div>
                    <div class="metric-value" style="color: red">{summary['max_drawdown_pct']:.2f}%</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Total Trades</div>
                    <div class="metric-value">{summary['total_trades']}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Win Rate</div>
                    <div class="metric-value">{summary['win_rate']:.1f}%</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Total Brokerage</div>
                    <div class="metric-value" style="color: #dc3545">₹{total_brokerage:,.2f}</div>
                </div>
            </div>

            <h2>Portfolio Performance</h2>
            <div class="chart-container">
                <canvas id="equityCurve"></canvas>
            </div>

            <h2>Capital Allocation</h2>
            <div class="chart-container">
                <canvas id="allocationChart"></canvas>
            </div>

            <h2>Trade History (Closed Cycles)</h2>
            <div style="overflow-x: auto;">
                <table>
                    <thead>
                        <tr>
                            <th>Symbol</th>
                            <th>Entry Date</th>
                            <th>Exit Date</th>
                            <th>Hold Days</th>
                            <th>Avg Buy Price</th>
                            <th>Sell Price</th>
                            <th>Qty</th>
                            <th>Averages</th>
                            <th>P&L</th>
                            <th>P&L %</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join([f'''
                        <tr>
                            <td>{c['symbol']}</td>
                            <td>{c['entry_date']}</td>
                            <td>{c['exit_date']}</td>
                            <td>{c['hold_days']}</td>
                            <td>₹{c['avg_buy_price']:.2f}</td>
                            <td>₹{c['sell_price']:.2f}</td>
                            <td>{c['quantity']}</td>
                            <td>{c['num_averages']}</td>
                            <td class="{ 'profit' if c['pnl'] >= 0 else 'loss' }">₹{c['pnl']:.2f}</td>
                            <td class="{ 'profit' if c['pnl'] >= 0 else 'loss' }">{c['pnl_pct']:.2f}%</td>
                        </tr>
                        ''' for c in cycles])}
                    </tbody>
                </table>
            </div>
        </div>

        <script>
            const dates = {json.dumps(dates)};
            const portfolioValues = {json.dumps(portfolio_values)};
            const capitalDeployed = {json.dumps(capital_deployed)};
            const cashBalance = {json.dumps(cash_balance)};

            // Equity Curve
            new Chart(document.getElementById('equityCurve'), {{
                type: 'line',
                data: {{
                    labels: dates,
                    datasets: [{{
                        label: 'Portfolio Value',
                        data: portfolioValues,
                        borderColor: '#007bff',
                        tension: 0.1,
                        fill: false
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {{ intersect: false, mode: 'index' }}
                }}
            }});

            // Allocation Chart
            new Chart(document.getElementById('allocationChart'), {{
                type: 'bar',
                data: {{
                    labels: dates,
                    datasets: [
                        {{
                            label: 'Capital Deployed',
                            data: capitalDeployed,
                            backgroundColor: '#28a745',
                            stack: 'Stack 0'
                        }},
                        {{
                            label: 'Cash Balance',
                            data: cashBalance,
                            backgroundColor: '#ffc107',
                            stack: 'Stack 0'
                        }}
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {{ intersect: false, mode: 'index' }},
                    scales: {{
                        x: {{ stacked: true }},
                        y: {{ stacked: true }}
                    }}
                }}
            }});
        </script>
    </body>
    </html>
    """

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"Report generated at {output_file}")

if __name__ == "__main__":
    generate_html_report()
