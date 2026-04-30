from GoogleNews import GoogleNews

def test_gn(term, lang=None, region=None):
    print(f"\nTesting: '{term}' (lang={lang}, region={region})")
    if lang and region:
        gn = GoogleNews(lang=lang, region=region, period='1y')
    else:
        gn = GoogleNews(period='1y')
    gn.search(term)
    res = gn.results()
    print(f"Found {len(res)} results.")
    for item in res[:3]:
        print(f" - {item['title']} ({item['date']})")

test_gn("2330 台積電")
test_gn("2330 台積電", lang='zh-TW', region='TW')
test_gn("台積電", lang='zh-TW', region='TW')
test_gn("2330", lang='zh-TW', region='TW')
