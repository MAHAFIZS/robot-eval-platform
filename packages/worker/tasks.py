# packages/worker/tasks.py

import json
import os
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from packages.backend.gates_logic import evaluate_gate_for_candidate

import boto3
from botocore.client import Config

from packages.worker.celery_app import celery_app
from packages.backend.db_exec import (
    fetch_one,
    exec_returning,
    create_run_episode,
    complete_run_episode,
    fail_run_episode,
    list_run_episodes,
)

# IMPORTANT: use your real module path
from packages.runner.rep_runner.build_taskspec_from_db import build_taskspec_from_db

# Keep these as you already had
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
# Demo MuJoCo scene for fallback video
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
# Gate helpers (NEW: auto PASS/FAIL so UI stops showing "—")
# ----------------------------
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
            "duration_mean_ms": None,
            "safety_violations": None,
            "time_to_success_mean_s": None,
            "num_episodes": None,
        }
    return {
        "success_rate": _as_float(summary.get("success_rate")),
        "duration_mean_ms": _as_float(summary.get("duration_mean_ms") or summary.get("duration_mean")),
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
    # You can tune these later
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


def auto_create_gate_if_possible(run_id: int, suite_id: Optional[int], dataset_id: Optional[int], backend: str) -> None:
    """
    If a baseline lock exists for (suite_id, dataset_id, backend),
    create/update gate_evaluations(baseline_run_id, candidate_run_id) with pass/fail.
    """
    if suite_id is None or dataset_id is None:
        logger.info("Gate skipped: run_id=%s has suite_id/dataset_id missing", run_id)
        return

    # Already exists? (idempotent)
    existing = fetch_one(
        """
        SELECT id
        FROM gate_evaluations
        WHERE candidate_run_id = :rid
        ORDER BY created_at DESC
        LIMIT 1
        """,
        {"rid": run_id},
    )
    if existing:
        logger.info("Gate already exists for run_id=%s (gate_id=%s) - skipping", run_id, existing["id"])
        return

    lock = fetch_one(
        """
        SELECT *
        FROM baseline_locks
        WHERE suite_id=:suite_id AND dataset_id=:dataset_id AND backend=:backend
        """,
        {"suite_id": suite_id, "dataset_id": dataset_id, "backend": backend},
    )
    if not lock:
        logger.info("Gate skipped: no baseline lock for suite=%s dataset=%s backend=%s", suite_id, dataset_id, backend)
        return

    baseline_id = lock.get("baseline_run_id")
    baseline = fetch_one("SELECT id, status, summary_json FROM runs WHERE id=:id", {"id": baseline_id})
    cand = fetch_one("SELECT id, status, summary_json FROM runs WHERE id=:id", {"id": run_id})

    if not baseline or not cand:
        logger.warning("Gate skipped: missing baseline or candidate row (baseline=%s candidate=%s)", baseline_id, run_id)
        return

    # We only gate completed candidate (we are called after completion anyway)
    if (cand.get("status") or "").lower() != "completed":
        logger.info("Gate skipped: candidate not completed run_id=%s status=%s", run_id, cand.get("status"))
        return

    status, details = _gate_decision(baseline, cand)

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
        RETURNING id, status
        """,
        {
            "baseline_run_id": baseline_id,
            "candidate_run_id": run_id,
            "status": status,
            "details": json.dumps(details),
        },
    )
    logger.info("Gate created: run_id=%s baseline=%s status=%s gate_id=%s", run_id, baseline_id, status, row.get("id"))


# ----------------------------
# HTML report with episode table (+ metrics link)
# ----------------------------
def build_report_html(run_id: int, status: str, summary: Dict[str, Any], episodes: List[dict]) -> str:
    public_base = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

    # legacy root video
    video_src = f"{public_base}/runs/{run_id}/artifacts/rollout.mp4"

    artifacts_json = f"{public_base}/runs/{run_id}/artifacts"
    run_json = f"{public_base}/runs/{run_id}"
    episodes_json = f"{public_base}/runs/{run_id}/episodes"

    def g(k: str, default: Any = ""):
        v = summary.get(k, default)
        return default if v is None else v

    def esc(s: Any) -> str:
        s = "" if s is None else str(s)
        return (
            s.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    rows_html = ""
    for ep in episodes:
        idx = ep.get("episode_index")
        st = ep.get("status")
        mj = ep.get("metrics_json") or {}

        success = mj.get("success", "")
        steps = mj.get("steps", "")
        reward = mj.get("reward", "")
        duration_ms = mj.get("duration_ms", "")

        ep_video_key = f"episodes/{int(idx):03d}/rollout.mp4"
        ep_metrics_key = f"episodes/{int(idx):03d}/metrics.json"

        ep_video_url = f"{public_base}/runs/{run_id}/artifacts/{ep_video_key}"
        ep_metrics_url = f"{public_base}/runs/{run_id}/artifacts/{ep_metrics_key}"

        rows_html += f"""
          <tr>
            <td style="padding:8px; border-bottom:1px solid #eee;">{idx}</td>
            <td style="padding:8px; border-bottom:1px solid #eee;">{esc(st)}</td>
            <td style="padding:8px; border-bottom:1px solid #eee;">{esc(success)}</td>
            <td style="padding:8px; border-bottom:1px solid #eee;">{esc(steps)}</td>
            <td style="padding:8px; border-bottom:1px solid #eee;">{esc(reward)}</td>
            <td style="padding:8px; border-bottom:1px solid #eee;">{esc(duration_ms)}</td>
            <td style="padding:8px; border-bottom:1px solid #eee;">
              <a href="{ep_video_url}" target="_blank">Open video</a>
            </td>
            <td style="padding:8px; border-bottom:1px solid #eee;">
              <a href="{ep_metrics_url}" target="_blank">metrics.json</a>
            </td>
          </tr>
        """

    if not rows_html:
        rows_html = """
          <tr>
            <td colspan="8" style="padding:10px; color:#666;">No episode rows found.</td>
          </tr>
        """

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Run {run_id} Report</title>
</head>
<body style="font-family: system-ui, Arial, sans-serif; max-width: 980px; margin: 40px auto; line-height: 1.45;">
  <h1>Run {run_id} Report</h1>
  <p><b>Status:</b> {esc(status)}</p>

  <p>
    <a href="{run_json}" target="_blank">Run JSON</a> ·
    <a href="{episodes_json}" target="_blank">Episodes JSON</a> ·
    <a href="{artifacts_json}" target="_blank">Artifacts JSON</a>
  </p>

  <h2>KPIs</h2>
  <ul>
    <li><b>Backend:</b> {esc(g("backend"))}</li>
    <li><b>Episodes:</b> {esc(g("num_episodes"))}</li>
    <li><b>Success rate:</b> {esc(g("success_rate"))}</li>
    <li><b>Mean duration (ms):</b> {esc(g("duration_mean_ms"))}</li>
    <li><b>Latency p95 (ms):</b> {esc(g("latency_p95_ms"))}</li>
    <li><b>Safety violations:</b> {esc(g("safety_violations"))}</li>
    <li><b>Time-to-success mean (s):</b> {esc(g("time_to_success_mean_s"))}</li>
  </ul>

  <h2>Episode metrics</h2>
  <table style="width:100%; border-collapse:collapse; border:1px solid #eee; border-radius:10px; overflow:hidden;">
    <thead>
      <tr style="background:#fafafa;">
        <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Episode</th>
        <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Status</th>
        <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Success</th>
        <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Steps</th>
        <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Reward</th>
        <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Duration (ms)</th>
        <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Video</th>
        <th style="text-align:left; padding:10px; border-bottom:1px solid #eee;">Metrics</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>

  <h2>Run video (legacy)</h2>
  <p style="color:#666; margin-top:-6px;">
    Kept for backward compatibility. It points to episode 0 if available:
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

    # IMPORTANT: include suite_id/dataset_id (needed for baseline lock lookup)
    run = fetch_one(
        "SELECT id, status, backend, suite_id, dataset_id FROM runs WHERE id=:id",
        {"id": run_id},
    )
    if not run:
        return {"ok": False, "error": "run not found", "run_id": run_id}

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
    out_dir = artifacts_root / str(run_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1) Build TaskSpec from DB
        task = build_taskspec_from_db(run_id)

        # 2) Create backend + runner
        backend = make_backend(task.backend)
        runner = Runner(backend=backend, local_artifact_root=str(artifacts_root))

        # 3) Execute evaluation EPISODE-BY-EPISODE
        episodes = list(getattr(task, "episodes", []) or [])
        num_episodes = len(episodes) if episodes else int(getattr(task, "config", {}).get("num_episodes", 1) or 1)

        logger.info("Running %s episodes for run_id=%s", num_episodes, run_id)

        for ep in range(num_episodes):
            logger.info("Episode loop: run_id=%s ep=%s/%s", run_id, ep, num_episodes)

            ep_id = create_run_episode(run_id=run_id, episode_index=ep)
            ep_dir = out_dir / "episodes" / f"{ep:03d}"
            ep_dir.mkdir(parents=True, exist_ok=True)

            t0 = datetime.now(timezone.utc)
            try:
                # IMPORTANT: avoid mutating the shared task object
                task_ep = task.model_copy(
                    deep=True,
                    update={
                        "num_episodes": 1,
                        "episodes": [task.episodes[ep]],  # reuse already-built episode
                    },
                )

                runner.run(task_ep)

                t1 = datetime.now(timezone.utc)
                duration_ms = int((t1 - t0).total_seconds() * 1000)

                metrics = {
                    "success": True,
                    "steps": None,
                    "reward": None,
                    "duration_ms": duration_ms,
                }

                write_json(ep_dir / "metrics.json", metrics)

                video_path = ensure_rollout_video(
                    out_dir=ep_dir,
                    run_id=run_id,
                    prefer_existing=True,
                )

                if (not video_path.exists()) or video_path.stat().st_size < 10_000:
                    raise RuntimeError(
                        f"Invalid rollout video for run {run_id} ep {ep}: "
                        f"{video_path} size="
                        f"{video_path.stat().st_size if video_path.exists() else 'MISSING'}"
                    )

                complete_run_episode(ep_id, metrics)

            except Exception as e:
                # mark failed in DB
                fail_run_episode(ep_id, str(e))
                write_text(ep_dir / "error.txt", str(e))

                # still write metrics + generate fallback video
                t1 = datetime.now(timezone.utc)
                duration_ms = int((t1 - t0).total_seconds() * 1000)
                fail_metrics = {
                    "success": False,
                    "steps": None,
                    "reward": None,
                    "duration_ms": duration_ms,
                    "error": str(e),
                }
                write_json(ep_dir / "metrics.json", fail_metrics)

                # Force-create a video so your report link never 404s/NoSuchKey
                ensure_rollout_video(out_dir=ep_dir, run_id=run_id, prefer_existing=False)

                logger.exception("Episode failed run_id=%s ep=%s", run_id, ep)

        # 4) Aggregate summary from episodes
        episodes = list_run_episodes(run_id)

        succ_vals: List[float] = []
        durations: List[int] = []

        for ep in episodes:
            mj = ep.get("metrics_json") or {}
            st = (ep.get("status") or "").lower()

            if "success" in mj:
                succ_vals.append(1.0 if mj.get("success") else 0.0)
            else:
                if st == "failed":
                    succ_vals.append(0.0)

            if mj.get("duration_ms") is not None:
                try:
                    durations.append(int(mj["duration_ms"]))
                except Exception:
                    pass

        success_rate = (sum(succ_vals) / len(succ_vals)) if succ_vals else None
        duration_mean_ms = (sum(durations) / len(durations)) if durations else None

        summary: Dict[str, Any] = {
            "run_id": run_id,
            "backend": getattr(task, "backend", run.get("backend")),
            "num_episodes": len(episodes),
            "success_rate": success_rate,
            "duration_mean_ms": duration_mean_ms,
            "latency_p95_ms": None,
            "safety_violations": None,
            "time_to_success_mean_s": None,
        }

        write_json(out_dir / "summary.json", summary)

        # 5) Keep legacy rollout.mp4 at run root (copy episode 0 if exists)
        ep0_video = out_dir / "episodes" / "000" / "rollout.mp4"
        if ep0_video.exists():
            (out_dir / "rollout.mp4").write_bytes(ep0_video.read_bytes())
            summary["rollout_generated"] = True
        else:
            video_path = ensure_rollout_video(out_dir=out_dir, run_id=run_id, prefer_existing=True)
            summary["rollout_generated"] = bool(video_path.exists())

        # 6) Report with episode table
        report_html = build_report_html(
            run_id=run_id,
            status="completed",
            summary=summary,
            episodes=episodes,
        )
        write_text(out_dir / "report.html", report_html)

        # 7) Upload artifacts to MinIO
        bucket = os.getenv("S3_BUCKET", "artifacts")
        report_uri = upload_folder_to_minio(run_id, out_dir, bucket)

        # 8) Update runs table -> completed
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

        # 9) AUTO GATE (creates gate_evaluations row if baseline exists)
        try:
            auto_create_gate_if_possible(
                run_id=run_id,
                suite_id=run.get("suite_id"),
                dataset_id=run.get("dataset_id"),
                backend=run.get("backend"),
            )
            logger.info("Auto gate evaluated for run_id=%s", run_id)
        except Exception:
            logger.exception("Auto gate evaluation failed for run_id=%s (non-fatal)", run_id)

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
