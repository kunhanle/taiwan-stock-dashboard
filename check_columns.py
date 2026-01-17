from finlab import data, login
import os

API_TOKEN = "WxYZVitl9Ly7elxSHam9yTSgTq1VXS+tz2CODiBY5N4SGiM4FjQuXr1kk+1V7gsv#vip_m"
login(api_token=API_TOKEN)

candidates = [
    'taiex_total_index:成交金額',
    'taiex_total_index:成交值',
    'taiex_total_index:成交股數',
    'taiex_total_index:總成交股數',
    'taiex_total_index:成交量'
]

print("Testing columns for taiex_total_index...")
for c in candidates:
    try:
        s = data.get(c)
        print(f"PASS: {c} - Latest: {s.iloc[-1]}")
    except Exception as e:
        print(f"FAIL: {c} - Error: {e}")
