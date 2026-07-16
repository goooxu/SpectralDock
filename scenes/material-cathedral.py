#!/usr/bin/env python3
"""Material Cathedral: compare legacy and metallic-roughness transport."""

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
        look_from=(10.5, 4.0, 11.5),
        look_at=(0.0, 1.25, -1.0),
        up=(0.0, 1.0, 0.0),
        vfov=33.0,
        aperture=0.035,
        focus_distance=16.1,
    )
    renderer.background(type="constant", color=(0.002, 0.002, 0.004), exposure=0.0)

    limestone = renderer.material(
        name="limestone", type="lambertian", base_color=(0.48, 0.43, 0.36)
    )
    warm_wall = renderer.material(
        name="warm_wall", type="lambertian", base_color=(0.56, 0.31, 0.18)
    )
    cool_wall = renderer.material(
        name="cool_wall", type="lambertian", base_color=(0.12, 0.23, 0.34)
    )
    ceramic = renderer.material(
        name="ceramic",
        type="pbr",
        base_color=(0.93, 0.88, 0.75),
        metallic=0.0,
        roughness=0.28,
    )
    rough_metal = renderer.material(
        name="rough_metal",
        type="pbr",
        base_color=(0.74, 0.42, 0.18),
        metallic=1.0,
        roughness=0.34,
    )
    glass = renderer.material(
        name="glass", type="dielectric", base_color=(0.96, 0.99, 1.0), ior=1.52
    )
    plinth = renderer.material(
        name="plinth", type="metal", base_color=(0.14, 0.15, 0.17), roughness=0.22
    )
    key_emitter = renderer.material(
        name="key_emitter", type="emitter", emission=(13.0, 9.0, 5.2)
    )
    mascot = renderer.mesh(
        name="mascot", path=ROOT / "assets/examples/models/capsule-mascot.obj"
    )

    renderer.object(
        name="floor",
        type="rectangle",
        p1=(-8.0, 0.0, 6.0),
        p2=(-8.0, 0.0, -8.0),
        p3=(8.0, 0.0, -8.0),
        material=limestone,
    )
    renderer.object(
        name="back_wall",
        type="rectangle",
        p1=(-8.0, 0.0, -8.0),
        p2=(-8.0, 6.0, -8.0),
        p3=(8.0, 6.0, -8.0),
        material=warm_wall,
    )
    renderer.object(
        name="left_wall",
        type="rectangle",
        p1=(-8.0, 0.0, 6.0),
        p2=(-8.0, 6.0, 6.0),
        p3=(-8.0, 6.0, -8.0),
        material=cool_wall,
    )
    renderer.object(
        name="right_wall",
        type="rectangle",
        p1=(8.0, 0.0, -8.0),
        p2=(8.0, 6.0, -8.0),
        p3=(8.0, 6.0, 6.0),
        material=limestone,
    )
    renderer.object(
        name="ceiling",
        type="rectangle",
        p1=(-8.0, 6.0, 6.0),
        p2=(8.0, 6.0, 6.0),
        p3=(8.0, 6.0, -8.0),
        material=limestone,
    )

    for name, x, z, height, radius in (
        ("left_plinth", -3.2, -1.0, 0.72, 1.25),
        ("center_plinth", 0.0, -1.4, 0.88, 1.35),
        ("right_plinth", 3.2, -1.0, 0.72, 1.25),
    ):
        renderer.object(
            name=name,
            type="cylinder",
            base=(x, 0.0, z),
            axis=(0.0, 1.0, 0.0),
            height=height,
            radius=radius,
            material=plinth,
        )
        renderer.object(
            name=f"{name}_cap",
            type="disk",
            center=(x, height, z),
            normal=(0.0, 1.0, 0.0),
            radius=radius,
            material=plinth,
        )

    for name, material, translate, rotation in (
        ("ceramic_mascot", ceramic, (-3.2, 0.72, -1.0), (0.0, -24.0, 0.0)),
        ("metal_mascot", rough_metal, (0.0, 0.88, -1.4), (0.0, 18.0, 0.0)),
        ("glass_mascot", glass, (3.2, 0.72, -1.0), (0.0, 52.0, 0.0)),
    ):
        renderer.object(
            name=name,
            type="mesh",
            mesh=mascot,
            translate=translate,
            rotate_degrees=rotation,
            scale=(0.78, 0.78, 0.78),
            material=material,
        )

    main_light = renderer.object(
        name="main_light",
        type="rectangle",
        p1=(-2.4, 5.92, -1.0),
        p2=(2.4, 5.92, -1.0),
        p3=(2.4, 5.92, -3.0),
        front_material=key_emitter,
    )
    renderer.light(
        name="main_light_sample",
        type="rectangle",
        object=main_light,
        position=(-2.4, 5.92, -1.0),
        edge_u=(0.0, 0.0, -2.0),
        edge_v=(4.8, 0.0, 0.0),
        emission=(13.0, 9.0, 5.2),
    )
    renderer.light(
        name="round_fill_sample",
        type="disk",
        position=(-5.8, 3.0, 2.5),
        normal=(0.78, -0.18, -0.60),
        radius=1.05,
        emission=(2.4, 4.2, 7.5),
    )
    return renderer


def main() -> None:
    renderer = create_renderer()
    output = ROOT / "output/examples/material-cathedral.png"
    renderer.render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=1920,
        height=1080,
        spp=512,
        depth=12,
        seed=101,
        denoise=True,
    )


if __name__ == "__main__":
    main()
