#!/usr/bin/env python3
"""GPU A/B check for the production Radiance Pavilion environment."""

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image


WIDTH = 256
HEIGHT = 144
MAX_DEPTH = 8
LOW_SPP = 8
HIGH_SPP = 256
REFERENCE_SPP = 1024
# The retained Pavilion camera puts the stage and exhibits below the horizon.
# Excluding most directly visible sky keeps the metric focused on lit geometry.
ROI = (12, 46, 244, 144)
LOW_SEEDS = (1109, 1223, 1327)
REFERENCE_SEED = 9001
HIGH_UNIFORM_SEED = 2011
HIGH_IMPORTANCE_SEED = 2027
MAX_MSE_RATIO = 0.85
MAX_HIGH_SPP_MEAN_ERROR = 0.08


def absolute_asset_path(scene_path, asset_path):
    path = Path(asset_path)
    if not path.is_absolute():
        path = scene_path.parent / path
    return str(path.resolve())


def scene_with_absolute_assets(scene_path):
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    background = scene.get("background", {})
    if background.get("type") != "environment" or not background.get("path"):
        raise RuntimeError("Radiance Pavilion must use an HDR environment")
    if scene.get("lights") != []:
        raise RuntimeError(
            "Radiance Pavilion A/B requires the environment to be its only light"
        )
    emissive_materials = [
        material.get("name", "<unnamed>")
        for material in scene.get("materials", [])
        if material.get("type") == "emitter"
        or any(component > 0.0 for component in material.get("emission", []))
    ]
    procedural_emitters = [
        object_data.get("name", "<unnamed>")
        for object_data in scene.get("objects", [])
        if object_data.get("type") == "flame"
    ]
    if emissive_materials or procedural_emitters:
        raise RuntimeError(
            "Radiance Pavilion A/B found non-environment emitters: materials={}, "
            "objects={}".format(emissive_materials, procedural_emitters)
        )
    background["path"] = absolute_asset_path(scene_path, background["path"])

    for mesh in scene.get("meshes", []):
        if not mesh.get("path"):
            raise RuntimeError("mesh is missing its path: {!r}".format(mesh))
        mesh["path"] = absolute_asset_path(scene_path, mesh["path"])

    for asset in [background["path"]] + [
        mesh["path"] for mesh in scene.get("meshes", [])
    ]:
        if not Path(asset).is_file():
            raise RuntimeError("scene asset not found: {}".format(asset))

    scene["render"].update(
        {
            "width": WIDTH,
            "height": HEIGHT,
            "spp": LOW_SPP,
            "max_depth": MAX_DEPTH,
            "denoise": False,
        }
    )
    return scene


def render(renderer, base, directory, name, mode, spp, seed):
    scene_data = copy.deepcopy(base)
    scene_data["integrator"]["direct_light_sampling"] = mode
    scene_data["render"]["spp"] = spp
    scene_data["render"]["seed"] = seed

    scene_path = directory / (name + ".json")
    output_path = directory / (name + ".png")
    scene_path.write_text(
        json.dumps(scene_data, indent=2) + "\n", encoding="utf-8"
    )
    subprocess.run(
        [
            str(renderer),
            "--scene", str(scene_path),
            "--output", str(output_path),
            "--width", str(WIDTH),
            "--height", str(HEIGHT),
            "--spp", str(spp),
            "--max-depth", str(MAX_DEPTH),
            "--seed", str(seed),
            "--no-denoise",
        ],
        check=True,
    )

    with Image.open(output_path) as decoded:
        decoded.load()
        if decoded.size != (WIDTH, HEIGHT) or decoded.mode != "RGBA":
            raise RuntimeError(
                "unexpected Pavilion output: {} {}".format(
                    decoded.size, decoded.mode
                )
            )
        image = decoded.copy()

    stats = json.loads(
        output_path.with_suffix(".stats.json").read_text(encoding="utf-8")
    )
    actual = stats.get("render", {})
    expected = {
        "width": WIDTH,
        "height": HEIGHT,
        "spp": spp,
        "max_depth": MAX_DEPTH,
        "seed": seed,
        "denoised": False,
        "direct_light_sampling": mode,
    }
    for key, value in expected.items():
        if actual.get(key) != value:
            raise RuntimeError(
                "stats render.{}={!r}, expected {!r}".format(
                    key, actual.get(key), value
                )
            )
    return image


