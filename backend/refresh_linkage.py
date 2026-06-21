"""
Scheduled refresh (Step 6): run nightly after the US close.

  1. Re-validate every ticker (catches delisting drift like JNPR / 奇力新).
  2. Pre-compute the two-layer linkage for ALL categories and write a snapshot
     JSON, so the API / frontend serve instantly instead of computing live.
  3. Warm the on-disk caches (TW symbols, SEC CIK map, US EDGAR revenue) as a
     side effect of the computation.

Run:  python backend/refresh_linkage.py
Cron: e.g. daily 06:30 Asia/Taipei (after the US session settles).
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

from sqlmodel import Session, select

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))
REPO = BACKEND_DIR.parent
VALIDATE = REPO / "linkage-service" / "validate_tickers.py"
REPORT = REPO / "linkage-service" / "seed" / "ticker_validation_report.json"
SNAPSHOT = REPO / "linkage-service" / "seed" / "linkage_snapshot.json"

from database import engine  # noqa: E402
from models import UsCategory  # noqa: E402
import linkage_engine as le  # noqa: E402
import linkage_synthesis as ls  # noqa: E402


def _finlab_env() -> dict:
    env = dict(os.environ)
    if not env.get("FINLAB_API_TOKEN"):
        tok = Path.home() / ".finlab_token"
        if tok.exists():
            env["FINLAB_API_TOKEN"] = tok.read_text(encoding="utf-8").strip()
    return env


def validate() -> dict:
    """Run the ticker validator; return its report (invalids = drift)."""
    print("[1/2] validating tickers (delisting drift check)...")
    try:
        subprocess.run([sys.executable, str(VALIDATE)], cwd=str(VALIDATE.parent),
                       env=_finlab_env(), check=False, timeout=900,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:  # noqa: BLE001
        print(f"  validator failed: {e}")
    rep = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else {}
    drift = {**rep.get("us_invalid", {}), **rep.get("tw_invalid", {})}
    if drift:
        print(f"  ⚠ DRIFT — {len(drift)} invalid ticker(s): "
              + ", ".join(f"{k}->{','.join(v)}" for k, v in drift.items()))
    else:
        print(f"  ok: {rep.get('us_total')} US / {rep.get('tw_total')} TW all valid")
    return rep


def build_snapshot(stamp: str) -> dict:
    print("[2/2] pre-computing two-layer for all categories...")
    cats_out, movers, missing_price = {}, [], []
    with Session(engine) as s:
        slugs = [c.slug for c in s.exec(select(UsCategory)).all()]
        for i, slug in enumerate(slugs, 1):
            try:
                r = ls.category_two_layer(s, slug)
            except Exception as e:  # noqa: BLE001
                print(f"  [{i}/{len(slugs)}] {slug}: FAILED {e}")
                continue
            cats_out[slug] = r
            movers.append({"slug": slug, "name_zh": r["name_zh"], "cluster": r["cluster"],
                           "a_move": r["a_move"], "a_z": r["a_z"]})
            # delisting signal: a TW node with neither price nor revenue
            for n in r["nodes"]:
                if n.get("a_corr") is None and n.get("b_corr") is None and n.get("b_corr_raw") is None:
                    missing_price.append(f"{slug}:{n['ticker']}")
            print(f"  [{i}/{len(slugs)}] {slug}: {len(r['nodes'])} nodes")
    movers.sort(key=lambda x: abs(x["a_z"] or 0), reverse=True)
    return {"generated_at": stamp, "categories": cats_out, "movers": movers,
            "suspect_delisted": missing_price}


def main() -> int:
    stamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    validate()
    snap = build_snapshot(stamp)
    SNAPSHOT.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    print(f"\nsnapshot: {len(snap['categories'])} categories -> {SNAPSHOT.name} @ {stamp}")
    if snap["suspect_delisted"]:
        print(f"⚠ suspect delisted nodes: {', '.join(snap['suspect_delisted'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
