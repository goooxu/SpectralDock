#!/usr/bin/env python3
"""Render HDR sampling and firefly-clamping comparison pairs."""

import argparse
from pathlib import Path

from spectraldock import Renderer


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "output/gallery/comparisons"
ENVIRONMENT = ROOT / "assets/examples/environments/radiance-pavilion.hdr"
FORMAL_SIZE = 1024
PREVIEW_SIZE = 256
ENVIRONMENT_SEED = 2201
FIREFLY_SEED = 909


def nonnegative_integer(value: str) -> int:
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return result


def create_hdr_sampling_renderer(
    *, direct_light_sampling: str = "importance", device: int = 0
) -> Renderer:
    """Build the fixed HDR-only optical table for sampling comparisons."""
    renderer = Renderer(device=device, scene_name="comparison-hdr-sampling")
    renderer.integrator(
        direct_light_sampling=direct_light_sampling,
        clamp_direct=0.0,
        clamp_indirect=0.0,
    )
    renderer.camera(
        look_from=(7.3, 4.4, 9.6),
        look_at=(0.0, 1.18, -0.8),
        up=(0.0, 1.0, 0.0),
        vfov=37.0,
        aperture=0.0,
        focus_distance=13.1,
    )
    renderer.background(
        type="environment",
        path=ENVIRONMENT,
        intensity=1.25,
        rotation_degrees=22.0,
        exposure=-0.65,
    )

    floor = renderer.material(
        name="matte-floor", type="lambertian", base_color=(0.075, 0.085, 0.10)
    )
    table = renderer.material(
        name="optical-table", type="lambertian", base_color=(0.22, 0.24, 0.27)
    )
    white = renderer.material(
        name="diffuse-calibration", type="lambertian", base_color=(0.82, 0.80, 0.74)
    )
    orange = renderer.material(
        name="diffuse-orange", type="lambertian", base_color=(0.78, 0.18, 0.035)
    )
    frame = renderer.material(
        name="instrument-frame",
        type="metal",
        base_color=(0.13, 0.15, 0.18),
        roughness=0.28,
    )
    chrome = renderer.material(
        name="polished-chrome",
        type="metal",
        base_color=(0.94, 0.96, 0.99),
        roughness=0.012,
    )
    brushed_bronze = renderer.material(
        name="brushed-bronze",
        type="metal",
        base_color=(0.72, 0.34, 0.075),
        roughness=0.20,
    )
    glass = renderer.material(
        name="optical-glass",
        type="dielectric",
        base_color=(0.97, 0.99, 1.0),
        ior=1.52,
        roughness=0.018,
    )

    renderer.object(
        name="ground",
        type="rectangle",
        p1=(-14.0, 0.0, 12.0),
        p2=(-14.0, 0.0, -14.0),
        p3=(14.0, 0.0, -14.0),
        material=floor,
    )
    renderer.object(
        name="table-base",
        type="cylinder",
        base=(0.0, 0.0, -0.8),
        axis=(0.0, 1.0, 0.0),
        height=0.66,
        radius=4.55,
        material=frame,
    )
    renderer.object(
        name="table-top",
        type="disk",
        center=(0.0, 0.66, -0.8),
        normal=(0.0, 1.0, 0.0),
        radius=4.55,
        material=table,
    )

    renderer.object(
        name="chrome-reference",
        type="sphere",
        center=(-1.38, 1.52, -0.45),
        radius=0.86,
        material=chrome,
    )
    renderer.object(
        name="glass-reference",
        type="sphere",
        center=(0.68, 1.48, 0.10),
        radius=0.82,
        material=glass,
    )
    renderer.object(
        name="diffuse-reference",
        type="sphere",
        center=(2.25, 1.31, -1.15),
        radius=0.65,
        material=white,
    )
    renderer.object(
        name="bronze-reference",
        type="sphere",
        center=(-0.15, 1.14, -2.35),
        radius=0.48,
        material=brushed_bronze,
    )

    for index, (x, z, material) in enumerate(
        (
            (-2.92, -1.95, orange),
            (-2.65, 0.95, white),
            (2.72, 0.90, orange),
        )
    ):
        renderer.object(
            name=f"calibration-column-{index}",
            type="cylinder",
            base=(x, 0.66, z),
            axis=(0.0, 1.0, 0.0),
            height=1.45,
            radius=0.24,
            material=material,
        )
        renderer.object(
            name=f"calibration-cap-{index}",
            type="disk",
            center=(x, 2.11, z),
            normal=(0.0, 1.0, 0.0),
            radius=0.24,
            material=chrome,
        )

    # The clipped polished parabola and near-specular references make the
    # low-spp clamp comparison sensitive to rare HDR sun paths.  The same HDR
    # map remains the scene's only illumination source.
    renderer.object(
        name="polished-reflector",
        type="parabola",
        origin=(0.55, 0.78, -3.15),
        normal=(0.0, 1.0, 0.0),
        focus=(1.35, 0.78, -3.15),
        clip_min=(-1.25, 0.72, -4.75),
        clip_max=(2.35, 2.75, -1.55),
        front_material=chrome,
        back_material=frame,
    )
    renderer.object(
        name="vertical-catcher",
        type="rectangle",
        p1=(-3.85, 0.66, -3.85),
        p2=(-3.85, 3.50, -3.85),
        p3=(-0.95, 3.50, -3.85),
        material=white,
    )
    return renderer


