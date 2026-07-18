#!/usr/bin/env python3
"""GPU contracts for scale-aware secondary and shadow-ray spawning."""

import argparse
import math
import sys
import tempfile
from pathlib import Path

from spectraldock import Renderer

from avif_test_utils import assert_avif_dimensions, captured_linear_rgb


ROOT = Path(__file__).resolve().parents[1]
QUAD = ROOT / "tests/assets/pbr-quad.obj"
SEED = 4243

# The fourth case deliberately translates geometry along its normal. At this
# magnitude a binary32 ulp is much larger than the historical fixed epsilon.
CASES = (
    ("unit", 1.0, (0.0, 0.0, 0.0)),
    ("millimetre", 1.0e-3, (0.0, 0.0, 0.0)),
    ("large", 1.0e4, (0.0, 0.0, 0.0)),
    ("translated", 1.0, (0.0, 0.0, 1.0e6)),
)


def nonnegative_integer(value: str) -> int:
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return result


def add(a, b):
    return tuple(left + right for left, right in zip(a, b))


def mul(value, scale):
    return tuple(component * scale for component in value)


def render_probe(
    renderer: Renderer,
    directory: Path,
    name: str,
    *,
    spp: int,
    depth: int,
) -> tuple[tuple[float, float, float], bytes, dict]:
    avif = directory / f"{name}.avif"
    stats = renderer.render(
        output=avif,
        stats_output=avif.with_suffix(".stats.json"),
        width=1,
        height=1,
        spp=spp,
        depth=depth,
        seed=SEED,
        denoise=False,
        clamp_direct=0.0,
        clamp_indirect=0.0,
        _test_capture_linear=True,
    )
    assert_avif_dimensions(avif, 1, 1)
    pixels, linear_values = captured_linear_rgb(stats, 1, 1)
    render = stats.get("render", {})
    if (
        render.get("denoised") is not False
        or render.get("clamp_direct") != 0.0
        or render.get("clamp_indirect") != 0.0
    ):
        raise RuntimeError(f"{name}: ray-spawning contract used biased output")
    return pixels[0], linear_values, stats


def common_renderer(
    *, device: int, scale: float, offset, target_offset=(0.0, 0.0, 0.0)
) -> Renderer:
    renderer = Renderer(device=device)
    renderer.integrator(
        direct_light_sampling="importance", clamp_direct=0.0, clamp_indirect=0.0
    )
    renderer.camera(
        look_from=add(offset, (0.0, 0.0, 4.0 * scale)),
        look_at=add(offset, target_offset),
        up=(0.0, 1.0, 0.0),
        vfov=2.0,
        aperture=0.0,
        focus_distance=4.0 * scale,
    )
    return renderer


def shadow_renderer(
    *,
    device: int,
    scale: float,
    offset,
    receiver_kind: str,
    blocked: bool,
    light_kind: str = "directional",
) -> Renderer:
    renderer = common_renderer(device=device, scale=scale, offset=offset)
    renderer.background(type="constant", color=(0.0, 0.0, 0.0), exposure=0.0)
    receiver = renderer.material(
        name="receiver", type="lambertian", base_color=(0.8, 0.7, 0.6)
    )
    occluder = renderer.material(
        name="occluder", type="lambertian", base_color=(0.0, 0.0, 0.0)
    )
    if receiver_kind == "mesh":
        mesh = renderer.mesh(name="receiver-quad", path=QUAD)
        renderer.object(
            name="receiver",
            type="mesh",
            mesh=mesh,
            translate=offset,
            scale=(scale, scale, scale),
            material=receiver,
        )
    elif receiver_kind == "rectangle":
        renderer.object(
            name="receiver",
            type="rectangle",
            p1=add(offset, (-2.0 * scale, -2.0 * scale, 0.0)),
            p2=add(offset, (2.0 * scale, -2.0 * scale, 0.0)),
            p3=add(offset, (2.0 * scale, 2.0 * scale, 0.0)),
            material=receiver,
        )
    else:
        raise RuntimeError(f"unsupported receiver kind: {receiver_kind}")

    # The shadow ray passes through the centre of a very thin disk only 3% of
    # one scene unit from the receiver. The camera ray does not intersect it.
    # At scale 1e-3, a fixed 2e-4 normal offset starts beyond this blocker.
    # z=1e6 has a binary32 ulp of 0.0625, so its fixture instead uses a clearly
    # representable separation and a radius between the corrected mesh bound's
    # ~0.43 lateral shift and the historical formula's ~0.49 shift. It still
    # catches an over-large offset without demanding sub-ulp geometry.
    wi = (0.979795897, 0.0, 0.2)
    if blocked:
        translated = abs(offset[2]) >= 1.0e6
        blocker_distance = (2.0 if translated else 0.03) * scale
        blocker_radius = (0.46 if translated else 0.015) * scale
        renderer.object(
            name="thin-occluder",
            type="disk",
            center=add(offset, mul(wi, blocker_distance)),
            normal=mul(wi, -1.0),
            radius=blocker_radius,
            material=occluder,
        )
    if light_kind == "directional":
        renderer.light(
            name="grazing-key",
            type="directional",
            direction=wi,
            irradiance=tuple(8.0 * math.pi for _ in range(3)),
        )
    elif light_kind == "point":
        translated = abs(offset[2]) >= 1.0e6
        light_distance = (6.0 if translated else 0.5) * scale
        renderer.light(
            name="grazing-key",
            type="point",
            position=add(offset, mul(wi, light_distance)),
            intensity=tuple(
                8.0 * math.pi * light_distance * light_distance
                for _ in range(3)
            ),
        )
    else:
        raise RuntimeError(f"unsupported shadow light kind: {light_kind}")
    return renderer


