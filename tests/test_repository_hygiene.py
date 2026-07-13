import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRECTORIES = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "build",
    "output",
    "reports",
}
TEXT_SUFFIXES = {
    ".cpp",
    ".cu",
    ".h",
    ".json",
    ".md",
    ".obj",
    ".py",
    ".sh",
    ".svg",
    ".txt",
    ".yaml",
    ".yml",
}
TEXT_FILENAMES = {
    ".dockerignore",
    ".gitattributes",
    ".gitignore",
    "CMakeLists.txt",
    "Dockerfile",
    "Dockerfile.physx",
    "LICENSE",
    "NOTICE",
}
OLD_BRAND_TOKENS = (
    "RTX" + "Trace",
    "rtx" + "trace",
    "RTX" + "TRACE",
)
INTERNAL_FRAGMENTS = (
    "/ho" + "me/",
    "/Us" + "ers/",
    "gem" + "sg",
    "2u1g-" + "b650-0516",
)
PRIVATE_IPV4 = re.compile(
    r"\b(?:10|127)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"
    r"|\b192\.168\.\d{1,3}\.\d{1,3}\b"
    r"|\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"
)


def repository_text_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRECTORIES for part in path.relative_to(ROOT).parts):
            continue
        if path.name in TEXT_FILENAMES or path.suffix in TEXT_SUFFIXES:
            yield path


def test_legacy_brand_and_internal_environment_details_are_absent():
    for path in repository_text_files():
        relative = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        assert not any(token in relative for token in OLD_BRAND_TOKENS), relative
        assert not any(token in text for token in OLD_BRAND_TOKENS), relative
        assert not any(fragment in text for fragment in INTERNAL_FRAGMENTS), relative
        assert PRIVATE_IPV4.search(text) is None, relative


def test_public_repository_metadata_is_present():
    required = (
        ".dockerignore",
        ".gitattributes",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/pull_request_template.md",
        ".github/workflows/ci.yml",
        "CONTRIBUTING.md",
        "docs/PHYSX_SCENE.md",
        "LICENSE",
        "NOTICE",
        "SECURITY.md",
        "THIRD_PARTY_NOTICES.md",
    )
    missing = [name for name in required if not (ROOT / name).is_file()]
    assert not missing, "missing public repository files: {}".format(missing)


def test_gallery_records_have_required_sidecars():
    gallery = ROOT / "docs" / "gallery"
    png_stems = {path.stem for path in gallery.glob("*.png")}
    stats_stems = {
        path.name[: -len(".stats.json")]
        for path in gallery.glob("*.stats.json")
    }
    physics_stems = {
        path.name[: -len(".physics.json")]
        for path in gallery.glob("*.physics.json")
    }
    builtin_stems = {
        "benchmark-harbor",
        "celestial-archive",
        "material-cathedral",
        "neon-koi",
        "reflector-laboratory",
        "rocket-test-stand",
    }
    physx_stems = {"kinetic-foundry"}
    assert png_stems == stats_stems == builtin_stems | physx_stems
    assert physics_stems == physx_stems


def test_host_math_has_no_reference_rendering_implementation():
    assert not (ROOT / "include/spectraldock/integrator_policy.h").exists()

    host_math = (ROOT / "include/spectraldock/math.h").read_text(
        encoding="utf-8"
    )
    forbidden_host_symbols = (
        "SPECTRALDOCK_HD",
        "SPECTRALDOCK_INLINE",
        "kRayEpsilon",
        "struct Ray",
        "struct SurfaceHit",
        "orient_hit(",
        "reflect(",
        "refract(",
        "fresnel_schlick(",
        "intersect_sphere(",
        "intersect_parallelogram(",
        "intersect_disk(",
        "intersect_cylinder(",
        "intersect_parabola(",
        "contains(Vec3",
        "linear_to_srgb(",
        "srgb_to_linear(",
        "aces_tonemap(",
        "luminance(",
    )
    present = [symbol for symbol in forbidden_host_symbols if symbol in host_math]
    assert not present, "host rendering symbols remain: {}".format(present)

    core_tests = (ROOT / "tests/test_core.cpp").read_text(encoding="utf-8")
    forbidden_tests = (
        "test_vectors_and_optics",
        "test_intersections",
        "test_color",
        "test_mis",
    )
    present = [name for name in forbidden_tests if name in core_tests]
    assert not present, "CPU rendering tests remain: {}".format(present)
