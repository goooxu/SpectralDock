import hashlib
from pathlib import Path

import pytest
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
TEXTURES = ROOT / "assets" / "examples" / "textures"
TEXTURE_METADATA = {
    "circuit-panel.png": (
        "9361c04d5fab6098676cee2f65efb8d222246ddba0b1828a7ab4088f9f05f0be",
        (1536, 1024),
        "RGB",
    ),
    "koi-mask.png": (
        "fd4376986b5622043fdb63386bc02450f9ec162d7f4517ebb154e45e3052bf60",
        (1024, 1536),
        "RGBA",
    ),
    "planet-azure.png": (
        "813e73e7b89e28098d7926093268365037fd97bc68ff91f108aad1a4099096a3",
        (1774, 887),
        "RGB",
    ),
    "planet-ember.png": (
        "14cb336904b10e18758aa1923ad786a2651e326e4f92dd116fd689675d1d5d52",
        (1774, 887),
        "RGB",
    ),
}


@pytest.mark.parametrize(
    ("name", "metadata"),
    tuple(TEXTURE_METADATA.items()),
)
def test_runtime_texture_bytes_dimensions_and_modes(name, metadata):
    expected_sha256, expected_size, expected_mode = metadata
    path = TEXTURES / name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256
    with Image.open(path) as image:
        image.load()
        assert image.size == expected_size
        assert image.mode == expected_mode


@pytest.mark.parametrize("name", ("planet-azure.png", "planet-ember.png"))
def test_planet_textures_are_exact_horizontal_wraps(name):
    with Image.open(TEXTURES / name) as image:
        image.load()
        left = image.crop((0, 0, 1, image.height)).tobytes()
        right = image.crop((image.width - 1, 0, image.width, image.height)).tobytes()
        assert left == right


def png_chunk_types(path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    offset = 8
    chunk_types = []
    while offset < len(data):
        assert offset + 12 <= len(data)
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        chunk_end = offset + 8 + length
        assert chunk_end + 4 <= len(data)
        chunk_types.append(chunk_type)
        offset = chunk_end + 4
        if chunk_type == b"IEND":
            break
    assert chunk_types[-1] == b"IEND"
    assert offset == len(data)
    return set(chunk_types)


def test_only_circuit_panel_retains_c2pa_manifest():
    assert b"caBX" in png_chunk_types(TEXTURES / "circuit-panel.png")
    for name in (
        "koi-mask.png",
        "planet-azure.png",
        "planet-ember.png",
    ):
        assert b"caBX" not in png_chunk_types(TEXTURES / name)
