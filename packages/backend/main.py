# packages/backend/main.py  (CLEAN FINAL — corrected)
# Robot Eval Orchestrator API (FastAPI)
#
# Assumptions:
# - gate_evaluations columns: id, baseline_run_id, candidate_run_id, status, details_json, created_at
#   (NO suite_id/dataset_id/backend columns in gate_evaluations)
# - baseline_locks columns: id, suite_id, dataset_id, backend, baseline_run_id, created_at
# - runs has: id, model_id, suite_id, dataset_id, backend, status, created_at, started_at, ended_at,
#             summary_json, report_uri, error_message, git_commit, config_snapshot, seed, worker_version, ...
#
# Notes:
# - /ui/runs shows latest gate badge per run (pass/fail/—) + SHIP/BLOCK/PENDING badge
# - /ui/gates shows latest gate evaluations list
# - /ui/gate shows a single gate detail page
# - /ship/decision returns SHIP/BLOCK/PENDING for CI

import json
import os
import random
import subprocess
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import urlparse

import boto3
from botocore.client import Config
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from packages.backend.db import ping_db
from packages.backend.db_exec import exec_returning, fetch_all, fetch_one, list_run_episodes
from packages.backend.hashutil import sha256_text

app = FastAPI(title="Robot Eval Orchestrator API")

ARTIFACTS_LOCAL_DIR = os.getenv("ARTIFACTS_LOCAL_DIR", "./artifacts")
WORKER_VERSION = os.getenv("WORKER_VERSION", "dev")


# ----------------------
# Repro helpers
# ----------------------
def get_git_commit() -> Optional[str]:
    env_sha = os.getenv("GIT_COMMIT")
    if env_sha:
        return env_sha.strip()
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return None


def make_seed() -> int:
    s = os.getenv("RUN_SEED")
    if s:
        try:
            return int(s)
        except Exception:
            pass
    return random.randint(1, 2_147_483_647)


# ----------------------
# Health
# ----------------------
@app.get("/health")
def health():
    return {
        "status": "ok",
        "db": "ok" if ping_db() else "down",
        "whoami": "packages/backend/main.py (UPDATED)"
    }



# ----------------------
# MinIO / S3 helpers
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


def parse_s3_uri(uri: str) -> Tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path:
        raise ValueError(f"invalid s3 uri: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def presign_s3_get(uri: str, expires_seconds: int = 3600) -> str:
    s3 = minio_client()
    bucket, key = parse_s3_uri(uri)
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_seconds,
    )


# ----------------------
# Local artifact helpers
# ----------------------
def _safe_join(base_dir: str, rel_path: str) -> str:
    base = os.path.abspath(base_dir)
    target = os.path.abspath(os.path.join(base, rel_path))
    if not (target == base or target.startswith(base + os.sep)):
        raise ValueError("invalid artifact path")
    return target


def _media_type_for_name(name: str) -> str:
    n = name.lower()
    if n.endswith(".html"):
        return "text/html"
    if n.endswith(".json"):
        return "application/json"
    if n.endswith(".jsonl"):
        return "application/x-ndjson"
    if n.endswith(".csv"):
        return "text/csv"
    if n.endswith(".txt") or n.endswith(".log"):
        return "text/plain"
    if n.endswith(".png"):
        return "image/png"
    if n.endswith(".jpg") or n.endswith(".jpeg"):
        return "image/jpeg"
    if n.endswith(".mp4"):
        return "video/mp4"
    return "application/octet-stream"


