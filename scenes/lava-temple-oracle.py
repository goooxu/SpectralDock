#!/usr/bin/env python3
"""Lava Temple Oracle: 4K cover scene driven by live GPU PhysX state."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from spectraldock import PhysicsResult, PhysicsWorld, Renderer


ROOT = Path(__file__).resolve().parents[1]
SEED = 909
FIXED_DT = 1.0 / 120.0
STEPS = 24
EXPLOSION_CENTER = (0.0, 5.25, -1.55)
GODRAY_ORIGIN = (-4.10, 10.25, 3.65)
GODRAY_AXIS = (0.50, -0.61, -0.63)


class _SplitMix64:
    def __init__(self, seed: int) -> None:
        self.state = seed & 0xFFFFFFFFFFFFFFFF

    def next(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        value = self.state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        return value ^ (value >> 31)

    def unit(self) -> float:
        return (self.next() >> 11) / float(1 << 53)

    def symmetric(self, magnitude: float) -> float:
        return (2.0 * self.unit() - 1.0) * magnitude


def _add(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return a[0] + b[0], a[1] + b[1], a[2] + b[2]


def _sub(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _mul(value: tuple[float, ...], scale: float) -> tuple[float, float, float]:
    return value[0] * scale, value[1] * scale, value[2] * scale


def _length(value: tuple[float, ...]) -> float:
    return math.sqrt(sum(component * component for component in value))


def _unit(value: tuple[float, ...], fallback: tuple[float, ...]) -> tuple[float, float, float]:
    length = _length(value)
    if length <= 1.0e-12:
        return fallback  # type: ignore[return-value]
    return _mul(value, 1.0 / length)


def _cross(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _quat(angle: float, axis: tuple[float, ...]) -> tuple[float, float, float, float]:
    axis = _unit(axis, (1.0, 0.0, 0.0))
    sine = math.sin(angle * 0.5)
    return axis[0] * sine, axis[1] * sine, axis[2] * sine, math.cos(angle * 0.5)


def _local_rectangle(body: Any, name: str, half_x: float, half_y: float,
                     local_z: float, material: Any) -> None:
    body.attach_rectangle(name, (-half_x, -half_y, local_z),
                          (-half_x, half_y, local_z),
                          (half_x, half_y, local_z), material)


def _capsule_attachments(body: Any, prefix: str, radius: float,
                         half_height: float, material: Any) -> None:
    body.attach_cylinder(prefix + "_shaft", (-half_height, 0.0, 0.0),
                         (1.0, 0.0, 0.0), 2.0 * half_height, radius, material)
    body.attach_sphere(prefix + "_cap_a", (-half_height, 0.0, 0.0), radius, material)
    body.attach_sphere(prefix + "_cap_b", (half_height, 0.0, 0.0), radius, material)


def _apply_explosion(body: Any, initial: tuple[float, ...], speed: float,
                     upward_bias: float, random: _SplitMix64) -> None:
    displacement = _sub(initial, EXPLOSION_CENTER)
    radial = (displacement[0] + random.symmetric(0.16),
              displacement[1] * 0.38 + upward_bias,
              displacement[2] + random.symmetric(0.16))
    radial = _unit(radial, (0.0, 1.0, 0.0))
    tangent = _unit((-radial[2], 0.35, radial[0]), (1.0, 0.0, 0.0))
    application = _add(_add(initial, _mul(tangent, random.symmetric(0.22))),
                       (0.0, random.symmetric(0.12), 0.0))
    body.mass_scaled_impulse_at_position(
        _mul(radial, speed + random.symmetric(0.8)), application)


def create_physics_world(*, device: int = 0) -> PhysicsWorld:
    return PhysicsWorld(device=device, seed=SEED, fixed_dt=FIXED_DT, steps=STEPS,
                        gravity=(0.0, -9.81, 0.0),
                        scene_name="lava-temple-oracle")


def _validate(result: PhysicsResult) -> bool:
    if len(result.bodies) != 130:
        return False
    moving = radial = rotating = 0
    quadrants: set[tuple[bool, bool]] = set()
    maximum_upward = -math.inf
    for body in result.bodies:
        displacement = _sub(body.position, body.initial_position)
        speed = _length(body.linear_velocity)
        angular = _length(body.angular_velocity)
        if speed > 1.0e-3 or angular > 1.0e-3:
            moving += 1
        if _length(displacement) >= 0.08:
            radial += 1
            if abs(displacement[0]) > 1.0e-6 and abs(displacement[2]) > 1.0e-6:
                quadrants.add((displacement[0] > 0.0, displacement[2] > 0.0))
        if angular > 0.02:
            rotating += 1
        maximum_upward = max(maximum_upward, displacement[1])
        if not (-12.0 <= body.position[0] <= 12.0 and
                -0.2 <= body.position[1] <= 15.0 and
                -10.0 <= body.position[2] <= 8.0):
            return False
    return (moving >= 120 and radial >= 120 and rotating >= 12 and
            len(quadrants) == 4 and maximum_upward >= 0.08 and
            not any(body.sleeping for body in result.bodies))


def _populate_physics(world: PhysicsWorld, materials: dict[str, Any]) -> None:
    stone = world.material("stone_contact", static_friction=0.72,
                           dynamic_friction=0.61, restitution=0.08)
    metal = world.material("metal_contact", static_friction=0.42,
                           dynamic_friction=0.35, restitution=0.16)
    spark = world.material("spark_contact", static_friction=0.18,
                           dynamic_friction=0.12, restitution=0.04)
    world.static_plane("temple_ground_collision", material=stone)
    for name, position, extents in (
        ("altar_collision", (0.0, 0.6, -1.55), (1.75, 0.6, 1.55)),
        ("left_wall_collision", (-9.5, 5.0, -3.0), (0.45, 5.0, 7.0)),
        ("right_wall_collision", (9.5, 5.0, -3.0), (0.45, 5.0, 7.0)),
        ("back_wall_collision", (0.0, 5.0, -9.5), (9.5, 5.0, 0.45)),
    ):
        world.static_box(name, position=position, half_extents=extents, material=stone)

    random = _SplitMix64(world.seed)
    row_y = (-1.12, -0.38, 0.38, 1.12)
    row_radius = (1.02, 1.35, 1.35, 1.02)
    for row in range(4):
        for segment in range(6):
            index = row * 6 + segment
            angle = (segment + 0.18 * row) * (2.0 * math.pi / 6.0)
            position = _add(EXPLOSION_CENTER,
                            (math.sin(angle) * row_radius[row], row_y[row],
                             math.cos(angle) * row_radius[row]))
            extents = (0.40 if row in (0, 3) else 0.53, 0.33, 0.09)
            body = world.rigid_body(f"shell_plate_{index:02d}", category="shell_plate",
                                    position=position, rotation=_quat(angle, (0.0, 1.0, 0.0)),
                                    density=2.7, linear_damping=0.025,
                                    angular_damping=0.045, sleep_threshold=0.001)
            body.box(extents, metal)
            _apply_explosion(body, position, 2.66 + 0.056 * index, 0.22, random)
            _local_rectangle(body, f"shell_outer_{index:02d}", extents[0], extents[1],
                             extents[2], materials["shell_dark_metal"])
            _local_rectangle(body, f"shell_inner_{index:02d}", extents[0], extents[1],
                             -extents[2], materials["shell_inner_gold"])

    for index in range(2):
        position = _add(EXPLOSION_CENTER, (-0.48 if index == 0 else 0.48, 0.42, 1.42))
        extents = (0.42, 0.48, 0.075)
        body = world.rigid_body(f"visor_panel_{index:02d}", category="visor_panel",
                                position=position,
                                rotation=_quat(-0.12 if index == 0 else 0.12,
                                               (0.0, 1.0, 0.0)), density=3.1,
                                linear_damping=0.025, angular_damping=0.045,
                                sleep_threshold=0.001)
        body.box(extents, metal)
        _apply_explosion(body, position, 2.76, 0.20, random)
        _local_rectangle(body, f"visor_panel_{index:02d}", extents[0], extents[1],
                         extents[2], materials["visor_metal"])

    for index in range(2):
        position = _add(EXPLOSION_CENTER, (-0.42 if index == 0 else 0.42, 0.48, 1.52))
        body = world.rigid_body(f"eye_{index:02d}", category="eye", position=position,
                                density=1.4, linear_damping=0.025,
                                angular_damping=0.045, sleep_threshold=0.001)
        body.sphere(0.16, metal)
        _apply_explosion(body, position, 2.805, 0.28, random)
        body.attach_sphere(f"eye_{index:02d}", (0.0, 0.0, 0.0), 0.16,
                           materials["eye_emitter"])

    limb_positions = (
        _add(EXPLOSION_CENTER, (-1.55, 0.38, 0.0)),
        _add(EXPLOSION_CENTER, (1.55, 0.38, 0.0)),
        _add(EXPLOSION_CENTER, (-0.68, -1.72, 0.0)),
        _add(EXPLOSION_CENTER, (0.68, -1.72, 0.0)),
    )
    for index, position in enumerate(limb_positions):
        arm = index < 2
        radius, half_height = ((0.17, 0.48) if arm else (0.20, 0.43))
        body = world.rigid_body(f"limb_{index:02d}", category="limb", position=position,
                                rotation=_quat(0.0 if arm else math.pi * 0.5,
                                               (0.0, 0.0, 1.0)), density=2.1,
                                linear_damping=0.025, angular_damping=0.045,
                                sleep_threshold=0.001)
        body.capsule(radius, half_height, metal)
        _apply_explosion(body, position, 2.94, 0.30, random)
        _capsule_attachments(body, f"limb_{index:02d}", radius, half_height,
                             materials["limb_metal"])

    for index in range(2):
        position = _add(EXPLOSION_CENTER, (-0.17 if index == 0 else 0.17, 1.72, 0.04))
        body = world.rigid_body(
            f"antenna_part_{index:02d}", category="antenna_part", position=position,
            rotation=_quat(math.pi * 0.5 + (-0.16 if index == 0 else 0.16),
                           (0.0, 0.0, 1.0)), density=1.8, linear_damping=0.025,
            angular_damping=0.045, sleep_threshold=0.001)
        body.capsule(0.075, 0.34, metal)
        _apply_explosion(body, position, 3.5, 0.45, random)
        _capsule_attachments(body, f"antenna_{index:02d}", 0.075, 0.34,
                             materials["mechanism_copper"])
    tip_position = _add(EXPLOSION_CENTER, (0.0, 2.18, 0.04))
    tip = world.rigid_body("antenna_part_02", category="antenna_part",
                           position=tip_position, density=1.3, linear_damping=0.025,
                           angular_damping=0.045, sleep_threshold=0.001)
    tip.sphere(0.19, metal)
    _apply_explosion(tip, tip_position, 3.78, 0.55, random)
    tip.attach_sphere("antenna_tip", (0.0, 0.0, 0.0), 0.19,
                      materials["mechanism_gold"])

    gear_offsets = ((-0.55, 0.42, 0.28), (0.48, 0.58, 0.18),
                    (-0.30, -0.30, 0.42), (0.58, -0.42, 0.12),
                    (-0.02, 0.03, -0.30), (0.12, 0.95, -0.22))
    for index, offset in enumerate(gear_offsets):
        position = _add(EXPLOSION_CENTER, offset)
        axis = _unit((random.symmetric(1.0), random.symmetric(1.0), 1.0),
                     (0.0, 0.0, 1.0))
        body = world.rigid_body(
            f"compound_gear_{index:02d}", category="compound_gear", position=position,
            rotation=_quat(random.symmetric(0.36), axis), density=4.2,
            linear_damping=0.025, angular_damping=0.045, sleep_threshold=0.001)
        body.sphere(0.35, metal)
        for tooth in range(6):
            angle = 2.0 * math.pi * tooth / 6.0
            body.box((0.18, 0.11, 0.12), metal,
                     local_position=(0.52 * math.cos(angle), 0.52 * math.sin(angle), 0.0),
                     local_rotation=_quat(angle, (0.0, 0.0, 1.0)))
        _apply_explosion(body, position, 2.66 + index * 0.154, 0.24, random)
        render_material = materials["mechanism_gold" if index % 2 == 0 else "mechanism_copper"]
        prefix = f"gear_{index:02d}"
        body.attach_cylinder(prefix + "_body", (0.0, 0.0, -0.12),
                             (0.0, 0.0, 1.0), 0.24, 0.3025, render_material)
        body.attach_disk(prefix + "_front", (0.0, 0.0, 0.12),
                         (0.0, 0.0, 1.0), 0.3025, render_material)
        body.attach_disk(prefix + "_back", (0.0, 0.0, -0.12),
                         (0.0, 0.0, -1.0), 0.3025, render_material)
        if index == 4:
            body.attach_sphere(prefix + "_oracle_core", (0.0, 0.0, 0.0), 0.24,
                               materials["oracle_core_emitter"])
        for element in range(6):
            angle = 2.0 * math.pi * element / 6.0
            radial = (math.cos(angle), math.sin(angle), 0.0)
            tangent = (-math.sin(angle), math.cos(angle), 0.0)
            body.attach_cylinder(f"{prefix}_spoke_s_{element:02d}", (0.0, 0.0, 0.0),
                                 radial, 0.55 * 0.77, 0.042, render_material)
            center = _mul(radial, 0.55)
            p1 = _sub(_sub(center, _mul(tangent, 0.16)), _mul(radial, 0.10))
            p2 = _add(_sub(center, _mul(tangent, 0.16)), _mul(radial, 0.10))
            p3 = _add(_add(center, _mul(tangent, 0.16)), _mul(radial, 0.10))
            body.attach_rectangle(f"{prefix}_tooth_t_{element:02d}", p1, p2, p3,
                                  render_material)

    for index in range(29):
        angle = 2.0 * math.pi * index / 29.0 + random.symmetric(0.12)
        radius = 0.24 + 0.66 * random.unit()
        position = _add(EXPLOSION_CENTER,
                        (radius * math.cos(angle), random.symmetric(0.95),
                         radius * math.sin(angle)))
        rotation = _quat(random.symmetric(math.pi),
                         _unit((random.symmetric(1.0), random.symmetric(1.0),
                                random.symmetric(1.0)), (1.0, 0.0, 0.0)))
        render_material = materials["mechanism_gold" if index % 3 == 0 else "mechanism_copper"]
        body = world.rigid_body(
            f"mechanical_part_{index:02d}", category="mechanical_part",
            position=position, rotation=rotation,
            density=3.4 if index < 17 else 3.6, linear_damping=0.025,
            angular_damping=0.045, sleep_threshold=0.001)
        if index < 17:
            part_radius = 0.055 + 0.018 * (index % 3)
            half_height = 0.24 + 0.055 * (index % 4)
            body.capsule(part_radius, half_height, metal)
            _apply_explosion(body, position, 2.94 + 0.056 * index, 0.18, random)
            _capsule_attachments(body, f"mechanism_{index:02d}", part_radius,
                                 half_height, render_material)
        else:
            extents = (0.16 + 0.025 * (index % 4),
                       0.11 + 0.018 * (index % 3), 0.045)
            body.box(extents, metal)
            _apply_explosion(body, position, 3.08 + 0.049 * index, 0.20, random)
            _local_rectangle(body, f"mechanism_{index:02d}_outer", extents[0],
                             extents[1], extents[2], render_material)
            _local_rectangle(body, f"mechanism_{index:02d}_inner", extents[0],
                             extents[1], -extents[2], materials["shell_inner_gold"])

    for index in range(12):
        column, row = float(index % 4), float(index // 4)
        position = (-3.6 + 1.22 * column + random.symmetric(0.12),
                    10.25 + 0.52 * row + random.symmetric(0.12),
                    -2.4 + 0.72 * row + random.symmetric(0.18))
        rotation = _quat(random.symmetric(0.32),
                         _unit((random.symmetric(1.0), 1.0, random.symmetric(1.0)),
                               (0.0, 1.0, 0.0)))
        extents = (0.42 + 0.08 * (index % 3), 0.24 + 0.04 * (index % 2),
                   0.34 + 0.06 * ((index + 1) % 3))
        body = world.rigid_body(f"roof_stone_{index:02d}", category="roof_stone",
                                position=position, rotation=rotation, density=2.8,
                                linear_damping=0.025, angular_damping=0.045,
                                sleep_threshold=0.001)
        body.box(extents, stone)
        body.linear_velocity((0.25 * math.sin(index), -2.0 - 0.12 * index,
                              0.18 * math.cos(index)))
        body.angular_velocity((random.symmetric(2.1), random.symmetric(1.4),
                               random.symmetric(2.1)))
        hx, hy, hz = extents
        material = materials["roof_stone"]
        body.attach_rectangle(f"roof_fragment_{index:02d}_front",
                              (-hx, -hy, hz), (-hx, hy, hz), (hx, hy, hz), material)
        body.attach_rectangle(f"roof_fragment_{index:02d}_side",
                              (hx, -hy, hz), (hx, hy, hz), (hx, hy, -hz), material)
        body.attach_rectangle(f"roof_fragment_{index:02d}_top",
                              (-hx, hy, -hz), (-hx, hy, hz), (hx, hy, hz), material)

    for index in range(48):
        angle = 2.0 * math.pi * random.unit()
        radial = 0.18 + 0.72 * random.unit()
        position = (radial * math.cos(angle), 1.72 + 1.15 * random.unit(),
                    -1.55 + radial * math.sin(angle))
        radius = 0.025 + 0.020 * random.unit()
        body = world.rigid_body(f"spark_{index:02d}", category="spark",
                                position=position, density=0.32,
                                linear_damping=0.025, angular_damping=0.045,
                                sleep_threshold=0.001)
        body.sphere(radius, spark)
        body.linear_velocity((1.8 * math.cos(angle) + random.symmetric(0.8),
                              8.0 + 5.2 * random.unit(),
                              1.8 * math.sin(angle) + random.symmetric(0.8)))
        body.angular_velocity((random.symmetric(4.0), random.symmetric(4.0),
                               random.symmetric(4.0)))
        body.attach_sphere(f"spark_{index:02d}", (0.0, 0.0, 0.0), radius,
                           materials["spark_emitter"])


def _rectangle(renderer: Renderer, materials: dict[str, Any], name: str,
               p1: tuple[float, ...], p2: tuple[float, ...], p3: tuple[float, ...],
               material: str) -> None:
    renderer.object(name=name, type="rectangle", p1=p1, p2=p2, p3=p3,
                    material=materials[material])


def _cylinder(renderer: Renderer, materials: dict[str, Any], name: str,
              base: tuple[float, ...], axis: tuple[float, ...], height: float,
              radius: float, material: str) -> None:
    renderer.object(name=name, type="cylinder", base=base, axis=_unit(axis, (0.0, 1.0, 0.0)),
                    height=height, radius=radius, material=materials[material])


def _static_temple(renderer: Renderer, materials: dict[str, Any]) -> None:
    rectangles = (
        ("temple_floor_left", (-9.5, 0.0, 6.0), (-9.5, 0.0, -9.5), (2.75, 0.0, -9.5), "temple_floorstone"),
        ("temple_floor_front_right", (2.75, 0.0, 6.0), (2.75, 0.0, 2.15), (9.5, 0.0, 2.15), "temple_wetstone"),
        ("temple_floor_back_right", (2.75, 0.0, -5.95), (2.75, 0.0, -9.5), (9.5, 0.0, -9.5), "temple_wetstone"),
        ("temple_back_wall", (-9.5, 0.0, -9.5), (-9.5, 10.5, -9.5), (9.5, 10.5, -9.5), "temple_blackstone"),
        ("temple_left_wall", (-9.5, 0.0, 6.0), (-9.5, 10.5, 6.0), (-9.5, 10.5, -9.5), "temple_blackstone"),
        ("temple_right_wall_back", (9.5, 0.0, -9.5), (9.5, 10.5, -9.5), (9.5, 10.5, -1.0), "temple_blackstone"),
        ("temple_right_wall_front", (9.5, 0.0, 2.8), (9.5, 8.2, 2.8), (9.5, 8.2, 6.0), "temple_blackstone"),
        ("roof_left_slab", (-9.5, 10.5, 6.0), (-9.5, 10.5, -9.5), (-4.45, 10.5, -9.5), "roof_stone"),
        ("roof_back_slab", (-4.45, 10.5, -9.5), (-4.45, 10.5, -5.2), (9.5, 10.5, -5.2), "roof_stone"),
        ("roof_right_slab", (3.8, 10.5, -5.2), (3.8, 10.5, 6.0), (9.5, 10.5, 6.0), "roof_stone"),
        ("roof_front_fragment", (-4.45, 10.5, 3.5), (-4.45, 10.5, 6.0), (3.8, 10.5, 6.0), "roof_stone"),
    )
    for values in rectangles:
        _rectangle(renderer, materials, *values)

    columns = ((-8.1, 0.0, -7.4), (-8.1, 0.0, -2.7), (-8.1, 0.0, 2.2),
               (-4.4, 0.0, -8.3), (8.7, 0.0, -7.4), (8.7, 0.0, -2.7),
               (9.30, 0.0, -1.35), (4.3, 0.0, -8.3))
    for index, base in enumerate(columns):
        _cylinder(renderer, materials, f"column_shaft_{index:02d}", base,
                  (0.0, 1.0, 0.0), 9.8, 0.64, "temple_carved_stone")
        _cylinder(renderer, materials, f"column_base_{index:02d}", base,
                  (0.0, 1.0, 0.0), 0.34, 0.86, "temple_wetstone")
        _cylinder(renderer, materials, f"column_band_{index:02d}",
                  _add(base, (0.0, 4.35, 0.0)), (0.0, 1.0, 0.0), 0.16, 0.70,
                  "temple_wetstone")
        _cylinder(renderer, materials, f"column_capital_{index:02d}",
                  _add(base, (0.0, 9.45, 0.0)), (0.0, 1.0, 0.0), 0.35, 0.88,
                  "roof_stone")

    _cylinder(renderer, materials, "altar_lower", (0.0, 0.0, -1.55),
              (0.0, 1.0, 0.0), 0.65, 1.75, "altar_obsidian")
    _cylinder(renderer, materials, "altar_upper", (0.0, 0.65, -1.55),
              (0.0, 1.0, 0.0), 0.55, 1.38, "temple_blackstone")
    renderer.object(name="altar_bowl", type="disk", center=(0.0, 1.22, -1.55),
                    normal=(0.0, 1.0, 0.0), radius=1.18,
                    material=materials["altar_obsidian"])
    for index in range(8):
        angle = 2.0 * math.pi * index / 8.0
        _cylinder(renderer, materials, f"altar_gold_inlay_{index:02d}",
                  (1.26 * math.cos(angle), 0.52, -1.55 + 1.26 * math.sin(angle)),
                  (0.0, 1.0, 0.0), 0.12, 0.075, "mechanism_gold")

    pool_rectangles = (
        ("pool_floor_shallow", (5.0, -0.75, 2.0), (5.0, -0.75, -5.8), (8.45, -0.75, -5.8), "pool_moss"),
        ("pool_floor_deep", (2.95, -2.55, 2.0), (2.95, -2.55, -5.8), (5.0, -2.55, -5.8), "pool_mosaic"),
        ("pool_depth_riser", (5.0, -2.55, 2.0), (5.0, -0.75, 2.0), (5.0, -0.75, -5.8), "pool_moss"),
        ("pool_left_wall", (2.95, -2.55, -5.8), (2.95, 0.50, -5.8), (2.95, 0.50, 2.0), "temple_wetstone"),
        ("pool_right_wall", (8.45, -2.55, 2.0), (8.45, 0.50, 2.0), (8.45, 0.50, -5.8), "temple_wetstone"),
        ("pool_back_wall", (2.95, -2.55, -5.8), (2.95, 0.50, -5.8), (8.45, 0.50, -5.8), "temple_wetstone"),
        ("pool_front_wall", (2.95, -2.55, 2.0), (8.45, -2.55, 2.0), (8.45, 0.50, 2.0), "temple_wetstone"),
    )
    for values in pool_rectangles:
        _rectangle(renderer, materials, *values)
    for index in range(9):
        x, z = 5.35 + 0.90 * (index % 3), -4.8 + 2.65 * (index // 3)
        _rectangle(renderer, materials, f"pool_moss_tile_{index:02d}",
                   (x, -0.735, z + 0.8), (x, -0.735, z),
                   (x + 0.72, -0.735, z),
                   "pool_moss" if index % 2 == 0 else "pool_mosaic")
    renderer.object(name="pool_water", type="water_surface", center=(5.7, 0.22, -1.9),
                    size=(5.4, 7.6), material=materials["oracle_water"],
                    waves=(({"direction": (1.0, 0.18), "amplitude": 0.065,
                             "wavelength": 2.7, "phase_radians": 0.55}),
                           ({"direction": (-0.32, 1.0), "amplitude": 0.038,
                             "wavelength": 1.55, "phase_radians": 2.15}),
                           ({"direction": (0.72, 1.0), "amplitude": 0.019,
                             "wavelength": 0.92, "phase_radians": 4.1})))

    for index in range(16):
        right, local = index >= 8, index % 8
        base = (9.38 if right else -9.38, 2.0 + 0.68 * (local % 4),
                -7.0 + 2.3 * (local // 4))
        _cylinder(renderer, materials, f"rune_stroke_{index:02d}", base,
                  (0.0, 0.58, 0.34 if local % 2 == 0 else -0.34),
                  0.78, 0.035, "rune_emitter")

    frost_centers = ((-4.02, 10.08, 2.92), (-3.38, 9.92, 3.18),
                     (-2.62, 10.14, 3.28), (-1.72, 9.96, 3.34),
                     (2.72, 10.10, 3.16), (3.32, 9.91, 2.76),
                     (3.48, 10.13, 1.96), (-4.06, 10.04, -4.78),
                     (-3.42, 9.88, -4.92), (2.56, 10.08, -4.96),
                     (3.22, 9.90, -4.84), (3.48, 10.12, -4.18))
    frost_radii = (0.14, 0.20, 0.12, 0.17, 0.13, 0.19,
                   0.11, 0.18, 0.12, 0.16, 0.11, 0.15)
    for index, center in enumerate(frost_centers):
        renderer.object(name=f"frost_crystal_{index:02d}", type="sphere", center=center,
                        radius=frost_radii[index], material=materials["frost_ice"])

    godray_axis = _unit(GODRAY_AXIS, (0.0, -1.0, 0.0))
    godray_u = _unit((0.63, 0.0, 0.50), (1.0, 0.0, 0.0))
    godray_v = _unit(_cross(godray_axis, godray_u), (0.0, 0.0, 1.0))
    for index in range(30):
        fraction = (index + 0.5) / 30.0
        distance = 0.70 + 13.50 * fraction
        angle = 2.0 * math.pi * 0.61803398875 * index
        jitter = 0.05 + 0.15 * (index % 5) / 4.0
        center = _add(_add(_add(GODRAY_ORIGIN, _mul(godray_axis, distance)),
                           _mul(godray_u, jitter * math.cos(angle))),
                      _mul(godray_v, jitter * math.sin(angle)))
        renderer.object(name=f"dust_mote_{index:02d}", type="sphere", center=center,
                        radius=0.018 + 0.006 * (index % 3),
                        material=materials["dust_gold"])


def _add_lights(renderer: Renderer) -> None:
    dawn = _unit(tuple(-value for value in GODRAY_AXIS), (0.0, 1.0, 0.0))
    renderer.light(name="dawn_directional", type="directional", direction=dawn,
                   irradiance=(1.65, 2.25, 3.6))
    flame_definitions = (
        ("altar_white_core", (0.0, 1.20, -1.55), (0.02, 1.0, -0.03), 1.35, 0.72, 0.26,
         (95.0, 52.0, 12.0), (52.0, 10.0, 0.25), 2.0, 0.72, 0.52, 4.4, 909),
        ("altar_main_flame", (-0.12, 1.35, -1.58), (-0.08, 1.0, 0.02), 2.65, 0.58, 0.15,
         (72.0, 18.0, 0.55), (11.0, 0.75, 0.015), 1.78, 0.61, 0.86, 3.65, 1909),
        ("altar_side_tongue", (0.48, 1.42, -1.42), (0.28, 1.0, 0.09), 1.95, 0.34, 0.08,
         (58.0, 10.0, 0.2), (6.0, 0.25, 0.004), 1.46, 0.51, 0.93, 5.1, 2909),
        ("smoke_lower", (0.25, 3.15, -1.62), (0.10, 1.0, -0.04), 3.4, 0.62, 0.92,
         (0.018, 0.014, 0.008), (0.004, 0.005, 0.008), 1.744, 0.752, 0.88, 2.75, 3909),
        ("smoke_upper", (0.81, 5.65, -1.78), (-0.12, 1.0, -0.10), 2.85, 0.82, 0.68,
         (0.009, 0.008, 0.009), (0.002, 0.003, 0.006), 1.616, 0.704, 0.79, 2.35, 4909),
        ("dawn_godray", GODRAY_ORIGIN, GODRAY_AXIS, 15.2, 0.46, 0.82,
         (0.10, 0.25, 0.50), (0.04, 0.12, 0.28), 0.25, 0.45, 0.12, 1.0, 5909),
    )
    for (name, position, axis, height, radius_start, radius_end, emission_start,
         emission_end, extinction, density_scale, turbulence, noise_scale,
         seed) in flame_definitions:
        renderer.light(name=name, type="flame", position=position,
                       axis=_unit(axis, (0.0, 1.0, 0.0)), height=height,
                       radius_start=radius_start, radius_end=radius_end,
                       emission_start=emission_start, emission_end=emission_end,
                       extinction=extinction, density_scale=density_scale,
                       turbulence=turbulence, noise_scale=noise_scale, seed=seed)
    for index, position, intensity in (
        (0, (-9.0, 3.2, -5.8), (1.6, 7.2, 13.5)),
        (1, (-9.0, 4.2, -2.5), (1.4, 6.5, 12.0)),
        (2, (9.0, 3.2, -5.8), (1.6, 7.2, 13.5)),
        (3, (9.0, 4.2, -2.5), (1.4, 6.5, 12.0)),
    ):
        renderer.light(name=f"rune_point_{index:02d}", type="point",
                       position=position, intensity=intensity)


def create_renderer(physics: PhysicsWorld, *, metadata_output: Path | None = None,
                    verify: bool = False) -> Renderer:
    if (physics.scene_name != "lava-temple-oracle" or physics.seed != SEED or
            physics.steps != STEPS or
            physics.gravity != (0.0, -9.81, 0.0) or
            not math.isclose(physics.fixed_dt, FIXED_DT, abs_tol=1.0e-12)):
        raise ValueError("physics must come from create_physics_world()")
    renderer = Renderer(device=physics.device, scene_name="lava-temple-oracle")
    renderer.integrator(direct_light_sampling="importance", clamp_direct=64.0,
                        clamp_indirect=16.0)
    renderer.camera(look_from=(8.2, 6.65, 19.8), look_at=(0.2, 4.15, -1.65),
                    up=(0.0, 1.0, 0.0), vfov=29.5, aperture=0.012,
                    focus_distance=23.05)
    renderer.background(type="sky", bottom=(0.003, 0.005, 0.012),
                        top=(0.008, 0.016, 0.028),
                        sun_direction=_unit(tuple(-value for value in GODRAY_AXIS),
                                            (0.0, 1.0, 0.0)),
                        sun_color=(0.0, 0.0, 0.0), sun_cos_angle=2.0,
                        exposure=0.0)
    definitions = (
        ("temple_blackstone", "lambertian", {"base_color": (0.070, 0.075, 0.085)}),
        ("temple_carved_stone", "lambertian", {"base_color": (0.115, 0.120, 0.130)}),
        ("temple_floorstone", "lambertian", {"base_color": (0.065, 0.058, 0.060)}),
        ("temple_wetstone", "lambertian", {"base_color": (0.075, 0.095, 0.105)}),
        ("roof_stone", "lambertian", {"base_color": (0.040, 0.043, 0.050)}),
        ("altar_obsidian", "metal", {"base_color": (0.105, 0.085, 0.075), "roughness": 0.47}),
        ("pool_mosaic", "lambertian", {"base_color": (0.030, 0.135, 0.175)}),
        ("pool_moss", "lambertian", {"base_color": (0.065, 0.165, 0.095)}),
        ("oracle_water", "water", {"roughness": 0.11, "ior": 1.333,
                                      "absorption": (0.42, 0.085, 0.026)}),
        ("frost_ice", "metal", {"base_color": (0.65, 0.82, 0.95), "roughness": 0.42}),
        ("shell_dark_metal", "metal", {"base_color": (0.34, 0.36, 0.40), "roughness": 0.48}),
        ("shell_inner_gold", "metal", {"base_color": (0.92, 0.58, 0.12), "roughness": 0.23}),
        ("mechanism_gold", "metal", {"base_color": (0.96, 0.68, 0.16), "roughness": 0.18}),
        ("mechanism_copper", "metal", {"base_color": (0.80, 0.28, 0.07), "roughness": 0.26}),
        ("visor_metal", "metal", {"base_color": (0.055, 0.095, 0.12), "roughness": 0.14}),
        ("limb_metal", "metal", {"base_color": (0.31, 0.34, 0.38), "roughness": 0.44}),
        ("eye_emitter", "emitter", {"emission": (0.8, 5.5, 9.5)}),
        ("oracle_core_emitter", "emitter", {"emission": (1.2, 5.5, 12.0)}),
        ("spark_emitter", "emitter", {"emission": (24.0, 6.0, 0.18)}),
        ("rune_emitter", "emitter", {"emission": (0.08, 1.7, 3.8)}),
        ("dust_gold", "lambertian", {"base_color": (0.90, 0.52, 0.12)}),
    )
    materials = {name: renderer.material(name=name, type=kind, **parameters)
                 for name, kind, parameters in definitions}
    _static_temple(renderer, materials)
    _populate_physics(physics, materials)
    result = physics.simulate(metadata_output=metadata_output, verify=verify,
                            validator=_validate)
    result.apply_to(renderer)
    _add_lights(renderer)
    return renderer


def main() -> None:
    output = ROOT / "output/examples/lava-temple-oracle.png"
    physics = create_physics_world()
    renderer = create_renderer(physics,
                               metadata_output=output.with_suffix(".physics.json"),
                               verify=True)
    renderer.render(output=output, stats_output=output.with_suffix(".stats.json"),
                    width=3840, height=2160, spp=2048, depth=12, seed=SEED,
                    denoise=True)


if __name__ == "__main__":
    main()
