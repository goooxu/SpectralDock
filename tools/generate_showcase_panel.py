#!/usr/bin/env python3
"""Generate the deterministic showcase panel mesh and linear data textures."""

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from array import array
from pathlib import Path

from spectraldock import _native


VERSION = "spectraldock-showcase-panel-generator/1.0"
TEXTURE_SIZE = 1024
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = (
    ROOT / "assets" / "examples" / "models" / "showcase-panel"
)

OBJ_NAME = "showcase-panel.obj"
NORMAL_NAME = "showcase-panel-normal.avif"
METALLIC_ROUGHNESS_NAME = "showcase-panel-metallic-roughness.avif"
MANIFEST_NAME = "manifest.json"


def clamp(value, lower, upper):
    return max(lower, min(upper, value))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write_linear_rgb8_avif(path, width, height, pixels):
    """Write lossless top-to-bottom RGB8 data as the strict linear AVIF profile."""
    expected_size = width * height * 3
    if len(pixels) != expected_size:
        raise ValueError(
            f"RGB8 payload has {len(pixels)} bytes, expected {expected_size}"
        )
    rgba = bytearray(width * height * 4)
    source = 0
    destination = 0
    while source < len(pixels):
        rgba[destination : destination + 4] = (
            pixels[source],
            pixels[source + 1],
            pixels[source + 2],
            255,
        )
        source += 3
        destination += 4
    _native.write_texture_avif(
        os.fspath(path), width, height, bytes(rgba), False
    )


def distance_to_axis_segment(x, y, x0, y0, x1, y1):
    """Return a deterministic squared distance to an axis-aligned segment."""
    if x0 == x1:
        dx = abs(x - x0)
        dy = 0 if min(y0, y1) <= y <= max(y0, y1) else min(
            abs(y - y0), abs(y - y1)
        )
    elif y0 == y1:
        dx = 0 if min(x0, x1) <= x <= max(x0, x1) else min(
            abs(x - x0), abs(x - x1)
        )
        dy = abs(y - y0)
    else:
        raise ValueError("showcase traces must be axis-aligned")
    return dx * dx + dy * dy


TRACE_SEGMENTS = (
    (72, 196, 302, 196),
    (302, 196, 302, 334),
    (302, 334, 428, 334),
    (596, 690, 720, 690),
    (720, 690, 720, 826),
    (720, 826, 952, 826),
    (110, 760, 248, 760),
    (248, 630, 248, 760),
    (776, 264, 776, 394),
    (776, 264, 914, 264),
)


def integer_sqrt(value):
    """Return floor(sqrt(value)) on every supported Python version."""
    result = int(math.sqrt(value))
    while (result + 1) * (result + 1) <= value:
        result += 1
    while result * result > value:
        result -= 1
    return result


def radial_distance(x, y, center_x=512, center_y=512):
    dx = x - center_x
    dy = y - center_y
    return integer_sqrt(dx * dx + dy * dy)


def build_radius_field():
    values = array("H")
    values.extend(
        radial_distance(x, y)
        for y in range(TEXTURE_SIZE)
        for x in range(TEXTURE_SIZE)
    )
    return values


def build_trace_relief():
    size = TEXTURE_SIZE
    relief = array("H", [0]) * (size * size)
    for x0, y0, x1, y1 in TRACE_SEGMENTS:
        for y in range(max(0, min(y0, y1) - 15), min(size, max(y0, y1) + 16)):
            for x in range(
                max(0, min(x0, x1) - 15), min(size, max(x0, x1) + 16)
            ):
                distance = integer_sqrt(
                    distance_to_axis_segment(x, y, x0, y0, x1, y1)
                )
                if distance <= 5:
                    value = 190
                elif distance < 15:
                    value = (15 - distance) * 19
                else:
                    value = 0
                index = y * size + x
                relief[index] = max(relief[index], value)
    return relief


def build_bolt_relief():
    size = TEXTURE_SIZE
    relief = array("H", [0]) * (size * size)
    for center_x, center_y in ((112, 112), (912, 112), (112, 912), (912, 912)):
        for y in range(center_y - 37, center_y + 38):
            for x in range(center_x - 37, center_x + 38):
                radius = radial_distance(x, y, center_x, center_y)
                if radius <= 24:
                    value = 250
                elif radius < 38:
                    value = (38 - radius) * 250 // 14
                else:
                    value = 0
                relief[y * size + x] = value
    return relief


