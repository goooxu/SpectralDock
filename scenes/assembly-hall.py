#!/usr/bin/env python3
"""Assembly Hall: a sunlit PhysX toy-factory cover scene."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any, Sequence

from spectraldock import PhysicsResult, PhysicsWorld, Renderer
from spectraldock.physics import BodyState


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "output/gallery"
ENVIRONMENT = ROOT / "assets/examples/environments/assembly-hall-noon.hdr"
GEAR_ALPHA = ROOT / "assets/examples/textures/assembly-hall-gear-alpha.avif"

FORMAL_WIDTH = 2560
FORMAL_HEIGHT = 1440
FORMAL_SPP = 2048
FORMAL_DEPTH = 12
PREVIEW_WIDTH = 640
PREVIEW_HEIGHT = 360
PREVIEW_SPP = 16
PREVIEW_DEPTH = 8

SEED = 20260718
FIXED_DT = 1.0 / 120.0
STEPS = 36
SPOT_COUNT = 12
HALL_X = (-10.5, 10.5)
HALL_Y = (-0.25, 11.5)
HALL_Z = (-8.8, 7.5)


def _length(value: Sequence[float]) -> float:
    return math.sqrt(sum(component * component for component in value))


def _quat_degrees(
    angle_degrees: float, axis: Sequence[float]
) -> tuple[float, float, float, float]:
    length = _length(axis)
    if length <= 1.0e-12:
        raise ValueError("rotation axis must not be zero")
    sine = math.sin(math.radians(angle_degrees) * 0.5) / length
    return (
        axis[0] * sine,
        axis[1] * sine,
        axis[2] * sine,
        math.cos(math.radians(angle_degrees) * 0.5),
    )


def _quat_multiply(
    first: Sequence[float], second: Sequence[float]
) -> tuple[float, float, float, float]:
    ax, ay, az, aw = first
    bx, by, bz, bw = second
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def _rotate(
    quaternion: Sequence[float], point: Sequence[float]
) -> tuple[float, float, float]:
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


def _transform(
    position: Sequence[float],
    rotation: Sequence[float],
    point: Sequence[float],
) -> tuple[float, float, float]:
    rotated = _rotate(rotation, point)
    return tuple(position[index] + rotated[index] for index in range(3))  # type: ignore[return-value]


def _euler_degrees(quaternion: Sequence[float]) -> tuple[float, float, float]:
    """Match the worker's Rz * Ry * Rx quaternion-to-Euler conversion."""
    length = _length(quaternion)
    x, y, z, w = (component / length for component in quaternion)
    m00 = 1.0 - 2.0 * (y * y + z * z)
    m10 = 2.0 * (x * y + z * w)
    m20 = 2.0 * (x * z - y * w)
    m11 = 1.0 - 2.0 * (x * x + z * z)
    m21 = 2.0 * (y * z + x * w)
    m12 = 2.0 * (y * z - x * w)
    m22 = 1.0 - 2.0 * (x * x + y * y)
    angle_y = math.asin(max(-1.0, min(1.0, -m20)))
    if abs(math.cos(angle_y)) > 1.0e-6:
        angle_x = math.atan2(m21, m22)
        angle_z = math.atan2(m10, m00)
    else:
        angle_x = math.atan2(-m12, m11)
        angle_z = 0.0
    scale = 180.0 / math.pi
    return angle_x * scale, angle_y * scale, angle_z * scale


def _apply_body_mesh(
    renderer: Any,
    state: BodyState,
    *,
    name: str,
    mesh: Any,
    scale: Sequence[float],
    local_translate: Sequence[float] = (0.0, 0.0, 0.0),
    local_rotation: Sequence[float] = (0.0, 0.0, 0.0, 1.0),
    material: Any | None = None,
) -> Any:
    """Apply one BodyState pose without flattening mapped mesh materials."""
    translate = _transform(state.position, state.rotation, local_translate)
    rotation = _quat_multiply(state.rotation, local_rotation)
    parameters: dict[str, Any] = {
        "name": name,
        "type": "mesh",
        "mesh": mesh,
        "translate": translate,
        "rotate_degrees": _euler_degrees(rotation),
        "scale": tuple(scale),
    }
    # Material-mapped meshes reject and do not need a per-instance override.
    if material is not None:
        parameters["material"] = material
    return renderer.object(**parameters)


