from flask import Flask, request, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd
import datetime

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# Map common metal names to likely Yahoo Finance tickers (Futures)
# Note: These are futures, so they might have expiration logic, but 'GC=F' usually gives continuous contract.
METAL_TICKERS = {
    'Gold': 'GC=F',
    'Silver': 'SI=F',
    'Copper': 'HG=F',
    'Platinum': 'PL=F',
    'Palladium': 'PA=F',
    'Aluminium': 'ALI=F', # COMEX Aluminium Futures
    'Nickel': 'NICK.L',   # WisdomTree Nickel (ETF proxy) as Futures are unavailable
    'Zinc': 'ZINC.L',     # WisdomTree Zinc (ETF proxy) - ZNC=F is flat/frozen
}

def get_stock_ticker(stock_id):
    stock_id = stock_id.strip().upper()
    if stock_id.endswith('.TW'):
        return stock_id
    if stock_id.endswith('.TWO'):
        return stock_id
    if stock_id.endswith('.JP'):
        return stock_id.replace('.JP', '.T')
    # Assume US if 4 letters or less and no suffix
    if len(stock_id) <= 5 and '.' not in stock_id:
        return stock_id
    return stock_id

@app.route('/api/analyze', methods=['POST'])
def analyze():
    data = request.json
    stock_ids = data.get('stock_ids', [])
    # Support legacy single stock_id for backward compatibility (optional, but good practice)
    if not stock_ids and 'stock_id' in data:
        stock_ids = [data['stock_id']]
        
    metal_name = data.get('metal')
    start_date = data.get('start_date')
    end_date = data.get('end_date')

    if not stock_ids:
        return jsonify({'error': 'Missing stock_ids'}), 400

    # Calculate default date range if not provided (2 years)
    if not start_date or not end_date:
        end = datetime.datetime.now()
        start = end - datetime.timedelta(days=730) # ~2 years
        start_date = start.strftime('%Y-%m-%d')
        end_date = end.strftime('%Y-%m-%d')
    
    # 1. Fetch Metal Data (Optional)
    metal_ticker = None
    metal_series = pd.Series(dtype='float64')
    
    if metal_name:
        metal_ticker = METAL_TICKERS.get(metal_name)
        if metal_ticker:
            try:
                metal_df = yf.download(metal_ticker, start=start_date, end=end_date, interval="1d", progress=False)
                if not metal_df.empty:
                     # Ensure index is datetime and consistent
                     metal_df.index = pd.to_datetime(metal_df.index).tz_localize(None)

                     if isinstance(metal_df.columns, pd.MultiIndex):
                         metal_close = metal_df['Close'].iloc[:, 0]
                     else:
                         metal_close = metal_df['Close']
                     metal_series = metal_close.rename('metal_price')
            except Exception as e:
                print(f"YF failed for {metal_name}: {e}")

        if metal_series.empty:
            return jsonify({'error': f'Could not fetch data for metal: {metal_name}'}), 404

    # 2. Fetch Data for Each Stock
    results = {
        'metal_ticker': metal_ticker if metal_ticker else 'None',
        'stock_results': [],    # List of { id, correlation, data: [...] }
        'stock_vs_stock': []    # List of { id1, id2, correlation, data: [...] }
    }
    
    stock_series_map = {} # Store series for stock-to-stock comparison logic

    for s_id in stock_ids:
        ticker = get_stock_ticker(s_id)
        try:
            stock_ticker_obj = yf.Ticker(ticker)
            
            # Fetch Stock Name (Try to get descriptive name)
            stock_name = s_id
            try:
                info = stock_ticker_obj.info
                # Prefer shortName, then longName, then default to s_id
                name_candidate = info.get('shortName') or info.get('longName')
                if name_candidate:
                    stock_name = name_candidate
            except:
                pass # processing continues if info fails

            stock_df = stock_ticker_obj.history(start=start_date, end=end_date, interval="1d") # Use history for Ticker obj
            
            # If empty, try legacy download just in case (optional, but stick to one consistent way)
            if stock_df.empty:
                stock_df = yf.download(ticker, start=start_date, end=end_date, interval="1d", progress=False)

            if stock_df.empty:
                results['stock_results'].append({'stock_id': s_id, 'stock_name': stock_name, 'error': 'No data'})
                continue

            if isinstance(stock_df.columns, pd.MultiIndex):
                 stock_close = stock_df['Close'].iloc[:, 0]
            else:
                 stock_close = stock_df['Close']
            
            # Ensure stock index is tz-naive for compatibility
            stock_close.index = pd.to_datetime(stock_close.index).tz_localize(None)
            
            s_series = stock_close.rename('stock_price')
            stock_series_map[s_id] = {'series': s_series, 'name': stock_name} # Store for later

            # Align with Metal (if exists) for correlation
            if not metal_series.empty:
                combined = pd.concat([s_series, metal_series], axis=1).dropna()
                
                if combined.empty:
                    correlation = 0
                    chart_data = []
                else:
                    correlation = combined['stock_price'].corr(combined['metal_price'])
                    if pd.isna(correlation): correlation = 0
                    
                    chart_data = []
                    for date, row in combined.iterrows():
                        chart_data.append({
                            'date': date.strftime('%Y-%m-%d'),
                            'stock_price': float(row['stock_price']),
                            'metal_price': float(row['metal_price'])
                        })
                
                results['stock_results'].append({
                    'stock_id': s_id,
                    'stock_name': stock_name,
                    'ticker': ticker,
                    'correlation': correlation,
                    'data': chart_data
                })
            else:
                # No metal selected, just return stock data
                chart_data = []
                # Just use stock series, handle NaNs
                s_series_clean = s_series.dropna()
                for date, price in s_series_clean.items():
                    chart_data.append({
                        'date': date.strftime('%Y-%m-%d'),
                        'stock_price': float(price),
                        # No metal_price
                    })

                results['stock_results'].append({
                    'stock_id': s_id,
                    'stock_name': stock_name,
                    'ticker': ticker,
                    'correlation': None, # Indicate no correlation
                    'data': chart_data
                })

        except Exception as e:
            results['stock_results'].append({'stock_id': s_id, 'stock_name': s_id, 'error': str(e)})

    # 3. Stock vs Stock Comparison (Compare first stock with others, or all pairs?)
    # Requirement: "NIKL vs 1605.TW stock price" implies all pairs or specifically first vs others?
    # User said: "NIKL vs 1605.TW" when both are entered. 
    # If 3 stocks A, B, C? A vs B, A vs C, B vs C?
    # For simplicity and typical usage, let's do all unique pairs.
    
    ids_list = list(stock_series_map.keys())
    for i in range(len(ids_list)):
        for j in range(i + 1, len(ids_list)):
            id1 = ids_list[i]
            id2 = ids_list[j]
            
            s1 = stock_series_map[id1]['series'].rename('price1')
            s2 = stock_series_map[id2]['series'].rename('price2')
            
            combined_pair = pd.concat([s1, s2], axis=1, join='inner').dropna()
            
            if not combined_pair.empty:
                corr = combined_pair['price1'].corr(combined_pair['price2'])
                
                # Normalize or just raw prices? User asked for stock price.
                # Raw prices usually fine for separate axes or normalized. 
                # Our chart handles dual axes, so we can send raw.
                
                pair_data = []
                for date, row in combined_pair.iterrows():
                    pair_data.append({
                        'date': date.strftime('%Y-%m-%d'),
                        'price1': float(row['price1']),
                        'price2': float(row['price2'])
                    })

                results['stock_vs_stock'].append({
                    'stock1': id1,
                    'stock2': id2,
                    'correlation': corr if not pd.isna(corr) else 0,
                    'data': pair_data
                })

    return jsonify(results)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
