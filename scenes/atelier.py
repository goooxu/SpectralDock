#!/usr/bin/env python3
"""Atelier: a settled PhysX still life in a cold, firelit studio."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

from spectraldock import PhysicsResult, PhysicsWorld, Renderer


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "output/gallery"
FORMAL_WIDTH = 2560
FORMAL_HEIGHT = 1440
FORMAL_SPP = 1024
FORMAL_DEPTH = 12
PREVIEW_WIDTH = 640
PREVIEW_HEIGHT = 360
PREVIEW_SPP = 16
PREVIEW_DEPTH = 8
SEED = 20260717
FIXED_DT = 1.0 / 120.0
STEPS = 480

_BASIN_X = (2.55, 6.85)
_BASIN_Z = (0.35, 4.30)


def _length(value: tuple[float, ...]) -> float:
    return math.sqrt(sum(component * component for component in value))


def _add(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return a[0] + b[0], a[1] + b[1], a[2] + b[2]


def _rotate(quaternion: tuple[float, ...], point: tuple[float, ...]) -> tuple[float, float, float]:
    """Rotate a point by an xyzw quaternion without adding a scene dependency."""
    x, y, z, w = quaternion
    px, py, pz = point
    tx = 2.0 * (y * pz - z * py)
    ty = 2.0 * (z * px - x * pz)
    tz = 2.0 * (x * py - y * px)
    return (
        px + w * tx + y * tz - z * ty,
        py + w * ty + z * tx - x * tz,
        pz + w * tz + x * ty - y * tx,
    )


def _quat_degrees(angle: float, axis: tuple[float, ...]) -> tuple[float, float, float, float]:
    length = _length(axis)
    if length <= 1.0e-12:
        raise ValueError("quaternion axis must not be zero")
    sine = math.sin(math.radians(angle) * 0.5) / length
    return (
        axis[0] * sine,
        axis[1] * sine,
        axis[2] * sine,
        math.cos(math.radians(angle) * 0.5),
    )


def _quaternion_to_euler_degrees(
    quaternion: tuple[float, ...],
) -> tuple[float, float, float]:
    """Return XYZ angles for the renderer's ``Rz * Ry * Rx`` convention."""
    x, y, z, w = quaternion
    roll = math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
    sin_pitch = max(-1.0, min(1.0, 2.0 * (w * y - z * x)))
    pitch = math.asin(sin_pitch)
    yaw = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
    return tuple(math.degrees(value) for value in (roll, pitch, yaw))  # type: ignore[return-value]


def create_physics_world(*, device: int = 0) -> PhysicsWorld:
    """Create the deterministic four-second settling capture."""
    return PhysicsWorld(
        device=device,
        seed=SEED,
        fixed_dt=FIXED_DT,
        steps=STEPS,
        gravity=(0.0, -9.81, 0.0),
        scene_name="atelier",
    )


def _validate(result: PhysicsResult) -> bool:
    """Accept only a quiet, bounded arrangement outside the open water basin."""
    expected = {
        "brick": 9,
        "metal_ball": 1,
        "frosted_ball": 1,
        "capsule": 1,
        "spot": 1,
        "sparky": 1,
    }
    counts = {category: 0 for category in expected}
    if len(result.bodies) != 14:
        return False

    fallen = 0
    quiet = 0
    sleeping = 0
    for body in result.bodies:
        if body.category not in counts:
            return False
        counts[body.category] += 1
        x, y, z = body.position
        if not (-7.20 <= x <= 7.20 and -0.05 <= y <= 6.50 and -6.15 <= z <= 4.85):
            return False
        if _BASIN_X[0] <= x <= _BASIN_X[1] and _BASIN_Z[0] <= z <= _BASIN_Z[1]:
            return False
        if body.initial_position[1] - y >= 0.55:
            fallen += 1
        if _length(body.linear_velocity) <= 0.15 and _length(body.angular_velocity) <= 0.30:
            quiet += 1
        if body.sleeping:
            sleeping += 1

    return counts == expected and fallen >= 12 and quiet >= 12 and sleeping >= 8


