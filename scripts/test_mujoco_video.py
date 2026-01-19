import mujoco
import numpy as np
import imageio.v2 as imageio
from pathlib import Path

XML = r"""
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


def main():
    model = mujoco.MjModel.from_xml_string(XML)
    data = mujoco.MjData(model)

    # Offscreen renderer (no viewer window)
    renderer = mujoco.Renderer(model, width=1280, height=720)

    frames = []
    sim_steps = 300  # 3 seconds @ dt=0.01

    for step in range(sim_steps):
        mujoco.mj_step(model, data)

        if step % 2 == 0:  # record every 2nd step (~50% fps)
            renderer.update_scene(data)
            img = renderer.render()
            frames.append(img.copy())

    out = Path("artifacts") / "demo_rollout.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)

    # Save MP4
    imageio.mimsave(out, frames, fps=30)
    print(f"Wrote video: {out.resolve()}  frames={len(frames)}")

if __name__ == "__main__":
    main()
