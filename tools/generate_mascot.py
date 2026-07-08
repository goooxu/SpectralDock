#!/usr/bin/env python3
"""Generate the original low-poly capsule mascot and its stable manifest."""

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


VERSION = "spectraldock-mascot-generator/1.0"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "assets" / "examples" / "models" / "capsule-mascot.obj"
DEFAULT_MANIFEST = ROOT / "assets" / "examples" / "model-manifest.json"


@dataclass
class Component:
    name: str
    vertices: list = field(default_factory=list)
    faces: list = field(default_factory=list)


class Model:
    def __init__(self):
        self.components = []

    @staticmethod
    def quantized(value):
        result = float(f"{float(value):.6f}")
        return 0.0 if result == 0.0 else result

    def add_component(self, name):
        component = Component(name)
        self.components.append(component)
        return component

    def vertex(self, component, x, y, z):
        component.vertices.append(
            (self.quantized(x), self.quantized(y), self.quantized(z))
        )
        return len(component.vertices)

    @staticmethod
    def face(component, a, b, c):
        component.faces.append((a, b, c))


def rotate_z(x, y, angle):
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return x * cosine - y * sine, x * sine + y * cosine


def add_ellipsoid(
    model,
    name,
    center,
    radii,
    segments,
    stacks,
    rotation_z=0.0,
):
    """Add a closed UV ellipsoid with unique poles and no seam duplicates."""
    if segments < 3 or stacks < 2:
        raise ValueError("ellipsoid tessellation is too small")

    component = model.add_component(name)
    cx, cy, cz = center
    rx, ry, rz = radii

    top_x, top_y = rotate_z(0.0, ry, rotation_z)
    top = model.vertex(component, cx + top_x, cy + top_y, cz)
    rings = []
    for stack in range(1, stacks):
        latitude = 0.5 * math.pi - math.pi * stack / stacks
        radial = math.cos(latitude)
        local_y = ry * math.sin(latitude)
        ring = []
        for segment in range(segments):
            longitude = 2.0 * math.pi * segment / segments
            local_x = rx * radial * math.cos(longitude)
            local_z = rz * radial * math.sin(longitude)
            rotated_x, rotated_y = rotate_z(local_x, local_y, rotation_z)
            ring.append(
                model.vertex(
                    component,
                    cx + rotated_x,
                    cy + rotated_y,
                    cz + local_z,
                )
            )
        rings.append(ring)

    bottom_x, bottom_y = rotate_z(0.0, -ry, rotation_z)
    bottom = model.vertex(component, cx + bottom_x, cy + bottom_y, cz)

    first = rings[0]
    for segment in range(segments):
        following = (segment + 1) % segments
        model.face(component, top, first[following], first[segment])

    for upper, lower in zip(rings, rings[1:]):
        for segment in range(segments):
            following = (segment + 1) % segments
            model.face(component, upper[segment], upper[following], lower[segment])
            model.face(
                component,
                upper[following],
                lower[following],
                lower[segment],
            )

    last = rings[-1]
    for segment in range(segments):
        following = (segment + 1) % segments
        model.face(component, bottom, last[segment], last[following])


