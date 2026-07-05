import asyncio
import os
import threading
import time
from datetime import datetime, timedelta

import httpx
import pandas as pd
from fastapi import APIRouter

router = APIRouter()

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
FINMIND_TOKEN = os.getenv("FINMIND_API_TOKEN", "")

_cache: dict = {}
_lock = threading.Lock()
CACHE_TTL = 3600


def _start(years: int) -> str:
    return (datetime.now() - timedelta(days=years * 365 + 90)).strftime("%Y-%m-%d")


class FinMindPremiumError(Exception):
    pass


async def _fetch(dataset: str, stock_id: str, start: str, require_premium: bool = False) -> list:
    key = f"{dataset}|{stock_id}|{start}"
    with _lock:
        if key in _cache:
            ts, rows = _cache[key]
            if time.time() - ts < CACHE_TTL:
                return rows

    params = {"dataset": dataset, "data_id": stock_id, "start_date": start}
    if FINMIND_TOKEN:
        params["token"] = FINMIND_TOKEN

    async with httpx.AsyncClient(timeout=30) as cli:
        r = await cli.get(FINMIND_URL, params=params)

    if r.status_code == 400 and require_premium:
        raise FinMindPremiumError("此資料集需要 FinMind 付費帳號，請在 .env 設定 FINMIND_API_TOKEN")
    r.raise_for_status()

    rows = r.json().get("data", [])
    with _lock:
        _cache[key] = (time.time(), rows)
    return rows


def _pivot(raw: list) -> pd.DataFrame:
    """Handle FinMind's long format (origin_name + value) or wide format."""
    df = pd.DataFrame(raw)
    if df.empty or "origin_name" not in df.columns:
        return df
    # FinMind balance sheet includes both absolute and _per (% of total assets) rows;
    # keep only absolute values.
    if "type" in df.columns:
        df = df[~df["type"].str.endswith("_per", na=False)]
    pivot = df.pivot_table(index="date", columns="origin_name", values="value", aggfunc="last")
    pivot.columns.name = None
    return pivot.reset_index()


def _col(df: pd.DataFrame, *names: str) -> pd.Series:
    """Return first matching column as numeric, or all-NaN series."""
    for n in names:
        if n in df.columns:
            return pd.to_numeric(df[n], errors="coerce")
    return pd.Series([float("nan")] * len(df), index=df.index)


def _monthly_close(price_raw: list) -> pd.DataFrame:
    if not price_raw:
        return pd.DataFrame(columns=["month", "price"])
    df = pd.DataFrame(price_raw)
    df["dt"] = pd.to_datetime(df["date"])
    df["month"] = df["dt"].dt.to_period("M").astype(str)
    return (
        df.sort_values("dt")
        .groupby("month")
        .last()[["close"]]
        .reset_index()
        .rename(columns={"close": "price"})
    )


def _quarterly_close(price_raw: list) -> pd.DataFrame:
    if not price_raw:
        return pd.DataFrame(columns=["quarter", "price"])
    df = pd.DataFrame(price_raw)
    df["dt"] = pd.to_datetime(df["date"])
    df["quarter"] = df["dt"].dt.to_period("Q").astype(str)
    return (
        df.sort_values("dt")
        .groupby("quarter")
        .last()[["close"]]
        .reset_index()
        .rename(columns={"close": "price"})
    )


# ─── 1. Monthly Revenue ──────────────────────────────────────────────────────
@router.get("/{stock_id}/revenue")
async def get_revenue(stock_id: str, years: int = 5):
    start = _start(years)
    rev_raw, price_raw = await asyncio.gather(
        _fetch("TaiwanStockMonthRevenue", stock_id, start),
        _fetch("TaiwanStockPrice", stock_id, start),
    )
    if not rev_raw:
        return {"data": []}

    rev = pd.DataFrame(rev_raw)
    rev["revenue_raw"] = pd.to_numeric(rev["revenue"], errors="coerce")
    # Use actual revenue period from revenue_year + revenue_month fields if available
    if "revenue_year" in rev.columns and "revenue_month" in rev.columns:
        rev["month"] = rev.apply(
            lambda r: f"{int(r['revenue_year'])}-{int(r['revenue_month']):02d}", axis=1
        )
    else:
        rev["dt"] = pd.to_datetime(rev["date"])
        rev["month"] = rev["dt"].dt.to_period("M").astype(str)
    rev = rev.sort_values("month")
    rev["value"] = (rev["revenue_raw"] / 1e8).round(2)  # 元 → 億

    price = _monthly_close(price_raw)
    merged = rev[["month", "value"]].merge(price, on="month", how="left")
    merged["price"] = merged["price"].ffill()

    return {"data": merged.rename(columns={"month": "date"}).to_dict("records")}


