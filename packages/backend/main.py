# packages/backend/main.py - COMPLETE UPDATED CODE

import json
import os
import subprocess
import random
from typing import List, Optional, Literal, Any, Dict
from urllib.parse import urlparse
from datetime import datetime, date
from decimal import Decimal
import boto3
from botocore.client import Config
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from pydantic import BaseModel, Field

from packages.backend.db import ping_db
from packages.backend.db_exec import fetch_all, fetch_one, exec_returning, list_run_episodes
from packages.backend.hashutil import sha256_text

app = FastAPI(title="Robot Eval Orchestrator API")

# Where local artifacts live (if you store artifacts on disk as well)
# Expect structure like: <ARTIFACTS_LOCAL_DIR>/<run_id>/report.html, summary.json, ...
ARTIFACTS_LOCAL_DIR = os.getenv("ARTIFACTS_LOCAL_DIR", "./artifacts")

# ----------------------
# Reproducibility (Day 1)
# ----------------------
WORKER_VERSION = os.getenv("WORKER_VERSION", "dev")


def get_git_commit() -> Optional[str]:
    # Prefer env var (works in Docker/CI), fallback to git command (works in dev)
    env_sha = os.getenv("GIT_COMMIT")
    if env_sha:
        return env_sha.strip()

    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return None


def make_seed() -> int:
    # allow overriding for reproducible re-runs
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
# Local artifact helpers (Day 10)
# ----------------------
def _safe_join(base_dir: str, rel_path: str) -> str:
    """
    Prevent path traversal when serving local artifacts.
    rel_path must be a relative path like "7/report.html".
    """
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
    """
    Normalize commonly used KPI fields from summary_json.
    This makes /runs and UI easier.
    """
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
    """
    Compute (b - a) if both numeric; otherwise None.
    """
    try:
        if a is None or b is None:
            return None
        return float(b) - float(a)
    except Exception:
        return None


# ----------------------
# UI helpers for improved /ui/compare
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
    """
    Return CSS class for delta coloring.
    - success_rate: higher is better
    - duration_mean_ms, safety_violations, time_to_success_mean_s: lower is better
    """
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
    # Validate IDs
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

    # ---- Reproducibility fields ----
    git_commit = get_git_commit()  # Use helper consistently
    seed = int.from_bytes(os.urandom(4), "big")  # Crypto-secure seed
    worker_version = os.getenv("WORKER_VERSION", "dev")

    # Store config_snapshot as JSON TEXT (not dict), then CAST in SQL
    config_snapshot = None
    if payload.suite_id is not None:
        srow = fetch_one("SELECT yaml_spec FROM suites WHERE id=:id", {"id": payload.suite_id})
        if srow and srow.get("yaml_spec"):
            config_snapshot = json.dumps({"suite_yaml_spec": srow["yaml_spec"]})

    row = exec_returning(
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
            "config_snapshot": config_snapshot,  # json string or None
            "seed": seed,
            "worker_version": worker_version,
        },
    )
    return row


