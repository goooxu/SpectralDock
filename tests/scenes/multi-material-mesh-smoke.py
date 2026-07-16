#!/usr/bin/env python3
"""Per-usemtl material binding smoke scene for one shared mesh GAS."""

from pathlib import Path

from spectraldock import Renderer


ROOT = Path(__file__).resolve().parents[2]


def create_renderer() -> Renderer:
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
        path=ROOT / "assets/examples/textures/circuit-panel.png",
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
    output = ROOT / "output/tests/multi-material-mesh-smoke.png"
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