def _attach_box_faces(
    body: Any,
    prefix: str,
    half_extents: tuple[float, float, float],
    material: Any,
) -> None:
    x, y, z = half_extents
    faces = (
        ((-x, -y, z), (-x, y, z), (x, y, z)),
        ((x, -y, -z), (x, y, -z), (-x, y, -z)),
        ((x, -y, z), (x, y, z), (x, y, -z)),
        ((-x, -y, -z), (-x, y, -z), (-x, y, z)),
        ((-x, y, z), (-x, y, -z), (x, y, -z)),
        ((-x, -y, -z), (-x, -y, z), (x, -y, z)),
    )
    for index, (p1, p2, p3) in enumerate(faces):
        body.attach_rectangle(f"{prefix}_face_{index}", p1, p2, p3, material)


def _populate_physics(world: PhysicsWorld, materials: dict[str, Any]) -> None:
    floor_contact = world.material(
        "atelier_floor_contact",
        static_friction=0.82,
        dynamic_friction=0.70,
        restitution=0.025,
    )
    object_contact = world.material(
        "atelier_object_contact",
        static_friction=0.68,
        dynamic_friction=0.58,
        restitution=0.035,
    )
    ball_contact = world.material(
        "atelier_ball_contact",
        static_friction=0.72,
        dynamic_friction=0.62,
        restitution=0.045,
    )

    world.static_plane("studio_floor_collision", material=floor_contact)
    for name, position, extents in (
        ("left_wall_collision", (-7.45, 2.5, -0.65), (0.15, 2.5, 5.75)),
        ("right_wall_collision", (7.45, 2.5, -0.65), (0.15, 2.5, 5.75)),
        ("back_wall_collision", (0.0, 2.5, -6.25), (7.45, 2.5, 0.15)),
        ("front_guard_collision", (0.0, 1.0, 4.95), (7.45, 1.0, 0.15)),
        ("basin_left_collision", (2.70, 0.55, 2.35), (0.16, 0.55, 1.95)),
        ("basin_right_collision", (6.70, 0.55, 2.35), (0.16, 0.55, 1.95)),
        ("basin_back_collision", (4.70, 0.55, 0.50), (2.15, 0.55, 0.16)),
        ("basin_front_collision", (4.70, 0.55, 4.20), (2.15, 0.55, 0.16)),
    ):
        world.static_box(name, position=position, half_extents=extents, material=floor_contact)

    brick_extents = (0.54, 0.18, 0.37)
    brick_materials = (
        "brick_coral",
        "brick_saffron",
        "brick_lime",
        "brick_teal",
        "brick_cobalt",
        "brick_lilac",
        "brick_rose",
        "brick_mint",
        "brick_ivory",
    )
    brick_positions = (
        (-2.35, 2.15, -2.95),
        (-0.85, 2.72, -2.85),
        (0.75, 2.30, -2.95),
        (-2.10, 3.32, -1.55),
        (-0.45, 2.18, -1.45),
        (1.35, 3.00, -1.50),
        (-1.95, 2.52, -0.05),
        (-0.20, 3.45, 0.00),
        (1.55, 2.42, -0.10),
    )
    yaw_angles = (-18.0, 11.0, 26.0, 8.0, -29.0, 17.0, -7.0, 32.0, -15.0)
    for index, (position, yaw, material_name) in enumerate(
        zip(brick_positions, yaw_angles, brick_materials)
    ):
        body = world.rigid_body(
            f"brick_body_{index:02d}",
            category="brick",
            position=position,
            rotation=_quat_degrees(yaw, (0.0, 1.0, 0.0)),
            density=1.25,
            linear_damping=0.32,
            angular_damping=0.52,
            sleep_threshold=0.085,
            solver_iterations=(12, 4),
        )
        body.box(brick_extents, object_contact)
        _attach_box_faces(body, f"brick_{index:02d}", brick_extents, materials[material_name])

    for body_name, category, position, radius, density, material_name in (
        ("metal_ball_body", "metal_ball", (-3.10, 4.15, 0.95), 0.52, 5.8, "polished_ball"),
        ("frosted_ball_body", "frosted_ball", (0.55, 3.80, 1.65), 0.60, 1.65, "frosted_glass"),
    ):
        body = world.rigid_body(
            body_name,
            category=category,
            position=position,
            density=density,
            linear_damping=0.48,
            angular_damping=0.72,
            sleep_threshold=0.11,
            solver_iterations=(12, 4),
        )
        body.sphere(radius, ball_contact)
        body.attach_sphere(body_name.removesuffix("_body"), (0.0, 0.0, 0.0), radius, materials[material_name])

    # Character meshes keep their authored material slots.  Their simple proxy
    # bodies therefore have no render attachment; create_renderer applies each
    # returned BodyState pose to a mapped mesh instance after simulation.
    capsule = world.rigid_body(
        "capsule_body",
        category="capsule",
        position=(-4.65, 3.25, -0.55),
        rotation=_quat_degrees(18.0, (0.0, 1.0, 0.0)),
        density=2.2,
        linear_damping=0.38,
        angular_damping=0.58,
        sleep_threshold=0.09,
        solver_iterations=(14, 4),
    )
    capsule.box((0.52, 0.92, 0.42), object_contact)

    spot = world.rigid_body(
        "spot_body",
        category="spot",
        position=(2.75, 2.80, -2.55),
        rotation=_quat_degrees(-24.0, (0.0, 1.0, 0.0)),
        density=1.65,
        linear_damping=0.42,
        angular_damping=0.62,
        sleep_threshold=0.10,
        solver_iterations=(14, 4),
    )
    spot.box((0.78, 0.48, 0.52), object_contact)

    sparky = world.rigid_body(
        "sparky_body",
        category="sparky",
        position=(4.40, 3.45, -2.60),
        rotation=_quat_degrees(-20.0, (0.0, 1.0, 0.0)),
        density=2.7,
        linear_damping=0.40,
        angular_damping=0.62,
        sleep_threshold=0.10,
        solver_iterations=(14, 4),
    )
    sparky.box((0.66, 0.92, 0.58), object_contact)


