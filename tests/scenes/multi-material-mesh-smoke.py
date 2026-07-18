#!/usr/bin/env python3
"""Per-usemtl material binding smoke scene for one shared mesh GAS."""

from pathlib import Path

from spectraldock import Renderer
from spectraldock import _native


ROOT = Path(__file__).resolve().parents[2]


def _write_screen_fixture() -> Path:
    """Create a deterministic dark, saturated sRGB screen pattern."""
    output_dir = ROOT / "output/tests"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "multi-material-srgb-fixture.avif"

    size = 16
    pixels = bytearray()
    for y in range(size):
        for x in range(size):
            if x in (2, 7, 13):
                color = (3, 96, 132)
            elif y in (3, 10) or (x + y) % 11 == 0:
                color = (128, 3, 78)
            elif (x // 4 + y // 4) % 5 == 0:
                color = (104, 35, 3)
            else:
                shade = 4 + ((5 * x + 3 * y) % 7)
                color = (shade, shade + 2, shade + 5)
            pixels.extend((*color, 255))
    _native.write_texture_avif(path, size, size, bytes(pixels), True)
    return path


def create_renderer() -> Renderer:
    screen_path = _write_screen_fixture()
    renderer = Renderer()
    renderer.integrator(
        direct_light_sampling="importance", clamp_direct=0.0, clamp_indirect=0.0
    )
    renderer.camera(
        look_from=(0.0, 1.5, 5.2),
        look_at=(0.0, 0.9, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=36.0,
        aperture=0.0,
        focus_distance=5.2,
    )
    renderer.background(type="constant", color=(0.012, 0.018, 0.03))

    screen_texture = renderer.texture(
        name="screen_texture",
        type="image",
        path=screen_path,
        color_space="srgb",
    )
    red = renderer.material(
        name="red", type="lambertian", base_color=(0.82, 0.055, 0.025)
    )
    screen = renderer.material(
        name="screen", type="lambertian", texture=screen_texture
    )
    metal = renderer.material(
        name="metal",
        type="metal",
        base_color=(0.72, 0.77, 0.84),
        roughness=0.22,
    )
    floor = renderer.material(
        name="floor", type="lambertian", base_color=(0.16, 0.18, 0.22)
    )

    panels = renderer.mesh(
        name="multi_material_panels",
        path=ROOT / "tests/assets/multi-material-mesh.obj",
        materials={
            "ScreenPanel": screen,
            "MetalPanel": metal,
            "RedPanel": red,
        },
    )
    renderer.object(
        name="panels",
        type="mesh",
        mesh=panels,
        translate=(0.0, 0.12, 0.0),
    )
    renderer.object(
        name="ground",
        type="rectangle",
        p1=(-3.0, 0.0, 2.0),
        p2=(-3.0, 0.0, -2.0),
        p3=(3.0, 0.0, -2.0),
        material=floor,
    )
    renderer.light(
        name="softbox",
        type="rectangle",
        position=(-1.8, 3.2, 2.2),
        edge_u=(3.6, 0.0, 0.0),
        edge_v=(0.0, 0.0, 1.6),
        emission=(13.0, 12.0, 10.0),
    )
    return renderer


def main() -> None:
    output = ROOT / "output/tests/multi-material-mesh-smoke.avif"
    create_renderer().render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=64,
        height=64,
        spp=1,
        depth=4,
        seed=211,
        denoise=False,
    )


if __name__ == "__main__":
    main()
