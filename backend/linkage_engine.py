"""
US–TW Linkage engine (Step 3).

Given the ingested taxonomy (UsCategory / UsCategoryTicker / TwLinkageNode),
turn a *US category move* into a weighted *read-through* onto Taiwan nodes.

Pipeline per category:
  1. Basket return  = equal-weight mean of member US tickers' daily returns.
  2. Category move  = cumulative basket return over the last `window` days,
                      plus a z-score vs the basket's own daily vol (for ranking
                      "sharp" moves robustly across different-volatility themes).
  3. Read-through   = move * empirical_corr * linkage_prior * purity_weight
                      for each TW node, where
        empirical_corr  = corr(basket daily ret, node daily ret) over the window
        linkage_prior   = strong 1.0 / medium 0.6 / weak 0.3   (seed `linkage`)
        purity_weight   = 1.0 unless the node is a low-purity proxy (see overrides)
     `dual` nodes (ADR<->TW same company) are EXCLUDED — self-correlation, not a
     linkage signal (TwLinkageNode.exclude_from_scoring).

Design choices vs the legacy correlation_analysis.py:
  * Correlate on RETURNS, not price levels (price-level corr is spurious on trends).
  * LAG the US basket by 1 trading day when correlating with TW nodes: TW trades
    ahead of the US session, so TW day-t reacts to the US day-(t-1) close.
    Contemporaneous (same-day) corr structurally understates the linkage.
    Consequently today's US move implies TW's *next* session read-through.
  * Resolve bare TW ids to .TW/.TWO ourselves (get_stock_ticker() mislabels
    numeric TW ids as US).

Everything reads from the DB, so it always reflects the latest ingested seed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from sqlmodel import Session, select

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from database import engine  # noqa: E402
from models import TwLinkageNode, UsCategory, UsCategoryTicker  # noqa: E402

# --------------------------------------------------------------------------- #
# Tunables
# --------------------------------------------------------------------------- #
LINKAGE_PRIOR = {"strong": 1.0, "medium": 0.6, "weak": 0.3}

# Low-purity TW proxies: business mix dilutes the linkage signal, so down-weight
# (user principle: 對標要用 pure-play 同業). Extend as needed.
PURITY_OVERRIDES = {
    "1101": 0.4,   # 台泥 TCC — cement co. proxied for Molicel battery cells
    "1303": 0.6,   # 南亞 Nan Ya — diversified plastics, partial battery-material
    "1722": 0.7,   # 台肥 TFC — fertilizer co., LFP cathode is a small segment
}

# Categories with fewer than this many TW nodes are flagged low-signal and
# get a category-level penalty (e.g. medical-devices / aerospace-defense: 1 node).
MIN_NODES_FOR_SIGNAL = 2
LOW_SIGNAL_PENALTY = 0.5

# Semiconductor sector factor. For semi clusters, a TW node's raw corr with the
# US category basket is mostly Phlx-Semi (SOX) sector beta — the US baskets are
# themselves 0.77-0.91 correlated with SOX. We therefore weight semi categories
# by the SOX-ADJUSTED PARTIAL correlation, isolating the category-specific
# linkage from broad-semi co-movement. (Validated: memory makers survive,
# WFE->foundry collapses to ~0, TSMC collapses everywhere — it IS the sector.)
SOX_SYMBOL = "^SOX"
# StatementDog-rebuilt taxonomy: the clusters whose constituents ARE semiconductor
# names (chip design / wafer / memory / back-end / semi materials) carry heavy SOX
# beta, so we strip it via partial corr + benchmark alerts against SOX. PCB, passive
# components, liquid cooling and LEO/satellite track AI-capex / industrial / broad
# market rather than the chip cycle -> they keep the S&P 500 benchmark (raw corr).
SEMI_CLUSTERS = {
    "Silicon Photonics / CPO",
    "Glass Substrate",
    "Advanced Packaging",
    "Specialty Chemicals",
    "Silicon Wafer",
    "GaN",
    "IC Design",
    "MCU",
    "Memory",
    "Power Management IC",
    "CoPoS",
    "SiC",
}

# Relative-strength benchmark for alerts: a category only "alerts" when its basket
# out-moves its benchmark. Three tiers: semiconductor -> SOX; tech-but-not-semi
# (PCB / passives / cooling / satellite — they ride the Nasdaq-100 tech tape) ->
# QQQ; everything genuinely non-tech (future footwear / aerospace / auto-parts /
# hand-tool themes) -> S&P 500. A group rising 6% while its tape rises 6% has ~0
# excess and should NOT alert.
SPX_SYMBOL = "^GSPC"
QQQ_SYMBOL = "QQQ"
# Tech hardware that is NOT a chip play -> benchmark against Nasdaq-100, not SPX.
TECH_CLUSTERS = {
    "CCL / PCB",
    "Passive Components",
    "Liquid Cooling",
    "LEO Satellite",
    "Optical Lens",
}


def _benchmark_for(cluster: str) -> str:
    if cluster in SEMI_CLUSTERS:
        return SOX_SYMBOL
    if cluster in TECH_CLUSTERS:
        return QQQ_SYMBOL
    return SPX_SYMBOL


ALERT_EXCESS_THRESHOLD = 0.03  # |basket move - benchmark move| over the window

# On-disk cache of resolved TW yahoo symbols (avoids re-probing .TW/.TWO).
TW_SYMBOL_CACHE = BACKEND_DIR.parent / "linkage-service" / "seed" / "tw_symbol_map.json"


# --------------------------------------------------------------------------- #
# Ticker resolution + price fetch
# --------------------------------------------------------------------------- #
def _load_tw_cache() -> dict:
    if TW_SYMBOL_CACHE.exists():
        try:
            return json.loads(TW_SYMBOL_CACHE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_tw_cache(cache: dict) -> None:
    TW_SYMBOL_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_tw_symbol(tw_id: str, cache: dict) -> str | None:
    """Map a bare TW id (e.g. '2330') to a working yahoo symbol ('2330.TW' or
    '2330.TWO'), probing once and caching the result."""
    if tw_id in cache:
        return cache[tw_id]
    for suffix in (".TW", ".TWO"):
        try:
            if not yf.Ticker(tw_id + suffix).history(period="5d").empty:
                cache[tw_id] = tw_id + suffix
                return cache[tw_id]
        except Exception:
            pass
    cache[tw_id] = None
    return None


def _market(sym: str) -> str:
    """Market key from the yfinance suffix (after the last dot); bare = US."""
    return sym.rsplit(".", 1)[1] if "." in sym else "US"


def _truncate_phantom(close_df: pd.DataFrame) -> None:
    """Null out PHANTOM trailing bars in place. A mixed-market union index can carry
    the NEXT session for some market while it's only pre-market there — yfinance may
    return a thin/junk bar for a few names on that date. For each market group with
    enough symbols to vote, keep data only up to the latest date where a MAJORITY
    have a real bar; later (pre-market/phantom) bars are nulled so move/repair never
    read them. Needs a populated group (>=3) to judge consensus; smaller groups are
    left as-is (the snapshot fetches the whole universe at once so US has ~40)."""
    if close_df.empty:
        return
    groups: dict[str, list[str]] = {}
    for sym in close_df.columns:
        groups.setdefault(_market(sym), []).append(sym)
    for syms in groups.values():
        if len(syms) < 3:
            continue
        counts = close_df[syms].notna().sum(axis=1)
        thresh = max(2, int(len(syms) * 0.5))
        consensus = counts[counts >= thresh]
        if consensus.empty:
            continue
        last_good = consensus.index.max()
        late = close_df.index > last_good
        if late.any():
            close_df.loc[late, syms] = np.nan


def _repair_latest(close_df: pd.DataFrame) -> list[str]:
    """yfinance's daily history feed sometimes omits the most recent session for
    a SINGLE ticker (NaN bar) while its realtime quote already has that close
    (observed: MOD 2026-06-18 NaN in history, but fast_info=297.37). Silently
    dropping the NaN would use a stale T-1 close and miss the latest move — the
    exact signal this engine exists to catch. Fill such gaps from the realtime
    quote and return the list of patched symbols so the caller can surface it.

    Caveat: if run during an OPEN session this injects the intraday last price as
    the day's "close"; intended for end-of-day runs. Does not handle the case
    where the entire latest session is absent from the index (needs a market
    calendar — production should use a reliable EOD source; see PLAN step 6)."""
    if close_df.empty:
        return []
    patched = []
    # Group by MARKET (suffix after the last dot; bare symbol = US). A mixed-market
    # fetch builds a UNION index of every market's trading days, so e.g. a US stock
    # gets a phantom NaN bar on an Asia-only session date. Repairing against the
    # global index.max() would then inject a realtime quote on that phantom day and
    # corrupt the move. Repair each symbol only against ITS OWN market's latest
    # session (the lone-missing-US-ticker case this exists for is intra-market).
    groups: dict[str, list[str]] = {}
    for sym in close_df.columns:
        groups.setdefault(_market(sym), []).append(sym)
    for syms in groups.values():
        sub = close_df[syms].dropna(how="all")
        if sub.empty:
            continue
        target = sub.index.max()  # latest real session for THIS market
        for sym in syms:
            valid = close_df[sym].dropna()
            if valid.empty or valid.index.max() >= target:
                continue  # up to date for its market -> nothing to repair
            try:
                lp = yf.Ticker(sym).fast_info.last_price
            except Exception:
                lp = None
            if lp and float(lp) != float(valid.iloc[-1]):
                close_df.loc[target, sym] = float(lp)
                patched.append(sym)
    return patched


def fetch_returns(symbols: list[str], period: str = "1y") -> pd.DataFrame:
    """Daily simple returns for each symbol, columns = symbols, NaNs kept
    (pairwise dropna happens at correlation time)."""
    symbols = sorted(set(s for s in symbols if s))
    if not symbols:
        return pd.DataFrame()
    # Download in CHUNKS: a single yf.download of the whole (~300-symbol) universe
    # silently drops bars for individual tickers (observed: WOLF lost its 2026-06-22
    # bar in a 300-symbol call but not a 40-symbol one), which then corrupts the
    # multi-day cumulative move. Smaller batches return complete series.
    CHUNK = 40
    closes = {}
    for i in range(0, len(symbols), CHUNK):
        chunk = symbols[i:i + CHUNK]
        raw = yf.download(chunk, period=period, interval="1d",
                          auto_adjust=True, progress=False, group_by="ticker")
        if raw is None or raw.empty:
            continue
        multi = isinstance(raw.columns, pd.MultiIndex)
        for s in chunk:
            try:
                col = raw[s]["Close"] if multi else raw["Close"]
                if col.dropna().empty:
                    continue
                closes[s] = col
            except Exception:
                continue
    if not closes:
        return pd.DataFrame()
    close_df = pd.DataFrame(closes)
    close_df.index = pd.to_datetime(close_df.index).tz_localize(None)
    close_df = close_df.sort_index()
    _truncate_phantom(close_df)  # drop pre-market/phantom trailing bars first
    patched = _repair_latest(close_df)
    if patched:
        print(f"[fetch_returns] WARNING: stale latest bar repaired from realtime "
              f"quote for: {', '.join(patched)}", file=sys.stderr)
    return close_df.pct_change(fill_method=None).dropna(how="all")


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def _basket_return(returns: pd.DataFrame, us_syms: list[str]) -> pd.Series:
    cols = [c for c in us_syms if c in returns.columns]
    if not cols:
        return pd.Series(dtype="float64")
    return returns[cols].mean(axis=1)


def _move_and_z(basket: pd.Series, window: int) -> tuple[float, float]:
    """Cumulative return over the last `window` VALID days + z-score vs daily vol.
    dropna first: a mixed-market union index leaves phantom trailing NaN bars (an
    Asia-only session a US name didn't trade), and tail() on those would read a
    missing/repaired bar instead of the symbol's real last session."""
    s = basket.dropna()
    if s.empty:
        return 0.0, 0.0
    recent = s.tail(window)
    move = float((1 + recent).prod() - 1)
    vol = float(s.std())
    z = move / (vol * (window ** 0.5)) if vol > 0 else 0.0
    return move, z


def _corr(a: pd.Series, b: pd.Series) -> float | None:
    pair = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    if len(pair) <= 5:
        return None
    c = pair["a"].corr(pair["b"])
    return None if pd.isna(c) else float(c)


def _partial_corr(node: pd.Series, basket_lag: pd.Series, sox_lag: pd.Series) -> float | None:
    """Partial corr(node, basket | SOX): the category-specific linkage left after
    removing the common Phlx-Semi factor.
        r(t,b|s) = (r_tb - r_ts*r_bs) / sqrt((1-r_ts^2)(1-r_bs^2))
    """
    df = pd.concat([node.rename("t"), basket_lag.rename("b"), sox_lag.rename("s")],
                   axis=1).dropna()
    if len(df) <= 8:
        return None
    r_tb, r_ts, r_bs = df["t"].corr(df["b"]), df["t"].corr(df["s"]), df["b"].corr(df["s"])
    if any(pd.isna(x) for x in (r_tb, r_ts, r_bs)):
        return None
    denom = ((1 - r_ts ** 2) * (1 - r_bs ** 2)) ** 0.5
    if denom < 1e-6:
        return None
    return float((r_tb - r_ts * r_bs) / denom)


def score_category(session: Session, slug: str, returns: pd.DataFrame,
                   tw_cache: dict, window: int = 1, lag: int = 1) -> dict | None:
    cat = session.get(UsCategory, slug)
    if cat is None:
        return None
    us_syms = [t.ticker for t in cat.us_tickers]
    has_trigger = bool(us_syms)
    basket = _basket_return(returns, us_syms)
    is_semi = cat.cluster in SEMI_CLUSTERS

    # Asian leaders (.T Tokyo / .KS Korea / .HK HK / .SS Shanghai / .SZ Shenzhen)
    # trade the SAME session as TW -> no lag; US/EU lead TW by one session -> lag 1.
    # Mixed basket: majority rules.
    _ASIAN_SUFFIX = (".T", ".KS", ".KQ", ".HK", ".SS", ".SZ")
    eff_lag = 0 if (us_syms and sum(s.endswith(_ASIAN_SUFFIX) for s in us_syms) * 2 >= len(us_syms)) else lag

    if has_trigger:
        move, z = _move_and_z(basket, window)
        # Relative strength vs benchmark (semi->SOX, tech->QQQ, else S&P 500).
        bench_sym = _benchmark_for(cat.cluster)
        bench_move = (_move_and_z(returns[bench_sym], window)[0]
                      if bench_sym in returns.columns else 0.0)
        excess = move - bench_move
    else:
        # No US/JP trigger (e.g. TW-only material/equipment groups): a watchlist,
        # not a read-through — no basket move, no alert.
        move = z = excess = None
        bench_sym = bench_move = None

    # Per-US-member moves over the window (so the UI can show the US side too).
    us_members = []
    for s in us_syms:
        present = s in returns.columns
        m = _move_and_z(returns[s], window)[0] if present else None
        m1 = _move_and_z(returns[s], 1)[0] if present else None  # last completed session
        us_members.append({"ticker": s, "move": m, "move_1d": m1})

    prior = LINKAGE_PRIOR.get(cat.linkage, 0.5)
    scored_nodes = [n for n in cat.tw_nodes if not n.exclude_from_scoring]
    low_signal = len(scored_nodes) < MIN_NODES_FOR_SIGNAL
    cat_penalty = LOW_SIGNAL_PENALTY if low_signal else 1.0

    # Correlate TW[t] with US basket[t-eff_lag] (0 for Asian leaders).
    basket_lagged = basket.shift(eff_lag)

    # Semi categories: weight by SOX-adjusted partial corr (strip sector beta).
    sox_lagged = returns[SOX_SYMBOL].shift(eff_lag) if SOX_SYMBOL in returns.columns else None

    nodes = []
    for n in scored_nodes:
        sym = resolve_tw_symbol(n.ticker, tw_cache)
        corr_raw = corr_sox = corr_partial = None
        if sym and sym in returns.columns and not basket.empty:
            node_ret = returns[sym]
            corr_raw = _corr(basket_lagged, node_ret)
            if is_semi and sox_lagged is not None:
                corr_sox = _corr(sox_lagged, node_ret)
                corr_partial = _partial_corr(node_ret, basket_lagged, sox_lagged)

        # Effective weight: partial (semi) else raw. Fall back to raw if SOX
        # is unavailable so a fetch glitch doesn't silently zero a whole sector.
        if is_semi and sox_lagged is not None:
            method, eff = "partial-sox", corr_partial
        else:
            method, eff = ("raw-fallback(no-SOX)" if is_semi else "raw"), corr_raw

        purity = PURITY_OVERRIDES.get(n.ticker, 1.0)
        readthrough = None
        if eff is not None and move is not None:
            # Negative specific linkage -> no read-through (clamp to 0).
            readthrough = move * max(eff, 0.0) * prior * purity * cat_penalty
        nodes.append({
            "ticker": n.ticker, "name": n.name, "role": n.role,
            "corr": eff, "corr_raw": corr_raw, "corr_sox": corr_sox,
            "method": method, "purity": purity, "readthrough": readthrough,
        })

    nodes.sort(key=lambda x: abs(x["readthrough"]) if x["readthrough"] is not None else -1,
               reverse=True)
    return {
        "slug": slug, "name_zh": cat.name_zh, "name_en": cat.name_en,
        "cluster": cat.cluster, "linkage": cat.linkage,
        "move": move, "z": z, "low_signal": low_signal,
        "benchmark": bench_sym, "benchmark_move": bench_move, "excess": excess,
        "us_tickers": us_syms, "us_members": us_members, "nodes": nodes,
    }


def _all_symbols(session: Session, slugs: list[str], tw_cache: dict) -> list[str]:
    us = session.exec(select(UsCategoryTicker.ticker).where(
        UsCategoryTicker.category_slug.in_(slugs))).all()
    tw_ids = session.exec(select(TwLinkageNode.ticker).where(
        TwLinkageNode.category_slug.in_(slugs),
        TwLinkageNode.exclude_from_scoring == False)).all()  # noqa: E712
    tw = [resolve_tw_symbol(t, tw_cache) for t in set(tw_ids)]
    # Always include the three benchmark tapes: SOX (semi partial corr) + QQQ
    # (tech relative strength) + S&P 500 (broad relative strength).
    return list(set(us)) + [s for s in tw if s] + [SOX_SYMBOL, QQQ_SYMBOL, SPX_SYMBOL]


def compute_movers(session: Session, clusters: list[str] | None = None,
                   window: int = 1, period: str = "1y", lag: int = 1) -> list[dict]:
    """Score every category (optionally limited to `clusters`); return ranked by
    |z| (sharpest US moves first), each with its TW read-throughs."""
    q = select(UsCategory)
    if clusters:
        q = q.where(UsCategory.cluster.in_(clusters))
    cats = session.exec(q).all()
    slugs = [c.slug for c in cats]

    tw_cache = _load_tw_cache()
    returns = fetch_returns(_all_symbols(session, slugs, tw_cache), period=period)
    _save_tw_cache(tw_cache)

    out = []
    for slug in slugs:
        r = score_category(session, slug, returns, tw_cache, window=window, lag=lag)
        if r:
            out.append(r)
    out.sort(key=lambda x: abs(x["z"] or 0), reverse=True)
    return out


def stock_readthrough(session: Session, tw_id: str, window: int = 1,
                      period: str = "1y", lag: int = 1) -> dict:
    """Reverse lookup: which US themes currently drive a given TW stock."""
    nodes = session.exec(select(TwLinkageNode).where(
        TwLinkageNode.ticker == tw_id)).all()
    if not nodes:
        return {"tw_id": tw_id, "drivers": []}
    slugs = [n.category_slug for n in nodes]
    tw_cache = _load_tw_cache()
    returns = fetch_returns(_all_symbols(session, slugs, tw_cache), period=period)
    _save_tw_cache(tw_cache)

    drivers = []
    for slug in slugs:
        cat = score_category(session, slug, returns, tw_cache, window=window, lag=lag)
        if not cat:
            continue
        node = next((n for n in cat["nodes"] if n["ticker"] == tw_id), None)
        if node:
            drivers.append({
                "slug": slug, "name_zh": cat["name_zh"], "role": node["role"],
                "us_move": cat["move"], "corr": node["corr"],
                "readthrough": node["readthrough"], "low_signal": cat["low_signal"],
            })
    drivers.sort(key=lambda x: abs(x["readthrough"]) if x["readthrough"] is not None else -1,
                 reverse=True)
    return {"tw_id": tw_id, "drivers": drivers}


# --------------------------------------------------------------------------- #
# CLI demo / smoke test (small subset to stay fast)
# --------------------------------------------------------------------------- #
def _demo() -> int:
    with Session(engine) as s:
        movers = compute_movers(s, clusters=["AI Datacenter"], window=5)
        if not movers:
            print("No categories scored (DB empty? run ingest_linkage.py first).")
            return 1
        print(f"AI Datacenter — {len(movers)} categories, ranked by |z| (5d window)\n")
        for m in movers[:5]:
            print(f"[{m['z']:+.2f}z  move {m['move']:+.1%}] {m['slug']}  {m['name_zh']}"
                  f"{'  (LOW SIGNAL)' if m['low_signal'] else ''}")
            for n in m["nodes"][:3]:
                rt = f"{n['readthrough']:+.3f}" if n["readthrough"] is not None else "  n/a"
                cr = f"{n['corr']:+.2f}" if n["corr"] is not None else " n/a"
                print(f"     -> {n['ticker']:<5} {n['name'][:22]:<22} role={n['role']:<4}"
                      f" corr={cr} readthrough={rt}")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
