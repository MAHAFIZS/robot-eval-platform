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
    row = exec_returning(
        """
        INSERT INTO run_episodes (run_id, episode_index, status)
        VALUES (:run_id, :episode_index, 'running')
        RETURNING id
        """,
        {"run_id": run_id, "episode_index": episode_index},
    )
    return int(row["id"])


def complete_run_episode(episode_id: int, metrics_json: dict) -> None:
    exec_returning(
        """
        UPDATE run_episodes
        SET status = 'completed',
            metrics_json = CAST(:metrics_json AS jsonb),
            ended_at = now()
        WHERE id = :episode_id
        RETURNING id
        """,
        {"episode_id": episode_id, "metrics_json": json.dumps(metrics_json)},
    )


def fail_run_episode(episode_id: int, error_message: str) -> None:
    exec_returning(
        """
        UPDATE run_episodes
        SET status = 'failed',
            error_message = :error_message,
            ended_at = now()
        WHERE id = :episode_id
        RETURNING id
        """,
        {"episode_id": episode_id, "error_message": error_message},
    )


def list_run_episodes(run_id: int) -> list[dict]:
    return fetch_all(
        """
        SELECT id, run_id, episode_index, status, metrics_json, error_message, started_at, ended_at
        FROM run_episodes
        WHERE run_id = :run_id
        ORDER BY episode_index ASC
        """,
        {"run_id": run_id},
    )
