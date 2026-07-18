#!/usr/bin/env python3
"""Neon Koi: a procedural neon line installation in a dark gallery."""

from math import hypot
from pathlib import Path

from spectraldock import Renderer


ROOT = Path(__file__).resolve().parents[1]


def _wall_segment(
    renderer: Renderer,
    name: str,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    z: float,
    width: float,
    material,
) -> None:
    """Add one slightly overlapped, camera-facing line segment."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = hypot(dx, dy)
    if not length > 0.0:
        raise ValueError(f"zero-length wall segment: {name}")
    ux = dx / length
    uy = dy / length
    half = 0.5 * width
    ax = start[0] - ux * half
    ay = start[1] - uy * half
    bx = end[0] + ux * half
    by = end[1] + uy * half
    nx = -uy * half
    ny = ux * half
    renderer.object(
        name=name,
        type="rectangle",
        p1=(ax - nx, ay - ny, z),
        p2=(ax + nx, ay + ny, z),
        p3=(bx + nx, by + ny, z),
        front_material=material,
    )


def _polyline(
    renderer: Renderer,
    prefix: str,
    points: tuple[tuple[float, float], ...],
    *,
    z: float,
    width: float,
    material,
) -> None:
    for index, (start, end) in enumerate(zip(points, points[1:])):
        _wall_segment(
            renderer,
            f"{prefix}_{index:02d}",
            start,
            end,
            z=z,
            width=width,
            material=material,
        )


def _koi_points(
    center: tuple[float, float],
    points: tuple[tuple[float, float], ...],
    *,
    mirror: float,
    scale: float,
) -> tuple[tuple[float, float], ...]:
    return tuple(
        (center[0] + mirror * scale * x, center[1] + scale * y)
        for x, y in points
    )


def _add_koi_sign(
    renderer: Renderer,
    prefix: str,
    center: tuple[float, float],
    *,
    mirror: float,
    outline,
    vermilion,
) -> None:
    scale = 1.08

    def points(
        values: tuple[tuple[float, float], ...],
    ) -> tuple[tuple[float, float], ...]:
        return _koi_points(center, values, mirror=mirror, scale=scale)

    def point(value: tuple[float, float]) -> tuple[float, float]:
        return points((value,))[0]

    left = (
        (-0.08, 1.65),
        (-0.36, 1.30),
        (-0.46, 0.55),
        (-0.30, -0.30),
        (-0.08, -1.22),
    )
    right = (
        (0.08, 1.65),
        (0.36, 1.28),
        (0.46, 0.52),
        (0.28, -0.35),
        (-0.08, -1.22),
    )
    _polyline(
        renderer,
        f"{prefix}_left_outline",
        points(((0.0, 1.78),) + left),
        z=-3.80,
        width=0.055,
        material=outline,
    )
    _polyline(
        renderer,
        f"{prefix}_right_outline",
        points(((0.0, 1.78),) + right),
        z=-3.80,
        width=0.055,
        material=outline,
    )
    for suffix, path in (
        ("tail_left", ((-0.08, -1.22), (-0.50, -1.68), (-0.02, -1.48))),
        ("tail_right", ((-0.08, -1.22), (0.46, -1.76), (0.06, -1.43))),
        ("fin_left", ((-0.43, 0.58), (-0.80, 0.22))),
        ("fin_right", ((0.43, 0.55), (0.79, 0.18))),
    ):
        _polyline(
            renderer,
            f"{prefix}_{suffix}",
            points(path),
            z=-3.80,
            width=0.055,
            material=outline,
        )

    _polyline(
        renderer,
        f"{prefix}_vermilion_spine",
        points(((0.0, 1.38), (-0.08, 0.72), (0.08, 0.02), (-0.03, -0.72))),
        z=-3.77,
        width=0.095,
        material=vermilion,
    )
    for index, (start, end) in enumerate(
        (
            ((-0.20, 0.96), (0.18, 0.78)),
            ((-0.30, 0.25), (0.28, 0.06)),
            ((-0.22, -0.48), (0.18, -0.62)),
        )
    ):
        _wall_segment(
            renderer,
            f"{prefix}_vermilion_patch_{index:02d}",
            point(start),
            point(end),
            z=-3.77,
            width=0.10,
            material=vermilion,
        )


def create_renderer() -> Renderer:
    renderer = Renderer()
    renderer.integrator(
        direct_light_sampling="importance",
        clamp_direct=64.0,
        clamp_indirect=16.0,
    )
    renderer.camera(
        look_from=(0.0, 3.1, 10.8),
        look_at=(0.0, 2.0, -2.3),
        up=(0.0, 1.0, 0.0),
        vfov=39.0,
        aperture=0.11,
        focus_distance=13.2,
    )
    renderer.background(type="constant", color=(0.001, 0.002, 0.006), exposure=-0.25)

    circuit_wall = renderer.material(
        name="circuit_wall",
        type="pbr",
        base_color=(0.012, 0.018, 0.028),
        metallic=0.55,
        roughness=0.42,
    )
    wall_panel = renderer.material(
        name="wall_panel",
        type="pbr",
        base_color=(0.026, 0.032, 0.044),
        metallic=0.72,
        roughness=0.30,
    )
    wet_floor = renderer.material(
        name="wet_floor",
        type="metal",
        base_color=(0.08, 0.11, 0.14),
        roughness=0.12,
    )
    dark_wall = renderer.material(
        name="dark_wall", type="lambertian", base_color=(0.015, 0.02, 0.03)
    )
    koi_outline = renderer.material(
        name="koi_outline", type="emitter", emission=(4.6, 3.3, 1.7)
    )
    koi_vermilion = renderer.material(
        name="koi_vermilion", type="emitter", emission=(8.5, 0.55, 0.10)
    )
    cyan_glow = renderer.material(
        name="cyan_glow", type="emitter", emission=(0.4, 8.0, 12.0)
    )
    magenta_glow = renderer.material(
        name="magenta_glow", type="emitter", emission=(11.0, 0.35, 6.8)
    )
    mascot = renderer.mesh(
        name="mascot",
        path=ROOT / "assets/examples/models/capsule-mascot/capsule-mascot.obj",
    )

    for name, p1, p2, p3, material in (
        ("floor", (-7.0, 0.0, 6.0), (-7.0, 0.0, -6.0), (7.0, 0.0, -6.0), wet_floor),
        (
            "circuit_backdrop",
            (-7.0, 0.0, -4.0),
            (-7.0, 5.5, -4.0),
            (7.0, 5.5, -4.0),
            circuit_wall,
        ),
        ("left_wall", (-7.0, 0.0, 6.0), (-7.0, 5.5, 6.0), (-7.0, 5.5, -4.0), dark_wall),
        ("right_wall", (7.0, 0.0, -4.0), (7.0, 5.5, -4.0), (7.0, 5.5, 6.0), dark_wall),
    ):
        renderer.object(name=name, type="rectangle", p1=p1, p2=p2, p3=p3, material=material)

    for name, p1, p2, p3 in (
        (
            "panel_lower_left",
            (-6.3, 0.35, -3.96),
            (-6.3, 1.55, -3.96),
            (-4.15, 1.55, -3.96),
        ),
        (
            "panel_upper_left",
            (-6.25, 3.65, -3.96),
            (-6.25, 5.10, -3.96),
            (-4.05, 5.10, -3.96),
        ),
        (
            "panel_lower_right",
            (4.05, 0.35, -3.96),
            (4.05, 1.70, -3.96),
            (6.30, 1.70, -3.96),
        ),
        (
            "panel_upper_right",
            (4.10, 3.70, -3.96),
            (4.10, 5.10, -3.96),
            (6.30, 5.10, -3.96),
        ),
    ):
        renderer.object(
            name=name,
            type="rectangle",
            p1=p1,
            p2=p2,
            p3=p3,
            material=wall_panel,
        )

    for prefix, points_, material in (
        (
            "cyan_lower_left",
            ((-6.0, 1.90), (-5.15, 1.90), (-5.15, 2.48), (-4.28, 2.48)),
            cyan_glow,
        ),
        (
            "magenta_upper_left",
            ((-6.05, 3.18), (-5.42, 3.18), (-5.42, 3.58), (-4.42, 3.58)),
            magenta_glow,
        ),
        (
            "cyan_lower_right",
            ((4.18, 2.30), (5.05, 2.30), (5.05, 1.92), (6.02, 1.92)),
            cyan_glow,
        ),
        (
            "magenta_upper_right",
            ((4.22, 3.56), (5.20, 3.56), (5.20, 3.14), (6.05, 3.14)),
            magenta_glow,
        ),
        (
            "cyan_top",
            ((-1.20, 5.02), (-0.18, 5.02), (-0.18, 4.70), (1.12, 4.70)),
            cyan_glow,
        ),
        (
            "magenta_bottom",
            (
                (-1.45, 0.48),
                (-0.62, 0.48),
                (-0.62, 0.82),
                (0.58, 0.82),
                (0.58, 0.48),
                (1.32, 0.48),
            ),
            magenta_glow,
        ),
    ):
        _polyline(
            renderer,
            prefix,
            points_,
            z=-3.91,
            width=0.045,
            material=material,
        )

    _add_koi_sign(
        renderer,
        "left_koi",
        (-2.45, 2.70),
        mirror=1.0,
        outline=koi_outline,
        vermilion=koi_vermilion,
    )
    _add_koi_sign(
        renderer,
        "right_koi",
        (2.30, 2.82),
        mirror=-1.0,
        outline=koi_outline,
        vermilion=koi_vermilion,
    )

    renderer.object(
        name="cyan_strip",
        type="rectangle",
        p1=(-6.9, 0.7, -2.5),
        p2=(-6.9, 4.6, -2.5),
        p3=(-6.9, 4.6, -1.9),
        back_material=cyan_glow,
    )
    renderer.object(
        name="magenta_strip",
        type="rectangle",
        p1=(6.9, 0.7, -1.0),
        p2=(6.9, 4.6, -1.0),
        p3=(6.9, 4.6, -1.6),
        back_material=magenta_glow,
    )
    renderer.object(
        name="metal_mascot",
        type="mesh",
        mesh=mascot,
        translate=(0.1, 0.0, 0.4),
        rotate_degrees=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
        material=wet_floor,
    )
    renderer.light(
        name="cyan_area",
        type="rectangle",
        position=(-6.8, 0.8, -2.7),
        edge_u=(0.0, 3.7, 0.0),
        edge_v=(0.0, 0.0, 2.2),
        emission=(0.5, 7.0, 11.0),
    )
    renderer.light(
        name="magenta_area",
        type="rectangle",
        position=(6.8, 0.8, 0.0),
        edge_u=(0.0, 3.7, 0.0),
        edge_v=(0.0, 0.0, -2.2),
        emission=(10.0, 0.4, 6.0),
    )
    renderer.light(
        name="soft_top",
        type="disk",
        position=(0.0, 5.3, 0.0),
        normal=(0.0, -1.0, -0.1),
        radius=1.8,
        emission=(1.0, 1.1, 1.5),
    )
    return renderer


def main() -> None:
    output = ROOT / "output/examples/neon-koi.avif"
    create_renderer().render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=1920,
        height=1080,
        spp=512,
        depth=12,
        seed=202,
        denoise=True,
    )


if __name__ == "__main__":
    main()
