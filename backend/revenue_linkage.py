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

from models import TwLinkageNode, UsCategory, UsCategoryTicker  # noqa: E402
from linkage_engine import SEMI_CLUSTERS  # reuse the semi-cluster definition  # noqa: E402

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
# #3 lead/lag gating: contemporaneous is primary; a non-zero lead/lag is only
# reported when it's both robust (enough quarters) and a material improvement —
# otherwise best-of-5-shifts overfits noise (and can pick implausible signs).
LEADLAG_MIN_N = 16        # quarters required to trust a shifted correlation
LEADLAG_MIN_GAIN = 0.12   # |corr@lag| must beat |corr@0| by this much


def _leadlag(us: pd.Series, tw: pd.Series, max_lag: int = 2) -> dict:
    """corr_same = contemporaneous; lead_lag reported only if confident.
    lag>0 = TW lags US (US leads); lag<0 = TW leads US."""
    base = pd.DataFrame({"us": us, "tw": tw}).dropna()
    c0 = float(base["us"].corr(base["tw"])) if len(base) >= 5 else None
    best_lag, best_c, best_n = 0, c0, len(base)
    for k in range(-max_lag, max_lag + 1):
        if k == 0:
            continue
        d = pd.DataFrame({"us": us, "tw": tw.shift(k)}).dropna()
        if len(d) >= 5:
            ck = float(d["us"].corr(d["tw"]))
            if best_c is None or abs(ck) > abs(best_c):
                best_lag, best_c, best_n = k, ck, len(d)
    confident = (best_lag != 0 and c0 is not None and best_n >= LEADLAG_MIN_N
                 and abs(best_c) - abs(c0) >= LEADLAG_MIN_GAIN)
    return {
        "corr_same": c0, "n": len(base),
        "lead_lag": best_lag if confident else 0,
        "lead_lag_corr": best_c if confident else c0,
        "lead_lag_confident": confident,
    }


def _partial_corr_q(tw: pd.Series, us: pd.Series, factor: pd.Series):
    """Partial corr(tw, us | factor) on quarter-aligned series. #2: strips the
    broad semi-revenue-cycle factor so we see CATEGORY-specific revenue linkage."""
    df = pd.DataFrame({"tw": tw, "us": us, "f": factor}).dropna()
    if len(df) <= 8:
        return None
    r_tu, r_tf, r_uf = df["tw"].corr(df["us"]), df["tw"].corr(df["f"]), df["us"].corr(df["f"])
    if any(pd.isna(x) for x in (r_tu, r_tf, r_uf)):
        return None
    denom = ((1 - r_tf ** 2) * (1 - r_uf ** 2)) ** 0.5
    return float((r_tu - r_tf * r_uf) / denom) if denom > 1e-6 else None


_SEMI_UNIVERSE = None  # cached {ticker: revenue-YoY series} for all semi US names


def _semi_revenue_factor(session: Session, cache: dict, ciks: dict,
                         exclude: set | None = None) -> pd.Series:
    """Equal-weight mean revenue YoY across the semiconductor US universe,
    EXCLUDING the category's own tickers (else the basket is collinear with the
    factor and the partial is undefined). = the 'rest of the semi cycle'."""
    global _SEMI_UNIVERSE
    if _SEMI_UNIVERSE is None:
        slugs = session.exec(select(UsCategory.slug).where(
            UsCategory.cluster.in_(SEMI_CLUSTERS))).all()
        tickers = session.exec(select(UsCategoryTicker.ticker).where(
            UsCategoryTicker.category_slug.in_(slugs))).all()
        uni = {}
        for t in sorted(set(tickers)):
            s = us_revenue_yoy_series(t, cache, ciks)
            if not s.empty:
                uni[t] = s
        _SEMI_UNIVERSE = uni
    cols = {t: s for t, s in _SEMI_UNIVERSE.items() if t not in (exclude or set())}
    return pd.DataFrame(cols).mean(axis=1) if cols else pd.Series(dtype="float64")


def category_revenue_linkage(session: Session, slug: str) -> dict:
    """B-layer view: US-leader revenue YoY + each TW node's revenue-YoY linkage.
    Semi categories use SOX-equivalent partial (control for the semi revenue
    cycle); non-semi use raw. Reports coverage and gated lead/lag."""
    cat = session.get(UsCategory, slug)
    us_tickers = session.exec(select(UsCategoryTicker.ticker).where(
        UsCategoryTicker.category_slug == slug)).all()
    tw_nodes = session.exec(select(TwLinkageNode).where(
        TwLinkageNode.category_slug == slug,
        TwLinkageNode.exclude_from_scoring == False)).all()  # noqa: E712

    cache, ciks = _load_json(US_REV_CACHE), _cik_map()
    us_yoys = {}
    for t in us_tickers:
        s = us_revenue_yoy_series(t, cache, ciks)
        if not s.empty:
            us_yoys[t] = s
    us_agg = pd.DataFrame(us_yoys).mean(axis=1) if us_yoys else pd.Series(dtype="float64")

    is_semi = cat.cluster in SEMI_CLUSTERS
    factor = (_semi_revenue_factor(session, cache, ciks, exclude=set(us_tickers))
              if is_semi else None)
    US_REV_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    has_factor = is_semi and factor is not None and not factor.empty

    nodes = []
    for n in tw_nodes:
        tw = tw_revenue_yoy_series(n.ticker, freq="Q")
        ll = _leadlag(us_agg, tw) if (not us_agg.empty and not tw.empty) else {}
        raw = ll.get("corr_same")
        # #2 effective B corr: partial-out semi factor for semi categories.
        partial = (_partial_corr_q(tw, us_agg, factor)
                   if (has_factor and not tw.empty and not us_agg.empty) else None)
        eff = partial if has_factor else raw
        nodes.append({
            "ticker": n.ticker, "name": n.name, "role": n.role,
            "tw_yoy_latest": float(tw.iloc[-1]) if not tw.empty else None,
            "tw_yoy_recent": {str(p): round(float(v), 3) for p, v in tw.tail(6).items()},
            "corr_b": eff, "corr_b_raw": raw,
            "method_b": "partial-semi" if has_factor else "raw",
            **ll,
        })
    nodes.sort(key=lambda x: abs(x.get("corr_b") or 0), reverse=True)
    missing = [t for t in us_tickers if t not in us_yoys]
    return {
        "slug": slug, "cluster": cat.cluster,
        "us_coverage": f"{len(us_yoys)}/{len(us_tickers)}",
        "us_tickers_with_data": list(us_yoys),
        "us_tickers_missing": missing,  # #4: usually foreign filers (20-F/IFRS)
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
