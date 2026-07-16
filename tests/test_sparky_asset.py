from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "assets/examples/models/sparky"
MANIFEST = ASSET_DIR / "manifest.json"
CC0 = ROOT / "assets/examples/models/CC0-1.0.txt"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def test_sparky_manifest_files_and_cc0_scope_are_exact():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["asset_license"] == "CC0-1.0"
    assert manifest["manifest_license"] == "Apache-2.0"

    expected = {
        "sparky.obj": (
            520676,
            "9e22935d0c7cf34d7c2964419cacb04518d4b7a9e05646d8e5ca1b14765eb5ae",
        ),
        "sparky.mtl": (
            408,
            "24e7f30ffa16d67c2b2ed092460bb7b1fc62ef2552bafdacf759810f546b4f28",
        ),
        "sparky_albedo.png": (
            15103,
            "e0c5f6b728a53d3cfbc1ef6f29bd55417170d5f02c53305a7a4b1a9f931e22f0",
        ),
    }
    records = {record["path"]: record for record in manifest["files"]}
    assert set(records) == set(expected)
    cc0 = CC0.read_text(encoding="utf-8")
    for name, (size, digest) in expected.items():
        relative = PurePosixPath(name)
        assert not relative.is_absolute() and ".." not in relative.parts
        path = ASSET_DIR / name
        assert path.stat().st_size == records[name]["bytes"] == size
        assert sha256(path) == records[name]["sha256"] == digest
        assert f"assets/examples/models/sparky/{name}" in cc0


def test_sparky_obj_topology_materials_and_bounds_match_manifest():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    vertices = []
    texcoords = 0
    normals = 0
    faces = 0
    degenerate_faces = 0
    missing_uv_faces = 0
    current_material = None
    triangles_by_material = Counter()
    degenerate_by_material = Counter()
    mtllibs = []

    for line in (ASSET_DIR / "sparky.obj").read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] == "v":
            vertices.append(tuple(float(value) for value in fields[1:4]))
        elif fields[0] == "vt":
            texcoords += 1
        elif fields[0] == "vn":
            normals += 1
        elif fields[0] == "mtllib":
            mtllibs.extend(fields[1:])
        elif fields[0] == "usemtl":
            current_material = " ".join(fields[1:])
        elif fields[0] == "f":
            faces += 1
            assert len(fields) == 4, "Sparky OBJ must remain triangulated"
            assert current_material is not None
            triangles_by_material[current_material] += 1
            if any(
                len(corner.split("/")) < 2 or not corner.split("/")[1]
                for corner in fields[1:]
            ):
                missing_uv_faces += 1
            indices = [int(corner.split("/")[0]) - 1 for corner in fields[1:]]
            positions = [vertices[index] for index in indices]
            if len(set(positions)) < 3:
                degenerate_faces += 1
                degenerate_by_material[current_material] += 1

    geometry = manifest["geometry"]
    assert len(vertices) == geometry["positions"] == 5818
    assert texcoords == geometry["texture_coordinates"] == 5818
    assert normals == geometry["explicit_normals"] == 0
    assert faces == geometry["source_triangles"] == 7284
    assert (
        degenerate_faces
        == geometry["discarded_duplicate_position_triangles"]
        == 896
    )
    assert faces - degenerate_faces == geometry["renderable_triangles"] == 6388
    assert missing_uv_faces == 0
    assert mtllibs == ["sparky.mtl"]
    expected_materials = {
        record["name"]: record["source_triangles"]
        for record in manifest["materials"]
    }
    assert triangles_by_material == expected_materials
    assert degenerate_by_material == {"PlasticBlue": 512, "PlasticWhite": 384}
    assert {
        record["name"]: record["renderable_triangles"]
        for record in manifest["materials"]
    } == {
        name: count - degenerate_by_material[name]
        for name, count in triangles_by_material.items()
    }

    minimum = [min(vertex[axis] for vertex in vertices) for axis in range(3)]
    maximum = [max(vertex[axis] for vertex in vertices) for axis in range(3)]
    assert minimum == manifest["bounds"]["min"]
    assert maximum == manifest["bounds"]["max"]


def test_sparky_mtl_and_albedo_contract():
    materials = {}
    current = None
    for line in (ASSET_DIR / "sparky.mtl").read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] == "newmtl":
            current = " ".join(fields[1:])
            assert current not in materials
            materials[current] = {}
        else:
            assert current is not None
            materials[current][fields[0]] = " ".join(fields[1:])

    expected_names = {
        record["name"]
        for record in json.loads(MANIFEST.read_text(encoding="utf-8"))["materials"]
    }
    assert set(materials) == expected_names
    assert {
        name for name, values in materials.items() if "map_Kd" in values
    } == {"ScreenFace", "ScreenChest", "ScreenPalm"}
    assert all(
        materials[name]["map_Kd"] == "sparky_albedo.png"
        for name in ("ScreenFace", "ScreenChest", "ScreenPalm")
    )

    with Image.open(ASSET_DIR / "sparky_albedo.png") as image:
        image.load()
        assert image.size == (1024, 1024)
        assert image.mode == "RGBA"
        assert image.getchannel("A").getextrema() == (255, 255)
        assert "srgb" not in image.info
        assert "icc_profile" not in image.info
