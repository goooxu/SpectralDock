#!/usr/bin/env python3
"""Directional GPU checks for analytic runtime water transport."""

from dataclasses import dataclass
import math
import sys
import tempfile
from pathlib import Path

from spectraldock import MaterialHandle, Renderer

from avif_test_utils import assert_avif_dimensions, captured_linear_image


POSITIVE_METRICS = (
    "water_height_evaluations",
    "water_tile_tests",
    "water_roots_reported",
    "water_medium_segments",
    "water_rough_nee_attempts",
    "water_rough_nee_contributions",
)
SAFETY_METRICS = (
    "water_solver_overflows",
    "water_medium_errors",
)


@dataclass(frozen=True)
class WaterMaterials:
    water: MaterialHandle
    receiver: MaterialHandle
    dark: MaterialHandle
    immersed_glass: MaterialHandle
    red_probe: MaterialHandle
    white_probe: MaterialHandle
    moon_probe: MaterialHandle


def new_renderer(roughness=0.12):
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
    materials = WaterMaterials(
        water=renderer.material(
            name="water",
            type="water",
            roughness=roughness,
            ior=1.333,
            absorption=(0.70, 0.20, 0.05),
        ),
        receiver=renderer.material(
            name="receiver", type="lambertian", base_color=(0.74, 0.74, 0.74)
        ),
        dark=renderer.material(
            name="dark", type="lambertian", base_color=(0.018, 0.020, 0.024)
        ),
        immersed_glass=renderer.material(
            name="immersed_glass",
            type="dielectric",
            base_color=(0.98, 0.99, 1.0),
            ior=1.52,
        ),
        red_probe=renderer.material(
            name="red_probe", type="emitter", emission=(18.0, 0.8, 0.25)
        ),
        white_probe=renderer.material(
            name="white_probe", type="emitter", emission=(9.0, 9.0, 9.0)
        ),
        moon_probe=renderer.material(
            name="moon_probe", type="emitter", emission=(16.0, 20.0, 30.0)
        ),
    )
    return renderer, materials


def add_pool(renderer, materials, *, floor=True, back=True):
    if floor:
        renderer.object(
            name="pool_floor",
            type="rectangle",
            p1=(-3.0, -1.45, 2.25),
            p2=(-3.0, -1.45, -3.25),
            p3=(3.0, -1.45, -3.25),
            material=materials.receiver,
        )
    if back:
        renderer.object(
            name="pool_back",
            type="rectangle",
            p1=(-3.0, -1.45, -3.25),
            p2=(-3.0, 2.8, -3.25),
            p3=(3.0, 2.8, -3.25),
            material=materials.dark,
        )
    renderer.object(
        name="pool_front",
        type="rectangle",
        p1=(-3.0, -1.45, 2.25),
        p2=(-3.0, 0.18, 2.25),
        p3=(3.0, 0.18, 2.25),
        material=materials.dark,
    )
    renderer.object(
        name="pool_left",
        type="rectangle",
        p1=(-3.0, -1.45, -3.25),
        p2=(-3.0, 0.18, -3.25),
        p3=(-3.0, 0.18, 2.25),
        material=materials.dark,
    )
    renderer.object(
        name="pool_right",
        type="rectangle",
        p1=(3.0, -1.45, 2.25),
        p2=(3.0, 0.18, 2.25),
        p3=(3.0, 0.18, -3.25),
        material=materials.dark,
    )


def add_water(renderer, materials):
    renderer.object(
        name="test_water",
        type="water_surface",
        center=(0.0, 0.0, -0.50),
        size=(6.0, 5.5),
        material=materials.water,
        waves=(
            {"direction": (1.0, 0.15), "amplitude": 0.050, "wavelength": 2.20, "phase_radians": 0.40},
            {"direction": (-0.25, 1.0), "amplitude": 0.032, "wavelength": 1.35, "phase_radians": 1.70},
            {"direction": (0.75, 1.0), "amplitude": 0.018, "wavelength": 0.82, "phase_radians": 3.20},
            {"direction": (-1.0, 0.30), "amplitude": 0.009, "wavelength": 0.52, "phase_radians": 5.10},
        ),
    )


def add_overhead(renderer):
    renderer.light(
        name="overhead",
        type="disk",
        position=(0.4, 2.8, 0.8),
        normal=(0.0, -1.0, 0.0),
        radius=0.70,
        emission=(20.0, 20.0, 20.0),
    )


