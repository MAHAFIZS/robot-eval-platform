import json
from typing import Any, Dict

from rep_core.specs import TaskSpec, EpisodeSpec, ModelRef, DatasetRef, SuiteRef
from packages.backend.db_exec import fetch_one


def _suite_cfg(suite_row: Dict[str, Any]) -> Dict[str, Any]:
    cfg = suite_row.get("config_json")
    if cfg is None:
        return {"episodes_n": 3, "horizon_steps": 50, "seed_start": 0}
    # db_exec may return dict already; normalize
    if isinstance(cfg, str):
        return json.loads(cfg)
    return cfg


def build_taskspec_from_db(run_id: int) -> TaskSpec:
    """
    Day 8: Build TaskSpec by joining runs/models/datasets/suites.
    Suite controls episode generation via suites.config_json.
    """
    run = fetch_one(
        """
        SELECT id, backend, model_id, dataset_id, suite_id
        FROM runs
        WHERE id=:id
        """,
        {"id": run_id},
    )
    if not run:
        raise ValueError(f"run not found: {run_id}")

    model = fetch_one(
        """
        SELECT id, name, version, uri
        FROM models
        WHERE id=:id
        """,
        {"id": run["model_id"]},
    )
    if not model:
        raise ValueError(f"model not found: {run['model_id']}")

    dataset = fetch_one(
        """
        SELECT id, uri, format
        FROM datasets
        WHERE id=:id
        """,
        {"id": run["dataset_id"]},
    )
    if not dataset:
        raise ValueError(f"dataset not found: {run['dataset_id']}")

    # NOTE: your suites table does NOT have a version column (by design right now)
    suite = fetch_one(
        """
        SELECT id, name, config_json
        FROM suites
        WHERE id=:id
        """,
        {"id": run["suite_id"]},
    )
    if not suite:
        raise ValueError(f"suite not found: {run['suite_id']}")

    cfg = _suite_cfg(suite)
    episodes_n = int(cfg.get("episodes_n", 3))
    horizon_steps = int(cfg.get("horizon_steps", 50))
    seed_start = int(cfg.get("seed_start", 0))

    episodes = [
        EpisodeSpec(seed=seed_start + i, horizon_steps=horizon_steps)
        for i in range(episodes_n)
    ]

    return TaskSpec(
        run_id=run["id"],
        backend=run["backend"],
        model=ModelRef(
            model_id=model["id"],
            uri=model["uri"],
            version=model.get("version") or "v1",
        ),
        dataset=DatasetRef(
            dataset_id=dataset["id"],
            uri=dataset["uri"],
            format=dataset.get("format") or "unknown",
        ),
        suite=SuiteRef(
            suite_id=suite["id"],
            name=suite.get("name") or f"suite_{suite['id']}",
            # suites table currently has no version column; default to v1
            version="v1",
        ),
        episodes=episodes,
        artifact_base_uri=f"s3://artifacts/{run_id}/",
    )
