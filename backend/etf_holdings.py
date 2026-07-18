"""TW active-ETF daily holdings collector (phase 1: 統一投信).

Taiwan's active ETFs disclose their FULL holdings every day, but the issuer sites
only ever show the CURRENT day — there is no history endpoint anywhere (checked:
TWSE OpenAPI, SITCA, FinLab, and the PCF 申購買回清單, which for cash-creation
ETFs carries no stock basket at all). So we snapshot daily into EtfHolding; the
day-over-day share delta is what reveals what the managers actually bought and
sold. Every day not collected is a diff that cannot be recovered later.

Source shape (統一投信 / ezmoney): the fund page embeds its portfolio as
HTML-escaped JSON. The object with AssetName == "股票" holds Details[] with
DetailCode / DetailName / Share / NavRate / Amount / TranDate. A bare GET gets
302-looped, so we reuse one client and let it pick up the session cookie.

Run daily after the TW close:  python backend/etf_holdings.py
"""
from __future__ import annotations

import html as _html
import json
import sys
from pathlib import Path
from typing import Optional

import httpx
from sqlmodel import Session, delete, select

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

BASE = "https://www.ezmoney.com.tw"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# (etf_code, name, issuer-internal fundCode). Phase 1 = 統一投信 actives.
ACTIVE_ETFS: list[tuple[str, str, str]] = [
    ("00981A", "主動統一台股增長", "49YTW"),
    ("00403A", "主動統一升級50", "63YTW"),
    ("00988A", "主動統一全球創新", "61YTW"),
]


def _extract_stock_block(page: str) -> Optional[dict]:
    """Pull the AssetName=="股票" object out of the page's embedded JSON."""
    u = _html.unescape(page)
    i = u.find('"AssetName":"股票"')
    if i < 0:
        return None
    start = u.rfind("{", 0, i)
    if start < 0:
        return None
    depth = 0
    for k in range(start, len(u)):
        if u[k] == "{":
            depth += 1
        elif u[k] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(u[start:k + 1])
                except json.JSONDecodeError:
                    return None
    return None


def fetch_holdings(fund_code: str) -> tuple[Optional[str], list[dict]]:
    """Return (trade_date, holdings[]) for one fund. Empty list if unavailable."""
    with httpx.Client(follow_redirects=True, timeout=30.0,
                      headers={"User-Agent": UA}) as c:
        r = c.get(f"{BASE}/ETF/Fund/Info", params={"fundCode": fund_code})
        r.raise_for_status()
        block = _extract_stock_block(r.text)
    if not block:
        return None, []
    out: list[dict] = []
    trade_date = None
    for d in block.get("Details", []):
        code = str(d.get("DetailCode") or "").strip()
        if not code:
            continue
        if trade_date is None:
            trade_date = str(d.get("TranDate") or "")[:10]
        out.append({
            "stock_code": code,
            "stock_name": str(d.get("DetailName") or "").strip(),
            "shares": float(d.get("Share") or 0),
            "weight": float(d.get("NavRate") or 0),
            "amount": float(d.get("Amount") or 0),
        })
    return trade_date, out


def store(session: Session, etf_code: str, etf_name: str,
          trade_date: str, holdings: list[dict]) -> int:
    """Idempotent: re-running for the same day replaces that day's rows."""
    from models import EtfHolding
    session.exec(delete(EtfHolding).where(
        EtfHolding.trade_date == trade_date, EtfHolding.etf_code == etf_code))
    for h in holdings:
        session.add(EtfHolding(trade_date=trade_date, etf_code=etf_code,
                               etf_name=etf_name, **h))
    session.commit()
    return len(holdings)


def previous_date(session: Session, etf_code: str, before: str) -> Optional[str]:
    from models import EtfHolding
    return session.exec(
        select(EtfHolding.trade_date)
        .where(EtfHolding.etf_code == etf_code, EtfHolding.trade_date < before)
        .distinct().order_by(EtfHolding.trade_date.desc())).first()


def diff(session: Session, etf_code: str, new_date: str, old_date: str) -> list[dict]:
    """Share deltas between two snapshots — what the manager bought/sold."""
    from models import EtfHolding

    def snap(d: str) -> dict:
        rows = session.exec(select(EtfHolding).where(
            EtfHolding.etf_code == etf_code, EtfHolding.trade_date == d)).all()
        return {r.stock_code: r for r in rows}

    new, old = snap(new_date), snap(old_date)
    out = []
    for code in set(new) | set(old):
        n, o = new.get(code), old.get(code)
        delta = (n.shares if n else 0.0) - (o.shares if o else 0.0)
        if delta == 0:
            continue
        out.append({
            "stock_code": code,
            "stock_name": (n or o).stock_name,
            "delta_shares": delta,
            "new_shares": n.shares if n else 0.0,
            "new_weight": n.weight if n else 0.0,
            "action": "新進" if not o else ("清空" if not n else
                                          ("買進" if delta > 0 else "賣出")),
        })
    out.sort(key=lambda x: abs(x["delta_shares"]), reverse=True)
    return out


def main() -> int:
    from database import engine, create_db_and_tables
    create_db_and_tables()
    print(f"[etf-holdings] collecting {len(ACTIVE_ETFS)} active ETFs...")
    with Session(engine) as s:
        for etf_code, name, fund_code in ACTIVE_ETFS:
            try:
                date, hold = fetch_holdings(fund_code)
            except Exception as e:  # noqa: BLE001
                print(f"  {etf_code} {name}: FAILED {type(e).__name__} {e}")
                continue
            if not date or not hold:
                print(f"  {etf_code} {name}: no holdings found (site changed?)")
                continue
            prev = previous_date(s, etf_code, date)
            n = store(s, etf_code, name, date, hold)
            line = f"  {etf_code} {name}: {date} — {n} holdings"
            if prev:
                d = diff(s, etf_code, date, prev)
                line += f" | vs {prev}: {len(d)} changed"
                for x in d[:5]:
                    line += (f"\n      {x['action']} {x['stock_code']} "
                             f"{x['stock_name']} {x['delta_shares']:+,.0f}股")
            else:
                line += " | first snapshot (no diff yet)"
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
