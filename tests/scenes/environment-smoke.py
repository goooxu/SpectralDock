#!/usr/bin/env python3
"""HDR environment lookup and importance-sampling smoke scene."""

from pathlib import Path

from spectraldock import Renderer


ROOT = Path(__file__).resolve().parents[2]


def create_renderer() -> Renderer:
    renderer = Renderer()
    renderer.integrator(
        direct_light_sampling="importance", clamp_direct=0.0, clamp_indirect=0.0
    )
    renderer.camera(
        look_from=(0.0, 1.45, 4.8),
        look_at=(0.0, 1.05, -0.4),
        up=(0.0, 1.0, 0.0),
        vfov=34.0,
        aperture=0.0,
        focus_distance=5.2,
    )
    renderer.background(
        type="environment",
        path=ROOT / "assets/examples/environments/radiance-pavilion.hdr",
        intensity=0.8,
        rotation_degrees=22.5,
        exposure=-1.0,
    )
    matte = renderer.material(
        name="matte", type="lambertian", base_color=(0.72, 0.72, 0.72)
    )
    metal = renderer.material(
        name="metal", type="metal", base_color=(0.92, 0.82, 0.58), roughness=0.18
    )
    renderer.object(
        name="floor",
        type="rectangle",
        p1=(-3.0, 0.0, 2.0),
        p2=(-3.0, 0.0, -3.0),
        p3=(3.0, 0.0, -3.0),
        material=matte,
    )
    renderer.object(
        name="receiver",
        type="rectangle",
        p1=(-2.0, 0.0, -2.1),
        p2=(-2.0, 3.0, -2.1),
        p3=(2.0, 3.0, -2.1),
        material=matte,
    )
    renderer.object(
        name="metal_probe", type="sphere", center=(0.75, 0.72, -0.6), radius=0.72, material=metal
    )
    return renderer


def main() -> None:
    output = ROOT / "output/tests/environment-smoke.avif"
    create_renderer().render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=64,
        height=64,
        spp=4,
        depth=4,
        seed=109,
        denoise=False,
    )


if __name__ == "__main__":
    main()