def roi_rgb(image):
    return [pixel[:3] for pixel in image.crop(ROI).getdata()]


def mse(image, reference):
    actual = roi_rgb(image)
    expected = roi_rgb(reference)
    return sum(
        (left - right) * (left - right)
        for actual_pixel, expected_pixel in zip(actual, expected)
        for left, right in zip(actual_pixel, expected_pixel)
    ) / (3.0 * len(actual))


def mean_luminance(image):
    pixels = roi_rgb(image)
    return sum(
        0.2126 * red + 0.7152 * green + 0.0722 * blue
        for red, green, blue in pixels
    ) / len(pixels)


def main():
    if len(sys.argv) != 3:
        raise RuntimeError(
            "usage: check_radiance_pavilion_importance.py "
            "RENDERER scenes/radiance-pavilion.json"
        )
    renderer = Path(sys.argv[1]).resolve()
    scene_path = Path(sys.argv[2]).resolve()
    if not renderer.is_file():
        raise RuntimeError("renderer not found: {}".format(renderer))
    if not scene_path.is_file():
        raise RuntimeError("scene not found: {}".format(scene_path))
    base = scene_with_absolute_assets(scene_path)

    with tempfile.TemporaryDirectory(
        prefix="spectraldock-radiance-pavilion-"
    ) as temporary:
        directory = Path(temporary)
        reference = render(
            renderer,
            base,
            directory,
            "importance-reference",
            "importance",
            REFERENCE_SPP,
            REFERENCE_SEED,
        )
        reference_mean = mean_luminance(reference)
        if reference_mean <= 1.0:
            raise RuntimeError(
                "Pavilion reference ROI is blank or unexpectedly dark: {:.3f}".format(
                    reference_mean
                )
            )

        uniform_error = 0.0
        importance_error = 0.0
        for index, seed in enumerate(LOW_SEEDS):
            uniform = render(
                renderer,
                base,
                directory,
                "uniform-low-{}".format(index),
                "uniform",
                LOW_SPP,
                seed,
            )
            importance = render(
                renderer,
                base,
                directory,
                "importance-low-{}".format(index),
                "importance",
                LOW_SPP,
                seed,
            )
            uniform_error += mse(uniform, reference)
            importance_error += mse(importance, reference)

        if uniform_error <= 1.0e-12:
            raise RuntimeError("Pavilion uniform low-spp reference error is zero")
        mse_ratio = importance_error / uniform_error
        if mse_ratio > MAX_MSE_RATIO:
            raise RuntimeError(
                "Pavilion importance sampling did not reduce cumulative "
                "low-spp RGB MSE by 15%: importance={:.3f}, uniform={:.3f}, "
                "ratio={:.3f}".format(
                    importance_error, uniform_error, mse_ratio
                )
            )

        uniform_high = render(
            renderer,
            base,
            directory,
            "uniform-high",
            "uniform",
            HIGH_SPP,
            HIGH_UNIFORM_SEED,
        )
        importance_high = render(
            renderer,
            base,
            directory,
            "importance-high",
            "importance",
            HIGH_SPP,
            HIGH_IMPORTANCE_SEED,
        )
        uniform_mean = mean_luminance(uniform_high)
        importance_mean = mean_luminance(importance_high)
        relative_mean_error = abs(uniform_mean - importance_mean) / max(
            importance_mean, 1.0
        )
        if relative_mean_error > MAX_HIGH_SPP_MEAN_ERROR:
            raise RuntimeError(
                "Pavilion uniform/importance high-spp ROI means did not "
                "converge: uniform={:.3f}, importance={:.3f}, "
                "relative_error={:.3f}".format(
                    uniform_mean, importance_mean, relative_mean_error
                )
            )

    print(
        "Radiance Pavilion importance A/B passed: "
        "low-spp MSE ratio={:.3f}, high-spp mean error={:.3f}".format(
            mse_ratio, relative_mean_error
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        json.JSONDecodeError,
        OSError,
        RuntimeError,
        subprocess.CalledProcessError,
    ) as error:
        print("error: {}".format(error), file=sys.stderr)
        raise SystemExit(1)
