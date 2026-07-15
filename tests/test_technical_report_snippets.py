import re
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "docs" / "technical-report"
CHAPTERS = tuple("{:02d}".format(index) for index in range(1, 14))
MARKER = "<!-- source-snippet "
SNIPPET = re.compile(
    r'<!-- source-snippet id="(?P<id>[a-z0-9-]+)" '
    r'path="(?P<path>[^"]+)" anchor="(?P<anchor>[^"]+)" -->\n'
    r'```(?P<language>[a-z0-9+-]+)\n'
    r'(?P<code>.*?)\n```',
    re.DOTALL,
)
ALLOWED_ROOTS = {"include", "scripts", "src", "tests", "tools"}
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
    "output-linear-pfm",
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
REQUIRED_PHYSX_FLOW_SNIPPETS = {
    "physx-baked-scene-validation",
    "physx-body-properties",
    "physx-contract-verification",
    "physx-capsule-proxy",
    "physx-euler-conversion",
    "physx-fixed-step-simulation",
    "physx-gpu-scene-contract",
    "physx-pose-baking",
}
PHYSX_CHAPTER_SNIPPET_ORDER = (
    "physx-body-properties",
    "physx-gpu-scene-contract",
    "physx-capsule-proxy",
    "physx-fixed-step-simulation",
    "physx-euler-conversion",
    "physx-pose-baking",
    "physx-baked-scene-validation",
    "physx-contract-verification",
)
REQUIRED_VOLUME_SNIPPETS = {
    "volume-delta-tracking-acceptance",
    "volume-host-safety-gate",
    "volume-nee-estimator",
    "volume-path-estimator-partition",
    "volume-three-octave-fbm",
}
REQUIRED_WATER_SNIPPETS = {
    "rough-dielectric-btdf-jacobian",
    "rough-dielectric-vndf-pdf",
    "rough-water-reflection-oversampling",
    "water-analytic-height-gradient",
    "water-beer-segment",
    "water-bounded-split-state",
    "water-bounded-split-weights",
    "water-direct-single-event",
    "water-double-root-refinement",
    "water-exact-fresnel",
    "water-finite-emitter-balance-path",
    "water-geometric-side-consistency",
    "water-host-safety-gate",
    "water-medium-stack-update",
    "water-signed-direct-offset",
    "water-solid-sphere-intersection",
    "water-three-technique-balance",
}
REQUIRED_ENVIRONMENT_SNIPPETS = {
    "environment-direction-to-uv",
    "environment-infinite-nee",
    "environment-miss-mis",
    "environment-texel-solid-angle",
    "finite-flame-selection-pdf",
    "finite-light-vertex-mode",
    "finite-light-power-mixture",
    "finite-light-water-balance-density",
    "finite-light-water-sphere-sampling",
    "finite-light-water-two-sample",
    "hdr-rgbe-linear-decode",
    "sampling-realized-float-probabilities",
}
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

    missing_physx_snippets = REQUIRED_PHYSX_FLOW_SNIPPETS - identifiers
    assert not missing_physx_snippets, (
        "missing PhysX flow source snippets: {}".format(
            sorted(missing_physx_snippets)
        )
    )

    physx_chapter = (
        REPORT_DIR / "10-physx-rigid-body-scene-baking.md"
    ).read_text(encoding="utf-8")
    physx_positions = [
        physx_chapter.index('id="{}"'.format(identifier))
        for identifier in PHYSX_CHAPTER_SNIPPET_ORDER
    ]
    assert physx_positions == sorted(physx_positions), (
        "PhysX chapter snippets must follow the documented data flow"
    )
    for boundary in (
        "GPU-only",
        "schema v6",
        "sleeping_dynamic_actors=0",
        "motion blur",
    ):
        assert boundary in physx_chapter, (
            "PhysX chapter must explain the {} boundary".format(boundary)
        )

    missing_volume_snippets = REQUIRED_VOLUME_SNIPPETS - identifiers
    assert not missing_volume_snippets, (
        "missing volume source snippets: {}".format(
            sorted(missing_volume_snippets)
        )
    )
    volume_chapter = (
        REPORT_DIR / "11-procedural-volumetric-flame.md"
    ).read_text(encoding="utf-8")
    for boundary in (
        "Delta Tracking",
        "不注册为 OptiX primitive",
        "不散射",
        "2048 spp",
    ):
        assert boundary in volume_chapter

    missing_water_snippets = REQUIRED_WATER_SNIPPETS - identifiers
    assert not missing_water_snippets, (
        "missing water source snippets: {}".format(
            sorted(missing_water_snippets)
        )
    )
    water_chapter = (
        REPORT_DIR / "12-runtime-analytic-water.md"
    ).read_text(encoding="utf-8")
    for boundary in (
        "Fresnel",
        "Snell",
        "Beer",
        "有限顶界面",
        "不透明池壁",
        "背面剔除",
        "正退出根",
        "roughness: 0.12",
        "512 spp",
        "MNEE",
        "PFM",
    ):
        assert boundary in water_chapter

    missing_environment_snippets = REQUIRED_ENVIRONMENT_SNIPPETS - identifiers
    assert not missing_environment_snippets, (
        "missing HDR environment source snippets: {}".format(
            sorted(missing_environment_snippets)
        )
    )
    environment_chapter = (
        REPORT_DIR / "13-hdr-environment-and-importance-sampling.md"
    ).read_text(encoding="utf-8")
    for boundary in (
        "RGBE",
        "线性 Rec.709",
        "texel",
        "二维 CDF",
        "uniform",
        "importance",
        "两个 connection",
        "flame",
        "power heuristic",
        "2048×1024",
    ):
        assert boundary in environment_chapter


def test_technical_report_avoids_unsupported_math_macros():
    for report in sorted(REPORT_DIR.glob("*.md")):
        text = report.read_text(encoding="utf-8")
        assert "\\operatorname" not in text, (
            "{} uses unsupported \\operatorname".format(report.name)
        )

        prose = []
        fence = None
        for line in text.splitlines():
            stripped = line.lstrip()
            marker = next(
                (candidate for candidate in ("```", "~~~")
                 if stripped.startswith(candidate)),
                None,
            )
            if fence is not None:
                if marker == fence:
                    fence = None
                continue
            if marker is not None:
                fence = marker
                continue
            prose.append(re.sub(r"`[^`\n]*`", "", line))
        assert fence is None, "{} has an unclosed code fence".format(report.name)

        state = None
        index = 0
        prose = "\n".join(prose)
        prose = re.sub(r"<!--.*?-->", "", prose, flags=re.DOTALL)
        prose = re.sub(r"\]\([^\)\n]*\)", "]", prose)
        while index < len(prose):
            if prose.startswith("$$", index):
                assert state != "inline", (
                    "{} opens display math inside inline math".format(report.name)
                )
                state = None if state == "display" else "display"
                index += 2
            elif prose[index] == "$":
                assert state != "display", (
                    "{} opens inline math inside display math".format(report.name)
                )
                state = None if state == "inline" else "inline"
                index += 1
            elif prose[index] == "_" and state is None:
                escaped = index > 0 and prose[index - 1] == "\\"
                assert escaped, (
                    "{} has an unescaped underscore outside math mode".format(
                        report.name
                    )
                )
                index += 1
            else:
                index += 1
        assert state is None, "{} has unclosed {} math".format(report.name, state)
