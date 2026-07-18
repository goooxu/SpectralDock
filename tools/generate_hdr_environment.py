#!/usr/bin/env python3
"""Generate the deterministic Radiance Pavilion sunset-coast environment."""

import argparse
import hashlib
import math
import os
import sys
import tempfile
from pathlib import Path


VERSION = "spectraldock-hdr-environment-generator/2.1"
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


def mix(first, second, amount):
    return tuple(
        first_component + (second_component - first_component) * amount
        for first_component, second_component in zip(first, second)
    )


def smoothstep(lower, upper, value):
    t = clamp((value - lower) / (upper - lower))
    return t * t * (3.0 - 2.0 * t)


def spherical_direction(azimuth_degrees, elevation_degrees):
    """Return a direction in the renderer's +X-to-+Z azimuth convention."""
    azimuth = math.radians(azimuth_degrees)
    elevation = math.radians(elevation_degrees)
    cosine = math.cos(elevation)
    return (
        cosine * math.cos(azimuth),
        math.sin(elevation),
        cosine * math.sin(azimuth),
    )


# With Radiance Pavilion's fixed camera and 22-degree environment rotation,
# this places the sun near the left third of the final frame rather than just
# outside the horizontal field of view.  The low elevation leaves a visible
# margin above the horizon and below the top crop.
SUN_AZIMUTH_DEGREES = -118.0
SUN_ELEVATION_DEGREES = 4.5
SUN_DIRECTION = spherical_direction(SUN_AZIMUTH_DEGREES, SUN_ELEVATION_DEGREES)
SKY_FILL_DIRECTION = spherical_direction(
    SUN_AZIMUTH_DEGREES + 180.0, 35.0
)


def horizontal_azimuth(direction):
    """Return a periodic azimuth; poles use a harmless canonical value."""
    x, _, z = direction
    if math.hypot(x, z) < 1.0e-12:
        return 0.0
    return math.atan2(z, x)


def horizontal_distance(direction, azimuth_degrees):
    """Shortest unsigned azimuth distance, continuous across the U seam."""
    x, _, z = direction
    horizontal_length = math.hypot(x, z)
    if horizontal_length < 1.0e-12:
        return math.pi
    azimuth = math.radians(azimuth_degrees)
    alignment = (x * math.cos(azimuth) + z * math.sin(azimuth)) / horizontal_length
    return math.acos(clamp(alignment, -1.0, 1.0))


def cloud_layer(direction, center, width, phase, opacity, azimuth=None):
    """Return cloud opacity and a thin-edge mask for one periodic cloud band."""
    _, y, _ = direction
    if azimuth is None:
        azimuth = horizontal_azimuth(direction)
    vertical = math.exp(-((y - center) / width) ** 2)
    structure = (
        0.58
        + 0.20 * math.sin(3.0 * azimuth + phase)
        + 0.13 * math.sin(7.0 * azimuth - 0.7 * phase + 9.0 * y)
        + 0.08 * math.sin(13.0 * azimuth + 1.9 * phase - 5.0 * y)
    )
    field = max(0.0, vertical * structure)
    body = smoothstep(0.31, 0.58, field)
    shoulder = smoothstep(0.22, 0.43, field)
    core = smoothstep(0.49, 0.72, field)
    edge = max(0.0, shoulder - core)
    return opacity * body, edge


def island_ridge(direction):
    """Continuous distant-island height assembled from periodic angular lobes."""
    lobes = (
        # azimuth, angular width, height
        (-128.0, 22.0, 0.012),
        (-132.0, 7.0, 0.030),
        (-119.0, 9.0, 0.022),
        (-84.0, 20.0, 0.011),
        (-90.0, 8.0, 0.027),
        (-76.0, 6.0, 0.019),
    )
    ridge = 0.004
    for azimuth, width, height in lobes:
        distance = horizontal_distance(direction, azimuth)
        ridge += height * math.exp(-((distance / math.radians(width)) ** 2))
    return ridge