def _capsule_materials(renderer: Renderer) -> dict[str, Any]:
    yellow = renderer.material(
        name="atelier_capsule_yellow",
        type="pbr",
        base_color=(0.96, 0.70, 0.06),
        metallic=0.0,
        roughness=0.25,
    )
    visor = renderer.material(
        name="atelier_capsule_visor",
        type="pbr",
        base_color=(0.035, 0.075, 0.13),
        metallic=0.28,
        roughness=0.10,
    )
    eye = renderer.material(
        name="atelier_capsule_eye",
        type="pbr",
        base_color=(0.94, 0.98, 1.0),
        metallic=0.0,
        roughness=0.13,
    )
    navy = renderer.material(
        name="atelier_capsule_navy",
        type="pbr",
        base_color=(0.025, 0.08, 0.19),
        metallic=0.82,
        roughness=0.30,
    )
    rubber = renderer.material(
        name="atelier_capsule_rubber",
        type="pbr",
        base_color=(0.13, 0.045, 0.018),
        metallic=0.0,
        roughness=0.76,
    )
    antenna = renderer.material(
        name="atelier_capsule_antenna",
        type="pbr",
        base_color=(0.50, 0.54, 0.60),
        metallic=0.92,
        roughness=0.20,
    )
    tip = renderer.material(
        name="atelier_capsule_tip",
        type="pbr",
        base_color=(1.0, 0.66, 0.035),
        metallic=0.16,
        roughness=0.17,
    )
    return {
        "mascot_torso": yellow,
        "mascot_arm_left": yellow,
        "mascot_arm_right": yellow,
        "mascot_leg_left": yellow,
        "mascot_leg_right": yellow,
        "mascot_visor": visor,
        "mascot_eye_left": eye,
        "mascot_eye_right": eye,
        "mascot_belt_flange": navy,
        "mascot_glove_left": rubber,
        "mascot_glove_right": rubber,
        "mascot_boot_left": rubber,
        "mascot_boot_right": rubber,
        "mascot_antenna_stem": antenna,
        "mascot_antenna_tip": tip,
    }