def create_physics_world(*, device: int = 0) -> PhysicsWorld:
    return PhysicsWorld(
        device=device,
        seed=SEED,
        fixed_dt=FIXED_DT,
        steps=STEPS,
        gravity=(0.0, -9.81, 0.0),
        scene_name="assembly-hall",
    )


def _validate(result: PhysicsResult) -> bool:
    spots = [body for body in result.bodies if body.category == "spot"]
    if len(result.bodies) != SPOT_COUNT or len(spots) != SPOT_COUNT:
        return False

    airborne = 0
    moved_and_awake = 0
    for body in spots:
        x, y, z = body.position
        if not (
            HALL_X[0] <= x <= HALL_X[1]
            and HALL_Y[0] <= y <= HALL_Y[1]
            and HALL_Z[0] <= z <= HALL_Z[1]
        ):
            return False
        displacement = tuple(
            body.position[index] - body.initial_position[index]
            for index in range(3)
        )
        if y - 0.55 > 0.35:
            airborne += 1
        if _length(displacement) >= 0.08 and not body.sleeping:
            moved_and_awake += 1
    return airborne >= 8 and moved_and_awake >= 6


def _populate_physics(world: PhysicsWorld) -> None:
    painted_steel = world.material(
        "painted_steel_contact",
        static_friction=0.58,
        dynamic_friction=0.46,
        restitution=0.08,
    )
    toy_contact = world.material(
        "toy_contact",
        static_friction=0.44,
        dynamic_friction=0.35,
        restitution=0.18,
    )
    world.static_plane("assembly_floor_collision", material=painted_steel)
    for name, position, extents in (
        ("left_hall_collision", (-10.65, 5.5, -0.65), (0.15, 5.5, 8.15)),
        ("right_hall_collision", (10.65, 5.5, -0.65), (0.15, 5.5, 8.15)),
        ("back_hall_collision", (0.0, 5.5, -8.95), (10.8, 5.5, 0.15)),
    ):
        world.static_box(
            name,
            position=position,
            half_extents=extents,
            material=painted_steel,
        )

    # The open mouth points down and left.  These three slabs are both a
    # recognizable toy bin and real collision geometry, while the initial
    # velocities capture its contents shortly after they clear the lip.
    bin_position = (6.60, 4.00, -3.05)
    bin_rotation = _quat_degrees(-16.0, (0.0, 0.0, 1.0))
    world.static_box(
        "tilted_toy_box_floor_collision",
        position=bin_position,
        rotation=bin_rotation,
        half_extents=(2.20, 0.10, 1.38),
        material=painted_steel,
    )
    for suffix, local_position, extents in (
        ("rear", (2.05, 0.72, 0.0), (0.10, 0.72, 1.38)),
        ("near_rail", (0.0, 0.52, 1.32), (2.20, 0.52, 0.08)),
        ("far_rail", (0.0, 0.52, -1.32), (2.20, 0.52, 0.08)),
    ):
        world.static_box(
            f"tilted_toy_box_{suffix}_collision",
            position=_transform(bin_position, bin_rotation, local_position),
            rotation=bin_rotation,
            half_extents=extents,
            material=painted_steel,
        )

    for index in range(SPOT_COUNT):
        column = index % 4
        row = index // 4
        position = (
            3.82 + 0.72 * column,
            4.78 + 1.22 * row + 0.04 * (column % 2),
            -2.72 + 0.31 * ((index * 5) % 4),
        )
        yaw = -22.0 + 13.0 * ((index * 7) % 5)
        roll = -14.0 + 9.0 * (index % 4)
        rotation = _quat_multiply(
            _quat_degrees(yaw, (0.0, 1.0, 0.0)),
            _quat_degrees(roll, (0.0, 0.0, 1.0)),
        )
        body = world.rigid_body(
            f"spot_body_{index:02d}",
            category="spot",
            position=position,
            rotation=rotation,
            density=1.15,
            linear_damping=0.035,
            angular_damping=0.045,
            sleep_threshold=0.001,
            solver_iterations=(10, 3),
        )
        body.box((0.30, 0.53, 0.34), toy_contact)
        body.linear_velocity(
            (-2.15 - 0.16 * row, 1.15 + 0.22 * row, 0.32 * (column - 1.5))
        )
        body.angular_velocity(
            (0.7 + 0.16 * row, -0.55 + 0.22 * column, 0.9 - 0.10 * index)
        )


