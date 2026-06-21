"""
B-layer: fundamental (revenue-YoY) linkage.

Complements the A-layer price read-through (linkage_engine.py). For cyclical
supply chains, the real linkage shows up in REVENUE YoY co-movement, not daily
stock-price correlation (validated 2026-06: equipment supply-chain names track
AMAT revenue YoY at 0.5-0.57 with a 0-2 quarter lag, vs price partial 0.03-0.19).

Data sources:
  * US quarterly revenue : SEC EDGAR companyconcept XBRL (free, ~6-10y history),
                           via the SEC-computed calendar-quarter `frame` field.
  * TW monthly revenue   : FinLab `monthly_revenue:當月營收` (long history),
                           aggregated to calendar quarters.

Output per category: each TW node's revenue-YoY series + correlation and best
lead/lag against the category's aggregate US-leader revenue YoY.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd
from sqlmodel import Session, select

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from models import TwLinkageNode, UsCategoryTicker  # noqa: E402

SEED_DIR = BACKEND_DIR.parent / "linkage-service" / "seed"
US_REV_CACHE = SEED_DIR / "us_revenue_cache.json"
CIK_CACHE = SEED_DIR / "sec_cik_map.json"

SEC_UA = {"User-Agent": "taiwan-stock-dashboard research kunhanle@gmail.com"}
# Revenue XBRL concepts, tried in order (US-GAAP filers).
US_REVENUE_CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
]
_FRAME_RE = re.compile(r"^CY(\d{4})Q([1-4])$")


# --------------------------------------------------------------------------- #
# US quarterly revenue via SEC EDGAR
# --------------------------------------------------------------------------- #
def _http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=SEC_UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _cik_map() -> dict:
    m = _load_json(CIK_CACHE)
    if m:
        return m
    d = _http_json("https://www.sec.gov/files/company_tickers.json")
    m = {row["ticker"].upper(): f"{int(row['cik_str']):010d}" for row in d.values()}
    CIK_CACHE.write_text(json.dumps(m), encoding="utf-8")
    return m


def us_quarterly_revenue(ticker: str, cache: dict, ciks: dict) -> dict:
    """{'2024Q2': revenue, ...} from EDGAR calendar-quarter frames. Cached."""
    t = ticker.upper()
    if t in cache:
        return cache[t]
    cik = ciks.get(t)
    quarters: dict[str, float] = {}
    if cik:
        for concept in US_REVENUE_CONCEPTS:
            try:
                d = _http_json(f"https://data.sec.gov/api/xbrl/companyconcept/"
                               f"CIK{cik}/us-gaap/{concept}.json")
            except Exception:
                continue
            for f in d.get("units", {}).get("USD", []):
                m = _FRAME_RE.match(f.get("frame", "") or "")
                if m:
                    quarters[f"{m.group(1)}Q{m.group(2)}"] = float(f["val"])
            if quarters:
                break
            time.sleep(0.2)  # be gentle on SEC
    cache[t] = quarters  # cache even empties (avoid re-hitting foreign filers)
    return quarters


def _qkey_to_period(qkey: str) -> pd.Period:
    y, q = qkey.split("Q")
    return pd.Period(year=int(y), quarter=int(q), freq="Q")


def us_revenue_yoy_series(ticker: str, cache: dict, ciks: dict) -> pd.Series:
    q = us_quarterly_revenue(ticker, cache, ciks)
    if not q:
        return pd.Series(dtype="float64")
    s = pd.Series({_qkey_to_period(k): v for k, v in q.items()}).sort_index()
    return (s / s.shift(4) - 1).dropna()


# --------------------------------------------------------------------------- #
# TW monthly revenue via FinLab
# --------------------------------------------------------------------------- #
_TW_REV = None  # cached monthly-revenue DataFrame


def _finlab_token() -> str | None:
    tok = os.getenv("FINLAB_API_TOKEN")
    if tok:
        return tok
    p = Path.home() / ".finlab_token"
    return p.read_text(encoding="utf-8").strip() if p.exists() else None


def _tw_monthly_revenue() -> pd.DataFrame:
    global _TW_REV
    if _TW_REV is None:
        import contextlib
        with contextlib.redirect_stdout(sys.stderr):  # keep finlab noise off stdout
            from finlab import data, login
            login(api_token=_finlab_token())
            _TW_REV = data.get("monthly_revenue:當月營收")
    return _TW_REV


def tw_revenue_yoy_series(stock_id: str, freq: str = "Q") -> pd.Series:
    rev = _tw_monthly_revenue()
    if stock_id not in rev.columns:
        return pd.Series(dtype="float64")
    s = rev[stock_id].dropna()
    if freq == "Q":
        s = s.resample("QE").sum()
        yoy = (s / s.shift(4) - 1).dropna()
        yoy.index = yoy.index.to_period("Q")
    else:  # monthly
        yoy = (s / s.shift(12) - 1).dropna()
        yoy.index = yoy.index.to_period("M")
    return yoy


# --------------------------------------------------------------------------- #
# Linkage
# --------------------------------------------------------------------------- #
def _best_leadlag(us: pd.Series, tw: pd.Series, max_lag: int = 2) -> dict:
    """Correlate tw vs us at quarterly shifts. lag>0 = TW lags US (US leads)."""
    base = pd.DataFrame({"us": us, "tw": tw}).dropna()
    c0 = float(base["us"].corr(base["tw"])) if len(base) >= 5 else None
    best = {"lag": 0, "corr": c0, "n": len(base)}
    for k in range(-max_lag, max_lag + 1):
        if k == 0:
            continue
        d = pd.DataFrame({"us": us, "tw": tw.shift(k)}).dropna()
        if len(d) >= 5:
            ck = float(d["us"].corr(d["tw"]))
            if best["corr"] is None or abs(ck) > abs(best["corr"]):
                best = {"lag": k, "corr": ck, "n": len(d)}
    return {"corr_same": c0, **{f"best_{k}": v for k, v in best.items()}}


def category_revenue_linkage(session: Session, slug: str) -> dict:
    """B-layer view for one category: US-leader revenue YoY + each TW node's
    revenue YoY with correlation and best lead/lag."""
    us_tickers = session.exec(select(UsCategoryTicker.ticker).where(
        UsCategoryTicker.category_slug == slug)).all()
    tw_nodes = session.exec(select(TwLinkageNode).where(
        TwLinkageNode.category_slug == slug,
        TwLinkageNode.exclude_from_scoring == False)).all()  # noqa: E712

    cache, ciks = _load_json(US_REV_CACHE), _cik_map()
    # Aggregate US revenue YoY = equal-weight mean of available tickers' YoY.
    us_yoys = {}
    for t in us_tickers:
        s = us_revenue_yoy_series(t, cache, ciks)
        if not s.empty:
            us_yoys[t] = s
    US_REV_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    us_agg = pd.DataFrame(us_yoys).mean(axis=1) if us_yoys else pd.Series(dtype="float64")

    nodes = []
    for n in tw_nodes:
        tw = tw_revenue_yoy_series(n.ticker, freq="Q")
        ll = _best_leadlag(us_agg, tw) if (not us_agg.empty and not tw.empty) else {}
        nodes.append({
            "ticker": n.ticker, "name": n.name, "role": n.role,
            "tw_yoy_latest": float(tw.iloc[-1]) if not tw.empty else None,
            "tw_yoy_recent": {str(p): round(float(v), 3) for p, v in tw.tail(6).items()},
            **ll,
        })
    nodes.sort(key=lambda x: abs(x.get("best_corr") or 0), reverse=True)
    return {
        "slug": slug,
        "us_tickers_with_data": list(us_yoys),
        "us_yoy_latest": float(us_agg.iloc[-1]) if not us_agg.empty else None,
        "us_yoy_recent": {str(p): round(float(v), 3) for p, v in us_agg.tail(8).items()},
        "nodes": nodes,
    }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(BACKEND_DIR))
    from database import engine
    slug = sys.argv[1] if len(sys.argv) > 1 else "semi-wfe"
    with Session(engine) as s:
        r = category_revenue_linkage(s, slug)
    print(json.dumps(r, ensure_ascii=False, indent=2))
