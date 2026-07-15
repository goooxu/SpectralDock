#!/usr/bin/env python3
"""GPU contracts for delta lights and per-contribution firefly control."""

import copy
import json
import math
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image


WIDTH = 24
HEIGHT = 24


def read_pfm(path):
    with path.open("rb") as stream:
        if stream.readline() != b"PF\n":
            raise RuntimeError("expected a three-channel PFM")
        width, height = map(int, stream.readline().split())
        if float(stream.readline()) >= 0.0:
            raise RuntimeError("expected little-endian PFM data")
        payload = stream.read()
    expected = width * height * 3 * 4
    if len(payload) != expected:
        raise RuntimeError(
            "PFM payload has {} bytes, expected {}".format(
                len(payload), expected
            )
        )
    values = struct.unpack("<{}f".format(width * height * 3), payload)
    if any(not math.isfinite(value) for value in values):
        raise RuntimeError("linear output contains a non-finite value")
    return width, height, tuple(zip(values[0::3], values[1::3], values[2::3]))


def render(renderer, data, directory, name, spp=2, depth=1, seed=313,
           overrides=()):
    scene = directory / (name + ".json")
    png = directory / (name + ".png")
    pfm = directory / (name + ".pfm")
    scene.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    command = [
        str(renderer), "--scene", str(scene), "--output", str(png),
        "--linear-output", str(pfm), "--width", str(WIDTH),
        "--height", str(HEIGHT), "--spp", str(spp),
        "--max-depth", str(depth), "--seed", str(seed), "--no-denoise",
    ]
    command.extend(overrides)
    subprocess.run(command, check=True)
    with Image.open(png) as image:
        image.load()
        if image.size != (WIDTH, HEIGHT) or image.mode != "RGBA":
            raise RuntimeError(
                "unexpected delta-light PNG: {} {}".format(
                    image.size, image.mode
                )
            )
    width, height, pixels = read_pfm(pfm)
    if (width, height) != (WIDTH, HEIGHT):
        raise RuntimeError("unexpected delta-light PFM dimensions")
    stats = json.loads(
        png.with_suffix(".stats.json").read_text(encoding="utf-8")
    )
    return pixels, stats, pfm.read_bytes()


def mean_rgb(pixels):
    count = float(len(pixels))
    return tuple(sum(pixel[channel] for pixel in pixels) / count
                 for channel in range(3))


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


def receiver_scene():
    return {
        "schema_version": 6,
        "camera": {
            "look_from": [0.0, 0.0, 3.0],
            "look_at": [0.0, 0.0, 0.0],
            "up": [0.0, 1.0, 0.0],
            "vfov": 35.0,
            "aperture": 0.0,
            "focus_distance": 3.0,
        },
        "integrator": {"direct_light_sampling": "importance"},
        "background": {
            "type": "constant", "color": [0.0, 0.0, 0.0],
            "exposure": 0.0,
        },
        "render": {
            "width": WIDTH, "height": HEIGHT, "spp": 2,
            "max_depth": 1, "seed": 313, "denoise": False,
        },
        "textures": [],
        "materials": [
            {"name": "receiver", "type": "lambertian",
             "base_color": [1.0, 1.0, 1.0]},
            {"name": "blocker", "type": "lambertian",
             "base_color": [0.1, 0.1, 0.1]},
        ],
        "objects": [
            {"name": "receiver", "type": "rectangle",
             "p1": [-2.0, -2.0, 0.0], "p2": [-2.0, 2.0, 0.0],
             "p3": [2.0, 2.0, 0.0], "material": "receiver"},
        ],
        "lights": [],
    }


