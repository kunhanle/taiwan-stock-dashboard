"""Commodity futures monitor.

A standalone board of key commodity futures (energy, precious/industrial metals,
agriculture) with price moves across horizons (1d/1w/1m/3m/1y). Independent of
the US->TW linkage map; computed into the nightly snapshot and served via
/api/linkage/commodity-monitor. Useful macro context — e.g. crude falling while
petrochemical spreads widen — but note commodity *price* correlation to a stock
is usually a poor linkage signal (a common demand factor dominates daily
co-movement); read commodities as cost inputs / regime context, not as a corr.
"""
from __future__ import annotations

import linkage_engine as le

# (ticker, category, name_zh) — verified live 2026-07 via yfinance.
COMMODITY_UNIVERSE: list[tuple[str, str, str]] = [
    # 能源
    ("CL=F", "能源", "WTI原油"),
    ("BZ=F", "能源", "Brent原油"),
    ("NG=F", "能源", "天然氣"),
    ("RB=F", "能源", "汽油"),
    ("HO=F", "能源", "熱燃油"),
    # 貴金屬
    ("GC=F", "貴金屬", "黃金"),
    ("SI=F", "貴金屬", "白銀"),
    ("PL=F", "貴金屬", "白金"),
    ("PA=F", "貴金屬", "鈀金"),
    # 工業金屬
    ("HG=F", "工業金屬", "銅"),
    # 農產
    ("ZC=F", "農產", "玉米"),
    ("ZS=F", "農產", "黃豆"),
    ("ZW=F", "農產", "小麥"),
    ("KC=F", "農產", "咖啡"),
    ("SB=F", "農產", "糖"),
    ("CT=F", "農產", "棉花"),
    ("CC=F", "農產", "可可"),
    ("LE=F", "農產", "活牛"),
]

# label key -> trailing-session window
HORIZONS: list[tuple[str, int]] = [
    ("move_1d", 1), ("move_5d", 5), ("move_20d", 20),
    ("move_60d", 60), ("move_252d", 252),
]


def compute_commodity_monitor(period: str = "1y") -> dict:
    syms = sorted({t for t, _, _ in COMMODITY_UNIVERSE})
    ret = le.fetch_returns(syms, period=period)

    def mv(t: str, w: int):
        if t not in ret.columns:
            return None
        return le._move_and_z(ret[t], w)[0]

    out = []
    for t, cat, name in COMMODITY_UNIVERSE:
        row = {"ticker": t, "category": cat, "name": name}
        for k, w in HORIZONS:
            row[k] = mv(t, w)
        out.append(row)
    # rank by 1-month move (None sinks)
    out.sort(key=lambda c: (c["move_20d"] is not None, c["move_20d"] or -9), reverse=True)
    return {"commodities": out, "horizons": [k for k, _ in HORIZONS]}
