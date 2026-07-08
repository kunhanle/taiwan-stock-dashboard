"""
Two-layer synthesis (#5): combine the A-layer price read-through and the
B-layer revenue-YoY linkage into ONE per-node verdict, so the app can tell the
user whether a linkage is tradeable, only-fundamental, or noise.

  tradeable+fundamental : A price signal AND B revenue signal
  fundamental-only      : B revenue signal, no A price signal (sector beta in price)
  tradeable-only        : A price signal but no B revenue co-movement (rare/fragile)
  weak                  : neither
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlmodel import Session

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

import yaml

import linkage_engine as le
import revenue_linkage as rl

# US/foreign ticker -> display name (Chinese preferred, English fallback). Built
# once from the committed map (linkage-service/seed/us_ticker_names.yaml) so the
# UI can show company names next to bare tickers like "4063.T".
_NAMES_PATH = BACKEND_DIR.parent / "linkage-service" / "seed" / "us_ticker_names.yaml"
_names_cache: dict | None = None


def _ticker_name(ticker: str):
    global _names_cache
    if _names_cache is None:
        try:
            _names_cache = yaml.safe_load(_NAMES_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            _names_cache = {}
    return _names_cache.get(ticker)
from database import engine
from models import UsCategory

A_THRESHOLD = 0.15   # min A-layer (price) correlation to call it tradeable
B_THRESHOLD = 0.25   # min B-layer (revenue) correlation to call it fundamental


def _classify(a_corr: float | None, b_corr: float | None,
              b_raw: float | None = None, is_semi: bool = False) -> str:
    a = a_corr is not None and a_corr >= A_THRESHOLD
    b = b_corr is not None and b_corr >= B_THRESHOLD   # category-specific (partial)
    if a and b:
        return "tradeable+fundamental"
    if b:
        return "fundamental-only"
    if a:
        return "tradeable-only"
    # Semi node whose revenue co-moves with the broad semi cycle but NOT
    # category-specifically (raw high, partial washed out) — honest middle case.
    if is_semi and b_raw is not None and b_raw >= B_THRESHOLD:
        return "semi-cycle"
    return "weak"


def category_two_layer(session: Session, slug: str, price_period: str = "3mo",
                       returns=None) -> dict:
    cache = le._load_tw_cache()
    if returns is None:
        syms = le._all_symbols(session, [slug], cache)
        returns = le.fetch_returns(syms, period=price_period)
    a = le.score_category(session, slug, returns, cache, window=5)
    le._save_tw_cache(cache)
    b = rl.category_revenue_linkage(session, slug)

    amap = {n["ticker"]: n for n in a["nodes"]}
    bmap = {n["ticker"]: n for n in b["nodes"]}
    cat = session.get(UsCategory, slug)
    is_semi = cat.cluster in le.SEMI_CLUSTERS

    nodes = []
    for t in dict.fromkeys(list(bmap) + list(amap)):
        an, bn = amap.get(t, {}), bmap.get(t, {})
        a_corr, b_corr, b_raw = an.get("corr"), bn.get("corr_b"), bn.get("corr_b_raw")
        nodes.append({
            "ticker": t,
            "name": bn.get("name") or an.get("name"),
            "role": bn.get("role") or an.get("role"),
            "a_corr": a_corr, "a_method": an.get("method"),
            "readthrough": an.get("readthrough"),
            "b_corr": b_corr, "b_corr_raw": b_raw,
            "b_method": bn.get("method_b"),
            "lead_lag": bn.get("lead_lag"), "lead_lag_confident": bn.get("lead_lag_confident"),
            "n": bn.get("n"),
            "verdict": _classify(a_corr, b_corr, b_raw, is_semi),
        })
    order = {"tradeable+fundamental": 0, "tradeable-only": 1, "fundamental-only": 2,
             "semi-cycle": 3, "weak": 4}
    nodes.sort(key=lambda x: (order[x["verdict"]], -abs(x["b_corr"] or x["b_corr_raw"] or 0)))

    # US basket members: window move (A) + latest revenue YoY (B), so the UI
    # shows the US side too, not just the TW read-through.
    rev_map = b.get("us_members_rev", {})
    us_members = [{"ticker": m["ticker"], "name": _ticker_name(m["ticker"]),
                   "move": m["move"], "move_1d": m.get("move_1d"),
                   "rev_yoy": rev_map.get(m["ticker"])}
                  for m in a.get("us_members", [])]

    return {
        "slug": slug, "cluster": cat.cluster, "name_zh": cat.name_zh,
        "a_move": a["move"], "a_move_1d": a.get("move_1d"), "a_z": a["z"],
        "benchmark": a.get("benchmark"), "benchmark_move": a.get("benchmark_move"),
        "excess": a.get("excess"),
        "us_members": us_members,
        "us_coverage": b["us_coverage"], "us_missing": b["us_tickers_missing"],
        "us_yoy_latest": b["us_yoy_latest"],
        "nodes": nodes,
    }


if __name__ == "__main__":
    slug = sys.argv[1] if len(sys.argv) > 1 else "ai-training-gpu"
    with Session(engine) as s:
        r = category_two_layer(s, slug)
    print(f"# {r['slug']} ({r['name_zh']}) cluster={r['cluster']}")
    print(f"A move {r['a_move']:+.1%} z {r['a_z']:+.2f} | US rev cov {r['us_coverage']}"
          f"{' missing ' + ','.join(r['us_missing']) if r['us_missing'] else ''}"
          f" | US revYoY {r['us_yoy_latest']:+.2f}" if r['us_yoy_latest'] is not None else "")
    for n in r["nodes"]:
        ll = f" lag{n['lead_lag']:+d}" if n.get("lead_lag") else ""
        print(f"  {n['ticker']:5} {n['role']:5} A={n['a_corr']:+.2f}({n['a_method']:>11}) "
              f"B={n['b_corr']:+.2f}({n['b_method']}){ll} n={n['n']}  -> {n['verdict']}")
