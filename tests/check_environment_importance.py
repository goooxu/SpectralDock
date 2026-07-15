#!/usr/bin/env python3
"""Directional GPU checks for HDR environment lookup, NEE, and sampling."""

import copy
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image


WIDTH = 64
HEIGHT = 64
ROI = (8, 8, 56, 56)


def rgbe(red, green, blue):
    maximum = max(red, green, blue)
    if maximum < 1.0e-32:
        return bytes((0, 0, 0, 0))
    mantissa, exponent = math.frexp(maximum)
    scale = mantissa * 256.0 / maximum
    return bytes(
        (
            min(255, int(red * scale)),
            min(255, int(green * scale)),
            min(255, int(blue * scale)),
            exponent + 128,
        )
    )


def encode_channel(values):
    encoded = bytearray()
    index = 0
    while index < len(values):
        run = 1
        while (
            index + run < len(values)
            and values[index + run] == values[index]
            and run < 127
        ):
            run += 1
        if run >= 4:
            encoded.extend((128 + run, values[index]))
            index += run
            continue

        literal = bytearray()
        while index < len(values) and len(literal) < 128:
            next_run = 1
            while (
                index + next_run < len(values)
                and values[index + next_run] == values[index]
                and next_run < 127
            ):
                next_run += 1
            if next_run >= 4 and literal:
                break
            take = min(next_run, 128 - len(literal))
            literal.extend(values[index:index + take])
            index += take
        encoded.append(len(literal))
        encoded.extend(literal)
    return encoded


def write_asymmetric_hdr(path):
    width = 64
    height = 32
    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            value = (0.025, 0.030, 0.040)
            if 40 <= x < 50 and 7 <= y < 14:
                value = (18.0, 10.0, 3.0)
            elif 8 <= x < 22 and 19 <= y < 24:
                value = (1.5, 3.0, 11.0)
            row.append(rgbe(*value))
        rows.append(row)

    payload = bytearray(
        b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 32 +X 64\n"
    )
    for row in rows:
        payload.extend((2, 2, width >> 8, width & 255))
        for channel in range(4):
            payload.extend(encode_channel([pixel[channel] for pixel in row]))
    path.write_bytes(payload)


def receiver_scene(source, hdr_name):
    scene = copy.deepcopy(source)
    scene["schema_version"] = 6
    scene["camera"] = {
        "look_from": [0.0, 0.0, 3.0],
        "look_at": [0.0, 0.0, 0.0],
        "up": [0.0, 1.0, 0.0],
        "vfov": 42.0,
        "aperture": 0.0,
        "focus_distance": 3.0,
    }
    scene["integrator"] = {
        "direct_light_sampling": "importance",
        "clamp_direct": 0.0,
        "clamp_indirect": 0.0,
    }
    scene["background"] = {
        "type": "environment",
        "path": hdr_name,
        "intensity": 1.0,
        "rotation_degrees": 0.0,
        "exposure": -2.0,
    }
    scene["render"] = {
        "width": WIDTH,
        "height": HEIGHT,
        "spp": 8,
        "max_depth": 1,
        "seed": 109,
        "denoise": False,
    }
    scene["textures"] = []
    scene["materials"] = [
        {
            "name": "receiver",
            "type": "lambertian",
            "base_color": [0.72, 0.72, 0.72],
        }
    ]
    scene.pop("meshes", None)
    scene["objects"] = [
        {
            "name": "receiver",
            "type": "rectangle",
            "p1": [-2.0, -2.0, 0.0],
            "p2": [-2.0, 2.0, 0.0],
            "p3": [2.0, 2.0, 0.0],
            "material": "receiver",
        }
    ]
    scene["lights"] = []
    return scene


def render(renderer, base, directory, name, mode, spp, seed, intensity=1.0,
           rotation=0.0):
    scene_data = copy.deepcopy(base)
    scene_data["integrator"]["direct_light_sampling"] = mode
    scene_data["background"]["intensity"] = intensity
    scene_data["background"]["rotation_degrees"] = rotation
    scene_data["render"]["spp"] = spp
    scene_data["render"]["seed"] = seed
    scene = directory / (name + ".json")
    output = directory / (name + ".png")
    scene.write_text(json.dumps(scene_data, indent=2) + "\n", encoding="utf-8")
    subprocess.run(
        [
            str(renderer),
            "--scene", str(scene),
            "--output", str(output),
            "--width", str(WIDTH),
            "--height", str(HEIGHT),
            "--spp", str(spp),
            "--max-depth", "1",
            "--seed", str(seed),
            "--no-denoise",
        ],
        check=True,
    )
    with Image.open(output) as decoded:
        decoded.load()
        if decoded.size != (WIDTH, HEIGHT) or decoded.mode != "RGBA":
            raise RuntimeError(
                "unexpected environment output: {} {}".format(
                    decoded.size, decoded.mode
                )
            )
        image = decoded.copy()
    stats = json.loads(
        output.with_suffix(".stats.json").read_text(encoding="utf-8")
    )
    actual_mode = stats.get("render", {}).get("direct_light_sampling")
    if actual_mode != mode:
        raise RuntimeError(
            "stats report direct_light_sampling={!r}, expected {!r}".format(
                actual_mode, mode
            )
        )
    return image


