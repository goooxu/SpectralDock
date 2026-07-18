#!/usr/bin/env python3
"""Analytic rough-water refraction, absorption, and NEE smoke scene."""

from pathlib import Path

from spectraldock import Renderer


ROOT = Path(__file__).resolve().parents[2]


def create_renderer() -> Renderer:
    renderer = Renderer()
    renderer.integrator(
        direct_light_sampling="importance", clamp_direct=0.0, clamp_indirect=0.0
    )
    renderer.camera(
        look_from=(3.6, 3.0, 6.5),
        look_at=(0.0, -0.35, -0.65),
        up=(0.0, 1.0, 0.0),
        vfov=36.0,
        aperture=0.0,
        focus_distance=8.6,
    )
    renderer.background(type="constant", color=(0.0, 0.0, 0.0), exposure=0.0)
    water = renderer.material(
        name="water",
        type="water",
        roughness=0.12,
        ior=1.333,
        absorption=(0.70, 0.20, 0.05),
    )
    receiver = renderer.material(
        name="receiver", type="lambertian", base_color=(0.74, 0.74, 0.74)
    )
    dark = renderer.material(
        name="dark", type="lambertian", base_color=(0.018, 0.020, 0.024)
    )
    immersed_glass = renderer.material(
        name="immersed_glass",
        type="dielectric",
        base_color=(0.98, 0.99, 1.0),
        ior=1.52,
    )
    red_probe = renderer.material(
        name="red_probe", type="emitter", emission=(18.0, 0.8, 0.25)
    )
    white_probe = renderer.material(
        name="white_probe", type="emitter", emission=(9.0, 9.0, 9.0)
    )
    moon_probe = renderer.material(
        name="moon_probe", type="emitter", emission=(16.0, 20.0, 30.0)
    )

    def rectangle(name, p1, p2, p3, material):
        renderer.object(name=name, type="rectangle", p1=p1, p2=p2, p3=p3, material=material)

    rectangle("pool_floor", (-3.0, -1.45, 2.25), (-3.0, -1.45, -3.25), (3.0, -1.45, -3.25), receiver)
    rectangle("pool_back", (-3.0, -1.45, -3.25), (-3.0, 2.8, -3.25), (3.0, 2.8, -3.25), dark)
    rectangle("pool_front", (-3.0, -1.45, 2.25), (-3.0, 0.18, 2.25), (3.0, 0.18, 2.25), dark)
    rectangle("pool_left", (-3.0, -1.45, -3.25), (-3.0, 0.18, -3.25), (-3.0, 0.18, 2.25), dark)
    rectangle("pool_right", (3.0, -1.45, 2.25), (3.0, 0.18, 2.25), (3.0, 0.18, -3.25), dark)
    for name, center, radius, material in (
        ("red_refractive_probe", (-0.95, -0.63, -0.55), 0.28, red_probe),
        ("shallow_probe", (0.20, -0.38, -1.45), 0.22, white_probe),
        ("deep_probe", (1.18, -1.08, -1.45), 0.22, white_probe),
        ("immersed_glass_probe", (0.72, -0.76, 0.10), 0.36, immersed_glass),
        ("moon_reflection_probe", (-0.25, 2.15, -2.35), 0.34, moon_probe),
    ):
        renderer.object(name=name, type="sphere", center=center, radius=radius, material=material)
    renderer.object(
        name="test_water",
        type="water_surface",
        center=(0.0, 0.0, -0.50),
        size=(6.0, 5.5),
        material=water,
        waves=(
            {"direction": (1.0, 0.15), "amplitude": 0.050, "wavelength": 2.20, "phase_radians": 0.40},
            {"direction": (-0.25, 1.0), "amplitude": 0.032, "wavelength": 1.35, "phase_radians": 1.70},
            {"direction": (0.75, 1.0), "amplitude": 0.018, "wavelength": 0.82, "phase_radians": 3.20},
            {"direction": (-1.0, 0.30), "amplitude": 0.009, "wavelength": 0.52, "phase_radians": 5.10},
        ),
    )
    renderer.light(
        name="overhead",
        type="disk",
        position=(0.4, 2.8, 0.8),
        normal=(0.0, -1.0, 0.0),
        radius=0.70,
        emission=(20.0, 20.0, 20.0),
    )
    return renderer


def main() -> None:
    output = ROOT / "output/tests/water-smoke.avif"
    create_renderer().render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=96,
        height=72,
        spp=256,
        depth=8,
        seed=83,
        denoise=False,
    )


if __name__ == "__main__":
    main()
