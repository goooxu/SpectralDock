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
        "LICENSE",
        "NOTICE",
        "SECURITY.md",
        "THIRD_PARTY_NOTICES.md",
    )
    missing = [name for name in required if not (ROOT / name).is_file()]
    assert not missing, "missing public repository files: {}".format(missing)


def test_gallery_png_and_stats_names_stay_paired():
    gallery = ROOT / "docs" / "gallery"
    png_stems = {path.stem for path in gallery.glob("*.png")}
    stats_stems = {
        path.name[: -len(".stats.json")]
        for path in gallery.glob("*.stats.json")
    }
    assert png_stems == stats_stems == {
        "benchmark-harbor",
        "celestial-archive",
        "material-cathedral",
        "neon-koi",
        "reflector-laboratory",
    }
