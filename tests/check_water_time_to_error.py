#!/usr/bin/env python3
"""Maintenance-only Moonlit Stepwell time-to-error comparison.

Both estimators integrate the same roughness=0.12 scene and are measured
against one independent high-spp rough-water NEE reference.  The baseline
removes only explicit light bindings, retaining their emitter objects, so it
uses BSDF-only endpoint sampling without changing the scene radiance.  The
1024-spp NEE and 2048-spp BSDF-only candidates have comparable measured GPU
render time; three candidate seeds are disjoint from the reference stream.
"""

import copy
import json
import math
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


WIDTH = 320
HEIGHT = 180
REFERENCE_SPP = 8192
BSDF_ONLY_SPP = 2048
ROUGH_NEE_SPP = 1024
CANDIDATE_SEEDS = (1201, 2203, 3209)
REFLECTION_ROI = (60, 76, 190, 132)
UNDERWATER_ROI = (155, 82, 255, 142)


def set_water_roughness(scene, roughness):
    count = 0
    for material in scene["materials"]:
        if material["type"] == "water":
            material["roughness"] = roughness
            count += 1
    if count == 0:
        raise RuntimeError("Moonlit scene has no water material")


def read_pfm(path):
    with path.open("rb") as stream:
        if stream.readline() != b"PF\n":
            raise RuntimeError("linear reference is not a color PFM")
        width, height = map(int, stream.readline().split())
        if float(stream.readline()) >= 0.0:
            raise RuntimeError("linear PFM must use little-endian negative scale")
        values = struct.unpack(f"<{width * height * 3}f", stream.read())
    rows = [values[y * width * 3:(y + 1) * width * 3] for y in range(height)]
    pixels = []
    for row in reversed(rows):
        pixels.extend(zip(row[0::3], row[1::3], row[2::3]))
    if any(not math.isfinite(v) for pixel in pixels for v in pixel):
        raise RuntimeError("linear PFM contains non-finite values")
    return width, height, tuple(pixels)


def render(renderer, scene_data, directory, name, spp, seed):
    scene = directory / f"{name}.json"
    png = directory / f"{name}.png"
    pfm = directory / f"{name}.pfm"
    scene.write_text(json.dumps(scene_data, indent=2) + "\n", encoding="utf-8")
    subprocess.run(
        [
            str(renderer), "--scene", str(scene), "--output", str(png),
            "--linear-output", str(pfm), "--width", str(WIDTH),
            "--height", str(HEIGHT), "--spp", str(spp),
            "--max-depth", "12", "--seed", str(seed), "--no-denoise",
        ],
        check=True,
    )
    stats_path = png.with_suffix(".stats.json")
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    render_ms = stats.get("timings_ms", {}).get("render")
    if not isinstance(render_ms, (int, float)) or not math.isfinite(render_ms):
        raise RuntimeError(f"{stats_path.name}: invalid render time")
    if render_ms <= 0.0:
        raise RuntimeError(f"{stats_path.name}: render time must be positive")
    return read_pfm(pfm)[2], float(render_ms)


def normalized_mse(image, reference, box):
    left, top, right, bottom = box
    squared_error = 0.0
    reference_energy = 0.0
    count = 0
    for y in range(top, bottom):
        for x in range(left, right):
            offset = y * WIDTH + x
            for actual, target in zip(image[offset], reference[offset]):
                squared_error += (actual - target) ** 2
                reference_energy += target * target
                count += 1
    return (squared_error / count) / max(reference_energy / count, 1.0e-12)


def main():
    if len(sys.argv) != 3:
        raise RuntimeError(
            "usage: check_water_time_to_error.py RENDERER MOONLIT_SCENE"
        )
    renderer = Path(sys.argv[1]).resolve()
    source_path = Path(sys.argv[2]).resolve()
    base = json.loads(source_path.read_text(encoding="utf-8"))
    for mesh in base.get("meshes", []):
        path = Path(mesh["path"])
        if not path.is_absolute():
            mesh["path"] = str((source_path.parent / path).resolve())
    for texture in base.get("textures", []):
        raw_path = texture.get("path")
        if raw_path is None:
            continue
        path = Path(raw_path)
        if not path.is_absolute():
            texture["path"] = str((source_path.parent / path).resolve())
    background = base.get("background", {})
    if background.get("type") == "environment":
        path = Path(background["path"])
        if not path.is_absolute():
            background["path"] = str((source_path.parent / path).resolve())
    rough = copy.deepcopy(base)
    set_water_roughness(rough, 0.12)
    bsdf_only = copy.deepcopy(rough)
    if not bsdf_only.get("lights"):
        raise RuntimeError("Moonlit scene has no explicit lights to unbind")
    bsdf_only["lights"] = []

    with tempfile.TemporaryDirectory(prefix="spectraldock-water-error-") as tmp:
        directory = Path(tmp)
        reference, _ = render(
            renderer, rough, directory, "rough-nee-reference", REFERENCE_SPP, 809
        )
        bsdf_only_candidates = []
        rough_nee_candidates = []
        for seed in CANDIDATE_SEEDS:
            bsdf_only_candidates.append(
                render(
                    renderer, bsdf_only, directory,
                    f"rough-bsdf-only-{BSDF_ONLY_SPP}-seed-{seed}",
                    BSDF_ONLY_SPP, seed,
                )
            )
            rough_nee_candidates.append(
                render(
                    renderer, rough, directory,
                    f"rough-nee-{ROUGH_NEE_SPP}-seed-{seed}",
                    ROUGH_NEE_SPP, seed,
                )
            )

        comparisons = []
        for name, roi in (
            ("reflection", REFLECTION_ROI),
            ("underwater", UNDERWATER_ROI),
        ):
            bsdf_only_error = sum(
                normalized_mse(candidate[0], reference, roi)
                for candidate in bsdf_only_candidates
            ) / len(bsdf_only_candidates)
            rough_nee_error = sum(
                normalized_mse(candidate[0], reference, roi)
                for candidate in rough_nee_candidates
            ) / len(rough_nee_candidates)
            comparisons.append(
                (name, rough_nee_error, bsdf_only_error)
            )
            print(
                f"{name}: rough_nee_{ROUGH_NEE_SPP}={rough_nee_error:.6g} "
                f"rough_bsdf_only_{BSDF_ONLY_SPP}={bsdf_only_error:.6g}"
            )

        bsdf_only_ms = sum(
            candidate[1] for candidate in bsdf_only_candidates
        ) / len(bsdf_only_candidates)
        rough_nee_ms = sum(
            candidate[1] for candidate in rough_nee_candidates
        ) / len(rough_nee_candidates)
        print(
            f"mean render time: rough_nee_{ROUGH_NEE_SPP}={rough_nee_ms:.3f} ms "
            f"rough_bsdf_only_{BSDF_ONLY_SPP}={bsdf_only_ms:.3f} ms"
        )

        failures = [
            f"{name} error: nee={rough_nee_error:.6g}, "
            f"bsdf_only={bsdf_only_error:.6g}"
            for name, rough_nee_error, bsdf_only_error in comparisons
            if rough_nee_error > bsdf_only_error
        ]
        if rough_nee_ms > 1.15 * bsdf_only_ms:
            failures.append(
                f"render time: nee={rough_nee_ms:.3f} ms, "
                f"bsdf_only={bsdf_only_ms:.3f} ms"
            )
        if failures:
            raise RuntimeError(
                "rough-water NEE did not beat the comparable-time BSDF-only "
                "baseline: " + "; ".join(failures)
            )

    print("Moonlit Stepwell rough-water NEE time-to-error comparison passed")
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
