#!/usr/bin/env python3
"""Directional GPU checks for the procedural absorption/emission volume."""

import argparse
import math
import sys
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

from spectraldock import Renderer


WIDTH = 64
HEIGHT = 64
SPP = 128
SEED = 71
VOLUME_METRICS = (
    "volume_density_evaluations",
    "volume_real_collisions",
    "volume_light_samples",
    "volume_majorant_violations",
    "volume_tracking_overflows",
)


def positive_integer(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return result


def nonnegative_integer(value: str) -> int:
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return result


def create_flame_renderer(
    *, with_flame: bool, with_baffle: bool, device: int
) -> Renderer:
    renderer = Renderer(device=device, scene_name="flame-transport")
    renderer.integrator(
        direct_light_sampling="importance", clamp_direct=0.0, clamp_indirect=0.0
    )
    renderer.camera(
        look_from=(0.0, 1.35, 6.0),
        look_at=(0.0, 1.15, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=35.0,
        aperture=0.0,
        focus_distance=6.0,
    )
    renderer.background(type="constant", color=(0.0, 0.0, 0.0), exposure=0.0)

    receiver = renderer.material(
        name="receiver", type="lambertian", base_color=(0.72, 0.72, 0.72)
    )
    floor = renderer.material(
        name="floor", type="lambertian", base_color=(0.24, 0.25, 0.27)
    )
    occluder = renderer.material(
        name="occluder", type="lambertian", base_color=(0.015, 0.015, 0.018)
    )
    glass = renderer.material(
        name="glass", type="dielectric", base_color=(0.98, 0.99, 1.0), ior=1.5
    )
    renderer.material(
        name="area_emitter", type="emitter", emission=(24.0, 22.0, 18.0)
    )

    renderer.object(
        name="floor",
        type="rectangle",
        p1=(-3.2, 0.0, 2.0),
        p2=(-3.2, 0.0, -2.0),
        p3=(3.2, 0.0, -2.0),
        material=floor,
    )
    renderer.object(
        name="left_receiver",
        type="rectangle",
        p1=(-2.75, 0.0, 0.0),
        p2=(-2.75, 2.5, 0.0),
        p3=(-1.0, 2.5, 0.0),
        material=receiver,
    )
    renderer.object(
        name="glass_probe",
        type="sphere",
        center=(0.95, 1.25, 1.0),
        radius=0.48,
        material=glass,
    )
    if with_baffle:
        renderer.object(
            name="receiver_baffle",
            type="rectangle",
            p1=(-0.45, 0.0, -0.65),
            p2=(-0.45, 2.6, -0.65),
            p3=(-0.45, 2.6, 0.65),
            material=occluder,
        )
    if with_flame:
        renderer.light(
            name="fixture_flame",
            type="flame",
            position=(0.95, 0.5, 0.0),
            axis=(0.0, 1.0, 0.0),
            height=1.65,
            radius_start=0.26,
            radius_end=0.48,
            emission_start=(52.0, 67.0, 92.0),
            emission_end=(26.0, 5.0, 0.35),
            extinction=2.6,
            density_scale=1.0,
            turbulence=0.36,
            noise_scale=2.0,
            seed=SEED,
        )
    return renderer


def create_area_transmission_renderer(*, with_flame: bool, device: int) -> Renderer:
    renderer = Renderer(device=device, scene_name="flame-area-transmission")
    renderer.integrator(
        direct_light_sampling="importance", clamp_direct=0.0, clamp_indirect=0.0
    )
    renderer.camera(
        look_from=(0.0, 1.25, 5.0),
        look_at=(0.0, 1.25, -1.5),
        up=(0.0, 1.0, 0.0),
        vfov=30.0,
        aperture=0.0,
        focus_distance=6.5,
    )
    renderer.background(type="constant", color=(0.0, 0.0, 0.0), exposure=0.0)
    white = renderer.material(
        name="white", type="lambertian", base_color=(0.78, 0.78, 0.78)
    )
    renderer.object(
        name="receiver",
        type="rectangle",
        p1=(-2.0, 0.0, -1.5),
        p2=(-2.0, 2.5, -1.5),
        p3=(2.0, 2.5, -1.5),
        material=white,
    )
    renderer.light(
        name="area_key",
        type="disk",
        position=(0.0, 2.7, 1.0),
        normal=(0.0, 0.0, -1.0),
        radius=0.65,
        emission=(28.0, 28.0, 28.0),
    )
    if with_flame:
        renderer.light(
            name="absorbing_volume",
            type="flame",
            position=(0.0, 1.25, 0.65),
            axis=(0.0, 0.0, -1.0),
            height=1.65,
            radius_start=0.75,
            radius_end=0.75,
            emission_start=(0.000001, 0.000001, 0.000001),
            emission_end=(0.000001, 0.000001, 0.000001),
            extinction=3.2,
            density_scale=1.0,
            turbulence=0.0,
            noise_scale=2.0,
            seed=SEED,
        )
    return renderer


def render_variant(
    renderer: Renderer,
    directory: Path,
    name: str,
    *,
    spp: int,
    depth: int,
) -> tuple[Image.Image, dict[str, Any]]:
    output = directory / f"{name}.png"
    stats = renderer.render(
        output=output,
        width=WIDTH,
        height=HEIGHT,
        spp=spp,
        max_depth=depth,
        seed=SEED,
        denoise=False,
    )
    with Image.open(output) as decoded:
        decoded.load()
        if decoded.size != (WIDTH, HEIGHT) or decoded.mode != "RGBA":
            raise RuntimeError(
                f"unexpected flame output: {decoded.size} {decoded.mode}"
            )
        pixels = decoded.copy()
    assert_finite(stats)
    return pixels, stats


def assert_finite(value: Any) -> None:
    if isinstance(value, dict):
        for child in value.values():
            assert_finite(child)
    elif isinstance(value, list):
        for child in value:
            assert_finite(child)
    elif isinstance(value, float) and not math.isfinite(value):
        raise RuntimeError("stats contain NaN or infinity")


def metric(tree: Any, name: str) -> Any:
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


def mean_luminance(image: Image.Image, box: tuple[int, int, int, int]) -> float:
    values = []
    for red, green, blue, _ in image.crop(box).getdata():
        values.append(0.2126 * red + 0.7152 * green + 0.0722 * blue)
    return sum(values) / len(values)


def run_checks(directory: Path, args: argparse.Namespace) -> None:
    first, first_stats = render_variant(
        create_flame_renderer(
            with_flame=True, with_baffle=False, device=args.device
        ),
        directory,
        "flame-a",
        spp=args.spp,
        depth=3,
    )
    second, _ = render_variant(
        create_flame_renderer(
            with_flame=True, with_baffle=False, device=args.device
        ),
        directory,
        "flame-b",
        spp=args.spp,
        depth=3,
    )
    if first.tobytes() != second.tobytes():
        raise RuntimeError("fixed-seed flame renders are not byte-identical")

    for name in VOLUME_METRICS[:3]:
        value = metric(first_stats, name)
        if value is None or value <= 0:
            raise RuntimeError(f"{name} must be positive for the flame fixture")
    for name in VOLUME_METRICS[3:]:
        if metric(first_stats, name) != 0:
            raise RuntimeError(f"{name} must remain zero")

    off_image, off_stats = render_variant(
        create_flame_renderer(
            with_flame=False, with_baffle=False, device=args.device
        ),
        directory,
        "flame-off",
        spp=args.spp,
        depth=3,
    )
    for name in VOLUME_METRICS:
        if metric(off_stats, name) != 0:
            raise RuntimeError(f"{name} must be zero without a flame")
    receiver_box = (2, 10, 25, 55)
    if mean_luminance(first, receiver_box) <= mean_luminance(
        off_image, receiver_box
    ) + 1.0:
        raise RuntimeError("flame NEE did not illuminate the external receiver")

    blocked_image, _ = render_variant(
        create_flame_renderer(
            with_flame=True, with_baffle=True, device=args.device
        ),
        directory,
        "flame-blocked",
        spp=args.spp,
        depth=3,
    )
    if mean_luminance(blocked_image, receiver_box) >= mean_luminance(
        first, receiver_box
    ):
        raise RuntimeError("surface occluder did not reduce flame illumination")

    clear_image, _ = render_variant(
        create_area_transmission_renderer(with_flame=False, device=args.device),
        directory,
        "area-clear",
        spp=args.spp,
        depth=1,
    )
    absorbed_image, _ = render_variant(
        create_area_transmission_renderer(with_flame=True, device=args.device),
        directory,
        "area-absorbed",
        spp=args.spp,
        depth=1,
    )
    wall_box = (12, 10, 52, 54)
    if mean_luminance(absorbed_image, wall_box) >= mean_luminance(
        clear_image, wall_box
    ):
        raise RuntimeError("flame absorption did not attenuate an area light")

    center_glass = (36, 19, 52, 43)
    if mean_luminance(first, center_glass) <= 0.0:
        raise RuntimeError("delta dielectric path did not see the flame")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="preserve rendered checks in this directory instead of a temporary one",
    )
    parser.add_argument("--device", type=nonnegative_integer, default=0)
    parser.add_argument("--spp", type=positive_integer, default=SPP)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output_dir is not None:
        directory = args.output_dir.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        run_checks(directory, args)
    else:
        with tempfile.TemporaryDirectory(prefix="spectraldock-flame-") as temporary:
            run_checks(Path(temporary), args)

    print("procedural flame transport checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
