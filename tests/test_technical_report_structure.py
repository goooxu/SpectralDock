import html
import re
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "docs" / "technical-report"
EXPECTED_CHAPTERS = (
    "01-vectors-rays-and-camera.md",
    "02-light-and-rendering-equation.md",
    "03-materials-and-bsdf.md",
    "04-monte-carlo-path-tracing.md",
    "05-direct-lighting-and-mis.md",
    "06-hdr-environment-and-importance-sampling.md",
    "07-geometry-visibility-and-bvh.md",
    "08-optix-gpu-implementation.md",
    "09-denoising-color-and-output.md",
    "10-procedural-volumetric-flame.md",
    "11-runtime-analytic-water.md",
    "12-physx-rigid-body-scene-baking.md",
    "13-limitations-performance-and-validation.md",
)
MARKDOWN_LINK = re.compile(r'!?\[[^\]]*\]\((?P<target>[^)\n]+)\)')
NAVIGATION_LINK = re.compile(
    r'\[(?P<label>[^\]]*(?:上一章|下一章)[^\]]*)\]'
    r'\((?P<target>[^)#]+\.md)(?:#[^)]+)?\)'
)
HEADING = re.compile(r"^(?P<level>#{1,6})\s+(?P<title>.+?)\s*$", re.MULTILINE)


def _without_fenced_blocks(markdown):
    prose = []
    fence = None
    for line in markdown.splitlines():
        stripped = line.lstrip()
        marker = next(
            (
                candidate
                for candidate in ("```", "~~~")
                if stripped.startswith(candidate)
            ),
            None,
        )
        if fence is not None:
            if marker == fence:
                fence = None
            continue
        if marker is not None:
            fence = marker
            continue
        prose.append(line)
    return "\n".join(prose)


def _github_heading_slugs(markdown):
    slugs = set()
    occurrences = {}
    for match in HEADING.finditer(_without_fenced_blocks(markdown)):
        title = match.group("title")
        title = re.sub(r"\s+#+\s*$", "", title)
        title = re.sub(r"`([^`]*)`", r"\1", title)
        title = re.sub(r"!?\[([^\]]*)\]\([^)]+\)", r"\1", title)
        title = re.sub(r"<[^>]+>", "", title)
        title = html.unescape(title).lower()
        title = "".join(
            character
            for character in title
            if character.isalnum() or character in "-_ " or character.isspace()
        )
        base = re.sub(r"\s+", "-", title.strip())
        occurrence = occurrences.get(base, 0)
        occurrences[base] = occurrence + 1
        slugs.add(base if occurrence == 0 else "{}-{}".format(base, occurrence))
    return slugs


def _chapter_links(markdown):
    return [
        match.group("target").split("#", 1)[0]
        for match in MARKDOWN_LINK.finditer(markdown)
        if re.fullmatch(
            r"[0-9]{2}-[^/]+\.md(?:#[^)]+)?", match.group("target")
        )
    ]


def test_technical_report_has_one_consistent_thirteen_chapter_sequence():
    chapters = tuple(
        path.name for path in sorted(REPORT_DIR.glob("[0-9][0-9]-*.md"))
    )
    assert chapters == EXPECTED_CHAPTERS

    for index, filename in enumerate(EXPECTED_CHAPTERS, start=1):
        first_line = (REPORT_DIR / filename).read_text(encoding="utf-8").splitlines()[0]
        heading = re.fullmatch(r"#\s+([0-9]{2})[\s\u3000]+.+", first_line)
        assert heading is not None, "invalid chapter H1 in {}".format(filename)
        assert heading.group(1) == "{:02d}".format(index)

    readme = (REPORT_DIR / "README.md").read_text(encoding="utf-8")
    reading_order = readme.split("## 推荐阅读顺序", 1)[1].split("\n## ", 1)[0]
    assert _chapter_links(reading_order) == list(EXPECTED_CHAPTERS)


def test_technical_report_previous_and_next_navigation_forms_one_chain():
    for index, filename in enumerate(EXPECTED_CHAPTERS):
        markdown = (REPORT_DIR / filename).read_text(encoding="utf-8")
        navigation = list(NAVIGATION_LINK.finditer(markdown))
        previous = [
            match.group("target")
            for match in navigation
            if "上一章" in match.group("label")
        ]
        following = [
            match.group("target")
            for match in navigation
            if "下一章" in match.group("label")
        ]
        expected_previous = [] if index == 0 else [EXPECTED_CHAPTERS[index - 1]]
        expected_following = (
            [] if index == len(EXPECTED_CHAPTERS) - 1
            else [EXPECTED_CHAPTERS[index + 1]]
        )
        assert previous == expected_previous, "wrong previous link in {}".format(
            filename
        )
        assert following == expected_following, "wrong next link in {}".format(
            filename
        )


def test_technical_report_local_links_and_markdown_anchors_are_valid():
    reports = [REPORT_DIR / "README.md"] + [
        REPORT_DIR / filename for filename in EXPECTED_CHAPTERS
    ]
    heading_cache = {}

    for report in reports:
        markdown = report.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(_without_fenced_blocks(markdown)):
            target = match.group("target").strip()
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            target_path, separator, fragment = target.partition("#")
            target_path = unquote(target_path)
            fragment = unquote(fragment)
            resolved = (
                report if not target_path else (report.parent / target_path).resolve()
            )
            assert resolved == ROOT or ROOT in resolved.parents, (
                "local link escapes the repository in {}: {}".format(
                    report.relative_to(ROOT), target
                )
            )
            assert resolved.exists(), "broken local link in {}: {}".format(
                report.relative_to(ROOT), target
            )

            if separator and fragment:
                assert resolved.suffix == ".md", (
                    "anchor target is not Markdown in {}: {}".format(
                        report.relative_to(ROOT), target
                    )
                )
                if resolved not in heading_cache:
                    heading_cache[resolved] = _github_heading_slugs(
                        resolved.read_text(encoding="utf-8")
                    )
                assert fragment in heading_cache[resolved], (
                    "broken Markdown anchor in {}: {}".format(
                        report.relative_to(ROOT), target
                    )
                )