def secondary_renderer(
    *, device: int, scale: float, offset, material_type: str
) -> Renderer:
    renderer = common_renderer(
        device=device,
        scale=scale,
        offset=offset,
        target_offset=(0.55 * scale, 0.0, 0.0),
    )
    # An off-axis primary hit makes the spawned direction non-trivial while a
    # constant environment keeps this a transport invariant, not a pixel gold.
    renderer.background(type="constant", color=(0.7, 0.5, 0.3), exposure=0.0)
    if material_type == "metal":
        material = renderer.material(
            name="reflector",
            type="metal",
            base_color=(0.85, 0.62, 0.35),
            roughness=0.18,
        )
    elif material_type == "dielectric":
        material = renderer.material(
            name="glass",
            type="dielectric",
            base_color=(0.98, 0.99, 1.0),
            roughness=0.0,
            ior=1.5,
        )
    else:
        raise RuntimeError(f"unsupported secondary material: {material_type}")
    renderer.object(
        name="probe",
        type="sphere",
        center=offset,
        radius=scale,
        material=material,
    )
    return renderer


def luminance(pixel) -> float:
    return 0.2126 * pixel[0] + 0.7152 * pixel[1] + 0.0722 * pixel[2]


def assert_close(actual, expected, label: str, *, relative: float) -> None:
    for channel, (left, right) in enumerate(zip(actual, expected)):
        tolerance = max(2.0e-5, relative * max(abs(left), abs(right)))
        if abs(left - right) > tolerance:
            raise RuntimeError(
                f"{label}: channel {channel} differs: {left:.8g} vs "
                f"{right:.8g} (tolerance {tolerance:.3g})"
            )


def check_thin_visibility(directory: Path, *, device: int) -> None:
    for receiver_kind in ("mesh", "rectangle"):
        reference = None
        deterministic = None
        for case_name, scale, offset in CASES:
            lit, lit_bytes, _ = render_probe(
                shadow_renderer(
                    device=device,
                    scale=scale,
                    offset=offset,
                    receiver_kind=receiver_kind,
                    blocked=False,
                ),
                directory,
                f"{receiver_kind}-{case_name}-lit",
                spp=1,
                depth=1,
            )
            shadowed, shadow_bytes, _ = render_probe(
                shadow_renderer(
                    device=device,
                    scale=scale,
                    offset=offset,
                    receiver_kind=receiver_kind,
                    blocked=True,
                ),
                directory,
                f"{receiver_kind}-{case_name}-shadowed",
                spp=1,
                depth=1,
            )
            if luminance(lit) <= 0.1:
                raise RuntimeError(
                    f"{receiver_kind}/{case_name}: control receiver was not lit: {lit!r}"
                )
            if luminance(shadowed) > max(1.0e-6, luminance(lit) * 1.0e-4):
                raise RuntimeError(
                    f"{receiver_kind}/{case_name}: thin blocker leaked light: "
                    f"lit={lit!r}, shadowed={shadowed!r}"
                )
            if case_name == "unit":
                reference = lit
                deterministic = (shadowed, shadow_bytes)
            else:
                if reference is not None:
                    assert_close(
                        lit,
                        reference,
                        f"{receiver_kind}/{case_name} direct scale invariant",
                        relative=0.03,
                    )

        # Rebuilding the same scene catches uninitialized launch-state and
        # keeps determinism independent of renderer object reuse.
        repeated, repeated_bytes, _ = render_probe(
            shadow_renderer(
                device=device,
                scale=1.0,
                offset=(0.0, 0.0, 0.0),
                receiver_kind=receiver_kind,
                blocked=True,
            ),
            directory,
            f"{receiver_kind}-unit-shadowed-repeat",
            spp=1,
            depth=1,
        )
        if deterministic is None or (repeated, repeated_bytes) != deterministic:
            raise RuntimeError(
                f"{receiver_kind}: fixed-seed shadow-ray output is not deterministic"
            )


