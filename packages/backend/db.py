import os
from sqlalchemy import create_engine, text

def get_db_url() -> str:
    return os.getenv("DATABASE_URL", "postgresql+psycopg://eval:eval@localhost:5432/evaldb")

engine = create_engine(get_db_url(), pool_pre_ping=True)

def ping_db() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
