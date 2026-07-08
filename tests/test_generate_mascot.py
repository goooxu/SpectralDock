import hashlib
import json
import math
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "tools" / "generate_mascot.py"
OBJ = ROOT / "assets" / "examples" / "models" / "capsule-mascot.obj"
MANIFEST = ROOT / "assets" / "examples" / "model-manifest.json"
GROUPS = [
    "mascot_torso",
    "mascot_visor",
    "mascot_eye_left",
    "mascot_eye_right",
    "mascot_belt_flange",
    "mascot_arm_left",
    "mascot_glove_left",
    "mascot_arm_right",
    "mascot_glove_right",
    "mascot_leg_left",
    "mascot_boot_left",
    "mascot_leg_right",
    "mascot_boot_right",
    "mascot_antenna_stem",
    "mascot_antenna_tip",
]


def run_generator(directory, stem):
    output = directory / f"{stem}.obj"
    manifest = directory / f"{stem}.json"
    result = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--output",
            str(output),
            "--manifest",
            str(manifest),
        ],
        universal_newlines=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return result, output, manifest


def parse_obj(data):
    vertices = []
    faces = []
    groups = []
    vertex_group = {}
    current = None

    for raw in data.decode("ascii").splitlines():
        if raw.startswith("g "):
            current = raw[2:]
            groups.append(current)
        elif raw.startswith("v "):
            assert re.fullmatch(
                r"v -?\d+\.\d{6} -?\d+\.\d{6} -?\d+\.\d{6}",
                raw,
            )
            vertices.append(tuple(map(float, raw.split()[1:])))
            vertex_group[len(vertices)] = current
        elif raw.startswith("f "):
            assert re.fullmatch(r"f \d+ \d+ \d+", raw)
            faces.append((current, tuple(map(int, raw.split()[1:]))))

    return vertices, faces, groups, vertex_group


def component_bounds(vertices, vertex_group):
    grouped = defaultdict(list)
    for index, vertex in enumerate(vertices, 1):
        grouped[vertex_group[index]].append(vertex)
    return {
        name: (
            tuple(min(vertex[axis] for vertex in values) for axis in range(3)),
            tuple(max(vertex[axis] for vertex in values) for axis in range(3)),
        )
        for name, values in grouped.items()
    }


def test_generator_is_deterministic_and_matches_checked_in_assets(tmp_path):
    first, first_obj, first_manifest = run_generator(tmp_path, "first")
    second, second_obj, second_manifest = run_generator(tmp_path, "second")
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first_obj.read_bytes() == second_obj.read_bytes() == OBJ.read_bytes()
    assert (
        first_manifest.read_bytes()
        == second_manifest.read_bytes()
        == MANIFEST.read_bytes()
    )


def test_manifest_matches_obj_bytes_and_geometry():
    obj_bytes = OBJ.read_bytes()
    manifest = json.loads(MANIFEST.read_text(encoding="ascii"))
    vertices, faces, groups, _ = parse_obj(obj_bytes)
    mins = [min(vertex[axis] for vertex in vertices) for axis in range(3)]
    maxs = [max(vertex[axis] for vertex in vertices) for axis in range(3)]

    assert manifest["schema_version"] == 1
    assert manifest["name"] == "capsule-mascot"
    assert manifest["asset"] == "models/capsule-mascot.obj"
    assert manifest["generator"] == "spectraldock-mascot-generator/1.0"
    assert manifest["license"] == "CC0-1.0"
    assert manifest["license_file"] == "models/CC0-1.0.txt"
    assert manifest["source_archives_in_distribution"] is False
    assert manifest["coordinate_system"] == {
        "up": "+Y",
        "front": "+Z",
        "ground_y": 0.0,
        "units": "scene units",
    }
    assert manifest["vertices"] == len(vertices) == 2936
    assert manifest["triangles"] == len(faces) == 5816
    assert manifest["components"] == groups == GROUPS
    assert manifest["bounds"] == {"min": mins, "max": maxs}
    assert manifest["obj_bytes"] == len(obj_bytes)
    assert manifest["obj_sha256"] == hashlib.sha256(obj_bytes).hexdigest()


def test_geometry_is_closed_non_degenerate_and_matches_contract():
    data = OBJ.read_bytes()
    vertices, faces, groups, vertex_group = parse_obj(data)
    text = data.decode("ascii")

    assert groups == GROUPS
    assert 3000 <= len(faces) <= 6000
    assert len(vertices) == 2936
    assert len(faces) == 5816
    assert "\nvt " not in text
    assert "\nvn " not in text
    assert "\nmtllib " not in text
    assert "\nusemtl " not in text
    assert all(all(math.isfinite(value) for value in vertex) for vertex in vertices)

    mins = [min(vertex[axis] for vertex in vertices) for axis in range(3)]
    maxs = [max(vertex[axis] for vertex in vertices) for axis in range(3)]
    assert mins == pytest.approx([-0.7, 0.0, -0.5], abs=1.0e-6)
    assert maxs == pytest.approx([0.7, 2.0, 0.5], abs=1.0e-6)

    edges_by_group = defaultdict(Counter)
    for group, face in faces:
        assert group in GROUPS
        assert len(set(face)) == 3
        assert all(1 <= index <= len(vertices) for index in face)
        assert {vertex_group[index] for index in face} == {group}

        a, b, c = (vertices[index - 1] for index in face)
        ux, uy, uz = (b[axis] - a[axis] for axis in range(3))
        vx, vy, vz = (c[axis] - a[axis] for axis in range(3))
        cross = (
            uy * vz - uz * vy,
            uz * vx - ux * vz,
            ux * vy - uy * vx,
        )
        assert sum(value * value for value in cross) > 1.0e-20

        for edge in (
            (face[0], face[1]),
            (face[1], face[2]),
            (face[2], face[0]),
        ):
            edges_by_group[group][tuple(sorted(edge))] += 1

    assert set(edges_by_group) == set(GROUPS)
    assert all(set(edges.values()) == {2} for edges in edges_by_group.values())


def test_components_have_intentional_assembly_gaps():
    vertices, _, _, vertex_group = parse_obj(OBJ.read_bytes())
    bounds = component_bounds(vertices, vertex_group)

    torso_min, torso_max = bounds["mascot_torso"]
    visor_min, visor_max = bounds["mascot_visor"]
    assert torso_max[2] < visor_min[2]
    for eye in ("mascot_eye_left", "mascot_eye_right"):
        eye_min, _ = bounds[eye]
        assert visor_max[2] < eye_min[2]

    left_arm_min, left_arm_max = bounds["mascot_arm_left"]
    right_arm_min, _ = bounds["mascot_arm_right"]
    assert left_arm_max[0] < torso_min[0]
    assert torso_max[0] < right_arm_min[0]

    for side in ("left", "right"):
        arm_min, _ = bounds[f"mascot_arm_{side}"]
        _, glove_max = bounds[f"mascot_glove_{side}"]
        boot_min, boot_max = bounds[f"mascot_boot_{side}"]
        leg_min, leg_max = bounds[f"mascot_leg_{side}"]
        assert glove_max[1] < arm_min[1]
        assert boot_max[1] < leg_min[1]
        assert leg_max[1] < torso_min[1]
        assert boot_min[1] >= 0.0

    _, torso_max = bounds["mascot_torso"]
    stem_min, stem_max = bounds["mascot_antenna_stem"]
    tip_min, _ = bounds["mascot_antenna_tip"]
    assert torso_max[1] < stem_min[1]
    assert stem_max[1] < tip_min[1]
