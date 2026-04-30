from GoogleNews import GoogleNews
from datetime import datetime, timedelta
import pandas as pd
import os
from urllib.parse import urlparse
from finlab import data, login
from dotenv import load_dotenv
import dateparser

load_dotenv()
api_token = os.getenv("FINLAB_API_TOKEN")
if api_token:
    login(api_token=api_token)
else:
    print("Warning: FINLAB_API_TOKEN not found in .env")

# Simple cache for stock names
_stock_name_cache = {}

def is_us_stock(stock_id: str):
    """
    Check if stock_id is a US stock symbol (usually contains letters).
    Taiwan stock IDs are typically 4 or more digits.
    """
    return any(c.isalpha() for c in stock_id)

def get_stock_name(stock_id: str):
    """
    Get Chinese stock name using FinLab API.
    """
    if stock_id in _stock_name_cache:
        return _stock_name_cache[stock_id]
        
    if is_us_stock(stock_id):
        return None
        
    try:
        # Load basic info (this is cached by finlab naturally, but dataframe ops can be heavy)
        # We assume the user has login or it works freely for this table.
        # Ideally we load this once globally, but data.get() handles caching.
        df = data.get('company_basic_info')
        if df is not None:
            # Check if stock_id exists
            # stock_id in df might be string or int. 
            # The df usually has stock_id as specific column or index.
            # User snippet: company_info = data.get('company_basic_info').set_index('stock_id')
            
            # Using query might be faster/safer than set_index entire table
            # But let's follow user snippet logic but optimized
            
            # Ensure stock_id is compatible. API usually returns strings
            matches = df[df['stock_id'] == stock_id]
            if matches.empty:
                matches = df[df['stock_id'] == int(stock_id)] if stock_id.isdigit() else pd.DataFrame()
                
            if not matches.empty:
                name = matches.iloc[0]['公司簡稱']
                _stock_name_cache[stock_id] = name
                return name
                
    except Exception as e:
        print(f"Finlab lookup error: {e}")
        
    return None

def load_custom_sources():
    sources = []
    try:
        # Assuming news_source.txt is one level up from backend/
        file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'news_source.txt')
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        parsed = urlparse(line)
                        domain = parsed.netloc if parsed.netloc else line
                        if domain:
                            # Correction for Threads domain
                            if domain == "www.threads.com" or domain == "threads.com":
                                domain = "www.threads.net"
                            sources.append(domain)
    except Exception as e:
        print(f"Error loading custom sources: {e}")
    return sources

def get_finlab_news(stock_id: str, days: int = 3, start_date: str = None, end_date: str = None):
    """
    Fetch news from FinLab 'tw_news_cnyes' and filter by stock_id.
    """
    news_list = []
    try:
        # Determine strict filter range
        start_ts = 0
        end_ts = datetime.now().timestamp()
        
        if start_date and end_date:
             s_dt = datetime.strptime(start_date, "%Y-%m-%d")
             e_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1) - timedelta(seconds=1)
             start_ts = s_dt.timestamp()
             end_ts = e_dt.timestamp()
        else:
             current_timestamp = datetime.now().timestamp()
             start_ts = current_timestamp - (days * 24 * 60 * 60)
        
        # Pull data (this caches internally in finlab usually)
        # However, getting the WHOLE table might be slow if uncached.
        # Ideally we'd filter at API level but finlab works with dataframes locally mostly.
        df = data.get('tw_news_cnyes')
        
        if df is not None and not df.empty:
            # The 'date' column in FinLab is often a string or datetime
            # We need to ensure it's comparable
            # User sample: 2013-01-02 08:09:00
            
            # Filter by stock_id in 'stock_ids' column (comma separated)
            # We assume stock_id is 4 digit string
            
            # Naive filter: string contains (might match 6903 in 16903)
            # Safer: check split string
            # Vectorized approach check is hard without exploding.
            # Let's use simple apply for now or string matching if IDs are fixed width
            
            # String contains is fast:
            mask = df['stock_ids'].astype(str).str.contains(stock_id, na=False)
            filtered_df = df[mask]
            
            # Now post-filter to safely ensure exact match (exclude '16903' if searching '6903')
            # But wait, commas separate them. e.g. "1310,2012"
            # So searching ",6903," or "^6903," or ",6903$" or "^6903$" covers it.
            # Building a regex is safest.
            # Regex: (^|,)6903(,|$)
            
            regex_pat = f'(^|,){stock_id}(,|$)'
            mask_strict = df['stock_ids'].astype(str).str.contains(regex_pat, regex=True, na=False)
            filtered_df = df[mask_strict]
            
            # Filter by date
            # Ensure 'date' is datetime
            filtered_df['date'] = pd.to_datetime(filtered_df['date'])
            
            # convert to timestamp
            # Filter rows where date is within range
            # Pandas can filter by datetime directly
            
            dt_start = datetime.fromtimestamp(start_ts)
            dt_end = datetime.fromtimestamp(end_ts)
            
            filtered_df = filtered_df[(filtered_df['date'] >= dt_start) & (filtered_df['date'] <= dt_end)]
            
            for _, row in filtered_df.iterrows():
                # Convert to our News format
                ts = row['date'].timestamp()
                news_list.append({
                    "title": row['title'],
                    "date": row['date'].strftime("%Y-%m-%d %H:%M"),
                    "datetime": row['date'],
                    "source": "CNYES (FinLab)",
                    "link": row['url'],
                    "summary": row['title'], # Use title as initial summary
                    "timestamp": ts
                })
                
            print(f"DEBUG: FinLab found {len(news_list)} news items for {stock_id}")
            
    except Exception as e:
        print(f"Error fetching FinLab news: {e}")
        
    return news_list


