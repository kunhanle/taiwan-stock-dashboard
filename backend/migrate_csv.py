import os
import csv
from sqlmodel import Session, select
from database import engine, create_db_and_tables
from models import Category, CategoryStock, StockAnnotation

def migrate():
    print("Creating tables...")
    create_db_and_tables()
    
    with Session(engine) as session:
        # 1. Migrate Categories
        cat_file = os.path.join(os.path.dirname(__file__), "..", "category.csv")
        if os.path.exists(cat_file):
            print(f"Migrating {cat_file}...")
            with open(cat_file, 'r', encoding='utf-8') as f:
                # category.csv format: Name, StockID1, StockID2...
                for line in f:
                    parts = line.strip().split(',')
                    if not parts: continue
                    cat_name = parts[0].strip()
                    if not cat_name: continue
                    
                    # Create Category
                    category = session.exec(select(Category).where(Category.name == cat_name)).first()
                    if not category:
                        category = Category(name=cat_name)
                        session.add(category)
                        session.commit()
                        session.refresh(category)
                    
                    # Add Stocks
                    stock_ids = [s.strip() for s in parts[1:] if s.strip()]
                    for sid in stock_ids:
                        # Check exist
                        exists = session.exec(select(CategoryStock).where(CategoryStock.category_id == category.id, CategoryStock.stock_id == sid)).first()
                        if not exists:
                            session.add(CategoryStock(category_id=category.id, stock_id=sid))
            session.commit()
            print("Categories migrated.")

        # 2. Migrate SMA
        sma_file = os.path.join(os.path.dirname(__file__), "..", "stock_with_SMA.csv")
        if os.path.exists(sma_file):
            print(f"Migrating {sma_file}...")
            # Format: StockID, Short, Long
            # Check if has header or check format. 
            # Based on view_file earlier: "2408,13,25" -> No header.
            with open(sma_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) < 3: continue
                    sid = row[0].strip()
                    try:
                        short_ma = int(row[1])
                        long_ma = int(row[2])
                    except ValueError:
                        continue
                        
                    # Get or Create Annotation
                    annot = session.get(StockAnnotation, sid)
                    if not annot:
                        annot = StockAnnotation(stock_id=sid)
                    
                    annot.sma_short = short_ma
                    annot.sma_long = long_ma
                    session.add(annot)
            session.commit()
            print("SMA migrated.")

        # 3. Migrate Levels
        lvl_file = os.path.join(os.path.dirname(__file__), "..", "stock_with_levels.csv")
        if os.path.exists(lvl_file):
            print(f"Migrating {lvl_file}...")
            # Format: StockID, L1, L2, L3
            # Based on view_file: "3030,145,160,270"
            with open(lvl_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) < 4: continue
                    sid = row[0].strip()
                    try:
                        l1 = float(row[1])
                        l2 = float(row[2])
                        l3 = float(row[3])
                    except ValueError:
                        continue

                    annot = session.get(StockAnnotation, sid)
                    if not annot:
                        annot = StockAnnotation(stock_id=sid)
                    
                    annot.level_1 = l1
                    annot.level_2 = l2
                    annot.level_3 = l3
                    session.add(annot)
            session.commit()
            print("Levels migrated.")
            
if __name__ == "__main__":
    migrate()
