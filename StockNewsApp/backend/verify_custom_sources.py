from news_service import get_stock_news

def verify_sources(stock_id):
    print(f"Verifying custom sources for {stock_id} through get_stock_news...")
    news = get_stock_news(stock_id, days=7)
    print(f"Total articles found: {len(news)}")

verify_sources("2330")
