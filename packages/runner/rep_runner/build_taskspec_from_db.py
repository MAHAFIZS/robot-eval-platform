# packages/runner/rep_runner/build_taskspec_from_db.py

from __future__ import annotations

from typing import Any, Dict, List
from datetime import datetime, date

from packages.backend.db_exec import fetch_one
from rep_core.specs import TaskSpec, EpisodeSpec


def _jsonable(x: Any) -> Any:
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    if isinstance(x, (datetime, date)):
        return x.isoformat()
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    return str(x)


def build_taskspec_from_db(run_id: int) -> TaskSpec:
    run = fetch_one(
        """
        SELECT id, model_id, suite_id, dataset_id, backend
        FROM runs
        WHERE id = :id
        """,
        {"id": run_id},
    )
    if not run:
        raise ValueError(f"run not found: {run_id}")

    model = fetch_one("SELECT * FROM models WHERE id = :id", {"id": run["model_id"]})
    suite = fetch_one("SELECT * FROM suites WHERE id = :id", {"id": run["suite_id"]})
    dataset = fetch_one("SELECT * FROM datasets WHERE id = :id", {"id": run["dataset_id"]})

    if not model:
        raise ValueError(f"model not found: {run['model_id']}")
    if not suite:
        raise ValueError(f"suite not found: {run['suite_id']}")
    if not dataset:
        raise ValueError(f"dataset not found: {run['dataset_id']}")

    model_cfg = model.get("config_json") or {}
    suite_cfg = suite.get("config_json") or {}
    dataset_cfg = dataset.get("config_json") or {}

    num_episodes = int(suite_cfg.get("num_episodes", 1))

    merged_cfg: Dict[str, Any] = {}
    merged_cfg.update(model_cfg)
    merged_cfg.update(dataset_cfg)
    merged_cfg.update(suite_cfg)

    # Runner expects episode_id to be a STRING like "000"
    episodes: List[EpisodeSpec] = [
        EpisodeSpec(episode_id=f"{i:03d}") for i in range(num_episodes)
    ]

    # rep_core TaskSpec expects model_id/suite_id/dataset_id style fields in nested dicts
    model_payload = {"model_id": model["id"], **_jsonable(model)}
    suite_payload = {"suite_id": suite["id"], **_jsonable(suite)}
    dataset_payload = {"dataset_id": dataset["id"], **_jsonable(dataset)}

    return TaskSpec(
        run_id=run_id,
        backend=(run.get("backend") or "mujoco"),
        artifact_base_uri=f"s3://artifacts/{run_id}",
        model=model_payload,
        suite=suite_payload,
        dataset=dataset_payload,
        config=_jsonable(merged_cfg),
        episodes=episodes,
    )
