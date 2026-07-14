#!/usr/bin/env python3
"""Generate the deterministic 16-mascot / 1024-sphere harbor scene."""

import argparse
import json
import math
import random
import sys
from pathlib import Path


DEFAULT_SEED = 20260707
GRID_SIDE = 32
WAVE_COUNT = GRID_SIDE * GRID_SIDE
MASCOT_COUNT = 16
WAVE_RADIUS = 0.17
WAVE_SPACING = 0.48


def rounded(value):
    return round(float(value), 6)


def build_scene(seed=DEFAULT_SEED):
    rng = random.Random(seed)
    objects = []

    # Every mascot names the same mesh resource. The renderer builds
    # one compacted GAS and keeps per-object transforms/materials in the IAS.
    for row in range(4):
        for column in range(4):
            index = row * 4 + column
            x = -5.4 + column * 3.6
            z = -5.4 + row * 3.6
            phase = 0.41 * row + 0.63 * column
            y = 0.05 + 0.08 * math.sin(phase) + rng.uniform(-0.01, 0.01)
            objects.append({
                "name": "mascot_{:02d}".format(index),
                "type": "mesh",
                "mesh": "mascot",
                "transform": {
                    "translate": [rounded(x), rounded(y), rounded(z)],
                    "rotate_degrees": [
                        rounded(rng.uniform(-1.5, 1.5)),
                        rounded(18.0 * math.sin(phase) + rng.uniform(-2.0, 2.0)),
                        rounded(rng.uniform(-2.0, 2.0)),
                    ],
                    "scale": [0.88, 0.88, 0.88],
                },
                "material": "mascot_{}".format(index % 4),
            })

    half = 0.5 * (GRID_SIDE - 1) * WAVE_SPACING
    for row in range(GRID_SIDE):
        for column in range(GRID_SIDE):
            index = row * GRID_SIDE + column
            x = column * WAVE_SPACING - half
            z = row * WAVE_SPACING - half
            wave = (
                0.055 * math.sin(0.72 * x + 0.31 * z)
                + 0.035 * math.cos(0.28 * x - 0.83 * z)
                + rng.uniform(-0.006, 0.006)
            )
            objects.append({
                "name": "wave_{:04d}".format(index),
                "type": "sphere",
                "center": [rounded(x), rounded(-0.22 + wave), rounded(z)],
                "radius": WAVE_RADIUS,
                "material": "water_{}".format((row + 3 * column) % 4),
            })

    return {
        "schema_version": 5,
        "camera": {
            "look_from": [15.0, 10.0, 18.0],
            "look_at": [0.0, 0.1, 0.0],
            "up": [0.0, 1.0, 0.0],
            "vfov": 35.0,
            "aperture": 0.035,
            "focus_distance": 25.4,
        },
        "background": {
            "type": "sky",
            "bottom": [0.08, 0.16, 0.24],
            "top": [0.015, 0.035, 0.09],
            "sun_direction": [-0.4, 0.78, -0.48],
            "sun_color": [2.8, 2.1, 1.45],
            "sun_cos_angle": 0.997,
            "exposure": 0.0,
        },
        "render": {
            "width": 1920,
            "height": 1080,
            "spp": 512,
            "max_depth": 12,
            "seed": seed,
            "denoise": True,
        },
        "textures": [],
        "materials": [
            {"name": "water_0", "type": "metal", "base_color": [0.025, 0.18, 0.28], "roughness": 0.16},
            {"name": "water_1", "type": "metal", "base_color": [0.035, 0.25, 0.34], "roughness": 0.19},
            {"name": "water_2", "type": "metal", "base_color": [0.04, 0.31, 0.39], "roughness": 0.22},
            {"name": "water_3", "type": "metal", "base_color": [0.03, 0.22, 0.32], "roughness": 0.18},
            {"name": "mascot_0", "type": "lambertian", "base_color": [0.84, 0.12, 0.05]},
            {"name": "mascot_1", "type": "lambertian", "base_color": [0.95, 0.44, 0.04]},
            {"name": "mascot_2", "type": "lambertian", "base_color": [0.06, 0.34, 0.58]},
            {"name": "mascot_3", "type": "lambertian", "base_color": [0.82, 0.82, 0.76]},
        ],
        "meshes": [
            {"name": "mascot", "path": "../assets/examples/models/capsule-mascot.obj"}
        ],
        "objects": objects,
        "lights": [
            {
                "name": "harbor_key",
                "type": "rectangle",
                "position": [-8.0, 12.0, -6.0],
                "edge_u": [12.0, 0.0, 0.0],
                "edge_v": [0.0, 0.0, 8.0],
                "emission": [5.5, 4.6, 3.5],
            },
            {
                "name": "harbor_fill",
                "type": "disk",
                "position": [9.0, 7.0, 8.0],
                "normal": [-0.62, -0.52, -0.58],
                "radius": 2.8,
                "emission": [1.1, 2.2, 3.8],
            },
        ],
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "scenes" / "benchmark-harbor.json",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)
    if args.seed < 0:
        parser.error("--seed must be non-negative")
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        scene = build_scene(args.seed)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(scene, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as error:
        print("error: {}".format(error), file=sys.stderr)
        return 2
    print(
        "generated {} with {} shared-mascot instances and {} non-overlapping wave spheres (seed={})".format(
            args.output, MASCOT_COUNT, WAVE_COUNT, args.seed
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
