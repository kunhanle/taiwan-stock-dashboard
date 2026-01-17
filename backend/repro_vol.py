from finlab import data, login
import pandas as pd
import os
import json

# Login
API_TOKEN = "WxYZVitl9Ly7elxSHam9yTSgTq1VXS+tz2CODiBY5N4SGiM4FjQuXr1kk+1V7gsv#vip_m"
login(api_token=API_TOKEN)

def load_categories():
    categories = {}
    csv_path = os.path.join(os.path.dirname(__file__), '..', 'category.csv')
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split(',')
                if not parts: continue
                cat_name = parts[0]
                stock_ids = [s for s in parts[1:] if s and s.strip()]
                if stock_ids:
                    categories[cat_name] = stock_ids
    except Exception as e:
        print(f"Error loading categories: {e}")
    return categories

def check_volume():
    print("--- Loading Categories ---")
    categories = load_categories()
    if '水泥' not in categories:
        print("Category '水泥' not found!")
        return
    
    stock_ids = categories['水泥']
    print(f"Stocks in '水泥': {stock_ids}")
    
    print("\n--- Fetching Volume Data ---")
    volume = data.get("price:成交股數")
    print(f"Volume shape: {volume.shape}")
    
    # Check 1101
    sid = '1101'
    if sid in volume.columns:
        print(f"\nVolume for {sid} (last 5 days):")
        print(volume[sid].tail())
        
        # Check values
        v = volume[sid].iloc[-1]
        print(f"Latest volume: {v} (Type: {type(v)})")
    else:
        print(f"{sid} not in volume columns")

    # Simulate get_category_details logic
    print("\n--- Simulating API Response ---")
    close = data.get("price:收盤價")
    open_ = data.get("price:開盤價")
    high = data.get("price:最高價")
    low = data.get("price:最低價")
    
    # Filter last 10 days for brevity
    close = close.iloc[-10:]
    open_ = open_.iloc[-10:]
    high = high.iloc[-10:]
    low = low.iloc[-10:]
    volume = volume.iloc[-10:]
    
    stock_data = {}
    # Just check 1101
    if sid in close.columns:
         df = pd.DataFrame({
            'date': close.index,
            'open': open_[sid],
            'high': high[sid],
            'low': low[sid],
            'close': close[sid],
            'volume': volume[sid] if sid in volume.columns else 0
        }).dropna()
         
         df['date'] = df['date'].dt.strftime('%Y-%m-%d')
         records = df.to_dict(orient='records')
         print(f"\nAPI Response Record for {sid} (Last item):")
         print(json.dumps(records[-1], indent=2))

if __name__ == "__main__":
    check_volume()
