from __future__ import annotations

from pathlib import Path
from typing import List

import mujoco
import imageio.v2 as imageio


def render_rollout_mp4(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    out_path: str | Path,
    sim_steps: int,
    fps: int = 30,
    width: int = 1280,
    height: int = 720,
    record_every: int = 2,
) -> Path:
    """
    Render an offscreen MP4 of the simulation as it runs.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    renderer = mujoco.Renderer(model, width=width, height=height)

    frames: List = []
    for step in range(sim_steps):
        mujoco.mj_step(model, data)

        if step % record_every == 0:
            renderer.update_scene(data)
            img = renderer.render()
            frames.append(img.copy())

    imageio.mimsave(out, frames, fps=fps)
    return out
