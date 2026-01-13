from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Literal

from packages.backend.db import ping_db
from packages.backend.db_exec import fetch_all, fetch_one, exec_returning

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
