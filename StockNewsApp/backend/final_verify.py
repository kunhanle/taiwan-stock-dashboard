from news_service import get_stock_news

def verify(stock_id):
    print(f"Verifying {stock_id}...")
    news = get_stock_news(stock_id, days=30)
    print(f"Found {len(news)} articles.")
    if news:
        print(f"Top: {news[0]['title']} ({news[0]['date']})")
    else:
        print("ALERT: NO NEWS FOUND")

verify("2330")
verify("6903")
