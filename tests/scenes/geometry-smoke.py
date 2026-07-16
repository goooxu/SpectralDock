#!/usr/bin/env python3
"""Primitive, alpha any-hit, and one-sided parabola smoke scene."""

from pathlib import Path

from spectraldock import Renderer


ROOT = Path(__file__).resolve().parents[2]


def create_renderer() -> Renderer:
    renderer = Renderer()
    renderer.integrator(
        direct_light_sampling="importance", clamp_direct=0.0, clamp_indirect=0.0
    )
    renderer.camera(
        look_from=(3.0, 3.0, 7.0),
        look_at=(0.5, 0.4, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=28.0,
        aperture=0.0,
        focus_distance=7.5,
    )
    renderer.background(type="constant", color=(0.01, 0.01, 0.015), exposure=0.0)
    opaque_mask = renderer.texture(
        name="opaque_mask", type="constant", color=(1.0, 1.0, 1.0)
    )
    gray = renderer.material(
        name="gray", type="lambertian", base_color=(0.68, 0.68, 0.68)
    )
    red = renderer.material(
        name="red", type="lambertian", base_color=(0.75, 0.05, 0.04)
    )
    metal = renderer.material(
        name="metal", type="metal", base_color=(0.9, 0.9, 0.9), roughness=0.08
    )
    glass = renderer.material(
        name="glass", type="dielectric", base_color=(0.98, 0.99, 1.0), ior=1.5
    )
    renderer.object(
        name="ground",
        type="rectangle",
        p1=(-2.0, 0.0, 2.0),
        p2=(-2.0, 0.0, -3.0),
        p3=(2.5, 0.0, -3.0),
        material=gray,
    )
    renderer.object(
        name="alpha_panel",
        type="sketch",
        p1=(-1.2, 0.05, 0.8),
        p2=(-1.2, 1.35, 0.8),
        p3=(-0.4, 1.35, 0.8),
        material=red,
        alpha_texture=opaque_mask,
    )
    renderer.object(
        name="glass_ball", type="sphere", center=(-0.6, 0.55, -0.2), radius=0.55, material=glass
    )
    renderer.object(
        name="short_cylinder",
        type="cylinder",
        base=(0.7, 0.0, 0.5),
        axis=(0.0, 1.0, 0.0),
        height=0.7,
        radius=0.35,
        material=gray,
    )
    renderer.object(
        name="cylinder_cap",
        type="disk",
        center=(0.7, 0.7, 0.5),
        normal=(0.0, 1.0, 0.0),
        radius=0.35,
        material=gray,
    )
    renderer.object(
        name="parabolic_mirror",
        type="parabola",
        origin=(1.0, 0.0, -2.0),
        normal=(0.0, 1.0, 0.0),
        focus=(1.0, 0.0, -1.75),
        clip_min=(-1.0, 0.0, -2.0),
        clip_max=(1.5, 1.3, 2.0),
        front_material=None,
        back_material=metal,
    )
    renderer.light(
        name="sphere_key",
        type="sphere",
        position=(-0.8, 2.5, 0.2),
        radius=0.18,
        emission=(18.0, 15.0, 10.0),
    )
    renderer.light(
        name="disk_fill",
        type="disk",
        position=(1.8, 2.2, 1.0),
        normal=(-0.5, -0.8, -0.2),
        radius=0.35,
        emission=(4.0, 6.0, 10.0),
    )
    return renderer


def main() -> None:
    output = ROOT / "output/tests/geometry-smoke.png"
    create_renderer().render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=64,
        height=64,
        spp=4,
        depth=8,
        seed=19,
        denoise=False,
    )


if __name__ == "__main__":
    main()