def height_at(x, y, radius, trace_relief, bolt_relief):
    """Return a fixed-point machined-panel height at an integer texel."""
    height = 1024

    # A broad beveled medallion gives the normal-map comparison a strong,
    # readable silhouette without changing the actual OBJ geometry.
    if radius <= 164:
        height += 420
    elif radius < 204:
        height += (204 - radius) * 420 // 40

    # Two recessed circular tool paths and four raised fasteners provide both
    # tangent directions, making an accidental DirectX/-Y interpretation easy
    # to spot under a grazing light.
    if abs(radius - 254) <= 7:
        height -= (8 - abs(radius - 254)) * 24
    if abs(radius - 314) <= 4:
        height -= (5 - abs(radius - 314)) * 16

    height += bolt_relief
    height += trace_relief

    # Shallow diagonal milling marks keep the otherwise flat fields active.
    diagonal = (x + 2 * y) % 64
    groove_distance = min(diagonal, 64 - diagonal)
    if groove_distance <= 2:
        height -= (3 - groove_distance) * 12

    return clamp(height, 0, 65535)


def build_height_field(radius_field, trace_relief, bolt_relief):
    size = TEXTURE_SIZE
    values = array("H")
    values.extend(
        height_at(
            index % size,
            index // size,
            radius_field[index],
            trace_relief[index],
            bolt_relief[index],
        )
        for index in range(size * size)
    )
    return values