def _sparky_materials(renderer: Renderer, screen_texture: Any) -> dict[str, Any]:
    screen = renderer.material(
        name="atelier_sparky_screen",
        type="emitter",
        texture=screen_texture,
        emission=(1.2, 3.6, 5.8),
    )
    return {
        "AccentOrange": renderer.material(
            name="atelier_sparky_orange", type="pbr",
            base_color=(0.96, 0.25, 0.035), metallic=0.0, roughness=0.30,
        ),
        "EmitYellow": renderer.material(
            name="atelier_sparky_yellow", type="pbr",
            base_color=(1.0, 0.76, 0.055), metallic=0.0, roughness=0.22,
        ),
        # A glossy PBR shell is the nearest safe appearance while the scene's
        # single actual dielectric medium is the analytical water basin.
        "GlassHead": renderer.material(
            name="atelier_sparky_glossy_head", type="pbr",
            base_color=(0.20, 0.48, 0.73), metallic=0.08, roughness=0.09,
        ),
        "MetalGrey": renderer.material(
            name="atelier_sparky_metal", type="pbr",
            base_color=(0.34, 0.39, 0.46), metallic=0.90, roughness=0.29,
        ),
        "PlasticBlue": renderer.material(
            name="atelier_sparky_blue", type="pbr",
            base_color=(0.08, 0.37, 0.70), metallic=0.0, roughness=0.33,
        ),
        "PlasticWhite": renderer.material(
            name="atelier_sparky_white", type="pbr",
            base_color=(0.88, 0.92, 0.96), metallic=0.0, roughness=0.30,
        ),
        "ScreenChest": screen,
        "ScreenFace": screen,
        "ScreenPalm": screen,
        "TreadOrange": renderer.material(
            name="atelier_sparky_tread", type="pbr",
            base_color=(0.80, 0.16, 0.02), metallic=0.0, roughness=0.66,
        ),
    }


def _rectangle(
    renderer: Renderer,
    name: str,
    p1: tuple[float, ...],
    p2: tuple[float, ...],
    p3: tuple[float, ...],
    material: Any,
) -> Any:
    return renderer.object(name=name, type="rectangle", p1=p1, p2=p2, p3=p3, material=material)


def _cylinder(
    renderer: Renderer,
    name: str,
    base: tuple[float, ...],
    axis: tuple[float, ...],
    height: float,
    radius: float,
    material: Any,
) -> Any:
    return renderer.object(
        name=name,
        type="cylinder",
        base=base,
        axis=axis,
        height=height,
        radius=radius,
        material=material,
    )


