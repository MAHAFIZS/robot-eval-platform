from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    UniqueConstraint,
    Index,
    func,
)
from sqlalchemy.orm import relationship

# Adjust this import to match your project’s Base location
from packages.backend.db.base import Base


class Episode(Base):
    __tablename__ = "episodes"

    id = Column(Integer, primary_key=True, autoincrement=True)

    run_id = Column(Integer, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    episode_index = Column(Integer, nullable=False)

    # Core metrics (nullable because not every backend/task yields all metrics)
    success = Column(Boolean, nullable=True)
    time_to_success_s = Column(Float, nullable=True)
    collision_count = Column(Integer, nullable=True)
    safety_violation = Column(Boolean, nullable=True)
    reward_total = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationship back to Run (adjust "Run" / run model import if needed)
    run = relationship("Run", back_populates="episodes")

    __table_args__ = (
        UniqueConstraint("run_id", "episode_index", name="uq_episodes_run_id_episode_index"),
        Index("ix_episodes_run_id", "run_id"),
        Index("ix_episodes_run_id_success", "run_id", "success"),
    )
