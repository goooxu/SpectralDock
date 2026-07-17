#!/usr/bin/env python3
"""Moonlit Stepwell: analytic water under mixed moon and sconce lighting."""

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
        look_from=(5.0, 5.1, 11.2),
        look_at=(0.0, -0.25, -1.25),
        up=(0.0, 1.0, 0.0),
        vfov=36.0,
        aperture=0.0,
        focus_distance=13.8,
    )
    renderer.background(
        type="sky",
        bottom=(0.020, 0.028, 0.050),
        top=(0.002, 0.004, 0.015),
        sun_direction=(-0.25, 0.82, -0.51),
        sun_color=(0.0, 0.0, 0.0),
        sun_cos_angle=2.0,
        exposure=0.65,
    )

    dry_sandstone = renderer.material(
        name="dry_sandstone", type="lambertian", base_color=(0.42, 0.30, 0.18)
    )
    wet_sandstone = renderer.material(
        name="wet_sandstone", type="lambertian", base_color=(0.12, 0.15, 0.17)
    )
    pool_mosaic = renderer.material(
        name="pool_mosaic", type="lambertian", base_color=(0.045, 0.14, 0.17)
    )
    aged_bronze = renderer.material(
        name="aged_bronze", type="metal", base_color=(0.42, 0.24, 0.09), roughness=0.28
    )
    moon_ceramic = renderer.material(
        name="moon_ceramic", type="lambertian", base_color=(0.64, 0.61, 0.52)
    )
    moon_water = renderer.material(
        name="moon_water",
        type="water",
        roughness=0.12,
        ior=1.333,
        absorption=(0.42, 0.10, 0.035),
    )
    moon_emitter = renderer.material(
        name="moon_emitter", type="emitter", emission=(28.0, 34.0, 50.0)
    )
    sconce_emitter = renderer.material(
        name="sconce_emitter", type="emitter", emission=(9.0, 2.8, 0.7)
    )
    submerged_emitter = renderer.material(
        name="submerged_emitter", type="emitter", emission=(0.28, 1.05, 1.9)
    )
    mascot = renderer.mesh(
        name="mascot",
        path=ROOT / "assets/examples/models/capsule-mascot/capsule-mascot.obj",
    )

    def rectangle(name, p1, p2, p3, material):
        return renderer.object(
            name=name, type="rectangle", p1=p1, p2=p2, p3=p3, material=material
        )

    def cylinder(name, base, axis, height, radius, material):
        return renderer.object(
            name=name,
            type="cylinder",
            base=base,
            axis=axis,
            height=height,
            radius=radius,
            material=material,
        )

    def disk(name, center, normal, radius, material):
        return renderer.object(
            name=name,
            type="disk",
            center=center,
            normal=normal,
            radius=radius,
            material=material,
        )

    rectangle("pool_floor", (-3.4, -1.65, 1.7), (-3.4, -1.65, -3.7), (3.4, -1.65, -3.7), pool_mosaic)
    for values in (
        ("left_lower_walk", (-4.4, -0.10, 2.2), (-4.4, -0.10, -4.2), (-3.4, -0.10, -4.2), wet_sandstone),
        ("right_lower_walk", (3.4, -0.10, 2.2), (3.4, -0.10, -4.2), (4.4, -0.10, -4.2), wet_sandstone),
        ("left_middle_walk", (-5.4, 0.35, 2.8), (-5.4, 0.35, -4.8), (-4.4, 0.35, -4.8), dry_sandstone),
        ("right_middle_walk", (4.4, 0.35, 2.8), (4.4, 0.35, -4.8), (5.4, 0.35, -4.8), dry_sandstone),
        ("left_upper_walk", (-6.4, 0.80, 4.2), (-6.4, 0.80, -5.4), (-5.4, 0.80, -5.4), dry_sandstone),
        ("right_upper_walk", (5.4, 0.80, 4.2), (5.4, 0.80, -5.4), (6.4, 0.80, -5.4), dry_sandstone),
        ("front_lower_step", (-3.4, -0.10, 2.5), (-3.4, -0.10, 1.7), (3.4, -0.10, 1.7), wet_sandstone),
        ("front_middle_step", (-4.4, 0.35, 3.3), (-4.4, 0.35, 2.5), (4.4, 0.35, 2.5), dry_sandstone),
        ("front_upper_step", (-5.4, 0.80, 4.2), (-5.4, 0.80, 3.3), (5.4, 0.80, 3.3), dry_sandstone),
        ("back_lower_step", (-3.4, -0.10, -3.7), (-3.4, -0.10, -4.2), (3.4, -0.10, -4.2), wet_sandstone),
        ("back_middle_step", (-4.4, 0.35, -4.2), (-4.4, 0.35, -4.8), (4.4, 0.35, -4.8), dry_sandstone),
        ("back_upper_step", (-5.4, 0.80, -4.8), (-5.4, 0.80, -5.4), (5.4, 0.80, -5.4), dry_sandstone),
        ("front_lower_riser", (-3.4, -1.65, 1.7), (-3.4, -0.10, 1.7), (3.4, -0.10, 1.7), wet_sandstone),
        ("front_middle_riser", (-4.4, -0.10, 2.5), (-4.4, 0.35, 2.5), (4.4, 0.35, 2.5), dry_sandstone),
        ("front_upper_riser", (-5.4, 0.35, 3.3), (-5.4, 0.80, 3.3), (5.4, 0.80, 3.3), dry_sandstone),
        ("back_pool_riser", (-3.4, -1.65, -3.7), (-3.4, -0.10, -3.7), (3.4, -0.10, -3.7), wet_sandstone),
        ("left_pool_riser", (-3.4, -1.65, -3.7), (-3.4, -0.10, -3.7), (-3.4, -0.10, 1.7), wet_sandstone),
        ("right_pool_riser", (3.4, -1.65, 1.7), (3.4, -0.10, 1.7), (3.4, -0.10, -3.7), wet_sandstone),
        ("left_wall", (-6.4, 0.0, -5.4), (-6.4, 4.8, -5.4), (-6.4, 4.8, 4.2), dry_sandstone),
        ("right_wall", (6.4, 0.0, 4.2), (6.4, 4.8, 4.2), (6.4, 4.8, -5.4), dry_sandstone),
        ("back_wall", (-6.4, 0.0, -5.4), (-6.4, 5.2, -5.4), (6.4, 5.2, -5.4), dry_sandstone),
    ):
        rectangle(*values)

    cylinder("left_column", (-5.55, 0.8, -4.65), (0.0, 1.0, 0.0), 4.1, 0.27, aged_bronze)
    cylinder("right_column", (5.55, 0.8, -4.65), (0.0, 1.0, 0.0), 4.1, 0.27, aged_bronze)
    disk("left_brazier", (-5.55, 4.9, -4.65), (0.0, 1.0, 0.0), 0.42, aged_bronze)
    disk("right_brazier", (5.55, 4.9, -4.65), (0.0, 1.0, 0.0), 0.42, aged_bronze)
    cylinder("central_dais", (0.0, -1.65, -1.0), (0.0, 1.0, 0.0), 2.35, 0.82, wet_sandstone)
    disk("central_dais_cap", (0.0, 0.70, -1.0), (0.0, 1.0, 0.0), 0.82, dry_sandstone)
    renderer.object(
        name="submerged_bronze_orb",
        type="sphere",
        center=(-1.65, -0.98, -1.20),
        radius=0.42,
        material=aged_bronze,
    )
    renderer.object(
        name="submerged_ceramic_orb",
        type="sphere",
        center=(1.55, -1.02, -0.55),
        radius=0.38,
        material=moon_ceramic,
    )
    submerged_marker = renderer.object(
        name="submerged_marker",
        type="sphere",
        center=(0.35, -1.28, -2.95),
        radius=0.12,
        material=submerged_emitter,
    )
    left_sconce = disk(
        "left_sconce", (-6.35, 2.65, -1.55), (1.0, 0.0, 0.0), 0.24, sconce_emitter
    )
    right_sconce = disk(
        "right_sconce", (6.35, 2.65, -1.55), (-1.0, 0.0, 0.0), 0.24, sconce_emitter
    )
    renderer.object(
        name="moon_pool",
        type="water_surface",
        center=(0.0, -0.35, -1.0),
        size=(6.8, 5.4),
        material=moon_water,
        waves=(
            {"direction": (1.0, 0.25), "amplitude": 0.070, "wavelength": 2.60, "phase_radians": 0.35},
            {"direction": (-0.35, 1.0), "amplitude": 0.045, "wavelength": 1.60, "phase_radians": 1.75},
            {"direction": (0.70, 1.0), "amplitude": 0.025, "wavelength": 1.00, "phase_radians": 3.10},
            {"direction": (-1.0, 0.15), "amplitude": 0.012, "wavelength": 0.65, "phase_radians": 5.20},
        ),
    )
    renderer.object(
        name="stepwell_observer",
        type="mesh",
        mesh=mascot,
        translate=(0.0, 0.70, -1.0),
        rotate_degrees=(0.0, 28.0, 0.0),
        scale=(0.82, 0.82, 0.82),
        material=moon_ceramic,
    )
    moon_disk = disk(
        "moon_disk", (-2.8, 4.6, -5.1), (0.0, -0.3, 0.953939), 0.75, moon_emitter
    )

    renderer.light(
        name="moon_key",
        type="disk",
        object=moon_disk,
        position=(-2.8, 4.6, -5.1),
        normal=(0.0, -0.3, 0.953939),
        radius=0.75,
        emission=(28.0, 34.0, 50.0),
    )
    renderer.light(
        name="left_warm_sconce",
        type="disk",
        object=left_sconce,
        position=(-6.35, 2.65, -1.55),
        normal=(1.0, 0.0, 0.0),
        radius=0.24,
        emission=(9.0, 2.8, 0.7),
    )
    renderer.light(
        name="right_warm_sconce",
        type="disk",
        object=right_sconce,
        position=(6.35, 2.65, -1.55),
        normal=(-1.0, 0.0, 0.0),
        radius=0.24,
        emission=(9.0, 2.8, 0.7),
    )
    renderer.light(
        name="underwater_cyan",
        type="sphere",
        object=submerged_marker,
        position=(0.35, -1.28, -2.95),
        radius=0.12,
        emission=(0.28, 1.05, 1.9),
    )
    return renderer


def main() -> None:
    output = ROOT / "output/examples/moonlit-stepwell.png"
    create_renderer().render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=1920,
        height=1080,
        spp=512,
        depth=12,
        seed=808,
        denoise=True,
    )


if __name__ == "__main__":
    main()
