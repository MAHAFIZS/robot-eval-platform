# Robot Eval Platform (robot-eval-platform)

A **robot-centric evaluation and regression dashboard** for learning-enabled controllers and robotics stacks.

It turns simulation or robot rollouts into **episode-level metrics, videos, and reports**, and helps answer one critical question:

> **Is the new controller/model better and safe to deploy compared to the baseline?**

Think of it as **CI for robot behavior** — not just another ML experiment tracker.

---

## Why this exists

Most ML dashboards track loss and reward.
Robotics teams care about **behavior**:

- Task success and time-to-completion
- Safety violations and unstable motion
- Episode-by-episode failure analysis
- Video-first debugging
- Baseline vs candidate comparison before real-robot deployment

This platform provides a **decision layer** between simulation and real hardware.

---

## Input → Output (simple)

### Input
- Robot or simulator rollout results
- Episode metrics (JSON)
- Episode videos (MP4)
- Run metadata (model/controller version, task, config)

### Output
- Run summaries and reports
- Episode browser with videos and metrics
- Baseline vs candidate comparison
- Clear **regression decision** (pass / warn / fail)

---

## High-level architecture

## High-level architecture

```text
Controller / Policy / Robot Stack
            |
            v
      Evaluator / Runner
            |
            v
Artifacts (metrics.json, rollout.mp4)
            |
            v
Backend API + Database + Artifact Store
            |
            v
          Dashboard

- Backend: FastAPI
- Database: Postgres
- Artifact store: Local filesystem or S3-compatible (e.g. MinIO)
- Workers generate metrics, videos, and reports

---

## Quickstart (local)

### Prerequisites
- Docker
- Docker Compose

### Start services
```bash
docker compose up -d
API

Backend API: http://localhost:8000

Runs endpoint: http://localhost:8000/runs

Your evaluator/worker can POST runs and episodes or upload artifacts directly.

Artifact format (simulator-agnostic)

The platform is MuJoCo-first, but simulator-agnostic by design.

Any simulator or real robot can integrate by exporting standardized artifacts.

Minimal example: metrics.json

{
  "episode_id": "007",
  "success": false,
  "time_sec": 6.8,
  "safety_violations": 2,
  "notes": "oscillation near goal"
}


Required artifacts per episode:

metrics.json

rollout.mp4 (video)

Optional per run:

summary.json

report.html

Core features

Run and episode tracking

Episode-level metrics

Video-first debugging

Baseline vs candidate comparison

Regression detection via thresholds/rules

Works with simulation or real-robot logs

Example use cases

Detect regressions in learned controllers

Compare policy versions before deployment

Analyze failure cases with video evidence

Standardize evaluation across teams

Reduce real-robot risk

Roadmap

v1 (product-ready core)

Stable API and schema

One-command deployment

Demo baseline vs regressed run

Comparison + regression flags

Clear documentation

v2

More task templates (pick, place, insert, screw)

Additional stability and safety metrics

ROS / real-robot adapter examples

CI integration examples

License

See LICENSE file.

If you plan commercial usage, contact the author for permission.

Author

M. A. Hafiz

GitHub: https://github.com/MAHAFIZS

Portfolio: https://mahafizsourav.com

LinkedIn: https://linkedin.com/in/hafiz-ma