def add_vertical_capsule(
    model,
    name,
    center,
    radii,
    half_segment,
    segments,
    cap_steps,
    cylinder_steps,
):
    """Add a closed Y-axis elliptical capsule."""
    if segments < 3 or cap_steps < 2 or cylinder_steps < 1:
        raise ValueError("capsule tessellation is too small")

    component = model.add_component(name)
    cx, cy, cz = center
    rx, cap_y, rz = radii
    bottom_y = cy - half_segment - cap_y
    top_y = cy + half_segment + cap_y
    bottom = model.vertex(component, cx, bottom_y, cz)

    profiles = []
    for step in range(1, cap_steps + 1):
        angle = -0.5 * math.pi + 0.5 * math.pi * step / cap_steps
        profiles.append(
            (
                cy - half_segment + cap_y * math.sin(angle),
                math.cos(angle),
            )
        )
    for step in range(1, cylinder_steps + 1):
        profiles.append(
            (
                cy - half_segment
                + 2.0 * half_segment * step / cylinder_steps,
                1.0,
            )
        )
    for step in range(1, cap_steps):
        angle = 0.5 * math.pi * step / cap_steps
        profiles.append(
            (
                cy + half_segment + cap_y * math.sin(angle),
                math.cos(angle),
            )
        )

    rings = []
    for y, radial in profiles:
        ring = []
        for segment in range(segments):
            longitude = 2.0 * math.pi * segment / segments
            ring.append(
                model.vertex(
                    component,
                    cx + rx * radial * math.cos(longitude),
                    y,
                    cz + rz * radial * math.sin(longitude),
                )
            )
        rings.append(ring)

    top = model.vertex(component, cx, top_y, cz)

    first = rings[0]
    for segment in range(segments):
        following = (segment + 1) % segments
        model.face(component, bottom, first[segment], first[following])

    for lower, upper in zip(rings, rings[1:]):
        for segment in range(segments):
            following = (segment + 1) % segments
            model.face(component, lower[segment], upper[segment], upper[following])
            model.face(
                component,
                lower[segment],
                upper[following],
                lower[following],
            )

    last = rings[-1]
    for segment in range(segments):
        following = (segment + 1) % segments
        model.face(component, top, last[following], last[segment])


def add_belt_torus(
    model,
    name,
    center,
    major_radii,
    tube_radius,
    tube_height,
    major_segments,
    tube_segments,
):
    """Add a closed elliptical torus around the Y axis."""
    component = model.add_component(name)
    cx, cy, cz = center
    major_x, major_z = major_radii
    grid = []

    for major_index in range(major_segments):
        major_angle = 2.0 * math.pi * major_index / major_segments
        cosine_major = math.cos(major_angle)
        sine_major = math.sin(major_angle)
        ring = []
        for tube_index in range(tube_segments):
            tube_angle = 2.0 * math.pi * tube_index / tube_segments
            radial = tube_radius * math.cos(tube_angle)
            ring.append(
                model.vertex(
                    component,
                    cx + (major_x + radial) * cosine_major,
                    cy + tube_height * math.sin(tube_angle),
                    cz + (major_z + radial) * sine_major,
                )
            )
        grid.append(ring)

    for major_index in range(major_segments):
        next_major = (major_index + 1) % major_segments
        for tube_index in range(tube_segments):
            next_tube = (tube_index + 1) % tube_segments
            a = grid[major_index][tube_index]
            b = grid[next_major][tube_index]
            c = grid[next_major][next_tube]
            d = grid[major_index][next_tube]
            model.face(component, a, c, b)
            model.face(component, a, d, c)