def _add_static_studio(renderer: Renderer, materials: dict[str, Any]) -> None:
    # The floor is split around the recessed water basin so camera paths can
    # travel through the analytical surface to the submerged tile floor.
    for name, p1, p2, p3, material_name in (
        ("studio_floor_rear", (-7.5, 0.0, 0.50), (-7.5, 0.0, -6.35), (7.5, 0.0, -6.35), "floor"),
        ("studio_floor_front_left", (-7.5, 0.0, 4.90), (-7.5, 0.0, 0.50), (2.70, 0.0, 0.50), "floor"),
        ("studio_floor_front_right", (6.70, 0.0, 0.50), (6.70, 0.0, 4.90), (7.5, 0.0, 4.90), "floor"),
        ("studio_floor_front_strip", (2.70, 0.0, 4.90), (2.70, 0.0, 4.20), (6.70, 0.0, 4.20), "floor"),
        ("studio_back_wall", (-7.5, 0.0, -6.35), (-7.5, 7.0, -6.35), (7.5, 7.0, -6.35), "wall"),
        ("studio_left_wall", (-7.5, 0.0, 4.90), (-7.5, 7.0, 4.90), (-7.5, 7.0, -6.35), "wall"),
        ("basin_floor", (2.70, -1.05, 4.20), (2.70, -1.05, 0.50), (6.70, -1.05, 0.50), "pool_tile"),
        ("basin_left_wall", (2.70, -1.05, 0.50), (2.70, 0.52, 0.50), (2.70, 0.52, 4.20), "pool_rim"),
        ("basin_right_wall", (6.70, -1.05, 4.20), (6.70, 0.52, 4.20), (6.70, 0.52, 0.50), "pool_rim"),
        ("basin_back_wall", (2.70, -1.05, 0.50), (2.70, 0.52, 0.50), (6.70, 0.52, 0.50), "pool_rim"),
        ("basin_front_wall", (6.70, -1.05, 4.20), (6.70, 0.52, 4.20), (2.70, 0.52, 4.20), "pool_rim"),
    ):
        _rectangle(renderer, name, p1, p2, p3, materials[material_name])

    renderer.object(
        name="atelier_basin_water",
        type="water_surface",
        center=(4.70, 0.31, 2.35),
        size=(4.0, 3.70),
        material=materials["water"],
        waves=(
            {"direction": (1.0, 0.18), "amplitude": 0.030, "wavelength": 2.40, "phase_radians": 0.45},
            {"direction": (-0.35, 1.0), "amplitude": 0.012, "wavelength": 1.50, "phase_radians": 2.10},
            {"direction": (0.70, 1.0), "amplitude": 0.004, "wavelength": 0.85, "phase_radians": 4.25},
        ),
    )
    for index, center in enumerate(((3.55, -0.62, 1.35), (4.75, -0.72, 2.45), (5.85, -0.66, 3.25))):
        renderer.object(
            name=f"submerged_study_{index:02d}",
            type="sphere",
            center=center,
            radius=0.24 + 0.05 * index,
            material=materials["submerged_ceramic" if index != 1 else "submerged_copper"],
        )

    # Shelves and frames establish a cool working studio rather than a bare
    # simulation box.
    for index, y in enumerate((2.15, 3.40, 4.65)):
        _cylinder(
            renderer,
            f"left_shelf_{index:02d}",
            (-6.95, y, -2.95),
            (1.0, 0.0, 0.0),
            3.05,
            0.075,
            materials["dark_metal"],
        )
    for index, x in enumerate((-6.85, -4.05)):
        _cylinder(
            renderer,
            f"shelf_upright_{index:02d}",
            (x, 0.0, -2.95),
            (0.0, 1.0, 0.0),
            5.05,
            0.085,
            materials["dark_metal"],
        )
    for index, (x, y, radius, material_name) in enumerate(
        ((-6.20, 2.30, 0.20, "brick_coral"), (-5.45, 3.56, 0.24, "brick_teal"), (-4.60, 4.82, 0.18, "brick_saffron"))
    ):
        renderer.object(
            name=f"shelf_pigment_jar_{index:02d}",
            type="sphere",
            center=(x, y, -3.02),
            radius=radius,
            material=materials[material_name],
        )

    # Fireplace at left rear: procedural flame supplies both visible volume
    # and warm contrast against the blue HDR/area-light studio.
    for index, x in enumerate((-6.20, -4.45)):
        _cylinder(
            renderer,
            f"fireplace_pillar_{index:02d}",
            (x, 0.0, -5.82),
            (0.0, 1.0, 0.0),
            2.35,
            0.34,
            materials["fireplace_stone"],
        )
    _cylinder(
        renderer,
        "fireplace_lintel",
        (-6.20, 2.10, -5.82),
        (1.0, 0.0, 0.0),
        1.75,
        0.34,
        materials["fireplace_stone"],
    )
    _cylinder(
        renderer,
        "fireplace_bowl",
        (-5.33, 0.16, -5.50),
        (0.0, 1.0, 0.0),
        0.20,
        0.76,
        materials["hearth_metal"],
    )
    renderer.object(
        name="fireplace_bowl_cap",
        type="disk",
        center=(-5.33, 0.36, -5.50),
        normal=(0.0, 1.0, 0.0),
        radius=0.76,
        material=materials["ember_bed"],
    )

    for index, (base, axis, height) in enumerate(
        (
            ((-3.25, 0.0, -5.65), (0.05, 1.0, 0.0), 3.4),
            ((3.70, 0.0, -5.90), (-0.04, 1.0, 0.02), 4.1),
            ((6.85, 0.0, -3.25), (0.0, 1.0, -0.04), 3.0),
        )
    ):
        _cylinder(
            renderer,
            f"studio_pipe_{index:02d}",
            base,
            axis,
            height,
            0.095,
            materials["rough_copper"],
        )

    # A small group of lidded workshop cans and loose silver bearings fills
    # the quiet right wall without competing with the PhysX hero objects.
    for index, (x, z, height, radius, material_name) in enumerate(
        (
            (5.55, -4.92, 1.05, 0.34, "dark_metal"),
            (6.35, -4.74, 0.78, 0.29, "rough_copper"),
        )
    ):
        _cylinder(
            renderer,
            f"workshop_can_{index:02d}",
            (x, 0.0, z),
            (0.0, 1.0, 0.0),
            height,
            radius,
            materials[material_name],
        )
        renderer.object(
            name=f"workshop_can_lid_{index:02d}",
            type="disk",
            center=(x, height, z),
            normal=(0.0, 1.0, 0.0),
            radius=radius,
            material=materials[material_name],
        )
    for index, (center, radius) in enumerate(
        (
            ((5.00, 0.17, -4.72), 0.17),
            ((5.34, 0.12, -4.42), 0.12),
            ((6.82, 0.15, -4.56), 0.15),
        )
    ):
        renderer.object(
            name=f"wall_silver_bearing_{index:02d}",
            type="sphere",
            center=center,
            radius=radius,
            material=materials["polished_ball"],
        )


