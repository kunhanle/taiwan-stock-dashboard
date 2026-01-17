import yfinance as yf
import pandas as pd

tickers = {
    'Tin': 'TINM.L',
    'Lead': 'LEED.L' # or AIGL.L? WisdomTree Lead is usually LEED.L
}

for name, ticker in tickers.items():
    print(f"Checking {name} ({ticker})...")
    try:
        df = yf.download(ticker, period="1mo", progress=False)
        if not df.empty:
            print(f"  [OK] Found {len(df)} rows. Last price: {df['Close'].iloc[-1]}")
        else:
            print(f"  [FAIL] No data found.")
    except Exception as e:
        print(f"  [ERROR] {e}")
