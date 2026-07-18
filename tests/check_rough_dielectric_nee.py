#!/usr/bin/env python3
"""GPU checks for rough dielectric NEE/MIS and transparent blockers.

The checks compare the private pre-display linear capture and decode the HDR
AVIF once per render so the public output contract is exercised as well.
"""

import math
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

from spectraldock import Renderer

from avif_test_utils import assert_avif_dimensions, captured_linear_rgb


WIDTH = 96
HEIGHT = 72
WATER_ROI = (5, 27, 91, 70)
RECEIVER_ROI = (18, 10, 78, 58)
GLASS_ROI = (23, 11, 73, 61)
GLASS_TRANSMISSION_ROI = (34, 22, 62, 50)


class SampleProfile(NamedTuple):
    high_spp: int
    low_spp: int
    depth_one_spp: int
    blocked_spp: int
    restored_spp: int
    beer_spp: int
    glass_reflection_spp: int
    glass_transmission_spp: int
    tir_spp: int


# Keep every transport branch and assertion while avoiding an 8192-spp
# maintainer-only convergence pass in routine acceptance.
SAMPLE_PROFILE = SampleProfile(2048, 32, 64, 64, 256, 256, 64, 128, 128)


def render(renderer, directory, name, spp, depth, seed):
    avif = directory / f"{name}.avif"
    stats = renderer.render(
        output=avif,
        stats_output=avif.with_suffix(".stats.json"),
        width=WIDTH,
        height=HEIGHT,
        spp=spp,
        depth=depth,
        seed=seed,
        denoise=False,
        _test_capture_linear=True,
    )
    assert_avif_dimensions(avif, WIDTH, HEIGHT)
    pixels, linear_values = captured_linear_rgb(stats, WIDTH, HEIGHT)
    return pixels, stats, linear_values


def metric(tree, name):
    if isinstance(tree, dict):
        if name in tree:
            return tree[name]
        values = [metric(value, name) for value in tree.values()]
    elif isinstance(tree, list):
        values = [metric(value, name) for value in tree]
    else:
        return None
    values = [value for value in values if value is not None]
    if len(values) > 1:
        raise RuntimeError(f"duplicate metric {name}")
    return values[0] if values else None


def roi_values(pixels, box):
    left, top, right, bottom = box
    return [
        pixels[y * WIDTH + x]
        for y in range(top, bottom)
        for x in range(left, right)
    ]


def luminance(pixel):
    return 0.2126 * pixel[0] + 0.7152 * pixel[1] + 0.0722 * pixel[2]


def mean_luminance(pixels, box):
    values = roi_values(pixels, box)
    return sum(luminance(pixel) for pixel in values) / len(values)


def mean_rgb(pixels, box):
    values = roi_values(pixels, box)
    return tuple(sum(pixel[c] for pixel in values) / len(values) for c in range(3))


def mse(pixels, reference, box):
    left = roi_values(pixels, box)
    right = roi_values(reference, box)
    return sum(
        (a - b) * (a - b)
        for first, second in zip(left, right)
        for a, b in zip(first, second)
    ) / (3.0 * len(left))


def relative_mean_error(first, second, box):
    a = mean_luminance(first, box)
    b = mean_luminance(second, box)
    return abs(a - b) / max(abs(a), abs(b), 1.0e-6)


def reflection_renderer(bound):
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
        roughness=0.30,
        ior=1.333,
        absorption=(0.70, 0.20, 0.05),
    )
    moon_probe = renderer.material(
        name="moon_probe", type="emitter", emission=(16.0, 20.0, 30.0)
    )
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
    disk_center = (-3.0, 2.5, -6.3)
    disk_normal = (0.429, -0.358, 0.829)
    disk_radius = 0.55
    reflection_disk = renderer.object(
        name="reflection_disk",
        type="disk",
        center=disk_center,
        normal=disk_normal,
        radius=disk_radius,
        front_material=moon_probe,
    )
    if bound:
        renderer.light(
            name="bound_reflection_disk",
            type="disk",
            object=reflection_disk,
            position=disk_center,
            normal=disk_normal,
            radius=disk_radius,
            emission=(16.0, 20.0, 30.0),
        )
    return renderer


