# packages/worker/tasks.py

import json
import os
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict

import boto3
from botocore.client import Config

from packages.worker.celery_app import celery_app
from packages.backend.db_exec import fetch_one, exec_returning

from rep_runner import build_taskspec_from_db
from rep_runner.runner import Runner
from rep_runner.backends import make_backend

from packages.worker.video import render_rollout_mp4

logger = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


# ----------------------------
# Time helper
# ----------------------------
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ----------------------------
# MinIO / S3 helpers
# ----------------------------
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


def ensure_bucket(s3, bucket: str):
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:
        s3.create_bucket(Bucket=bucket)


def _content_type_for_path(p: Path) -> str:
    n = p.name.lower()
    if n.endswith(".html"):
        return "text/html"
    if n.endswith(".json"):
        return "application/json"
    if n.endswith(".mp4"):
        return "video/mp4"
    if n.endswith(".png"):
        return "image/png"
    if n.endswith(".jpg") or n.endswith(".jpeg"):
        return "image/jpeg"
    if n.endswith(".csv"):
        return "text/csv"
    if n.endswith(".txt") or n.endswith(".log"):
        return "text/plain"
    return "application/octet-stream"


def upload_folder_to_minio(run_id: int, local_dir: Path, bucket: str) -> str:
    """
    Upload all files under local_dir to s3://bucket/<run_id>/...
    Returns report_uri (s3://bucket/<run_id>/report.html)
    """
    s3 = minio_client()
    ensure_bucket(s3, bucket)

    base_prefix = f"{run_id}"
    for p in local_dir.rglob("*"):
        if not p.is_file():
            continue
        key = f"{base_prefix}/{p.relative_to(local_dir).as_posix()}"
        ct = _content_type_for_path(p)
        s3.upload_file(str(p), bucket, key, ExtraArgs={"ContentType": ct})

    return f"s3://{bucket}/{base_prefix}/report.html"