def rgb_values(image):
    return [pixel[:3] for pixel in image.crop(ROI).getdata()]


def mean_luminance(image):
    values = rgb_values(image)
    return sum(
        0.2126 * red + 0.7152 * green + 0.0722 * blue
        for red, green, blue in values
    ) / len(values)


def mse(image, reference):
    left = rgb_values(image)
    right = rgb_values(reference)
    return sum(
        (a - b) * (a - b)
        for left_pixel, right_pixel in zip(left, right)
        for a, b in zip(left_pixel, right_pixel)
    ) / (3.0 * len(left))


def rgb_is_black(image):
    return all(
        red == 0 and green == 0 and blue == 0
        for red, green, blue, _ in image.getdata()
    )


def main():
    if len(sys.argv) != 3:
        raise RuntimeError(
            "usage: check_environment_importance.py RENDERER ENVIRONMENT_SCENE"
        )
    renderer = Path(sys.argv[1]).resolve()
    fixture = Path(sys.argv[2]).resolve()
    if not renderer.is_file():
        raise RuntimeError("renderer not found: {}".format(renderer))
    source = json.loads(fixture.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory(prefix="spectraldock-environment-") as tmp:
        directory = Path(tmp)
        hdr = directory / "asymmetric-studio.hdr"
        write_asymmetric_hdr(hdr)
        base = receiver_scene(source, hdr.name)

        first = render(renderer, base, directory, "deterministic-a",
                       "importance", 8, 109)
        second = render(renderer, base, directory, "deterministic-b",
                        "importance", 8, 109)
        if first.tobytes() != second.tobytes():
            raise RuntimeError("fixed-seed environment renders are not identical")
        if mean_luminance(first) <= 0.5:
            raise RuntimeError("depth-1 environment NEE produced a blank receiver")

        dark = render(renderer, base, directory, "zero-intensity",
                      "importance", 8, 109, intensity=0.0)
        if not rgb_is_black(dark):
            raise RuntimeError("zero-intensity environment must be exactly black")

        unrotated = render(renderer, base, directory, "rotation-0",
                           "importance", 64, 211, rotation=0.0)
        rotated = render(renderer, base, directory, "rotation-180",
                         "importance", 64, 211, rotation=180.0)
        if abs(mean_luminance(unrotated) - mean_luminance(rotated)) < 1.0:
            raise RuntimeError("180-degree environment rotation had no visible response")

        reference = render(renderer, base, directory, "reference",
                           "importance", 1024, 313)
        uniform_high = render(renderer, base, directory, "uniform-high",
                              "uniform", 1024, 419)
        reference_mean = mean_luminance(reference)
        uniform_mean = mean_luminance(uniform_high)
        relative_mean_error = abs(reference_mean - uniform_mean) / max(
            reference_mean, 1.0
        )
        if relative_mean_error > 0.12:
            raise RuntimeError(
                "uniform/importance high-spp means did not converge: {:.3f}".format(
                    relative_mean_error
                )
            )

        uniform_error = 0.0
        importance_error = 0.0
        for index, seed in enumerate((521, 631, 743)):
            uniform = render(
                renderer, base, directory, "uniform-low-{}".format(index),
                "uniform", 8, seed
            )
            importance = render(
                renderer, base, directory, "importance-low-{}".format(index),
                "importance", 8, seed
            )
            uniform_error += mse(uniform, reference)
            importance_error += mse(importance, reference)
        if not importance_error < 0.85 * uniform_error:
            raise RuntimeError(
                "environment importance sampling did not reduce low-spp MSE: "
                "importance={:.3f}, uniform={:.3f}".format(
                    importance_error, uniform_error
                )
            )

    print("HDR environment lookup and importance sampling checks passed")
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
