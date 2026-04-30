from news_service import _get_stock_news_impl, is_us_stock, get_stock_name
from datetime import datetime, timedelta
import dateparser

def debug_us_stock(stock_id):
    print(f"\n--- DEBUGGING {stock_id} ---")
    days = 7
    current_timestamp = datetime.now().timestamp()
    start_ts = current_timestamp - (days * 24 * 60 * 60)
    
    # Run the impl and see where it fails
    # Since I want to see internal state, I might copy logic here or use print in news_service
    # Let's use get_stock_news but I need to make sure I see the logs
    
    try:
        results = _get_stock_news_impl(stock_id, days, None, None, "debug_key")
        print(f"Total raw results from _get_stock_news_impl: {len(results)}")
        
        if len(results) == 0:
            print("WARNING: Zero results returned from implementation.")
        else:
            for i, item in enumerate(results[:5]):
                print(f"[{i}] Title: {item['title'][:50]}... | Date: {item['date']} | TS: {item.get('timestamp')}")
                
    except Exception as e:
        print(f"ERROR during _get_stock_news_impl: {e}")

debug_us_stock("AAPL")
debug_us_stock("TSLA")
