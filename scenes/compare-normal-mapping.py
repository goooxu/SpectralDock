#!/usr/bin/env python3
"""Render the fixed machined-panel normal-mapping comparison pair."""

import argparse
import math
from pathlib import Path

from spectraldock import Renderer


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "output/gallery/comparisons"
PANEL_DIR = ROOT / "assets/examples/models/showcase-panel"
PANEL_OBJ = PANEL_DIR / "showcase-panel.obj"
PANEL_NORMAL = PANEL_DIR / "showcase-panel-normal.png"
PANEL_METALLIC_ROUGHNESS = (
    PANEL_DIR / "showcase-panel-metallic-roughness.png"
)
FORMAL_SIZE = 1024
PREVIEW_SIZE = 256
SEED = 3301


def nonnegative_integer(value: str) -> int:
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return result


def create_normal_mapping_renderer(
    *, normal_scale: float, device: int = 0
) -> Renderer:
    """Build the panel close-up; ``normal_scale`` is its sole variant input."""
    renderer = Renderer(device=device, scene_name="comparison-normal-mapping")
    renderer.integrator(
        direct_light_sampling="importance",
        clamp_direct=0.0,
        clamp_indirect=0.0,
    )
    renderer.camera(
        look_from=(0.18, 0.10, 4.25),
        look_at=(0.0, 0.0, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=31.0,
        aperture=0.0,
        focus_distance=4.25,
    )
    renderer.background(
        type="constant", color=(0.006, 0.008, 0.012), exposure=-0.25
    )

    normal = renderer.texture(
        name="panel-normal",
        type="image",
        path=PANEL_NORMAL,
        color_space="linear",
        wrap_u="clamp_to_edge",
        wrap_v="clamp_to_edge",
    )
    metallic_roughness = renderer.texture(
        name="panel-metallic-roughness",
        type="image",
        path=PANEL_METALLIC_ROUGHNESS,
        color_space="linear",
        wrap_u="clamp_to_edge",
        wrap_v="clamp_to_edge",
    )
    panel_material = renderer.material(
        name="machined-panel",
        type="pbr",
        base_color=(0.46, 0.60, 0.72),
        metallic=1.0,
        roughness=1.0,
        metallic_roughness_texture=metallic_roughness,
        normal_texture=normal,
        normal_scale=normal_scale,
    )
    backing = renderer.material(
        name="panel-backing",
        type="metal",
        base_color=(0.055, 0.07, 0.09),
        roughness=0.34,
    )
    surround = renderer.material(
        name="surround",
        type="lambertian",
        base_color=(0.025, 0.032, 0.042),
    )

    renderer.object(
        name="surround",
        type="rectangle",
        p1=(-3.2, -3.2, -0.12),
        p2=(3.2, -3.2, -0.12),
        p3=(3.2, 3.2, -0.12),
        material=surround,
    )
    renderer.object(
        name="backing",
        type="rectangle",
        p1=(-1.16, -1.16, -0.055),
        p2=(1.16, -1.16, -0.055),
        p3=(1.16, 1.16, -0.055),
        material=backing,
    )
    panel_mesh = renderer.mesh(name="showcase-panel", path=PANEL_OBJ)
    renderer.object(
        name="showcase-panel",
        type="mesh",
        mesh=panel_mesh,
        material=panel_material,
    )

    # A strong grazing key reveals the OpenGL/+Y tangent-space relief.  The
    # weak opposing fill preserves the dark machined fields without masking
    # the OFF/ON difference.
    renderer.light(
        name="grazing-key",
        type="directional",
        direction=(0.86, -0.22, 0.46),
        irradiance=tuple(14.0 * math.pi * value for value in (1.0, 0.88, 0.70)),
    )
    renderer.light(
        name="cool-fill",
        type="directional",
        direction=(-0.42, 0.30, 0.86),
        irradiance=tuple(1.4 * math.pi * value for value in (0.55, 0.72, 1.0)),
    )
    return renderer


def _render(
    renderer: Renderer, output_dir: Path, stem: str, *, size: int, spp: int
) -> None:
    output = output_dir / f"{stem}.png"
    renderer.render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=size,
        height=size,
        spp=spp,
        depth=8,
        seed=SEED,
        denoise=False,
        clamp_direct=0.0,
        clamp_indirect=0.0,
    )


def render_comparisons(
    *, device: int = 0, output_dir: Path = DEFAULT_OUTPUT_DIR, preview: bool = False
) -> tuple[Path, ...]:
    """Render OFF then ON, binding both linear textures in both variants."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    size = PREVIEW_SIZE if preview else FORMAL_SIZE
    spp = 16 if preview else 512
    for stem, normal_scale in (
        ("normal-mapping-off", 0.0),
        ("normal-mapping-on", 1.0),
    ):
        _render(
            create_normal_mapping_renderer(
                normal_scale=normal_scale, device=device
            ),
            output_dir,
            stem,
            size=size,
            spp=spp,
        )
    return tuple(
        output_dir / f"normal-mapping-{state}.png" for state in ("off", "on")
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
