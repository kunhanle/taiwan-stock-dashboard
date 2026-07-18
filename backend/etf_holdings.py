"""TW active-ETF daily holdings collector.

Taiwan's active ETFs disclose their FULL holdings every day, but there is no
central history anywhere (checked: TWSE OpenAPI, TWSE ETFortune, SITCA, FinLab,
and the PCF 申購買回清單 — cash-creation ETFs' PCF carries no stock basket at
all; MoneyDJ has daily shares but only the top 10). So we snapshot per issuer
into EtfHolding: the day-over-day SHARE delta is the signal (weights move with
price, shares only move when the manager trades).

Each issuer needs its own adapter:
  pcsit   統一投信 — fund page embeds portfolio as HTML-escaped JSON. Current
          day only; a bare GET is 302-looped so the client must keep cookies.
  fhtrust 復華投信 — dated XLSX endpoint /api/assetsExcel/{id}/{YYYYMMDD}. No
          cookie needed, and past dates work, so this one can be backfilled.

Run daily after the TW close:  python backend/etf_holdings.py
Backfill (issuers that support it): python backend/etf_holdings.py --backfill 30
"""
from __future__ import annotations

import html as _html
import json
import re
import sys
from datetime import date as _date, timedelta
from io import BytesIO
from pathlib import Path
from typing import Optional

import httpx
from sqlmodel import Session, delete, select

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

# Must be imported at module level: create_db_and_tables() only creates tables
# for models already registered in SQLModel.metadata, so a lazy in-function
# import would leave etfholding missing on a fresh DB.
from models import EtfHolding  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
PCSIT_BASE = "https://www.ezmoney.com.tw"
FH_BASE = "https://www.fhtrust.com.tw"

# code, name, issuer, adapter, issuer-internal ref
ACTIVE_ETFS: list[dict] = [
    {"code": "00981A", "name": "主動統一台股增長", "issuer": "統一", "adapter": "pcsit", "ref": "49YTW"},
    {"code": "00403A", "name": "主動統一升級50", "issuer": "統一", "adapter": "pcsit", "ref": "63YTW"},
    {"code": "00988A", "name": "主動統一全球創新", "issuer": "統一", "adapter": "pcsit", "ref": "61YTW"},
    {"code": "00991A", "name": "主動復華未來50", "issuer": "復華", "adapter": "fhtrust", "ref": "ETF23"},
]


# --------------------------------------------------------------------------
# 統一投信 (pcsit)
# --------------------------------------------------------------------------
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


def fetch_pcsit(ref: str, on: Optional[str] = None) -> tuple[Optional[str], list[dict]]:
    """統一投信: current day only (`on` is ignored — the site has no history)."""
    with httpx.Client(follow_redirects=True, timeout=30.0,
                      headers={"User-Agent": UA}) as c:
        r = c.get(f"{PCSIT_BASE}/ETF/Fund/Info", params={"fundCode": ref})
        r.raise_for_status()
        block = _extract_stock_block(r.text)
    if not block:
        return None, []
    out, trade_date = [], None
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


# --------------------------------------------------------------------------
# 復華投信 (fhtrust) — dated XLSX, supports backfill
# --------------------------------------------------------------------------
def _fh_latest_date(client: httpx.Client, ref: str) -> Optional[str]:
    """The fund page embeds its own latest export URL — read the date off it
    instead of guessing around holidays."""
    r = client.get(f"{FH_BASE}/ETF/etf_detail/{ref}")
    r.raise_for_status()
    m = re.search(rf"/api/assetsExcel/{re.escape(ref)}/(\d{{8}})", r.text)
    return m.group(1) if m else None


