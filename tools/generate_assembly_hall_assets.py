#!/usr/bin/env python3
"""Generate Assembly Hall's deterministic noon HDR and gear alpha mask."""

from __future__ import annotations

import argparse
import hashlib
import math
import os
from pathlib import Path
import sys
import tempfile

from spectraldock import _native


VERSION = "spectraldock-assembly-hall-assets/1.0"
HDR_WIDTH = 2048
HDR_HEIGHT = 1024
ALPHA_SIZE = 1024

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HDR_OUTPUT = (
    ROOT / "assets/examples/environments/assembly-hall-noon.hdr"
)
DEFAULT_ALPHA_OUTPUT = (
    ROOT / "assets/examples/textures/assembly-hall-gear-alpha.avif"
)

SUN_AZIMUTH_DEGREES = 45.0
SUN_ELEVATION_DEGREES = 76.0


def clamp(value, lower=0.0, upper=1.0):
    return max(lower, min(upper, value))


def dot(first, second):
    return sum(a * b for a, b in zip(first, second))


def add(first, second):
    return tuple(a + b for a, b in zip(first, second))


def scale(color, amount):
    return tuple(component * amount for component in color)


def mix(first, second, amount):
    return tuple(
        first_component
        + (second_component - first_component) * amount
        for first_component, second_component in zip(first, second)
    )


def smoothstep(lower, upper, value):
    amount = clamp((value - lower) / (upper - lower))
    return amount * amount * (3.0 - 2.0 * amount)


def spherical_direction(azimuth_degrees, elevation_degrees):
    azimuth = math.radians(azimuth_degrees)
    elevation = math.radians(elevation_degrees)
    horizontal = math.cos(elevation)
    return (
        horizontal * math.cos(azimuth),
        math.sin(elevation),
        horizontal * math.sin(azimuth),
    )


SUN_DIRECTION = spherical_direction(
    SUN_AZIMUTH_DEGREES, SUN_ELEVATION_DEGREES
)


def environment_radiance(direction):
    """Return a seamless high-noon sky with one compact HDR solar lobe."""
    _, y, _ = direction
    if y >= 0.0:
        height = clamp(y) ** 0.42
        sky = mix((0.66, 0.84, 1.12), (0.10, 0.30, 0.78), height)
        horizon_haze = math.exp(-((max(0.0, y) / 0.19) ** 2))
        sky = add(sky, scale((0.38, 0.33, 0.25), horizon_haze))

        # A broad, extremely restrained aureole gives the solar disk a
        # plausible shoulder without diluting the importance-sampling peak.
        alignment = clamp(dot(direction, SUN_DIRECTION), -1.0, 1.0)
        angle = math.acos(alignment)
        aureole = math.exp(-((angle / math.radians(4.8)) ** 2))
        disk = smoothstep(
            math.cos(math.radians(0.82)),
            math.cos(math.radians(0.42)),
            alignment,
        )
        color = add(sky, scale((2.2, 1.85, 1.18), aureole))
        color = add(color, scale((520.0, 445.0, 285.0), disk))
    else:
        # The lower hemisphere is a neutral exterior yard.  It is deliberately
        # broad and nonzero so glossy objects never reflect an artificial void.
        depth = clamp(-y) ** 0.55
        color = mix((0.34, 0.36, 0.35), (0.055, 0.065, 0.070), depth)
    return tuple(max(0.0, component) for component in color)


def float_to_rgbe(red, green, blue):
    maximum = max(red, green, blue)
    if maximum < 1.0e-32:
        return 0, 0, 0, 0
    mantissa, exponent = math.frexp(maximum)
    multiplier = mantissa * 256.0 / maximum
    return (
        min(255, int(red * multiplier)),
        min(255, int(green * multiplier)),
        min(255, int(blue * multiplier)),
        exponent + 128,
    )


