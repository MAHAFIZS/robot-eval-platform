from sqlalchemy import text
from db import engine

with engine.connect() as c:
    result = c.execute(text("SELECT to_regclass('public.run_episodes')")).scalar()
    print(result)
