from __future__ import annotations

from rep_runner.backends.base import BackendBase
from rep_backend_mujoco.backend import MujocoBackend


def make_backend(name: str) -> BackendBase:
    name = (name or "").strip().lower()
    if name == "mujoco":
        return MujocoBackend()
    raise ValueError(f"Unknown backend: {name!r}")
