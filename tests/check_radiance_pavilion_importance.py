#!/usr/bin/env python3
"""GPU A/B check for the production Radiance Pavilion environment."""

import argparse
import importlib.util
import sys
import tempfile
from pathlib import Path
from typing import Callable

from PIL import Image

from spectraldock import Renderer


ROOT = Path(__file__).resolve().parents[1]
PAVILION_SCENE = ROOT / "scenes/radiance-pavilion.py"
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


def load_renderer_factory() -> Callable[[], Renderer]:
    if not PAVILION_SCENE.is_file():
        raise RuntimeError(f"Pavilion Python scene not found: {PAVILION_SCENE}")
    spec = importlib.util.spec_from_file_location(
        "spectraldock_radiance_pavilion_scene", PAVILION_SCENE
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Pavilion Python scene: {PAVILION_SCENE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    factory = getattr(module, "create_renderer", None)
    if not callable(factory):
        raise RuntimeError("Radiance Pavilion must define create_renderer()")
    return factory


def create_variant(
    factory: Callable[[], Renderer], *, mode: str, device: int
) -> Renderer:
    renderer = factory()
    if not isinstance(renderer, Renderer):
        raise RuntimeError("Radiance Pavilion create_renderer() returned the wrong type")
    renderer.device = device
    renderer.integrator(
        direct_light_sampling=mode, clamp_direct=0.0, clamp_indirect=0.0
    )
    return renderer


def render_variant(
    factory: Callable[[], Renderer],
    directory: Path,
    name: str,
    mode: str,
    spp: int,
    seed: int,
    *,
    device: int,
) -> Image.Image:
    output = directory / f"{name}.png"
    stats = create_variant(factory, mode=mode, device=device).render(
        output=output,
        width=WIDTH,
        height=HEIGHT,
        spp=spp,
        max_depth=MAX_DEPTH,
        seed=seed,
        denoise=False,
    )

    with Image.open(output) as decoded:
        decoded.load()
        if decoded.size != (WIDTH, HEIGHT) or decoded.mode != "RGBA":
            raise RuntimeError(
                f"unexpected Pavilion output: {decoded.size} {decoded.mode}"
            )
        image = decoded.copy()

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
                f"stats render.{key}={actual.get(key)!r}, expected {value!r}"
            )
    return image


def roi_rgb(image: Image.Image) -> list[tuple[int, int, int]]:
    return [pixel[:3] for pixel in image.crop(ROI).getdata()]


def mse(image: Image.Image, reference: Image.Image) -> float:
    actual = roi_rgb(image)
    expected = roi_rgb(reference)
    return sum(
        (left - right) * (left - right)
        for actual_pixel, expected_pixel in zip(actual, expected)
        for left, right in zip(actual_pixel, expected_pixel)
    ) / (3.0 * len(actual))


def mean_luminance(image: Image.Image) -> float:
    pixels = roi_rgb(image)
    return sum(
        0.2126 * red + 0.7152 * green + 0.0722 * blue
        for red, green, blue in pixels
    ) / len(pixels)


def run_checks(directory: Path, args: argparse.Namespace) -> tuple[float, float]:
    factory = load_renderer_factory()
    reference = render_variant(
        factory,
        directory,
        "importance-reference",
        "importance",
        args.reference_spp,
        REFERENCE_SEED,
        device=args.device,
    )
    reference_mean = mean_luminance(reference)
    if reference_mean <= 1.0:
        raise RuntimeError(
            "Pavilion reference ROI is blank or unexpectedly dark: "
            f"{reference_mean:.3f}"
        )

    uniform_error = 0.0
    importance_error = 0.0
    for index, seed in enumerate(LOW_SEEDS):
        uniform = render_variant(
            factory,
            directory,
            f"uniform-low-{index}",
            "uniform",
            args.low_spp,
            seed,
            device=args.device,
        )
        importance = render_variant(
            factory,
            directory,
            f"importance-low-{index}",
            "importance",
            args.low_spp,
            seed,
            device=args.device,
        )
        uniform_error += mse(uniform, reference)
        importance_error += mse(importance, reference)

    if uniform_error <= 1.0e-12:
        raise RuntimeError("Pavilion uniform low-spp reference error is zero")
    mse_ratio = importance_error / uniform_error
    if mse_ratio > MAX_MSE_RATIO:
        raise RuntimeError(
            "Pavilion importance sampling did not reduce cumulative low-spp "
            "RGB MSE by 15%: importance={:.3f}, uniform={:.3f}, "
            "ratio={:.3f}".format(
                importance_error, uniform_error, mse_ratio
            )
        )

    uniform_high = render_variant(
        factory,
        directory,
        "uniform-high",
        "uniform",
        args.high_spp,
        HIGH_UNIFORM_SEED,
        device=args.device,
    )
    importance_high = render_variant(
        factory,
        directory,
        "importance-high",
        "importance",
        args.high_spp,
        HIGH_IMPORTANCE_SEED,
        device=args.device,
    )
    uniform_mean = mean_luminance(uniform_high)
    importance_mean = mean_luminance(importance_high)
    relative_mean_error = abs(uniform_mean - importance_mean) / max(
        importance_mean, 1.0
    )
    if relative_mean_error > MAX_HIGH_SPP_MEAN_ERROR:
        raise RuntimeError(
            "Pavilion uniform/importance high-spp ROI means did not converge: "
            "uniform={:.3f}, importance={:.3f}, relative_error={:.3f}".format(
                uniform_mean, importance_mean, relative_mean_error
            )
        )
    return mse_ratio, relative_mean_error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="preserve rendered checks in this directory instead of a temporary one",
    )
    parser.add_argument("--device", type=nonnegative_integer, default=0)
    parser.add_argument("--low-spp", type=positive_integer, default=LOW_SPP)
    parser.add_argument("--high-spp", type=positive_integer, default=HIGH_SPP)
    parser.add_argument(
        "--reference-spp", type=positive_integer, default=REFERENCE_SPP
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output_dir is not None:
        directory = args.output_dir.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        mse_ratio, relative_mean_error = run_checks(directory, args)
    else:
        with tempfile.TemporaryDirectory(
            prefix="spectraldock-radiance-pavilion-"
        ) as temporary:
            mse_ratio, relative_mean_error = run_checks(Path(temporary), args)

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
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