def directional_contract(renderer, directory):
    scene = receiver_scene()
    scene["lights"] = [
        {"name": "parallel", "type": "directional",
         "direction": [0.0, 0.0, 4.0],
         "irradiance": [math.pi, 0.5 * math.pi, 0.25 * math.pi]},
    ]
    pixels, stats, first_bytes = render(
        renderer, scene, directory, "directional-a"
    )
    color = mean_rgb(pixels)
    for actual, expected, name in zip(color, (1.0, 0.5, 0.25), "rgb"):
        near(actual, expected, 2.0e-5, "directional analytic " + name)
    if (stats["render"]["clamp_direct"] != 64.0 or
            stats["render"]["clamp_indirect"] != 16.0):
        raise RuntimeError("default clamp thresholds were not reported")

    _, _, second_bytes = render(
        renderer, scene, directory, "directional-b"
    )
    if first_bytes != second_bytes:
        raise RuntimeError("fixed-seed directional PFM is not deterministic")

    translated = copy.deepcopy(scene)
    translated["camera"]["look_from"][0] += 5.0
    translated["camera"]["look_at"][0] += 5.0
    for key in ("p1", "p2", "p3"):
        translated["objects"][0][key][0] += 5.0
    translated_pixels, _, _ = render(
        renderer, translated, directory, "directional-translated"
    )
    for first, second in zip(mean_rgb(pixels), mean_rgb(translated_pixels)):
        near(first, second, 2.0e-5, "directional translation invariance")

    back = copy.deepcopy(scene)
    back["lights"][0]["direction"] = [0.0, 0.0, -1.0]
    back_pixels, _, _ = render(renderer, back, directory, "directional-back")
    if maximum_rgb(back_pixels) > 1.0e-7:
        raise RuntimeError("back-facing directional light contributed")

    blocked = copy.deepcopy(scene)
    blocked["lights"][0]["direction"] = [0.6, 0.0, 0.8]
    blocked["objects"].append(
        {"name": "blocker", "type": "sphere",
         "center": [0.75, 0.0, 1.0], "radius": 0.28,
         "material": "blocker"}
    )
    blocked_pixels, _, _ = render(
        renderer, blocked, directory, "directional-blocked"
    )
    if center_maximum_rgb(blocked_pixels) > 1.0e-7:
        raise RuntimeError("directional shadow ray ignored an opaque blocker")


def point_contract(renderer, directory):
    scene = receiver_scene()
    scene["camera"]["vfov"] = 1.5
    scene["objects"][0].update(
        {"p1": [-0.1, -0.1, 0.0], "p2": [-0.1, 0.1, 0.0],
         "p3": [0.1, 0.1, 0.0]}
    )
    scene["lights"] = [
        {"name": "point", "type": "point", "position": [0.0, 0.0, 2.0],
         "intensity": [16.0, 16.0, 16.0]},
    ]
    near_pixels, _, near_bytes = render(
        renderer, scene, directory, "point-near", spp=8
    )
    far = copy.deepcopy(scene)
    far["lights"][0]["position"][2] = 4.0
    far_pixels, _, _ = render(renderer, far, directory, "point-far", spp=8)
    ratio = mean_rgb(near_pixels)[0] / mean_rgb(far_pixels)[0]
    near(ratio, 4.0, 0.035, "point inverse-square ratio")
    _, _, repeat_bytes = render(
        renderer, scene, directory, "point-repeat", spp=8
    )
    if near_bytes != repeat_bytes:
        raise RuntimeError("fixed-seed point-light PFM is not deterministic")