def unit_component_to_byte(component, length):
    magnitude = (abs(component) * 127 + length // 2) // length
    signed = magnitude if component >= 0 else -magnitude
    return clamp(128 + signed, 0, 255)


def build_normal_pixels(heights):
    """Encode tangent-space normals using the renderer's OpenGL/+Y convention."""
    size = TEXTURE_SIZE
    pixels = bytearray(size * size * 3)
    for y in range(size):
        top = max(0, y - 1) * size
        center = y * size
        bottom = min(size - 1, y + 1) * size
        for x in range(size):
            left = max(0, x - 1)
            right = min(size - 1, x + 1)
            du = int(heights[center + right]) - int(heights[center + left])
            # Image row zero maps to v=1 in the renderer. Therefore -dh/dv,
            # the OpenGL green component, is h(bottom)-h(top).
            minus_dv = int(heights[bottom + x]) - int(heights[top + x])
            nx = -8 * du
            ny = 8 * minus_dv
            nz = 512
            length = integer_sqrt(nx * nx + ny * ny + nz * nz)
            offset = (center + x) * 3
            pixels[offset] = unit_component_to_byte(nx, length)
            pixels[offset + 1] = unit_component_to_byte(ny, length)
            pixels[offset + 2] = unit_component_to_byte(nz, length)
    return pixels


def build_metallic_roughness_pixels(radius_field, trace_relief, bolt_relief):
    """Build glTF-style packed data: R unused, G roughness, B metallic."""
    size = TEXTURE_SIZE
    pixels = bytearray(size * size * 3)
    for y in range(size):
        for x in range(size):
            index = y * size + x
            radius = radius_field[index]
            roughness = 164
            metallic = 214

            if radius <= 164:
                roughness, metallic = 58, 246
            elif 204 <= radius <= 320:
                roughness, metallic = 204, 116

            if bolt_relief[index] > 0:
                roughness, metallic = 74, 255

            if trace_relief[index] > 0:
                roughness, metallic = 34, 255

            # R is deliberately one: it is ignored by SpectralDock's PBR
            # shader and remains compatible with glTF's optional occlusion use.
            offset = index * 3
            pixels[offset] = 255
            pixels[offset + 1] = roughness
            pixels[offset + 2] = metallic
    return pixels


def serialize_obj():
    return (
        "\n".join(
            (
                f"# Generated deterministically by {VERSION}",
                "# SPDX-License-Identifier: CC0-1.0",
                "o showcase_panel",
                "v -1.000000 -1.000000 0.000000",
                "v 1.000000 -1.000000 0.000000",
                "v 1.000000 1.000000 0.000000",
                "v -1.000000 1.000000 0.000000",
                "vt 0.000000 0.000000",
                "vt 1.000000 0.000000",
                "vt 1.000000 1.000000",
                "vt 0.000000 1.000000",
                "vn 0.000000 0.000000 1.000000",
                "s 1",
                "f 1/1/1 2/2/1 3/3/1",
                "f 1/1/1 3/3/1 4/4/1",
            )
        )
        + "\n"
    ).encode("ascii")


def file_record(path, role, data, **metadata):
    return {
        "path": path,
        "role": role,
        "bytes": len(data),
        "sha256": sha256(data),
        **metadata,
    }


def serialize_manifest(obj_bytes, normal_bytes, metallic_roughness_bytes):
    manifest = {
        "schema_version": 1,
        "name": "showcase-panel",
        "description": (
            "Deterministic UV-mapped panel for SpectralDock PBR and tangent-space "
            "normal-map showcase scenes."
        ),
        "source": "Procedurally generated for SpectralDock",
        "generator": VERSION,
        "source_archives_in_distribution": False,
        "asset_license": "CC0-1.0",
        "license_file": "../CC0-1.0.txt",
        "manifest_license": "Apache-2.0",
        "manifest_license_file": "../../../../LICENSE",
        "coordinate_system": {
            "up": "+Y",
            "front": "+Z",
            "units": "scene units",
        },
        "geometry": {
            "positions": 4,
            "texture_coordinates": 4,
            "explicit_normals": 1,
            "triangles": 2,
            "bounds": {
                "min": [-1.0, -1.0, 0.0],
                "max": [1.0, 1.0, 0.0],
            },
        },
        "files": [
            file_record(
                OBJ_NAME,
                "triangle geometry with complete UVs and explicit +Z normals",
                obj_bytes,
            ),
            file_record(
                NORMAL_NAME,
                "OpenGL/+Y tangent-space normal data",
                normal_bytes,
                width=TEXTURE_SIZE,
                height=TEXTURE_SIZE,
                mode="RGB8",
                format="AVIF",
                encoding="lossless 8-bit YUV 4:4:4 full-range",
                scene_color_space="linear",
                cicp=[1, 8, 0],
                convention="OpenGL/+Y",
            ),
            file_record(
                METALLIC_ROUGHNESS_NAME,
                "packed metallic-roughness data",
                metallic_roughness_bytes,
                width=TEXTURE_SIZE,
                height=TEXTURE_SIZE,
                mode="RGB8",
                format="AVIF",
                encoding="lossless 8-bit YUV 4:4:4 full-range",
                scene_color_space="linear",
                cicp=[1, 8, 0],
                channels={
                    "R": "unused (constant 1.0)",
                    "G": "roughness",
                    "B": "metallic",
                },
            ),
        ],
    }
    return (json.dumps(manifest, indent=2, ensure_ascii=True) + "\n").encode(
        "ascii"
    )


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(str(temporary), 0o644)
        os.replace(temporary, path)
    except BaseException:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        raise


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        obj_bytes = serialize_obj()
        radius_field = build_radius_field()
        trace_relief = build_trace_relief()
        bolt_relief = build_bolt_relief()
        heights = build_height_field(radius_field, trace_relief, bolt_relief)
        normal_path = args.output_dir / NORMAL_NAME
        metallic_roughness_path = args.output_dir / METALLIC_ROUGHNESS_NAME
        write_linear_rgb8_avif(
            normal_path, TEXTURE_SIZE, TEXTURE_SIZE, build_normal_pixels(heights)
        )
        write_linear_rgb8_avif(
            metallic_roughness_path,
            TEXTURE_SIZE,
            TEXTURE_SIZE,
            build_metallic_roughness_pixels(
                radius_field, trace_relief, bolt_relief
            ),
        )
        normal_bytes = normal_path.read_bytes()
        metallic_roughness_bytes = metallic_roughness_path.read_bytes()
        manifest_bytes = serialize_manifest(
            obj_bytes, normal_bytes, metallic_roughness_bytes
        )

        outputs = (
            (OBJ_NAME, obj_bytes),
            (MANIFEST_NAME, manifest_bytes),
        )
        for name, data in outputs:
            atomic_write(args.output_dir / name, data)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(
        "generated {} (4 vertices, 2 triangles) and two {}x{} linear RGB8 "
        "textures in {}".format(
            OBJ_NAME,
            TEXTURE_SIZE,
            TEXTURE_SIZE,
            args.output_dir,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