def fixture_renderer(
    roughness=0.12, *, include_water=True, include_glass=True, include_moon=True
):
    renderer, materials = new_renderer(roughness)
    add_pool(renderer, materials)
    renderer.object(
        name="red_refractive_probe",
        type="sphere",
        center=(-0.95, -0.63, -0.55),
        radius=0.28,
        material=materials.red_probe,
    )
    renderer.object(
        name="shallow_probe",
        type="sphere",
        center=(0.20, -0.38, -1.45),
        radius=0.22,
        material=materials.white_probe,
    )
    renderer.object(
        name="deep_probe",
        type="sphere",
        center=(1.18, -1.08, -1.45),
        radius=0.22,
        material=materials.white_probe,
    )
    if include_glass:
        renderer.object(
            name="immersed_glass_probe",
            type="sphere",
            center=(0.72, -0.76, 0.10),
            radius=0.36,
            material=materials.immersed_glass,
        )
    if include_moon:
        renderer.object(
            name="moon_reflection_probe",
            type="sphere",
            center=(-0.25, 2.15, -2.35),
            radius=0.34,
            material=materials.moon_probe,
        )
    if include_water:
        add_water(renderer, materials)
    add_overhead(renderer)
    return renderer


def absorption_renderer(depth):
    renderer, materials = new_renderer(0.12)
    renderer.object(
        name="depth_probe",
        type="sphere",
        center=(0.0, depth, -0.55),
        radius=0.16,
        material=materials.white_probe,
    )
    add_pool(renderer, materials, floor=False, back=False)
    add_water(renderer, materials)
    return renderer


def direct_renderer(*, lit=True, blocked=False):
    renderer, materials = new_renderer(0.12)
    add_pool(renderer, materials)
    add_water(renderer, materials)
    if blocked:
        renderer.object(
            name="opaque_light_baffle",
            type="disk",
            center=(0.4, 1.55, 0.8),
            normal=(0.0, 1.0, 0.0),
            radius=0.78,
            material=materials.dark,
        )
    if lit:
        add_overhead(renderer)
    return renderer


def render(renderer, directory, name, spp=192, depth=8):
    image = directory / f"{name}.avif"
    stats = renderer.render(
        output=image,
        stats_output=image.with_suffix(".stats.json"),
        width=96,
        height=72,
        spp=spp,
        depth=depth,
        seed=83,
        denoise=False,
        _test_capture_linear=True,
    )
    assert_avif_dimensions(image, 96, 72)
    pixels = captured_linear_image(stats, 96, 72)
    assert_finite(stats)
    return pixels, stats


def assert_finite(value):
    if isinstance(value, dict):
        for child in value.values():
            assert_finite(child)
    elif isinstance(value, list):
        for child in value:
            assert_finite(child)
    elif isinstance(value, float) and not math.isfinite(value):
        raise RuntimeError("stats contain NaN or infinity")


def metric(tree, name):
    if isinstance(tree, dict):
        if name in tree:
            return tree[name]
        found = [metric(child, name) for child in tree.values()]
        found = [value for value in found if value is not None]
        if len(found) > 1:
            raise RuntimeError(f"duplicate stats metric: {name}")
        return found[0] if found else None
    if isinstance(tree, list):
        found = [metric(child, name) for child in tree]
        found = [value for value in found if value is not None]
        return found[0] if len(found) == 1 else None
    return None


def mean_luminance(image, box=None):
    source = image.crop(box) if box else image
    values = [
        0.2126 * red + 0.7152 * green + 0.0722 * blue
        for red, green, blue, _ in source.getdata()
    ]
    return sum(values) / len(values)


def channel_energy(image):
    total = [0.0, 0.0, 0.0]
    for pixel in image.getdata():
        for channel in range(3):
            total[channel] += pixel[channel]
    return tuple(total)


def mean_absolute_difference(first, second, box=None):
    left = first.crop(box) if box else first
    right = second.crop(box) if box else second
    total = 0.0
    for a, b in zip(left.getdata(), right.getdata()):
        total += sum(abs(a[channel] - b[channel]) for channel in range(3))
    return total / (3.0 * left.width * left.height)


def red_centroid(image):
    weighted_x = 0.0
    weighted_y = 0.0
    total = 0.0
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue, _ = image.getpixel((x, y))
            weight = max(0.0, red - 2.0 * max(green, blue))
            if red < 1.0e-6:
                continue
            weighted_x += x * weight
            weighted_y += y * weight
            total += weight
    if total <= 0.0:
        raise RuntimeError("red refractive probe was not visible")
    return weighted_x / total, weighted_y / total


