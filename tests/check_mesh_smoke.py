#!/usr/bin/env python3
"""Validate the composite GPU mesh fixture and its deterministic RTX 5090 output."""

import ast
import hashlib
import json
import sys
from pathlib import Path

from PIL import Image, ImageStat


ROOT = Path(__file__).resolve().parents[1]
SCENE_PATH = ROOT / "tests/scenes/mesh-composite-smoke.py"
OBJ_PATH = ROOT / "tests/assets/uv-quad.obj"
IMAGE_PATH = ROOT / "output/tests/mesh-composite-smoke.png"
STATS_PATH = ROOT / "output/tests/mesh-composite-smoke.stats.json"
HASH_PATH = ROOT / "tests/golden/mesh-composite-smoke-64x64-spp1-depth6-seed1.sha256"


def main() -> int:
    if len(sys.argv) != 1:
        raise RuntimeError("check_mesh_smoke.py does not accept arguments")

    source = SCENE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SCENE_PATH))
    object_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "object"
    ]

    def keywords(call):
        return {keyword.arg: keyword.value for keyword in call.keywords
                if keyword.arg is not None}

    mesh_objects = []
    for call in object_calls:
        values = keywords(call)
        type_node = values.get("type")
        if (isinstance(type_node, ast.Constant)
                and type_node.value == "mesh"):
            mesh_objects.append(values)
    if len(mesh_objects) != 2:
        raise RuntimeError("mesh smoke must contain exactly two mesh instances")
    if len({ast.dump(item["mesh"]) for item in mesh_objects}) != 1:
        raise RuntimeError("mesh smoke instances must share one mesh resource")
    transform_keys = ("translate", "rotate_degrees", "scale")
    transforms = [
        tuple(ast.dump(item[key]) if key in item else None
              for key in transform_keys)
        for item in mesh_objects
    ]
    if transforms[0] == transforms[1]:
        raise RuntimeError("mesh smoke instances must use different transforms")
    binding_keys = ("material", "front_material", "back_material")
    first_binding = tuple(
        ast.dump(mesh_objects[0][key]) if key in mesh_objects[0] else None
        for key in binding_keys
    )
    second_binding = tuple(
        ast.dump(mesh_objects[1][key]) if key in mesh_objects[1] else None
        for key in binding_keys
    )
    if first_binding == second_binding:
        raise RuntimeError("mesh smoke instances must use different materials")
    if not any("alpha_texture" in item for item in mesh_objects):
        raise RuntimeError("mesh smoke must exercise alpha any-hit")

    obj_lines = OBJ_PATH.read_text(encoding="ascii").splitlines()
    if not any(line.startswith("vt ") for line in obj_lines):
        raise RuntimeError("mesh smoke OBJ must contain UVs")
    if not any(line.startswith("vn ") for line in obj_lines):
        raise RuntimeError("mesh smoke OBJ must contain smooth normals")

    stats = json.loads(STATS_PATH.read_text(encoding="utf-8"))
    geometry = stats["geometry"]
    expected_geometry = {
        "objects": 6,
        "instances": 6,
        "unique_meshes": 1,
        "mesh_triangles": 2,
        "gas_count": 5,
    }
    if geometry != expected_geometry:
        raise RuntimeError(
            f"unexpected mesh smoke geometry stats: {geometry!r}"
        )
    if "RTX 5090" not in stats["hardware"]["gpu"]:
        raise RuntimeError("mesh smoke golden is restricted to RTX 5090")
    if stats["render"]["denoised"] is not False:
        raise RuntimeError("mesh smoke golden must not use denoising")

    actual = hashlib.sha256(IMAGE_PATH.read_bytes()).hexdigest()
    expected = HASH_PATH.read_text(encoding="ascii").strip()
    if actual != expected:
        raise RuntimeError(
            f"mesh smoke golden mismatch: expected {expected}, got {actual}"
        )

    with Image.open(IMAGE_PATH) as image:
        image.load()
        if image.size != (64, 64) or image.mode != "RGBA":
            raise RuntimeError(
                f"mesh smoke must be 64x64 RGBA, got {image.size} {image.mode}"
            )
        deviation = ImageStat.Stat(image.convert("RGB")).stddev
        if max(deviation) < 3.0:
            raise RuntimeError("mesh smoke output is blank or nearly constant")

    print(f"mesh composite GPU golden passed ({actual})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
