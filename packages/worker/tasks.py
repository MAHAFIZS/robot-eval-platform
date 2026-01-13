import json
import os
import time
from pathlib import Path
from datetime import datetime, timezone

import boto3
from botocore.client import Config

from packages.worker.celery_app import celery_app
from packages.backend.db_exec import fetch_one, exec_returning


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def upload_folder_to_minio(run_id: int, local_dir: Path, bucket: str) -> tuple[str, str]:
    """
    Uploads all files under local_dir to s3://bucket/<run_id>/...
    Returns (report_uri, base_prefix)
    """
    s3 = minio_client()
    ensure_bucket(s3, bucket)

    base_prefix = f"{run_id}"
    for p in local_dir.rglob("*"):
        if p.is_file():
            key = f"{base_prefix}/{p.relative_to(local_dir).as_posix()}"
            s3.upload_file(str(p), bucket, key)

    report_uri = f"s3://{bucket}/{base_prefix}/report.html"
    return report_uri, base_prefix


def write_artifacts(run_id: int) -> Path:
    """
    Minimal artifacts for demo: config snapshot + metrics + report.html
    """
    out_dir = Path("artifacts") / str(run_id)
    (out_dir / "plots").mkdir(parents=True, exist_ok=True)

    env_snapshot = {
        "created_at": utc_now(),
        "run_id": run_id,
        "note": "Day5 dummy worker job (replace with Mujoco runner later)",
    }
    (out_dir / "env_snapshot.json").write_text(json.dumps(env_snapshot, indent=2), encoding="utf-8")

    metrics = {
        "success_rate": 1.0,
        "time_to_success_mean": 2.3,
        "safety_violations": 0,
        "latency_p95_ms": 12.4,
    }
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    report_html = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>Run {run_id} Report</title></head>
<body>
<h1>Run {run_id} Report</h1>
<p>Status: completed</p>
<pre>{json.dumps(metrics, indent=2)}</pre>
</body>
</html>
"""
    (out_dir / "report.html").write_text(report_html, encoding="utf-8")

    return out_dir


@celery_app.task(name="packages.worker.tasks.evaluate_run")
def evaluate_run(run_id: int) -> dict:
    # Validate run exists
    run = fetch_one("SELECT id, status FROM runs WHERE id=:id", {"id": run_id})
    if not run:
        return {"ok": False, "error": "run not found", "run_id": run_id}

    # Move to running (idempotent-ish)
    exec_returning(
        """
        UPDATE runs
        SET status='running', started_at=NOW(), error_message=NULL
        WHERE id=:id
        RETURNING id
        """,
        {"id": run_id},
    )

    try:
        # Simulate doing work (replace later with Mujoco evaluation)
        time.sleep(2)

        # Write local artifacts
        out_dir = write_artifacts(run_id)

        # Upload artifacts to MinIO
        bucket = os.getenv("S3_BUCKET", "artifacts")
        report_uri, _ = upload_folder_to_minio(run_id, out_dir, bucket)

        # Read metrics back for DB summary
        metrics = json.loads((out_dir / "metrics.json").read_text(encoding="utf-8"))

        # Mark completed
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
            {"id": run_id, "summary": json.dumps(metrics), "report_uri": report_uri},
        )

        return {"ok": True, "run_id": run_id, "report_uri": report_uri, "metrics": metrics}

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
        return {"ok": False, "run_id": run_id, "error": str(e)}

