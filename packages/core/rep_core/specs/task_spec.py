from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

BackendName = Literal["mujoco", "real"]


class ModelRef(BaseModel):
    model_id: int
    uri: str  # e.g. s3://models/... or local path
    version: Optional[str] = None


class DatasetRef(BaseModel):
    dataset_id: int
    uri: str  # e.g. s3://datasets/... or local path
    format: str = "unknown"


class SuiteRef(BaseModel):
    suite_id: int
    name: str
    version: Optional[str] = None


class EpisodeSpec(BaseModel):
    episode_id: str = Field(default_factory=lambda: uuid4().hex)
    seed: int = 0
    horizon_steps: int = 1000
    params: Dict[str, Any] = Field(default_factory=dict)


class TaskSpec(BaseModel):
    """
    Single source of truth for an evaluation run.
    This should be buildable from DB rows and usable by both sim + real runners.
    """

    run_id: int
    backend: BackendName

    model: ModelRef
    dataset: DatasetRef
    suite: SuiteRef

    episodes: List[EpisodeSpec]
    metadata: Dict[str, Any] = Field(default_factory=dict)

    artifact_base_uri: str  # e.g. s3://artifacts/{run_id}/
    log_level: str = "INFO"
