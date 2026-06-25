"""
US-TW linkage API (Step 4). Exposes the A-layer price read-through, B-layer
revenue linkage, and the combined two-layer verdict over the ingested taxonomy.

Endpoints (mounted under /api/linkage):
  GET /categories          list categories for navigation
  GET /category/{slug}     two-layer view (A price + B revenue + verdict)
  GET /movers              categories ranked by |z| of US basket move (A-layer)
  GET /stock/{tw_id}       reverse: which US themes drive a TW stock (A-layer)

The two-layer / movers computations hit yfinance + SEC EDGAR + FinLab and are
slow on a cold cache, so results are TTL-cached. For production, a scheduled job
should pre-warm these (see PLAN step 6).
"""
import json
import math
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from database import get_session
from models import UsCategory
import linkage_engine as le
import linkage_synthesis as ls

router = APIRouter()

_CACHE: dict[str, tuple] = {}
HEAVY_TTL = 1800  # 30 min — revenue/price data changes slowly

# Nightly snapshot (refresh_linkage.py). Served instantly when fresh; falls back
# to live compute if absent or stale (so a missed job degrades, not breaks).
SNAPSHOT = Path(__file__).resolve().parent.parent / "linkage-service" / "seed" / "linkage_snapshot.json"
SNAPSHOT_MAX_AGE = 36 * 3600  # 36h
_snap = {"data": None, "mtime": 0.0}