def _num(x) -> float:
    s = str(x).replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def fetch_fhtrust(ref: str, on: Optional[str] = None) -> tuple[Optional[str], list[dict]]:
    """復華投信: `on` = 'YYYYMMDD' to backfill a past session."""
    import pandas as pd
    with httpx.Client(follow_redirects=True, timeout=60.0,
                      headers={"User-Agent": UA,
                               "Referer": f"{FH_BASE}/ETF/etf_detail/{ref}"}) as c:
        ymd = on or _fh_latest_date(c, ref)
        if not ymd:
            return None, []
        r = c.get(f"{FH_BASE}/api/assetsExcel/{ref}/{ymd}")
        if r.status_code != 200 or len(r.content) < 200:
            return None, []          # non-trading day returns an empty body
        df = pd.read_excel(BytesIO(r.content), header=None)

    # Locate the holdings header row (證券代號 / 證券名稱 / 股數 / 金額 / 權重)
    hdr = None
    for i in range(len(df)):
        if str(df.iloc[i, 0]).strip() == "證券代號":
            hdr = i
            break
    if hdr is None:
        return None, []
    trade_date = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
    out = []
    for i in range(hdr + 1, len(df)):
        code = str(df.iloc[i, 0]).strip()
        if not code or code.lower() == "nan":
            continue
        out.append({
            "stock_code": code,
            "stock_name": str(df.iloc[i, 1]).strip(),
            "shares": _num(df.iloc[i, 2]),
            "weight": _num(df.iloc[i, 4]),
            "amount": _num(df.iloc[i, 3]),
        })
    return trade_date, out


ADAPTERS = {"pcsit": fetch_pcsit, "fhtrust": fetch_fhtrust}
BACKFILLABLE = {"fhtrust"}


# --------------------------------------------------------------------------
# storage + diff
# --------------------------------------------------------------------------
def store(session: Session, etf_code: str, etf_name: str,
          trade_date: str, holdings: list[dict]) -> int:
    """Idempotent: re-running for the same day replaces that day's rows."""
    session.exec(delete(EtfHolding).where(
        EtfHolding.trade_date == trade_date, EtfHolding.etf_code == etf_code))
    for h in holdings:
        session.add(EtfHolding(trade_date=trade_date, etf_code=etf_code,
                               etf_name=etf_name, **h))
    session.commit()
    return len(holdings)


def previous_date(session: Session, etf_code: str, before: str) -> Optional[str]:
    return session.exec(
        select(EtfHolding.trade_date)
        .where(EtfHolding.etf_code == etf_code, EtfHolding.trade_date < before)
        .distinct().order_by(EtfHolding.trade_date.desc())).first()


def diff(session: Session, etf_code: str, new_date: str, old_date: str) -> list[dict]:
    """Share deltas between two snapshots — what the manager bought/sold."""
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


def collect_one(session: Session, etf: dict, on: Optional[str] = None,
                quiet: bool = False) -> bool:
    fn = ADAPTERS[etf["adapter"]]
    try:
        trade_date, hold = fn(etf["ref"], on)
    except Exception as e:  # noqa: BLE001
        print(f"  {etf['code']} {etf['name']}: FAILED {type(e).__name__} {e}")
        return False
    if not trade_date or not hold:
        if not quiet:
            print(f"  {etf['code']} {etf['name']}: no data"
                  + (f" for {on}" if on else " (site changed?)"))
        return False
    prev = previous_date(session, etf["code"], trade_date)
    n = store(session, etf["code"], etf["name"], trade_date, hold)
    line = f"  {etf['code']} {etf['name']} [{etf['issuer']}]: {trade_date} — {n} holdings"
    if prev:
        d = diff(session, etf["code"], trade_date, prev)
        line += f" | vs {prev}: {len(d)} changed"
        for x in d[:5]:
            line += (f"\n      {x['action']} {x['stock_code']} "
                     f"{x['stock_name']} {x['delta_shares']:+,.0f}股")
    else:
        line += " | first snapshot (no diff yet)"
    print(line)
    return True


def main(argv: Optional[list[str]] = None) -> int:
    from database import engine, create_db_and_tables
    argv = argv if argv is not None else sys.argv[1:]
    days = 0
    if "--backfill" in argv:
        i = argv.index("--backfill")
        days = int(argv[i + 1]) if len(argv) > i + 1 else 30

    create_db_and_tables()
    with Session(engine) as s:
        if days:
            targets = [e for e in ACTIVE_ETFS if e["adapter"] in BACKFILLABLE]
            print(f"[etf-holdings] backfilling {days}d for "
                  f"{len(targets)} backfillable ETF(s)...")
            for etf in targets:
                got = 0
                for k in range(days, -1, -1):
                    d = (_date.today() - timedelta(days=k)).strftime("%Y%m%d")
                    if collect_one(s, etf, on=d, quiet=True):
                        got += 1
                print(f"  {etf['code']}: {got} sessions stored")
            return 0

        print(f"[etf-holdings] collecting {len(ACTIVE_ETFS)} active ETFs...")
        for etf in ACTIVE_ETFS:
            collect_one(s, etf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
