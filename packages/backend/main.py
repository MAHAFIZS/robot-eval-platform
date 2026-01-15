# packages/backend/main.py

import os
from typing import List, Optional, Literal
from urllib.parse import urlparse

import boto3
from botocore.client import Config
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from packages.backend.db import ping_db
from packages.backend.db_exec import fetch_all, fetch_one, exec_returning
from packages.backend.hashutil import sha256_text

app = FastAPI(title="Robot Eval Orchestrator API")


# ----------------------
# Health
# ----------------------
@app.get("/health")
def health():
    return {"status": "ok", "db": "ok" if ping_db() else "down"}


# ----------------------
# MinIO / S3 helpers (Day 9)
# ----------------------
def minio_client():
    endpoint_url = os.getenv("S3_ENDPOINT_URL", "http://localhost:9000")
    access_key = os.getenv("S3_ACCESS_KEY", "minio")
    secret_key = os.getenv("S3_SECRET_KEY", "minio12345")
    region = os.getenv("S3_REGION", "us-east-1")

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(signature_version="s3v4"),
    )


def parse_s3_uri(uri: str) -> tuple[str, str]:
    # s3://bucket/key/path/file.html
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path:
        raise ValueError(f"invalid s3 uri: {uri}")
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    return bucket, key


def presign_s3_get(uri: str, expires_seconds: int = 3600) -> str:
    s3 = minio_client()
    bucket, key = parse_s3_uri(uri)
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_seconds,
    )


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


# Day 9: run detail endpoint
@app.get("/runs/{run_id}")
def get_run(run_id: int):
    run = fetch_one(
        """
        SELECT id, model_id, suite_id, dataset_id, backend, status,
               started_at, ended_at, summary_json, report_uri, error_message, created_at
        FROM runs
        WHERE id=:id
        """,
        {"id": run_id},
    )
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return run


# Day 9: open report endpoint (redirect to presigned MinIO URL)
@app.get("/runs/{run_id}/report")
def open_report(run_id: int):
    run = fetch_one("SELECT id, report_uri FROM runs WHERE id=:id", {"id": run_id})
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    uri = run.get("report_uri")
    if not uri:
        raise HTTPException(status_code=404, detail="report_uri missing")

    if uri.startswith("http://") or uri.startswith("https://"):
        return RedirectResponse(uri)

    if uri.startswith("s3://"):
        try:
            url = presign_s3_get(uri, expires_seconds=3600)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"failed to presign report: {e}")
        return RedirectResponse(url)

    raise HTTPException(status_code=400, detail="unknown report_uri scheme")


# Day 9: minimal UI
@app.get("/ui/runs", response_class=HTMLResponse)
def ui_runs():
    runs = fetch_all(
        """
        SELECT id, backend, status, created_at, started_at, ended_at,
               report_uri, summary_json, error_message
        FROM runs
        ORDER BY id DESC
        LIMIT 50
        """,
        {},
    )

    rows_html = ""
    for r in runs:
        rid = r["id"]
        status = r["status"]
        backend = r["backend"]
        created = r["created_at"]
        summary = r.get("summary_json")
        err = r.get("error_message") or ""

        report_btn = (
            f'<a class="btn" href="/runs/{rid}/report" target="_blank">Open report</a>'
            if r.get("report_uri")
            else ""
        )

        rows_html += f"""
        <tr>
          <td>{rid}</td>
          <td>{backend}</td>
          <td><b>{status}</b></td>
          <td>{created}</td>
          <td><pre>{summary}</pre></td>
          <td style="color:#ffb4b4;">{err}</td>
          <td>{report_btn}</td>
        </tr>
        """

    html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8" />
      <title>robot-eval-platform — Runs</title>
      <style>
        body {{ font-family: Arial, sans-serif; margin: 24px; background: #0b0f19; color: #e6e6e6; }}
        h1 {{ margin-bottom: 12px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ border-bottom: 1px solid #222; padding: 10px; vertical-align: top; }}
        th {{ text-align: left; color: #b8c0ff; }}
        pre {{ margin: 0; white-space: pre-wrap; word-break: break-word; max-width: 520px; }}
        .btn {{ display: inline-block; padding: 6px 10px; border: 1px solid #3a4; border-radius: 6px; color: #dff; text-decoration: none; }}
        .btn:hover {{ background: #163; }}
      </style>
    </head>
    <body>
      <h1>Runs</h1>
      <p>Latest 50 runs. Click “Open report” to view MinIO-hosted HTML.</p>
      <table>
        <thead>
          <tr>
            <th>ID</th><th>Backend</th><th>Status</th><th>Created</th><th>Summary</th><th>Error</th><th>Report</th>
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.post("/runs/{run_id}/enqueue")
def enqueue_run(run_id: int):
    from packages.worker.tasks import evaluate_run  # import here to avoid circular imports

    run = fetch_one("SELECT id, status FROM runs WHERE id=:id", {"id": run_id})
    if not run:
        raise HTTPException(status_code=404, detail="run not found")

    if run["status"] != "queued":
        raise HTTPException(
            status_code=409,
            detail=f"run status must be queued (is {run['status']})",
        )

    task = evaluate_run.delay(run_id)
    return {"message": "enqueued", "run_id": run_id, "task_id": task.id}
