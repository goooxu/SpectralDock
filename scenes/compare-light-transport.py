#!/usr/bin/env python3
"""Render indirect-light and OptiX-denoiser comparison pairs."""

import argparse
from pathlib import Path

from spectraldock import Renderer


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "output/gallery/comparisons"
FORMAL_SIZE = 1024
PREVIEW_SIZE = 256
INDIRECT_SEED = 1101
DENOISER_SEED = 1102


def nonnegative_integer(value: str) -> int:
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return result


def create_light_transport_renderer(*, device: int = 0) -> Renderer:
    """Build the fixed all-diffuse corridor used by both comparison pairs."""
    renderer = Renderer(device=device, scene_name="comparison-light-transport")
    renderer.integrator(
        direct_light_sampling="importance",
        clamp_direct=0.0,
        clamp_indirect=0.0,
    )
    renderer.camera(
        look_from=(0.0, 1.75, 7.8),
        look_at=(0.0, 1.55, -0.9),
        up=(0.0, 1.0, 0.0),
        vfov=38.0,
        aperture=0.0,
        focus_distance=8.7,
    )
    renderer.background(
        type="constant", color=(0.002, 0.003, 0.005), exposure=-0.35
    )

    white = renderer.material(
        name="matte-white", type="lambertian", base_color=(0.76, 0.74, 0.69)
    )
    pale = renderer.material(
        name="matte-pale", type="lambertian", base_color=(0.48, 0.52, 0.55)
    )
    red = renderer.material(
        name="matte-red", type="lambertian", base_color=(0.72, 0.055, 0.035)
    )
    blue = renderer.material(
        name="matte-blue", type="lambertian", base_color=(0.025, 0.15, 0.68)
    )
    charcoal = renderer.material(
        name="matte-charcoal", type="lambertian", base_color=(0.055, 0.06, 0.07)
    )
    emitter = renderer.material(
        name="ceiling-emitter", type="emitter", emission=(17.0, 15.5, 13.5)
    )

    # An open-front corridor makes red/blue bounce light visible on neutral
    # geometry.  All non-emissive materials are Lambertian by design so the
    # depth comparison cannot be mistaken for glass or mirror transport.
    renderer.object(
        name="floor",
        type="rectangle",
        p1=(-3.2, 0.0, 2.5),
        p2=(-3.2, 0.0, -4.3),
        p3=(3.2, 0.0, -4.3),
        material=white,
    )
    renderer.object(
        name="ceiling",
        type="rectangle",
        p1=(-3.2, 4.2, -4.3),
        p2=(-3.2, 4.2, 2.5),
        p3=(3.2, 4.2, 2.5),
        material=charcoal,
    )
    renderer.object(
        name="back-wall",
        type="rectangle",
        p1=(-3.2, 0.0, -4.3),
        p2=(-3.2, 4.2, -4.3),
        p3=(3.2, 4.2, -4.3),
        material=pale,
    )
    renderer.object(
        name="red-wall",
        type="rectangle",
        p1=(-3.2, 0.0, 2.5),
        p2=(-3.2, 4.2, 2.5),
        p3=(-3.2, 4.2, -4.3),
        material=red,
    )
    renderer.object(
        name="blue-wall",
        type="rectangle",
        p1=(3.2, 0.0, -4.3),
        p2=(3.2, 4.2, -4.3),
        p3=(3.2, 4.2, 2.5),
        material=blue,
    )

    for name, center, radius, material in (
        ("left-probe", (-1.45, 0.82, -0.45), 0.82, white),
        ("center-probe", (0.0, 1.10, -2.15), 1.10, pale),
        ("right-probe", (1.48, 0.62, 0.25), 0.62, white),
    ):
        renderer.object(
            name=name,
            type="sphere",
            center=center,
            radius=radius,
            material=material,
        )

    renderer.object(
        name="center-plinth",
        type="cylinder",
        base=(0.0, 0.0, -2.15),
        axis=(0.0, 1.0, 0.0),
        height=0.28,
        radius=1.44,
        material=charcoal,
    )
    light_panel = renderer.object(
        name="ceiling-panel",
        type="rectangle",
        p1=(-1.05, 4.08, 0.15),
        p2=(-1.05, 4.08, -1.65),
        p3=(1.05, 4.08, -1.65),
        material=emitter,
    )
    renderer.light(
        name="ceiling-area-light",
        type="rectangle",
        object=light_panel,
        position=(-1.05, 4.08, 0.15),
        edge_u=(0.0, 0.0, -1.8),
        edge_v=(2.1, 0.0, 0.0),
        emission=(17.0, 15.5, 13.5),
    )
    return renderer


def _render(
    renderer: Renderer,
    output_dir: Path,
    stem: str,
    *,
    width: int,
    height: int,
    spp: int,
    depth: int,
    denoise: bool,
    clamp_direct: float,
    clamp_indirect: float,
    seed: int,
) -> None:
    output = output_dir / f"{stem}.png"
    renderer.render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=width,
        height=height,
        spp=spp,
        depth=depth,
        seed=seed,
        denoise=denoise,
        clamp_direct=clamp_direct,
        clamp_indirect=clamp_indirect,
    )


def render_comparisons(
    *, device: int = 0, output_dir: Path = DEFAULT_OUTPUT_DIR, preview: bool = False
) -> tuple[Path, ...]:
    """Render both OFF/ON pairs sequentially and return their PNG paths."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    size = PREVIEW_SIZE if preview else FORMAL_SIZE

    # The first pair differs only in maximum path depth.
    indirect = create_light_transport_renderer(device=device)
    for stem, depth in (
        ("indirect-light-off", 1),
        ("indirect-light-on", 12),
    ):
        _render(
            indirect,
            output_dir,
            stem,
            width=size,
            height=size,
            spp=16 if preview else 512,
            depth=depth,
            denoise=False,
            clamp_direct=0.0,
            clamp_indirect=0.0,
            seed=INDIRECT_SEED,
        )

    # Both images are generated from the same frozen renderer and sampling
    # sequence.  Denoising is the sole changed render option.
    denoiser = create_light_transport_renderer(device=device)
    for stem, enabled in (
        ("denoiser-off", False),
        ("denoiser-on", True),
    ):
        _render(
            denoiser,
            output_dir,
            stem,
            width=size,
            height=size,
            spp=4 if preview else 16,
            depth=12,
            denoise=enabled,
            clamp_direct=64.0,
            clamp_indirect=16.0,
            seed=DENOISER_SEED,
        )

    return tuple(
        output_dir / f"{stem}.png"
        for stem in (
            "indirect-light-off",
            "indirect-light-on",
            "denoiser-off",
            "denoiser-on",
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