def check_secondary_transport(directory: Path, *, device: int) -> None:
    for material_type, spp, depth in (
        ("metal", 16, 2),
        ("dielectric", 64, 4),
    ):
        reference = None
        deterministic = None
        for case_name, scale, offset in CASES:
            pixel, payload, stats = render_probe(
                secondary_renderer(
                    device=device,
                    scale=scale,
                    offset=offset,
                    material_type=material_type,
                ),
                directory,
                f"{material_type}-{case_name}",
                spp=spp,
                depth=depth,
            )
            if luminance(pixel) <= 1.0e-4:
                raise RuntimeError(
                    f"{material_type}/{case_name}: secondary transport was black"
                )
            traced_rays = stats.get("performance", {}).get("traced_rays", 0)
            if traced_rays <= spp:
                raise RuntimeError(
                    f"{material_type}/{case_name}: no secondary rays were traced"
                )
            if case_name == "unit":
                reference = pixel
                deterministic = (pixel, payload)
            elif reference is not None:
                assert_close(
                    pixel,
                    reference,
                    f"{material_type}/{case_name} secondary scale invariant",
                    relative=0.18,
                )

        repeated, repeated_bytes, _ = render_probe(
            secondary_renderer(
                device=device,
                scale=1.0,
                offset=(0.0, 0.0, 0.0),
                material_type=material_type,
            ),
            directory,
            f"{material_type}-unit-repeat",
            spp=spp,
            depth=depth,
        )
        if deterministic is None or (repeated, repeated_bytes) != deterministic:
            raise RuntimeError(
                f"{material_type}: fixed-seed secondary output is not deterministic"
            )


def check_point_visibility(directory: Path, *, device: int) -> None:
    """Exercise the finite point segment at every scale and translation."""
    for case_name, scale, offset in CASES:
        lit, _, _ = render_probe(
            shadow_renderer(
                device=device,
                scale=scale,
                offset=offset,
                receiver_kind="mesh",
                blocked=False,
                light_kind="point",
            ),
            directory,
            f"point-{case_name}-lit",
            spp=1,
            depth=1,
        )
        shadowed, _, _ = render_probe(
            shadow_renderer(
                device=device,
                scale=scale,
                offset=offset,
                receiver_kind="mesh",
                blocked=True,
                light_kind="point",
            ),
            directory,
            f"point-{case_name}-shadowed",
            spp=1,
            depth=1,
        )
        if luminance(lit) <= 0.1:
            raise RuntimeError(
                f"point/{case_name}: control receiver was not lit: {lit!r}"
            )
        if luminance(shadowed) > max(1.0e-6, luminance(lit) * 1.0e-4):
            raise RuntimeError(
                f"point/{case_name}: thin blocker leaked light: "
                f"lit={lit!r}, shadowed={shadowed!r}"
            )


def run_check(directory: Path, *, device: int) -> None:
    check_thin_visibility(directory, device=device)
    check_point_visibility(directory, device=device)
    check_secondary_transport(directory, device=device)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="preserve rendered probes in this directory instead of a temporary one",
    )
    parser.add_argument("--device", type=nonnegative_integer, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output_dir is not None:
        directory = args.output_dir.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        run_check(directory, device=args.device)
    else:
        with tempfile.TemporaryDirectory(
            prefix="spectraldock-ray-spawning-"
        ) as temporary:
            run_check(Path(temporary), device=args.device)
    print("scale-aware ray-spawning GPU checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
