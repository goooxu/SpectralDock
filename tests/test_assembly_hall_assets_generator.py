import hashlib
import importlib.util
import math
from pathlib import Path
import subprocess
import sys

from avif_test_utils import read_avif_rgba


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "tools" / "generate_assembly_hall_assets.py"
TRACKED_HDR = ROOT / "assets/examples/environments/assembly-hall-noon.hdr"
TRACKED_ALPHA = ROOT / "assets/examples/textures/assembly-hall-gear-alpha.avif"


def load_generator():
    spec = importlib.util.spec_from_file_location(
        "assembly_hall_assets_generator", GENERATOR
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GENERATOR_MODULE = load_generator()


def alpha_at(pixels, width, x, y):
    return pixels[(y * width + x) * 4 + 3]


def test_generator_reconstructs_both_tracked_assets(tmp_path):
    hdr = tmp_path / "assembly-hall-noon.hdr"
    alpha = tmp_path / "assembly-hall-gear-alpha.avif"
    subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--hdr-output",
            str(hdr),
            "--alpha-output",
            str(alpha),
        ],
        cwd=ROOT,
        check=True,
    )
    for expected, actual in ((TRACKED_HDR, hdr),):
        expected_bytes = expected.read_bytes()
        actual_bytes = actual.read_bytes()
        assert actual_bytes == expected_bytes, (
            "{} changed: expected {}, regenerated {}".format(
                expected.name,
                hashlib.sha256(expected_bytes).hexdigest(),
                hashlib.sha256(actual_bytes).hexdigest(),
            )
        )
    assert read_avif_rgba(alpha) == read_avif_rgba(TRACKED_ALPHA)
    assert b"-Y 1024 +X 2048\n" in hdr.read_bytes()[:512]


def test_noon_environment_is_finite_seamless_and_sun_dominated():
    generator = GENERATOR_MODULE
    epsilon = 1.0e-7
    for elevation in (-70.0, -5.0, 12.0, 55.0, 86.0):
        radians = math.radians(elevation)
        horizontal = math.cos(radians)
        before = generator.environment_radiance(
            (-horizontal, math.sin(radians), -horizontal * epsilon)
        )
        after = generator.environment_radiance(
            (-horizontal, math.sin(radians), horizontal * epsilon)
        )
        assert all(math.isfinite(value) and value >= 0.0 for value in before)
        for first, second in zip(before, after):
            assert math.isclose(first, second, rel_tol=2.0e-5, abs_tol=2.0e-6)

    luminance = lambda color: (
        0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]
    )
    sun = luminance(generator.environment_radiance(generator.SUN_DIRECTION))
    zenith = luminance(generator.environment_radiance((0.0, 1.0, 0.0)))
    horizon = luminance(generator.environment_radiance((1.0, 0.0, 0.0)))
    assert min(zenith, horizon) > 0.05
    assert sun > 150.0 * max(zenith, horizon)


def test_gear_mask_is_rgba_and_has_teeth_spokes_ring_and_hole():
    width, height, pixels, _ = read_avif_rgba(TRACKED_ALPHA)
    assert (width, height) == (1024, 1024)
    assert set(pixels[0::4]) == {255}
    assert set(pixels[1::4]) == {255}
    assert set(pixels[2::4]) == {255}
    assert set(pixels[3::4]) == {0, 255}
    assert alpha_at(pixels, width, 512, 512) == 0
    assert alpha_at(pixels, width, 512 + 100, 512) == 255
    assert alpha_at(pixels, width, 512 + 240, 512) == 255
    assert alpha_at(pixels, width, 0, 0) == 0
