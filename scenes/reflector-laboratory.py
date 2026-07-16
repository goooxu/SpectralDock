#!/usr/bin/env python3
"""Reflector Laboratory: paraboloids, a point light, and a directional rim."""

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
        look_from=(8.6, 4.4, 11.8),
        look_at=(0.0, 1.35, -0.7),
        up=(0.0, 1.0, 0.0),
        vfov=36.0,
        aperture=0.028,
        focus_distance=15.5,
    )
    renderer.background(type="constant", color=(0.008, 0.011, 0.016), exposure=0.0)

    ceramic = renderer.material(
        name="ceramic", type="lambertian", base_color=(0.91, 0.94, 0.96)
    )
    mirror = renderer.material(
        name="mirror", type="metal", base_color=(0.96, 0.97, 0.98), roughness=0.025
    )
    anodized = renderer.material(
        name="anodized", type="metal", base_color=(0.16, 0.22, 0.30), roughness=0.24
    )
    floor = renderer.material(
        name="floor", type="lambertian", base_color=(0.20, 0.22, 0.24)
    )
    white_light = renderer.material(
        name="white_light", type="emitter", emission=(10.0, 9.4, 8.5)
    )
    mascot = renderer.mesh(
        name="mascot", path=ROOT / "assets/examples/models/capsule-mascot.obj"
    )

    renderer.object(
        name="lab_floor",
        type="rectangle",
        p1=(-7.0, 0.0, 6.0),
        p2=(-7.0, 0.0, -7.0),
        p3=(7.0, 0.0, -7.0),
        material=floor,
    )
    renderer.object(
        name="lab_back",
        type="rectangle",
        p1=(-7.0, 0.0, -7.0),
        p2=(-7.0, 5.5, -7.0),
        p3=(7.0, 5.5, -7.0),
        material=anodized,
    )
    renderer.object(
        name="mascot_stage",
        type="cylinder",
        base=(0.0, 0.0, -0.9),
        axis=(0.0, 1.0, 0.0),
        height=0.62,
        radius=1.55,
        material=anodized,
    )
    renderer.object(
        name="mascot_stage_cap",
        type="disk",
        center=(0.0, 0.62, -0.9),
        normal=(0.0, 1.0, 0.0),
        radius=1.55,
        material=anodized,
    )
    renderer.object(
        name="ceramic_mascot",
        type="mesh",
        mesh=mascot,
        translate=(0.0, 0.64, -0.9),
        rotate_degrees=(0.0, 24.0, 0.0),
        scale=(1.0, 1.0, 1.0),
        material=ceramic,
    )
    renderer.object(
        name="left_reflector",
        type="parabola",
        origin=(-2.25, 0.25, -1.15),
        normal=(0.0, 1.0, 0.0),
        focus=(-1.55, 0.25, -1.15),
        clip_min=(-2.55, 0.2, -2.75),
        clip_max=(-0.15, 3.4, 0.55),
        front_material=None,
        back_material=mirror,
    )
    renderer.object(
        name="right_reflector",
        type="parabola",
        origin=(2.25, 0.25, -1.15),
        normal=(0.0, 1.0, 0.0),
        focus=(1.55, 0.25, -1.15),
        clip_min=(0.15, 0.2, -2.75),
        clip_max=(2.55, 3.4, 0.55),
        front_material=None,
        back_material=mirror,
    )
    for name, x in (("left_column", -4.2), ("right_column", 4.2)):
        renderer.object(
            name=name,
            type="cylinder",
            base=(x, 0.0, -2.0),
            axis=(0.0, 1.0, 0.0),
            height=3.8,
            radius=0.32,
            material=anodized,
        )
    ceiling_panel = renderer.object(
        name="ceiling_panel",
        type="rectangle",
        p1=(-1.8, 5.2, 0.2),
        p2=(1.8, 5.2, 0.2),
        p3=(1.8, 5.2, -1.4),
        front_material=white_light,
    )
    renderer.light(
        name="rect_key",
        type="rectangle",
        object=ceiling_panel,
        position=(-1.8, 5.2, 0.2),
        edge_u=(0.0, 0.0, -1.6),
        edge_v=(3.6, 0.0, 0.0),
        emission=(10.0, 9.4, 8.5),
    )
    renderer.light(
        name="warm_focus_point",
        type="point",
        position=(-1.55, 1.45, -1.15),
        intensity=(32.0, 10.0, 2.5),
    )
    renderer.light(
        name="cool_directional_rim",
        type="directional",
        direction=(0.45, 0.78, -0.44),
        irradiance=(0.55, 0.8, 1.45),
    )
    return renderer


def main() -> None:
    output = ROOT / "output/examples/reflector-laboratory.png"
    create_renderer().render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=1920,
        height=1080,
        spp=512,
        depth=12,
        seed=404,
        denoise=True,
    )


if __name__ == "__main__":
    main()