def _clean_nan(o):
    """Recursively replace NaN/Inf floats with None. JSON has no NaN, so FastAPI's
    serializer raises (500) on any NaN that slips through (e.g. a node's b_corr_raw
    when revenue history is too sparse to correlate). Sanitize before returning."""
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {k: _clean_nan(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean_nan(v) for v in o]
    return o


def _snapshot():
    if not SNAPSHOT.exists():
        return None
    mtime = SNAPSHOT.stat().st_mtime
    if time.time() - mtime > SNAPSHOT_MAX_AGE:
        return None
    if _snap["mtime"] != mtime:
        try:
            _snap["data"] = _clean_nan(json.loads(SNAPSHOT.read_text(encoding="utf-8")))
            _snap["mtime"] = mtime
        except Exception:
            _snap["data"] = None
    return _snap["data"]


def _cached(key: str, ttl: int, fn):
    hit = _CACHE.get(key)
    if hit and time.time() - hit[1] < ttl:
        return hit[0]
    val = fn()
    _CACHE[key] = (val, time.time())
    return val


@router.get("/categories")
def list_categories(session: Session = Depends(get_session)):
    cats = session.exec(select(UsCategory)).all()
    return [
        {"slug": c.slug, "name_zh": c.name_zh, "name_en": c.name_en,
         "cluster": c.cluster, "linkage": c.linkage}
        for c in cats
    ]


@router.get("/category/{slug}")
def category_two_layer(slug: str, refresh: bool = Query(False),
                       session: Session = Depends(get_session)):
    if session.get(UsCategory, slug) is None:
        raise HTTPException(status_code=404, detail=f"unknown category: {slug}")
    if not refresh:
        snap = _snapshot()
        if snap and slug in snap.get("categories", {}):
            return snap["categories"][slug]
    key = f"two:{slug}"
    if refresh:
        _CACHE.pop(key, None)
    return _clean_nan(_cached(key, HEAVY_TTL, lambda: ls.category_two_layer(session, slug)))


@router.get("/movers")
def movers(clusters: str = Query(None, description="comma-separated cluster filter"),
           refresh: bool = Query(False), session: Session = Depends(get_session)):
    cl = [c.strip() for c in clusters.split(",")] if clusters else None
    if not refresh:
        snap = _snapshot()
        if snap:
            mv = snap.get("movers", [])
            return [m for m in mv if not cl or m["cluster"] in cl]
    key = f"movers:{clusters or 'all'}"
    if refresh:
        _CACHE.pop(key, None)
    return _cached(key, HEAVY_TTL, lambda: le.compute_movers(session, clusters=cl))


@router.get("/alerts")
def alerts(threshold: float = Query(None, description="min excess over benchmark"),
           min_breadth: int = Query(2, description="min US trigger count (basket breadth)"),
           session: Session = Depends(get_session)):
    """Categories whose US basket OUT-moved its benchmark (semi->SOX, tech->QQQ,
    else S&P) by >= threshold — relative-strength breakouts, not just market beta.
    Served from the snapshot; each alert lists the TW nodes worth watching."""
    th = le.ALERT_EXCESS_THRESHOLD if threshold is None else threshold
    snap = _snapshot()
    if not snap:
        return {"ready": False, "detail": "snapshot not built yet; try again shortly"}
    out = []
    for c in snap.get("categories", {}).values():
        exc = c.get("excess")
        if exc is None or exc < th:
            continue
        # Breadth gate: a 1-stock "basket" move IS that stock's move -> any volatile
        # single name clears the threshold on its own and isn't a group rotation.
        # Require >= MIN_ALERT_BREADTH triggers for a real relative-strength alert.
        us_count = len(c.get("us_members", []))
        if us_count < min_breadth:
            continue
        watch = [{"ticker": n["ticker"], "name": n["name"], "verdict": n["verdict"],
                  "b_corr": n.get("b_corr"), "readthrough": n.get("readthrough")}
                 for n in c.get("nodes", []) if n["verdict"] in
                 ("tradeable+fundamental", "fundamental-only")][:5]
        out.append({"slug": c["slug"], "name_zh": c["name_zh"], "cluster": c["cluster"],
                    "a_move": c["a_move"], "benchmark": c.get("benchmark"),
                    "benchmark_move": c.get("benchmark_move"), "excess": exc,
                    "us_count": us_count, "watch": watch})
    out.sort(key=lambda x: x["excess"], reverse=True)
    return {"ready": True, "threshold": th, "min_breadth": min_breadth,
            "generated_at": snap.get("generated_at"), "alerts": out}


@router.get("/overview")
def overview():
    """Cross-category leaderboard: ALL categories (not just alerts), each with its
    benchmark tier, group move, relative-strength excess and the single strongest
    read-through TW node. Sorted by excess desc (no-trigger watchlists last)."""
    snap = _snapshot()
    if not snap:
        return {"ready": False, "detail": "snapshot not built yet; try again shortly"}
    out = []
    for c in snap.get("categories", {}).values():
        nodes = c.get("nodes", [])
        tw = [{"ticker": n["ticker"], "name": n["name"], "role": n.get("role"),
               "a_corr": n.get("a_corr"), "readthrough": n.get("readthrough"),
               "verdict": n.get("verdict")} for n in nodes]  # pre-sorted by |readthrough|
        out.append({
            "slug": c["slug"], "name_zh": c["name_zh"], "cluster": c["cluster"],
            "benchmark": c.get("benchmark"), "a_move": c.get("a_move"),
            "a_z": c.get("a_z"), "excess": c.get("excess"),
            "has_trigger": c.get("excess") is not None,
            "us_count": len(c.get("us_members", [])),
            "tw_count": len(nodes), "tw_nodes": tw,
        })
    # excess desc; None (no-trigger watchlists) sink to the bottom
    out.sort(key=lambda x: (x["excess"] is not None, x["excess"] or 0), reverse=True)
    return {"ready": True, "generated_at": snap.get("generated_at"), "categories": out}


@router.get("/stock/{tw_id}")
def stock_readthrough(tw_id: str, refresh: bool = Query(False),
                      session: Session = Depends(get_session)):
    key = f"stock:{tw_id}"
    if refresh:
        _CACHE.pop(key, None)
    result = _cached(key, HEAVY_TTL, lambda: le.stock_readthrough(session, tw_id))
    if not result.get("drivers"):
        raise HTTPException(status_code=404, detail=f"no linkage for TW stock: {tw_id}")
    return result
