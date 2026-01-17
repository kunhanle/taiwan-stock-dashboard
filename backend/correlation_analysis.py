
import yfinance as yf
import pandas as pd
import datetime

# Map common metal names to likely Yahoo Finance tickers (Futures)
METAL_TICKERS = {
    'Gold': 'GC=F',
    'Silver': 'SI=F',
    'Copper': 'HG=F',
    'Platinum': 'PL=F',
    'Palladium': 'PA=F',
    'Aluminium': 'ALI=F', # COMEX Aluminium Futures
    'Nickel': 'NICK.L',   # WisdomTree Nickel (ETF proxy)
    'Zinc': 'ZINC.L',     # WisdomTree Zinc (ETF proxy)
    'Tin': 'TINM.L',      # WisdomTree Tin
    'Lead': 'LEED.L',     # WisdomTree Lead
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

def analyze_correlation(stock_ids, metal_name=None, start_date=None, end_date=None):
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
                pass 

            stock_df = stock_ticker_obj.history(start=start_date, end=end_date, interval="1d") 
            
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
            stock_series_map[s_id] = {'series': s_series, 'name': stock_name} 

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
                s_series_clean = s_series.dropna()
                for date, price in s_series_clean.items():
                    chart_data.append({
                        'date': date.strftime('%Y-%m-%d'),
                        'stock_price': float(price),
                    })

                results['stock_results'].append({
                    'stock_id': s_id,
                    'stock_name': stock_name,
                    'ticker': ticker,
                    'correlation': None, 
                    'data': chart_data
                })

        except Exception as e:
            results['stock_results'].append({'stock_id': s_id, 'stock_name': s_id, 'error': str(e)})

    # 3. Stock vs Stock Comparison
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

    return results
