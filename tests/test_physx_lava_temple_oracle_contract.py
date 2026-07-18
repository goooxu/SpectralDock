from dataclasses import replace
import importlib.util
import math
from pathlib import Path

import pytest

import spectraldock.physics as physics
from spectraldock.physics import BodyState, PhysicsError, PhysicsResult, PhysicsWorld


ROOT = Path(__file__).resolve().parents[1]
COVER_SCENE = ROOT / "scenes" / "lava-temple-oracle.py"


def load_cover_scene():
    spec = importlib.util.spec_from_file_location(
        "spectraldock_lava_temple_oracle_contract", COVER_SCENE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COVER = load_cover_scene()


def make_world(**overrides):
    parameters = {
        "device": 0,
        "seed": 17,
        "fixed_dt": 1.0 / 120.0,
        "steps": 24,
        "gravity": (0.0, -9.81, 0.0),
        "scene_name": "host-contract",
    }
    parameters.update(overrides)
    return PhysicsWorld(**parameters)


def contact_material(world, name="contact"):
    return world.material(
        name,
        static_friction=0.6,
        dynamic_friction=0.4,
        restitution=0.2,
    )


def make_result(*, bodies, attachments=(), source_attachments=(), **overrides):
    parameters = {
        "scene_name": "host-contract",
        "seed": 17,
        "device": 0,
        "device_name": "Synthetic NVIDIA GPU",
        "backend": "physx-gpu",
        "physx_version": (5 << 24) | (8 << 16),
        "physx_commit": physics._PHYSX_COMMIT,
        "cuda_runtime_version": 12080,
        "cuda_context_valid": True,
        "gpu_dynamics": True,
        "gpu_broad_phase": True,
        "tgs_solver": True,
        "pcm": True,
        "stabilization": True,
        "cpu_fallback": False,
        "enhanced_determinism": False,
        "gpu_statistics": physics._GpuPipelineStatistics(
            samples=24,
            heap_bytes=16_384,
            broad_phase_bytes=1_024,
            narrow_phase_bytes=2_048,
            solver_bytes=4_096,
            simulation_bytes=8_192,
        ),
        "fixed_dt": 1.0 / 120.0,
        "steps": 24,
        "gravity": (0.0, -9.81, 0.0),
        "bodies": tuple(bodies),
        "attachments": tuple(attachments),
        "source_attachments": tuple(source_attachments),
    }
    parameters.update(overrides)
    if "steps" in overrides and "gpu_statistics" not in overrides:
        parameters["gpu_statistics"] = replace(
            parameters["gpu_statistics"], samples=parameters["steps"]
        )
    return PhysicsResult(**parameters)


def body_state(
    name="body",
    *,
    category="part",
    initial_position=(0.0, 0.0, 0.0),
    position=(0.0, 0.1, 0.0),
    rotation=(0.0, 0.0, 0.0, 1.0),
    linear_velocity=(0.0, 1.0, 0.0),
    angular_velocity=(0.0, 0.1, 0.0),
    sleeping=False,
):
    return BodyState(
        name=name,
        category=category,
        initial_position=initial_position,
        initial_rotation=(0.0, 0.0, 0.0, 1.0),
        position=position,
        rotation=rotation,
        linear_velocity=linear_velocity,
        angular_velocity=angular_velocity,
        sleeping=sleeping,
    )


def test_cover_factory_owns_the_fixed_physx_capture_contract():
    world = COVER.create_physics_world(device=3)

    assert world.device == 3
    assert world.seed == COVER.SEED == 909
    assert world.steps == COVER.STEPS == 24
    assert math.isclose(world.fixed_dt, COVER.FIXED_DT, rel_tol=0.0, abs_tol=1.0e-15)
    assert world.gravity == (0.0, -9.81, 0.0)
    assert world.scene_name == "lava-temple-oracle"


@pytest.mark.parametrize(
    "parameters, message",
    [
        ({"device": -1}, "device"),
        ({"seed": -1}, "seed"),
        ({"seed": 1 << 64}, "seed"),
        ({"fixed_dt": 0.0}, "fixed_dt"),
        ({"steps": 0}, "steps"),
        ({"gravity": (0.0, float("inf"), 0.0)}, "gravity"),
        ({"scene_name": " "}, "scene_name"),
    ],
)
def test_world_rejects_invalid_core_parameters(parameters, message):
    with pytest.raises(ValueError, match=message):
        make_world(**parameters)


def test_material_body_shape_and_attachment_parameters_are_checked():
    world = make_world()

    with pytest.raises(ValueError, match="friction"):
        world.material("negative", static_friction=-0.1,
                       dynamic_friction=0.2, restitution=0.0)
    with pytest.raises(ValueError, match="restitution"):
        world.material("bouncy", static_friction=0.1,
                       dynamic_friction=0.1, restitution=1.01)

    contact = contact_material(world)
    with pytest.raises(ValueError, match="duplicate PhysX material"):
        contact_material(world)
    with pytest.raises(ValueError, match="density"):
        world.rigid_body("zero-density", category="part", position=(0.0, 0.0, 0.0),
                         density=0.0)
    with pytest.raises(ValueError, match="zero quaternion"):
        world.rigid_body("zero-rotation", category="part", position=(0.0, 0.0, 0.0),
                         rotation=(0.0, 0.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="solver iteration"):
        world.rigid_body("bad-solver", category="part", position=(0.0, 0.0, 0.0),
                         solver_iterations=(0, 2))

    body = world.rigid_body("valid", category="part", position=(0.0, 1.0, 0.0))
    with pytest.raises(ValueError, match="half_extents"):
        body.box((1.0, 0.0, 1.0), contact)
    with pytest.raises(ValueError, match="renderer material"):
        body.attach_sphere("missing-material", (0.0, 0.0, 0.0), 0.2, None)
    with pytest.raises(ValueError, match="renderer mesh"):
        body.attach_mesh("missing-mesh", None, material=object())


def test_contact_materials_cannot_cross_physics_worlds():
    first = make_world(scene_name="first")
    second = make_world(scene_name="second")
    foreign = contact_material(first)
    local = contact_material(second)

    with pytest.raises(ValueError, match="different PhysicsWorld"):
        second.static_plane("ground", material=foreign)

    body = second.rigid_body("body", category="part", position=(0.0, 1.0, 0.0))
    with pytest.raises(ValueError, match="different PhysicsWorld"):
        body.sphere(0.25, foreign)

    body.sphere(0.25, local)


def test_request_requires_material_body_and_collision_shape_without_a_worker():
    empty = make_world()
    with pytest.raises(PhysicsError, match="contact material"):
        empty._encode(empty.seed)

    no_body = make_world()
    contact_material(no_body)
    with pytest.raises(PhysicsError, match="rigid body"):
        no_body._encode(no_body.seed)

    no_shape = make_world()
    contact_material(no_shape)
    no_shape.rigid_body("body", category="part", position=(0.0, 1.0, 0.0))
    with pytest.raises(PhysicsError, match="no collision shape"):
        no_shape._encode(no_shape.seed)


def typed_attachment_result():
    world = make_world()
    contact = contact_material(world)
    body = world.rigid_body("body", category="part", position=(0.0, 1.0, 0.0))
    body.box((0.5, 0.5, 0.5), contact)

    renderer_material = object()
    renderer_mesh = object()
    body.attach_sphere("sphere", (0.0, 0.0, 0.0), 0.5, renderer_material)
    body.attach_rectangle("rectangle", (-1.0, 0.0, 1.0),
                          (-1.0, 0.0, -1.0), (1.0, 0.0, -1.0),
                          renderer_material)
    body.attach_cylinder("cylinder", (0.0, 0.0, 0.0),
                         (0.0, 1.0, 0.0), 2.0, 0.25,
                         renderer_material)
    body.attach_disk("disk", (0.0, 0.0, 0.0),
                     (0.0, 1.0, 0.0), 0.75, renderer_material)
    body.attach_mesh("mesh", renderer_mesh, local_translate=(0.0, -0.5, 0.0),
                     scale=(0.7, 0.7, 0.7), material=renderer_material)

    attachments = (
        physics._BakedAttachment(0, 0, 1, (1.0, 2.0, 3.0, 0.5)),
        physics._BakedAttachment(
            1, 0, 2,
            (-1.0, 0.0, 1.0, -1.0, 0.0, -1.0, 1.0, 0.0, -1.0),
        ),
        physics._BakedAttachment(
            2, 0, 3, (0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 2.0, 0.25)
        ),
        physics._BakedAttachment(3, 0, 4, (0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.75)),
        physics._BakedAttachment(
            4, 0, 5, (4.0, 5.0, 6.0, 10.0, 20.0, 30.0, 0.7, 0.7, 0.7)
        ),
    )
    result = make_result(
        bodies=(body_state(position=(0.0, 1.0, 0.0)),),
        attachments=attachments,
        source_attachments=world._source_attachments(),
    )
    return result, renderer_material, renderer_mesh


class RecordingRenderer:
    def __init__(self):
        self.objects = []

    def object(self, **parameters):
        self.objects.append(parameters)
        return parameters["name"]


def test_typed_result_applies_every_attachment_without_serializing_handles():
    result, renderer_material, renderer_mesh = typed_attachment_result()
    renderer = RecordingRenderer()

    assert result.apply_to(renderer) is renderer
    assert [item["type"] for item in renderer.objects] == [
        "sphere", "rectangle", "cylinder", "disk", "mesh"
    ]
    assert [item["name"] for item in renderer.objects] == [
        "sphere", "rectangle", "cylinder", "disk", "mesh"
    ]
    assert all(item["material"] is renderer_material for item in renderer.objects)
    assert renderer.objects[0]["center"] == (1.0, 2.0, 3.0)
    assert renderer.objects[4]["mesh"] is renderer_mesh
    assert renderer.objects[4]["translate"] == (4.0, 5.0, 6.0)
    assert renderer.objects[4]["rotate_degrees"] == (10.0, 20.0, 30.0)
    assert renderer.objects[4]["scale"] == (0.7, 0.7, 0.7)


@pytest.mark.parametrize(
    "mutation, message",
    [
        (
            lambda result: setattr(result, "_attachments", result._attachments[:-1]),
            "attachment count",
        ),
        (
            lambda result: setattr(
                result,
                "_attachments",
                (replace(result._attachments[0], kind=2),) + result._attachments[1:],
            ),
            "changed an attachment type",
        ),
        (
            lambda result: setattr(
                result,
                "_attachments",
                (result._attachments[0], replace(result._attachments[1], index=0))
                + result._attachments[2:],
            ),
            "invalid attachment index",
        ),
        (
            lambda result: setattr(
                result,
                "_attachments",
                (replace(result._attachments[0], body_index=1),)
                + result._attachments[1:],
            ),
            "invalid attachment body index",
        ),
        (
            lambda result: setattr(
                result,
                "bodies",
                (replace(result.bodies[0], rotation=(0.0, 0.0, 0.0, 2.0)),),
            ),
            "non-unit rotation",
        ),
    ],
)
def test_result_rejects_broken_attachment_and_pose_contracts(mutation, message):
    result, _, _ = typed_attachment_result()
    mutation(result)

    with pytest.raises(PhysicsError, match=message):
        result.validate()


@pytest.mark.parametrize(
    "attribute, value, message",
    [
        ("backend", "cpu", "CPU fallback"),
        ("physx_commit", "wrong-revision", "pinned 5.8.0"),
        ("cuda_runtime_version", 13030, "CUDA 12.8"),
        ("device_name", "", "CUDA device"),
        ("cuda_context_valid", False, "invalid CUDA context"),
        ("cpu_fallback", True, "CPU fallback"),
        ("gpu_dynamics", False, "GPU dynamics"),
        ("gpu_broad_phase", False, "GPU broadphase"),
        ("tgs_solver", False, "TGS solver"),
        ("pcm", False, "GPU scene flags"),
        ("stabilization", False, "GPU scene flags"),
        ("enhanced_determinism", True, "GPU scene flags"),
    ],
)
def test_result_rejects_wrong_gpu_worker_identity(attribute, value, message):
    result, _, _ = typed_attachment_result()
    setattr(result, attribute, value)

    with pytest.raises(PhysicsError, match=message):
        result.validate()


@pytest.mark.parametrize(
    "statistics, message",
    [
        (
            physics._GpuPipelineStatistics(23, 16_384, 1_024, 2_048, 4_096, 8_192),
            "one GPU statistics sample per step",
        ),
        (
            physics._GpuPipelineStatistics(24, 16_384, 0, 2_048, 4_096, 8_192),
            "zero GPU pipeline heap",
        ),
        (
            physics._GpuPipelineStatistics(24, 16_384, 32_768, 2_048, 4_096, 8_192),
            "inconsistent GPU heap",
        ),
    ],
)
def test_result_rejects_missing_gpu_pipeline_evidence(statistics, message):
    result, _, _ = typed_attachment_result()
    result._gpu_statistics = statistics

    with pytest.raises(PhysicsError, match=message):
        result.validate()


def test_metadata_reports_measured_gpu_only_pipeline_and_dispatcher_role():
    result, _, _ = typed_attachment_result()

    metadata = result.metadata()

    assert metadata["schema_version"] == 2
    assert metadata["backend"]["mode"] == "gpu"
    assert metadata["backend"]["cuda_context_valid"] is True
    assert metadata["backend"]["cpu_fallback"] is False
    assert metadata["backend"]["cpu_dispatcher_role"] == "host-task-scheduling-only"
    assert metadata["backend"]["gpu_heap_bytes"] == {
        "samples": 24,
        "total": 16_384,
        "broad_phase": 1_024,
        "narrow_phase": 2_048,
        "solver": 4_096,
        "simulation": 8_192,
    }


def test_request_protocol_scalars_are_explicitly_little_endian():
    world = make_world(device=0x01020304, seed=0x0102030405060708)
    contact = contact_material(world)
    world.rigid_body("body", category="part", position=(0.0, 1.0, 0.0)).sphere(
        0.25, contact
    )

    encoded = world._encode(world.seed)

    assert encoded[:8] == b"SDPXRQ2\0"
    assert encoded[8:12] == b"\x02\x00\x00\x00"
    assert encoded[12:16] == b"\x04\x03\x02\x01"
    assert encoded[16:24] == b"\x08\x07\x06\x05\x04\x03\x02\x01"


def cover_bodies():
    result = []
    for index in range(130):
        quadrant = index % 4
        x = 0.2 if quadrant in (0, 1) else -0.2
        z = 0.2 if quadrant in (0, 2) else -0.2
        result.append(body_state(
            f"cover_{index:03d}",
            initial_position=(0.0, 5.0, 0.0),
            position=(x, 5.1, z),
            linear_velocity=(x * 10.0, 2.0, z * 10.0),
            angular_velocity=(0.1, 0.2, 0.3),
        ))
    return tuple(result)


def cover_result(bodies=None):
    return make_result(
        scene_name="lava-temple-oracle",
        seed=COVER.SEED,
        fixed_dt=COVER.FIXED_DT,
        steps=COVER.STEPS,
        bodies=cover_bodies() if bodies is None else bodies,
    )


def drop_one_body(bodies):
    return bodies[:-1]


def make_one_body_sleep(bodies):
    return (replace(bodies[0], sleeping=True),) + bodies[1:]


def move_one_body_out_of_bounds(bodies):
    return (replace(bodies[0], position=(12.01, 5.1, 0.2)),) + bodies[1:]


def fall_below_motion_thresholds(bodies):
    modified = list(bodies)
    for index in range(11):
        modified[index] = replace(
            modified[index],
            position=modified[index].initial_position,
            linear_velocity=(0.0, 0.0, 0.0),
            angular_velocity=(0.0, 0.0, 0.0),
        )
    return tuple(modified)


def remove_one_explosion_quadrant(bodies):
    modified = []
    for body in bodies:
        x, y, z = body.position
        if x < 0.0 and z < 0.0:
            body = replace(body, position=(-x, y, -z))
        modified.append(body)
    return tuple(modified)


def remove_upward_displacement(bodies):
    return tuple(replace(
        body,
        position=(body.position[0], body.initial_position[1], body.position[2]),
    ) for body in bodies)


def test_cover_validator_accepts_a_representative_130_body_explosion():
    result = cover_result()

    result.validate()
    assert COVER._validate(result)
    PhysicsWorld._accept(result, COVER._validate)


@pytest.mark.parametrize(
    "mutation",
    [
        drop_one_body,
        make_one_body_sleep,
        move_one_body_out_of_bounds,
        fall_below_motion_thresholds,
        remove_one_explosion_quadrant,
        remove_upward_displacement,
    ],
    ids=(
        "body-count",
        "sleeping",
        "bounds",
        "motion-thresholds",
        "quadrant-coverage",
        "upward-displacement",
    ),
)
def test_cover_validator_rejects_representative_invalid_states(mutation):
    rejected = cover_result(mutation(cover_bodies()))

    rejected.validate()
    assert not COVER._validate(rejected)
    with pytest.raises(PhysicsError, match="scene-specific"):
        PhysicsWorld._accept(rejected, COVER._validate)