def build_model():
    model = Model()
    add_vertical_capsule(
        model,
        "mascot_torso",
        (0.0, 1.22, -0.045),
        (0.44, 0.31, 0.395),
        0.25,
        36,
        6,
        3,
    )
    add_ellipsoid(
        model,
        "mascot_visor",
        (0.0, 1.43, 0.399),
        (0.34, 0.13, 0.032),
        32,
        10,
    )
    add_ellipsoid(
        model,
        "mascot_eye_left",
        (-0.115, 1.44, 0.447),
        (0.052, 0.052, 0.010),
        16,
        8,
    )
    add_ellipsoid(
        model,
        "mascot_eye_right",
        (0.115, 1.44, 0.447),
        (0.052, 0.052, 0.010),
        16,
        8,
    )
    add_belt_torus(
        model,
        "mascot_belt_flange",
        (0.0, 1.02, -0.045),
        (0.480, 0.430),
        0.025,
        0.025,
        40,
        10,
    )

    add_ellipsoid(
        model,
        "mascot_arm_left",
        (-0.585, 1.15, -0.040),
        (0.065, 0.200, 0.075),
        18,
        10,
    )
    add_ellipsoid(
        model,
        "mascot_glove_left",
        (-0.590, 0.83, -0.015),
        (0.110, 0.110, 0.115),
        18,
        10,
    )
    add_ellipsoid(
        model,
        "mascot_arm_right",
        (0.585, 1.15, -0.040),
        (0.065, 0.200, 0.075),
        18,
        10,
    )
    add_ellipsoid(
        model,
        "mascot_glove_right",
        (0.590, 0.83, -0.015),
        (0.110, 0.110, 0.115),
        18,
        10,
    )

    add_ellipsoid(
        model,
        "mascot_leg_left",
        (-0.19, 0.46, -0.035),
        (0.085, 0.120, 0.090),
        16,
        8,
    )
    add_ellipsoid(
        model,
        "mascot_boot_left",
        (-0.19, 0.15, 0.220),
        (0.145, 0.150, 0.280),
        20,
        10,
    )
    add_ellipsoid(
        model,
        "mascot_leg_right",
        (0.19, 0.46, -0.035),
        (0.085, 0.120, 0.090),
        16,
        8,
    )
    add_ellipsoid(
        model,
        "mascot_boot_right",
        (0.19, 0.15, 0.220),
        (0.145, 0.150, 0.280),
        20,
        10,
    )

    add_ellipsoid(
        model,
        "mascot_antenna_stem",
        (0.160, 1.845, -0.015),
        (0.022, 0.065, 0.022),
        14,
        8,
        rotation_z=-0.18,
    )
    add_ellipsoid(
        model,
        "mascot_antenna_tip",
        (0.195, 1.963, -0.015),
        (0.042, 0.037, 0.042),
        18,
        10,
    )
    return model


def serialize_obj(model):
    lines = [
        "# Original capsule mascot for SpectralDock",
        f"# Generated deterministically by {VERSION}",
        "# SPDX-License-Identifier: CC0-1.0",
        "o capsule_mascot",
        "s off",
    ]
    vertex_offset = 0
    for component in model.components:
        lines.append(f"g {component.name}")
        for x, y, z in component.vertices:
            lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
        for a, b, c in component.faces:
            lines.append(
                f"f {a + vertex_offset} {b + vertex_offset} {c + vertex_offset}"
            )
        vertex_offset += len(component.vertices)
    return ("\n".join(lines) + "\n").encode("ascii")


def model_stats(model):
    vertices = [
        vertex
        for component in model.components
        for vertex in component.vertices
    ]
    return {
        "vertices": len(vertices),
        "triangles": sum(len(component.faces) for component in model.components),
        "components": [component.name for component in model.components],
        "bounds": {
            "min": [min(vertex[axis] for vertex in vertices) for axis in range(3)],
            "max": [max(vertex[axis] for vertex in vertices) for axis in range(3)],
        },
    }


def serialize_manifest(model, obj_bytes):
    stats = model_stats(model)
    manifest = {
        "schema_version": 1,
        "name": "capsule-mascot",
        "asset": "models/capsule-mascot.obj",
        "description": (
            "Original modular low-poly capsule robot mascot with visor, eyes, "
            "asymmetric antenna, gloves, boots, and belt flange."
        ),
        "generator": VERSION,
        "license": "CC0-1.0",
        "license_file": "models/CC0-1.0.txt",
        "source_archives_in_distribution": False,
        "coordinate_system": {
            "up": "+Y",
            "front": "+Z",
            "ground_y": 0.0,
            "units": "scene units",
        },
        **stats,
        "obj_sha256": hashlib.sha256(obj_bytes).hexdigest(),
        "obj_bytes": len(obj_bytes),
    }
    return (
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n"
    ).encode("ascii")


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
        os.replace(temporary, path)
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        model = build_model()
        obj_bytes = serialize_obj(model)
        manifest_bytes = serialize_manifest(model, obj_bytes)
        atomic_write(args.output, obj_bytes)
        atomic_write(args.manifest, manifest_bytes)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    stats = model_stats(model)
    print(
        "generated {} ({} vertices, {} triangles, {} components) and {}".format(
            args.output,
            stats["vertices"],
            stats["triangles"],
            len(stats["components"]),
            args.manifest,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
