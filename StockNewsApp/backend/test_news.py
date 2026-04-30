from news_service import get_stock_news
import pandas as pd

try:
    print("Fetching news for 2330 (TSMC)...")
    news = get_stock_news("2330", days=7)
    print(f"Found {len(news)} articles.")
    if news:
        print("Top article:")
        print(news[0])
except Exception as e:
    print(f"Error: {e}")