def clamp_contract(renderer, directory):
    scene = receiver_scene()
    scene["lights"] = [
        {"name": "hot", "type": "directional",
         "direction": [0.0, 0.0, 1.0],
         "irradiance": [128.0 * math.pi, 64.0 * math.pi,
                        32.0 * math.pi]},
    ]
    clamped, clamped_stats, _ = render(
        renderer, scene, directory, "clamp-direct-default"
    )
    raw, raw_stats, _ = render(
        renderer, scene, directory, "clamp-direct-off",
        overrides=("--clamp-direct", "0", "--clamp-indirect", "0"),
    )
    for actual, expected in zip(mean_rgb(clamped), (64.0, 32.0, 16.0)):
        near(actual, expected, 2.0e-3, "direct clamp color")
    for actual, expected in zip(mean_rgb(raw), (128.0, 64.0, 32.0)):
        near(actual, expected, 4.0e-3, "unclamped direct color")
    if clamped_stats["firefly"]["direct_clamped_contributions"] <= 0:
        raise RuntimeError("direct firefly counter did not increment")
    if clamped_stats["firefly"]["indirect_clamped_contributions"] != 0:
        raise RuntimeError("direct fixture incremented the indirect counter")
    if (raw_stats["render"]["clamp_direct"] != 0.0 or
            raw_stats["render"]["clamp_indirect"] != 0.0 or
            any(raw_stats["firefly"].values())):
        raise RuntimeError("CLI clamp disable was not honored")

    quiet = receiver_scene()
    quiet["lights"] = [
        {"name": "quiet", "type": "directional",
         "direction": [0.0, 0.0, 1.0],
         "irradiance": [math.pi, 0.5 * math.pi, 0.25 * math.pi]},
    ]
    _, quiet_stats, quiet_on = render(
        renderer, quiet, directory, "clamp-no-trigger"
    )
    _, _, quiet_off = render(
        renderer, quiet, directory, "clamp-no-trigger-off",
        overrides=("--clamp-direct", "0", "--clamp-indirect", "0"),
    )
    if quiet_on != quiet_off or any(quiet_stats["firefly"].values()):
        raise RuntimeError("an untriggered clamp changed linear output")

    # Exercise the legacy grouped-add path itself: no delta lights, a positive
    # default threshold, and a finite-light term which stays below it.
    quiet_finite = receiver_scene()
    quiet_finite["lights"] = [
        {"name": "quiet-area", "type": "rectangle",
         "position": [-0.5, 0.5, 2.0],
         "edge_u": [1.0, 0.0, 0.0], "edge_v": [0.0, -1.0, 0.0],
         "emission": [1.0, 0.5, 0.25]},
    ]
    finite_pixels, finite_stats, finite_on = render(
        renderer, quiet_finite, directory, "clamp-no-trigger-finite", spp=8
    )
    _, _, finite_off = render(
        renderer, quiet_finite, directory, "clamp-no-trigger-finite-off",
        spp=8,
        overrides=("--clamp-direct", "0", "--clamp-indirect", "0"),
    )
    if (finite_on != finite_off or any(finite_stats["firefly"].values()) or
            maximum_rgb(finite_pixels) <= 0.0):
        raise RuntimeError(
            "an untriggered no-delta clamp changed the legacy add path"
        )

    # A sampled finite light may sit at any global scene-light index. Insert
    # two back-facing delta lights around it and verify that the uploaded CDF
    # slot-to-global-index map still selects the same rectangle.
    remap_reference = copy.deepcopy(quiet_finite)
    remap_reference["integrator"].update(
        {"clamp_direct": 0.0, "clamp_indirect": 0.0}
    )
    remap_mixed = copy.deepcopy(remap_reference)
    remap_mixed["lights"] = [
        {"name": "back-directional", "type": "directional",
         "direction": [0.0, 0.0, -1.0],
         "irradiance": [10.0, 10.0, 10.0]},
        remap_reference["lights"][0],
        {"name": "back-point", "type": "point",
         "position": [0.0, 0.0, -2.0],
         "intensity": [10.0, 10.0, 10.0]},
    ]
    reference_pixels, _, _ = render(
        renderer, remap_reference, directory, "finite-remap-reference", spp=64
    )
    mixed_pixels, _, _ = render(
        renderer, remap_mixed, directory, "finite-remap-mixed", spp=64
    )
    for reference, mixed in zip(
            mean_rgb(reference_pixels), mean_rgb(mixed_pixels)):
        near(mixed, reference, 2.0e-6, "finite-light global-index remap")

    # Clamping applies independently to each strategy contribution, never to
    # their already accumulated sum. Each lamp contributes 40 (<64), while
    # their combined direct result is 80 (>64).
    independent = receiver_scene()
    independent["lights"] = [
        {"name": "a", "type": "directional",
         "direction": [0.0, 0.0, 1.0],
         "irradiance": [40.0 * math.pi] * 3},
        {"name": "b", "type": "directional",
         "direction": [0.0, 0.0, 1.0],
         "irradiance": [40.0 * math.pi] * 3},
    ]
    independent_pixels, independent_stats, _ = render(
        renderer, independent, directory, "clamp-independent-contributions"
    )
    for actual in mean_rgb(independent_pixels):
        near(actual, 80.0, 3.0e-3, "independent contribution clamp")
    if any(independent_stats["firefly"].values()):
        raise RuntimeError("independent sub-threshold contributions were clamped")

    indirect = receiver_scene()
    indirect["background"]["color"] = [80.0, 40.0, 20.0]
    indirect_pixels, indirect_stats, _ = render(
        renderer, indirect, directory, "clamp-indirect", spp=4, depth=2
    )
    for actual, expected in zip(mean_rgb(indirect_pixels), (16.0, 8.0, 4.0)):
        near(actual, expected, 2.0e-3, "indirect clamp color")
    if indirect_stats["firefly"]["direct_clamped_contributions"] != 0:
        raise RuntimeError("indirect fixture incremented the direct counter")
    if indirect_stats["firefly"]["indirect_clamped_contributions"] <= 0:
        raise RuntimeError("indirect firefly counter did not increment")