def _rectangle(
    renderer: Renderer,
    name: str,
    p1: Sequence[float],
    p2: Sequence[float],
    p3: Sequence[float],
    material: Any,
    **parameters: Any,
) -> Any:
    return renderer.object(
        name=name,
        type="rectangle",
        p1=p1,
        p2=p2,
        p3=p3,
        material=material,
        **parameters,
    )


def _cylinder(
    renderer: Renderer,
    name: str,
    base: Sequence[float],
    axis: Sequence[float],
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


def _disk(
    renderer: Renderer,
    name: str,
    center: Sequence[float],
    normal: Sequence[float],
    radius: float,
    material: Any,
) -> Any:
    return renderer.object(
        name=name,
        type="disk",
        center=center,
        normal=normal,
        radius=radius,
        material=material,
    )


def _capsule_materials(renderer: Renderer) -> dict[str, Any]:
    yellow = renderer.material(
        name="assembly_capsule_yellow",
        type="pbr",
        base_color=(0.98, 0.68, 0.045),
        metallic=0.0,
        roughness=0.22,
    )
    dark = renderer.material(
        name="assembly_capsule_dark",
        type="pbr",
        base_color=(0.035, 0.075, 0.15),
        metallic=0.42,
        roughness=0.19,
    )
    white = renderer.material(
        name="assembly_capsule_white",
        type="pbr",
        base_color=(0.95, 0.98, 1.0),
        metallic=0.0,
        roughness=0.16,
    )
    rubber = renderer.material(
        name="assembly_capsule_rubber",
        type="pbr",
        base_color=(0.13, 0.045, 0.018),
        metallic=0.0,
        roughness=0.76,
    )
    metal = renderer.material(
        name="assembly_capsule_metal",
        type="pbr",
        base_color=(0.46, 0.50, 0.56),
        metallic=0.92,
        roughness=0.22,
    )
    tip = renderer.material(
        name="assembly_capsule_tip",
        type="pbr",
        base_color=(1.0, 0.52, 0.035),
        metallic=0.12,
        roughness=0.18,
    )
    return {
        "mascot_torso": yellow,
        "mascot_arm_left": yellow,
        "mascot_arm_right": yellow,
        "mascot_leg_left": yellow,
        "mascot_leg_right": yellow,
        "mascot_visor": dark,
        "mascot_eye_left": white,
        "mascot_eye_right": white,
        "mascot_belt_flange": dark,
        "mascot_glove_left": rubber,
        "mascot_glove_right": rubber,
        "mascot_boot_left": rubber,
        "mascot_boot_right": rubber,
        "mascot_antenna_stem": metal,
        "mascot_antenna_tip": tip,
    }


def _sparky_materials(
    renderer: Renderer,
    *,
    index: int,
    screen_texture: Any,
    primary: Sequence[float],
    accent: Sequence[float],
    lit: bool,
) -> dict[str, Any]:
    # SpectralDock's PBR material supplies a Lambert diffuse lobe and GGX
    # specular lobe.  A low-roughness nonmetal is the closest clearcoat-like
    # finish without inventing a separate clearcoat renderer feature.
    shell = renderer.material(
        name=f"sparky_{index}_candy_shell",
        type="pbr",
        base_color=primary,
        metallic=0.0,
        roughness=0.17,
    )
    trim = renderer.material(
        name=f"sparky_{index}_candy_trim",
        type="pbr",
        base_color=accent,
        metallic=0.0,
        roughness=0.20,
    )
    white = renderer.material(
        name=f"sparky_{index}_warm_white",
        type="pbr",
        base_color=(0.91, 0.91, 0.84),
        metallic=0.0,
        roughness=0.25,
    )
    metal = renderer.material(
        name=f"sparky_{index}_brushed_metal",
        type="pbr",
        base_color=(0.32, 0.35, 0.40),
        metallic=0.88,
        roughness=0.31,
    )
    head = renderer.material(
        name=f"sparky_{index}_glossy_head",
        type="pbr",
        base_color=(0.20, 0.48, 0.72),
        metallic=0.04,
        roughness=0.075,
    )
    tread = renderer.material(
        name=f"sparky_{index}_rubber_tread",
        type="pbr",
        base_color=(0.075, 0.055, 0.048),
        metallic=0.0,
        roughness=0.82,
    )
    if lit:
        screen = renderer.material(
            name=f"sparky_{index}_lit_texture_screen",
            type="emitter",
            texture=screen_texture,
            emission=(1.4, 6.0, 13.0),
        )
    else:
        screen = renderer.material(
            name=f"sparky_{index}_texture_screen",
            type="lambertian",
            texture=screen_texture,
            base_color=(0.82, 0.90, 1.0),
        )
    signal = renderer.material(
        name=f"sparky_{index}_signal",
        type="pbr",
        base_color=(1.0, 0.71, 0.035),
        metallic=0.0,
        roughness=0.16,
    )
    return {
        "AccentOrange": trim,
        "EmitYellow": signal,
        "GlassHead": head,
        "MetalGrey": metal,
        "PlasticBlue": shell,
        "PlasticWhite": white,
        "ScreenChest": screen,
        "ScreenFace": screen,
        "ScreenPalm": screen,
        "TreadOrange": tread,
    }


def _add_architecture(renderer: Renderer, materials: dict[str, Any]) -> None:
    floor = materials["factory_floor"]
    wall = materials["factory_wall"]
    roof = materials["roof_panel"]
    steel = materials["truss_steel"]
    brass = materials["truss_joint"]

    _rectangle(
        renderer,
        "assembly_hall_floor",
        (-11.0, 0.0, 7.8),
        (-11.0, 0.0, -9.2),
        (11.0, 0.0, -9.2),
        floor,
    )
    _rectangle(
        renderer,
        "assembly_hall_back_wall",
        (-11.0, 0.0, -9.0),
        (-11.0, 11.2, -9.0),
        (11.0, 11.2, -9.0),
        wall,
    )
    _rectangle(
        renderer,
        "assembly_hall_left_wall",
        (-11.0, 0.0, 7.8),
        (-11.0, 11.2, 7.8),
        (-11.0, 11.2, -9.0),
        wall,
    )
    _rectangle(
        renderer,
        "assembly_hall_right_wall",
        (11.0, 0.0, -9.0),
        (11.0, 11.2, -9.0),
        (11.0, 11.2, 7.8),
        wall,
    )

    # Four independent roof slabs leave a genuine 6.8 x 5.5 opening.  The
    # high noon environment is consequently visible and sampleable through it.
    roof_y = 11.2
    for name, points in (
        (
            "roof_left_of_skylight",
            ((-11.0, roof_y, 7.8), (-11.0, roof_y, -9.0), (-3.4, roof_y, -9.0)),
        ),
        (
            "roof_right_of_skylight",
            ((3.4, roof_y, -9.0), (11.0, roof_y, -9.0), (11.0, roof_y, 7.8)),
        ),
        (
            "roof_behind_skylight",
            ((-3.4, roof_y, -3.0), (-3.4, roof_y, -9.0), (3.4, roof_y, -9.0)),
        ),
        (
            "roof_ahead_of_skylight",
            ((-3.4, roof_y, 7.8), (-3.4, roof_y, 2.5), (3.4, roof_y, 2.5)),
        ),
    ):
        _rectangle(renderer, name, *points, roof)

    for index, x in enumerate((-9.2, -3.4, 3.4, 9.2)):
        _cylinder(
            renderer,
            f"truss_column_{index:02d}",
            (x, 0.0, -8.72),
            (0.0, 1.0, 0.0),
            10.9,
            0.13,
            steel,
        )
        _disk(
            renderer,
            f"truss_column_joint_{index:02d}",
            (x, 10.9, -8.72),
            (0.0, 0.0, 1.0),
            0.31,
            brass,
        )
    for index, (base, axis, height) in enumerate(
        (
            ((-9.2, 10.9, -8.72), (1.0, 0.0, 0.0), 18.4),
            ((-9.2, 7.0, -8.70), (5.8, 3.9, 0.0), 7.0),
            ((-3.4, 10.9, -8.70), (6.8, -3.9, 0.0), 7.85),
            ((3.4, 7.0, -8.70), (5.8, 3.9, 0.0), 7.0),
        )
    ):
        _cylinder(
            renderer,
            f"truss_beam_{index:02d}",
            base,
            axis,
            height,
            0.105,
            steel,
        )
    for index, x in enumerate((-9.2, -3.4, 3.4, 9.2)):
        _rectangle(
            renderer,
            f"truss_gusset_{index:02d}",
            (x - 0.35, 10.55, -8.68),
            (x + 0.35, 10.55, -8.68),
            (x + 0.35, 11.15, -8.68),
            brass,
        )


def _add_conveyor_and_characters(
    renderer: Renderer,
    materials: dict[str, Any],
    sparky_meshes: Sequence[Any],
    capsule_mesh: Any,
) -> None:
    _rectangle(
        renderer,
        "conveyor_belt_top",
        (-5.15, 0.82, 3.45),
        (-5.15, 0.82, 1.35),
        (4.85, 0.82, 1.35),
        materials["conveyor_belt"],
    )
    for index, x in enumerate((-4.75, -2.25, 0.25, 2.75, 4.55)):
        _cylinder(
            renderer,
            f"conveyor_roller_{index:02d}",
            (x, 0.63, 1.43),
            (0.0, 0.0, 1.0),
            1.94,
            0.19,
            materials["conveyor_roller"],
        )
    for index, x in enumerate((-4.7, 4.4)):
        for side, z in enumerate((1.52, 3.28)):
            _cylinder(
                renderer,
                f"conveyor_leg_{index}_{side}",
                (x, 0.0, z),
                (0.0, 1.0, 0.0),
                0.68,
                0.10,
                materials["truss_steel"],
            )

    sparky_positions = (-3.65, -1.35, 0.95, 3.25)
    for index, (x, mesh) in enumerate(zip(sparky_positions, sparky_meshes)):
        renderer.object(
            name=f"conveyor_sparky_{index:02d}",
            type="mesh",
            mesh=mesh,
            translate=(x, 0.825, 2.24 + 0.08 * (index % 2)),
            rotate_degrees=(0.0, -4.0 + 3.0 * index, 0.0),
            scale=(0.68, 0.68, 0.68),
        )

    # The emissive screen remains textured geometry; this matching finite NEE
    # rectangle is the closest supported way to sample its outgoing light.
    renderer.light(
        name="awake_sparky_screen_nee",
        type="rectangle",
        position=(-3.39, 2.10, 2.54),
        edge_u=(-0.44, 0.0, 0.0),
        edge_v=(0.0, -0.30, 0.0),
        emission=(1.4, 6.0, 13.0),
    )

    # Capsule stands directly below the true roof opening and its noon patch.
    renderer.object(
        name="capsule_in_skylight",
        type="mesh",
        mesh=capsule_mesh,
        translate=(-0.55, 0.0, -1.05),
        rotate_degrees=(0.0, 18.0, 0.0),
        scale=(0.94, 0.94, 0.94),
    )


def _add_forges(renderer: Renderer, materials: dict[str, Any]) -> None:
    for prefix, center in (
        ("open_forge", (-6.40, 0.0, -5.55)),
        ("safety_forge", (-2.75, 0.0, -5.55)),
    ):
        _cylinder(
            renderer,
            prefix + "_base",
            center,
            (0.0, 1.0, 0.0),
            0.72,
            1.12,
            materials["forge_dark_metal"],
        )
        _disk(
            renderer,
            prefix + "_bowl",
            (center[0], 0.72, center[2]),
            (0.0, 1.0, 0.0),
            0.92,
            materials["forge_copper"],
        )

    # Water scenes use a strict LIFO medium stack.  A second rough dielectric
    # boundary can expose rare near-tangent ordering failures at cover-image
    # sample counts, so the frosted booth is represented by a pale, rough PBR
    # ribbed shroud.  Overlapping finite emitter spheres below supply the warm
    # blurred read; the shroud is an explicit opaque visual proxy rather than
    # a claim of glass transmission.
    shroud_x, shroud_z = -2.75, -5.55
    shroud_radius = 1.24
    shroud_segments = 12
    for index in range(shroud_segments):
        angle = 2.0 * math.pi * index / shroud_segments
        next_angle = 2.0 * math.pi * (index + 1) / shroud_segments
        base = (
            shroud_x + shroud_radius * math.cos(angle),
            0.72,
            shroud_z + shroud_radius * math.sin(angle),
        )
        _cylinder(
            renderer,
            f"frosted_shroud_rib_{index:02d}",
            base,
            (0.0, 1.0, 0.0),
            2.46,
            0.052,
            materials["safety_shroud"],
        )
        next_point = (
            shroud_x + shroud_radius * math.cos(next_angle),
            0.72,
            shroud_z + shroud_radius * math.sin(next_angle),
        )
        segment = tuple(next_point[axis] - base[axis] for axis in range(3))
        segment_length = _length(segment)
        segment_axis = tuple(value / segment_length for value in segment)
        for ring_index, y in enumerate((0.72, 3.18)):
            ring_base = (base[0], y, base[2])
            _cylinder(
                renderer,
                f"frosted_shroud_ring_{ring_index}_{index:02d}",
                ring_base,
                segment_axis,
                segment_length,
                0.052,
                materials["safety_shroud"],
            )

    for index, (center, radius) in enumerate(
        (
            ((-2.75, 1.43, -5.55), 0.66),
            ((-2.56, 2.08, -5.53), 0.43),
            ((-2.83, 2.53, -5.56), 0.25),
        )
    ):
        glow = renderer.object(
            name=f"enclosed_warm_glow_{index:02d}",
            type="sphere",
            center=center,
            radius=radius,
            material=materials["safety_glow"],
        )
        renderer.light(
            name=f"enclosed_warm_glow_light_{index:02d}",
            type="sphere",
            object=glow,
            position=center,
            radius=radius,
            emission=(5.5, 1.0, 0.06),
        )

    for name, position, axis, height, radius_start, radius_end, seed in (
        ("open_fire_core", (-6.42, 0.73, -5.55), (0.02, 1.0, -0.03), 2.35, 0.61, 0.12, 20260718),
        ("open_fire_tongue", (-6.05, 0.78, -5.48), (0.24, 1.0, 0.06), 1.72, 0.32, 0.07, 20260719),
    ):
        renderer.light(
            name=name,
            type="flame",
            position=position,
            axis=axis,
            height=height,
            radius_start=radius_start,
            radius_end=radius_end,
            emission_start=(45.0, 10.5, 0.25),
            emission_end=(4.5, 0.24, 0.004),
            extinction=1.52,
            density_scale=0.76,
            turbulence=0.72,
            noise_scale=3.7,
            seed=seed,
        )

    # A flame volume with almost no emission is the supported approximation
    # for smoke: high extinction makes it cast a readable environment shadow.
    renderer.light(
        name="absorptive_smoke_volume",
        type="flame",
        position=(-6.27, 2.55, -5.60),
        axis=(0.12, 1.0, -0.05),
        height=4.65,
        radius_start=0.52,
        radius_end=1.03,
        emission_start=(0.0008, 0.0006, 0.0004),
        emission_end=(0.0002, 0.00025, 0.00035),
        extinction=3.25,
        density_scale=1.18,
        turbulence=0.86,
        noise_scale=2.55,
        seed=20260722,
    )


def _add_cooling_pool(renderer: Renderer, materials: dict[str, Any]) -> None:
    for name, points, material_name in (
        ("cooling_pool_floor", ((5.0, -0.78, 3.85), (5.0, -0.78, -1.25), (9.75, -0.78, -1.25)), "pool_tile"),
        ("cooling_pool_left", ((5.0, -0.78, -1.25), (5.0, 0.30, -1.25), (5.0, 0.30, 3.85)), "pool_rim"),
        ("cooling_pool_right", ((9.75, -0.78, 3.85), (9.75, 0.30, 3.85), (9.75, 0.30, -1.25)), "pool_rim"),
        ("cooling_pool_back", ((5.0, -0.78, -1.25), (9.75, -0.78, -1.25), (9.75, 0.30, -1.25)), "pool_rim"),
        ("cooling_pool_front", ((5.0, -0.78, 3.85), (5.0, 0.30, 3.85), (9.75, 0.30, 3.85)), "pool_rim"),
    ):
        _rectangle(renderer, name, *points, materials[material_name])
    renderer.object(
        name="four_octave_cooling_water",
        type="water_surface",
        center=(7.375, 0.12, 1.30),
        size=(4.75, 5.10),
        material=materials["cooling_water"],
        waves=(
            {
                "direction": (1.0, 0.18),
                "amplitude": 0.040,
                "wavelength": 3.20,
                "phase_radians": 0.42,
            },
            {
                "direction": (-0.37, 1.0),
                "amplitude": 0.015,
                "wavelength": 1.80,
                "phase_radians": 1.91,
            },
            {
                "direction": (0.71, 1.0),
                "amplitude": 0.006,
                "wavelength": 1.00,
                "phase_radians": 3.73,
            },
            {
                "direction": (-1.0, 0.29),
                "amplitude": 0.002,
                "wavelength": 0.55,
                "phase_radians": 5.18,
            },
        ),
    )


def _add_toy_box(renderer: Renderer, materials: dict[str, Any]) -> None:
    position = (6.60, 4.00, -3.05)
    rotation = _quat_degrees(-16.0, (0.0, 0.0, 1.0))
    wood = materials["toy_box"]
    edge = materials["toy_box_edge"]
    for name, p1, p2, p3, material in (
        ("tilted_toy_box_floor", (-2.2, 0.10, 1.34), (-2.2, 0.10, -1.34), (2.2, 0.10, -1.34), wood),
        ("tilted_toy_box_rear", (2.12, 0.10, -1.34), (2.12, 1.50, -1.34), (2.12, 1.50, 1.34), wood),
        ("tilted_toy_box_near", (-2.2, 0.10, 1.34), (2.2, 0.10, 1.34), (2.2, 1.05, 1.34), wood),
        ("tilted_toy_box_far", (2.2, 0.10, -1.34), (-2.2, 0.10, -1.34), (-2.2, 1.05, -1.34), wood),
    ):
        _rectangle(
            renderer,
            name,
            _transform(position, rotation, p1),
            _transform(position, rotation, p2),
            _transform(position, rotation, p3),
            material,
        )
    for index, local in enumerate(((-2.18, 0.1, 1.34), (-2.18, 0.1, -1.34))):
        _cylinder(
            renderer,
            f"toy_box_mouth_edge_{index}",
            _transform(position, rotation, local),
            _rotate(rotation, (0.0, 1.0, 0.0)),
            0.95,
            0.07,
            edge,
        )


def create_renderer(
    physics: PhysicsWorld,
    *,
    metadata_output: Path | None = None,
    verify: bool = False,
) -> Renderer:
    if (
        physics.scene_name != "assembly-hall"
        or physics.seed != SEED
        or physics.steps != STEPS
        or physics.gravity != (0.0, -9.81, 0.0)
        or not math.isclose(physics.fixed_dt, FIXED_DT, abs_tol=1.0e-12)
    ):
        raise ValueError("physics must come from create_physics_world()")

    renderer = Renderer(device=physics.device, scene_name="assembly-hall")
    renderer.integrator(
        direct_light_sampling="importance",
        clamp_direct=64.0,
        clamp_indirect=16.0,
    )
    renderer.camera(
        look_from=(9.35, 6.65, 16.2),
        look_at=(-0.20, 3.00, -1.35),
        up=(0.0, 1.0, 0.0),
        vfov=33.0,
        aperture=0.018,
        focus_distance=20.25,
    )
    renderer.background(
        type="environment",
        path=ENVIRONMENT,
        intensity=1.38,
        rotation_degrees=0.0,
        exposure=0.32,
    )

    screen_texture = renderer.texture(
        name="assembly_sparky_screen_atlas",
        type="image",
        path=ROOT / "assets/examples/models/sparky/sparky_albedo.avif",
        color_space="srgb",
    )
    spot_texture = renderer.texture(
        name="assembly_spot_albedo",
        type="image",
        path=ROOT / "assets/examples/models/spot/spot_texture.avif",
        color_space="srgb",
        wrap_u="repeat",
        wrap_v="repeat",
    )
    gear_alpha = renderer.texture(
        name="assembly_gear_alpha",
        type="image",
        path=GEAR_ALPHA,
        color_space="linear",
    )

    definitions = (
        ("factory_floor", "pbr", {"base_color": (0.18, 0.19, 0.20), "metallic": 0.18, "roughness": 0.46}),
        ("factory_wall", "pbr", {"base_color": (0.27, 0.255, 0.225), "metallic": 0.05, "roughness": 0.62}),
        ("roof_panel", "pbr", {"base_color": (0.095, 0.105, 0.12), "metallic": 0.76, "roughness": 0.37}),
        ("truss_steel", "pbr", {"base_color": (0.16, 0.18, 0.21), "metallic": 0.91, "roughness": 0.27}),
        ("truss_joint", "pbr", {"base_color": (0.72, 0.34, 0.075), "metallic": 0.86, "roughness": 0.31}),
        ("conveyor_belt", "pbr", {"base_color": (0.055, 0.085, 0.095), "metallic": 0.0, "roughness": 0.72}),
        ("conveyor_roller", "pbr", {"base_color": (0.46, 0.49, 0.52), "metallic": 0.94, "roughness": 0.20}),
        ("forge_dark_metal", "pbr", {"base_color": (0.075, 0.065, 0.060), "metallic": 0.92, "roughness": 0.42}),
        ("forge_copper", "pbr", {"base_color": (0.72, 0.23, 0.045), "metallic": 1.0, "roughness": 0.27}),
        ("pool_tile", "pbr", {"base_color": (0.035, 0.19, 0.23), "metallic": 0.04, "roughness": 0.50}),
        ("pool_rim", "pbr", {"base_color": (0.24, 0.29, 0.30), "metallic": 0.34, "roughness": 0.38}),
        ("safety_shroud", "pbr", {"base_color": (0.48, 0.68, 0.74), "metallic": 0.06, "roughness": 0.68}),
        ("safety_glow", "emitter", {"emission": (5.5, 1.0, 0.06)}),
        ("toy_box", "pbr", {"base_color": (0.64, 0.16, 0.055), "metallic": 0.0, "roughness": 0.48}),
        ("toy_box_edge", "pbr", {"base_color": (0.90, 0.52, 0.075), "metallic": 0.12, "roughness": 0.30}),
        ("gear_cutout", "pbr", {"base_color": (0.90, 0.46, 0.07), "metallic": 0.92, "roughness": 0.22}),
    )
    materials = {
        name: renderer.material(name=name, type=kind, **parameters)
        for name, kind, parameters in definitions
    }
    materials["cooling_water"] = renderer.material(
        name="assembly_cooling_water",
        type="water",
        roughness=0.060,
        ior=1.333,
        absorption=(0.48, 0.105, 0.028),
    )
    spot_material = renderer.material(
        name="textured_spot_coat",
        type="lambertian",
        texture=spot_texture,
        base_color=(0.96, 0.96, 0.96),
    )

    capsule_mesh = renderer.mesh(
        name="assembly_capsule",
        path=ROOT / "assets/examples/models/capsule-mascot/capsule-mascot.obj",
        materials=_capsule_materials(renderer),
    )
    candy_colors = (
        ((0.95, 0.17, 0.28), (1.0, 0.57, 0.08)),
        ((0.12, 0.66, 0.78), (0.96, 0.28, 0.52)),
        ((0.48, 0.72, 0.10), (1.0, 0.48, 0.05)),
        ((0.62, 0.27, 0.88), (0.12, 0.72, 0.78)),
    )
    sparky_meshes = tuple(
        renderer.mesh(
            name=f"assembly_sparky_{index}",
            path=ROOT / "assets/examples/models/sparky/sparky.obj",
            materials=_sparky_materials(
                renderer,
                index=index,
                screen_texture=screen_texture,
                primary=primary,
                accent=accent,
                lit=index == 0,
            ),
        )
        for index, (primary, accent) in enumerate(candy_colors)
    )
    spot_mesh = renderer.mesh(
        name="assembly_spot",
        path=ROOT / "assets/examples/models/spot/spot_triangulated.obj",
    )

    _add_architecture(renderer, materials)
    # A finite source just below the real roof opening keeps the skylight patch
    # legible at Gallery preview budgets.  The noon HDR remains enabled and
    # importance sampled for the directional sun/highlight contribution.
    renderer.light(
        name="skylight_area_fill",
        type="rectangle",
        position=(-3.0, 10.92, 2.30),
        edge_u=(0.0, 0.0, -5.20),
        edge_v=(6.0, 0.0, 0.0),
        emission=(7.0, 8.2, 9.8),
    )
    _add_conveyor_and_characters(
        renderer, materials, sparky_meshes, capsule_mesh
    )
    _add_forges(renderer, materials)
    _add_cooling_pool(renderer, materials)
    _add_toy_box(renderer, materials)

    renderer.object(
        name="alpha_masked_back_wall_gear",
        type="rectangle",
        p1=(4.10, 2.10, -8.92),
        p2=(4.10, 7.75, -8.92),
        p3=(9.35, 7.75, -8.92),
        material=materials["gear_cutout"],
        alpha_texture=gear_alpha,
        alpha_cutoff=0.5,
    )

    _populate_physics(physics)
    result = physics.simulate(
        metadata_output=metadata_output,
        verify=verify,
        validator=_validate,
    )
    for index, state in enumerate(result.bodies):
        _apply_body_mesh(
            renderer,
            state,
            name=f"falling_spot_{index:02d}",
            mesh=spot_mesh,
            local_translate=(0.0, -0.06, 0.0),
            scale=(0.66, 0.66, 0.66),
            material=spot_material,
        )
    return renderer


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
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
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "assembly-hall.avif"
    if args.preview:
        width, height, spp, depth = (
            PREVIEW_WIDTH,
            PREVIEW_HEIGHT,
            PREVIEW_SPP,
            PREVIEW_DEPTH,
        )
    else:
        width, height, spp, depth = (
            FORMAL_WIDTH,
            FORMAL_HEIGHT,
            FORMAL_SPP,
            FORMAL_DEPTH,
        )
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
