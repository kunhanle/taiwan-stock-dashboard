from typing import Optional, List
from sqlmodel import Field, SQLModel, Relationship

class Category(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    
    stocks: List["CategoryStock"] = Relationship(back_populates="category")

class CategoryStock(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    category_id: int = Field(foreign_key="category.id")
    stock_id: str = Field(index=True)
    
    category: Optional[Category] = Relationship(back_populates="stocks")

# ---------------------------------------------------------------------------
# US–TW Linkage taxonomy (populated from linkage-service/seed/us_categories.yaml
# via ingest_linkage.py). Separate from the user-defined Category/CategoryStock
# tables above — those are the user's own TW watchlist groups, a different concept.
# ---------------------------------------------------------------------------
class UsCategory(SQLModel, table=True):
    slug: str = Field(primary_key=True)          # stable id, e.g. "semi-wfe"
    name_en: str
    name_zh: str
    cluster: str = Field(index=True)
    linkage: str                                 # strong | medium | weak
    flags: Optional[str] = None

    us_tickers: List["UsCategoryTicker"] = Relationship(back_populates="category")
    tw_nodes: List["TwLinkageNode"] = Relationship(back_populates="category")


class UsCategoryTicker(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    category_slug: str = Field(foreign_key="uscategory.slug", index=True)
    ticker: str = Field(index=True)              # US leader ticker, e.g. "NVDA"

    category: Optional[UsCategory] = Relationship(back_populates="us_tickers")


class TwLinkageNode(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    category_slug: str = Field(foreign_key="uscategory.slug", index=True)
    ticker: str = Field(index=True)              # TW id, e.g. "2330"
    name: str
    role: str                                    # up | down | peer | dual
    # True when role == "dual" (ADR<->TW same company): identity, not a linkage
    # signal — the engine must exclude these from correlation scoring.
    exclude_from_scoring: bool = False

    category: Optional[UsCategory] = Relationship(back_populates="tw_nodes")


# ---------------------------------------------------------------------------
# TW active-ETF daily holdings snapshots (collected by etf_holdings.py).
# The issuer sites publish only the CURRENT day's holdings — there is no history
# endpoint — so every day we miss is a day of buy/sell diffs we can never get
# back. One row per (trade_date, etf, stock); the day-over-day share delta is
# the actual signal.
# ---------------------------------------------------------------------------
class EtfHolding(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    trade_date: str = Field(index=True)          # "2026-07-17"
    etf_code: str = Field(index=True)            # "00981A"
    etf_name: str
    stock_code: str = Field(index=True)          # "2330"
    stock_name: str
    shares: float                                # 股數
    weight: float                                # 佔基金淨值權重 %
    amount: float                                # 市值


class StockAnnotation(SQLModel, table=True):
    stock_id: str = Field(primary_key=True)
    
    # Levels (legacy fixed fields kept for migration fallback)
    level_1: Optional[float] = None
    level_2: Optional[float] = None
    level_3: Optional[float] = None

    # Take profit target
    take_profit: Optional[float] = None

    # Support levels stored as comma-separated string e.g. "100,90,80"
    levels_json: Optional[str] = None

    # SMA Settings
    sma_short: Optional[int] = None
    sma_long: Optional[int] = None