def environment_radiance(
    direction,
    azimuth=None,
    sun_azimuth_distance=None,
    ridge=None,
):
    _, y, _ = direction
    if azimuth is None:
        azimuth = horizontal_azimuth(direction)

    # A warm horizon grades into a cool blue zenith.  The broad sun-side haze
    # intentionally remains far dimmer than the solar disk, giving the
    # importance sampler both a concentrated target and useful wide support.
    sky_height = clamp(y)
    sky = mix(
        (0.62, 0.19, 0.045),
        (0.035, 0.105, 0.34),
        sky_height ** 0.46,
    )
    if sun_azimuth_distance is None:
        sun_azimuth_distance = horizontal_distance(
            direction, SUN_AZIMUTH_DEGREES
        )
    sun_side_haze = math.exp(-((sun_azimuth_distance / 0.92) ** 2))
    sun_side_haze *= math.exp(-((max(0.0, y) / 0.52) ** 2))
    sky = add(sky, scale((0.25, 0.072, 0.012), sun_side_haze))

    # A broad cool sky lobe sits opposite the visible sun.  It behaves like
    # natural open-sky fill, lifting the camera-facing sides of the exhibits
    # without adding a finite light or appearing as another painted panel.
    sky_fill = max(0.0, dot(direction, SKY_FILL_DIRECTION)) ** 3.0
    sky = add(sky, scale((0.65, 1.00, 1.70), sky_fill))

    # The lower hemisphere is a dark teal sea.  Integer-periodic azimuth waves
    # keep both the water texture and its solar path seamless at U=0/1.
    sea_depth = clamp(-y)
    sea = mix((0.032, 0.078, 0.105), (0.004, 0.016, 0.029), sea_depth ** 0.48)
    sea_wave = 0.93 + 0.07 * math.sin(
        86.0 * sea_depth + 5.0 * math.sin(4.0 * azimuth + 0.7)
    )
    sea = scale(sea, sea_wave)

    reflection_width = 0.018 + 0.17 * sea_depth
    reflection = math.exp(-((sun_azimuth_distance / reflection_width) ** 2))
    reflection *= math.exp(-sea_depth / 0.62)
    broken_highlight = 0.28 + 0.72 * max(
        0.0,
        math.sin(215.0 * sea_depth + 17.0 * math.sin(3.0 * azimuth - 0.4)),
    )
    sea = add(sea, scale((3.4, 1.18, 0.26), reflection * broken_highlight))

    horizon_blend = smoothstep(-0.010, 0.014, y)
    color = mix(sea, sky, horizon_blend)

    # Three distinct bands form layered sunset clouds.  Their body is cool;
    # the thin shoulder receives a warm, sun-facing rim.
    cloud_fade = smoothstep(0.0, 0.035, y)
    for center, width, phase, opacity in (
        (0.045, 0.028, 0.25, 0.42),
        (0.092, 0.038, 2.10, 0.58),
        (0.145, 0.050, 4.35, 0.38),
    ):
        cloud_opacity, cloud_edge = cloud_layer(
            direction, center, width, phase, opacity, azimuth
        )
        cloud_opacity *= cloud_fade
        cloud_edge *= cloud_fade
        sunward = math.exp(-((sun_azimuth_distance / 0.78) ** 2))
        cloud_color = mix(
            (0.105, 0.125, 0.19),
            (0.63, 0.205, 0.055),
            0.72 * sunward,
        )
        color = mix(color, cloud_color, cloud_opacity)
        color = add(
            color,
            scale(
                (1.35, 0.43, 0.075),
                cloud_edge * (0.10 + 0.90 * sunward),
            ),
        )

    # A pair of low island groups anchors the horizon without introducing
    # finite scene geometry or an additional emitter.
    if ridge is None:
        ridge = island_ridge(direction)
    island_lower_edge = smoothstep(-0.026, -0.010, y)
    island_upper_edge = 1.0 - smoothstep(ridge - 0.0025, ridge + 0.0025, y)
    island_mask = island_lower_edge * island_upper_edge
    color = mix(color, (0.0045, 0.009, 0.013), 0.96 * island_mask)

    # The soft-edged solar disk is the localized HDR peak.  A wider restrained
    # bloom prevents the disk from reading as an isolated white pixel cluster.
    sun_alignment = clamp(dot(direction, SUN_DIRECTION), -1.0, 1.0)
    sun_angle = math.acos(sun_alignment)
    disk = smoothstep(
        math.cos(math.radians(1.45)),
        math.cos(math.radians(0.72)),
        sun_alignment,
    )
    bloom = math.exp(-((sun_angle / math.radians(5.2)) ** 2))
    color = add(color, scale((1.65, 0.62, 0.13), bloom))
    color = add(color, scale((328.0, 188.0, 64.0), disk))

    # Every term above is non-negative; retain this final guard so future
    # procedural refinements cannot emit invalid RGBE input accidentally.
    return tuple(max(0.0, component) for component in color)


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


# The expensive azimuth-only pieces are identical for every scanline.  Cache
# them once so deterministic reconstruction remains practical in host CI; the
# public environment_radiance() path still computes them directly for tests
# and arbitrary directions.
COLUMN_AZIMUTHS = tuple(
    2.0 * math.pi * ((column + 0.5) / WIDTH - 0.5)
    for column in range(WIDTH)
)
COLUMN_SUN_DISTANCES = tuple(
    horizontal_distance(
        (math.cos(azimuth), 0.0, math.sin(azimuth)),
        SUN_AZIMUTH_DEGREES,
    )
    for azimuth in COLUMN_AZIMUTHS
)
COLUMN_ISLAND_RIDGES = tuple(
    island_ridge((math.cos(azimuth), 0.0, math.sin(azimuth)))
    for azimuth in COLUMN_AZIMUTHS
)


def scanline_bytes(row):
    theta = math.pi * (row + 0.5) / HEIGHT
    sine = math.sin(theta)
    y = math.cos(theta)
    components = [bytearray() for _ in range(4)]
    for column, phi in enumerate(COLUMN_AZIMUTHS):
        # Match device_programs.cu and the technical report exactly: U=0.5
        # points along +X, and increasing U rotates from +X toward +Z.
        direction = (sine * math.cos(phi), y, sine * math.sin(phi))
        rgbe = float_to_rgbe(
            *environment_radiance(
                direction,
                phi,
                COLUMN_SUN_DISTANCES[column],
                COLUMN_ISLAND_RIDGES[column],
            )
        )
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
        "PRIMARIES=0.6400 0.3300 0.3000 0.6000 0.1500 0.0600 0.3127 0.3290\n"
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
