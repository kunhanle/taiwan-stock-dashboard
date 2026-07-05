"""ETF sector-rotation monitor.

A standalone dashboard that ranks US sector/thematic ETFs by relative strength
vs SPY — a cleaner read on sector rotation than watching single stocks (an ETF
smooths out idiosyncratic single-name noise). Independent of the US->TW linkage
map; computed into the nightly snapshot and served via /api/linkage/etf-monitor.
"""
from __future__ import annotations

import linkage_engine as le

BENCH = "SPY"  # relative-strength benchmark: broad market

# (ticker, theme, name_zh) — verified live 2026-07. Grouped for the UI.
ETF_UNIVERSE: list[tuple[str, str, str]] = [
    # 大盤/基準
    ("SPY", "大盤基準", "S&P 500"),
    ("QQQ", "大盤基準", "Nasdaq 100"),
    ("DIA", "大盤基準", "道瓊工業"),
    ("IWM", "大盤基準", "小型股 Russell2000"),
    ("MDY", "大盤基準", "中型股"),
    # 11 大類股
    ("XLK", "11大類股", "科技"),
    ("XLF", "11大類股", "金融"),
    ("XLE", "11大類股", "能源"),
    ("XLV", "11大類股", "醫療保健"),
    ("XLI", "11大類股", "工業"),
    ("XLP", "11大類股", "必需消費"),
    ("XLY", "11大類股", "非必需消費"),
    ("XLU", "11大類股", "公用事業"),
    ("XLB", "11大類股", "原物料"),
    ("XLRE", "11大類股", "房地產"),
    ("XLC", "11大類股", "通訊服務"),
    # 半導體
    ("SMH", "半導體", "費半龍頭權重"),
    ("SOXX", "半導體", "半導體"),
    ("PSI", "半導體", "半導體(動態)"),
    ("XSD", "半導體", "半導體(等權)"),
    # 軟體/雲端/資安
    ("IGV", "軟體雲端資安", "軟體"),
    ("WCLD", "軟體雲端資安", "雲端軟體"),
    ("SKYY", "軟體雲端資安", "雲端運算"),
    ("CIBR", "軟體雲端資安", "資安"),
    ("HACK", "軟體雲端資安", "資安(HACK)"),
    ("BUG", "軟體雲端資安", "資安(BUG)"),
    # AI/機器人/網路/金融科技/遊戲
    ("BOTZ", "AI機器人數位", "機器人AI"),
    ("ROBO", "AI機器人數位", "機器人自動化"),
    ("IRBO", "AI機器人數位", "AI與機器人"),
    ("AIQ", "AI機器人數位", "AI科技"),
    ("FDN", "AI機器人數位", "網路"),
    ("SOCL", "AI機器人數位", "社群媒體"),
    ("FINX", "AI機器人數位", "金融科技"),
    ("IPAY", "AI機器人數位", "行動支付"),
    ("ESPO", "AI機器人數位", "遊戲電競"),
    ("HERO", "AI機器人數位", "電競(HERO)"),
    # 能源轉型
    ("TAN", "能源轉型", "太陽能"),
    ("ICLN", "能源轉型", "潔淨能源"),
    ("QCLN", "能源轉型", "潔淨能源(QCLN)"),
    ("FAN", "能源轉型", "風能"),
    ("LIT", "能源轉型", "鋰電池"),
    ("BATT", "能源轉型", "電池金屬"),
    ("KARS", "能源轉型", "電動車"),
    ("URA", "能源轉型", "鈾/核能"),
    ("URNM", "能源轉型", "鈾礦"),
    ("NLR", "能源轉型", "核能"),
    ("GRID", "能源轉型", "智慧電網/基建"),
    ("PAVE", "能源轉型", "美國基建"),
    ("IFRA", "能源轉型", "基礎建設"),
    # 航太國防/航空/太空
    ("ITA", "航太國防航空", "航太國防"),
    ("PPA", "航太國防航空", "航太國防(PPA)"),
    ("XAR", "航太國防航空", "航太國防(等權)"),
    ("SHLD", "航太國防航空", "國防科技"),
    ("JETS", "航太國防航空", "航空"),
    ("UFO", "航太國防航空", "太空"),
    ("ARKX", "航太國防航空", "太空探索"),
    # 生技醫療
    ("XBI", "生技醫療", "生技(等權,彈性大)"),
    ("IBB", "生技醫療", "生技(權重)"),
    ("ARKG", "生技醫療", "基因革命"),
    ("PPH", "生技醫療", "製藥"),
    ("IHI", "生技醫療", "醫療器材"),
    ("IHE", "生技醫療", "製藥(IHE)"),
    # 金屬礦業
    ("XME", "金屬礦業", "金屬礦業"),
    ("GDX", "金屬礦業", "金礦"),
    ("GDXJ", "金屬礦業", "小型金礦"),
    ("SIL", "金屬礦業", "銀礦"),
    ("COPX", "金屬礦業", "銅礦"),
    ("SLX", "金屬礦業", "鋼鐵"),
    ("REMX", "金屬礦業", "稀土/戰略金屬"),
    ("PICK", "金屬礦業", "金屬礦業(PICK)"),
    # 農業/林木/油氣/水
    ("MOO", "農業能源水", "農業"),
    ("VEGI", "農業能源水", "農企業"),
    ("WOOD", "農業能源水", "林木"),
    ("XOP", "農業能源水", "油氣探勘"),
    ("OIH", "農業能源水", "油田服務"),
    ("AMLP", "農業能源水", "能源管線MLP"),
    ("PHO", "農業能源水", "水資源"),
    # 消費零售/營建/金融/運輸/汽車
    ("XRT", "消費營建金融運輸", "零售"),
    ("VDC", "消費營建金融運輸", "必需消費"),
    ("XHB", "消費營建金融運輸", "營建"),
    ("ITB", "消費營建金融運輸", "住宅營建"),
    ("VNQ", "消費營建金融運輸", "REIT不動產"),
    ("KBE", "消費營建金融運輸", "銀行"),
    ("KRE", "消費營建金融運輸", "區域銀行"),
    ("KIE", "消費營建金融運輸", "保險"),
    ("IAI", "消費營建金融運輸", "券商/交易所"),
    ("IYT", "消費營建金融運輸", "運輸"),
    ("BOAT", "消費營建金融運輸", "航運"),
    ("SEA", "消費營建金融運輸", "海運"),
    ("DRIV", "消費營建金融運輸", "自駕電動車"),
    ("CARZ", "消費營建金融運輸", "汽車"),
    # 國家/區域
    ("FXI", "國家區域", "中國大型股"),
    ("KWEB", "國家區域", "中國網路"),
    ("MCHI", "國家區域", "中國"),
    ("ASHR", "國家區域", "中國A股"),
    ("EWT", "國家區域", "台灣"),
    ("EWY", "國家區域", "韓國"),
    ("EWJ", "國家區域", "日本"),
    ("INDA", "國家區域", "印度"),
    # 主題
    ("QTUM", "新主題", "量子運算"),
    ("BLOK", "新主題", "區塊鏈"),
]


def compute_etf_monitor(period: str = "3mo") -> dict:
    syms = sorted({BENCH} | {t for t, _, _ in ETF_UNIVERSE})
    ret = le.fetch_returns(syms, period=period)

    def mv(t: str, w: int):
        if t not in ret.columns:
            return None
        return le._move_and_z(ret[t], w)[0]

    b1, b5, b20 = mv(BENCH, 1), mv(BENCH, 5), mv(BENCH, 20)
    etfs = []
    for t, theme, name in ETF_UNIVERSE:
        m1, m5, m20 = mv(t, 1), mv(t, 5), mv(t, 20)
        etfs.append({
            "ticker": t, "theme": theme, "name": name,
            "move_1d": m1, "move_5d": m5, "move_20d": m20,
            "rs_5d": (m5 - (b5 or 0.0)) if m5 is not None else None,
            "rs_20d": (m20 - (b20 or 0.0)) if m20 is not None else None,
        })
    # rank by 5-day relative strength (None sinks)
    etfs.sort(key=lambda e: (e["rs_5d"] is not None, e["rs_5d"] or -9), reverse=True)
    return {"benchmark": BENCH, "bench_move_1d": b1, "bench_move_5d": b5,
            "bench_move_20d": b20, "etfs": etfs}
