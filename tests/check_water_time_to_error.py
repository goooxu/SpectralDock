#!/usr/bin/env python3
"""Maintenance-only Moonlit Stepwell time-to-error comparison.

Both estimators integrate the same roughness=0.12 scene and are measured
against one independent high-spp rough-water NEE reference. The baseline
retains all emitter objects but omits their explicit light bindings, so it uses
BSDF-only endpoint sampling without changing scene radiance.
"""

import math
import struct
import sys
import tempfile
from pathlib import Path

from spectraldock import Renderer


ROOT = Path(__file__).resolve().parents[1]
WIDTH = 320
HEIGHT = 180
REFERENCE_SPP = 8192
BSDF_ONLY_SPP = 2048
ROUGH_NEE_SPP = 1024
CANDIDATE_SEEDS = (1201, 2203, 3209)
REFLECTION_ROI = (60, 76, 190, 132)
UNDERWATER_ROI = (155, 82, 255, 142)


def moonlit_renderer(bind_lights):
    renderer = Renderer()
    renderer.integrator(
        direct_light_sampling="importance", clamp_direct=64.0, clamp_indirect=16.0
    )
    renderer.camera(
        look_from=(5.0, 5.1, 11.2),
        look_at=(0.0, -0.25, -1.25),
        up=(0.0, 1.0, 0.0),
        vfov=36.0,
        aperture=0.0,
        focus_distance=13.8,
    )
    renderer.background(
        type="sky",
        bottom=(0.020, 0.028, 0.050),
        top=(0.002, 0.004, 0.015),
        sun_direction=(-0.25, 0.82, -0.51),
        sun_color=(0.0, 0.0, 0.0),
        sun_cos_angle=2.0,
        exposure=0.65,
    )
    dry_sandstone = renderer.material(
        name="dry_sandstone", type="lambertian", base_color=(0.42, 0.30, 0.18)
    )
    wet_sandstone = renderer.material(
        name="wet_sandstone", type="lambertian", base_color=(0.12, 0.15, 0.17)
    )
    pool_mosaic = renderer.material(
        name="pool_mosaic", type="lambertian", base_color=(0.045, 0.14, 0.17)
    )
    aged_bronze = renderer.material(
        name="aged_bronze", type="metal", base_color=(0.42, 0.24, 0.09), roughness=0.28
    )
    moon_ceramic = renderer.material(
        name="moon_ceramic", type="lambertian", base_color=(0.64, 0.61, 0.52)
    )
    moon_water = renderer.material(
        name="moon_water",
        type="water",
        roughness=0.12,
        ior=1.333,
        absorption=(0.42, 0.10, 0.035),
    )
    moon_emitter = renderer.material(
        name="moon_emitter", type="emitter", emission=(28.0, 34.0, 50.0)
    )
    sconce_emitter = renderer.material(
        name="sconce_emitter", type="emitter", emission=(9.0, 2.8, 0.7)
    )
    submerged_emitter = renderer.material(
        name="submerged_emitter", type="emitter", emission=(0.28, 1.05, 1.9)
    )
    mascot = renderer.mesh(
        name="mascot", path=ROOT / "assets/examples/models/capsule-mascot.obj"
    )

    def rectangle(name, p1, p2, p3, material):
        return renderer.object(
            name=name, type="rectangle", p1=p1, p2=p2, p3=p3, material=material
        )

    def cylinder(name, base, axis, height, radius, material):
        return renderer.object(
            name=name,
            type="cylinder",
            base=base,
            axis=axis,
            height=height,
            radius=radius,
            material=material,
        )

    def disk(name, center, normal, radius, material):
        return renderer.object(
            name=name,
            type="disk",
            center=center,
            normal=normal,
            radius=radius,
            material=material,
        )

    rectangle("pool_floor", (-3.4, -1.65, 1.7), (-3.4, -1.65, -3.7), (3.4, -1.65, -3.7), pool_mosaic)
    for values in (
        ("left_lower_walk", (-4.4, -0.10, 2.2), (-4.4, -0.10, -4.2), (-3.4, -0.10, -4.2), wet_sandstone),
        ("right_lower_walk", (3.4, -0.10, 2.2), (3.4, -0.10, -4.2), (4.4, -0.10, -4.2), wet_sandstone),
        ("left_middle_walk", (-5.4, 0.35, 2.8), (-5.4, 0.35, -4.8), (-4.4, 0.35, -4.8), dry_sandstone),
        ("right_middle_walk", (4.4, 0.35, 2.8), (4.4, 0.35, -4.8), (5.4, 0.35, -4.8), dry_sandstone),
        ("left_upper_walk", (-6.4, 0.80, 4.2), (-6.4, 0.80, -5.4), (-5.4, 0.80, -5.4), dry_sandstone),
        ("right_upper_walk", (5.4, 0.80, 4.2), (5.4, 0.80, -5.4), (6.4, 0.80, -5.4), dry_sandstone),
        ("front_lower_step", (-3.4, -0.10, 2.5), (-3.4, -0.10, 1.7), (3.4, -0.10, 1.7), wet_sandstone),
        ("front_middle_step", (-4.4, 0.35, 3.3), (-4.4, 0.35, 2.5), (4.4, 0.35, 2.5), dry_sandstone),
        ("front_upper_step", (-5.4, 0.80, 4.2), (-5.4, 0.80, 3.3), (5.4, 0.80, 3.3), dry_sandstone),
        ("back_lower_step", (-3.4, -0.10, -3.7), (-3.4, -0.10, -4.2), (3.4, -0.10, -4.2), wet_sandstone),
        ("back_middle_step", (-4.4, 0.35, -4.2), (-4.4, 0.35, -4.8), (4.4, 0.35, -4.8), dry_sandstone),
        ("back_upper_step", (-5.4, 0.80, -4.8), (-5.4, 0.80, -5.4), (5.4, 0.80, -5.4), dry_sandstone),
        ("front_lower_riser", (-3.4, -1.65, 1.7), (-3.4, -0.10, 1.7), (3.4, -0.10, 1.7), wet_sandstone),
        ("front_middle_riser", (-4.4, -0.10, 2.5), (-4.4, 0.35, 2.5), (4.4, 0.35, 2.5), dry_sandstone),
        ("front_upper_riser", (-5.4, 0.35, 3.3), (-5.4, 0.80, 3.3), (5.4, 0.80, 3.3), dry_sandstone),
        ("back_pool_riser", (-3.4, -1.65, -3.7), (-3.4, -0.10, -3.7), (3.4, -0.10, -3.7), wet_sandstone),
        ("left_pool_riser", (-3.4, -1.65, -3.7), (-3.4, -0.10, -3.7), (-3.4, -0.10, 1.7), wet_sandstone),
        ("right_pool_riser", (3.4, -1.65, 1.7), (3.4, -0.10, 1.7), (3.4, -0.10, -3.7), wet_sandstone),
        ("left_wall", (-6.4, 0.0, -5.4), (-6.4, 4.8, -5.4), (-6.4, 4.8, 4.2), dry_sandstone),
        ("right_wall", (6.4, 0.0, 4.2), (6.4, 4.8, 4.2), (6.4, 4.8, -5.4), dry_sandstone),
        ("back_wall", (-6.4, 0.0, -5.4), (-6.4, 5.2, -5.4), (6.4, 5.2, -5.4), dry_sandstone),
    ):
        rectangle(*values)

    cylinder("left_column", (-5.55, 0.8, -4.65), (0.0, 1.0, 0.0), 4.1, 0.27, aged_bronze)
    cylinder("right_column", (5.55, 0.8, -4.65), (0.0, 1.0, 0.0), 4.1, 0.27, aged_bronze)
    disk("left_brazier", (-5.55, 4.9, -4.65), (0.0, 1.0, 0.0), 0.42, aged_bronze)
    disk("right_brazier", (5.55, 4.9, -4.65), (0.0, 1.0, 0.0), 0.42, aged_bronze)
    cylinder("central_dais", (0.0, -1.65, -1.0), (0.0, 1.0, 0.0), 2.35, 0.82, wet_sandstone)
    disk("central_dais_cap", (0.0, 0.70, -1.0), (0.0, 1.0, 0.0), 0.82, dry_sandstone)
    renderer.object(
        name="submerged_bronze_orb",
        type="sphere",
        center=(-1.65, -0.98, -1.20),
        radius=0.42,
        material=aged_bronze,
    )
    renderer.object(
        name="submerged_ceramic_orb",
        type="sphere",
        center=(1.55, -1.02, -0.55),
        radius=0.38,
        material=moon_ceramic,
    )
    submerged_marker = renderer.object(
        name="submerged_marker",
        type="sphere",
        center=(0.35, -1.28, -2.95),
        radius=0.12,
        material=submerged_emitter,
    )
    left_sconce = disk(
        "left_sconce", (-6.35, 2.65, -1.55), (1.0, 0.0, 0.0), 0.24, sconce_emitter
    )
    right_sconce = disk(
        "right_sconce", (6.35, 2.65, -1.55), (-1.0, 0.0, 0.0), 0.24, sconce_emitter
    )
    renderer.object(
        name="moon_pool",
        type="water_surface",
        center=(0.0, -0.35, -1.0),
        size=(6.8, 5.4),
        material=moon_water,
        waves=(
            {"direction": (1.0, 0.25), "amplitude": 0.070, "wavelength": 2.60, "phase_radians": 0.35},
            {"direction": (-0.35, 1.0), "amplitude": 0.045, "wavelength": 1.60, "phase_radians": 1.75},
            {"direction": (0.70, 1.0), "amplitude": 0.025, "wavelength": 1.00, "phase_radians": 3.10},
            {"direction": (-1.0, 0.15), "amplitude": 0.012, "wavelength": 0.65, "phase_radians": 5.20},
        ),
    )
    renderer.object(
        name="stepwell_observer",
        type="mesh",
        mesh=mascot,
        translate=(0.0, 0.70, -1.0),
        rotate_degrees=(0.0, 28.0, 0.0),
        scale=(0.82, 0.82, 0.82),
        material=moon_ceramic,
    )
    moon_disk = disk(
        "moon_disk", (-2.8, 4.6, -5.1), (0.0, -0.3, 0.953939), 0.75, moon_emitter
    )

    if bind_lights:
        renderer.light(
            name="moon_key",
            type="disk",
            object=moon_disk,
            position=(-2.8, 4.6, -5.1),
            normal=(0.0, -0.3, 0.953939),
            radius=0.75,
            emission=(28.0, 34.0, 50.0),
        )
        renderer.light(
            name="left_warm_sconce",
            type="disk",
            object=left_sconce,
            position=(-6.35, 2.65, -1.55),
            normal=(1.0, 0.0, 0.0),
            radius=0.24,
            emission=(9.0, 2.8, 0.7),
        )
        renderer.light(
            name="right_warm_sconce",
            type="disk",
            object=right_sconce,
            position=(6.35, 2.65, -1.55),
            normal=(-1.0, 0.0, 0.0),
            radius=0.24,
            emission=(9.0, 2.8, 0.7),
        )
        renderer.light(
            name="underwater_cyan",
            type="sphere",
            object=submerged_marker,
            position=(0.35, -1.28, -2.95),
            radius=0.12,
            emission=(0.28, 1.05, 1.9),
        )
    return renderer


