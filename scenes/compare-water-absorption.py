#!/usr/bin/env python3
"""Render the fixed depth-tank Beer-absorption comparison pair."""

import argparse
from pathlib import Path
from typing import Sequence

from spectraldock import Renderer


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "output/gallery/comparisons"
FORMAL_SIZE = 1024
PREVIEW_SIZE = 256
SEED = 808
CLEAR_ABSORPTION = (0.0, 0.0, 0.0)
DISPLAY_ABSORPTION = (0.45, 0.09, 0.025)


def nonnegative_integer(value: str) -> int:
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return result


def create_water_absorption_renderer(
    *, absorption: Sequence[float], device: int = 0
) -> Renderer:
    """Build the fixed depth-gradient tank with the requested Beer medium."""
    renderer = Renderer(device=device, scene_name="comparison-water-absorption")
    renderer.integrator(
        direct_light_sampling="importance",
        clamp_direct=0.0,
        clamp_indirect=0.0,
    )
    renderer.camera(
        look_from=(5.6, 3.45, 7.6),
        look_at=(0.0, -0.58, -0.55),
        up=(0.0, 1.0, 0.0),
        vfov=35.0,
        aperture=0.0,
        focus_distance=10.65,
    )
    renderer.background(
        type="constant", color=(0.006, 0.011, 0.018), exposure=-0.35
    )

    water = renderer.material(
        name="tank-water",
        type="water",
        roughness=0.12,
        ior=1.333,
        absorption=absorption,
    )
    pale = renderer.material(
        name="neutral-pale", type="lambertian", base_color=(0.72, 0.71, 0.66)
    )
    sand = renderer.material(
        name="tank-floor", type="lambertian", base_color=(0.33, 0.29, 0.22)
    )
    dark = renderer.material(
        name="tank-frame", type="lambertian", base_color=(0.025, 0.032, 0.04)
    )
    copper = renderer.material(
        name="depth-markers",
        type="metal",
        base_color=(0.72, 0.28, 0.075),
        roughness=0.26,
    )
    white_emitter = renderer.material(
        name="white-depth-probe", type="emitter", emission=(3.6, 3.6, 3.6)
    )
    overhead_emitter = renderer.material(
        name="overhead-emitter", type="emitter", emission=(14.0, 15.5, 18.0)
    )

    renderer.object(
        name="tank-floor",
        type="rectangle",
        p1=(-3.3, -2.15, 2.8),
        p2=(-3.3, -2.15, -3.6),
        p3=(3.3, -2.15, -3.6),
        material=sand,
    )
    renderer.object(
        name="tank-back",
        type="rectangle",
        p1=(-3.3, -2.15, -3.6),
        p2=(-3.3, 2.25, -3.6),
        p3=(3.3, 2.25, -3.6),
        material=dark,
    )
    renderer.object(
        name="tank-left",
        type="rectangle",
        p1=(-3.3, -2.15, 2.8),
        p2=(-3.3, 0.22, 2.8),
        p3=(-3.3, 0.22, -3.6),
        material=dark,
    )
    renderer.object(
        name="tank-right",
        type="rectangle",
        p1=(3.3, -2.15, -3.6),
        p2=(3.3, 0.22, -3.6),
        p3=(3.3, 0.22, 2.8),
        material=dark,
    )

    # Equal neutral emitters at increasing depths make path-length-dependent
    # RGB attenuation legible independently of surface illumination.
    for name, center, radius in (
        ("shallow-probe", (-1.72, -0.30, -0.75), 0.36),
        ("middle-probe", (0.0, -0.88, -0.75), 0.36),
        ("deep-probe", (1.72, -1.47, -0.75), 0.36),
    ):
        renderer.object(
            name=name,
            type="sphere",
            center=center,
            radius=radius,
            material=white_emitter,
        )

    for index, (x, height) in enumerate(((-1.72, 1.50), (0.0, 0.92), (1.72, 0.33))):
        renderer.object(
            name=f"depth-plinth-{index}",
            type="cylinder",
            base=(x, -2.15, -0.75),
            axis=(0.0, 1.0, 0.0),
            height=height,
            radius=0.62,
            material=pale,
        )
        renderer.object(
            name=f"depth-ring-{index}",
            type="cylinder",
            base=(x, -2.10 + height, -0.75),
            axis=(0.0, 1.0, 0.0),
            height=0.08,
            radius=0.66,
            material=copper,
        )

    renderer.object(
        name="water-surface",
        type="water_surface",
        center=(0.0, 0.12, -0.4),
        size=(6.6, 6.4),
        material=water,
        waves=(
            {
                "direction": (1.0, 0.18),
                "amplitude": 0.045,
                "wavelength": 2.35,
                "phase_radians": 0.35,
            },
            {
                "direction": (-0.28, 1.0),
                "amplitude": 0.025,
                "wavelength": 1.28,
                "phase_radians": 1.65,
            },
            {
                "direction": (0.72, 1.0),
                "amplitude": 0.012,
                "wavelength": 0.70,
                "phase_radians": 3.10,
            },
        ),
    )

    overhead = renderer.object(
        name="overhead-panel",
        type="disk",
        center=(-0.75, 4.4, 0.9),
        normal=(0.0, -1.0, 0.0),
        radius=1.05,
        material=overhead_emitter,
    )
    renderer.light(
        name="overhead-area-light",
        type="disk",
        object=overhead,
        position=(-0.75, 4.4, 0.9),
        normal=(0.0, -1.0, 0.0),
        radius=1.05,
        emission=(14.0, 15.5, 18.0),
    )
    return renderer


def _render(
    renderer: Renderer, output_dir: Path, stem: str, *, size: int, spp: int
) -> None:
    output = output_dir / f"{stem}.avif"
    renderer.render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=size,
        height=size,
        spp=spp,
        depth=12,
        seed=SEED,
        denoise=False,
        clamp_direct=0.0,
        clamp_indirect=0.0,
    )


def render_comparisons(
    *, device: int = 0, output_dir: Path = DEFAULT_OUTPUT_DIR, preview: bool = False
) -> tuple[Path, ...]:
    """Render clear water then the absorbing medium in one process."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    size = PREVIEW_SIZE if preview else FORMAL_SIZE
    spp = 16 if preview else 512
    for stem, absorption in (
        ("beer-absorption-off", CLEAR_ABSORPTION),
        ("beer-absorption-on", DISPLAY_ABSORPTION),
    ):
        _render(
            create_water_absorption_renderer(
                absorption=absorption, device=device
            ),
            output_dir,
            stem,
            size=size,
            spp=spp,
        )
    return tuple(
        output_dir / f"beer-absorption-{state}.avif" for state in ("off", "on")
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
