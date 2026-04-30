from sqlmodel import SQLModel, create_engine, Session
from typing import Generator

import os

# DATA_DIR env var allows persistent volume mounting in production (e.g. Docker)
DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
os.makedirs(DATA_DIR, exist_ok=True)
sqlite_file_name = os.path.join(DATA_DIR, "database.db")
sqlite_url = f"sqlite:///{sqlite_file_name}"

connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, connect_args=connect_args)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
    _migrate()

def _migrate():
    from sqlalchemy import text
    with engine.connect() as conn:
        for ddl in [
            "ALTER TABLE stockannotation ADD COLUMN levels_json TEXT",
            "ALTER TABLE stockannotation ADD COLUMN take_profit REAL",
        ]:
            try:
                conn.execute(text(ddl))
                conn.commit()
            except Exception:
                pass  # Column already exists


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