@app.get("/runs")
def list_runs(limit: int = 50):
    rows = fetch_all(
        """
        SELECT r.*, m.name as model_name, m.version as model_version
        FROM runs r
        JOIN models m ON m.id = r.model_id
        ORDER BY r.created_at DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )

    # Day 10: add dashboard-friendly fields
    for r in rows:
        kpis = _dashboard_fields_from_summary(r.get("summary_json"))
        r.update(kpis)
        r["report_available"] = bool(r.get("report_uri"))
        r["report_link"] = f"/runs/{r['id']}/report" if r.get("report_uri") else None
        r["artifacts_link"] = f"/runs/{r['id']}/artifacts"
    return rows
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

    out = []
    for r in runs:
        a = agg.get(r["id"], {})
        sj = r.get("summary_json") or {}

        num_episodes = int(a.get("num_episodes") or sj.get("num_episodes") or 0)
        success_rate = a.get("success_rate", sj.get("success_rate"))
        duration_mean_ms = a.get("duration_mean_ms", sj.get("duration_mean_ms"))
        safety_violations = sj.get("safety_violations")
        time_to_success_mean_s = sj.get("time_to_success_mean_s")

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
                "num_episodes": num_episodes,
                "success_rate": success_rate,
                "duration_mean_ms": duration_mean_ms,
                "latency_p95_ms": sj.get("latency_p95_ms"),
                "safety_violations": safety_violations,
                "time_to_success_mean_s": time_to_success_mean_s,
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
            # safety violations often is int; delta may be None if missing
            "safety_violations_delta": _delta(A.get("safety_violations"), B.get("safety_violations")),
        }

    return {"runs": out, "deltas": deltas}


@app.get("/runs/{run_id}")
def get_run(run_id: int):
    run = fetch_one(
        """
        SELECT id, model_id, suite_id, dataset_id, backend, status,
               started_at, ended_at, summary_json, report_uri, error_message, created_at,
               git_commit, config_snapshot, seed, worker_version
        FROM runs
        WHERE id=:id
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
    return run


@app.get("/runs/{run_id}/episodes")
def get_run_episodes(run_id: int):
    return {"run_id": run_id, "episodes": list_run_episodes(run_id)}


# ----------------------
# Compare Runs (Phase 2.1 Step 2)
# ----------------------


# ----------------------
# UI: Compare Runs (UPDATED WITH A/B SELECTORS)
# ----------------------
@app.get("/ui/compare", response_class=HTMLResponse)
def ui_compare(
    run_ids: str = Query(..., description="Comma-separated run IDs, e.g. 38,41,42"),
    a: Optional[int] = Query(None, description="Run A id"),
    b: Optional[int] = Query(None, description="Run B id"),
):
    # Fetch compare payload from your own backend function directly (no HTTP call needed)
    payload = compare_runs(run_ids=run_ids)  # reuse your existing /runs/compare logic
    runs = payload.get("runs", [])

    if not runs:
        return HTMLResponse("<h1>No runs found</h1>", status_code=404)

    ids = [r["id"] for r in runs]

    # Default A/B selection:
    # - if user passed a/b and they exist => use them
    # - else use first two ids
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

    # Build runs table rows
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

    # Selector options
    opts = "\n".join([f'<option value="{rid}">{rid}</option>' for rid in ids])

    # Delta table rows
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

    # Make payload safe for JSON dumping in debug section
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
          // set selected values
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
# Day 10: Report resolver
# ----------------------
@app.get("/runs/{run_id}/report")
def open_report(run_id: int):
    run = fetch_one("SELECT id, report_uri FROM runs WHERE id=:id", {"id": run_id})
    if not run:
        raise HTTPException(status_code=404, detail="run not found")

    uri = (run.get("report_uri") or "").strip()
    if not uri:
        raise HTTPException(status_code=404, detail="report_uri missing")

    # Direct HTTP(S)
    if uri.startswith("http://") or uri.startswith("https://"):
        return RedirectResponse(uri)

    # S3 / MinIO
    if uri.startswith("s3://"):
        try:
            url = presign_s3_get(uri, expires_seconds=3600)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"failed to presign report: {e}")
        return RedirectResponse(url)

    # file:// absolute path
    if uri.startswith("file://"):
        path = uri.replace("file://", "", 1)
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="report file not found")
        return FileResponse(path, media_type="text/html", filename="report.html")

    # Otherwise treat as local relative artifact path under ARTIFACTS_LOCAL_DIR
    try:
        local_path = _safe_join(ARTIFACTS_LOCAL_DIR, uri)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid report_uri path")

    if not os.path.exists(local_path):
        raise HTTPException(status_code=404, detail="report file not found")

    return FileResponse(local_path, media_type="text/html", filename="report.html")


# ----------------------
# Day 10: Artifact listing & downloads
# ----------------------
@app.get("/runs/{run_id}/artifacts")
def list_run_artifacts(run_id: int):
    """
    Minimal Day 10 artifact listing.
    - Always includes report.html if report_uri exists
    - Includes common local artifacts if they exist under ARTIFACTS_LOCAL_DIR/<run_id>/
    """
    run = fetch_one(
        "SELECT id, report_uri FROM runs WHERE id=:id",
        {"id": run_id},
    )
    if not run:
        raise HTTPException(status_code=404, detail="run not found")

    artifacts: List[Dict[str, Any]] = []

    # Report (may be in MinIO or local)
    if run.get("report_uri"):
        artifacts.append(
            {
                "name": "report.html",
                "uri": run["report_uri"],
                "content_type": "text/html",
                "download": f"/runs/{run_id}/artifacts/report.html",
            }
        )

    # Local artifacts folder for this run
    run_dir = os.path.join(ARTIFACTS_LOCAL_DIR, f"run_{run_id}")

    if os.path.isdir(run_dir):
        for fname in sorted(os.listdir(run_dir)):
            # Avoid duplicating report.html if already included above
            if fname == "report.html" and run.get("report_uri"):
                continue
            fpath = os.path.join(run_dir, fname)
            if os.path.isfile(fpath):
                artifacts.append(
                    {
                        "name": fname,
                        "uri": f"{run_id}/{fname}",
                        "content_type": _media_type_for_name(fname),
                        "size_bytes": os.path.getsize(fpath),
                        "download": f"/runs/{run_id}/artifacts/{fname}",
                    }
                )

    return {"run_id": run_id, "artifacts": artifacts}


