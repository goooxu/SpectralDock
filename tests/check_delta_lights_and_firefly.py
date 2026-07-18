#!/usr/bin/env python3
"""GPU contracts for delta lights and per-contribution firefly control."""

import math
import sys
import tempfile
from pathlib import Path

from spectraldock import Renderer

from avif_test_utils import assert_avif_dimensions, captured_linear_rgb


WIDTH = 24
HEIGHT = 24


def render(
    renderer,
    directory,
    name,
    *,
    spp=2,
    depth=1,
    seed=313,
    clamp_direct=None,
    clamp_indirect=None,
):
    avif = directory / (name + ".avif")
    stats = renderer.render(
        output=avif,
        stats_output=avif.with_suffix(".stats.json"),
        width=WIDTH,
        height=HEIGHT,
        spp=spp,
        depth=depth,
        seed=seed,
        denoise=False,
        clamp_direct=clamp_direct,
        clamp_indirect=clamp_indirect,
        _test_capture_linear=True,
    )
    assert_avif_dimensions(avif, WIDTH, HEIGHT)
    pixels, linear_values = captured_linear_rgb(stats, WIDTH, HEIGHT)
    return pixels, stats, linear_values


def mean_rgb(pixels):
    count = float(len(pixels))
    return tuple(
        sum(pixel[channel] for pixel in pixels) / count for channel in range(3)
    )


def maximum_rgb(pixels):
    return max(channel for pixel in pixels for channel in pixel)


