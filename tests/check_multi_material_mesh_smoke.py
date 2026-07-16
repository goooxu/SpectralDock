#!/usr/bin/env python3
"""Validate per-primitive material selection without a GPU-specific golden."""

import json
import sys
from pathlib import Path

from PIL import Image, ImageStat


PANEL_BOXES = {
    "red": (6, 16, 20, 44),
    "screen": (24, 16, 39, 44),
    "metal": (43, 16, 58, 44),
}


def pixels(image: Image.Image, box: tuple[int, int, int, int]):
    left, top, right, bottom = box
    return [
        image.getpixel((x, y))
        for y in range(top, bottom)
        for x in range(left, right)
    ]


def mean_rgb(image: Image.Image, box: tuple[int, int, int, int]):
    return ImageStat.Stat(image.crop(box)).mean


def saturated_count(image: Image.Image, box: tuple[int, int, int, int]) -> int:
    return sum(
        1 for sample in pixels(image, box)
        if max(sample) - min(sample) > 25
    )


def main() -> int:
    if len(sys.argv) != 3:
        raise RuntimeError(
            "usage: check_multi_material_mesh_smoke.py IMAGE STATS"
        )
    image_path, stats_path = map(Path, sys.argv[1:])

    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    expected_geometry = {
        "objects": 2,
        "instances": 2,
        "unique_meshes": 1,
        "mesh_triangles": 6,
        "gas_count": 2,
    }
    if stats.get("geometry") != expected_geometry:
        raise RuntimeError(
            "unexpected multi-material geometry stats: {!r}".format(
                stats.get("geometry")
            )
        )
    render = stats.get("render", {})
    expected_render = {
        "width": 64,
        "height": 64,
        "spp": 1,
        "max_depth": 4,
        "seed": 211,
        "denoised": False,
    }
    for key, expected in expected_render.items():
        if render.get(key) != expected:
            raise RuntimeError(
                "unexpected render.{}={!r}; expected {!r}".format(
                    key, render.get(key), expected
                )
            )

    with Image.open(image_path) as decoded:
        decoded.load()
        if decoded.size != (64, 64) or decoded.mode != "RGBA":
            raise RuntimeError(
                "multi-material smoke must be 64x64 RGBA, got {} {}".format(
                    decoded.size, decoded.mode
                )
            )
        image = decoded.convert("RGB")

    red = mean_rgb(image, PANEL_BOXES["red"])
    screen = mean_rgb(image, PANEL_BOXES["screen"])
    metal = mean_rgb(image, PANEL_BOXES["metal"])
    screen_saturated = saturated_count(image, PANEL_BOXES["screen"])
    metal_saturated = saturated_count(image, PANEL_BOXES["metal"])

    if not (red[0] > 150.0 and red[0] > 3.0 * red[1]
            and red[0] > 5.0 * red[2]):
        raise RuntimeError("left RedPanel did not render red: {!r}".format(red))
    if max(screen) >= 100.0 or screen_saturated < 12:
        raise RuntimeError(
            "center ScreenPanel did not preserve its dark colored atlas: "
            "mean={!r}, saturated={}".format(screen, screen_saturated)
        )
    if metal_saturated > 8 or sum(metal) <= sum(screen) + 25.0:
        raise RuntimeError(
            "right MetalPanel is not distinct from the textured panel: "
            "metal_mean={!r}, screen_mean={!r}, metal_saturated={}".format(
                metal, screen, metal_saturated
            )
        )

    print(
        "multi-material mesh GPU smoke passed: "
        "red={!r}, screen={!r}, metal={!r}".format(red, screen, metal)
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        print("error: {}".format(error), file=sys.stderr)
        raise SystemExit(1)