def rough_transmission_contract(renderer, directory):
    scene = receiver_scene()
    scene["integrator"].update({"clamp_direct": 0.0, "clamp_indirect": 0.0})
    scene["materials"][0] = {
        "name": "receiver", "type": "dielectric",
        "base_color": [1.0, 1.0, 1.0], "ior": 1.5,
        "roughness": 0.35,
    }
    scene["lights"] = [
        {"name": "behind", "type": "directional",
         "direction": [0.0, 0.0, -1.0],
         "irradiance": [40.0, 40.0, 40.0]},
    ]
    pixels, _, _ = render(
        renderer, scene, directory, "rough-glass-delta", spp=32
    )
    if mean_rgb(pixels)[0] <= 0.01:
        raise RuntimeError("rough dielectric received no delta-light NEE")


def water_beer_contract(renderer, directory):
    def water_scene(absorption):
        return {
            "schema_version": 6,
            "camera": {
                "look_from": [0.0, 2.4, 3.0], "look_at": [0.0, 0.0, 0.0],
                "up": [0.0, 1.0, 0.0], "vfov": 32.0,
                "aperture": 0.0, "focus_distance": 3.8,
            },
            "integrator": {
                "direct_light_sampling": "importance",
                "clamp_direct": 0.0, "clamp_indirect": 0.0,
            },
            "background": {
                "type": "constant", "color": [0.0, 0.0, 0.0],
                "exposure": 0.0,
            },
            "render": {
                "width": WIDTH, "height": HEIGHT, "spp": 64,
                "max_depth": 1, "seed": 991, "denoise": False,
            },
            "textures": [],
            "materials": [
                {"name": "water", "type": "water", "ior": 1.333,
                 "roughness": 0.35, "absorption": absorption},
            ],
            "objects": [
                {"name": "water", "type": "water_surface",
                 "center": [0.0, 0.0, 0.0], "size": [5.0, 5.0],
                 "material": "water",
                 "waves": [
                     {"direction": [1.0, 0.2], "amplitude": 0.008,
                      "wavelength": 2.5, "phase_radians": 0.2},
                 ]},
            ],
            "lights": [
                {"name": "submerged", "type": "point",
                 "position": [0.0, -1.3, 0.0],
                 "intensity": [30.0, 30.0, 30.0]},
            ],
        }

    clear, clear_stats, _ = render(
        renderer, water_scene([0.0, 0.0, 0.0]), directory,
        "water-point-clear", spp=64
    )
    absorbing, absorbing_stats, _ = render(
        renderer, water_scene([1.2, 0.2, 0.02]), directory,
        "water-point-absorbing", spp=64
    )
    clear_rgb = mean_rgb(clear)
    absorbing_rgb = mean_rgb(absorbing)
    if clear_rgb[0] <= 1.0e-4 or absorbing_rgb[2] <= 1.0e-4:
        raise RuntimeError("rough water received no submerged point-light NEE")
    red_ratio = absorbing_rgb[0] / clear_rgb[0]
    blue_ratio = absorbing_rgb[2] / clear_rgb[2]
    if not red_ratio + 0.15 < blue_ratio:
        raise RuntimeError(
            "point-light water segment did not show RGB Beer attenuation"
        )
    for stats in (clear_stats, absorbing_stats):
        if stats["water"]["water_rough_nee_contributions"] <= 0:
            raise RuntimeError("water delta-light NEE counter stayed zero")


def main():
    if len(sys.argv) != 2:
        raise RuntimeError(
            "usage: check_delta_lights_and_firefly.py RENDERER"
        )
    renderer = Path(sys.argv[1]).resolve()
    if not renderer.is_file():
        raise RuntimeError("renderer not found: {}".format(renderer))
    with tempfile.TemporaryDirectory(prefix="spectraldock-delta-light-") as tmp:
        directory = Path(tmp)
        directional_contract(renderer, directory)
        point_contract(renderer, directory)
        clamp_contract(renderer, directory)
        rough_transmission_contract(renderer, directory)
        water_beer_contract(renderer, directory)
    print("delta lights and firefly control checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, RuntimeError, ValueError,
            subprocess.CalledProcessError) as error:
        print("error: {}".format(error), file=sys.stderr)
        raise SystemExit(1)
