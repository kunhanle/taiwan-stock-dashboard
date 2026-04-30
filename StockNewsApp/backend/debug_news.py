from news_service import get_stock_news, get_stock_name
import json
from datetime import datetime

stock_id = "6903"
start = "2025-10-01"
end = "2025-12-30"

print(f"DEBUG: Testing stock {stock_id} ({get_stock_name(stock_id)}) from {start} to {end}")

try:
    from GoogleNews import GoogleNews
    
    terms = [
        "台積電",
        "2330 台積電"
    ]
    for term in terms:
        print(f"\nDEBUG: Testing term '{term}' with period='1y'")
        gn = GoogleNews(period='1y')
        gn.search(term)
        res = gn.results()
        print(f" - Found {len(res)} results.")
        for item in res[:2]:
             print(f"   - {item['title']} ({item['date']})")
    
except Exception as e:
    import traceback
    traceback.print_exc()
