from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Literal

from packages.backend.db import ping_db
from packages.backend.db_exec import fetch_all, fetch_one, exec_returning
from packages.backend.hashutil import sha256_text

app = FastAPI(title="Robot Eval Orchestrator API")

@app.get("/health")
def health():
    return {"status": "ok", "db": "ok" if ping_db() else "down"}

# ----------------------
# Models
# ----------------------
class ModelCreate(BaseModel):
    name: str
    version: str
    tags: List[str] = Field(default_factory=list)
    artifact_uri: Optional[str] = None
    commit_hash: Optional[str] = None

@app.post("/models")
def create_model(payload: ModelCreate):
    existing = fetch_one(
        "SELECT id FROM models WHERE name=:name AND version=:version",
        {"name": payload.name, "version": payload.version},
    )
    if existing:
        raise HTTPException(status_code=409, detail="Model name+version already exists")

    row = exec_returning(
        """
        INSERT INTO models (name, version, tags, artifact_uri, commit_hash)
        VALUES (:name, :version, :tags, :artifact_uri, :commit_hash)
        RETURNING id, name, version, tags, artifact_uri, commit_hash, created_at
        """,
        {
            "name": payload.name,
            "version": payload.version,
            "tags": payload.tags,
            "artifact_uri": payload.artifact_uri,
            "commit_hash": payload.commit_hash,
        },
    )
    return row

@app.get("/models")
def list_models(tag: Optional[str] = None):
    if tag:
        return fetch_all(
            "SELECT * FROM models WHERE :tag = ANY(tags) ORDER BY created_at DESC",
            {"tag": tag},
        )
    return fetch_all("SELECT * FROM models ORDER BY created_at DESC")

# ----------------------
# Suites
# ----------------------
class SuiteCreate(BaseModel):
    name: str
    yaml_spec: str  # store raw YAML text

@app.post("/suites")
def create_suite(payload: SuiteCreate):
    spec_hash = sha256_text(payload.yaml_spec)

    existing = fetch_one("SELECT id FROM suites WHERE hash=:h", {"h": spec_hash})
    if existing:
        # idempotent: return existing
        return fetch_one("SELECT * FROM suites WHERE id=:id", {"id": existing["id"]})

    row = exec_returning(
        """
        INSERT INTO suites (name, yaml_spec, hash)
        VALUES (:name, :yaml_spec, :hash)
        RETURNING id, name, hash, created_at
        """,
        {"name": payload.name, "yaml_spec": payload.yaml_spec, "hash": spec_hash},
    )
    return row

@app.get("/suites")
def list_suites():
    return fetch_all("SELECT id, name, hash, created_at FROM suites ORDER BY created_at DESC")

@app.get("/suites/{suite_id}")
def get_suite(suite_id: int):
    row = fetch_one("SELECT * FROM suites WHERE id=:id", {"id": suite_id})
    if not row:
        raise HTTPException(status_code=404, detail="suite not found")
    return row

# ----------------------
# Datasets
# ----------------------
class DatasetCreate(BaseModel):
    name: str
    version: str
    uri: str
    hash: Optional[str] = None  # allow providing a precomputed hash

@app.post("/datasets")
def create_dataset(payload: DatasetCreate):
    # If user didn't provide a hash, derive from name+version+uri (simple governance for now)
    ds_hash = payload.hash or sha256_text(f"{payload.name}|{payload.version}|{payload.uri}")

    existing_nv = fetch_one(
        "SELECT id FROM datasets WHERE name=:name AND version=:version",
        {"name": payload.name, "version": payload.version},
    )
    if existing_nv:
        raise HTTPException(status_code=409, detail="Dataset name+version already exists")

    existing_hash = fetch_one("SELECT id FROM datasets WHERE hash=:h", {"h": ds_hash})
    if existing_hash:
        raise HTTPException(status_code=409, detail="Dataset hash already exists")

    row = exec_returning(
        """
        INSERT INTO datasets (name, version, uri, hash)
        VALUES (:name, :version, :uri, :hash)
        RETURNING id, name, version, uri, hash, created_at
        """,
        {"name": payload.name, "version": payload.version, "uri": payload.uri, "hash": ds_hash},
    )
    return row

@app.get("/datasets")
def list_datasets():
    return fetch_all("SELECT * FROM datasets ORDER BY created_at DESC")

# ----------------------
# Runs
# ----------------------
class RunCreate(BaseModel):
    model_id: int
    suite_id: Optional[int] = None
    dataset_id: Optional[int] = None
    backend: Literal["mujoco", "real", "replay"] = "mujoco"

@app.post("/runs")
def create_run(payload: RunCreate):
    m = fetch_one("SELECT id FROM models WHERE id=:id", {"id": payload.model_id})
    if not m:
        raise HTTPException(status_code=404, detail="model_id not found")

    if payload.suite_id is not None:
        s = fetch_one("SELECT id FROM suites WHERE id=:id", {"id": payload.suite_id})
        if not s:
            raise HTTPException(status_code=404, detail="suite_id not found")

    if payload.dataset_id is not None:
        d = fetch_one("SELECT id FROM datasets WHERE id=:id", {"id": payload.dataset_id})
        if not d:
            raise HTTPException(status_code=404, detail="dataset_id not found")

    row = exec_returning(
        """
        INSERT INTO runs (model_id, suite_id, dataset_id, backend, status)
        VALUES (:model_id, :suite_id, :dataset_id, :backend, 'queued')
        RETURNING id, model_id, suite_id, dataset_id, backend, status, created_at
        """,
        {
            "model_id": payload.model_id,
            "suite_id": payload.suite_id,
            "dataset_id": payload.dataset_id,
            "backend": payload.backend,
        },
    )
    return row

@app.get("/runs")
def list_runs(limit: int = 50):
    return fetch_all(
        """
        SELECT r.*, m.name as model_name, m.version as model_version
        FROM runs r
        JOIN models m ON m.id = r.model_id
        ORDER BY r.created_at DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )

@app.post("/runs/{run_id}/enqueue")
def enqueue_run(run_id: int):
    run = fetch_one("SELECT id, status FROM runs WHERE id=:id", {"id": run_id})
    if not run:
        raise HTTPException(status_code=404, detail="run not found")

    if run["status"] != "queued":
        raise HTTPException(status_code=409, detail=f"run status must be queued (is {run['status']})")

    updated = exec_returning(
        """
        UPDATE runs
        SET status='running', started_at=NOW()
        WHERE id=:id
        RETURNING id, status, started_at
        """,
        {"id": run_id},
    )
    return {"message": "enqueued (stub)", "run": updated}
