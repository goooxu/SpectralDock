import binascii
import hashlib
import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "tools" / "generate_showcase_panel.py"
ASSET_DIR = (
    ROOT / "assets" / "examples" / "models" / "showcase-panel"
)
ASSET_NAMES = (
    "showcase-panel.obj",
    "showcase-panel-normal.png",
    "showcase-panel-metallic-roughness.png",
    "manifest.json",
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def decode_rgb8_png(path):
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")

    offset = 8
    chunks = []
    idat = bytearray()
    ihdr = None
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(
            ">I", data[offset + 8 + length : offset + 12 + length]
        )[0]
        actual_crc = binascii.crc32(chunk_type)
        actual_crc = binascii.crc32(payload, actual_crc) & 0xFFFFFFFF
        assert actual_crc == expected_crc
        chunks.append(chunk_type)
        if chunk_type == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", payload)
        elif chunk_type == b"IDAT":
            idat.extend(payload)
        offset += 12 + length

    assert offset == len(data)
    assert chunks == [b"IHDR", b"IDAT", b"IEND"]
    assert ihdr is not None
    width, height, bit_depth, color_type, compression, filtering, interlace = ihdr
    assert (bit_depth, color_type, compression, filtering, interlace) == (
        8,
        2,
        0,
        0,
        0,
    )

    packed = zlib.decompress(bytes(idat))
    row_size = width * 3
    assert len(packed) == (row_size + 1) * height
    pixels = bytearray(width * height * 3)
    for y in range(height):
        source = y * (row_size + 1)
        assert packed[source] == 0
        destination = y * row_size
        pixels[destination : destination + row_size] = packed[
            source + 1 : source + 1 + row_size
        ]
    return width, height, bytes(pixels)


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

    for name in ASSET_NAMES:
        expected = (ASSET_DIR / name).read_bytes()
        actual = (tmp_path / name).read_bytes()
        assert actual == expected, (
            "showcase-panel generator output differs for {}: expected {}, "
            "regenerated {}".format(name, sha256(expected), sha256(actual))
        )


def test_showcase_panel_pngs_are_linear_rgb8_data_maps():
    normal_width, normal_height, normal = decode_rgb8_png(
        ASSET_DIR / "showcase-panel-normal.png"
    )
    mr_width, mr_height, metallic_roughness = decode_rgb8_png(
        ASSET_DIR / "showcase-panel-metallic-roughness.png"
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