# ----------------------
# KPI helpers
# ----------------------
def _as_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _as_int(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        return int(x)
    except Exception:
        return None


def _dashboard_fields_from_summary(summary: Any) -> Dict[str, Any]:
    if not isinstance(summary, dict):
        return {
            "success_rate": None,
            "latency_p95_ms": None,
            "safety_violations": None,
            "time_to_success_mean_s": None,
            "num_episodes": None,
            "duration_mean_ms": None,
        }

    return {
        "success_rate": _as_float(summary.get("success_rate")),
        "duration_mean_ms": _as_float(summary.get("duration_mean_ms") or summary.get("duration_mean")),
        "latency_p95_ms": _as_float(summary.get("latency_p95_ms") or summary.get("latency_p95")),
        "safety_violations": _as_int(summary.get("safety_violations") or summary.get("violations")),
        "time_to_success_mean_s": _as_float(
            summary.get("time_to_success_mean_s") or summary.get("time_to_success_mean")
        ),
        "num_episodes": _as_int(summary.get("num_episodes") or summary.get("episodes") or summary.get("n_episodes")),
    }


def _delta(a: Any, b: Any) -> Optional[float]:
    try:
        if a is None or b is None:
            return None
        return float(b) - float(a)
    except Exception:
        return None


# ----------------------
# UI formatting helpers
# ----------------------
def _to_iso(x: Any) -> Any:
    if isinstance(x, (datetime, date)):
        return x.isoformat()
    if isinstance(x, Decimal):
        return float(x)
    return x


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _json_safe(_to_iso(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(_to_iso(v)) for v in obj]
    return _to_iso(obj)


def _fmt(x: Any, digits: int = 3) -> str:
    if x is None:
        return "—"
    try:
        if isinstance(x, bool):
            return str(x)
        if isinstance(x, int):
            return str(x)
        if isinstance(x, float):
            return f"{x:.{digits}f}"
        return str(x)
    except Exception:
        return str(x)


def _delta_class(metric: str, delta: Optional[float]) -> str:
    if delta is None:
        return "delta-na"
    if abs(delta) < 1e-12:
        return "delta-zero"

    higher_better = {"success_rate"}
    lower_better = {"duration_mean_ms", "safety_violations", "time_to_success_mean_s"}

    if metric in higher_better:
        return "delta-good" if delta > 0 else "delta-bad"
    if metric in lower_better:
        return "delta-good" if delta < 0 else "delta-bad"
    return "delta-neutral"


def _parse_details(x: Any) -> dict:
    if x is None:
        return {}
    if isinstance(x, dict):
        return x
    if isinstance(x, str):
        try:
            v = json.loads(x)
            return v if isinstance(v, dict) else {}
        except Exception:
            return {}
    return {}


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

    return exec_returning(
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


@app.get("/models")
def list_models(tag: Optional[str] = None):
    if tag:
        return fetch_all(
            "SELECT * FROM models WHERE :tag = ANY(tags) ORDER BY created_at DESC",
            {"tag": tag},
        )
    return fetch_all("SELECT * FROM models ORDER BY created_at DESC", {})


# ----------------------
# Suites
# ----------------------
class SuiteCreate(BaseModel):
    name: str
    yaml_spec: str


@app.post("/suites")
def create_suite(payload: SuiteCreate):
    spec_hash = sha256_text(payload.yaml_spec)
    existing = fetch_one("SELECT id FROM suites WHERE hash=:h", {"h": spec_hash})
    if existing:
        return fetch_one("SELECT * FROM suites WHERE id=:id", {"id": existing["id"]})

    return exec_returning(
        """
        INSERT INTO suites (name, yaml_spec, hash)
        VALUES (:name, :yaml_spec, :hash)
        RETURNING id, name, hash, created_at
        """,
        {"name": payload.name, "yaml_spec": payload.yaml_spec, "hash": spec_hash},
    )


@app.get("/suites")
def list_suites():
    return fetch_all("SELECT id, name, hash, created_at FROM suites ORDER BY created_at DESC", {})


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
    hash: Optional[str] = None


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

    return exec_returning(
        """
        INSERT INTO datasets (name, version, uri, hash)
        VALUES (:name, :version, :uri, :hash)
        RETURNING id, name, version, uri, hash, created_at
        """,
        {"name": payload.name, "version": payload.version, "uri": payload.uri, "hash": ds_hash},
    )


@app.get("/datasets")
def list_datasets():
    return fetch_all("SELECT * FROM datasets ORDER BY created_at DESC", {})


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

    git_commit = get_git_commit()
    seed = make_seed()
    worker_version = WORKER_VERSION

    config_snapshot = None
    if payload.suite_id is not None:
        srow = fetch_one("SELECT yaml_spec FROM suites WHERE id=:id", {"id": payload.suite_id})
        if srow and srow.get("yaml_spec"):
            config_snapshot = json.dumps({"suite_yaml_spec": srow["yaml_spec"]})

    return exec_returning(
        """
        INSERT INTO runs (model_id, suite_id, dataset_id, backend, status,
                          git_commit, config_snapshot, seed, worker_version)
        VALUES (:model_id, :suite_id, :dataset_id, :backend, 'queued',
                :git_commit, CAST(:config_snapshot AS json), :seed, :worker_version)
        RETURNING id, model_id, suite_id, dataset_id, backend, status,
                  git_commit, config_snapshot, seed, worker_version, created_at
        """,
        {
            "model_id": payload.model_id,
            "suite_id": payload.suite_id,
            "dataset_id": payload.dataset_id,
            "backend": payload.backend,
            "git_commit": git_commit,
            "config_snapshot": config_snapshot,
            "seed": seed,
            "worker_version": worker_version,
        },
    )


@app.get("/runs")
def list_runs(limit: int = 50):
    rows = fetch_all(
        """
        SELECT
          r.*,
          m.name AS model_name,
          m.version AS model_version,
          ge.status AS gate_status,
          ge.created_at AS gate_created_at,
          ge.id AS gate_id
        FROM runs r
        JOIN models m ON m.id = r.model_id
        LEFT JOIN LATERAL (
          SELECT ge.status, ge.created_at, ge.id
          FROM gate_evaluations ge
          WHERE ge.candidate_run_id = r.id
          ORDER BY ge.created_at DESC
          LIMIT 1
        ) ge ON TRUE
        ORDER BY r.created_at DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )

    for r in rows:
        r.update(_dashboard_fields_from_summary(r.get("summary_json")))
        r["report_available"] = bool(r.get("report_uri"))
        r["report_link"] = f"/runs/{r['id']}/report" if r.get("report_uri") else None
        r["artifacts_link"] = f"/runs/{r['id']}/artifacts"
        r["episodes_link"] = f"/runs/{r['id']}/episodes"
        r["gate_link"] = f"/runs/{r['id']}/gate"

    return rows


# ----------------------
# API aliases (frontend uses /api/*)
# ----------------------

@app.get("/api/runs")
def api_list_runs(limit: int = 50):
    return list_runs(limit=limit)

@app.get("/api/runs/{run_id}")
def api_get_run(run_id: int):
    return get_run(run_id=run_id)

@app.get("/api/runs/{run_id}/report")
def api_open_report(run_id: int):
    return open_report(run_id=run_id)

@app.get("/api/runs/{run_id}/rollout")
def api_rollout(run_id: int):
    # Serve local rollout.mp4 from artifacts/<run_id>/rollout.mp4
    rel = f"{run_id}/rollout.mp4"
    path = _safe_join(ARTIFACTS_LOCAL_DIR, rel)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="rollout.mp4 not found")
    return FileResponse(path, media_type="video/mp4", filename="rollout.mp4")




@app.get("/runs/{run_id}")
def get_run(run_id: int):
    run = fetch_one(
        """
        SELECT
          r.*,
          m.name AS model_name,
          m.version AS model_version,
          ge.status AS gate_status,
          ge.created_at AS gate_created_at,
          ge.id AS gate_id
        FROM runs r
        JOIN models m ON m.id = r.model_id
        LEFT JOIN LATERAL (
          SELECT ge.status, ge.created_at, ge.id
          FROM gate_evaluations ge
          WHERE ge.candidate_run_id = r.id
          ORDER BY ge.created_at DESC
          LIMIT 1
        ) ge ON TRUE
        WHERE r.id = :id
        """,
        {"id": run_id},
    )
    if not run:
        raise HTTPException(status_code=404, detail="run not found")

    run.update(_dashboard_fields_from_summary(run.get("summary_json")))
    run["report_available"] = bool(run.get("report_uri"))
    run["report_link"] = f"/runs/{run_id}/report" if run.get("report_uri") else None
    run["artifacts_link"] = f"/runs/{run_id}/artifacts"
    run["episodes_link"] = f"/runs/{run_id}/episodes"
    run["gate_link"] = f"/runs/{run_id}/gate"
    return run


@app.get("/runs/{run_id}/episodes")
def get_run_episodes(run_id: int):
    return {"run_id": run_id, "episodes": list_run_episodes(run_id)}


@app.get("/runs/{run_id}/gate")
def get_latest_gate_for_run(run_id: int):
    row = fetch_one(
        """
        SELECT id, baseline_run_id, candidate_run_id, status, details_json, created_at
        FROM gate_evaluations
        WHERE candidate_run_id = :rid
        ORDER BY created_at DESC
        LIMIT 1
        """,
        {"rid": run_id},
    )
    if not row:
        return {"candidate_run_id": run_id, "status": None}
    return row


# ----------------------
# Compare (JSON)
# ----------------------
@app.get("/runs/compare")
def compare_runs(run_ids: str = Query(..., description="Comma-separated run IDs, e.g. 41,42")):
    ids = [int(x.strip()) for x in run_ids.split(",") if x.strip()]
    if not ids:
        return {"runs": [], "deltas": {}}

    runs = fetch_all(
        """
        SELECT id, model_id, suite_id, dataset_id, backend, status,
               started_at, ended_at, created_at, summary_json, report_uri, error_message
        FROM runs
        WHERE id = ANY(:ids)
        ORDER BY id ASC
        """,
        {"ids": ids},
    )

    eps = fetch_all(
        """
        SELECT run_id,
               COUNT(*) AS num_episodes,
               AVG( (metrics_json->>'duration_ms')::float ) AS duration_mean_ms,
               AVG( CASE WHEN (metrics_json->>'success')::boolean THEN 1.0 ELSE 0.0 END ) AS success_rate
        FROM episodes
        WHERE run_id = ANY(:ids)
        GROUP BY run_id
        """,
        {"ids": ids},
    )
    agg = {e["run_id"]: e for e in eps}

    out: List[Dict[str, Any]] = []
    for r in runs:
        a = agg.get(r["id"], {})
        sj = r.get("summary_json") or {}

        out.append(
            {
                "id": r["id"],
                "model_id": r["model_id"],
                "suite_id": r["suite_id"],
                "dataset_id": r["dataset_id"],
                "backend": r["backend"],
                "status": r["status"],
                "created_at": r["created_at"],
                "started_at": r["started_at"],
                "ended_at": r["ended_at"],
                "error_message": r["error_message"],
                "report_uri": r["report_uri"],
                "report_link": f"/runs/{r['id']}/report" if r.get("report_uri") else None,
                "episodes_link": f"/runs/{r['id']}/episodes",
                "artifacts_link": f"/runs/{r['id']}/artifacts",
                "num_episodes": int(a.get("num_episodes") or sj.get("num_episodes") or 0),
                "success_rate": a.get("success_rate", sj.get("success_rate")),
                "duration_mean_ms": a.get("duration_mean_ms", sj.get("duration_mean_ms")),
                "latency_p95_ms": sj.get("latency_p95_ms"),
                "safety_violations": sj.get("safety_violations"),
                "time_to_success_mean_s": sj.get("time_to_success_mean_s"),
            }
        )

    deltas: Dict[str, Any] = {}
    if len(out) >= 2:
        A = out[0]
        B = out[1]
        deltas = {
            "baseline": A["id"],
            "candidate": B["id"],
            "success_rate_delta": _delta(A.get("success_rate"), B.get("success_rate")),
            "duration_mean_ms_delta": _delta(A.get("duration_mean_ms"), B.get("duration_mean_ms")),
            "time_to_success_mean_s_delta": _delta(A.get("time_to_success_mean_s"), B.get("time_to_success_mean_s")),
            "safety_violations_delta": _delta(A.get("safety_violations"), B.get("safety_violations")),
        }

    return {"runs": out, "deltas": deltas}


# ----------------------
# Baselines + Gates (Phase 2.2)
# ----------------------
class BaselineLockCreate(BaseModel):
    suite_id: int
    dataset_id: int
    backend: Literal["mujoco", "real", "replay"] = "mujoco"
    baseline_run_id: int


class GateEvaluateCreate(BaseModel):
    suite_id: int
    dataset_id: int
    backend: Literal["mujoco", "real", "replay"] = "mujoco"
    candidate_run_id: int


@app.get("/baselines")
def list_baselines():
    return fetch_all(
        """
        SELECT bl.*, r.status AS baseline_status
        FROM baseline_locks bl
        LEFT JOIN runs r ON r.id = bl.baseline_run_id
        ORDER BY bl.created_at DESC
        """,
        {},
    )


@app.post("/baselines/lock")
def lock_baseline(payload: BaselineLockCreate):
    r = fetch_one("SELECT id, status FROM runs WHERE id=:id", {"id": payload.baseline_run_id})
    if not r:
        raise HTTPException(status_code=404, detail="baseline_run_id not found")

    existing = fetch_one(
        """
        SELECT id FROM baseline_locks
        WHERE suite_id=:suite_id AND dataset_id=:dataset_id AND backend=:backend
        """,
        {"suite_id": payload.suite_id, "dataset_id": payload.dataset_id, "backend": payload.backend},
    )

    if existing:
        return exec_returning(
            """
            UPDATE baseline_locks
            SET baseline_run_id=:baseline_run_id
            WHERE id=:id
            RETURNING id, suite_id, dataset_id, backend, baseline_run_id, created_at
            """,
            {"id": existing["id"], "baseline_run_id": payload.baseline_run_id},
        )

    return exec_returning(
        """
        INSERT INTO baseline_locks (suite_id, dataset_id, backend, baseline_run_id)
        VALUES (:suite_id, :dataset_id, :backend, :baseline_run_id)
        RETURNING id, suite_id, dataset_id, backend, baseline_run_id, created_at
        """,
        {
            "suite_id": payload.suite_id,
            "dataset_id": payload.dataset_id,
            "backend": payload.backend,
            "baseline_run_id": payload.baseline_run_id,
        },
    )


def _pick_kpis(run_row: dict) -> dict:
    sj = run_row.get("summary_json") or {}
    k = _dashboard_fields_from_summary(sj)
    return {
        "success_rate": k.get("success_rate"),
        "duration_mean_ms": k.get("duration_mean_ms"),
        "safety_violations": k.get("safety_violations"),
        "time_to_success_mean_s": k.get("time_to_success_mean_s"),
        "num_episodes": k.get("num_episodes"),
    }


def _gate_decision(baseline: dict, cand: dict) -> Tuple[str, dict]:
    tol_success = 0.0
    tol_dur_ms = 0.0

    b = _pick_kpis(baseline)
    c = _pick_kpis(cand)

    reasons: List[str] = []
    passed = True

    if b["success_rate"] is not None and c["success_rate"] is not None:
        if c["success_rate"] < (b["success_rate"] - tol_success):
            passed = False
            reasons.append(f"success_rate regressed: {c['success_rate']} < {b['success_rate']} - {tol_success}")

    if b["duration_mean_ms"] is not None and c["duration_mean_ms"] is not None:
        if c["duration_mean_ms"] > (b["duration_mean_ms"] + tol_dur_ms):
            passed = False
            reasons.append(
                f"duration_mean_ms regressed: {c['duration_mean_ms']} > {b['duration_mean_ms']} + {tol_dur_ms}"
            )

    if b["safety_violations"] is not None and c["safety_violations"] is not None:
        if c["safety_violations"] > b["safety_violations"]:
            passed = False
            reasons.append(f"safety_violations regressed: {c['safety_violations']} > {b['safety_violations']}")

    details = {
        "baseline_run_id": baseline["id"],
        "candidate_run_id": cand["id"],
        "baseline_kpis": b,
        "candidate_kpis": c,
        "deltas": {
            "success_rate": _delta(b["success_rate"], c["success_rate"]),
            "duration_mean_ms": _delta(b["duration_mean_ms"], c["duration_mean_ms"]),
            "safety_violations": _delta(b["safety_violations"], c["safety_violations"]),
            "time_to_success_mean_s": _delta(b["time_to_success_mean_s"], c["time_to_success_mean_s"]),
        },
        "reasons": reasons,
        "thresholds": {"tol_success": tol_success, "tol_dur_ms": tol_dur_ms},
    }
    return ("pass" if passed else "fail"), details


@app.get("/gates")
def list_gates(limit: int = 50):
    return fetch_all(
        """
        SELECT *
        FROM gate_evaluations
        ORDER BY created_at DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )
@app.get("/gates/{gate_id}")
def get_gate(gate_id: int):
    row = fetch_one(
        """
        SELECT id, baseline_run_id, candidate_run_id, status, details_json, created_at
        FROM gate_evaluations
        WHERE id = :id
        """,
        {"id": gate_id},
    )
    if not row:
        raise HTTPException(status_code=404, detail="gate not found")
    return row


# OPTIONAL convenience wrappers (only if your frontend calls /api/* directly)
@app.get("/api/gates")
def api_list_gates(limit: int = 50):
    return list_gates(limit=limit)

@app.get("/api/gates/{gate_id}")
def api_get_gate(gate_id: int):
    return get_gate(gate_id=gate_id)


@app.post("/gates/evaluate")
def evaluate_gate(payload: GateEvaluateCreate):
    # 0) If we already have a gate for this candidate, return the latest one (idempotent)
    existing = fetch_one(
        """
        SELECT *
        FROM gate_evaluations
        WHERE candidate_run_id = :rid
        ORDER BY created_at DESC
        LIMIT 1
        """,
        {"rid": payload.candidate_run_id},
    )
    if existing:
        return existing

    # 1) Find baseline lock
    lock = fetch_one(
        """
        SELECT *
        FROM baseline_locks
        WHERE suite_id=:suite_id AND dataset_id=:dataset_id AND backend=:backend
        """,
        {"suite_id": payload.suite_id, "dataset_id": payload.dataset_id, "backend": payload.backend},
    )
    if not lock:
        raise HTTPException(status_code=404, detail="No baseline lock found for this suite/dataset/backend")

    # 2) Load baseline + candidate runs (need summary_json)
    baseline = fetch_one(
        "SELECT id, status, summary_json FROM runs WHERE id=:id",
        {"id": lock["baseline_run_id"]},
    )
    if not baseline:
        raise HTTPException(status_code=404, detail="baseline_run_id missing in runs")

    cand = fetch_one(
        "SELECT id, status, summary_json FROM runs WHERE id=:id",
        {"id": payload.candidate_run_id},
    )
    if not cand:
        raise HTTPException(status_code=404, detail="candidate_run_id not found")

    # Optional: only evaluate completed runs (avoids nonsense gates)
    if (cand.get("status") or "").lower() != "completed":
        raise HTTPException(status_code=409, detail="candidate run is not completed")

    # 3) Decide pass/fail + details
    status, details = _gate_decision(baseline, cand)

    # 4) Insert gate evaluation (FIXED INDENTATION)
    row = exec_returning(
        """
        INSERT INTO gate_evaluations
          (baseline_run_id, candidate_run_id, status, details_json)
        VALUES
          (:baseline_run_id, :candidate_run_id, :status, CAST(:details AS jsonb))
        ON CONFLICT (baseline_run_id, candidate_run_id)
        DO UPDATE SET
          status = EXCLUDED.status,
          details_json = EXCLUDED.details_json,
          created_at = NOW()
        RETURNING *
        """,
        {
            "baseline_run_id": lock["baseline_run_id"],
            "candidate_run_id": payload.candidate_run_id,
            "status": status,
            "details": json.dumps(details),
        },
    )
    return row


@app.get("/gate-evaluations/by-run/{candidate_run_id}")
def gate_by_run(candidate_run_id: int):
    row = fetch_one(
        """
        SELECT *
        FROM gate_evaluations
        WHERE candidate_run_id = :rid
        ORDER BY created_at DESC
        LIMIT 1
        """,
        {"rid": candidate_run_id},
    )
    if not row:
        return {"candidate_run_id": candidate_run_id, "status": None}
    return row


# ----------------------
# Phase 2.4 Step 1: CI "ship" decision
# ----------------------
@app.get("/ship/decision")
def ship_decision(
    run_id: int = Query(..., description="Candidate run id"),
    strict: bool = Query(False, description="If true: treat missing gate as BLOCK instead of PENDING"),
):
    """
    CI-style decision API.

    - If run not completed => PENDING (or BLOCK if strict)
    - If missing gate      => PENDING (or BLOCK if strict)
    - gate pass            => SHIP
    - gate fail            => BLOCK
    - else                 => PENDING
    """
    run = fetch_one(
        """
        SELECT id, status, model_id, suite_id, dataset_id, backend, created_at
        FROM runs
        WHERE id = :id
        """,
        {"id": run_id},
    )
    if not run:
        raise HTTPException(status_code=404, detail="run not found")

    run_status = (run.get("status") or "").lower()
    if run_status != "completed":
        return {
            "decision": "BLOCK" if strict else "PENDING",
            "reason": "run_not_completed",
            "candidate_run_id": run_id,
            "candidate_run_status": run.get("status"),
            "gate_status": None,
            "gate_id": None,
            "gate_created_at": None,
            "baseline_run_id": None,
            "compare_link": None,
            "gate_link": f"/runs/{run_id}/gate",
        }

    gate = fetch_one(
        """
        SELECT id, baseline_run_id, candidate_run_id, status, details_json, created_at
        FROM gate_evaluations
        WHERE candidate_run_id = :rid
        ORDER BY created_at DESC
        LIMIT 1
        """,
        {"rid": run_id},
    )

    if not gate or not gate.get("status"):
        return {
            "decision": "BLOCK" if strict else "PENDING",
            "reason": "missing_gate",
            "candidate_run_id": run_id,
            "candidate_run_status": run.get("status"),
            "gate_status": None,
            "gate_id": None,
            "gate_created_at": None,
            "baseline_run_id": None,
            "compare_link": None,
            "gate_link": f"/runs/{run_id}/gate",
        }

    gate_status = (gate.get("status") or "").lower()

    if gate_status == "pass":
        decision = "SHIP"
        decision_reason = None
    elif gate_status == "fail":
        decision = "BLOCK"
        decision_reason = "gate_failed"
    else:
        decision = "PENDING"
        decision_reason = "unknown_gate_status"

    reason_detail = None
    details = gate.get("details_json") or {}
    if isinstance(details, dict):
        reasons = details.get("reasons") or []
        if reasons:
            reason_detail = str(reasons[0])

    baseline_run_id = gate.get("baseline_run_id")
    compare_link = (
        f"/ui/compare?run_ids={baseline_run_id},{run_id}&a={baseline_run_id}&b={run_id}" if baseline_run_id else None
    )

    return {
        "decision": decision,
        "reason": reason_detail or decision_reason,
        "candidate_run_id": run_id,
        "candidate_run_status": run.get("status"),
        "gate_status": gate_status,
        "gate_id": gate.get("id"),
        "gate_created_at": gate.get("created_at"),
        "baseline_run_id": baseline_run_id,
        "compare_link": compare_link,
        "gate_link": f"/runs/{run_id}/gate",
    }

# ----------------------
# Release Decision APIs (Home page)
# ----------------------

class ReleaseLatestQuery(BaseModel):
    suite_id: int
    dataset_id: int
    backend: Literal["mujoco", "real", "replay"] = "mujoco"


def _kpi_delta_pack(baseline_summary: Any, cand_summary: Any) -> Dict[str, Any]:
    b = _dashboard_fields_from_summary(baseline_summary or {})
    c = _dashboard_fields_from_summary(cand_summary or {})

    def pack(metric: str):
        bv = b.get(metric)
        cv = c.get(metric)
        return {"baseline": bv, "candidate": cv, "delta": _delta(bv, cv)}

    return {
        "success_rate": pack("success_rate"),
        "duration_mean_ms": pack("duration_mean_ms"),
        "safety_violations": pack("safety_violations"),
        "time_to_success_mean_s": pack("time_to_success_mean_s"),
        "num_episodes": pack("num_episodes"),
    }


@app.get("/api/releases/latest")
def api_latest_release_decision(
    suite_id: int = Query(...),
    dataset_id: int = Query(...),
    backend: Literal["mujoco", "real", "replay"] = Query("mujoco"),
    include_runs: bool = Query(True),
):
    """
    Latest release decision for a (suite_id, dataset_id, backend) context.

    Logic:
    1) Find baseline lock for context
    2) Find latest gate evaluation for that baseline_run_id
    3) Return decision + candidate/baseline run info + KPI deltas

    If baseline lock exists but no gate yet => gate=null, decision="PENDING"
    If no baseline lock => 404
    """
    lock = fetch_one(
        """
        SELECT id, suite_id, dataset_id, backend, baseline_run_id, created_at
        FROM baseline_locks
        WHERE suite_id=:suite_id AND dataset_id=:dataset_id AND backend=:backend
        LIMIT 1
        """,
        {"suite_id": suite_id, "dataset_id": dataset_id, "backend": backend},
    )
    if not lock:
        raise HTTPException(
            status_code=404,
            detail=f"No baseline lock for suite_id={suite_id} dataset_id={dataset_id} backend={backend}",
        )

    baseline_run_id = lock["baseline_run_id"]

    gate = fetch_one(
        """
        SELECT id, baseline_run_id, candidate_run_id, status, details_json, created_at
        FROM gate_evaluations
        WHERE baseline_run_id = :bid
        ORDER BY created_at DESC
        LIMIT 1
        """,
        {"bid": baseline_run_id},
    )

    # baseline run (needed for kpi deltas)
    baseline_run = fetch_one(
        """
        SELECT id, status, created_at, started_at, ended_at, summary_json
        FROM runs
        WHERE id=:id
        """,
        {"id": baseline_run_id},
    )

    candidate_run = None
    if gate and gate.get("candidate_run_id"):
        candidate_run = fetch_one(
            """
            SELECT id, status, created_at, started_at, ended_at, summary_json
            FROM runs
            WHERE id=:id
            """,
            {"id": gate["candidate_run_id"]},
        )

    # Decision mapping for homepage
    decision = "PENDING"
    if gate and gate.get("status"):
        gs = (gate.get("status") or "").lower()
        if gs == "pass":
            decision = "SHIP"
        elif gs == "fail":
            decision = "BLOCK"

    # KPI deltas (only if we have both)
    kpi = None
    if baseline_run and candidate_run:
        kpi = _kpi_delta_pack(baseline_run.get("summary_json"), candidate_run.get("summary_json"))

    out = {
        "suite_id": suite_id,
        "dataset_id": dataset_id,
        "backend": backend,
        "baseline_run_id": baseline_run_id,
        "decision": decision,
        "gate": None if not gate else {
            "gate_id": gate.get("id"),
            "status": gate.get("status"),
            "created_at": gate.get("created_at"),
            "candidate_run_id": gate.get("candidate_run_id"),
            "baseline_run_id": gate.get("baseline_run_id"),
            "details_json": gate.get("details_json"),
        },
        "kpi": kpi,
        "links": {
            "baseline_run": f"/runs/{baseline_run_id}",
            "candidate_run": f"/runs/{gate['candidate_run_id']}" if gate and gate.get("candidate_run_id") else None,
            "gate": f"/gates/{gate['id']}" if gate and gate.get("id") else None,
            "compare": (
                f"/ui/compare?run_ids={baseline_run_id},{gate['candidate_run_id']}&a={baseline_run_id}&b={gate['candidate_run_id']}"
                if gate and gate.get("candidate_run_id") else None
            ),
        },
    }

    if include_runs:
        out["baseline"] = baseline_run
        out["candidate"] = candidate_run

    return out


@app.get("/api/releases")
def api_list_release_decisions(
    suite_id: int = Query(...),
    dataset_id: int = Query(...),
    backend: Literal["mujoco", "real", "replay"] = Query("mujoco"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    History list for dropdown: gate evaluations under the baseline lock for this context.
    """
    lock = fetch_one(
        """
        SELECT baseline_run_id
        FROM baseline_locks
        WHERE suite_id=:suite_id AND dataset_id=:dataset_id AND backend=:backend
        LIMIT 1
        """,
        {"suite_id": suite_id, "dataset_id": dataset_id, "backend": backend},
    )
    if not lock:
        return {"items": [], "suite_id": suite_id, "dataset_id": dataset_id, "backend": backend}

    rows = fetch_all(
        """
        SELECT id AS gate_id, status, created_at, baseline_run_id, candidate_run_id
        FROM gate_evaluations
        WHERE baseline_run_id = :bid
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
        """,
        {"bid": lock["baseline_run_id"], "limit": limit, "offset": offset},
    )
    return {"items": rows, "suite_id": suite_id, "dataset_id": dataset_id, "backend": backend}

# ----------------------
# Report resolver
# ----------------------
@app.get("/runs/{run_id}/report")
def open_report(run_id: int):
    run = fetch_one("SELECT id, report_uri FROM runs WHERE id=:id", {"id": run_id})
    if not run:
        raise HTTPException(status_code=404, detail="run not found")

    uri = (run.get("report_uri") or "").strip()

    # fallback: if report_uri missing, try local artifacts/<run_id>/report.html
    if not uri:
        fallback = _safe_join(ARTIFACTS_LOCAL_DIR, f"{run_id}/report.html")
        if os.path.exists(fallback):
            return FileResponse(fallback, media_type="text/html", filename="report.html")
        raise HTTPException(status_code=404, detail="report missing (no report_uri and no local report.html)")

    if uri.startswith("http://") or uri.startswith("https://"):
        return RedirectResponse(uri)

    if uri.startswith("s3://"):
        try:
            url = presign_s3_get(uri, expires_seconds=3600)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"failed to presign report: {e}")
        return RedirectResponse(url)

    if uri.startswith("file://"):
        path = uri.replace("file://", "", 1)
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="report file not found")
        return FileResponse(path, media_type="text/html", filename="report.html")

    try:
        local_path = _safe_join(ARTIFACTS_LOCAL_DIR, uri)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid report_uri path")

    if not os.path.exists(local_path):
        raise HTTPException(status_code=404, detail="report file not found")

    return FileResponse(local_path, media_type="text/html", filename="report.html")



# ----------------------
# Artifact listing & downloads
# ----------------------
@app.get("/runs/{run_id}/artifacts")
def list_run_artifacts(run_id: int):
    run = fetch_one("SELECT id, report_uri FROM runs WHERE id=:id", {"id": run_id})
    if not run:
        raise HTTPException(status_code=404, detail="run not found")

    artifacts: List[Dict[str, Any]] = []

    if run.get("report_uri"):
        artifacts.append(
            {
               "name": "report",
               "uri": run["report_uri"],
               "content_type": "text/html",
               "open": f"/runs/{run_id}/report",
        }

        )

    run_dir = os.path.join(ARTIFACTS_LOCAL_DIR, str(run_id))

    if os.path.isdir(run_dir):
        for fname in sorted(os.listdir(run_dir)):
            if fname == "report.html" and run.get("report_uri"):
                continue
            fpath = os.path.join(run_dir, fname)
            if os.path.isfile(fpath):
                artifacts.append(
                    {
                        "name": fname,
                        "uri": f"/runs/{run_id}/artifacts/{fname}",

                        "content_type": _media_type_for_name(fname),
                        "size_bytes": os.path.getsize(fpath),
                        "download": f"/runs/{run_id}/artifacts/{fname}",
                    }
                )

    return {"run_id": run_id, "artifacts": artifacts}
@app.get("/runs/{run_id}/rollout")
def rollout_alias(run_id: int):
    return api_rollout(run_id=run_id)


@app.get("/runs/{run_id}/artifacts/{name:path}")
def download_artifact(run_id: int, name: str):
    run = fetch_one("SELECT id, report_uri FROM runs WHERE id=:id", {"id": run_id})
    if not run:
        raise HTTPException(status_code=404, detail="run not found")

    report_uri = (run.get("report_uri") or "").strip()

    if report_uri.startswith("s3://"):
        bucket, report_key = parse_s3_uri(report_uri)
        prefix = report_key.rsplit("/", 1)[0]
        key = f"{prefix}/{name}"
        s3 = minio_client()
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=3600,
        )
        return RedirectResponse(url)

    rel = f"{run_id}/{name}"

    path = _safe_join(ARTIFACTS_LOCAL_DIR, rel)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path, media_type=_media_type_for_name(name), filename=name)


# ----------------------
# UI: Compare runs
# ----------------------
@app.get("/ui/compare", response_class=HTMLResponse)
def ui_compare(
    run_ids: str = Query(..., description="Comma-separated run IDs, e.g. 41,42"),
    a: Optional[int] = Query(None),
    b: Optional[int] = Query(None),
):
    payload = compare_runs(run_ids=run_ids)
    runs = payload.get("runs", [])

    if not runs:
        return HTMLResponse("<h1>No runs found</h1>", status_code=404)

    ids = [r["id"] for r in runs]
    if a not in ids:
        a = ids[0]
    if b not in ids:
        b = ids[1] if len(ids) > 1 else ids[0]

    runA = next((r for r in runs if r["id"] == a), None)
    runB = next((r for r in runs if r["id"] == b), None)

    metrics = ["success_rate", "duration_mean_ms", "safety_violations", "time_to_success_mean_s"]

    deltas = []
    for m in metrics:
        va = runA.get(m) if runA else None
        vb = runB.get(m) if runB else None
        d = None
        try:
            if va is not None and vb is not None:
                d = float(vb) - float(va)
        except Exception:
            d = None
        deltas.append((m, va, vb, d))

    def links_html(rid: int) -> str:
        return (
            f'<a class="btn" href="/runs/{rid}/report" target="_blank">Open report</a> '
            f'<a class="btn btn2" href="/runs/{rid}/episodes" target="_blank">Episodes JSON</a> '
            f'<a class="btn btn2" href="/runs/{rid}/artifacts" target="_blank">Artifacts JSON</a>'
        )

    runs_rows = ""
    for r in runs:
        runs_rows += f"""
        <tr>
          <td>{r["id"]}</td>
          <td><b>{r.get("status","")}</b></td>
          <td>{r.get("backend","")}</td>
          <td>{_fmt(r.get("success_rate"))}</td>
          <td>{_fmt(r.get("duration_mean_ms"))}</td>
          <td>{_fmt(r.get("safety_violations"))}</td>
          <td>{_fmt(r.get("time_to_success_mean_s"))}</td>
          <td>{links_html(r["id"])}</td>
        </tr>
        """

    opts = "\n".join([f'<option value="{rid}">{rid}</option>' for rid in ids])

    delta_rows = ""
    for (m, va, vb, d) in deltas:
        cls = _delta_class(m, d)
        delta_rows += f"""
        <tr>
          <td>{m}</td>
          <td>{_fmt(va)}</td>
          <td>{_fmt(vb)}</td>
          <td class="{cls}">{_fmt(d, digits=3)}</td>
        </tr>
        """

    dbg = json.dumps(_json_safe(payload), indent=2)

    html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8" />
      <title>Compare runs</title>
      <style>
        body {{ font-family: Arial, sans-serif; margin: 24px; background: #0b0f19; color: #e6e6e6; }}
        h1 {{ margin: 0 0 6px; }}
        .sub {{ color:#aab; margin-bottom: 16px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ border-bottom: 1px solid #222; padding: 10px; vertical-align: top; }}
        th {{ text-align: left; color: #b8c0ff; }}
        .btn {{
          display: inline-block; padding: 6px 10px; border: 1px solid #3a4;
          border-radius: 6px; color: #dff; text-decoration: none; margin-right: 6px;
        }}
        .btn:hover {{ background: #163; }}
        .btn2 {{ border-color: #446; color: #dde; }}
        .btn2:hover {{ background: #224; }}
        .panel {{ margin-top: 18px; padding: 12px; border: 1px solid #222; border-radius: 10px; background: #0e1322; }}
        .row {{ display:flex; gap:12px; align-items:center; flex-wrap:wrap; }}
        select, input {{
          background:#0b0f19; color:#e6e6e6; border:1px solid #223; border-radius: 8px; padding: 6px 8px;
        }}
        code {{ color:#b8c0ff; }}
        pre {{ margin: 0; white-space: pre-wrap; word-break: break-word; }}
        .delta-good {{ color: #7CFC9A; font-weight: 700; }}
        .delta-bad {{ color: #FF7A7A; font-weight: 700; }}
        .delta-zero {{ color: #cbd5e1; font-weight: 700; }}
        .delta-na {{ color: #94a3b8; }}
        .delta-neutral {{ color: #e2e8f0; }}
        .hint {{ color:#94a3b8; font-size: 12px; }}
      </style>
    </head>
    <body>
      <h1>Compare runs</h1>
      <div class="sub">Run IDs: <code>{run_ids}</code></div>

      <div class="panel">
        <form method="get" class="row">
          <div>
            <div class="hint">run_ids</div>
            <input name="run_ids" value="{run_ids}" style="min-width:220px;" />
          </div>

          <div>
            <div class="hint">Run A</div>
            <select name="a" onchange="this.form.submit()">
              {opts}
            </select>
          </div>

          <div>
            <div class="hint">Run B</div>
            <select name="b" onchange="this.form.submit()">
              {opts}
            </select>
          </div>

          <div style="margin-top:18px;">
            <button class="btn" type="submit">Compare</button>
            <a class="btn btn2" href="/runs/compare?run_ids={run_ids}" target="_blank">Open JSON</a>
          </div>
        </form>

        <script>
          (function() {{
            const a = "{a}";
            const b = "{b}";
            const selA = document.querySelector('select[name="a"]');
            const selB = document.querySelector('select[name="b"]');
            if (selA) selA.value = a;
            if (selB) selB.value = b;
          }})();
        </script>
      </div>

      <h2 style="margin-top:18px;">Runs</h2>
      <table>
        <thead>
          <tr>
            <th>ID</th><th>Status</th><th>Backend</th>
            <th>success_rate</th><th>duration_mean_ms</th><th>safety_violations</th><th>time_to_success_mean_s</th>
            <th>Links</th>
          </tr>
        </thead>
        <tbody>
          {runs_rows}
        </tbody>
      </table>

      <h2 style="margin-top:18px;">Delta (Run {b} − Run {a})</h2>
      <table>
        <thead>
          <tr>
            <th>Metric</th><th>Run A</th><th>Run B</th><th>Δ</th>
          </tr>
        </thead>
        <tbody>
          {delta_rows}
        </tbody>
      </table>

      <details style="margin-top:16px;">
        <summary style="cursor:pointer;color:#b8c0ff;">Raw payload (debug)</summary>
        <pre class="panel">{dbg}</pre>
      </details>
    </body>
    </html>
    """
    return HTMLResponse(html)


# ----------------------
# UI: Gates overview page
# ----------------------
@app.get("/ui/gates", response_class=HTMLResponse)
def ui_gates(limit: int = 50):
    gates = fetch_all(
        """
        SELECT
          ge.id,
          ge.created_at,
          ge.status,
          ge.baseline_run_id,
          ge.candidate_run_id,
          ge.details_json,

          rb.status AS baseline_status,
          rc.status AS candidate_status,

          mb.name AS baseline_model_name,
          mb.version AS baseline_model_version,
          mc.name AS candidate_model_name,
          mc.version AS candidate_model_version

        FROM gate_evaluations ge
        LEFT JOIN runs rb ON rb.id = ge.baseline_run_id
        LEFT JOIN runs rc ON rc.id = ge.candidate_run_id
        LEFT JOIN models mb ON mb.id = rb.model_id
        LEFT JOIN models mc ON mc.id = rc.model_id

        ORDER BY ge.created_at DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )

    rows_html = ""
    for g in gates:
        gid = g["id"]
        created = g.get("created_at") or ""
        status = (g.get("status") or "").lower()

        baseline_id = g.get("baseline_run_id")
        candidate_id = g.get("candidate_run_id")

        if status == "pass":
            badge = '<span class="badge pass">PASS</span>'
        elif status == "fail":
            badge = '<span class="badge fail">FAIL</span>'
        else:
            badge = '<span class="badge na">—</span>'

        details = _parse_details(g.get("details_json"))
        deltas = details.get("deltas") or {}
        reasons = details.get("reasons") or []
        reason_preview = str(reasons[0]) if reasons else ""

        d_success = deltas.get("success_rate")
        d_dur = deltas.get("duration_mean_ms")
        d_safety = deltas.get("safety_violations")

        compare_link = (
            f"/ui/compare?run_ids={baseline_id},{candidate_id}&a={baseline_id}&b={candidate_id}"
            if baseline_id and candidate_id
            else ""
        )

        gate_ui_link = f"/ui/gate?gate_id={gid}"
        gate_json_link = f"/runs/{candidate_id}/gate" if candidate_id else None
        baseline_run_link = f"/runs/{baseline_id}" if baseline_id else None
        candidate_run_link = f"/runs/{candidate_id}" if candidate_id else None

        rows_html += f"""
        <tr>
          <td>{gid}</td>
          <td>{created}</td>
          <td>{badge}</td>

          <td>
            <div><span class="k">run</span> {baseline_id or "—"}</div>
            <div class="muted">{(g.get("baseline_model_name") or "—")} {(g.get("baseline_model_version") or "")}</div>
            <div class="muted"><span class="k">status</span> {g.get("baseline_status") or "—"}</div>
          </td>

          <td>
            <div><span class="k">run</span> {candidate_id or "—"}</div>
            <div class="muted">{(g.get("candidate_model_name") or "—")} {(g.get("candidate_model_version") or "")}</div>
            <div class="muted"><span class="k">status</span> {g.get("candidate_status") or "—"}</div>
          </td>

          <td class="kpi">
            <div><span class="k">Δ success</span> {_fmt(_as_float(d_success), digits=3)}</div>
            <div><span class="k">Δ dur ms</span> {_fmt(_as_float(d_dur), digits=3)}</div>
            <div><span class="k">Δ safety</span> {_fmt(_as_float(d_safety), digits=3)}</div>
            <div class="muted"><span class="k">reason</span> {reason_preview or "—"}</div>
          </td>

          <td>
            <a class="btn" href="{gate_ui_link}" target="_blank">Gate UI</a>
            {f'<a class="btn btn2" href="{gate_json_link}" target="_blank">Gate JSON</a>' if gate_json_link else ""}
            {f'<a class="btn btn2" href="{baseline_run_link}" target="_blank">Baseline Run</a>' if baseline_run_link else ""}
            {f'<a class="btn btn2" href="{candidate_run_link}" target="_blank">Candidate Run</a>' if candidate_run_link else ""}
            {f'<a class="btn btn2" href="{compare_link}" target="_blank">Compare</a>' if compare_link else ""}
          </td>
        </tr>
        """

    html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8" />
      <title>robot-eval-platform — Gates</title>
      <style>
        body {{ font-family: Arial, sans-serif; margin: 24px; background: #0b0f19; color: #e6e6e6; }}
        h1 {{ margin: 0 0 10px; }}
        .sub {{ color:#aab; margin-bottom: 14px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ border-bottom: 1px solid #222; padding: 10px; vertical-align: top; }}
        th {{ text-align: left; color: #b8c0ff; }}
        .muted {{ color: #94a3b8; font-size: 12px; margin-top: 4px; }}
        .kpi {{ min-width: 260px; }}
        .k {{ color: #b8c0ff; display: inline-block; width: 90px; }}
        .btn {{
          display: inline-block; padding: 6px 10px; border: 1px solid #3a4;
          border-radius: 6px; color: #dff; text-decoration: none; margin-right: 6px; margin-bottom: 6px;
        }}
        .btn:hover {{ background: #163; }}
        .btn2 {{ border-color: #446; color: #dde; }}
        .btn2:hover {{ background: #224; }}
        .badge {{ padding: 3px 8px; border-radius: 999px; font-weight: 800; font-size: 12px; }}
        .pass {{ background: #123d2a; color: #7CFC9A; border: 1px solid #1f6f44; }}
        .fail {{ background: #3d1212; color: #FF7A7A; border: 1px solid #6f1f1f; }}
        .na   {{ background: #111827; color: #94a3b8; border: 1px solid #223; }}
      </style>
    </head>
    <body>
      <h1>Gates</h1>
      <div class="sub">
        Latest {limit} gate evaluations (baseline vs candidate).
        PASS = no regression. FAIL = regression detected.
      </div>
      <div style="margin-bottom:12px;">
        <a class="btn btn2" href="/ui/runs">Back to Runs</a>
      </div>

      <table>
        <thead>
          <tr>
            <th>Gate ID</th><th>Created</th><th>Status</th>
            <th>Baseline</th><th>Candidate</th><th>Delta preview</th><th>Links</th>
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


# ----------------------
# UI: Single gate detail page (FIXED: endpoint exists)
# ----------------------
@app.get("/ui/gate", response_class=HTMLResponse)
def ui_gate(gate_id: int = Query(...)):
    g = fetch_one(
        """
        SELECT
          ge.*,

          rb.status AS baseline_status,
          rc.status AS candidate_status,

          mb.name AS baseline_model_name,
          mb.version AS baseline_model_version,
          mc.name AS candidate_model_name,
          mc.version AS candidate_model_version

        FROM gate_evaluations ge
        LEFT JOIN runs rb ON rb.id = ge.baseline_run_id
        LEFT JOIN runs rc ON rc.id = ge.candidate_run_id
        LEFT JOIN models mb ON mb.id = rb.model_id
        LEFT JOIN models mc ON mc.id = rc.model_id
        WHERE ge.id = :id
        """,
        {"id": gate_id},
    )
    if not g:
        return HTMLResponse("<h1>Gate not found</h1>", status_code=404)

    status = (g.get("status") or "").lower()
    if status == "pass":
        badge = '<span class="badge pass">PASS</span>'
    elif status == "fail":
        badge = '<span class="badge fail">FAIL</span>'
    else:
        badge = '<span class="badge na">—</span>'

    baseline_id = g.get("baseline_run_id")
    candidate_id = g.get("candidate_run_id")

    compare_link = (
        f"/ui/compare?run_ids={baseline_id},{candidate_id}&a={baseline_id}&b={candidate_id}"
        if baseline_id and candidate_id
        else None
    )

    details = _parse_details(g.get("details_json"))
    dbg = json.dumps(_json_safe(details), indent=2)

    html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8" />
      <title>Gate {gate_id}</title>
      <style>
        body {{ font-family: Arial, sans-serif; margin: 24px; background: #0b0f19; color: #e6e6e6; }}
        .panel {{ margin-top: 14px; padding: 12px; border: 1px solid #222; border-radius: 10px; background: #0e1322; }}
        a {{ color: #b8c0ff; }}
        pre {{ white-space: pre-wrap; word-break: break-word; margin: 0; }}
        .badge {{ padding: 3px 8px; border-radius: 999px; font-weight: 800; font-size: 12px; }}
        .pass {{ background: #123d2a; color: #7CFC9A; border: 1px solid #1f6f44; }}
        .fail {{ background: #3d1212; color: #FF7A7A; border: 1px solid #6f1f1f; }}
        .na   {{ background: #111827; color: #94a3b8; border: 1px solid #223; }}
        .muted {{ color:#94a3b8; font-size: 12px; }}
        .k {{ color:#b8c0ff; }}
        .btn {{
          display: inline-block; padding: 6px 10px; border: 1px solid #3a4;
          border-radius: 6px; color: #dff; text-decoration: none; margin-right: 6px; margin-bottom: 6px;
        }}
        .btn:hover {{ background: #163; }}
        .btn2 {{ border-color: #446; color: #dde; }}
        .btn2:hover {{ background: #224; }}
      </style>
    </head>
    <body>
      <h1>Gate {gate_id} {badge}</h1>

      <div class="panel">
        <div><span class="k">Baseline</span>: run {baseline_id or "—"} — {(g.get("baseline_model_name") or "—")} {(g.get("baseline_model_version") or "")}</div>
        <div class="muted">status: {g.get("baseline_status") or "—"}</div>

        <div style="margin-top:10px;"><span class="k">Candidate</span>: run {candidate_id or "—"} — {(g.get("candidate_model_name") or "—")} {(g.get("candidate_model_version") or "")}</div>
        <div class="muted">status: {g.get("candidate_status") or "—"}</div>

        <div style="margin-top:12px;">
          <a class="btn btn2" href="/ui/gates">Back to Gates</a>
          <a class="btn btn2" href="/ui/runs">Back to Runs</a>
          {f'<a class="btn" href="{compare_link}" target="_blank">Open compare</a>' if compare_link else ""}
        </div>
      </div>

      <h2 style="margin-top:16px;">Details (debug JSON)</h2>
      <pre class="panel">{dbg}</pre>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


# ----------------------
# UI: Runs (single definitive endpoint — FIXED duplicate)
# ----------------------
@app.get("/ui/runs", response_class=HTMLResponse)
def ui_runs(limit: int = 50):
    runs = fetch_all(
        """
        SELECT
          r.id, r.backend, r.status, r.created_at,
          r.report_uri, r.summary_json, r.error_message,
          r.git_commit, r.seed, r.worker_version,

          ge.id AS gate_id,
          ge.status AS gate_status,
          ge.created_at AS gate_created_at,
          ge.baseline_run_id AS gate_baseline_run_id

        FROM runs r
        LEFT JOIN LATERAL (
          SELECT id, status, created_at, baseline_run_id
          FROM gate_evaluations
          WHERE candidate_run_id = r.id
          ORDER BY created_at DESC
          LIMIT 1
        ) ge ON TRUE

        ORDER BY r.id DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )

    def _gate_badge(gs: Optional[str]) -> str:
        gs = (gs or "").lower()
        if gs == "pass":
            return '<span class="badge pass">PASS</span>'
        if gs == "fail":
            return '<span class="badge fail">FAIL</span>'
        return '<span class="badge na">—</span>'

    def _ship_decision(run_status: Optional[str], gate_status: Optional[str]) -> Tuple[str, str]:
        rs = (run_status or "").lower()
        gs = (gate_status or "").lower()

        if rs != "completed":
            return ("PENDING", "pending")

        if gs == "pass":
            return ("SHIP", "ship")
        if gs == "fail":
            return ("BLOCK", "block")

        return ("PENDING", "pending")

    rows_html = ""
    for r in runs:
        rid = r["id"]
        summary = r.get("summary_json") or {}
        kpis = _dashboard_fields_from_summary(summary)

        full_commit = r.get("git_commit") or ""
        git_commit = full_commit[:8]
        seed = r.get("seed") or ""
        worker_version = r.get("worker_version") or ""

        gate_id = r.get("gate_id")
        gate_status = r.get("gate_status")
        gate_badge = _gate_badge(gate_status)

        decision, decision_cls = _ship_decision(r.get("status"), gate_status)
        decision_badge = f'<span class="badge {decision_cls}">{decision}</span>'

        decision_btn = f'<a class="btn btn2" href="/ship/decision?run_id={rid}" target="_blank">Decision JSON</a>'

        gate_btn = f'<a class="btn btn2" href="/runs/{rid}/gate" target="_blank">Gate JSON</a>' if gate_id else ""

        report_btn = (
            f'<a class="btn" href="/runs/{rid}/report" target="_blank">Open report</a>'
            if r.get("report_uri") else ""
        )
        artifacts_btn = f'<a class="btn btn2" href="/runs/{rid}/artifacts" target="_blank">Artifacts (JSON)</a>'

        rows_html += f"""
        <tr>
          <td>{rid}</td>
          <td>{r.get("backend","")}</td>
          <td><b>{r.get("status","")}</b></td>
          <td>{r.get("created_at","")}</td>

          <td class="kpi">
            <div><span class="k">success</span> {_fmt(kpis.get("success_rate"))}</div>
            <div><span class="k">dur ms</span> {_fmt(kpis.get("duration_mean_ms"))}</div>
            <div><span class="k">p95 ms</span> {_fmt(kpis.get("latency_p95_ms"))}</div>
            <div><span class="k">safety</span> {_fmt(kpis.get("safety_violations"))}</div>
            <div><span class="k">tts mean</span> {_fmt(kpis.get("time_to_success_mean_s"))}</div>
            <div><span class="k">episodes</span> {_fmt(kpis.get("num_episodes"))}</div>
          </td>

          <td>
            <div title="{full_commit}">
              <span class="k">git</span> {git_commit}
            </div>
            <div><span class="k">seed</span> {seed}</div>
            <div><span class="k">worker</span> {worker_version}</div>
          </td>

          <td style="color:#ffb4b4;">{r.get("error_message") or ""}</td>

          <td>
            <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:6px;">
              {decision_badge}
              <span class="muted">gate:</span> {gate_badge}
            </div>
            {decision_btn}
            {gate_btn}
            {report_btn}
            {artifacts_btn}
          </td>
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
        .muted {{ color: #94a3b8; font-size: 12px; }}

        .btn {{
          display: inline-block; padding: 6px 10px; border: 1px solid #3a4;
          border-radius: 6px; color: #dff; text-decoration: none; margin-right: 6px; margin-bottom: 6px;
        }}
        .btn:hover {{ background: #163; }}
        .btn2 {{ border-color: #446; color: #dde; }}
        .btn2:hover {{ background: #224; }}

        .kpi {{ min-width: 220px; }}
        .kpi .k {{ color: #b8c0ff; display: inline-block; width: 70px; }}
        .k {{ color: #b8c0ff; display: inline-block; width: 70px; }}

        .badge {{ padding: 3px 8px; border-radius: 999px; font-weight: 800; font-size: 12px; }}
        .pass {{ background: #123d2a; color: #7CFC9A; border: 1px solid #1f6f44; }}
        .fail {{ background: #3d1212; color: #FF7A7A; border: 1px solid #6f1f1f; }}
        .na   {{ background: #111827; color: #94a3b8; border: 1px solid #223; }}

        .ship {{ background: #0f2f1f; color: #7CFC9A; border: 1px solid #1f6f44; }}
        .block {{ background: #2f0f0f; color: #FF7A7A; border: 1px solid #6f1f1f; }}
        .pending {{ background: #111827; color: #e2e8f0; border: 1px solid #334155; }}
      </style>
    </head>
    <body>
      <h1>Runs</h1>
      <p class="muted">Latest {limit} runs. Decision badge is derived from run status + latest gate result.</p>
      <p>
        <a class="btn btn2" href="/ui/gates">Open Gates</a>
        <a class="btn btn2" href="/ui/compare?run_ids=41,42">Compare example</a>
      </p>

      <table>
        <thead>
          <tr>
            <th>ID</th><th>Backend</th><th>Status</th><th>Created</th>
            <th>KPIs</th><th>Repro</th><th>Error</th><th>Decision + Links</th>
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


# ----------------------
# Enqueue run (Celery)
# ----------------------
@app.post("/runs/{run_id}/enqueue")
def enqueue_run(run_id: int):
    from packages.worker.tasks import evaluate_run  # avoid circular import

    run = fetch_one("SELECT id, status FROM runs WHERE id=:id", {"id": run_id})
    if not run:
        raise HTTPException(status_code=404, detail="run not found")

    if run["status"] != "queued":
        raise HTTPException(status_code=409, detail=f"run status must be queued (is {run['status']})")

    task = evaluate_run.delay(run_id)
    return {"message": "enqueued", "run_id": run_id, "task_id": task.id}
