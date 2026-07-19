"""API for the TW active-ETF holdings board.

Serves what the active-ETF managers actually bought and sold, computed live from
the EtfHolding snapshots (small table, no need to precompute into the nightly
linkage snapshot). Deltas are in SHARES, never weights — weights drift with price
even when the manager does nothing.

Mounted at /api/etf (see main.py).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import Session, select

import etf_holdings as eh
from database import engine
from models import EtfHolding

router = APIRouter()


def _sessions(s: Session, etf_code: str) -> list[str]:
    """Distinct trade dates for one ETF, newest first."""
    return list(s.exec(
        select(EtfHolding.trade_date)
        .where(EtfHolding.etf_code == etf_code)
        .distinct().order_by(EtfHolding.trade_date.desc())).all())


@router.get("/summary")
def summary():
    """Coverage board: which ETFs we track, how much history each one has."""
    with Session(engine) as s:
        out = []
        for etf in eh.ACTIVE_ETFS:
            ds = _sessions(s, etf["code"])
            if not ds:
                continue
            rows = s.exec(select(EtfHolding).where(
                EtfHolding.etf_code == etf["code"],
                EtfHolding.trade_date == ds[0])).all()
            out.append({
                "code": etf["code"], "name": etf["name"], "issuer": etf["issuer"],
                "latest": ds[0], "earliest": ds[-1], "sessions": len(ds),
                "holdings": len(rows),
                "market_value": sum(r.amount for r in rows),
                "backfillable": etf["adapter"] in eh.BACKFILLABLE,
            })
        out.sort(key=lambda x: x["market_value"], reverse=True)
        return {"ready": bool(out), "etfs": out}


@router.get("/flows")
def flows(days: int = Query(1, ge=1, le=60),
          limit: int = Query(60, ge=1, le=300)):
    """Cross-ETF share flows: each ETF's latest session vs `days` sessions
    earlier, aggregated per stock. Positive = the managers net bought."""
    with Session(engine) as s:
        agg: dict[str, dict] = {}
        covered, skipped = [], []
        for etf in eh.ACTIVE_ETFS:
            ds = _sessions(s, etf["code"])
            if len(ds) < 2:
                # A blank board must not look like a bug: say which ETFs could
                # not be compared and why (issuers without history need two
                # collected days before any diff exists).
                skipped.append({"code": etf["code"], "name": etf["name"],
                                "sessions": len(ds),
                                "reason": f"僅 {len(ds)} 天快照，需累積 2 天才能比對"})
                continue
            new = ds[0]
            old = ds[min(days, len(ds) - 1)]
            covered.append({"code": etf["code"], "name": etf["name"],
                            "new": new, "old": old,
                            "span": min(days, len(ds) - 1)})
            for d in eh.diff(s, etf["code"], new, old):
                a = agg.setdefault(d["stock_code"], {
                    "stock_code": d["stock_code"],
                    "stock_name": d["stock_name"],
                    "delta_shares": 0.0, "etfs": []})
                a["delta_shares"] += d["delta_shares"]
                a["etfs"].append({"etf": etf["code"], "name": etf["name"],
                                  "delta": d["delta_shares"],
                                  "action": d["action"]})
        rows = sorted(agg.values(), key=lambda x: abs(x["delta_shares"]),
                      reverse=True)[:limit]
        for r in rows:
            r["etf_count"] = len(r["etfs"])
        return {"ready": bool(covered), "days": days,
                "covered": covered, "skipped": skipped, "flows": rows}


@router.get("/holdings/{etf_code}")
def holdings(etf_code: str):
    """One ETF's latest holdings, with the share delta vs its prior session."""
    with Session(engine) as s:
        ds = _sessions(s, etf_code)
        if not ds:
            raise HTTPException(404, f"no holdings collected for {etf_code}")
        rows = s.exec(select(EtfHolding).where(
            EtfHolding.etf_code == etf_code,
            EtfHolding.trade_date == ds[0])).all()
        delta = {}
        if len(ds) > 1:
            delta = {d["stock_code"]: d for d in eh.diff(s, etf_code, ds[0], ds[1])}
        out = [{
            "stock_code": r.stock_code, "stock_name": r.stock_name,
            "shares": r.shares, "weight": r.weight, "amount": r.amount,
            "delta_shares": delta.get(r.stock_code, {}).get("delta_shares", 0.0),
            "action": delta.get(r.stock_code, {}).get("action"),
        } for r in rows]
        out.sort(key=lambda x: x["weight"], reverse=True)
        # positions sold to zero no longer appear above — surface them too
        gone = [d for c, d in delta.items() if d["action"] == "清空"]
        name = next((e["name"] for e in eh.ACTIVE_ETFS if e["code"] == etf_code), etf_code)
        return {"etf_code": etf_code, "etf_name": name, "trade_date": ds[0],
                "prev_date": ds[1] if len(ds) > 1 else None,
                "holdings": out, "exited": gone}


@router.get("/stock/{stock_code}")
def stock(stock_code: str):
    """Reverse view: which active ETFs hold this stock, and their latest move."""
    with Session(engine) as s:
        held = []
        for etf in eh.ACTIVE_ETFS:
            ds = _sessions(s, etf["code"])
            if not ds:
                continue
            r = s.exec(select(EtfHolding).where(
                EtfHolding.etf_code == etf["code"],
                EtfHolding.trade_date == ds[0],
                EtfHolding.stock_code == stock_code)).first()
            d = None
            if len(ds) > 1:
                d = next((x for x in eh.diff(s, etf["code"], ds[0], ds[1])
                          if x["stock_code"] == stock_code), None)
            if r or d:
                held.append({
                    "etf": etf["code"], "etf_name": etf["name"],
                    "trade_date": ds[0],
                    "shares": r.shares if r else 0.0,
                    "weight": r.weight if r else 0.0,
                    "delta_shares": d["delta_shares"] if d else 0.0,
                    "action": d["action"] if d else None,
                })
        if not held:
            raise HTTPException(404, f"no active ETF holds {stock_code}")
        held.sort(key=lambda x: x["weight"], reverse=True)
        nm = next((h for h in held if h["shares"]), None)
        return {"stock_code": stock_code, "held_by": held,
                "etf_count": sum(1 for h in held if h["shares"] > 0),
                "total_shares": sum(h["shares"] for h in held),
                "total_delta": sum(h["delta_shares"] for h in held)}
