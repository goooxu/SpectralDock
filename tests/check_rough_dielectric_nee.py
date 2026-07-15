#!/usr/bin/env python3
"""GPU checks for rough dielectric NEE/MIS and transparent blockers.

The checks intentionally compare pre-tone-map linear PFM values.  PNG is still
decoded once per render so the public output contract is exercised as well.
"""

import copy
import json
import math
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image


WIDTH = 96
HEIGHT = 72
HIGH_SPP = 8192
WATER_ROI = (5, 27, 91, 70)
RECEIVER_ROI = (18, 10, 78, 58)
GLASS_ROI = (23, 11, 73, 61)
GLASS_TRANSMISSION_ROI = (34, 22, 62, 50)


def read_pfm(path):
    with path.open("rb") as stream:
        if stream.readline() != b"PF\n":
            raise RuntimeError(f"{path.name}: expected three-channel PF header")
        dimensions = stream.readline().split()
        if len(dimensions) != 2:
            raise RuntimeError(f"{path.name}: malformed dimensions")
        width, height = map(int, dimensions)
        scale = float(stream.readline())
        if scale >= 0.0:
            raise RuntimeError(f"{path.name}: expected little-endian negative scale")
        payload = stream.read()
    expected = width * height * 3 * 4
    if len(payload) != expected:
        raise RuntimeError(
            f"{path.name}: expected {expected} payload bytes, got {len(payload)}"
        )
    bottom_up = struct.unpack(f"<{width * height * 3}f", payload)
    pixels = []
    row_values = width * 3
    for y in range(height - 1, -1, -1):
        row = bottom_up[y * row_values:(y + 1) * row_values]
        pixels.extend(zip(row[0::3], row[1::3], row[2::3]))
    if any(not math.isfinite(channel) for pixel in pixels for channel in pixel):
        raise RuntimeError(f"{path.name}: non-finite linear sample")
    return width, height, tuple(pixels)


def render(renderer, scene_data, directory, name, spp, depth, seed):
    scene = directory / f"{name}.json"
    png = directory / f"{name}.png"
    pfm = directory / f"{name}.pfm"
    scene.write_text(json.dumps(scene_data, indent=2) + "\n", encoding="utf-8")
    subprocess.run(
        [
            str(renderer), "--scene", str(scene), "--output", str(png),
            "--linear-output", str(pfm), "--width", str(WIDTH),
            "--height", str(HEIGHT), "--spp", str(spp),
            "--max-depth", str(depth), "--seed", str(seed), "--no-denoise",
        ],
        check=True,
    )
    with Image.open(png) as image:
        image.load()
        if image.size != (WIDTH, HEIGHT) or image.mode != "RGBA":
            raise RuntimeError(
                f"unexpected PNG output: {image.size} {image.mode}"
            )
    width, height, pixels = read_pfm(pfm)
    if (width, height) != (WIDTH, HEIGHT):
        raise RuntimeError(f"unexpected PFM dimensions: {width}x{height}")
    stats = json.loads(png.with_suffix(".stats.json").read_text(encoding="utf-8"))
    linear_name = stats.get("linear_output")
    if linear_name is None or Path(linear_name).name != pfm.name:
        raise RuntimeError("stats do not identify the requested linear output")
    return pixels, stats, pfm.read_bytes()


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


def set_water_roughness(scene, roughness):
    for material in scene["materials"]:
        if material["type"] == "water":
            material["roughness"] = roughness


def reflection_scene(source, bound):
    scene = copy.deepcopy(source)
    set_water_roughness(scene, 0.30)
    # Isolate a water reflection so the high-spp contract compares only the
    # two sampling strategies.  A front-facing disk has one constant normal
    # and an exact area-to-solid-angle map; unlike a sphere, it does not mix
    # front/back samples or a curved visible silhouette into this MIS check.
    scene["objects"] = [
        obj for obj in scene["objects"] if obj["name"] == "test_water"
    ]
    disk_center = [-3.0, 2.5, -6.3]
    disk_normal = [0.429, -0.358, 0.829]
    disk_radius = 0.55
    scene["objects"].append(
        {
            "name": "reflection_disk", "type": "disk",
            "center": disk_center, "normal": disk_normal,
            "radius": disk_radius, "front_material": "moon_probe",
        }
    )
    scene["lights"] = []
    if bound:
        scene["lights"].append(
            {
                "name": "bound_reflection_disk", "type": "disk",
                "object": "reflection_disk", "position": disk_center,
                "normal": disk_normal, "radius": disk_radius,
                "emission": [16.0, 20.0, 30.0],
            }
        )
    return scene


