import re
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "docs" / "technical-report"
CHAPTERS = tuple("{:02d}".format(index) for index in range(1, 10))
MARKER = "<!-- source-snippet "
SNIPPET = re.compile(
    r'<!-- source-snippet id="(?P<id>[a-z0-9-]+)" '
    r'path="(?P<path>[^"]+)" anchor="(?P<anchor>[^"]+)" -->\n'
    r'```(?P<language>[a-z0-9+-]+)\n'
    r'(?P<code>.*?)\n```',
    re.DOTALL,
)
ALLOWED_ROOTS = {"include", "scripts", "src", "tests"}
LANGUAGES = {
    ".cpp": "cpp",
    ".cu": "cpp",
    ".h": "cpp",
    ".hpp": "cpp",
    ".py": "python",
    ".sh": "bash",
}
REQUIRED_OPTIX_FLOW_SNIPPETS = {
    "conditional-gas-compaction",
    "mesh-gas-resource-reuse",
    "optix-context-pipeline-setup",
    "optix-ir-build-command",
    "optix-ias-instance-binding",
    "optix-launch-params-population",
    "optix-mesh-upload-build-input",
    "optix-radiance-traversal",
    "optix-sbt-hit-records",
    "optix-shallow-pipeline-stack",
    "optix-state-teardown",
    "optix-two-dimensional-launch",
    "output-denoiser-guide-wiring",
    "output-postprocess-kernel",
    "shadow-ray-visibility-query",
}
OPTIX_CHAPTER_SNIPPET_ORDER = (
    "optix-ir-build-command",
    "optix-context-pipeline-setup",
    "optix-shallow-pipeline-stack",
    "optix-sbt-hit-records",
    "optix-launch-params-population",
    "optix-two-dimensional-launch",
    "optix-radiance-traversal",
    "optix-state-teardown",
)
STANDARD_OPTIX_STAGES = (
    "准备 CUDA 几何数据",
    "构建 GAS / IAS 加速结构",
    "编译 RayGen、Miss、Hit 等程序",
    "创建 Pipeline 和 Shader Binding Table",
    "调用 optixLaunch",
    "执行射线遍历、求交和自定义着色",
    "使用 OptiX Denoiser 降噪",
)


def test_technical_report_source_snippets_match_the_repository():
    identifiers = set()
    excerpts = set()
    covered_chapters = set()
    snippet_count = 0

    for report in sorted(REPORT_DIR.glob("[0-9][0-9]-*.md")):
        text = report.read_text(encoding="utf-8")
        matches = list(SNIPPET.finditer(text))
        assert len(matches) == text.count(MARKER), (
            "malformed source-snippet marker in {}".format(
                report.relative_to(ROOT)
            )
        )

        if matches:
            covered_chapters.add(report.name[:2])

        for match in matches:
            snippet_count += 1
            identifier = match.group("id")
            relative = PurePosixPath(match.group("path"))
            anchor = match.group("anchor")
            language = match.group("language")
            code = match.group("code")

            assert identifier not in identifiers, (
                "duplicate source-snippet id: {}".format(identifier)
            )
            identifiers.add(identifier)

            assert not relative.is_absolute() and ".." not in relative.parts
            assert relative.parts and (
                relative.parts[0] in ALLOWED_ROOTS
                or relative.as_posix() == "CMakeLists.txt"
            ), "unsupported source-snippet path: {}".format(relative)

            source_path = (ROOT / Path(*relative.parts)).resolve()
            assert ROOT == source_path or ROOT in source_path.parents
            assert source_path.is_file(), "missing source file: {}".format(relative)

            expected_language = (
                "cmake"
                if relative.as_posix() == "CMakeLists.txt"
                else LANGUAGES.get(source_path.suffix)
            )
            assert language == expected_language, (
                "{} must use a {} code fence".format(relative, expected_language)
            )

            lines = code.splitlines()
            assert 3 <= len(lines) <= 24, (
                "source-snippet {} has {} lines; expected 3..24".format(
                    identifier, len(lines)
                )
            )
            assert anchor in code, (
                "source-snippet {} does not contain anchor {!r}".format(
                    identifier, anchor
                )
            )

            source = source_path.read_text(encoding="utf-8")
            assert code in source, (
                "source-snippet {} is stale or was reformatted".format(identifier)
            )

            excerpt_key = (relative.as_posix(), code)
            assert excerpt_key not in excerpts, (
                "duplicate embedded source excerpt: {}".format(identifier)
            )
            excerpts.add(excerpt_key)

    assert snippet_count >= 18, "expected broad core-path source coverage"
    assert covered_chapters == set(CHAPTERS), (
        "every technical-report chapter must embed source; missing {}".format(
            sorted(set(CHAPTERS) - covered_chapters)
        )
    )

    missing_flow_snippets = REQUIRED_OPTIX_FLOW_SNIPPETS - identifiers
    assert not missing_flow_snippets, (
        "missing OptiX flow source snippets: {}".format(
            sorted(missing_flow_snippets)
        )
    )

    optix_chapter = (REPORT_DIR / "07-optix-gpu-implementation.md").read_text(
        encoding="utf-8"
    )
    snippet_positions = [
        optix_chapter.index('id="{}"'.format(identifier))
        for identifier in OPTIX_CHAPTER_SNIPPET_ORDER
    ]
    assert snippet_positions == sorted(snippet_positions), (
        "OptiX chapter source snippets must follow the runtime lifecycle"
    )

    stage_positions = [optix_chapter.index(stage) for stage in STANDARD_OPTIX_STAGES]
    assert stage_positions == sorted(stage_positions), (
        "standard OptiX stages must appear in order in the overview table"
    )
    for boundary in ("构建期", "运行期", "RAII", "纯 CUDA"):
        assert boundary in optix_chapter, (
            "OptiX chapter must explain the {} boundary".format(boundary)
        )
