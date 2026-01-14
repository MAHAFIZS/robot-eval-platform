from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

from rep_core.specs import TaskSpec, EpisodeSpec


class BackendContext(dict):
    """Backend-specific shared objects (loaded handles, clients, etc.)."""


class BackendBase(ABC):
    name: str

    @abstractmethod
    def prepare(self, task: TaskSpec) -> BackendContext:
        """Load/warm resources needed for the run."""

    @abstractmethod
    def run_episode(self, task: TaskSpec, episode: EpisodeSpec, ctx: BackendContext) -> Dict[str, Any]:
        """Execute one episode and return JSON-serializable metrics."""

    @abstractmethod
    def finalize(self, task: TaskSpec, ctx: BackendContext) -> None:
        """Cleanup."""
