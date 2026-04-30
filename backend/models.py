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
