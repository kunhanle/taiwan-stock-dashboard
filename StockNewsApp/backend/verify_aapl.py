from news_service import get_stock_news

print("\n--- Verifying AAPL (Apple) News ---")
news = get_stock_news("AAPL", days=5)
print(f"Found {len(news)} articles.")
for item in news[:5]:
    print(f"- {item['title']} ({item['date']}) [{item['source']}]")
