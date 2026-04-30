from GoogleNews import GoogleNews

def test_combined_query(term, domains):
    # Construct combined query: term (site:domain1 OR site:domain2)
    site_part = " OR ".join([f"site:{d}" for d in domains])
    query = f"{term} ({site_part})"
    print(f"\nCombined Query: '{query}'")
    gn = GoogleNews(lang='zh-TW', region='TW', period='7d')
    try:
        gn.search(query)
        res = gn.results()
        print(f"Found {len(res)} results.")
        for item in res[:5]:
             print(f" - {item['title']} [{item['media']}]")
    except Exception as e:
        print(f"Error: {e}")

domains = ['tw.stock.yahoo.com', 'www.moneydj.com', '36kr.com']
test_combined_query("台積電", domains)
