#!/usr/bin/env python3
"""Celestial Archive: textured worlds around a bronze mascot."""

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
        look_from=(9.2, 4.8, 13.2),
        look_at=(0.0, 1.9, -1.2),
        up=(0.0, 1.0, 0.0),
        vfov=34.0,
        aperture=0.04,
        focus_distance=17.3,
    )
    renderer.background(
        type="sky",
        bottom=(0.035, 0.045, 0.08),
        top=(0.002, 0.006, 0.025),
        sun_direction=(-0.42, 0.76, -0.50),
        sun_color=(4.2, 2.9, 1.5),
        sun_cos_angle=0.996,
        exposure=0.25,
    )

    azure_planet = renderer.texture(
        name="azure_planet",
        type="image",
        path=ROOT / "assets/examples/textures/planet-azure.avif",
        color_space="srgb",
    )
    ember_planet = renderer.texture(
        name="ember_planet",
        type="image",
        path=ROOT / "assets/examples/textures/planet-ember.avif",
        color_space="srgb",
    )
    bronze = renderer.material(
        name="bronze", type="metal", base_color=(0.68, 0.34, 0.12), roughness=0.28
    )
    azure_surface = renderer.material(
        name="azure_surface",
        type="lambertian",
        texture=azure_planet,
        base_color=(1.0, 1.0, 1.0),
    )
    ember_surface = renderer.material(
        name="ember_surface",
        type="lambertian",
        texture=ember_planet,
        base_color=(1.0, 1.0, 1.0),
    )
    celestial_glass = renderer.material(
        name="celestial_glass",
        type="dielectric",
        base_color=(0.92, 0.97, 1.0),
        ior=1.47,
    )
    black_stone = renderer.material(
        name="black_stone",
        type="metal",
        base_color=(0.09, 0.08, 0.10),
        roughness=0.38,
    )
    archive_wall = renderer.material(
        name="archive_wall", type="lambertian", base_color=(0.16, 0.12, 0.17)
    )
    gold_light = renderer.material(
        name="gold_light", type="emitter", emission=(3.2, 1.6, 0.6)
    )
    mascot = renderer.mesh(
        name="mascot",
        path=ROOT / "assets/examples/models/capsule-mascot/capsule-mascot.obj",
    )

    renderer.object(
        name="archive_floor",
        type="rectangle",
        p1=(-9.0, 0.0, 7.0),
        p2=(-9.0, 0.0, -9.0),
        p3=(9.0, 0.0, -9.0),
        material=black_stone,
    )
    renderer.object(
        name="archive_back",
        type="rectangle",
        p1=(-9.0, 0.0, -9.0),
        p2=(-9.0, 7.0, -9.0),
        p3=(9.0, 7.0, -9.0),
        material=archive_wall,
    )
    renderer.object(
        name="mascot_dais",
        type="cylinder",
        base=(0.0, 0.0, -2.0),
        axis=(0.0, 1.0, 0.0),
        height=0.75,
        radius=2.35,
        material=black_stone,
    )
    renderer.object(
        name="mascot_dais_cap",
        type="disk",
        center=(0.0, 0.75, -2.0),
        normal=(0.0, 1.0, 0.0),
        radius=2.35,
        material=black_stone,
    )
    renderer.object(
        name="bronze_mascot",
        type="mesh",
        mesh=mascot,
        translate=(0.0, 0.75, -2.0),
        rotate_degrees=(0.0, 31.2, 0.0),
        scale=(1.3, 1.3, 1.3),
        material=bronze,
    )
    renderer.object(
        name="azure_world",
        type="sphere",
        center=(-4.0, 2.35, -1.0),
        radius=1.45,
        material=azure_surface,
    )
    renderer.object(
        name="ember_world",
        type="sphere",
        center=(4.1, 2.0, -2.0),
        radius=1.25,
        material=ember_surface,
    )
    renderer.object(
        name="glass_moon",
        type="sphere",
        center=(2.8, 4.35, -4.2),
        radius=0.72,
        material=celestial_glass,
    )
    golden_oculus = renderer.object(
        name="golden_oculus",
        type="disk",
        center=(0.0, 6.6, -8.85),
        normal=(0.0, 0.0, 1.0),
        radius=1.15,
        front_material=gold_light,
    )
    renderer.light(
        name="oculus_sample",
        type="disk",
        object=golden_oculus,
        position=(0.0, 6.6, -8.85),
        normal=(0.0, 0.0, 1.0),
        radius=1.15,
        emission=(3.2, 1.6, 0.6),
    )
    renderer.light(
        name="archive_fill",
        type="rectangle",
        position=(-3.0, 6.2, 1.0),
        edge_u=(0.0, 0.0, -2.5),
        edge_v=(6.0, 0.0, 0.0),
        emission=(3.0, 4.0, 7.0),
    )
    return renderer


def main() -> None:
    output = ROOT / "output/examples/celestial-archive.avif"
    create_renderer().render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=1920,
        height=1080,
        spp=512,
        depth=12,
        seed=303,
        denoise=True,
    )


if __name__ == "__main__":
    main()
