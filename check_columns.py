from finlab import data, login
import os

API_TOKEN = os.environ.get("FINLAB_API_TOKEN") or open(os.path.expanduser("~/.finlab_token"), encoding="utf-8").read().strip()
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
