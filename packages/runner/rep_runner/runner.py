from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from rep_core.artifacts import ArtifactLayout
from rep_core.specs import TaskSpec
from rep_runner.backends.base import BackendBase


@dataclass
class RunResult:
    per_episode: List[Dict[str, Any]]
    summary: Dict[str, Any]


class Runner:
    """
    Executes a TaskSpec using a Backend and writes artifacts locally.
    Uploading to MinIO happens in your worker (existing logic).
    """

    def __init__(self, backend: BackendBase, local_artifact_root: str = "artifacts"):
        self.backend = backend
        self.local_artifact_root = Path(local_artifact_root)

    def run(self, task: TaskSpec) -> RunResult:
        layout = ArtifactLayout(run_id=task.run_id)

        # Ensure base dirs
        (self.local_artifact_root / layout.episodes_dir()).mkdir(parents=True, exist_ok=True)

        # Save manifest (TaskSpec)
        (self.local_artifact_root / layout.run_manifest()).write_text(
            task.model_dump_json(indent=2), encoding="utf-8"
        )

        ctx = self.backend.prepare(task)
        per_episode: List[Dict[str, Any]] = []

        try:
            for ep in task.episodes:
                ep_dir = self.local_artifact_root / layout.episode_dir(ep.episode_id)
                ep_dir.mkdir(parents=True, exist_ok=True)

                metrics = self.backend.run_episode(task, ep, ctx)
                per_episode.append({"episode_id": ep.episode_id, **metrics})

                (self.local_artifact_root / layout.episode_metrics(ep.episode_id)).write_text(
                    json.dumps(metrics, indent=2), encoding="utf-8"
                )
        finally:
            self.backend.finalize(task, ctx)

        # Minimal summary (Day 7 will expand)
        success_rate = None
        if per_episode and all("success" in m for m in per_episode):
            success_rate = sum(1 for m in per_episode if m["success"]) / len(per_episode)

        summary = {
            "run_id": task.run_id,
            "backend": task.backend,
            "num_episodes": len(per_episode),
            "success_rate": success_rate,
        }

        (self.local_artifact_root / layout.summary_json()).write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )

        (self.local_artifact_root / layout.report_html()).write_text(
            f"<html><body><h1>Run {task.run_id}</h1><pre>{json.dumps(summary, indent=2)}</pre></body></html>",
            encoding="utf-8",
        )

        return RunResult(per_episode=per_episode, summary=summary)
