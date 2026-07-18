#!/usr/bin/env python3
"""Procedural flame emission, absorption, and dielectric-path smoke scene."""

from pathlib import Path

from spectraldock import Renderer


ROOT = Path(__file__).resolve().parents[2]


def create_renderer() -> Renderer:
    renderer = Renderer()
    renderer.integrator(
        direct_light_sampling="importance", clamp_direct=0.0, clamp_indirect=0.0
    )
    renderer.camera(
        look_from=(0.0, 1.35, 6.0),
        look_at=(0.0, 1.15, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=35.0,
        aperture=0.0,
        focus_distance=6.0,
    )
    renderer.background(type="constant", color=(0.0, 0.0, 0.0), exposure=0.0)
    receiver = renderer.material(
        name="receiver", type="lambertian", base_color=(0.72, 0.72, 0.72)
    )
    floor = renderer.material(
        name="floor", type="lambertian", base_color=(0.24, 0.25, 0.27)
    )
    renderer.material(
        name="occluder", type="lambertian", base_color=(0.015, 0.015, 0.018)
    )
    glass = renderer.material(
        name="glass", type="dielectric", base_color=(0.98, 0.99, 1.0), ior=1.5
    )
    renderer.material(
        name="area_emitter", type="emitter", emission=(24.0, 22.0, 18.0)
    )
    renderer.object(
        name="floor",
        type="rectangle",
        p1=(-3.2, 0.0, 2.0),
        p2=(-3.2, 0.0, -2.0),
        p3=(3.2, 0.0, -2.0),
        material=floor,
    )
    renderer.object(
        name="left_receiver",
        type="rectangle",
        p1=(-2.75, 0.0, 0.0),
        p2=(-2.75, 2.5, 0.0),
        p3=(-1.0, 2.5, 0.0),
        material=receiver,
    )
    renderer.object(
        name="glass_probe", type="sphere", center=(0.95, 1.25, 1.0), radius=0.48, material=glass
    )
    renderer.light(
        name="fixture_flame",
        type="flame",
        position=(0.95, 0.5, 0.0),
        axis=(0.0, 1.0, 0.0),
        height=1.65,
        radius_start=0.26,
        radius_end=0.48,
        emission_start=(52.0, 67.0, 92.0),
        emission_end=(26.0, 5.0, 0.35),
        extinction=2.6,
        density_scale=1.0,
        turbulence=0.36,
        noise_scale=2.0,
        seed=71,
    )
    return renderer


def main() -> None:
    output = ROOT / "output/tests/flame-smoke.avif"
    create_renderer().render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=64,
        height=64,
        spp=128,
        depth=3,
        seed=71,
        denoise=False,
    )


if __name__ == "__main__":
    main()