def encode_component(values):
    """Encode one RGBE component using modern Radiance scanline RLE."""
    encoded = bytearray()
    index = 0
    length = len(values)
    while index < length:
        run = 1
        while (
            index + run < length
            and run < 127
            and values[index + run] == values[index]
        ):
            run += 1
        if run >= 4:
            encoded.extend((128 + run, values[index]))
            index += run
            continue

        literal = bytearray()
        while index < length and len(literal) < 128:
            next_run = 1
            while (
                index + next_run < length
                and next_run < 127
                and values[index + next_run] == values[index]
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


COLUMN_AZIMUTHS = tuple(
    2.0 * math.pi * ((column + 0.5) / HDR_WIDTH - 0.5)
    for column in range(HDR_WIDTH)
)


def hdr_scanline(row):
    theta = math.pi * (row + 0.5) / HDR_HEIGHT
    horizontal = math.sin(theta)
    y = math.cos(theta)
    components = [bytearray() for _ in range(4)]
    for azimuth in COLUMN_AZIMUTHS:
        direction = (
            horizontal * math.cos(azimuth),
            y,
            horizontal * math.sin(azimuth),
        )
        for component, value in zip(
            components, float_to_rgbe(*environment_radiance(direction))
        ):
            component.append(value)

    encoded = bytearray((2, 2, HDR_WIDTH >> 8, HDR_WIDTH & 0xFF))
    for component in components:
        encoded.extend(encode_component(component))
    return encoded


def hdr_header():
    return (
        "#?RADIANCE\n"
        "# Generated deterministically by {}\n"
        "FORMAT=32-bit_rle_rgbe\n"
        "\n"
        "-Y {} +X {}\n".format(VERSION, HDR_HEIGHT, HDR_WIDTH)
    ).encode("ascii")


def _atomic_stream(destination, writer):
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=destination.name + ".",
            delete=False,
        ) as stream:
            temporary_name = stream.name
            result = writer(stream)
        os.replace(temporary_name, destination)
        temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
    return result


def generate_hdr(output):
    digest = hashlib.sha256()
    byte_count = 0

    def write(stream):
        nonlocal byte_count
        header = hdr_header()
        stream.write(header)
        digest.update(header)
        byte_count += len(header)
        for row in range(HDR_HEIGHT):
            scanline = hdr_scanline(row)
            stream.write(scanline)
            digest.update(scanline)
            byte_count += len(scanline)

    _atomic_stream(Path(output), write)
    return byte_count, digest.hexdigest()


def gear_alpha_at(x, y):
    """Return the binary alpha of a toothed ring, hub, and eight spokes."""
    dx = x - ALPHA_SIZE // 2
    dy = y - ALPHA_SIZE // 2
    radius = math.hypot(dx, dy)
    if radius < 58.0 or radius > 340.0:
        return 0
    angle = math.atan2(dy, dx)
    tooth_phase = (angle * 16.0 / (2.0 * math.pi)) % 1.0
    outer_radius = 340.0 if 0.18 <= tooth_phase <= 0.82 else 296.0
    ring = 184.0 <= radius <= outer_radius
    spoke = 102.0 <= radius <= 214.0 and abs(
        math.sin(4.0 * angle)
    ) * radius <= 27.0
    hub = radius <= 126.0
    return 255 if ring or spoke or hub else 0


def build_gear_rgba():
    pixels = bytearray(ALPHA_SIZE * ALPHA_SIZE * 4)
    offset = 0
    for y in range(ALPHA_SIZE):
        for x in range(ALPHA_SIZE):
            alpha = gear_alpha_at(x, y)
            pixels[offset : offset + 4] = (255, 255, 255, alpha)
            offset += 4
    return pixels


def generate_alpha(output):
    output = Path(output)
    _native.write_texture_avif(
        os.fspath(output),
        ALPHA_SIZE,
        ALPHA_SIZE,
        bytes(build_gear_rgba()),
        False,
    )
    data = output.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def generate(hdr_output=DEFAULT_HDR_OUTPUT, alpha_output=DEFAULT_ALPHA_OUTPUT):
    return {
        "hdr": generate_hdr(Path(hdr_output)),
        "alpha": generate_alpha(Path(alpha_output)),
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hdr-output", type=Path, default=DEFAULT_HDR_OUTPUT
    )
    parser.add_argument(
        "--alpha-output", type=Path, default=DEFAULT_ALPHA_OUTPUT
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        records = generate(args.hdr_output, args.alpha_output)
    except (OSError, RuntimeError, ValueError) as error:
        print("error: {}".format(error), file=sys.stderr)
        return 2
    hdr_size, hdr_digest = records["hdr"]
    alpha_size, alpha_digest = records["alpha"]
    print(
        "generated {} ({}x{}, {} bytes, sha256={})".format(
            args.hdr_output,
            HDR_WIDTH,
            HDR_HEIGHT,
            hdr_size,
            hdr_digest,
        )
    )
    print(
        "generated {} ({}x{}, {} bytes, sha256={})".format(
            args.alpha_output,
            ALPHA_SIZE,
            ALPHA_SIZE,
            alpha_size,
            alpha_digest,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