def blocker_renderer(light_depth=-0.85):
    renderer = Renderer()
    renderer.integrator(
        direct_light_sampling="importance", clamp_direct=0.0, clamp_indirect=0.0
    )
    renderer.camera(
        look_from=(0.0, 1.25, 4.2),
        look_at=(0.0, 1.0, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=30.0,
        aperture=0.0,
        focus_distance=4.2,
    )
    renderer.background(type="constant", color=(0.0, 0.0, 0.0), exposure=0.0)
    water = renderer.material(
        name="water",
        type="water",
        ior=1.333,
        roughness=0.20,
        absorption=(0.9, 0.22, 0.04),
    )
    receiver = renderer.material(
        name="receiver", type="lambertian", base_color=(0.82, 0.82, 0.82)
    )
    dark = renderer.material(
        name="dark", type="lambertian", base_color=(0.005, 0.005, 0.005)
    )
    source = renderer.material(
        name="source", type="emitter", emission=(35.0, 35.0, 35.0)
    )
    renderer.object(
        name="receiver",
        type="rectangle",
        p1=(-1.5, 0.25, 0.0),
        p2=(-1.5, 1.9, 0.0),
        p3=(1.5, 1.9, 0.0),
        material=receiver,
    )
    underwater_source = renderer.object(
        name="underwater_source",
        type="sphere",
        center=(0.0, light_depth, 1.65),
        radius=0.42,
        material=source,
    )
    renderer.object(
        name="floor",
        type="rectangle",
        p1=(-3.0, -2.0, 3.0),
        p2=(-3.0, -2.0, -3.0),
        p3=(3.0, -2.0, -3.0),
        material=dark,
    )
    renderer.object(
        name="test_water",
        type="water_surface",
        center=(0.0, 0.0, 1.0),
        size=(6.0, 6.0),
        material=water,
        waves=(
            {"direction": (1.0, 0.2), "amplitude": 0.015, "wavelength": 2.4, "phase_radians": 0.3},
            {"direction": (-0.3, 1.0), "amplitude": 0.008, "wavelength": 1.1, "phase_radians": 1.7},
        ),
    )
    renderer.light(
        name="underwater_light",
        type="sphere",
        object=underwater_source,
        position=(0.0, light_depth, 1.65),
        radius=0.42,
        emission=(35.0, 35.0, 35.0),
    )
    return renderer


def generic_glass_renderer(mode, ior=1.52):
    inside = mode == "inside_tir"
    renderer = Renderer()
    renderer.integrator(
        direct_light_sampling="importance", clamp_direct=0.0, clamp_indirect=0.0
    )
    renderer.camera(
        look_from=(0.0, 0.0, 0.78) if inside else (0.0, 0.0, 4.0),
        look_at=(1.0, 0.0, 0.78) if inside else (0.0, 0.0, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=22.0 if inside else 30.0,
        aperture=0.0,
        focus_distance=3.0,
    )
    renderer.background(type="constant", color=(0.0, 0.0, 0.0), exposure=0.0)
    glass = renderer.material(
        name="glass",
        type="dielectric",
        base_color=(1.0, 1.0, 1.0),
        ior=ior,
        roughness=0.08 if inside else 0.20,
    )
    blue_source = renderer.material(
        name="blue_source", type="emitter", emission=(0.3, 1.0, 18.0)
    )
    if inside:
        renderer.object(
            name="glass_back_face",
            type="rectangle",
            p1=(2.2, -2.0, -0.4),
            p2=(-1.0, -2.0, 2.0),
            p3=(-1.0, 2.0, 2.0),
            material=glass,
        )
    else:
        renderer.object(
            name="glass_ball",
            type="sphere",
            center=(0.0, 0.0, 0.0),
            radius=1.0,
            material=glass,
        )
    if mode == "reflection":
        renderer.light(
            name="front_red",
            type="disk",
            position=(2.2, 2.0, 2.8),
            normal=(-0.54, -0.49, -0.69),
            radius=1.25,
            emission=(22.0, 0.4, 0.2),
        )
    elif mode == "transmission":
        renderer.object(
            name="back_panel",
            type="rectangle",
            p1=(-3.0, -3.0, -3.0),
            p2=(-3.0, 3.0, -3.0),
            p3=(3.0, 3.0, -3.0),
            material=blue_source,
        )
    elif mode == "inside_tir":
        renderer.light(
            name="outside_probe",
            type="disk",
            position=(3.0, 0.0, 0.8),
            normal=(-1.0, 0.0, 0.0),
            radius=1.0,
            emission=(12.0, 12.0, 12.0),
        )
    else:
        raise RuntimeError(f"unknown generic glass mode: {mode}")
    return renderer


def main():
    if len(sys.argv) != 1:
        raise RuntimeError("check_rough_dielectric_nee.py does not accept arguments")
    profile = SAMPLE_PROFILE

    with tempfile.TemporaryDirectory(prefix="spectraldock-rough-nee-") as tmp:
        directory = Path(tmp)
        bound_high, bound_stats, bound_bytes = render(
            reflection_renderer(True),
            directory,
            "bound-high",
            profile.high_spp,
            2,
            1201,
        )
        # The bound strategy can connect after two surface scatterings; the
        # unbound BSDF-only strategy needs one additional depth slot.
        bsdf_high, _, _ = render(
            reflection_renderer(False),
            directory,
            "bsdf-high",
            profile.high_spp,
            3,
            1301,
        )
        mean_error = relative_mean_error(bound_high, bsdf_high, WATER_ROI)
        if mean_error > 0.02:
            raise RuntimeError(
                "bound NEE/MIS and unbound BSDF-only linear means differ by >2%: "
                f"bound={mean_luminance(bound_high, WATER_ROI):.8g}, "
                f"bsdf={mean_luminance(bsdf_high, WATER_ROI):.8g}, "
                f"relative_error={mean_error:.4%}"
            )
        if metric(bound_stats, "water_rough_nee_attempts") in (None, 0):
            raise RuntimeError("rough water did not attempt finite-light NEE")
        if metric(bound_stats, "water_rough_nee_contributions") in (None, 0):
            raise RuntimeError("rough water produced no finite-light NEE contribution")

        repeat, _, repeat_bytes = render(
            reflection_renderer(True),
            directory,
            "bound-repeat",
            profile.high_spp,
            2,
            1201,
        )
        if bound_bytes != repeat_bytes or bound_high != repeat:
            raise RuntimeError("fixed-seed linear rough-water output is not deterministic")

        nee_error = 0.0
        bsdf_error = 0.0
        for index, seed in enumerate((1409, 1511, 1601)):
            nee, _, _ = render(
                reflection_renderer(True),
                directory,
                f"nee-low-{index}",
                profile.low_spp,
                2,
                seed,
            )
            bsdf, _, _ = render(
                reflection_renderer(False),
                directory,
                f"bsdf-low-{index}",
                profile.low_spp,
                3,
                seed,
            )
            nee_error += mse(nee, bound_high, WATER_ROI)
            bsdf_error += mse(bsdf, bound_high, WATER_ROI)
        if nee_error > 0.50 * bsdf_error:
            raise RuntimeError(
                "rough-water NEE did not halve three-seed low-spp MSE: "
                f"nee={nee_error:.6g}, bsdf={bsdf_error:.6g}"
            )

        depth_one, depth_one_stats, _ = render(
            reflection_renderer(True),
            directory,
            "depth-one",
            profile.depth_one_spp,
            1,
            1709,
        )
        if mean_luminance(depth_one, WATER_ROI) <= 1.0e-5:
            raise RuntimeError("depth-1 rough-water NEE produced no reflected light")
        if metric(depth_one_stats, "water_rough_nee_contributions") in (None, 0):
            raise RuntimeError("depth-1 rough-water NEE counter stayed zero")

        depth1, _, _ = render(
            blocker_renderer(),
            directory,
            "blocked-depth1",
            profile.blocked_spp,
            1,
            1801,
        )
        depth2, depth2_stats, _ = render(
            blocker_renderer(),
            directory,
            "restored-depth2",
            profile.restored_spp,
            2,
            1801,
        )
        dark_mean = mean_luminance(depth1, RECEIVER_ROI)
        restored_mean = mean_luminance(depth2, RECEIVER_ROI)
        if dark_mean > 1.0e-6:
            raise RuntimeError(
                "an intermediate water boundary leaked a straight depth-1 connection"
            )
        if restored_mean <= dark_mean + 1.0e-5:
            raise RuntimeError(
                "a later rough-water vertex did not restore the refracted connection"
            )
        if metric(depth2_stats, "water_rough_nee_contributions") in (None, 0):
            raise RuntimeError("transmission-side water NEE counter stayed zero")

        shallow, _, _ = render(
            blocker_renderer(-0.45),
            directory,
            "beer-shallow",
            profile.beer_spp,
            2,
            1901,
        )
        deep, _, _ = render(
            blocker_renderer(-1.35),
            directory,
            "beer-deep",
            profile.beer_spp,
            2,
            1901,
        )
        shallow_rgb = mean_rgb(shallow, RECEIVER_ROI)
        deep_rgb = mean_rgb(deep, RECEIVER_ROI)
        if sum(deep_rgb) >= sum(shallow_rgb):
            raise RuntimeError("longer transmission-side NEE segment was not attenuated")
        if deep_rgb[0] / max(deep_rgb[2], 1.0e-9) >= (
            shallow_rgb[0] / max(shallow_rgb[2], 1.0e-9)
        ):
            raise RuntimeError("transmission-side Beer attenuation lost RGB selectivity")

        glass_reflection, _, _ = render(
            generic_glass_renderer("reflection"),
            directory,
            "generic-front-reflection",
            profile.glass_reflection_spp,
            1,
            2203,
        )
        if mean_luminance(glass_reflection, GLASS_ROI) <= 1.0e-6:
            raise RuntimeError("air-side rough dielectric reflection NEE is blank")

        glass_transmission, _, _ = render(
            generic_glass_renderer("transmission"),
            directory,
            "generic-front-back-transmission",
            profile.glass_transmission_spp,
            3,
            2309,
        )
        if mean_luminance(glass_transmission, GLASS_TRANSMISSION_ROI) <= 1.0e-6:
            raise RuntimeError(
                "rough dielectric did not traverse its front and back surfaces"
            )

        low_ior, _, _ = render(
            generic_glass_renderer("inside_tir", 1.20),
            directory,
            "generic-inside-low-ior",
            profile.tir_spp,
            1,
            2411,
        )
        high_ior, _, high_ior_bytes = render(
            generic_glass_renderer("inside_tir", 2.40),
            directory,
            "generic-inside-tir",
            profile.tir_spp,
            1,
            2411,
        )
        high_repeat, _, high_repeat_bytes = render(
            generic_glass_renderer("inside_tir", 2.40),
            directory,
            "generic-inside-tir-repeat",
            profile.tir_spp,
            1,
            2411,
        )
        if high_ior != high_repeat or high_ior_bytes != high_repeat_bytes:
            raise RuntimeError("material-side rough dielectric output is not deterministic")
        low_energy = mean_luminance(low_ior, GLASS_ROI)
        high_energy = mean_luminance(high_ior, GLASS_ROI)
        if low_energy <= 1.0e-6:
            raise RuntimeError("low-IOR material-side transmission probe is blank")
        if high_energy >= 0.50 * low_energy:
            raise RuntimeError(
                "high-IOR material-side probe leaked through the TIR region: "
                f"high={high_energy:.6g}, low={low_energy:.6g}"
            )

    print("rough dielectric NEE/MIS and blocker checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
