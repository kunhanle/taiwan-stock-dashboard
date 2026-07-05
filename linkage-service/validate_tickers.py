"""
Ticker validation for the US-TW supply-chain category seed.

Validates every US ticker (us_tickers) and every Taiwan ticker (tw_linkage[].t)
referenced in seed/us_categories.yaml against live data sources:

  * US  tickers  -> yfinance (Yahoo Finance)
  * TW  tickers  -> FinLab `company_basic_info` (requires FINLAB_API_TOKEN);
                    falls back to yfinance "<id>.TW" / "<id>.TWO" if FinLab
                    is unavailable.

Outputs a human-readable summary plus a machine-readable report at
seed/ticker_validation_report.json listing any invalid/unresolved tickers
and which categories reference them.

NOTE: This environment's network egress allowlist may block Yahoo / FinLab
(HTTP 403). If so, run this locally or add the hosts to the egress settings:
  query1.finance.yahoo.com, query2.finance.yahoo.com, api.finlab.tw

Usage:
  FINLAB_API_TOKEN=xxxx python validate_tickers.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import warnings
from collections import defaultdict
from pathlib import Path

import yaml

warnings.filterwarnings("ignore")

SEED = Path(__file__).parent / "seed" / "us_categories.yaml"
REPORT = Path(__file__).parent / "seed" / "ticker_validation_report.json"


def load_seed() -> list[dict]:
    with open(SEED, encoding="utf-8") as f:
        return yaml.safe_load(f)


def collect(seed: list[dict]):
    """Return {us_ticker: [category_ids]} and {tw_ticker: [category_ids]}."""
    us, tw = defaultdict(list), defaultdict(list)
    for c in seed:
        for t in c["us_tickers"]:
            us[str(t)].append(c["id"])
        for n in c.get("tw_linkage") or []:
            tw[str(n["t"])].append(c["id"])
    return us, tw


# --------------------------------------------------------------------------- #
# US validation (yfinance)
# --------------------------------------------------------------------------- #
def _yf_has_history(symbol: str, retries: int = 3) -> bool:
    """True if Yahoo returns price history for `symbol`.

    Retries on empty/exception with backoff: under a long sequential run Yahoo
    intermittently throttles and returns an empty frame for a perfectly valid
    ticker, which would otherwise be mislabelled INVALID.
    """
    import yfinance as yf

    for attempt in range(retries):
        try:
            df = yf.Ticker(symbol).history(period="5d")
            if not df.empty:
                return True
        except Exception:
            pass
        time.sleep(0.5 * (attempt + 1))  # backoff before retrying
    return False


def validate_us(tickers: list[str]) -> dict[str, bool]:
    result = {}
    for i, t in enumerate(sorted(tickers), 1):
        ok = _yf_has_history(t)
        result[t] = ok
        print(f"  [US {i:>3}/{len(tickers)}] {t:<6} {'OK' if ok else 'INVALID'}")
        time.sleep(0.15)  # be gentle on Yahoo
    return result


# --------------------------------------------------------------------------- #
# TW validation (FinLab preferred, yfinance fallback)
# --------------------------------------------------------------------------- #
def validate_tw_finlab(tickers: list[str], token: str) -> dict[str, bool] | None:
    try:
        from finlab import data, login

        login(api_token=token)
        info = data.get("company_basic_info")
        valid = set(info["stock_id"].astype(str))
        print(f"  FinLab company_basic_info: {len(valid)} listed IDs loaded")
        return {t: (t in valid) for t in tickers}
    except Exception as e:  # noqa: BLE001
        print(f"  FinLab unavailable ({e}); falling back to yfinance .TW", file=sys.stderr)
        return None


def validate_tw_yfinance(tickers: list[str]) -> dict[str, bool]:
    result = {}
    for i, t in enumerate(sorted(tickers), 1):
        ok = any(_yf_has_history(t + suffix) for suffix in (".TW", ".TWO"))
        result[t] = ok
        print(f"  [TW {i:>3}/{len(tickers)}] {t:<6} {'OK' if ok else 'INVALID'}")
        time.sleep(0.15)
    return result


# --------------------------------------------------------------------------- #
def main() -> int:
    seed = load_seed()
    us_map, tw_map = collect(seed)
    print(f"Seed: {len(seed)} categories | {len(us_map)} US tickers | {len(tw_map)} TW tickers\n")

    print("Validating US tickers (yfinance)...")
    us_valid = validate_us(list(us_map))

    print("\nValidating TW tickers...")
    token = os.getenv("FINLAB_API_TOKEN")
    tw_valid = validate_tw_finlab(list(tw_map), token) if token else None
    if tw_valid is None:
        tw_valid = validate_tw_yfinance(list(tw_map))

    us_bad = {t: us_map[t] for t, ok in us_valid.items() if not ok}
    tw_bad = {t: tw_map[t] for t, ok in tw_valid.items() if not ok}

    report = {
        "us_total": len(us_map),
        "tw_total": len(tw_map),
        "us_invalid": us_bad,
        "tw_invalid": tw_bad,
        "tw_source": "finlab" if token else "yfinance",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"US: {len(us_map) - len(us_bad)}/{len(us_map)} valid")
    if us_bad:
        for t, cats in us_bad.items():
            print(f"  INVALID US {t}  -> {', '.join(cats)}")
    print(f"TW: {len(tw_map) - len(tw_bad)}/{len(tw_map)} valid  (source: {report['tw_source']})")
    if tw_bad:
        for t, cats in tw_bad.items():
            print(f"  INVALID TW {t}  -> {', '.join(cats)}")
    print(f"\nReport written to {REPORT}")
    return 1 if (us_bad or tw_bad) else 0


if __name__ == "__main__":
    raise SystemExit(main())
