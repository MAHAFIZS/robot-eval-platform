from __future__ import annotations

import time
from typing import Any, Dict

from rep_core.specs import TaskSpec, EpisodeSpec
from rep_runner.backends.base import BackendBase, BackendContext


class MujocoBackend(BackendBase):
    name = "mujoco"

    def prepare(self, task: TaskSpec) -> BackendContext:
        return BackendContext({"prepared_at": time.time()})

    def run_episode(self, task: TaskSpec, episode: EpisodeSpec, ctx: BackendContext) -> Dict[str, Any]:
        start = time.time()
        time.sleep(0.01)
        latency_ms = (time.time() - start) * 1000.0

        return {
            "success": True,
            "latency_ms": round(latency_ms, 3),
            "seed": episode.seed,
            "horizon_steps": episode.horizon_steps,
        }

    def finalize(self, task: TaskSpec, ctx: BackendContext) -> None:
        return