def _add_lights(renderer: Renderer, materials: dict[str, Any]) -> None:
    ceiling = renderer.object(
        name="atelier_overhead_emitter",
        type="rectangle",
        p1=(-3.40, 6.15, -0.95),
        p2=(3.40, 6.15, -0.95),
        p3=(3.40, 6.15, 0.85),
        front_material=materials["ceiling_emitter"],
        back_material=materials["ceiling_emitter"],
    )
    renderer.light(
        name="atelier_overhead_key",
        type="rectangle",
        object=ceiling,
        position=(-3.40, 6.15, -0.95),
        edge_u=(0.0, 0.0, 1.80),
        edge_v=(6.80, 0.0, 0.0),
        emission=(8.5, 11.5, 15.5),
    )
    # Finite disks are the renderer's closest supported substitute for focused
    # spotlights; their size keeps the local shadows visibly soft.
    renderer.light(
        name="left_focus_disk",
        type="disk",
        position=(-5.85, 4.85, 1.90),
        normal=(0.64, -0.69, -0.34),
        radius=0.72,
        emission=(9.0, 12.5, 17.0),
    )
    renderer.light(
        name="right_focus_disk",
        type="disk",
        position=(6.60, 4.30, -2.10),
        normal=(-0.82, -0.54, 0.18),
        radius=0.82,
        emission=(7.5, 5.0, 3.0),
    )
    renderer.light(
        name="atelier_fireplace_flame",
        type="flame",
        position=(-5.33, 0.40, -5.50),
        axis=(-0.05, 1.0, 0.03),
        height=1.72,
        radius_start=0.54,
        radius_end=0.11,
        emission_start=(22.0, 5.2, 0.55),
        emission_end=(4.0, 0.42, 0.035),
        extinction=0.90,
        density_scale=1.02,
        turbulence=0.52,
        noise_scale=2.50,
        seed=SEED & 0xFFFFFFFF,
    )


def _add_body_mesh(
    renderer: Renderer,
    result: PhysicsResult,
    *,
    body_name: str,
    object_name: str,
    mesh: Any,
    local_translate: tuple[float, float, float],
    scale: tuple[float, float, float],
    material: Any | None = None,
) -> None:
    state = result.body(body_name)
    parameters: dict[str, Any] = {
        "name": object_name,
        "type": "mesh",
        "mesh": mesh,
        "translate": _add(state.position, _rotate(state.rotation, local_translate)),
        "rotate_degrees": _quaternion_to_euler_degrees(state.rotation),
        "scale": scale,
    }
    if material is not None:
        parameters["material"] = material
    renderer.object(**parameters)


