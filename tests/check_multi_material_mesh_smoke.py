#!/usr/bin/env python3
"""Validate per-primitive material selection without a GPU-specific golden."""

import json
import runpy
import sys
from pathlib import Path

from avif_test_utils import (
    assert_avif_dimensions,
    captured_linear_image,
)


PANEL_BOXES = {
    "red": (6, 16, 20, 44),
    "screen": (24, 16, 39, 44),
    "metal": (43, 16, 58, 44),
}
ROOT = Path(__file__).resolve().parents[1]
SCENE_PATH = ROOT / "tests/scenes/multi-material-mesh-smoke.py"
IMAGE_PATH = ROOT / "output/tests/multi-material-mesh-smoke.avif"
STATS_PATH = ROOT / "output/tests/multi-material-mesh-smoke.stats.json"
SEMANTIC_PATH = ROOT / "output/tests/multi-material-mesh-semantic.avif"


def pixels(image, box: tuple[int, int, int, int]):
    left, top, right, bottom = box
    return [
        image.getpixel((x, y))
        for y in range(top, bottom)
        for x in range(left, right)
    ]


def mean_rgb(image, box: tuple[int, int, int, int]):
    values = pixels(image, box)
    return tuple(
        sum(pixel[channel] for pixel in values) / len(values)
        for channel in range(3)
    )

def main() -> int:
    if len(sys.argv) != 1:
        raise RuntimeError(
            "check_multi_material_mesh_smoke.py does not accept arguments"
        )

    stats = json.loads(STATS_PATH.read_text(encoding="utf-8"))
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

    assert_avif_dimensions(IMAGE_PATH, 64, 64)

    # Material semantics are evaluated in the renderer's linear-light domain.
    # Decoded HDR AVIF bytes are PQ signal values, so reusing the old SDR byte
    # thresholds here would test the transfer function instead of materials.
    module = runpy.run_path(str(SCENE_PATH))
    capture_stats = module["create_renderer"]().render(
        output=SEMANTIC_PATH,
        stats_output=SEMANTIC_PATH.with_suffix(".stats.json"),
        width=64,
        height=64,
        spp=1,
        depth=4,
        seed=211,
        denoise=False,
        _test_capture_linear=True,
    )
    assert_avif_dimensions(SEMANTIC_PATH, 64, 64)
    image = captured_linear_image(capture_stats, 64, 64)

    red = mean_rgb(image, PANEL_BOXES["red"])
    screen = mean_rgb(image, PANEL_BOXES["screen"])
    metal = mean_rgb(image, PANEL_BOXES["metal"])

    if not (red[0] > 0.4 and red[0] > 8.0 * red[1]
            and red[0] > 20.0 * red[2]):
        raise RuntimeError("left RedPanel did not render red: {!r}".format(red))
    if not (max(screen) < 0.08 and screen[0] > 1.3 * screen[1]
            and screen[2] > 1.3 * screen[1]):
        raise RuntimeError(
            "center ScreenPanel did not preserve its dark colored atlas: "
            "mean={!r}".format(screen)
        )
    if max(metal) - min(metal) >= 0.03 or sum(metal) <= sum(screen) + 0.03:
        raise RuntimeError(
            "right MetalPanel is not distinct from the textured panel: "
            "metal_mean={!r}, screen_mean={!r}".format(metal, screen)
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
