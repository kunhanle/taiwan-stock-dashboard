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
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from database import get_session
from models import UsCategory
import linkage_engine as le
import linkage_synthesis as ls

router = APIRouter()

_CACHE: dict[str, tuple] = {}
HEAVY_TTL = 1800  # 30 min — revenue/price data changes slowly


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
    key = f"two:{slug}"
    if refresh:
        _CACHE.pop(key, None)
    return _cached(key, HEAVY_TTL, lambda: ls.category_two_layer(session, slug))


@router.get("/movers")
def movers(clusters: str = Query(None, description="comma-separated cluster filter"),
           refresh: bool = Query(False), session: Session = Depends(get_session)):
    cl = [c.strip() for c in clusters.split(",")] if clusters else None
    key = f"movers:{clusters or 'all'}"
    if refresh:
        _CACHE.pop(key, None)
    return _cached(key, HEAVY_TTL, lambda: le.compute_movers(session, clusters=cl))


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
