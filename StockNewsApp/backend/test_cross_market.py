from news_service import get_stock_news

def test_stock(stock_id):
    print(f"\n--- Testing Stock: {stock_id} ---")
    news = get_stock_news(stock_id, days=7)
    print(f"Found {len(news)} articles.")
    if news:
        # Check title language to confirm region/lang settings worked
        print(f"Top article: {news[0]['title']} ({news[0]['date']})")
        print(f"Source: {news[0]['source']}")
    else:
        print("ERROR: No news found!")

# Test US Stock
test_stock("AAPL")

# Test TW Stock
test_stock("2330")
