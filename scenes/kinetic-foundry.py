#!/usr/bin/env python3
"""Kinetic Foundry: a live PhysX GPU collision captured at impact peak."""

from __future__ import annotations

import math
from pathlib import Path

from spectraldock import PhysicsResult, PhysicsWorld, Renderer


ROOT = Path(__file__).resolve().parents[1]
SEED = 20260711
FIXED_DT = 1.0 / 120.0
STEPS = 300


class _SplitMix64:
    def __init__(self, seed: int) -> None:
        self.state = seed & 0xFFFFFFFFFFFFFFFF

    def next(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        value = self.state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        return value ^ (value >> 31)

    def symmetric(self, magnitude: float) -> float:
        unit = (self.next() >> 11) / float(1 << 53)
        return (2.0 * unit - 1.0) * magnitude


def _quat_degrees(angle: float, axis: tuple[float, float, float]) -> tuple[float, ...]:
    length = math.sqrt(sum(value * value for value in axis))
    sine = math.sin(math.radians(angle) * 0.5) / length
    return axis[0] * sine, axis[1] * sine, axis[2] * sine, math.cos(math.radians(angle) * 0.5)


def _rotate(quaternion: tuple[float, ...], point: tuple[float, ...]) -> tuple[float, float, float]:
    x, y, z, w = quaternion
    px, py, pz = point
    tx, ty, tz = 2.0 * (y * pz - z * py), 2.0 * (z * px - x * pz), 2.0 * (x * py - y * px)
    return (px + w * tx + y * tz - z * ty,
            py + w * ty + z * tx - x * tz,
            pz + w * tz + x * ty - y * tx)


def _transform(position: tuple[float, ...], quaternion: tuple[float, ...],
               point: tuple[float, ...]) -> tuple[float, float, float]:
    rotated = _rotate(quaternion, point)
    return tuple(position[index] + rotated[index] for index in range(3))  # type: ignore[return-value]


def create_physics_world(*, device: int = 0) -> PhysicsWorld:
    return PhysicsWorld(device=device, seed=SEED, fixed_dt=FIXED_DT, steps=STEPS,
                        gravity=(0.0, -9.81, 0.0), scene_name="kinetic-foundry")


def _validate(result: PhysicsResult) -> bool:
    mascots = [body for body in result.bodies if body.category == "mascot"]
    if len(mascots) != 24 or len(result.bodies) != 216:
        return False
    threshold = math.cos(math.radians(15.0))
    toppled = 0
    for body in mascots:
        if _rotate(body.rotation, (0.0, 1.0, 0.0))[1] < threshold:
            toppled += 1
    return toppled >= 12


def _populate_physics(world: PhysicsWorld,
                      render_materials: dict[str, object], mascot: object) -> None:
    contact = world.material("foundry_contact", static_friction=0.58,
                             dynamic_friction=0.52, restitution=0.04)
    world.static_plane("ground_collision", material=contact)
    for name, position, extents in (
        ("left_boundary", (-7.15, 1.0, 0.0), (0.15, 1.0, 4.6)),
        ("right_boundary", (7.15, 1.0, 0.0), (0.15, 1.0, 4.6)),
        ("back_boundary", (0.0, 1.0, -4.45), (7.0, 1.0, 0.15)),
        ("front_boundary", (0.0, 1.0, 4.45), (7.0, 1.0, 0.15)),
    ):
        world.static_box(name, position=position, half_extents=extents, material=contact)

    chute_poses = (
        ((-4.4, 3.4, 0.0), _quat_degrees(-30.0, (0.0, 0.0, 1.0))),
        ((4.4, 3.4, 0.0), _quat_degrees(30.0, (0.0, 0.0, 1.0))),
    )
    for side, (position, rotation) in enumerate(chute_poses):
        world.static_box(f"chute_{side}_surface_collision", position=position,
                         rotation=rotation, half_extents=(3.5, 0.12, 1.35),
                         material=contact)
        for rail, z in enumerate((-1.43, 1.43)):
            world.static_box(f"chute_{side}_rail_{rail}_collision",
                             position=_transform(position, rotation, (0.0, 0.45, z)),
                             rotation=rotation, half_extents=(3.5, 0.35, 0.08),
                             material=contact)

    random = _SplitMix64(world.seed)
    mascot_materials = ("mascot_vermilion", "mascot_gold", "mascot_cyan", "mascot_ivory")
    capsule_rotation = _quat_degrees(90.0, (0.0, 0.0, 1.0))
    for side, (chute_position, chute_rotation) in enumerate(chute_poses):
        direction = -1.0 if side == 0 else 1.0
        for row in range(6):
            for lane in range(2):
                index = side * 12 + row * 2 + lane
                local = (direction * (2.55 - row),
                         0.97 + random.symmetric(0.015),
                         -0.52 if lane == 0 else 0.52)
                position = _transform(chute_position, chute_rotation, local)
                body = world.rigid_body(
                    f"mascot_body_{index:02d}", category="mascot", position=position,
                    rotation=_quat_degrees(random.symmetric(15.0), (0.0, 1.0, 0.0)),
                    density=2.4, linear_damping=0.08, angular_damping=0.12,
                )
                body.capsule(0.42, 0.28, contact, local_rotation=capsule_rotation)
                material_name = mascot_materials[index % len(mascot_materials)]
                body.attach_mesh(f"mascot_{index:02d}", mascot,
                                 local_translate=(0.0, -0.7, 0.0),
                                 scale=(0.7, 0.7, 0.7),
                                 material=render_materials[material_name])

    bead_materials = ("bead_copper", "bead_blue", "bead_silver")
    for side, (chute_position, chute_rotation) in enumerate(chute_poses):
        direction = -1.0 if side == 0 else 1.0
        for layer in range(6):
            for along in range(4):
                for across in range(4):
                    local_index = layer * 16 + along * 4 + across
                    index = side * 96 + local_index
                    radius = 0.12 + 0.01 * (random.next() % 8)
                    local = (direction * (2.75 - 0.44 * along) + random.symmetric(0.012),
                             2.05 + 0.44 * layer + random.symmetric(0.012),
                             -0.72 + 0.48 * across + random.symmetric(0.012))
                    body = world.rigid_body(
                        f"bead_body_{index:03d}", category="bead",
                        position=_transform(chute_position, chute_rotation, local),
                        density=0.85, linear_damping=0.08, angular_damping=0.12,
                    )
                    body.sphere(radius, contact)
                    body.attach_sphere(f"bead_{index:03d}", (0.0, 0.0, 0.0), radius,
                                       render_materials[bead_materials[index % 3]])


def create_renderer(physics: PhysicsWorld, *, metadata_output: Path | None = None,
                    verify: bool = False) -> Renderer:
    if (physics.scene_name != "kinetic-foundry" or physics.seed != SEED or
            physics.steps != STEPS or
            physics.gravity != (0.0, -9.81, 0.0) or
            not math.isclose(physics.fixed_dt, FIXED_DT, abs_tol=1.0e-12)):
        raise ValueError("physics must come from create_physics_world()")
    renderer = Renderer(device=physics.device, scene_name="kinetic-foundry")
    renderer.integrator(direct_light_sampling="importance", clamp_direct=64.0,
                        clamp_indirect=16.0)
    renderer.camera(look_from=(0.0, 8.0, 17.0), look_at=(0.0, 1.2, 0.0),
                    up=(0.0, 1.0, 0.0), vfov=36.0, aperture=0.035,
                    focus_distance=18.3)
    renderer.background(type="sky", bottom=(0.025, 0.04, 0.07),
                        top=(0.002, 0.006, 0.015),
                        sun_direction=(-0.45, 0.74, -0.5),
                        sun_color=(2.8, 2.1, 1.3), sun_cos_angle=0.996,
                        exposure=0.0)

    definitions = (
        ("floor", "lambertian", {"base_color": (0.10, 0.13, 0.17)}),
        ("wall", "lambertian", {"base_color": (0.12, 0.15, 0.22)}),
        ("chute_hot", "lambertian", {"base_color": (0.62, 0.18, 0.035)}),
        ("chute_cool", "lambertian", {"base_color": (0.035, 0.25, 0.48)}),
        ("mascot_vermilion", "lambertian", {"base_color": (0.82, 0.10, 0.045)}),
        ("mascot_gold", "metal", {"base_color": (0.88, 0.50, 0.09), "roughness": 0.24}),
        ("mascot_cyan", "lambertian", {"base_color": (0.035, 0.42, 0.62)}),
        ("mascot_ivory", "lambertian", {"base_color": (0.86, 0.84, 0.74)}),
        ("bead_copper", "metal", {"base_color": (0.72, 0.28, 0.08), "roughness": 0.18}),
        ("bead_blue", "metal", {"base_color": (0.04, 0.22, 0.55), "roughness": 0.16}),
        ("bead_silver", "metal", {"base_color": (0.72, 0.76, 0.80), "roughness": 0.12}),
    )
    materials = {name: renderer.material(name=name, type=kind, **parameters)
                 for name, kind, parameters in definitions}
    mascot = renderer.mesh(name="mascot",
                           path=ROOT / "assets/examples/models/capsule-mascot.obj")
    renderer.object(name="pool_floor", type="rectangle", p1=(-8.0, 0.0, 5.0),
                    p2=(-8.0, 0.0, -5.0), p3=(8.0, 0.0, -5.0),
                    material=materials["floor"])
    renderer.object(name="pool_back", type="rectangle", p1=(-8.0, 0.0, -4.4),
                    p2=(-8.0, 5.5, -4.4), p3=(8.0, 5.5, -4.4),
                    material=materials["wall"])
    for name, position, rotation, material in (
        ("left_chute", (-4.4, 3.4, 0.0), _quat_degrees(-30.0, (0.0, 0.0, 1.0)), materials["chute_hot"]),
        ("right_chute", (4.4, 3.4, 0.0), _quat_degrees(30.0, (0.0, 0.0, 1.0)), materials["chute_cool"]),
    ):
        renderer.object(name=name, type="rectangle",
                        p1=_transform(position, rotation, (-3.5, 0.12, 1.35)),
                        p2=_transform(position, rotation, (-3.5, 0.12, -1.35)),
                        p3=_transform(position, rotation, (3.5, 0.12, -1.35)),
                        material=material)

    _populate_physics(physics, materials, mascot)
    result = physics.simulate(metadata_output=metadata_output, verify=verify,
                            validator=_validate)
    result.apply_to(renderer)
    renderer.light(name="foundry_key", type="rectangle", position=(-5.0, 9.0, 3.0),
                   edge_u=(0.0, 0.0, -5.5), edge_v=(10.0, 0.0, 0.0),
                   emission=(14.0, 10.0, 6.0))
    renderer.light(name="foundry_fill", type="disk", position=(7.0, 5.5, 7.5),
                   normal=(-0.6, -0.35, -0.72), radius=2.0,
                   emission=(3.0, 6.0, 12.0))
    renderer.light(name="foundry_rim", type="sphere", position=(-6.0, 4.2, -2.5),
                   radius=0.55, emission=(8.0, 2.4, 0.8))
    return renderer


def main() -> None:
    output = ROOT / "output/examples/kinetic-foundry.png"
    physics = create_physics_world()
    renderer = create_renderer(physics,
                               metadata_output=output.with_suffix(".physics.json"),
                               verify=True)
    renderer.render(output=output, stats_output=output.with_suffix(".stats.json"),
                    width=1920, height=1080, spp=512, depth=12, seed=SEED,
                    denoise=True)


if __name__ == "__main__":
    main()