def main():
    if len(sys.argv) != 1:
        raise RuntimeError("check_water_transport.py does not accept arguments")

    with tempfile.TemporaryDirectory(prefix="spectraldock-water-") as tmp:
        directory = Path(tmp)
        first, first_stats = render(fixture_renderer(), directory, "water-a")
        second, _ = render(fixture_renderer(), directory, "water-b")
        if first.samples() != second.samples():
            raise RuntimeError("fixed-seed water linear captures are not identical")

        for name in POSITIVE_METRICS:
            value = metric(first_stats, name)
            if value is None or value <= 0:
                raise RuntimeError(f"{name} must be positive for the water fixture")
        for name in SAFETY_METRICS:
            if metric(first_stats, name) != 0:
                raise RuntimeError(f"{name} must remain zero")
        if metric(first_stats, "water_delta_splits") != 0:
            raise RuntimeError("rough water must not use the smooth delta split")

        smooth_image, smooth_stats = render(
            fixture_renderer(0.0), directory, "water-smooth", spp=64
        )
        smooth_repeat, _ = render(
            fixture_renderer(0.0), directory, "water-smooth-repeat", spp=64
        )
        if smooth_image.samples() != smooth_repeat.samples():
            raise RuntimeError("smooth first-water Fresnel split is not deterministic")
        if metric(smooth_stats, "water_delta_splits") in (None, 0):
            raise RuntimeError("smooth water did not exercise the bounded delta split")
        for name in ("water_rough_nee_attempts", "water_rough_nee_contributions"):
            if metric(smooth_stats, name) != 0:
                raise RuntimeError(f"smooth delta water must not increment {name}")

        air_image, air_stats = render(
            fixture_renderer(include_water=False), directory, "water-off"
        )
        for name in POSITIVE_METRICS + SAFETY_METRICS + ("water_delta_splits",):
            if metric(air_stats, name) != 0:
                raise RuntimeError(f"{name} must be zero without water_surface")
        water_center = red_centroid(first)
        air_center = red_centroid(air_image)
        displacement = math.hypot(
            water_center[0] - air_center[0], water_center[1] - air_center[1]
        )
        if displacement <= 1.0:
            raise RuntimeError("water refraction did not displace the underwater probe")

        no_glass_image, _ = render(
            fixture_renderer(include_glass=False), directory, "immersed-glass-off"
        )
        glass_box = (40, 28, 76, 62)
        if mean_absolute_difference(first, no_glass_image, glass_box) <= 0.01:
            raise RuntimeError("immersed dielectric was not visible through water")

        dark_reflection, _ = render(
            fixture_renderer(include_moon=False), directory, "reflection-off", spp=128
        )
        water_box = (4, 28, 92, 70)
        if mean_luminance(first, water_box) <= mean_luminance(
            dark_reflection, water_box
        ) + 0.005:
            raise RuntimeError("rough water did not reflect the above-water emitter")

        shallow_image, _ = render(
            absorption_renderer(-0.42), directory, "absorption-shallow", spp=256
        )
        deep_image, _ = render(
            absorption_renderer(-1.15), directory, "absorption-deep", spp=256
        )
        shallow_energy = channel_energy(shallow_image)
        deep_energy = channel_energy(deep_image)
        if sum(deep_energy) >= 0.99 * sum(shallow_energy):
            raise RuntimeError("a deeper water path was not attenuated")
        shallow_red_blue = shallow_energy[0] / max(shallow_energy[2], 1.0e-12)
        deep_red_blue = deep_energy[0] / max(deep_energy[2], 1.0e-12)
        if deep_red_blue >= shallow_red_blue:
            raise RuntimeError("Beer absorption did not attenuate red more than blue")

        lit_floor, _ = render(direct_renderer(), directory, "direct-lit")
        unlit_floor, _ = render(
            direct_renderer(lit=False), directory, "direct-off"
        )
        receiver_box = (6, 28, 90, 71)
        if mean_luminance(lit_floor, receiver_box) <= mean_luminance(
            unlit_floor, receiver_box
        ) + 0.005:
            raise RuntimeError(
                "rough-water BSDF/NEE paths did not restore underwater illumination"
            )

        blocked_floor, _ = render(
            direct_renderer(blocked=True), directory, "direct-blocked"
        )
        if mean_luminance(blocked_floor, receiver_box) >= mean_luminance(
            lit_floor, receiver_box
        ):
            raise RuntimeError("opaque occluder did not reduce underwater direct light")

    print("runtime water transport checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