# ─── 2. Quarterly EPS ────────────────────────────────────────────────────────
@router.get("/{stock_id}/eps")
async def get_eps(stock_id: str, years: int = 5):
    start = _start(years)
    fin_raw, price_raw = await asyncio.gather(
        _fetch("TaiwanStockFinancialStatements", stock_id, start),
        _fetch("TaiwanStockPrice", stock_id, start),
    )
    if not fin_raw:
        return {"data": []}

    fin = _pivot(fin_raw)
    eps = _col(fin, "基本每股盈餘", "每股盈餘", "eps", "EPS")
    if eps.isna().all():
        return {"data": [], "error": "EPS data not found"}

    fin["dt"] = pd.to_datetime(fin["date"])
    fin["quarter"] = fin["dt"].dt.to_period("Q").astype(str)
    fin["value"] = eps.round(2)

    price = _quarterly_close(price_raw)
    merged = fin[["quarter", "value"]].dropna().merge(price, on="quarter", how="left")
    merged["price"] = merged["price"].ffill()

    return {"data": merged.rename(columns={"quarter": "date"}).to_dict("records")}


# ─── 3. Profit Margins ───────────────────────────────────────────────────────
@router.get("/{stock_id}/margins")
async def get_margins(stock_id: str, years: int = 5):
    start = _start(years)
    fin_raw, price_raw = await asyncio.gather(
        _fetch("TaiwanStockFinancialStatements", stock_id, start),
        _fetch("TaiwanStockPrice", stock_id, start),
    )
    if not fin_raw:
        return {"data": []}

    fin = _pivot(fin_raw)
    fin["dt"] = pd.to_datetime(fin["date"])
    fin["quarter"] = fin["dt"].dt.to_period("Q").astype(str)

    # Prefer pre-calculated ratio fields; fall back to computing from absolutes
    gross_m = _col(fin, "毛利率")
    op_m = _col(fin, "營業利益率")
    pretax_m = _col(fin, "稅前淨利率")
    net_m = _col(fin, "稅後淨利率", "本期淨利率")

    if gross_m.isna().all():
        rev = _col(fin, "營業收入", "revenue", "Revenue")
        gp  = _col(fin, "營業毛利（毛損）", "毛利", "銷售毛利")
        oi  = _col(fin, "營業利益（損失）", "營業利益")
        pt  = _col(fin, "稅前淨利（淨損）", "稅前淨利", "繼續營業單位稅前損益")
        ni  = _col(fin, "本期淨利（淨損）", "本期淨利", "稅後淨利", "本期損益")
        gross_m = (gp / rev * 100).where(rev > 0)
        op_m = (oi / rev * 100).where(rev > 0)
        pretax_m = (pt / rev * 100).where(rev > 0)
        net_m = (ni / rev * 100).where(rev > 0)

    fin["gross_margin"] = gross_m.round(2)
    fin["operating_margin"] = op_m.round(2)
    fin["pre_tax_margin"] = pretax_m.round(2)
    fin["net_margin"] = net_m.round(2)

    price = _quarterly_close(price_raw)
    merged = fin[["quarter", "gross_margin", "operating_margin", "pre_tax_margin", "net_margin"]].merge(
        price, on="quarter", how="left"
    )
    merged["price"] = merged["price"].ffill()
    merged = merged.dropna(subset=["gross_margin"])

    return {"data": merged.rename(columns={"quarter": "date"}).to_dict("records")}


# ─── 4. Revenue Growth (3M / 6M / 12M YoY) ──────────────────────────────────
@router.get("/{stock_id}/revenue-growth")
async def get_revenue_growth(stock_id: str, years: int = 5):
    start = _start(years + 1)  # extra year for rolling baseline
    rev_raw, price_raw = await asyncio.gather(
        _fetch("TaiwanStockMonthRevenue", stock_id, start),
        _fetch("TaiwanStockPrice", stock_id, start),
    )
    if not rev_raw:
        return {"data": []}

    rev = pd.DataFrame(rev_raw)
    rev["revenue"] = pd.to_numeric(rev["revenue"], errors="coerce")
    if "revenue_year" in rev.columns and "revenue_month" in rev.columns:
        rev["month"] = rev.apply(
            lambda r: f"{int(r['revenue_year'])}-{int(r['revenue_month']):02d}", axis=1
        )
    else:
        rev["dt"] = pd.to_datetime(rev["date"])
        rev["month"] = rev["dt"].dt.to_period("M").astype(str)
    rev = rev.sort_values("month").reset_index(drop=True)

    rev["r3"] = rev["revenue"].rolling(3).sum()
    rev["r6"] = rev["revenue"].rolling(6).sum()
    rev["r12"] = rev["revenue"].rolling(12).sum()
    rev["rev3_yoy"] = ((rev["r3"] / rev["r3"].shift(12)) - 1) * 100
    rev["rev6_yoy"] = ((rev["r6"] / rev["r6"].shift(12)) - 1) * 100
    rev["rev12_yoy"] = ((rev["r12"] / rev["r12"].shift(12)) - 1) * 100

    price = _monthly_close(price_raw)
    merged = rev[["month", "rev3_yoy", "rev6_yoy", "rev12_yoy"]].merge(price, on="month", how="left")
    merged["price"] = merged["price"].ffill()
    merged = merged.dropna(subset=["rev3_yoy", "rev6_yoy", "rev12_yoy"])

    cutoff = (datetime.now() - timedelta(days=years * 365)).strftime("%Y-%m")
    merged = merged[merged["month"] >= cutoff]
    for c in ["rev3_yoy", "rev6_yoy", "rev12_yoy"]:
        merged[c] = merged[c].round(2)

    return {"data": merged.rename(columns={"month": "date"}).to_dict("records")}