def center_maximum_rgb(pixels):
    xs = (WIDTH // 2 - 1, WIDTH // 2)
    ys = (HEIGHT // 2 - 1, HEIGHT // 2)
    return max(
        channel
        for y in ys
        for x in xs
        for channel in pixels[y * WIDTH + x]
    )


def near(actual, expected, tolerance, label):
    if abs(actual - expected) > tolerance:
        raise RuntimeError(
            "{}: expected {}, got {}".format(label, expected, actual)
        )


def receiver_renderer(
    *,
    camera_x=0.0,
    vfov=35.0,
    receiver_points=None,
    rough_dielectric=False,
    background_color=(0.0, 0.0, 0.0),
    clamp_direct=64.0,
    clamp_indirect=16.0,
):
    renderer = Renderer()
    renderer.camera(
        look_from=(camera_x, 0.0, 3.0),
        look_at=(camera_x, 0.0, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=vfov,
        aperture=0.0,
        focus_distance=3.0,
    )
    renderer.integrator(
        direct_light_sampling="importance",
        clamp_direct=clamp_direct,
        clamp_indirect=clamp_indirect,
    )
    renderer.background(type="constant", color=background_color, exposure=0.0)
    if rough_dielectric:
        receiver = renderer.material(
            name="receiver",
            type="dielectric",
            base_color=(1.0, 1.0, 1.0),
            ior=1.5,
            roughness=0.35,
        )
    else:
        receiver = renderer.material(
            name="receiver", type="lambertian", base_color=(1.0, 1.0, 1.0)
        )
    blocker = renderer.material(
        name="blocker", type="lambertian", base_color=(0.1, 0.1, 0.1)
    )
    if receiver_points is None:
        receiver_points = (
            (-2.0 + camera_x, -2.0, 0.0),
            (-2.0 + camera_x, 2.0, 0.0),
            (2.0 + camera_x, 2.0, 0.0),
        )
    renderer.object(
        name="receiver",
        type="rectangle",
        p1=receiver_points[0],
        p2=receiver_points[1],
        p3=receiver_points[2],
        material=receiver,
    )
    return renderer, blocker


def directional_renderer(
    direction=(0.0, 0.0, 4.0),
    irradiance=(math.pi, 0.5 * math.pi, 0.25 * math.pi),
    *,
    camera_x=0.0,
    blocker=False,
):
    renderer, blocker_material = receiver_renderer(camera_x=camera_x)
    renderer.light(
        name="parallel",
        type="directional",
        direction=direction,
        irradiance=irradiance,
    )
    if blocker:
        renderer.object(
            name="blocker",
            type="sphere",
            center=(0.75, 0.0, 1.0),
            radius=0.28,
            material=blocker_material,
        )
    return renderer


def directional_contract(directory):
    pixels, stats, first_bytes = render(
        directional_renderer(), directory, "directional-a"
    )
    color = mean_rgb(pixels)
    for actual, expected, name in zip(color, (1.0, 0.5, 0.25), "rgb"):
        near(actual, expected, 2.0e-5, "directional analytic " + name)
    if (
        stats["render"]["clamp_direct"] != 64.0
        or stats["render"]["clamp_indirect"] != 16.0
    ):
        raise RuntimeError("default clamp thresholds were not reported")

    _, _, second_bytes = render(
        directional_renderer(), directory, "directional-b"
    )
    if first_bytes != second_bytes:
        raise RuntimeError("fixed-seed directional linear capture is not deterministic")

    translated_pixels, _, _ = render(
        directional_renderer(camera_x=5.0), directory, "directional-translated"
    )
    for first, second in zip(mean_rgb(pixels), mean_rgb(translated_pixels)):
        near(first, second, 2.0e-5, "directional translation invariance")

    back_pixels, _, _ = render(
        directional_renderer(direction=(0.0, 0.0, -1.0)),
        directory,
        "directional-back",
    )
    if maximum_rgb(back_pixels) > 1.0e-7:
        raise RuntimeError("back-facing directional light contributed")

    blocked_pixels, _, _ = render(
        directional_renderer(direction=(0.6, 0.0, 0.8), blocker=True),
        directory,
        "directional-blocked",
    )
    if center_maximum_rgb(blocked_pixels) > 1.0e-7:
        raise RuntimeError("directional shadow ray ignored an opaque blocker")


def point_renderer(distance):
    renderer, _ = receiver_renderer(
        vfov=1.5,
        receiver_points=(
            (-0.1, -0.1, 0.0),
            (-0.1, 0.1, 0.0),
            (0.1, 0.1, 0.0),
        ),
    )
    renderer.light(
        name="point",
        type="point",
        position=(0.0, 0.0, distance),
        intensity=(16.0, 16.0, 16.0),
    )
    return renderer


def point_contract(directory):
    near_pixels, _, near_bytes = render(
        point_renderer(2.0), directory, "point-near", spp=8
    )
    far_pixels, _, _ = render(
        point_renderer(4.0), directory, "point-far", spp=8
    )
    ratio = mean_rgb(near_pixels)[0] / mean_rgb(far_pixels)[0]
    near(ratio, 4.0, 0.035, "point inverse-square ratio")
    _, _, repeat_bytes = render(
        point_renderer(2.0), directory, "point-repeat", spp=8
    )
    if near_bytes != repeat_bytes:
        raise RuntimeError("fixed-seed point-light linear capture is not deterministic")


def hot_directional_renderer():
    renderer, _ = receiver_renderer()
    renderer.light(
        name="hot",
        type="directional",
        direction=(0.0, 0.0, 1.0),
        irradiance=(128.0 * math.pi, 64.0 * math.pi, 32.0 * math.pi),
    )
    return renderer


def quiet_directional_renderer():
    renderer, _ = receiver_renderer()
    renderer.light(
        name="quiet",
        type="directional",
        direction=(0.0, 0.0, 1.0),
        irradiance=(math.pi, 0.5 * math.pi, 0.25 * math.pi),
    )
    return renderer


def quiet_finite_renderer(*, clamp_direct=64.0, clamp_indirect=16.0, mixed=False):
    renderer, _ = receiver_renderer(
        clamp_direct=clamp_direct, clamp_indirect=clamp_indirect
    )
    if mixed:
        renderer.light(
            name="back-directional",
            type="directional",
            direction=(0.0, 0.0, -1.0),
            irradiance=(10.0, 10.0, 10.0),
        )
    renderer.light(
        name="quiet-area",
        type="rectangle",
        position=(-0.5, 0.5, 2.0),
        edge_u=(1.0, 0.0, 0.0),
        edge_v=(0.0, -1.0, 0.0),
        emission=(1.0, 0.5, 0.25),
    )
    if mixed:
        renderer.light(
            name="back-point",
            type="point",
            position=(0.0, 0.0, -2.0),
            intensity=(10.0, 10.0, 10.0),
        )
    return renderer


def independent_contributions_renderer():
    renderer, _ = receiver_renderer()
    for name in ("a", "b"):
        renderer.light(
            name=name,
            type="directional",
            direction=(0.0, 0.0, 1.0),
            irradiance=(40.0 * math.pi,) * 3,
        )
    return renderer


def clamp_contract(directory):
    clamped, clamped_stats, _ = render(
        hot_directional_renderer(), directory, "clamp-direct-default"
    )
    raw, raw_stats, _ = render(
        hot_directional_renderer(),
        directory,
        "clamp-direct-off",
        clamp_direct=0.0,
        clamp_indirect=0.0,
    )
    for actual, expected in zip(mean_rgb(clamped), (64.0, 32.0, 16.0)):
        near(actual, expected, 2.0e-3, "direct clamp color")
    for actual, expected in zip(mean_rgb(raw), (128.0, 64.0, 32.0)):
        near(actual, expected, 4.0e-3, "unclamped direct color")
    if clamped_stats["firefly"]["direct_clamped_contributions"] <= 0:
        raise RuntimeError("direct firefly counter did not increment")
    if clamped_stats["firefly"]["indirect_clamped_contributions"] != 0:
        raise RuntimeError("direct fixture incremented the indirect counter")
    if (
        raw_stats["render"]["clamp_direct"] != 0.0
        or raw_stats["render"]["clamp_indirect"] != 0.0
        or any(raw_stats["firefly"].values())
    ):
        raise RuntimeError("render clamp disable was not honored")

    _, quiet_stats, quiet_on = render(
        quiet_directional_renderer(), directory, "clamp-no-trigger"
    )
    _, _, quiet_off = render(
        quiet_directional_renderer(),
        directory,
        "clamp-no-trigger-off",
        clamp_direct=0.0,
        clamp_indirect=0.0,
    )
    if quiet_on != quiet_off or any(quiet_stats["firefly"].values()):
        raise RuntimeError("an untriggered clamp changed linear output")

    finite_pixels, finite_stats, finite_on = render(
        quiet_finite_renderer(), directory, "clamp-no-trigger-finite", spp=8
    )
    _, _, finite_off = render(
        quiet_finite_renderer(),
        directory,
        "clamp-no-trigger-finite-off",
        spp=8,
        clamp_direct=0.0,
        clamp_indirect=0.0,
    )
    if (
        finite_on != finite_off
        or any(finite_stats["firefly"].values())
        or maximum_rgb(finite_pixels) <= 0.0
    ):
        raise RuntimeError("an untriggered no-delta clamp changed the legacy add path")

    reference_pixels, _, _ = render(
        quiet_finite_renderer(clamp_direct=0.0, clamp_indirect=0.0),
        directory,
        "finite-remap-reference",
        spp=64,
    )
    mixed_pixels, _, _ = render(
        quiet_finite_renderer(clamp_direct=0.0, clamp_indirect=0.0, mixed=True),
        directory,
        "finite-remap-mixed",
        spp=64,
    )
    for reference, mixed in zip(mean_rgb(reference_pixels), mean_rgb(mixed_pixels)):
        near(mixed, reference, 2.0e-6, "finite-light global-index remap")

    independent_pixels, independent_stats, _ = render(
        independent_contributions_renderer(),
        directory,
        "clamp-independent-contributions",
    )
    for actual in mean_rgb(independent_pixels):
        near(actual, 80.0, 3.0e-3, "independent contribution clamp")
    if any(independent_stats["firefly"].values()):
        raise RuntimeError("independent sub-threshold contributions were clamped")

    indirect_renderer, _ = receiver_renderer(background_color=(80.0, 40.0, 20.0))
    indirect_pixels, indirect_stats, _ = render(
        indirect_renderer, directory, "clamp-indirect", spp=4, depth=2
    )
    for actual, expected in zip(mean_rgb(indirect_pixels), (16.0, 8.0, 4.0)):
        near(actual, expected, 2.0e-3, "indirect clamp color")
    if indirect_stats["firefly"]["direct_clamped_contributions"] != 0:
        raise RuntimeError("indirect fixture incremented the direct counter")
    if indirect_stats["firefly"]["indirect_clamped_contributions"] <= 0:
        raise RuntimeError("indirect firefly counter did not increment")


def rough_transmission_contract(directory):
    renderer, _ = receiver_renderer(
        rough_dielectric=True, clamp_direct=0.0, clamp_indirect=0.0
    )
    renderer.light(
        name="behind",
        type="directional",
        direction=(0.0, 0.0, -1.0),
        irradiance=(40.0, 40.0, 40.0),
    )
    pixels, _, _ = render(renderer, directory, "rough-glass-delta", spp=32)
    if mean_rgb(pixels)[0] <= 0.01:
        raise RuntimeError("rough dielectric received no delta-light NEE")


def water_renderer(absorption):
    renderer = Renderer()
    renderer.camera(
        look_from=(0.0, 2.4, 3.0),
        look_at=(0.0, 0.0, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=32.0,
        aperture=0.0,
        focus_distance=3.8,
    )
    renderer.integrator(
        direct_light_sampling="importance", clamp_direct=0.0, clamp_indirect=0.0
    )
    renderer.background(type="constant", color=(0.0, 0.0, 0.0), exposure=0.0)
    water = renderer.material(
        name="water",
        type="water",
        ior=1.333,
        roughness=0.35,
        absorption=absorption,
    )
    renderer.object(
        name="water",
        type="water_surface",
        center=(0.0, 0.0, 0.0),
        size=(5.0, 5.0),
        material=water,
        waves=(
            {
                "direction": (1.0, 0.2),
                "amplitude": 0.008,
                "wavelength": 2.5,
                "phase_radians": 0.2,
            },
        ),
    )
    renderer.light(
        name="submerged",
        type="point",
        position=(0.0, -1.3, 0.0),
        intensity=(30.0, 30.0, 30.0),
    )
    return renderer


def water_beer_contract(directory):
    clear, clear_stats, _ = render(
        water_renderer((0.0, 0.0, 0.0)),
        directory,
        "water-point-clear",
        spp=64,
    )
    absorbing, absorbing_stats, _ = render(
        water_renderer((1.2, 0.2, 0.02)),
        directory,
        "water-point-absorbing",
        spp=64,
    )
    clear_rgb = mean_rgb(clear)
    absorbing_rgb = mean_rgb(absorbing)
    if clear_rgb[0] <= 1.0e-4 or absorbing_rgb[2] <= 1.0e-4:
        raise RuntimeError("rough water received no submerged point-light NEE")
    red_ratio = absorbing_rgb[0] / clear_rgb[0]
    blue_ratio = absorbing_rgb[2] / clear_rgb[2]
    if not red_ratio + 0.15 < blue_ratio:
        raise RuntimeError("point-light water segment did not show RGB Beer attenuation")
    for stats in (clear_stats, absorbing_stats):
        if stats["water"]["water_rough_nee_contributions"] <= 0:
            raise RuntimeError("water delta-light NEE counter stayed zero")


def main():
    if len(sys.argv) != 1:
        raise RuntimeError(
            "check_delta_lights_and_firefly.py does not accept arguments"
        )
    with tempfile.TemporaryDirectory(prefix="spectraldock-delta-light-") as tmp:
        directory = Path(tmp)
        directional_contract(directory)
        point_contract(directory)
        clamp_contract(directory)
        rough_transmission_contract(directory)
        water_beer_contract(directory)
    print("delta lights and firefly control checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, RuntimeError, ValueError) as error:
        print("error: {}".format(error), file=sys.stderr)
        raise SystemExit(1)
