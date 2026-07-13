#!/usr/bin/env python3
"""Directional GPU checks for the procedural absorption/emission volume."""

import copy
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image


VOLUME_METRICS = (
    "volume_density_evaluations",
    "volume_real_collisions",
    "volume_light_samples",
    "volume_majorant_violations",
    "volume_tracking_overflows",
)


def render(renderer, scene_data, directory, name, spp=128, depth=3):
    scene = directory / f"{name}.json"
    image = directory / f"{name}.png"
    scene.write_text(json.dumps(scene_data, indent=2) + "\n", encoding="utf-8")
    subprocess.run(
        [
            str(renderer), "--scene", str(scene), "--output", str(image),
            "--width", "64", "--height", "64", "--spp", str(spp),
            "--max-depth", str(depth), "--seed", "71", "--no-denoise",
        ],
        check=True,
    )
    with Image.open(image) as decoded:
        decoded.load()
        if decoded.size != (64, 64) or decoded.mode != "RGBA":
            raise RuntimeError(f"unexpected flame output: {decoded.size} {decoded.mode}")
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


def mean_luminance(image, box):
    values = []
    for red, green, blue, _ in image.crop(box).getdata():
        values.append(0.2126 * red + 0.7152 * green + 0.0722 * blue)
    return sum(values) / len(values)


def area_transmission_scene(with_flame):
    lights = [
        {
            "name": "area_key", "type": "disk", "position": [0.0, 2.7, 1.0],
            "normal": [0.0, 0.0, -1.0], "radius": 0.65,
            "emission": [28.0, 28.0, 28.0],
        }
    ]
    if with_flame:
        lights.append(
            {
                "name": "absorbing_volume", "type": "flame",
                "position": [0.0, 1.25, 0.65], "axis": [0.0, 0.0, -1.0],
                "height": 1.65, "radius_start": 0.75, "radius_end": 0.75,
                "emission_start": [0.000001, 0.000001, 0.000001],
                "emission_end": [0.000001, 0.000001, 0.000001],
                "extinction": 3.2, "density_scale": 1.0,
                "turbulence": 0.0, "noise_scale": 2.0, "seed": 71,
            }
        )
    return {
        "schema_version": 3,
        "camera": {
            "look_from": [0.0, 1.25, 5.0], "look_at": [0.0, 1.25, -1.5],
            "up": [0.0, 1.0, 0.0], "vfov": 30.0,
            "aperture": 0.0, "focus_distance": 6.5,
        },
        "background": {"type": "constant", "color": [0.0, 0.0, 0.0], "exposure": 0.0},
        "render": {"width": 64, "height": 64, "spp": 128, "max_depth": 1, "seed": 71, "denoise": False},
        "textures": [],
        "materials": [{"name": "white", "type": "lambertian", "base_color": [0.78, 0.78, 0.78]}],
        "objects": [
            {"name": "receiver", "type": "rectangle", "p1": [-2.0, 0.0, -1.5], "p2": [-2.0, 2.5, -1.5], "p3": [2.0, 2.5, -1.5], "material": "white"}
        ],
        "lights": lights,
    }


def main():
    if len(sys.argv) != 3:
        raise RuntimeError("usage: check_flame_transport.py RENDERER FLAME_SCENE")
    renderer = Path(sys.argv[1]).resolve()
    fixture = Path(sys.argv[2]).resolve()
    base = json.loads(fixture.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory(prefix="spectraldock-flame-") as tmp:
        directory = Path(tmp)
        first, first_stats = render(renderer, base, directory, "flame-a")
        second, _ = render(renderer, base, directory, "flame-b")
        if first.tobytes() != second.tobytes():
            raise RuntimeError("fixed-seed flame renders are not byte-identical")

        for name in VOLUME_METRICS[:3]:
            value = metric(first_stats, name)
            if value is None or value <= 0:
                raise RuntimeError(f"{name} must be positive for the flame fixture")
        for name in VOLUME_METRICS[3:]:
            if metric(first_stats, name) != 0:
                raise RuntimeError(f"{name} must remain zero")

        off = copy.deepcopy(base)
        off["lights"] = []
        off_image, off_stats = render(renderer, off, directory, "flame-off")
        for name in VOLUME_METRICS:
            if metric(off_stats, name) != 0:
                raise RuntimeError(f"{name} must be zero without a flame")
        receiver_box = (2, 10, 25, 55)
        if mean_luminance(first, receiver_box) <= mean_luminance(off_image, receiver_box) + 1.0:
            raise RuntimeError("flame NEE did not illuminate the external receiver")

        blocked = copy.deepcopy(base)
        blocked["objects"].append(
            {
                "name": "receiver_baffle", "type": "rectangle",
                "p1": [-0.45, 0.0, -0.65], "p2": [-0.45, 2.6, -0.65],
                "p3": [-0.45, 2.6, 0.65], "material": "occluder",
            }
        )
        blocked_image, _ = render(renderer, blocked, directory, "flame-blocked")
        if mean_luminance(blocked_image, receiver_box) >= mean_luminance(first, receiver_box):
            raise RuntimeError("surface occluder did not reduce flame illumination")

        clear_image, _ = render(
            renderer, area_transmission_scene(False), directory, "area-clear", depth=1
        )
        absorbed_image, _ = render(
            renderer, area_transmission_scene(True), directory, "area-absorbed", depth=1
        )
        wall_box = (12, 10, 52, 54)
        if mean_luminance(absorbed_image, wall_box) >= mean_luminance(clear_image, wall_box):
            raise RuntimeError("flame absorption did not attenuate an area light")

        center_glass = (36, 19, 52, 43)
        if mean_luminance(first, center_glass) <= 0.0:
            raise RuntimeError("delta dielectric path did not see the flame")

    print("procedural flame transport checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (json.JSONDecodeError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
