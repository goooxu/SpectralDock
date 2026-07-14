import hashlib
import importlib.util
import math
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


def load_generator_module():
    spec = importlib.util.spec_from_file_location(
        "hdr_environment_generator", GENERATOR
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def spherical_direction(azimuth, elevation):
    cosine = math.cos(elevation)
    return (
        cosine * math.cos(azimuth),
        math.sin(elevation),
        cosine * math.sin(azimuth),
    )


def luminance(color):
    return 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]


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


def test_environment_radiance_is_continuous_across_longitude_seam():
    generator = load_generator_module()
    epsilon = 1.0e-7

    for elevation_degrees in (-70.0, -25.0, -2.0, 8.0, 30.0, 72.0):
        elevation = math.radians(elevation_degrees)
        before = generator.environment_radiance(
            spherical_direction(-math.pi + epsilon, elevation)
        )
        after = generator.environment_radiance(
            spherical_direction(math.pi - epsilon, elevation)
        )
        for before_component, after_component in zip(before, after):
            assert math.isclose(
                before_component,
                after_component,
                rel_tol=2.0e-5,
                abs_tol=2.0e-6,
            )


def test_environment_radiance_is_finite_and_non_negative():
    generator = load_generator_module()
    directions = [generator.SUN_DIRECTION]
    for elevation_index in range(-16, 17):
        elevation = 0.5 * math.pi * elevation_index / 16.0
        for azimuth_index in range(64):
            azimuth = 2.0 * math.pi * azimuth_index / 64.0 - math.pi
            directions.append(spherical_direction(azimuth, elevation))

    for direction in directions:
        color = generator.environment_radiance(direction)
        assert len(color) == 3
        assert all(math.isfinite(component) for component in color)
        assert all(component >= 0.0 for component in color)


def test_environment_has_local_hdr_peak_and_broad_sky_fill():
    generator = load_generator_module()
    sun = luminance(generator.environment_radiance(generator.SUN_DIRECTION))
    zenith = luminance(generator.environment_radiance((0.0, 1.0, 0.0)))
    anti_sun_sky = luminance(
        generator.environment_radiance(
            generator.spherical_direction(
                generator.SUN_AZIMUTH_DEGREES + 180.0,
                35.0,
            )
        )
    )
    sea = luminance(
        generator.environment_radiance(
            generator.spherical_direction(generator.SUN_AZIMUTH_DEGREES, -22.0)
        )
    )

    assert min(zenith, anti_sun_sky, sea) > 0.01
    assert sun > 150.0 * max(zenith, anti_sun_sky)
