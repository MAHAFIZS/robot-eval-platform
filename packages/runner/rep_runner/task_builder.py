from __future__ import annotations

from rep_core.specs import TaskSpec, EpisodeSpec, ModelRef, DatasetRef, SuiteRef


def build_taskspec_stub(
    *,
    run_id: int,
    backend: str,
    model_id: int,
    dataset_id: int,
    suite_id: int,
    episodes_n: int = 3,
) -> TaskSpec:
    """
    Day 6 stub. Day 7 will build this from DB + suite definition.
    """
    return TaskSpec(
        run_id=run_id,
        backend=backend,
        model=ModelRef(model_id=model_id, uri=f"s3://models/{model_id}/model.pt", version="v1"),
        dataset=DatasetRef(dataset_id=dataset_id, uri=f"s3://datasets/{dataset_id}/dataset.zip", format="zip"),
        suite=SuiteRef(suite_id=suite_id, name="default_suite", version="v1"),
        episodes=[EpisodeSpec(seed=i, horizon_steps=100) for i in range(episodes_n)],
        artifact_base_uri=f"s3://artifacts/{run_id}/",
    )
