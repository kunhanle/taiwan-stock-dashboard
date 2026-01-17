from finlab import data, login
import pandas as pd

# 1. Login
print("--- Logging in ---")
api_token = "WxYZVitl9Ly7elxSHam9yTSgTq1VXS+tz2CODiBY5N4SGiM4FjQuXr1kk+1V7gsv#vip_m"
login(api_token=api_token)

# 2. Fetch Data
print("\n--- Fetching Data (price:收盤價) ---")
try:
    close = data.get('price:收盤價')
    print(f"Data Shape: {close.shape}")
    print(f"Data Columns (First 10): {close.columns[:10].tolist()}")
    print("\nLast 5 rows of Close Price:")
    print(close.tail())
except Exception as e:
    print(f"Error fetching data: {e}")
    exit(1)

# 3. Process Logic Verification
print("\n--- Verifying Processing Logic ---")
# Filter stocks (4-digit, >= 1101)
valid_symbols = [s for s in close.columns if len(s) == 4 and s.isdigit() and int(s) >= 1101]
close = close[valid_symbols]
print(f"Valid Stock Count: {len(valid_symbols)}")

# Calculate rolling stats (just for verification)
window_52w = 250
rolling_max_52w = close.rolling(window=window_52w).max()
current_prices = close.iloc[-1]
current_highs = rolling_max_52w.iloc[-1]

# Check how many hit highs today
new_highs_count = (current_prices == current_highs).sum()
print(f"\nMetric Check (Latest Date):")
print(f"Number of stocks at 52-week high today: {new_highs_count}")