def _render(
    renderer: Renderer,
    output_dir: Path,
    stem: str,
    *,
    size: int,
    spp: int,
    clamp_direct: float,
    clamp_indirect: float,
    seed: int,
) -> None:
    output = output_dir / f"{stem}.avif"
    renderer.render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=size,
        height=size,
        spp=spp,
        depth=12,
        seed=seed,
        denoise=False,
        clamp_direct=clamp_direct,
        clamp_indirect=clamp_indirect,
    )


def render_comparisons(
    *, device: int = 0, output_dir: Path = DEFAULT_OUTPUT_DIR, preview: bool = False
) -> tuple[Path, ...]:
    """Render both OFF/ON pairs sequentially and return their AVIF paths."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    size = PREVIEW_SIZE if preview else FORMAL_SIZE

    # These two renderers are built by the same factory; integrator sampling
    # mode is their sole scene-level difference.
    for stem, mode in (
        ("environment-importance-off", "uniform"),
        ("environment-importance-on", "importance"),
    ):
        _render(
            create_hdr_sampling_renderer(
                direct_light_sampling=mode, device=device
            ),
            output_dir,
            stem,
            size=size,
            spp=4 if preview else 16,
            clamp_direct=0.0,
            clamp_indirect=0.0,
            seed=ENVIRONMENT_SEED,
        )

    # Reuse one frozen importance-sampled renderer.  Clamp thresholds are the
    # only changed render parameters in this second pair.
    firefly = create_hdr_sampling_renderer(
        direct_light_sampling="importance", device=device
    )
    for stem, direct, indirect in (
        ("firefly-clamp-off", 0.0, 0.0),
        ("firefly-clamp-on", 64.0, 16.0),
    ):
        _render(
            firefly,
            output_dir,
            stem,
            size=size,
            spp=4 if preview else 32,
            clamp_direct=direct,
            clamp_indirect=indirect,
            seed=FIREFLY_SEED,
        )

    return tuple(
        output_dir / f"{stem}.avif"
        for stem in (
            "environment-importance-off",
            "environment-importance-on",
            "firefly-clamp-off",
            "firefly-clamp-on",
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", type=nonnegative_integer, default=0)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--preview", action="store_true", help="render a low-cost 256 px preview"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    render_comparisons(
        device=args.device, output_dir=args.output_dir, preview=args.preview
    )


if __name__ == "__main__":
    main()
