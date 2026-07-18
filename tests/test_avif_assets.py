import hashlib
from pathlib import Path

from avif_test_utils import read_avif_rgba


ROOT = Path(__file__).resolve().parents[1]

ASSETS = (
    ("assets/examples/textures/planet-azure.avif", 1774, 887, 2488159,
     "9233abab289782a9e1f93e81e6d84d461c083227e71d1605a3e1543e08e5bd61", True, False),
    ("assets/examples/textures/planet-ember.avif", 1774, 887, 2407774,
     "12feceb14a29b0aba84152eb564f382c6212fc941b7a79e2bab2a677ede21fbc", True, False),
    ("assets/examples/models/sparky/sparky_albedo.avif", 1024, 1024, 8604,
     "1ef9ac86df962af208ec37f8401939a9fe195fa0043c9f12fed6638fe720f2be", True, False),
    ("assets/examples/models/spot/spot_texture.avif", 1024, 1024, 65222,
     "9cb5eb3a7a184a7085c93d330698b9df324697db83a083b343a771f55b42fc16", True, False),
    ("assets/examples/models/showcase-panel/showcase-panel-normal.avif", 1024, 1024, 262480,
     "c9e4f7488fce3f84c021985e62224e1657eb82d814d06e52879c6e60b2f56740", False, False),
    ("assets/examples/models/showcase-panel/showcase-panel-metallic-roughness.avif", 1024, 1024, 6197,
     "a2c09a209e4f0d49e194ab0c482fb2cf56e58d2315d4268eabb47232a4f7acee", False, False),
    ("assets/examples/textures/assembly-hall-gear-alpha.avif", 1024, 1024, 3835,
     "0a4ed9b5a52510da6b9a707f8e307b706516c8696798f5fe6cb3161e09730592", False, True),
)


def test_runtime_texture_assets_use_the_canonical_lossless_profiles():
    for relative, width, height, size, digest, srgb, has_alpha in ASSETS:
        path = ROOT / relative
        encoded = path.read_bytes()
        assert len(encoded) == size
        assert hashlib.sha256(encoded).hexdigest() == digest

        actual_width, actual_height, _, metadata = read_avif_rgba(path)
        assert (actual_width, actual_height) == (width, height)
        assert metadata["bit_depth"] == 8
        assert metadata["yuv_format"] == "4:4:4"
        assert metadata["full_range"] is True
        assert tuple(metadata["cicp"]) == (1, 13 if srgb else 8, 0)
        assert metadata["premultiplied"] is False
        assert metadata["animated"] is False
        assert metadata["has_alpha"] is has_alpha
