#!/usr/bin/env python3
"""Validate the composite GPU mesh fixture and its deterministic RTX 5090 output."""

import hashlib
import json
import sys
from pathlib import Path

from PIL import Image, ImageStat


def main() -> int:
    if len(sys.argv) != 6:
        raise RuntimeError(
            "usage: check_mesh_smoke.py SCENE OBJ IMAGE STATS EXPECTED_SHA256"
        )
    scene_path, obj_path, image_path, stats_path, hash_path = map(
        Path, sys.argv[1:]
    )

    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    mesh_objects = [
        item for item in scene["objects"] if item.get("type") == "mesh"
    ]
    if len(mesh_objects) != 2:
        raise RuntimeError("mesh smoke must contain exactly two mesh instances")
    if len({item["mesh"] for item in mesh_objects}) != 1:
        raise RuntimeError("mesh smoke instances must share one mesh resource")
    if mesh_objects[0]["transform"] == mesh_objects[1]["transform"]:
        raise RuntimeError("mesh smoke instances must use different transforms")
    first_binding = (
        mesh_objects[0].get("material"),
        mesh_objects[0].get("front_material"),
        mesh_objects[0].get("back_material"),
    )
    second_binding = (
        mesh_objects[1].get("material"),
        mesh_objects[1].get("front_material"),
        mesh_objects[1].get("back_material"),
    )
    if first_binding == second_binding:
        raise RuntimeError("mesh smoke instances must use different materials")
    if not any(item.get("alpha_texture") for item in mesh_objects):
        raise RuntimeError("mesh smoke must exercise alpha any-hit")

    obj_lines = obj_path.read_text(encoding="ascii").splitlines()
    if not any(line.startswith("vt ") for line in obj_lines):
        raise RuntimeError("mesh smoke OBJ must contain UVs")
    if not any(line.startswith("vn ") for line in obj_lines):
        raise RuntimeError("mesh smoke OBJ must contain smooth normals")

    stats = json.loads(stats_path.read_text(encoding="utf-8"))
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

    actual = hashlib.sha256(image_path.read_bytes()).hexdigest()
    expected = hash_path.read_text(encoding="ascii").strip()
    if actual != expected:
        raise RuntimeError(
            f"mesh smoke golden mismatch: expected {expected}, got {actual}"
        )

    with Image.open(image_path) as image:
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