@app.get("/runs/{run_id}/artifacts/{name:path}")
def download_artifact(run_id: int, name: str):
    run = fetch_one("SELECT id, report_uri FROM runs WHERE id=:id", {"id": run_id})
    if not run:
        raise HTTPException(status_code=404, detail="run not found")

    report_uri = (run.get("report_uri") or "").strip()
    if report_uri.startswith("s3://"):
        # Derive artifact key from report_uri base prefix
        bucket, report_key = parse_s3_uri(report_uri)   # report_key = "13/report.html"
        prefix = report_key.rsplit("/", 1)[0]           # "13"
        key = f"{prefix}/{name}"                        # "13/rollout.mp4"
        s3 = minio_client()
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=3600,
        )
        return RedirectResponse(url)

    # fallback to local
    rel = f"run_{run_id}/{name}"
    path = _safe_join(ARTIFACTS_LOCAL_DIR, rel)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path, media_type=_media_type_for_name(name), filename=name)


# ----------------------
# Day 9: minimal UI (updated for Day 10 KPIs + artifact links)
# ----------------------
@app.get("/ui/runs", response_class=HTMLResponse)
def ui_runs():
    runs = fetch_all(
        """
        SELECT id, backend, status, created_at, started_at, ended_at,
               report_uri, summary_json, error_message,
               git_commit, seed, worker_version
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
        summary = r.get("summary_json") or {}
        err = r.get("error_message") or ""

        kpis = _dashboard_fields_from_summary(summary)

        report_btn = (
            f'<a class="btn" href="/runs/{rid}/report" target="_blank">Open report</a>'
            if r.get("report_uri")
            else ""
        )
        artifacts_btn = f'<a class="btn btn2" href="/runs/{rid}/artifacts" target="_blank">Artifacts (JSON)</a>'

        full_commit = r.get("git_commit") or ""
        git_commit = full_commit[:8]

        seed = r.get("seed") or ""
        worker_version = r.get("worker_version") or ""

        rows_html += f"""
        <tr>
          <td>{rid}</td>
          <td>{backend}</td>
          <td><b>{status}</b></td>
          <td>{created}</td>
          <td class="kpi">
            <div><span class="k">success</span> {kpis.get("success_rate")}</div>
            <div><span class="k">dur ms</span> {kpis.get("duration_mean_ms")}</div>
            <div><span class="k">p95 ms</span> {kpis.get("latency_p95_ms")}</div>
            <div><span class="k">safety</span> {kpis.get("safety_violations")}</div>
            <div><span class="k">tts mean</span> {kpis.get("time_to_success_mean_s")}</div>
            <div><span class="k">episodes</span> {kpis.get("num_episodes")}</div>
          </td>
          <td>
            <div title="{full_commit}">
               <span class="k">git</span> {git_commit}
            </div>

            <div><span class="k">seed</span> {seed}</div>
            <div><span class="k">worker</span> {worker_version}</div>
            <details>
              <summary style="cursor:pointer;color:#b8c0ff;">summary_json</summary>
              <pre>{summary}</pre>
            </details>
          </td>
          <td style="color:#ffb4b4;">{err}</td>
          <td>{report_btn} {artifacts_btn}</td>
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
        .btn {{
          display: inline-block; padding: 6px 10px; border: 1px solid #3a4;
          border-radius: 6px; color: #dff; text-decoration: none; margin-right: 6px;
        }}
        .btn:hover {{ background: #163; }}
        .btn2 {{ border-color: #446; color: #dde; }}
        .btn2:hover {{ background: #224; }}
        .kpi {{ min-width: 220px; }}
        .kpi .k {{ color: #b8c0ff; display: inline-block; width: 70px; }}
      </style>
    </head>
    <body>
      <h1>Runs</h1>
      <p>Latest 50 runs. "Open report" resolves MinIO (s3://) via presigned URL or serves local file. "Artifacts" lists downloadable outputs.</p>
      <p><a class="btn btn2" href="/ui/compare?run_ids=41,42">Compare example (41,42)</a></p>
      <table>
        <thead>
          <tr>
            <th>ID</th><th>Backend</th><th>Status</th><th>Created</th><th>KPIs</th><th>Repro + Summary</th><th>Error</th><th>Links</th>
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