def blocker_scene(light_depth=-0.85):
    return {
        "schema_version": 6,
        "integrator": {
            "direct_light_sampling": "importance",
            "clamp_direct": 0.0,
            "clamp_indirect": 0.0,
        },
        "camera": {
            "look_from": [0.0, 1.25, 4.2], "look_at": [0.0, 1.0, 0.0],
            "up": [0.0, 1.0, 0.0], "vfov": 30.0,
            "aperture": 0.0, "focus_distance": 4.2,
        },
        "background": {
            "type": "constant", "color": [0.0, 0.0, 0.0], "exposure": 0.0,
        },
        "render": {
            "width": WIDTH, "height": HEIGHT, "spp": 256,
            "max_depth": 2, "seed": 911, "denoise": False,
        },
        "textures": [],
        "materials": [
            {"name": "water", "type": "water", "ior": 1.333,
             "roughness": 0.20, "absorption": [0.9, 0.22, 0.04]},
            {"name": "receiver", "type": "lambertian",
             "base_color": [0.82, 0.82, 0.82]},
            {"name": "dark", "type": "lambertian",
             "base_color": [0.005, 0.005, 0.005]},
            {"name": "source", "type": "emitter",
             "emission": [35.0, 35.0, 35.0]},
        ],
        "objects": [
            {"name": "receiver", "type": "rectangle",
             "p1": [-1.5, 0.25, 0.0], "p2": [-1.5, 1.9, 0.0],
             "p3": [1.5, 1.9, 0.0], "material": "receiver"},
            {"name": "underwater_source", "type": "sphere",
             "center": [0.0, light_depth, 1.65], "radius": 0.42,
             "material": "source"},
            {"name": "floor", "type": "rectangle",
             "p1": [-3.0, -2.0, 3.0], "p2": [-3.0, -2.0, -3.0],
             "p3": [3.0, -2.0, -3.0], "material": "dark"},
            {"name": "test_water", "type": "water_surface",
             "center": [0.0, 0.0, 1.0], "size": [6.0, 6.0],
             "material": "water",
             "waves": [
                 {"direction": [1.0, 0.2], "amplitude": 0.015,
                  "wavelength": 2.4, "phase_radians": 0.3},
                 {"direction": [-0.3, 1.0], "amplitude": 0.008,
                  "wavelength": 1.1, "phase_radians": 1.7},
             ]},
        ],
        "lights": [
            {"name": "underwater_light", "type": "sphere",
             "object": "underwater_source", "position": [0.0, light_depth, 1.65],
             "radius": 0.42, "emission": [35.0, 35.0, 35.0]},
        ],
    }


def generic_glass_scene(mode, ior=1.52):
    inside = mode == "inside_tir"
    scene = {
        "schema_version": 6,
        "integrator": {
            "direct_light_sampling": "importance",
            "clamp_direct": 0.0,
            "clamp_indirect": 0.0,
        },
        "camera": {
            "look_from": [0.0, 0.0, 0.78] if inside else [0.0, 0.0, 4.0],
            "look_at": [1.0, 0.0, 0.78] if inside else [0.0, 0.0, 0.0],
            "up": [0.0, 1.0, 0.0], "vfov": 22.0 if inside else 30.0,
            "aperture": 0.0, "focus_distance": 3.0,
        },
        "background": {
            "type": "constant", "color": [0.0, 0.0, 0.0], "exposure": 0.0,
        },
        "render": {
            "width": WIDTH, "height": HEIGHT, "spp": 256,
            "max_depth": 3, "seed": 2203, "denoise": False,
        },
        "textures": [],
        "materials": [
            {"name": "glass", "type": "dielectric",
             "base_color": [1.0, 1.0, 1.0], "ior": ior,
             "roughness": 0.08 if inside else 0.20},
            {"name": "blue_source", "type": "emitter",
             "emission": [0.3, 1.0, 18.0]},
        ],
        "objects": [],
        "lights": [],
    }
    if inside:
        # A back-face rectangle exercises the material-to-air branch without
        # relying on OptiX built-in sphere behavior for an inside-origin ray.
        scene["objects"].append(
            {"name": "glass_back_face", "type": "rectangle",
             "p1": [2.2, -2.0, -0.4], "p2": [-1.0, -2.0, 2.0],
             "p3": [-1.0, 2.0, 2.0], "material": "glass"}
        )
    else:
        scene["objects"].append(
            {"name": "glass_ball", "type": "sphere",
             "center": [0.0, 0.0, 0.0], "radius": 1.0,
             "material": "glass"}
        )
    if mode == "reflection":
        scene["lights"] = [
            {"name": "front_red", "type": "disk",
             "position": [2.2, 2.0, 2.8],
             "normal": [-0.54, -0.49, -0.69], "radius": 1.25,
             "emission": [22.0, 0.4, 0.2]},
        ]
    elif mode == "transmission":
        scene["objects"].append(
            {"name": "back_panel", "type": "rectangle",
             "p1": [-3.0, -3.0, -3.0], "p2": [-3.0, 3.0, -3.0],
             "p3": [3.0, 3.0, -3.0], "material": "blue_source"}
        )
    elif mode == "inside_tir":
        scene["lights"] = [
            {"name": "outside_probe", "type": "disk",
             "position": [3.0, 0.0, 0.8], "normal": [-1.0, 0.0, 0.0],
             "radius": 1.0, "emission": [12.0, 12.0, 12.0]},
        ]
    else:
        raise RuntimeError(f"unknown generic glass mode: {mode}")
    return scene


