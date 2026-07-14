import hashlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "tools" / "generate_hdr_environment.py"
TRACKED_ENVIRONMENT = (
    ROOT
    / "assets"
    / "examples"
    / "environments"
    / "radiance-pavilion.hdr"
)


def test_hdr_environment_generator_reconstructs_tracked_asset(tmp_path):
    regenerated = tmp_path / "radiance-pavilion.hdr"
    subprocess.run(
        [sys.executable, str(GENERATOR), "--output", str(regenerated)],
        cwd=ROOT,
        check=True,
    )

    expected = TRACKED_ENVIRONMENT.read_bytes()
    actual = regenerated.read_bytes()
    assert actual == expected, (
        "HDR generator output differs from the tracked asset: expected {}, "
        "regenerated {}".format(
            hashlib.sha256(expected).hexdigest(),
            hashlib.sha256(actual).hexdigest(),
        )
    )
    assert actual.startswith(b"#?RADIANCE\n")
    assert b"FORMAT=32-bit_rle_rgbe\n" in actual[:512]
    assert b"-Y 1024 +X 2048\n" in actual[:512]
