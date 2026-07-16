#!/usr/bin/env python3
"""Point and directional light smoke scene with a soft disk fill."""

from pathlib import Path

from spectraldock import Renderer


ROOT = Path(__file__).resolve().parents[2]


def create_renderer() -> Renderer:
    renderer = Renderer()
    renderer.integrator(
        direct_light_sampling="importance", clamp_direct=64.0, clamp_indirect=16.0
    )
    renderer.camera(
        look_from=(3.2, 2.5, 6.2),
        look_at=(0.0, 0.75, -0.5),
        up=(0.0, 1.0, 0.0),
        vfov=34.0,
        aperture=0.0,
        focus_distance=7.5,
    )
    renderer.background(type="constant", color=(0.002, 0.003, 0.006), exposure=0.0)
    gray = renderer.material(
        name="gray", type="lambertian", base_color=(0.62, 0.64, 0.68)
    )
    blue = renderer.material(
        name="blue", type="lambertian", base_color=(0.08, 0.20, 0.55)
    )
    metal = renderer.material(
        name="metal", type="metal", base_color=(0.94, 0.90, 0.82), roughness=0.12
    )
    renderer.object(
        name="floor",
        type="rectangle",
        p1=(-3.5, 0.0, 2.5),
        p2=(-3.5, 0.0, -4.0),
        p3=(3.5, 0.0, -4.0),
        material=gray,
    )
    renderer.object(
        name="back",
        type="rectangle",
        p1=(-3.5, 0.0, -4.0),
        p2=(-3.5, 3.5, -4.0),
        p3=(3.5, 3.5, -4.0),
        material=blue,
    )
    renderer.object(
        name="metal_ball", type="sphere", center=(0.0, 0.82, -0.7), radius=0.82, material=metal
    )
    renderer.object(
        name="occluder",
        type="cylinder",
        base=(-1.1, 0.0, -1.1),
        axis=(0.0, 1.0, 0.0),
        height=1.7,
        radius=0.28,
        material=gray,
    )
    renderer.light(
        name="warm_point", type="point", position=(-1.5, 2.4, 1.2), intensity=(180.0, 62.0, 15.0)
    )
    renderer.light(
        name="cool_directional",
        type="directional",
        direction=(0.42, 0.78, 0.46),
        irradiance=(0.8, 1.15, 2.2),
    )
    renderer.light(
        name="soft_fill",
        type="disk",
        position=(2.2, 2.8, 0.8),
        normal=(-0.45, -0.75, -0.48),
        radius=0.45,
        emission=(3.0, 4.0, 6.0),
    )
    return renderer


def main() -> None:
    output = ROOT / "output/tests/delta-light-smoke.png"
    create_renderer().render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=64,
        height=64,
        spp=4,
        depth=6,
        seed=313,
        denoise=False,
    )


if __name__ == "__main__":
    main()
