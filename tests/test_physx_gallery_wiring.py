import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _bash_array(source: str, name: str) -> tuple[str, ...]:
    match = re.search(
        r"^{}=\(\n(?P<body>.*?)^\)".format(re.escape(name)),
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, "missing {} array".format(name)
    return tuple(
        line.strip()
        for line in match.group("body").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def test_physx_gallery_programs_are_a_separate_acceptance_group():
    common = (ROOT / "scripts" / "common.sh").read_text(encoding="utf-8")
    acceptance = (ROOT / "scripts" / "acceptance.sh").read_text(
        encoding="utf-8"
    )

    assert _bash_array(common, "PHYSX_GALLERY_PROGRAMS") == (
        "atelier",
        "assembly-hall",
    )
    assert set(_bash_array(common, "PHYSX_GALLERY_PROGRAMS")).isdisjoint(
        _bash_array(common, "PHYSX_EXAMPLES")
    )
    assert 'for scene in "${PHYSX_GALLERY_PROGRAMS[@]}"' in acceptance
    assert '--preview' in acceptance
    assert '--output-dir "${ROOT}/output/acceptance-gallery/${scene}"' in acceptance


def test_cover_documentation_keeps_the_canonical_order():
    expected = (
        "gallery/showcase/tidal-observatory.png",
        "gallery/showcase/atelier.png",
        "gallery/showcase/assembly-hall.png",
    )
    documents = (
        ROOT / "README.md",
        ROOT / "docs" / "EXAMPLES.md",
        ROOT / "docs" / "technical-report" / "README.md",
    )

    for document in documents:
        text = document.read_text(encoding="utf-8")
        targets = tuple(
            target
            for target in expected
            if target in text
            or ("docs/" + target) in text
            or ("../" + target) in text
        )
        assert targets == expected, "wrong cover order in {}".format(
            document.relative_to(ROOT)
        )
        positions = [
            min(
                position
                for position in (
                    text.find(target),
                    text.find("docs/" + target),
                    text.find("../" + target),
                )
                if position >= 0
            )
            for target in expected
        ]
        assert positions == sorted(positions), "wrong cover order in {}".format(
            document.relative_to(ROOT)
        )


def test_new_cover_assets_are_cc0_without_runtime_sidecars():
    dedication = (
        ROOT / "assets" / "examples" / "models" / "CC0-1.0.txt"
    ).read_text(encoding="utf-8")
    for relative in (
        "assets/examples/environments/assembly-hall-noon.hdr",
        "assets/examples/textures/assembly-hall-gear-alpha.png",
        "docs/gallery/showcase/atelier.png",
        "docs/gallery/showcase/assembly-hall.png",
    ):
        assert "- " + relative in dedication

    for stem in ("atelier", "assembly-hall"):
        assert "docs/gallery/showcase/{}.stats.json".format(stem) not in dedication
        assert "docs/gallery/showcase/{}.physics.json".format(stem) not in dedication
