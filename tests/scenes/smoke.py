#!/usr/bin/env python3
"""Minimal area-light rendering smoke scene."""

from pathlib import Path

from spectraldock import Renderer


ROOT = Path(__file__).resolve().parents[2]


def create_renderer() -> Renderer:
    renderer = Renderer()
    renderer.integrator(
        direct_light_sampling="importance", clamp_direct=0.0, clamp_indirect=0.0
    )
    renderer.camera(
        look_from=(3.0, 2.0, 5.0),
        look_at=(0.0, 0.5, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=38.0,
        aperture=0.0,
        focus_distance=5.0,
    )
    renderer.background(type="constant", color=(0.01, 0.01, 0.015), exposure=0.0)
    white = renderer.material(
        name="white", type="lambertian", base_color=(0.75, 0.75, 0.75)
    )
    red = renderer.material(
        name="red", type="lambertian", base_color=(0.75, 0.08, 0.05)
    )
    mirror = renderer.material(
        name="mirror", type="metal", base_color=(0.92, 0.92, 0.92), roughness=0.08
    )
    light = renderer.material(
        name="light", type="emitter", emission=(12.0, 10.0, 8.0)
    )
    renderer.object(
        name="floor",
        type="rectangle",
        p1=(-3.0, 0.0, 2.0),
        p2=(-3.0, 0.0, -3.0),
        p3=(3.0, 0.0, -3.0),
        material=white,
    )
    renderer.object(
        name="red_ball", type="sphere", center=(-0.7, 0.7, 0.0), radius=0.7, material=red
    )
    renderer.object(
        name="mirror_ball",
        type="sphere",
        center=(0.9, 0.5, -0.4),
        radius=0.5,
        material=mirror,
    )
    ceiling_light = renderer.object(
        name="ceiling_light",
        type="rectangle",
        p1=(-0.7, 3.0, -0.7),
        p2=(0.7, 3.0, -0.7),
        p3=(0.7, 3.0, 0.7),
        material=light,
    )
    renderer.light(
        name="ceiling_light_sample",
        type="rectangle",
        object=ceiling_light,
        position=(-0.7, 3.0, -0.7),
        edge_u=(1.4, 0.0, 0.0),
        edge_v=(0.0, 0.0, 1.4),
        emission=(12.0, 10.0, 8.0),
    )
    return renderer


def main() -> None:
    output = ROOT / "output/tests/smoke.png"
    create_renderer().render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=64,
        height=64,
        spp=4,
        depth=4,
        seed=1,
        denoise=False,
        validation=True,
    )


if __name__ == "__main__":
    main()