def main():
    if len(sys.argv) != 3:
        raise RuntimeError(
            "usage: check_rough_dielectric_nee.py RENDERER WATER_SCENE"
        )
    renderer = Path(sys.argv[1]).resolve()
    source = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory(prefix="spectraldock-rough-nee-") as tmp:
        directory = Path(tmp)
        bound_scene = reflection_scene(source, True)
        bsdf_scene = reflection_scene(source, False)

        bound_high, bound_stats, bound_bytes = render(
            renderer, bound_scene, directory, "bound-high", HIGH_SPP, 2, 1201
        )
        # The bound strategy can connect the emitter after two surface
        # scatterings, while the unbound strategy needs one additional depth
        # slot to hit that same emitter. Compare equal scattering orders.
        bsdf_high, _, _ = render(
            renderer, bsdf_scene, directory, "bsdf-high", HIGH_SPP, 3, 1301
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
            renderer, bound_scene, directory, "bound-repeat", HIGH_SPP, 2, 1201
        )
        if bound_bytes != repeat_bytes or bound_high != repeat:
            raise RuntimeError("fixed-seed linear rough-water output is not deterministic")

        nee_error = 0.0
        bsdf_error = 0.0
        for index, seed in enumerate((1409, 1511, 1601)):
            nee, _, _ = render(
                renderer, bound_scene, directory, f"nee-low-{index}", 32, 2, seed
            )
            bsdf, _, _ = render(
                renderer, bsdf_scene, directory, f"bsdf-low-{index}", 32, 3, seed
            )
            nee_error += mse(nee, bound_high, WATER_ROI)
            bsdf_error += mse(bsdf, bound_high, WATER_ROI)
        if nee_error > 0.50 * bsdf_error:
            raise RuntimeError(
                "rough-water NEE did not halve three-seed low-spp MSE: "
                f"nee={nee_error:.6g}, bsdf={bsdf_error:.6g}"
            )

        depth_one, depth_one_stats, _ = render(
            renderer, bound_scene, directory, "depth-one", 128, 1, 1709
        )
        if mean_luminance(depth_one, WATER_ROI) <= 1.0e-5:
            raise RuntimeError("depth-1 rough-water NEE produced no reflected light")
        if metric(depth_one_stats, "water_rough_nee_contributions") in (None, 0):
            raise RuntimeError("depth-1 rough-water NEE counter stayed zero")

        blocked = blocker_scene()
        depth1, _, _ = render(renderer, blocked, directory, "blocked-depth1", 512, 1, 1801)
        depth2, depth2_stats, _ = render(
            renderer, blocked, directory, "restored-depth2", 1024, 2, 1801
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
            renderer, blocker_scene(-0.45), directory, "beer-shallow", 1024, 2, 1901
        )
        deep, _, _ = render(
            renderer, blocker_scene(-1.35), directory, "beer-deep", 1024, 2, 1901
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
            renderer, generic_glass_scene("reflection"), directory,
            "generic-front-reflection", 256, 1, 2203
        )
        if mean_luminance(glass_reflection, GLASS_ROI) <= 1.0e-6:
            raise RuntimeError("air-side rough dielectric reflection NEE is blank")

        glass_transmission, _, _ = render(
            renderer, generic_glass_scene("transmission"), directory,
            "generic-front-back-transmission", 512, 3, 2309
        )
        if mean_luminance(
            glass_transmission, GLASS_TRANSMISSION_ROI
        ) <= 1.0e-6:
            raise RuntimeError(
                "rough dielectric did not traverse its front and back surfaces"
            )

        low_ior, _, _ = render(
            renderer, generic_glass_scene("inside_tir", 1.20), directory,
            "generic-inside-low-ior", 512, 1, 2411
        )
        high_ior, _, high_ior_bytes = render(
            renderer, generic_glass_scene("inside_tir", 2.40), directory,
            "generic-inside-tir", 512, 1, 2411
        )
        high_repeat, _, high_repeat_bytes = render(
            renderer, generic_glass_scene("inside_tir", 2.40), directory,
            "generic-inside-tir-repeat", 512, 1, 2411
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
    except (
        json.JSONDecodeError,
        OSError,
        RuntimeError,
        subprocess.CalledProcessError,
        struct.error,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
