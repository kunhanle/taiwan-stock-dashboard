"""
Ingest the US–TW linkage seed into the backend SQLite DB.

Reads linkage-service/seed/us_categories.yaml and (re)populates the
UsCategory / UsCategoryTicker / TwLinkageNode tables. Idempotent: wipes the
three linkage tables first, so re-running always mirrors the current seed.

`role == "dual"` (ADR <-> TW same company) is persisted with
exclude_from_scoring=True so the linkage engine can skip self-correlation.

Usage (from anywhere):
  python backend/ingest_linkage.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml
from sqlmodel import Session, delete, select

# Allow `import models` / `import database` when run from repo root or backend/.
BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from database import create_db_and_tables, engine  # noqa: E402
from models import TwLinkageNode, UsCategory, UsCategoryTicker  # noqa: E402

SEED = BACKEND_DIR.parent / "linkage-service" / "seed" / "us_categories.yaml"


def load_seed() -> list[dict]:
    with open(SEED, encoding="utf-8") as f:
        return yaml.safe_load(f)


def ingest() -> dict:
    create_db_and_tables()  # creates the new linkage tables if absent
    seed = load_seed()

    n_cat = n_us = n_tw = n_dual = 0
    with Session(engine) as s:
        # Idempotent: clear existing linkage rows (children first).
        s.exec(delete(UsCategoryTicker))
        s.exec(delete(TwLinkageNode))
        s.exec(delete(UsCategory))
        s.commit()

        for c in seed:
            s.add(UsCategory(
                slug=c["id"],
                name_en=c.get("name_en", ""),
                name_zh=c.get("name_zh", ""),
                cluster=c.get("cluster", ""),
                linkage=c.get("linkage", ""),
                flags=c.get("flags") or None,
            ))
            n_cat += 1
            for t in c["us_tickers"]:
                s.add(UsCategoryTicker(category_slug=c["id"], ticker=str(t)))
                n_us += 1
            for node in c.get("tw_linkage") or []:
                role = node.get("role", "")
                is_dual = role == "dual"
                s.add(TwLinkageNode(
                    category_slug=c["id"],
                    ticker=str(node["t"]),
                    name=node.get("n", ""),
                    role=role,
                    exclude_from_scoring=is_dual,
                ))
                n_tw += 1
                n_dual += is_dual
        s.commit()

    return {"categories": n_cat, "us_rows": n_us, "tw_rows": n_tw, "dual_rows": n_dual}


def main() -> int:
    if not SEED.exists():
        print(f"Seed not found: {SEED}", file=sys.stderr)
        return 1
    stats = ingest()
    print(f"Ingested from {SEED.name}:")
    print(f"  US categories : {stats['categories']}")
    print(f"  US ticker rows: {stats['us_rows']}")
    print(f"  TW node rows  : {stats['tw_rows']}  (dual/excluded: {stats['dual_rows']})")
    print(f"  DB: {os.path.join(os.environ.get('DATA_DIR', str(BACKEND_DIR)), 'database.db')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