# ─── 5. Turnover Days ────────────────────────────────────────────────────────
@router.get("/{stock_id}/turnover-days")
async def get_turnover_days(stock_id: str, years: int = 5):
    start = _start(years)
    fin_raw, bs_raw = await asyncio.gather(
        _fetch("TaiwanStockFinancialStatements", stock_id, start),
        _fetch("TaiwanStockBalanceSheet", stock_id, start),
    )
    if not fin_raw or not bs_raw:
        return {"data": []}

    fin = _pivot(fin_raw)
    bs = _pivot(bs_raw)
    fin["dt"] = pd.to_datetime(fin["date"])
    bs["dt"] = pd.to_datetime(bs["date"])

    rev  = _col(fin, "營業收入", "revenue", "Revenue")
    cogs = _col(fin, "營業成本")                          # direct COGS field
    gp   = _col(fin, "營業毛利（毛損）", "毛利")
    fin["rev"]  = rev
    fin["cogs"] = cogs.where(cogs > 0).fillna((rev - gp).where(rev > 0))

    ar  = _col(bs, "應收帳款淨額", "應收帳款及票據應收淨額", "應收帳款", "account_receivable")
    inv = _col(bs, "存貨", "inventory")
    bs["ar"] = ar
    bs["inv"] = inv

    merged = fin[["dt", "rev", "cogs"]].merge(bs[["dt", "ar", "inv"]], on="dt", how="inner")
    merged["dso"] = (merged["ar"] / merged["rev"] * 91).round(1)
    merged["dio"] = (merged["inv"] / merged["cogs"] * 91).round(1)
    merged["operating_cycle"] = (merged["dso"] + merged["dio"]).round(1)
    merged["date"] = merged["dt"].dt.to_period("Q").astype(str)

    result = merged[["date", "dso", "dio", "operating_cycle"]].dropna()
    return {"data": result.to_dict("records")}


# ─── 6. Major Shareholders (FinLab TDCC 集保股權分散表) ───────────────────────
# 持股分級 lower bounds in 股 (1 張 = 1000 股):
# lvl 1: 1-999, 2: 1000-5000, ..., 12: 400001-600000, ..., 15: 1000001+
_LEVEL_LOWER = {
    1: 1, 2: 1_000, 3: 5_001, 4: 10_001, 5: 15_001, 6: 20_001,
    7: 30_001, 8: 40_001, 9: 50_001, 10: 100_001, 11: 200_001,
    12: 400_001, 13: 600_001, 14: 800_001, 15: 1_000_001,
}


def _levels_above(min_shares: int) -> set:
    """Return level numbers where lower bound > min_shares * 1000 shares."""
    threshold = min_shares * 1000
    return {lvl for lvl, lb in _LEVEL_LOWER.items() if lb > threshold}


@router.get("/{stock_id}/shareholders")
async def get_shareholders(stock_id: str, years: int = 5, min_shares: int = 400):
    """min_shares in 張. Data from FinLab (TDCC 集保股權分散表)."""
    levels = _levels_above(min_shares)
    start = _start(years)

    cache_key = f"finlab_sh|{stock_id}|{min(levels)}"
    with _lock:
        cached_sh = _cache.get(cache_key)

    if cached_sh and time.time() - cached_sh[0] < CACHE_TTL:
        sh_df = cached_sh[1]
    else:
        def _sync_fetch():
            from finlab import data as fd
            df = fd.get("inventory")
            mask = (df["stock_id"] == stock_id) & (df["持股分級"].astype(int).isin(levels))
            f = df[mask].copy()
            f["dt"] = pd.to_datetime(f["date"])
            f["month"] = f["dt"].dt.to_period("M").astype(str)
            # Multiple weekly snapshots per month — keep only the last date per month
            # before summing across levels to avoid double-counting.
            last_per_month = f.groupby("month")["dt"].transform("max")
            f = f[f["dt"] == last_per_month]
            result = f.groupby("month")["占集保庫存數比例"].sum().reset_index()
            result.columns = ["month", "value"]
            result["value"] = result["value"].round(2)
            return result.sort_values("month")

        try:
            sh_df = await asyncio.to_thread(_sync_fetch)
            with _lock:
                _cache[cache_key] = (time.time(), sh_df)
        except Exception as e:
            return {"data": [], "error": f"FinLab 讀取失敗: {e}"}

    cutoff = (datetime.now() - timedelta(days=years * 365)).strftime("%Y-%m")
    sh_filtered = sh_df[sh_df["month"] >= cutoff].copy()

    price_raw = await _fetch("TaiwanStockPrice", stock_id, start)
    price = _monthly_close(price_raw)
    merged = sh_filtered.merge(price, on="month", how="left")
    merged["price"] = merged["price"].ffill()

    return {"data": merged.rename(columns={"month": "date"}).to_dict("records")}
