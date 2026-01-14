from rep_core.specs import TaskSpec, EpisodeSpec, ModelRef, DatasetRef, SuiteRef
from rep_runner.runner import Runner
from rep_runner.backends import make_backend

task = TaskSpec(
    run_id=999,
    backend="mujoco",  # ← this string now selects the backend
    model=ModelRef(model_id=1, uri="s3://models/1/model.pt", version="v1"),
    dataset=DatasetRef(dataset_id=1, uri="s3://datasets/1/dset.zip", format="zip"),
    suite=SuiteRef(suite_id=1, name="smoke_suite", version="v1"),
    episodes=[
        EpisodeSpec(seed=0, horizon_steps=50),
        EpisodeSpec(seed=1, horizon_steps=50),
    ],
    artifact_base_uri="s3://artifacts/999/",
)

backend = make_backend(task.backend)
runner = Runner(backend=backend, local_artifact_root="artifacts")

result = runner.run(task)
print("SUMMARY:", result.summary)
