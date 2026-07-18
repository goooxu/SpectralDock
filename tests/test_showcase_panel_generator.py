import hashlib
import json
import subprocess
import sys
from pathlib import Path

from avif_test_utils import read_avif_rgba


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "tools" / "generate_showcase_panel.py"
ASSET_DIR = (
    ROOT / "assets" / "examples" / "models" / "showcase-panel"
)
ASSET_NAMES = (
    "showcase-panel.obj",
    "showcase-panel-normal.avif",
    "showcase-panel-metallic-roughness.avif",
    "manifest.json",
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def decode_rgb8_avif(path):
    width, height, rgba, _ = read_avif_rgba(path)
    return width, height, bytes(
        channel
        for offset in range(0, len(rgba), 4)
        for channel in rgba[offset : offset + 3]
    )


def pixel(pixels, width, x, y):
    offset = (y * width + x) * 3
    return tuple(pixels[offset : offset + 3])


def test_showcase_panel_generator_reconstructs_all_tracked_files(tmp_path):
    subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--output-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        check=True,
    )

    for name in ("showcase-panel.obj",):
        expected = (ASSET_DIR / name).read_bytes()
        actual = (tmp_path / name).read_bytes()
        assert actual == expected, (
            "showcase-panel generator output differs for {}: expected {}, "
            "regenerated {}".format(name, sha256(expected), sha256(actual))
        )
    for name in ASSET_NAMES[1:3]:
        expected = read_avif_rgba(ASSET_DIR / name)
        actual = read_avif_rgba(tmp_path / name)
        assert actual == expected

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    for record in manifest["files"]:
        data = (tmp_path / record["path"]).read_bytes()
        assert record["bytes"] == len(data)
        assert record["sha256"] == sha256(data)


def test_showcase_panel_avifs_are_linear_rgb8_data_maps():
    normal_width, normal_height, normal = decode_rgb8_avif(
        ASSET_DIR / "showcase-panel-normal.avif"
    )
    mr_width, mr_height, metallic_roughness = decode_rgb8_avif(
        ASSET_DIR / "showcase-panel-metallic-roughness.avif"
    )

    assert (normal_width, normal_height) == (1024, 1024)
    assert (mr_width, mr_height) == (1024, 1024)
    assert pixel(normal, normal_width, 512, 512) == (128, 128, 255)
    assert pixel(normal, normal_width, 512, 348)[1] > 128
    assert pixel(normal, normal_width, 512, 676)[1] < 128
    assert min(normal[2::3]) >= 128

    assert set(metallic_roughness[0::3]) == {255}
    assert pixel(metallic_roughness, mr_width, 512, 512) == (255, 58, 246)
    assert len(set(metallic_roughness[1::3])) >= 4
    assert len(set(metallic_roughness[2::3])) >= 4


def test_showcase_panel_manifest_hashes_geometry_and_license_contract():
    manifest = json.loads((ASSET_DIR / "manifest.json").read_text())
    assert manifest["generator"] == "spectraldock-showcase-panel-generator/1.0"
    assert manifest["asset_license"] == "CC0-1.0"
    assert manifest["manifest_license"] == "Apache-2.0"
    assert (ASSET_DIR / manifest["license_file"]).resolve().is_file()
    assert (ASSET_DIR / manifest["manifest_license_file"]).resolve().is_file()
    assert manifest["geometry"] == {
        "positions": 4,
        "texture_coordinates": 4,
        "explicit_normals": 1,
        "triangles": 2,
        "bounds": {
            "min": [-1.0, -1.0, 0.0],
            "max": [1.0, 1.0, 0.0],
        },
    }

    assert [record["path"] for record in manifest["files"]] == list(
        ASSET_NAMES[:3]
    )
    for record in manifest["files"]:
        data = (ASSET_DIR / record["path"]).read_bytes()
        assert record["bytes"] == len(data)
        assert record["sha256"] == sha256(data)

    obj_lines = (ASSET_DIR / "showcase-panel.obj").read_text().splitlines()
    assert sum(line.startswith("v ") for line in obj_lines) == 4
    assert sum(line.startswith("vt ") for line in obj_lines) == 4
    assert obj_lines.count("vn 0.000000 0.000000 1.000000") == 1
    faces = [line.split()[1:] for line in obj_lines if line.startswith("f ")]
    assert len(faces) == 2
    assert all(
        len(corner.split("/")) == 3
        and all(index for index in corner.split("/"))
        for face in faces
        for corner in face
    )