# ----------------------------
# Artifact write helpers
# ----------------------------
def write_json(path: Path, obj: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ----------------------------
# Day 11: demo MuJoCo scene for fallback video
# ----------------------------
DEMO_XML = r"""
<mujoco model="ball">
  <option timestep="0.01" gravity="0 0 -9.81"/>
  <visual>
    <global offwidth="1280" offheight="720"/>
  </visual>
  <worldbody>
    <light pos="0 0 2"/>
    <geom type="plane" size="2 2 0.1" rgba="0.2 0.2 0.2 1"/>
    <body pos="0 0 1">
      <joint name="free" type="free"/>
      <geom type="sphere" size="0.08" rgba="0.2 0.6 1 1"/>
    </body>
  </worldbody>
</mujoco>
"""


def ensure_rollout_video(out_dir: Path, run_id: int, prefer_existing: bool = True) -> Path:
    """
    Ensures out_dir/rollout.mp4 exists.
    If missing, generates a fallback MuJoCo demo video (headless).
    """
    video_path = out_dir / "rollout.mp4"
    if prefer_existing and video_path.exists():
        return video_path

    try:
        import mujoco

        model = mujoco.MjModel.from_xml_string(DEMO_XML)
        data = mujoco.MjData(model)

        # Try HD first, fallback to SD
        try:
            render_rollout_mp4(
                model=model,
                data=data,
                out_path=video_path,
                sim_steps=300,
                fps=30,
                width=1280,
                height=720,
                record_every=2,
            )
        except Exception:
            logger.exception("HD render failed; retrying SD for run_id=%s", run_id)
            render_rollout_mp4(
                model=model,
                data=data,
                out_path=video_path,
                sim_steps=300,
                fps=30,
                width=640,
                height=480,
                record_every=2,
            )

        logger.info("Generated rollout video for run_id=%s -> %s", run_id, str(video_path))
        return video_path
    except Exception:
        logger.exception("Could not generate rollout video for run_id=%s", run_id)
        return video_path


# ----------------------------
# HTML report (IMPORTANT FIX)
# ----------------------------
def build_report_html(run_id: int, status: str, summary: Dict[str, Any]) -> str:
    """
    Generates a simple HTML report.

    IMPORTANT:
    - The report is usually opened from MinIO (localhost:9000).
    - So video links MUST be absolute to FastAPI (localhost:8000), otherwise you get AccessDenied from MinIO.
    """
    public_base = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    video_src = f"{public_base}/runs/{run_id}/artifacts/rollout.mp4"
    artifacts_json = f"{public_base}/runs/{run_id}/artifacts"
    run_json = f"{public_base}/runs/{run_id}"

    def g(k: str, default: Any = ""):
        v = summary.get(k, default)
        return default if v is None else v

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Run {run_id} Report</title>
</head>
<body style="font-family: system-ui, Arial, sans-serif; max-width: 980px; margin: 40px auto; line-height: 1.45;">
  <h1>Run {run_id} Report</h1>
  <p><b>Status:</b> {status}</p>

  <p>
    <a href="{run_json}" target="_blank">Run JSON</a> ·
    <a href="{artifacts_json}" target="_blank">Artifacts JSON</a>
  </p>

  <h2>KPIs</h2>
  <ul>
    <li><b>Backend:</b> {g("backend")}</li>
    <li><b>Episodes:</b> {g("num_episodes")}</li>
    <li><b>Success rate:</b> {g("success_rate")}</li>
    <li><b>Latency p95 (ms):</b> {g("latency_p95_ms")}</li>
    <li><b>Safety violations:</b> {g("safety_violations")}</li>
    <li><b>Time-to-success mean (s):</b> {g("time_to_success_mean_s")}</li>
  </ul>

  <h2>Simulation video</h2>
  <p style="color:#666; margin-top:-6px;">
    Video is served via FastAPI so it can presign from MinIO:
    <a href="{video_src}" target="_blank">{video_src}</a>
  </p>

  <video width="920" controls autoplay loop muted style="border:1px solid #ddd; border-radius:10px;">
    <source src="{video_src}" type="video/mp4">
    Your browser does not support the video tag.
  </video>

  <h2>Raw summary</h2>
  <pre style="background:#f6f6f6; padding:12px; border-radius:10px; overflow:auto;">{json.dumps(summary, indent=2)}</pre>
</body>
</html>
"""


# ----------------------------
# Main Celery Task
# ----------------------------
@celery_app.task(name="packages.worker.tasks.evaluate_run")
def evaluate_run(run_id: int) -> dict:
    logger.info("Starting run_id=%s", run_id)

    # Validate run exists
    run = fetch_one("SELECT id, status, backend FROM runs WHERE id=:id", {"id": run_id})
    if not run:
        return {"ok": False, "error": "run not found", "run_id": run_id}

    # Move to running
    exec_returning(
        """
        UPDATE runs
        SET status='running', started_at=NOW(), error_message=NULL
        WHERE id=:id
        RETURNING id
        """,
        {"id": run_id},
    )

    artifacts_root = Path(os.getenv("ARTIFACTS_LOCAL_DIR", "artifacts"))

    # IMPORTANT: use artifacts/<run_id>/... (matches backend Day10 assumptions)
    out_dir = artifacts_root / str(run_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1) Build TaskSpec from DB
        task = build_taskspec_from_db(run_id)

        # 2) Create backend + runner
        backend = make_backend(task.backend)
        runner = Runner(backend=backend, local_artifact_root=str(artifacts_root))

        # 3) Execute evaluation
        result = runner.run(task)

        # NOTE:
        # If your Runner writes into artifacts/run_<id>/ by itself, we still write our “official”
        # report/summary/video into artifacts/<id>/ and upload THAT.

        # 4) Normalize summary
        summary: Dict[str, Any] = dict(getattr(result, "summary", None) or {})
        summary.setdefault("run_id", run_id)
        summary.setdefault("backend", getattr(task, "backend", run.get("backend")))
        summary.setdefault("num_episodes", summary.get("num_episodes", summary.get("episodes", 0)))
        summary.setdefault("success_rate", summary.get("success_rate", None))
        summary.setdefault("latency_p95_ms", summary.get("latency_p95_ms", None))
        summary.setdefault("safety_violations", summary.get("safety_violations", None))
        summary.setdefault("time_to_success_mean_s", summary.get("time_to_success_mean_s", None))

        write_json(out_dir / "summary.json", summary)

        # 5) Ensure rollout.mp4
        video_path = ensure_rollout_video(out_dir=out_dir, run_id=run_id, prefer_existing=True)
        summary["rollout_generated"] = bool(video_path.exists())

        # 6) Write report.html (with absolute FastAPI links)
        report_html = build_report_html(run_id=run_id, status="completed", summary=summary)
        write_text(out_dir / "report.html", report_html)

        # 7) Upload artifacts to MinIO (bucket artifacts by default)
        bucket = os.getenv("S3_BUCKET", "artifacts")
        report_uri = upload_folder_to_minio(run_id, out_dir, bucket)

        # 8) Update DB
        exec_returning(
            """
            UPDATE runs
            SET status='completed',
                ended_at=NOW(),
                summary_json=CAST(:summary AS jsonb),
                report_uri=:report_uri
            WHERE id=:id
            RETURNING id
            """,
            {"id": run_id, "summary": json.dumps(summary), "report_uri": report_uri},
        )

        logger.info("Completed run_id=%s report_uri=%s", run_id, report_uri)
        return {"ok": True, "run_id": run_id, "report_uri": report_uri, "summary": summary}

    except Exception as e:
        exec_returning(
            """
            UPDATE runs
            SET status='failed', ended_at=NOW(), error_message=:msg
            WHERE id=:id
            RETURNING id
            """,
            {"id": run_id, "msg": str(e)},
        )
        logger.exception("Run failed run_id=%s", run_id)
        return {"ok": False, "run_id": run_id, "error": str(e)}
