#!/usr/bin/env python3
"""Neon Koi: emissive alpha-cut rectangles in a dark gallery."""

from pathlib import Path

from spectraldock import Renderer


ROOT = Path(__file__).resolve().parents[1]


def create_renderer() -> Renderer:
    renderer = Renderer()
    renderer.integrator(
        direct_light_sampling="importance",
        clamp_direct=64.0,
        clamp_indirect=16.0,
    )
    renderer.camera(
        look_from=(0.0, 3.1, 10.8),
        look_at=(0.0, 2.0, -2.3),
        up=(0.0, 1.0, 0.0),
        vfov=39.0,
        aperture=0.11,
        focus_distance=13.2,
    )
    renderer.background(type="constant", color=(0.001, 0.002, 0.006), exposure=-0.25)

    circuit = renderer.texture(
        name="circuit",
        type="image",
        path=ROOT / "assets/examples/textures/circuit-panel.png",
        color_space="srgb",
    )
    koi = renderer.texture(
        name="koi",
        type="image",
        path=ROOT / "assets/examples/textures/koi-mask.png",
        color_space="srgb",
    )
    circuit_wall = renderer.material(
        name="circuit_wall",
        type="lambertian",
        texture=circuit,
        base_color=(1.0, 1.0, 1.0),
    )
    wet_floor = renderer.material(
        name="wet_floor",
        type="metal",
        base_color=(0.08, 0.11, 0.14),
        roughness=0.12,
    )
    dark_wall = renderer.material(
        name="dark_wall", type="lambertian", base_color=(0.015, 0.02, 0.03)
    )
    koi_glow = renderer.material(
        name="koi_glow", type="emitter", texture=koi, emission=(3.8, 1.2, 0.38)
    )
    cyan_glow = renderer.material(
        name="cyan_glow", type="emitter", emission=(0.4, 8.0, 12.0)
    )
    magenta_glow = renderer.material(
        name="magenta_glow", type="emitter", emission=(11.0, 0.35, 6.8)
    )
    mascot = renderer.mesh(
        name="mascot", path=ROOT / "assets/examples/models/capsule-mascot.obj"
    )

    for name, p1, p2, p3, material in (
        ("floor", (-7.0, 0.0, 6.0), (-7.0, 0.0, -6.0), (7.0, 0.0, -6.0), wet_floor),
        (
            "circuit_backdrop",
            (-7.0, 0.0, -4.0),
            (-7.0, 5.5, -4.0),
            (7.0, 5.5, -4.0),
            circuit_wall,
        ),
        ("left_wall", (-7.0, 0.0, 6.0), (-7.0, 5.5, 6.0), (-7.0, 5.5, -4.0), dark_wall),
        ("right_wall", (7.0, 0.0, -4.0), (7.0, 5.5, -4.0), (7.0, 5.5, 6.0), dark_wall),
    ):
        renderer.object(name=name, type="rectangle", p1=p1, p2=p2, p3=p3, material=material)

    for name, p1, p2, p3 in (
        ("koi_left", (-4.0, 0.45, -3.82), (-4.0, 4.65, -3.82), (-1.2, 4.65, -3.82)),
        ("koi_right", (0.9, 0.7, -3.78), (0.9, 4.9, -3.78), (3.7, 4.9, -3.78)),
    ):
        renderer.object(
            name=name,
            type="rectangle",
            p1=p1,
            p2=p2,
            p3=p3,
            material=koi_glow,
            alpha_texture=koi,
            alpha_cutoff=0.04,
        )

    renderer.object(
        name="cyan_strip",
        type="rectangle",
        p1=(-6.9, 0.7, -2.5),
        p2=(-6.9, 4.6, -2.5),
        p3=(-6.9, 4.6, -1.9),
        front_material=cyan_glow,
    )
    renderer.object(
        name="magenta_strip",
        type="rectangle",
        p1=(6.9, 0.7, -1.0),
        p2=(6.9, 4.6, -1.0),
        p3=(6.9, 4.6, -1.6),
        front_material=magenta_glow,
    )
    renderer.object(
        name="metal_mascot",
        type="mesh",
        mesh=mascot,
        translate=(0.1, 0.0, 0.4),
        rotate_degrees=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
        material=wet_floor,
    )
    renderer.light(
        name="cyan_area",
        type="rectangle",
        position=(-6.8, 0.8, -2.7),
        edge_u=(0.0, 3.7, 0.0),
        edge_v=(0.0, 0.0, 2.2),
        emission=(0.5, 7.0, 11.0),
    )
    renderer.light(
        name="magenta_area",
        type="rectangle",
        position=(6.8, 0.8, 0.0),
        edge_u=(0.0, 3.7, 0.0),
        edge_v=(0.0, 0.0, -2.2),
        emission=(10.0, 0.4, 6.0),
    )
    renderer.light(
        name="soft_top",
        type="disk",
        position=(0.0, 5.3, 0.0),
        normal=(0.0, -1.0, -0.1),
        radius=1.8,
        emission=(1.0, 1.1, 1.5),
    )
    return renderer


def main() -> None:
    output = ROOT / "output/examples/neon-koi.png"
    create_renderer().render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=1920,
        height=1080,
        spp=512,
        depth=12,
        seed=202,
        denoise=True,
    )


if __name__ == "__main__":
    main()