def read_pfm(path):
    with path.open("rb") as stream:
        if stream.readline() != b"PF\n":
            raise RuntimeError("linear reference is not a color PFM")
        width, height = map(int, stream.readline().split())
        if float(stream.readline()) >= 0.0:
            raise RuntimeError("linear PFM must use little-endian negative scale")
        payload = stream.read()
    expected = width * height * 3 * 4
    if len(payload) != expected:
        raise RuntimeError(
            f"linear PFM has {len(payload)} payload bytes, expected {expected}"
        )
    values = struct.unpack(f"<{width * height * 3}f", payload)
    rows = [values[y * width * 3:(y + 1) * width * 3] for y in range(height)]
    pixels = []
    for row in reversed(rows):
        pixels.extend(zip(row[0::3], row[1::3], row[2::3]))
    if any(not math.isfinite(v) for pixel in pixels for v in pixel):
        raise RuntimeError("linear PFM contains non-finite values")
    return width, height, tuple(pixels)


def render(renderer, directory, name, spp, seed):
    png = directory / f"{name}.png"
    pfm = directory / f"{name}.pfm"
    stats = renderer.render(
        output=png,
        stats_output=png.with_suffix(".stats.json"),
        linear_output=pfm,
        width=WIDTH,
        height=HEIGHT,
        spp=spp,
        depth=12,
        seed=seed,
        denoise=False,
    )
    render_ms = stats.get("timings_ms", {}).get("render")
    if not isinstance(render_ms, (int, float)) or not math.isfinite(render_ms):
        raise RuntimeError(f"{png.stem}: invalid render time")
    if render_ms <= 0.0:
        raise RuntimeError(f"{png.stem}: render time must be positive")
    width, height, pixels = read_pfm(pfm)
    if (width, height) != (WIDTH, HEIGHT):
        raise RuntimeError(f"unexpected PFM dimensions: {width}x{height}")
    return pixels, float(render_ms)


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
    if len(sys.argv) != 1:
        raise RuntimeError("check_water_time_to_error.py does not accept arguments")

    with tempfile.TemporaryDirectory(prefix="spectraldock-water-error-") as tmp:
        directory = Path(tmp)
        reference, _ = render(
            moonlit_renderer(True), directory, "rough-nee-reference", REFERENCE_SPP, 809
        )
        bsdf_only_candidates = []
        rough_nee_candidates = []
        for seed in CANDIDATE_SEEDS:
            bsdf_only_candidates.append(
                render(
                    moonlit_renderer(False),
                    directory,
                    f"rough-bsdf-only-{BSDF_ONLY_SPP}-seed-{seed}",
                    BSDF_ONLY_SPP,
                    seed,
                )
            )
            rough_nee_candidates.append(
                render(
                    moonlit_renderer(True),
                    directory,
                    f"rough-nee-{ROUGH_NEE_SPP}-seed-{seed}",
                    ROUGH_NEE_SPP,
                    seed,
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
            comparisons.append((name, rough_nee_error, bsdf_only_error))
            print(
                f"{name}: rough_nee_{ROUGH_NEE_SPP}={rough_nee_error:.6g} "
                f"rough_bsdf_only_{BSDF_ONLY_SPP}={bsdf_only_error:.6g}"
            )

        bsdf_only_ms = sum(candidate[1] for candidate in bsdf_only_candidates) / len(
            bsdf_only_candidates
        )
        rough_nee_ms = sum(candidate[1] for candidate in rough_nee_candidates) / len(
            rough_nee_candidates
        )
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
    except (OSError, RuntimeError, struct.error, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
