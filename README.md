#Robot Eval Platform

CI-style evaluation and regression gating for robot behavior

A robot-centric evaluation and regression platform for learning-enabled controllers, classical control stacks, and simulation-to-real pipelines.

It turns simulation or robot rollouts into episode-level metrics, videos, reports, and shipping decisions, answering one critical question:

Is the new controller safe and better than the baseline — and can it ship to real hardware?

Think of it as Continuous Integration (CI) for robot behavior, not just another ML experiment tracker.

Why this exists

Most ML dashboards optimize for loss curves and reward plots.
Robotics teams care about behavioral correctness and safety:

Task success and time-to-completion

Control latency and stability regressions

Safety violations and contact events

Episode-by-episode failure analysis

Video-first debugging

Baseline vs candidate comparison before deployment

This platform introduces a decision layer between simulation and real robots.

What problem it solves

Without a gating system:

Regressions reach real hardware

Engineers rely on manual inspection

Videos and metrics live in ad-hoc folders

“It worked last week” becomes the norm

Robot Eval Platform enforces discipline:

Reproducible evaluations

Evidence-backed decisions

Clear SHIP / BLOCK outcomes

Input → Output (simple mental model)
Input

Simulator or robot rollouts

Episode metrics (metrics.json)

Episode videos (rollout.mp4)

Run metadata (controller version, task, config)

Output

Run-level summaries

Episode browser with videos

Baseline vs candidate comparison

Automated gate decisions:

SHIP

BLOCK

PENDING

Core features

Run & episode tracking

Episode-level metrics

Video-first debugging

Baseline vs candidate comparison

Regression detection via rules

Immutable artifacts (S3 / MinIO)

Simulation-agnostic design

Real-robot compatible

High-level architecture
Controller / Policy / Robot Stack
            |
            v
      Evaluator / Runner
            |
            v
Artifacts (metrics.json, rollout.mp4, report.html)
            |
            v
Backend API + Database + Artifact Store
            |
            v
          Web Dashboard


Tech stack

Backend: FastAPI

Database: PostgreSQL

Artifact storage: Local filesystem or S3-compatible (MinIO)

Frontend: React + TypeScript

Evaluation workers: simulator / robot-specific

Gate-based decision logic

Each candidate run is compared against a locked baseline using explicit rules, e.g.:

Success rate ≥ baseline

Mean control latency ≤ baseline

Safety violations = 0

If any blocking rule fails, the run is automatically marked:

BLOCK — do not ship


This decision is:

Visible in the dashboard

Enforceable in CI

Traceable to metrics and videos

Simulator-agnostic artifact format

The platform does not depend on MuJoCo, ROS, or a specific simulator.

Any system can integrate by exporting standardized artifacts.

Minimal metrics.json
{
  "episode_id": "007",
  "success": false,
  "time_sec": 6.8,
  "safety_violations": 2,
  "notes": "oscillation near goal"
}

Required per episode

metrics.json

rollout.mp4

Optional per run

summary.json

report.html

Quickstart (local)
Prerequisites

Docker

Docker Compose

Start all services
docker compose up -d

Endpoints

Backend API: http://localhost:8000

Dashboard: http://localhost:5173

Your evaluator or worker can:

POST runs and episodes

Upload artifacts

Trigger gate evaluations

Example use cases

Detect regressions in learned controllers

Compare policy versions before deployment

Analyze failures with video evidence

Standardize evaluation across teams

Reduce real-robot risk

Scope (intentional)

This project focuses on evaluation correctness, not user management.

Out of scope (by design):

Authentication & accounts

Billing & multi-tenant SaaS

Organization management

These can be added later if needed.

Roadmap
v1 — Product-ready core (current)

Stable API and schema

One-command deployment

Baseline vs candidate gating

Regression detection

Evidence-backed SHIP / BLOCK decisions

v2

More task templates (pick, place, insert, screw)

Additional stability & safety metrics

ROS / real-robot adapters

CI integration examples

License

See LICENSE.

For commercial usage, contact the author.

Author

M. A. Hafiz
Robotics & Evaluation Infrastructure

GitHub: https://github.com/MAHAFIZS

Portfolio: https://mahafizsourav.com

LinkedIn: https://linkedin.com/in/hafiz-ma
