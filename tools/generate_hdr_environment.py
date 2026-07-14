#!/usr/bin/env python3
"""Generate the deterministic Radiance Pavilion studio environment."""

import argparse
import hashlib
import math
import os
import sys
import tempfile
from pathlib import Path


VERSION = "spectraldock-hdr-environment-generator/1.0"
WIDTH = 2048
HEIGHT = 1024
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    ROOT / "assets" / "examples" / "environments" / "radiance-pavilion.hdr"
)


def clamp(value, lower=0.0, upper=1.0):
    return max(lower, min(upper, value))


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def scale(color, amount):
    return (color[0] * amount, color[1] * amount, color[2] * amount)


def studio_basis(yaw_degrees, elevation_degrees):
    yaw = math.radians(yaw_degrees)
    elevation = math.radians(elevation_degrees)
    cosine = math.cos(elevation)
    forward = (
        cosine * math.sin(yaw),
        math.sin(elevation),
        cosine * math.cos(yaw),
    )
    right = (math.cos(yaw), 0.0, -math.sin(yaw))
    up = (
        -math.sin(yaw) * math.sin(elevation),
        cosine,
        -math.cos(yaw) * math.sin(elevation),
    )
    return forward, right, up


PANELS = (
    # name, yaw, elevation, tangent half-width/height, feather, linear RGB
    ("warm_key", -58.0, 34.0, 0.34, 0.16, 0.16, (18.0, 13.2, 8.4)),
    ("cool_fill", 67.0, 21.0, 0.12, 0.35, 0.18, (2.4, 4.5, 8.2)),
    ("overhead", 8.0, 72.0, 0.46, 0.10, 0.20, (7.5, 8.6, 10.5)),
    ("amber_rim", 168.0, 17.0, 0.09, 0.27, 0.18, (5.8, 2.5, 1.1)),
)
PANEL_BASES = tuple(
    (name, *studio_basis(yaw, elevation), half_width, half_height, feather, color)
    for name, yaw, elevation, half_width, half_height, feather, color in PANELS
)


def panel_weight(direction, forward, right, up, half_width, half_height, feather):
    facing = dot(direction, forward)
    if facing <= 0.0:
        return 0.0
    horizontal = abs(dot(direction, right) / facing) / half_width
    vertical = abs(dot(direction, up) / facing) / half_height
    extent = max(horizontal, vertical)
    if extent >= 1.0:
        return 0.0
    inner = 1.0 - feather
    if extent <= inner:
        return 1.0
    t = clamp((1.0 - extent) / feather)
    return t * t * (3.0 - 2.0 * t)


def environment_radiance(direction):
    x, y, z = direction
    sky = clamp(0.5 + 0.5 * y)
    color = (
        0.010 + 0.020 * sky,
        0.012 + 0.028 * sky,
        0.018 + 0.050 * sky,
    )

    # A dim wraparound cyclorama keeps the background readable without
    # competing with the four high-dynamic-range studio panels.
    horizon = math.exp(-((y + 0.04) / 0.19) ** 2)
    azimuth_warmth = 0.5 + 0.5 * math.cos(math.atan2(x, z) + 0.65)
    color = add(
        color,
        scale((0.040, 0.028, 0.020), horizon * (0.55 + 0.45 * azimuth_warmth)),
    )
    floor_bounce = clamp(-y) ** 1.7
    color = add(color, scale((0.028, 0.018, 0.012), floor_bounce))

    for _, forward, right, up, half_width, half_height, feather, radiance in PANEL_BASES:
        weight = panel_weight(
            direction, forward, right, up, half_width, half_height, feather
        )
        color = add(color, scale(radiance, weight))
    return color


def float_to_rgbe(red, green, blue):
    maximum = max(red, green, blue)
    if maximum < 1.0e-32:
        return (0, 0, 0, 0)
    mantissa, exponent = math.frexp(maximum)
    multiplier = mantissa * 256.0 / maximum
    return (
        min(255, int(red * multiplier)),
        min(255, int(green * multiplier)),
        min(255, int(blue * multiplier)),
        exponent + 128,
    )


def encode_component(values):
    """Encode one component using the modern Radiance scanline RLE."""
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


def scanline_bytes(row):
    theta = math.pi * (row + 0.5) / HEIGHT
    sine = math.sin(theta)
    y = math.cos(theta)
    components = [bytearray() for _ in range(4)]
    for column in range(WIDTH):
        phi = 2.0 * math.pi * ((column + 0.5) / WIDTH - 0.5)
        # Match device_programs.cu and the technical report exactly: U=0.5
        # points along +X, and increasing U rotates from +X toward +Z.
        direction = (sine * math.cos(phi), y, sine * math.sin(phi))
        rgbe = float_to_rgbe(*environment_radiance(direction))
        for component, value in zip(components, rgbe):
            component.append(value)

    encoded = bytearray((2, 2, WIDTH >> 8, WIDTH & 0xFF))
    for component in components:
        encoded.extend(encode_component(component))
    return encoded


def header_bytes():
    return (
        "#?RADIANCE\n"
        "# Generated deterministically by {}\n"
        "FORMAT=32-bit_rle_rgbe\n"
        "\n"
        "-Y {} +X {}\n".format(VERSION, HEIGHT, WIDTH)
    ).encode("ascii")


def generate(output):
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=output.parent, prefix=output.name + ".", delete=False
        ) as stream:
            temporary_name = stream.name
            header = header_bytes()
            stream.write(header)
            digest.update(header)
            size += len(header)
            for row in range(HEIGHT):
                scanline = scanline_bytes(row)
                stream.write(scanline)
                digest.update(scanline)
                size += len(scanline)
        os.replace(temporary_name, output)
        temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
    return size, digest.hexdigest()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        size, digest = generate(args.output)
    except (OSError, ValueError) as error:
        print("error: {}".format(error), file=sys.stderr)
        return 2
    print(
        "generated {} ({}x{}, {} bytes, sha256={})".format(
            args.output, WIDTH, HEIGHT, size, digest
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
