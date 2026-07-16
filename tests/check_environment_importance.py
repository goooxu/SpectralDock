#!/usr/bin/env python3
"""Directional GPU checks for HDR environment lookup, NEE, and sampling."""

import argparse
import math
import sys
import tempfile
from pathlib import Path

from PIL import Image

from spectraldock import Renderer


WIDTH = 64
HEIGHT = 64
ROI = (8, 8, 56, 56)
DETERMINISTIC_SPP = 8
ROTATION_SPP = 64
REFERENCE_SPP = 1024
HIGH_SPP = 1024
LOW_SPP = 8
LOW_SEEDS = (521, 631, 743)


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


def rgbe(red: float, green: float, blue: float) -> bytes:
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


def encode_channel(values: list[int]) -> bytearray:
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
            literal.extend(values[index : index + take])
            index += take
        encoded.append(len(literal))
        encoded.extend(literal)
    return encoded


def write_asymmetric_hdr(path: Path) -> None:
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


def create_renderer(
    hdr: Path,
    *,
    mode: str,
    intensity: float,
    rotation: float,
    device: int,
) -> Renderer:
    renderer = Renderer(device=device, scene_name=f"environment-{mode}")
    renderer.integrator(
        direct_light_sampling=mode, clamp_direct=0.0, clamp_indirect=0.0
    )
    renderer.camera(
        look_from=(0.0, 0.0, 3.0),
        look_at=(0.0, 0.0, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=42.0,
        aperture=0.0,
        focus_distance=3.0,
    )
    renderer.background(
        type="environment",
        path=hdr,
        intensity=intensity,
        rotation_degrees=rotation,
        exposure=-2.0,
    )
    receiver = renderer.material(
        name="receiver", type="lambertian", base_color=(0.72, 0.72, 0.72)
    )
    renderer.object(
        name="receiver",
        type="rectangle",
        p1=(-2.0, -2.0, 0.0),
        p2=(-2.0, 2.0, 0.0),
        p3=(2.0, 2.0, 0.0),
        material=receiver,
    )
    return renderer


def render_variant(
    hdr: Path,
    directory: Path,
    name: str,
    mode: str,
    spp: int,
    seed: int,
    *,
    device: int,
    intensity: float = 1.0,
    rotation: float = 0.0,
) -> Image.Image:
    output = directory / f"{name}.png"
    stats = create_renderer(
        hdr,
        mode=mode,
        intensity=intensity,
        rotation=rotation,
        device=device,
    ).render(
        output=output,
        width=WIDTH,
        height=HEIGHT,
        spp=spp,
        max_depth=1,
        seed=seed,
        denoise=False,
    )
    with Image.open(output) as decoded:
        decoded.load()
        if decoded.size != (WIDTH, HEIGHT) or decoded.mode != "RGBA":
            raise RuntimeError(
                f"unexpected environment output: {decoded.size} {decoded.mode}"
            )
        image = decoded.copy()

    actual_mode = stats.get("render", {}).get("direct_light_sampling")
    if actual_mode != mode:
        raise RuntimeError(
            "stats report direct_light_sampling={!r}, expected {!r}".format(
                actual_mode, mode
            )
        )
    return image


def rgb_values(image: Image.Image) -> list[tuple[int, int, int]]:
    return [pixel[:3] for pixel in image.crop(ROI).getdata()]


def mean_luminance(image: Image.Image) -> float:
    values = rgb_values(image)
    return sum(
        0.2126 * red + 0.7152 * green + 0.0722 * blue
        for red, green, blue in values
    ) / len(values)


def mse(image: Image.Image, reference: Image.Image) -> float:
    left = rgb_values(image)
    right = rgb_values(reference)
    return sum(
        (a - b) * (a - b)
        for left_pixel, right_pixel in zip(left, right)
        for a, b in zip(left_pixel, right_pixel)
    ) / (3.0 * len(left))


def rgb_is_black(image: Image.Image) -> bool:
    return all(
        red == 0 and green == 0 and blue == 0
        for red, green, blue, _ in image.getdata()
    )


def run_checks(directory: Path, args: argparse.Namespace) -> None:
    hdr = directory / "asymmetric-studio.hdr"
    write_asymmetric_hdr(hdr)

    first = render_variant(
        hdr,
        directory,
        "deterministic-a",
        "importance",
        args.deterministic_spp,
        109,
        device=args.device,
    )
    second = render_variant(
        hdr,
        directory,
        "deterministic-b",
        "importance",
        args.deterministic_spp,
        109,
        device=args.device,
    )
    if first.tobytes() != second.tobytes():
        raise RuntimeError("fixed-seed environment renders are not identical")
    if mean_luminance(first) <= 0.5:
        raise RuntimeError("depth-1 environment NEE produced a blank receiver")

    dark = render_variant(
        hdr,
        directory,
        "zero-intensity",
        "importance",
        args.deterministic_spp,
        109,
        device=args.device,
        intensity=0.0,
    )
    if not rgb_is_black(dark):
        raise RuntimeError("zero-intensity environment must be exactly black")

    unrotated = render_variant(
        hdr,
        directory,
        "rotation-0",
        "importance",
        args.rotation_spp,
        211,
        device=args.device,
        rotation=0.0,
    )
    rotated = render_variant(
        hdr,
        directory,
        "rotation-180",
        "importance",
        args.rotation_spp,
        211,
        device=args.device,
        rotation=180.0,
    )
    if abs(mean_luminance(unrotated) - mean_luminance(rotated)) < 1.0:
        raise RuntimeError("180-degree environment rotation had no visible response")

    reference = render_variant(
        hdr,
        directory,
        "reference",
        "importance",
        args.reference_spp,
        313,
        device=args.device,
    )
    uniform_high = render_variant(
        hdr,
        directory,
        "uniform-high",
        "uniform",
        args.high_spp,
        419,
        device=args.device,
    )
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
    for index, seed in enumerate(LOW_SEEDS):
        uniform = render_variant(
            hdr,
            directory,
            f"uniform-low-{index}",
            "uniform",
            args.low_spp,
            seed,
            device=args.device,
        )
        importance = render_variant(
            hdr,
            directory,
            f"importance-low-{index}",
            "importance",
            args.low_spp,
            seed,
            device=args.device,
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="preserve rendered checks in this directory instead of a temporary one",
    )
    parser.add_argument("--device", type=nonnegative_integer, default=0)
    parser.add_argument(
        "--deterministic-spp", type=positive_integer, default=DETERMINISTIC_SPP
    )
    parser.add_argument("--rotation-spp", type=positive_integer, default=ROTATION_SPP)
    parser.add_argument(
        "--reference-spp", type=positive_integer, default=REFERENCE_SPP
    )
    parser.add_argument("--high-spp", type=positive_integer, default=HIGH_SPP)
    parser.add_argument("--low-spp", type=positive_integer, default=LOW_SPP)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output_dir is not None:
        directory = args.output_dir.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        run_checks(directory, args)
    else:
        with tempfile.TemporaryDirectory(
            prefix="spectraldock-environment-"
        ) as temporary:
            run_checks(Path(temporary), args)

    print("HDR environment lookup and importance sampling checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