# In-memory cache: {cache_key: (timestamp, data)}
_news_cache = {}
CACHE_TTL = 1800  # 30 minutes

def get_stock_news(stock_id: str, days: int = 3, start_date: str = None, end_date: str = None):
    """
    Fetches news for a given stock ID using GoogleNews.
    If start_date and end_date are provided (YYYY-MM-DD), they override 'days'.
    """
    # Check cache
    cache_key = f"{stock_id}_{days}_{start_date}_{end_date}"
    current_time = datetime.now().timestamp()
    
    if cache_key in _news_cache:
        ts, cached_data = _news_cache[cache_key]
        if current_time - ts < CACHE_TTL:
            print(f"DEBUG: Returning cached results for {cache_key}")
            return cached_data
            
    # Function to cache and return
    result = _get_stock_news_impl(stock_id, days, start_date, end_date, cache_key)
    _news_cache[cache_key] = (current_time, result)
    return result

def _get_stock_news_impl(stock_id, days, start_date, end_date, cache_key):
    # Determine search term
    search_term = stock_id
    stock_name = get_stock_name(stock_id)
    
    if stock_name:
        search_term = f"{stock_id} {stock_name}"
        print(f"DEBUG: Using enhanced search term: {search_term}")
    elif len(stock_id) == 4 and stock_id.isdigit():
        search_term = f"{stock_id} TW stock"
    
    # Initialize GoogleNews
    # Note: scraping can be flaky.
    
    # Strategy: Use period based search if date range is recent (e.g., within 90 days)
    # or just rely on period search + local filtering because start/end is flaky.
    
    period_str = f'{days}d'
    use_date_range_query = False
    
    if start_date and end_date:
        try:
           s_dt = datetime.strptime(start_date, "%Y-%m-%d")
           e_dt = datetime.strptime(end_date, "%Y-%m-%d")
           delta = datetime.now() - s_dt
           # If the start date is within last ~100 days, use period logic which is reliable
           if delta.days < 100:
               days_needed = delta.days + 2 # Add buffer
               if days_needed > 28:
                   period_str = '1y' # GoogleNews period handling can be finicky, 1y is safer for months-long ranges
               else:
                   period_str = f'{days_needed}d'
               print(f"DEBUG: Using period fallback {period_str} instead of date range query") # Log strategy
           else:
               use_date_range_query = True
               s_str = s_dt.strftime("%m/%d/%Y")
               e_str = e_dt.strftime("%m/%d/%Y")
               print(f"DEBUG: Search with date range query: {s_str} - {e_str}")
        except Exception as e:
            print(f"Date calculation error: {e}. Using default period.")

    # Detect stock type for settings
    is_us = is_us_stock(stock_id)
    if is_us:
        gn_lang = 'en'
        gn_region = 'US'
        # Improvement: US stocks search better with "stock" keyword
        if "stock" not in search_term.lower():
            search_term = f"{search_term} stock"
        print(f"DEBUG: US stock detected, using search_term={search_term}, lang={gn_lang}, region={gn_region}")
    else:
        gn_lang = 'zh-TW'
        gn_region = 'TW'
        print(f"DEBUG: Taiwan stock detected, using lang={gn_lang}, region={gn_region}")

    if use_date_range_query:
         googlenews = GoogleNews(lang=gn_lang, region=gn_region, start=s_str, end=e_str)
    else:
         googlenews = GoogleNews(lang=gn_lang, region=gn_region, period=period_str)

    # Base search
    try:
        googlenews.search(search_term)
        results = googlenews.results() or []
    except Exception as e:
        print(f"Error in base GoogleNews search: {e}")
        results = []
    
    # Custom sources search (Skip for US stocks to avoid 429 and irrelevant sources)
    if is_us:
        print("DEBUG: Skipping custom sources for US stock to avoid rate limits.")
        custom_sources = []
    else:
        custom_sources = load_custom_sources()
        print(f"DEBUG: Found custom sources: {custom_sources}")
    
    for source in custom_sources:
        try:
            # Create a specific query for this site
            # Uses the enhanced search term if available, otherwise stock_id
            # site_query = f"{search_term} site:{source}"
            
            # Prioritize stock name for better results on custom sites (e.g., 36kr)
            # Fallback to search_term (id + name) or stock_id
            query_base = stock_name if stock_name else (search_term if search_term else stock_id)
            site_query = f"{query_base} site:{source}"
            print(f"DEBUG: Searching custom source: {site_query}")
            
            if use_date_range_query:
                 gn_source = GoogleNews(lang=gn_lang, region=gn_region, start=s_str, end=e_str)
            else:
                 gn_source = GoogleNews(lang=gn_lang, region=gn_region, period=period_str)

            gn_source.search(site_query)
            source_results = gn_source.results()
            if source_results:
                print(f"DEBUG: Source {source} found {len(source_results)} results.")
                results.extend(source_results)
            else:
                print(f"DEBUG: Source {source} found 0 results.")
        except Exception as e:
            print(f"Error searching source {source}: {e}")
            
    # Deduplicate results based on link
    seen_links = set()
    unique_results = []
    for item in results:
        link = item.get('link')
        if link and link not in seen_links:
            seen_links.add(link)
            unique_results.append(item)
    
    results = unique_results
    
    # If no results and no date range strictness, try just the ID (fallback)
    if not results and not (start_date and end_date):
        googlenews = GoogleNews(lang=gn_lang, region=gn_region, period=period_str)
        googlenews.search(stock_id)
        results = googlenews.results()
        
    news_list = []
    for item in results:
        # Item keys: title, media, date, datetime, desc, link, img
        news_list.append({
            "title": item.get('title'),
            "date": item.get('date'), # string like '1 hour ago' or 'Dec 12, 2024'
            "datetime": item.get('datetime'), # datetime object if parsed
            "source": item.get('media'),
            "link": item.get('link'),
            "summary": item.get('desc') # Initial summary, we will replace/augment with LLM
        })
    
    # Sort by datetime descending
    # Filter out items without datetime or handle them
    # GoogleNews often returns relative time. 'datetime' field is usually populated by the lib.
    
    # Merge FinLab News (Skip for US stocks)
    try:
        if not is_us_stock(stock_id):
            finlab_news = get_finlab_news(stock_id, days, start_date, end_date)
            if finlab_news:
                # Check for duplicates by link before adding
                current_links = {item.get('link') for item in news_list}
                for item in finlab_news:
                    if item.get('link') not in current_links:
                        news_list.append(item)
        else:
            print(f"DEBUG: Skipping FinLab for US stock {stock_id}")
    except Exception as e:
        print(f"Error merging Finlab news: {e}")
    
    # Clean up and sort
    # Ensure datetime is present
    for news in news_list:
        # Use dateparser to ensure we have a timestamp for sorting and filtering
        if news.get('timestamp') is None or news.get('timestamp') == 0:
            try:
                # If datetime object exists (e.g. from GoogleNews or FinLab)
                if isinstance(news.get('datetime'), (pd.Timestamp, datetime)):
                    news['timestamp'] = news['datetime'].timestamp()
                else:
                    # Fallback to parsing the date string
                    dt = dateparser.parse(news['date'], settings={'RELATIVE_BASE': datetime.now()})
                    if dt:
                        news['timestamp'] = dt.timestamp()
                    else:
                        news['timestamp'] = 0
            except Exception:
                news['timestamp'] = 0
        
        # Ensure 'datetime' matches if we successfully parsed it
        if news['timestamp'] > 0 and (news.get('datetime') is None or news.get('datetime') == 0):
             news['datetime'] = datetime.fromtimestamp(news['timestamp'])
              
    # Filter by date (StrictMode)
    # Determine the cutoff timestamps
    
    start_ts = 0
    end_ts = datetime.now().timestamp()
    
    if start_date and end_date:
        try:
            # We already have timestamps, re-calculating range logic
            # Assume start of start_date and end of end_date
            s_dt = datetime.strptime(start_date, "%Y-%m-%d")
            # End date should be end of that day (23:59:59)
            e_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1) - timedelta(seconds=1)
            
            start_ts = s_dt.timestamp()
            end_ts = e_dt.timestamp()
            # print(f"DEBUG: Strict Filtering: {start_ts} to {end_ts}")
        except Exception as e:
            print(f"Date conversion error during filtering: {e}")
    else:
        # Default days logic
        current_timestamp = datetime.now().timestamp()
        start_ts = current_timestamp - (days * 24 * 60 * 60)
        # End ts is effectively now (or infinity)
        
    filtered_news = []
    for news in news_list:
        # Check if news timestamp is within range
        # Note: news['timestamp'] = 0 if parsing failed.
        # We might want to include them if unsure, or exclude them.
        # For now, if we have a strict range, exclude 0.
        ts = news.get('timestamp', 0)
        if ts >= start_ts and ts <= end_ts:
            filtered_news.append(news)
            
    news_list = filtered_news
            
    news_list.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
    
    return news_list
