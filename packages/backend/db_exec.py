import os
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

def get_db_url() -> str:
    return os.getenv("DATABASE_URL", "postgresql+psycopg://eval:eval@localhost:5432/evaldb")

_engine: Engine | None = None

def engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(get_db_url(), pool_pre_ping=True)
    return _engine

def fetch_all(sql: str, params: dict | None = None) -> list[dict]:
    with engine().connect() as conn:
        result = conn.execute(text(sql), params or {})
        cols = result.keys()
        return [dict(zip(cols, row)) for row in result.fetchall()]

def fetch_one(sql: str, params: dict | None = None) -> dict | None:
    rows = fetch_all(sql, params)
    return rows[0] if rows else None

def exec_returning(sql: str, params: dict | None = None) -> dict:
    with engine().connect() as conn:
        with conn.begin():
            result = conn.execute(text(sql), params or {})
            row = result.fetchone()
            if row is None:
                return {}
            cols = result.keys()
            return dict(zip(cols, row))
