#!/usr/bin/env python3
"""Shared mesh, per-instance materials, transforms, UVs, and alpha smoke scene."""

from pathlib import Path

from spectraldock import Renderer


ROOT = Path(__file__).resolve().parents[2]


def create_renderer() -> Renderer:
    renderer = Renderer()
    renderer.integrator(
        direct_light_sampling="uniform", clamp_direct=0.0, clamp_indirect=0.0
    )
    renderer.camera(
        look_from=(0.0, 2.4, 7.0),
        look_at=(0.0, 0.8, -0.4),
        up=(0.0, 1.0, 0.0),
        vfov=38.0,
        aperture=0.0,
        focus_distance=7.0,
    )
    renderer.background(type="constant", color=(0.01, 0.015, 0.025), exposure=0.0)
    circuit = renderer.texture(
        name="circuit",
        type="image",
        path=ROOT / "assets/examples/textures/circuit-panel.png",
        color_space="srgb",
    )
    koi_alpha = renderer.texture(
        name="koi_alpha",
        type="image",
        path=ROOT / "assets/examples/textures/koi-mask.png",
        color_space="linear",
    )
    textured = renderer.material(name="textured", type="lambertian", texture=circuit)
    blue_metal = renderer.material(
        name="blue_metal", type="metal", base_color=(0.1, 0.45, 0.9), roughness=0.18
    )
    gray = renderer.material(
        name="gray", type="lambertian", base_color=(0.55, 0.58, 0.62)
    )
    mirror = renderer.material(
        name="mirror", type="metal", base_color=(0.92, 0.92, 0.92), roughness=0.04
    )
    uv_quad = renderer.mesh(name="uv_quad", path=ROOT / "tests/assets/uv-quad.obj")
    renderer.object(
        name="textured_alpha_instance",
        type="mesh",
        mesh=uv_quad,
        translate=(-1.15, 1.15, 0.0),
        rotate_degrees=(0.0, 18.0, 0.0),
        scale=(0.8, 0.8, 0.8),
        material=textured,
        alpha_texture=koi_alpha,
        alpha_cutoff=0.5,
    )
    renderer.object(
        name="metal_instance",
        type="mesh",
        mesh=uv_quad,
        translate=(1.15, 1.15, -0.2),
        rotate_degrees=(0.0, -24.0, 0.0),
        scale=(0.7, 0.9, 0.7),
        front_material=blue_metal,
        back_material=gray,
    )
    renderer.object(
        name="ground",
        type="rectangle",
        p1=(-3.0, 0.0, 2.0),
        p2=(-3.0, 0.0, -3.0),
        p3=(3.0, 0.0, -3.0),
        material=gray,
    )
    renderer.object(
        name="cylinder",
        type="cylinder",
        base=(-0.55, 0.0, -1.2),
        axis=(0.0, 1.0, 0.0),
        height=0.55,
        radius=0.28,
        material=gray,
    )
    renderer.object(
        name="disk_cap",
        type="disk",
        center=(-0.55, 0.55, -1.2),
        normal=(0.0, 1.0, 0.0),
        radius=0.28,
        material=gray,
    )
    renderer.object(
        name="parabolic_backface",
        type="parabola",
        origin=(0.9, 0.0, -1.8),
        normal=(0.0, 1.0, 0.0),
        focus=(0.9, 0.0, -1.55),
        clip_min=(-0.1, 0.0, -1.8),
        clip_max=(1.4, 1.0, 0.5),
        front_material=None,
        back_material=mirror,
    )
    renderer.light(
        name="rectangle_key",
        type="rectangle",
        position=(-1.5, 3.5, 1.0),
        edge_u=(1.4, 0.0, 0.0),
        edge_v=(0.0, 0.0, -1.0),
        emission=(12.0, 10.0, 8.0),
    )
    renderer.light(
        name="sphere_fill",
        type="sphere",
        position=(2.2, 2.4, 1.5),
        radius=0.25,
        emission=(4.0, 7.0, 12.0),
    )
    renderer.light(
        name="disk_rim",
        type="disk",
        position=(0.0, 2.8, -2.0),
        normal=(0.0, -0.5, 1.0),
        radius=0.3,
        emission=(9.0, 3.0, 8.0),
    )
    return renderer


def main() -> None:
    output = ROOT / "output/tests/mesh-composite-smoke.png"
    create_renderer().render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=64,
        height=64,
        spp=1,
        depth=6,
        seed=1,
        denoise=False,
    )


if __name__ == "__main__":
    main()
