import json

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
# ----------------------------
# run_episodes helpers
# ----------------------------

# ----------------------------
# run_episodes helpers
# ----------------------------

# ----------------------------
# run_episodes helpers
# ----------------------------

# ----------------------------
# run_episodes helpers
# ----------------------------

def create_run_episode(run_id: int, episode_index: int) -> int:
    # Creates (or reuses) a row for this episode and returns episode_id
    with engine().begin() as conn:
        row = conn.execute(
            text("""
                INSERT INTO episodes (run_id, episode_index, status, started_at)
                VALUES (:run_id, :episode_index, 'running', now())
                ON CONFLICT (run_id, episode_index) DO UPDATE
                SET status = 'running',
                    started_at = COALESCE(episodes.started_at, now()),
                    error_message = NULL
                RETURNING id;
            """),
            {"run_id": run_id, "episode_index": episode_index},
        ).fetchone()

        # fetchone() returns a Row; id is first column
        return int(row[0])


def complete_run_episode(episode_id: int, metrics_json: dict) -> None:
    with engine().begin() as conn:
        conn.execute(
            text("""
                UPDATE episodes
                SET status = 'completed',
                    ended_at = now(),
                    metrics_json = CAST(:metrics_json AS jsonb),
                    error_message = NULL
                WHERE id = :episode_id;
            """),
            {"episode_id": episode_id, "metrics_json": json.dumps(metrics_json)},
        )



def fail_run_episode(episode_id: int, error_message: str) -> None:
    with engine().begin() as conn:
        conn.execute(
            text("""
                UPDATE episodes
                SET status = 'failed',
                    ended_at = now(),
                    error_message = :error_message
                WHERE id = :episode_id;
            """),
            {"episode_id": episode_id, "error_message": error_message},
        )


def list_run_episodes(run_id: int) -> list[dict]:
    with engine().begin() as conn:
        result = conn.execute(
            text("""
                SELECT id, run_id, episode_index, status, metrics_json, error_message,
                       started_at, ended_at
                FROM episodes
                WHERE run_id = :run_id
                ORDER BY episode_index ASC;
            """),
            {"run_id": run_id},
        )
        rows = result.mappings().all()
        return [dict(r) for r in rows]
