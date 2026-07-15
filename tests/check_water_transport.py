#!/usr/bin/env python3
"""Directional GPU checks for schema-v6 runtime water transport."""

import copy
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image


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


def render(renderer, scene_data, directory, name, spp=192, depth=8):
    scene = directory / f"{name}.json"
    image = directory / f"{name}.png"
    scene.write_text(json.dumps(scene_data, indent=2) + "\n", encoding="utf-8")
    subprocess.run(
        [
            str(renderer), "--scene", str(scene), "--output", str(image),
            "--width", "96", "--height", "72", "--spp", str(spp),
            "--max-depth", str(depth), "--seed", "83", "--no-denoise",
        ],
        check=True,
    )
    with Image.open(image) as decoded:
        decoded.load()
        if decoded.size != (96, 72) or decoded.mode != "RGBA":
            raise RuntimeError(
                f"unexpected water output: {decoded.size} {decoded.mode}"
            )
        pixels = decoded.copy()
    stats = json.loads(image.with_suffix(".stats.json").read_text(encoding="utf-8"))
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
            if red < 20:
                continue
            weighted_x += x * weight
            weighted_y += y * weight
            total += weight
    if total <= 0.0:
        raise RuntimeError("red refractive probe was not visible")
    return weighted_x / total, weighted_y / total


def remove_objects(scene, names):
    result = copy.deepcopy(scene)
    result["objects"] = [
        obj for obj in result["objects"] if obj["name"] not in names
    ]
    return result


def set_water_roughness(scene, roughness):
    result = copy.deepcopy(scene)
    water_materials = [
        material for material in result["materials"]
        if material["type"] == "water"
    ]
    if not water_materials:
        raise RuntimeError("water fixture has no water material")
    for material in water_materials:
        material["roughness"] = roughness
    return result


def absorption_scene(base, depth):
    scene = remove_objects(
        base,
        {
            "pool_floor", "pool_back", "red_refractive_probe",
            "shallow_probe", "deep_probe", "immersed_glass_probe",
            "moon_reflection_probe",
        },
    )
    scene["lights"] = []
    scene["objects"].insert(
        0,
        {
            "name": "depth_probe", "type": "sphere",
            "center": [0.0, depth, -0.55], "radius": 0.16,
            "material": "white_probe",
        },
    )
    return scene


def main():
    if len(sys.argv) != 3:
        raise RuntimeError("usage: check_water_transport.py RENDERER WATER_SCENE")
    renderer = Path(sys.argv[1]).resolve()
    fixture = Path(sys.argv[2]).resolve()
    base = set_water_roughness(
        json.loads(fixture.read_text(encoding="utf-8")), 0.12
    )

    with tempfile.TemporaryDirectory(prefix="spectraldock-water-") as tmp:
        directory = Path(tmp)
        first, first_stats = render(renderer, base, directory, "water-a")
        second, _ = render(renderer, base, directory, "water-b")
        if first.tobytes() != second.tobytes():
            raise RuntimeError("fixed-seed water renders are not byte-identical")

        for name in POSITIVE_METRICS:
            value = metric(first_stats, name)
            if value is None or value <= 0:
                raise RuntimeError(f"{name} must be positive for the water fixture")
        for name in SAFETY_METRICS:
            if metric(first_stats, name) != 0:
                raise RuntimeError(f"{name} must remain zero")
        if metric(first_stats, "water_delta_splits") != 0:
            raise RuntimeError("rough water must not use the smooth delta split")

        smooth = set_water_roughness(base, 0.0)
        smooth_image, smooth_stats = render(
            renderer, smooth, directory, "water-smooth", spp=64
        )
        smooth_repeat, _ = render(
            renderer, smooth, directory, "water-smooth-repeat", spp=64
        )
        if smooth_image.tobytes() != smooth_repeat.tobytes():
            raise RuntimeError("smooth first-water Fresnel split is not deterministic")
        if metric(smooth_stats, "water_delta_splits") in (None, 0):
            raise RuntimeError("smooth water did not exercise the bounded delta split")
        for name in ("water_rough_nee_attempts", "water_rough_nee_contributions"):
            if metric(smooth_stats, name) != 0:
                raise RuntimeError(f"smooth delta water must not increment {name}")

        no_water = remove_objects(base, {"test_water"})
        air_image, air_stats = render(renderer, no_water, directory, "water-off")
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

        without_glass = remove_objects(base, {"immersed_glass_probe"})
        no_glass_image, _ = render(
            renderer, without_glass, directory, "immersed-glass-off"
        )
        glass_box = (40, 28, 76, 62)
        if mean_absolute_difference(first, no_glass_image, glass_box) <= 0.10:
            raise RuntimeError("immersed dielectric was not visible through water")

        without_moon = remove_objects(base, {"moon_reflection_probe"})
        dark_reflection, _ = render(
            renderer, without_moon, directory, "reflection-off", spp=128
        )
        water_box = (4, 28, 92, 70)
        if mean_luminance(first, water_box) <= mean_luminance(
            dark_reflection, water_box
        ) + 0.20:
            raise RuntimeError("rough water did not reflect the above-water emitter")

        shallow_image, _ = render(
            renderer, absorption_scene(base, -0.42), directory,
            "absorption-shallow", spp=256,
        )
        deep_image, _ = render(
            renderer, absorption_scene(base, -1.15), directory,
            "absorption-deep", spp=256,
        )
        shallow_energy = channel_energy(shallow_image)
        deep_energy = channel_energy(deep_image)
        if sum(deep_energy) >= 0.99 * sum(shallow_energy):
            raise RuntimeError("a deeper water path was not attenuated")
        shallow_red_blue = shallow_energy[0] / max(shallow_energy[2], 1.0)
        deep_red_blue = deep_energy[0] / max(deep_energy[2], 1.0)
        if deep_red_blue >= shallow_red_blue:
            raise RuntimeError("Beer absorption did not attenuate red more than blue")

        direct_scene = remove_objects(
            base,
            {
                "red_refractive_probe", "shallow_probe", "deep_probe",
                "immersed_glass_probe", "moon_reflection_probe",
            },
        )
        lit_floor, _ = render(renderer, direct_scene, directory, "direct-lit")
        unlit_scene = copy.deepcopy(direct_scene)
        unlit_scene["lights"] = []
        unlit_floor, _ = render(renderer, unlit_scene, directory, "direct-off")
        receiver_box = (6, 28, 90, 71)
        if mean_luminance(lit_floor, receiver_box) <= mean_luminance(
            unlit_floor, receiver_box
        ) + 0.5:
            raise RuntimeError(
                "rough-water BSDF/NEE paths did not restore underwater illumination"
            )

        blocked_scene = copy.deepcopy(direct_scene)
        blocked_scene["objects"].append(
            {
                "name": "opaque_light_baffle", "type": "disk",
                "center": [0.4, 1.55, 0.8], "normal": [0.0, 1.0, 0.0],
                "radius": 0.78, "material": "dark",
            }
        )
        blocked_floor, _ = render(
            renderer, blocked_scene, directory, "direct-blocked"
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
    except (json.JSONDecodeError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