def create_renderer(
    physics: PhysicsWorld,
    *,
    metadata_output: Path | None = None,
    verify: bool = False,
) -> Renderer:
    """Build Atelier and capture the requested world's settled PhysX state."""
    if (
        physics.scene_name != "atelier"
        or physics.seed != SEED
        or physics.steps != STEPS
        or physics.gravity != (0.0, -9.81, 0.0)
        or not math.isclose(physics.fixed_dt, FIXED_DT, rel_tol=0.0, abs_tol=1.0e-12)
    ):
        raise ValueError("physics must come from create_physics_world()")

    renderer = Renderer(device=physics.device, scene_name="atelier")
    renderer.integrator(
        direct_light_sampling="importance",
        clamp_direct=64.0,
        clamp_indirect=16.0,
    )
    renderer.camera(
        look_from=(9.15, 5.45, 13.25),
        look_at=(-0.05, 1.12, -0.65),
        up=(0.0, 1.0, 0.0),
        vfov=32.0,
        aperture=0.026,
        focus_distance=17.25,
    )
    renderer.background(
        type="environment",
        path=ROOT / "assets/examples/environments/radiance-pavilion.hdr",
        intensity=0.42,
        rotation_degrees=232.0,
        exposure=-0.42,
    )

    sparky_screen = renderer.texture(
        name="atelier_sparky_screen_atlas",
        type="image",
        path=ROOT / "assets/examples/models/sparky/sparky_albedo.avif",
        color_space="srgb",
    )
    spot_albedo = renderer.texture(
        name="atelier_spot_albedo",
        type="image",
        path=ROOT / "assets/examples/models/spot/spot_texture.avif",
        color_space="srgb",
        wrap_u="repeat",
        wrap_v="repeat",
    )

    definitions = (
        ("floor", "pbr", {"base_color": (0.11, 0.14, 0.18), "metallic": 0.16, "roughness": 0.62}),
        ("wall", "lambertian", {"base_color": (0.15, 0.19, 0.25)}),
        ("dark_metal", "pbr", {"base_color": (0.035, 0.055, 0.075), "metallic": 0.88, "roughness": 0.34}),
        ("rough_copper", "metal", {"base_color": (0.56, 0.21, 0.065), "roughness": 0.42}),
        ("fireplace_stone", "lambertian", {"base_color": (0.18, 0.15, 0.15)}),
        ("hearth_metal", "metal", {"base_color": (0.22, 0.17, 0.14), "roughness": 0.48}),
        ("ember_bed", "emitter", {"emission": (5.5, 0.75, 0.055)}),
        ("pool_tile", "pbr", {"base_color": (0.025, 0.14, 0.18), "metallic": 0.08, "roughness": 0.50}),
        ("pool_rim", "pbr", {"base_color": (0.20, 0.25, 0.28), "metallic": 0.24, "roughness": 0.38}),
        ("water", "water", {"roughness": 0.060, "ior": 1.333, "absorption": (0.48, 0.095, 0.028)}),
        ("submerged_ceramic", "pbr", {"base_color": (0.76, 0.84, 0.88), "metallic": 0.0, "roughness": 0.22}),
        ("submerged_copper", "metal", {"base_color": (0.74, 0.28, 0.07), "roughness": 0.24}),
        ("brick_coral", "pbr", {"base_color": (0.94, 0.19, 0.12), "metallic": 0.0, "roughness": 0.30}),
        ("brick_saffron", "pbr", {"base_color": (1.0, 0.60, 0.045), "metallic": 0.0, "roughness": 0.27}),
        ("brick_lime", "pbr", {"base_color": (0.55, 0.82, 0.075), "metallic": 0.0, "roughness": 0.32}),
        ("brick_teal", "pbr", {"base_color": (0.025, 0.64, 0.61), "metallic": 0.0, "roughness": 0.25}),
        ("brick_cobalt", "pbr", {"base_color": (0.055, 0.25, 0.85), "metallic": 0.0, "roughness": 0.24}),
        ("brick_lilac", "pbr", {"base_color": (0.58, 0.27, 0.86), "metallic": 0.0, "roughness": 0.30}),
        ("brick_rose", "pbr", {"base_color": (0.94, 0.25, 0.51), "metallic": 0.0, "roughness": 0.29}),
        ("brick_mint", "pbr", {"base_color": (0.25, 0.86, 0.58), "metallic": 0.0, "roughness": 0.31}),
        ("brick_ivory", "pbr", {"base_color": (0.91, 0.86, 0.72), "metallic": 0.0, "roughness": 0.35}),
        ("polished_ball", "metal", {"base_color": (0.90, 0.94, 0.98), "roughness": 0.055}),
        # A high-roughness PBR sphere is the closest medium-safe frosted
        # appearance in a scene that also contains an open analytical water
        # boundary.  It is intentionally opaque and does not enter the strict
        # dielectric/water medium stack.
        ("frosted_glass", "pbr", {"base_color": (0.61, 0.79, 0.88), "metallic": 0.08, "roughness": 0.47}),
        ("ceiling_emitter", "emitter", {"emission": (8.5, 11.5, 15.5)}),
    )
    materials = {
        name: renderer.material(name=f"atelier_{name}", type=kind, **parameters)
        for name, kind, parameters in definitions
    }

    capsule_mesh = renderer.mesh(
        name="atelier_capsule_mesh",
        path=ROOT / "assets/examples/models/capsule-mascot/capsule-mascot.obj",
        materials=_capsule_materials(renderer),
    )
    sparky_mesh = renderer.mesh(
        name="atelier_sparky_mesh",
        path=ROOT / "assets/examples/models/sparky/sparky.obj",
        materials=_sparky_materials(renderer, sparky_screen),
    )
    spot_mesh = renderer.mesh(
        name="atelier_spot_mesh",
        path=ROOT / "assets/examples/models/spot/spot_triangulated.obj",
    )
    spot_material = renderer.material(
        name="atelier_spot_coat",
        type="pbr",
        base_color_texture=spot_albedo,
        base_color=(1.0, 1.0, 1.0),
        metallic=0.0,
        roughness=0.50,
    )

    _add_static_studio(renderer, materials)
    _populate_physics(physics, materials)
    result = physics.simulate(
        metadata_output=metadata_output,
        verify=verify,
        validator=_validate,
    )
    result.apply_to(renderer)

    _add_body_mesh(
        renderer,
        result,
        body_name="capsule_body",
        object_name="capsule_settled",
        mesh=capsule_mesh,
        local_translate=(0.0, -0.92, 0.0),
        scale=(0.80, 0.80, 0.80),
    )
    _add_body_mesh(
        renderer,
        result,
        body_name="spot_body",
        object_name="spot_settled",
        mesh=spot_mesh,
        local_translate=(0.0, 0.20, -0.55),
        scale=(1.35, 1.35, 1.35),
        material=spot_material,
    )
    _add_body_mesh(
        renderer,
        result,
        body_name="sparky_body",
        object_name="sparky_settled",
        mesh=sparky_mesh,
        local_translate=(0.0, -0.92, 0.0),
        scale=(0.72, 0.72, 0.72),
    )
    _add_lights(renderer, materials)
    return renderer


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", type=int, default=0, help="CUDA device index")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="directory for the HDR AVIF and temporary validation sidecars",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="render a fast 640x360 composition preview",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "atelier.avif"
    if args.preview:
        width, height, spp, depth = PREVIEW_WIDTH, PREVIEW_HEIGHT, PREVIEW_SPP, PREVIEW_DEPTH
    else:
        width, height, spp, depth = FORMAL_WIDTH, FORMAL_HEIGHT, FORMAL_SPP, FORMAL_DEPTH

    physics = create_physics_world(device=args.device)
    renderer = create_renderer(
        physics,
        metadata_output=output.with_suffix(".physics.json"),
        verify=True,
    )
    renderer.render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=width,
        height=height,
        spp=spp,
        depth=depth,
        seed=SEED,
        denoise=True,
    )


if __name__ == "__main__":
    main()
