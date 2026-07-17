from dataclasses import replace
import importlib.util
import math
from pathlib import Path
import sys
from types import SimpleNamespace

from spectraldock.physics import BodyState


ROOT = Path(__file__).resolve().parents[1]
SCENE_PATH = ROOT / "scenes" / "atelier.py"


def load_scene():
    spec = importlib.util.spec_from_file_location("spectraldock_atelier_contract", SCENE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ATELIER = load_scene()


def body_state(
    name,
    category,
    *,
    initial_position,
    position,
    rotation=(0.0, 0.0, 0.0, 1.0),
    linear_velocity=(0.0, 0.0, 0.0),
    angular_velocity=(0.0, 0.0, 0.0),
    sleeping=True,
):
    return BodyState(
        name=name,
        category=category,
        initial_position=initial_position,
        initial_rotation=rotation,
        position=position,
        rotation=rotation,
        linear_velocity=linear_velocity,
        angular_velocity=angular_velocity,
        sleeping=sleeping,
    )


def accepted_bodies():
    bodies = []
    for index in range(9):
        x = -2.4 + 0.48 * index
        bodies.append(
            body_state(
                f"brick_body_{index:02d}",
                "brick",
                initial_position=(x, 2.2 + 0.1 * index, -1.5),
                position=(x, 0.18, -1.5),
            )
        )
    bodies.extend(
        (
            body_state(
                "metal_ball_body",
                "metal_ball",
                initial_position=(-3.1, 4.15, 0.95),
                position=(-3.1, 0.52, 0.95),
            ),
            body_state(
                "frosted_ball_body",
                "frosted_ball",
                initial_position=(0.55, 3.8, 1.65),
                position=(0.55, 0.60, 1.65),
            ),
            body_state(
                "capsule_body",
                "capsule",
                initial_position=(-4.65, 3.25, -0.55),
                position=(-4.65, 0.92, -0.55),
            ),
            body_state(
                "spot_body",
                "spot",
                initial_position=(2.75, 2.8, -2.55),
                position=(2.75, 0.48, -2.55),
            ),
            body_state(
                "sparky_body",
                "sparky",
                initial_position=(4.4, 3.45, -2.6),
                position=(4.4, 0.92, -2.6),
            ),
        )
    )
    return tuple(bodies)


def test_factory_owns_formal_preview_and_four_second_physx_contract():
    world = ATELIER.create_physics_world(device=3)

    assert world.device == 3
    assert world.scene_name == "atelier"
    assert world.seed == ATELIER.SEED == 20260717
    assert world.steps == ATELIER.STEPS == 480
    assert math.isclose(world.fixed_dt, ATELIER.FIXED_DT, rel_tol=0.0, abs_tol=1.0e-15)
    assert world.gravity == (0.0, -9.81, 0.0)
    assert (ATELIER.FORMAL_WIDTH, ATELIER.FORMAL_HEIGHT) == (2560, 1440)
    assert (ATELIER.FORMAL_SPP, ATELIER.FORMAL_DEPTH) == (1024, 12)
    assert (ATELIER.PREVIEW_WIDTH, ATELIER.PREVIEW_HEIGHT) == (640, 360)
    assert (ATELIER.PREVIEW_SPP, ATELIER.PREVIEW_DEPTH) == (16, 8)
    assert ATELIER.DEFAULT_OUTPUT_DIR == ROOT / "output/gallery"


def test_settling_validator_requires_counts_fall_bounds_basin_separation_and_rest():
    bodies = accepted_bodies()
    assert ATELIER._validate(SimpleNamespace(bodies=bodies))

    assert not ATELIER._validate(SimpleNamespace(bodies=bodies[:-1]))
    wrong_category = (replace(bodies[0], category="unknown"), *bodies[1:])
    assert not ATELIER._validate(SimpleNamespace(bodies=wrong_category))
    in_basin = (*bodies[:-1], replace(bodies[-1], position=(4.7, 0.92, 2.2)))
    assert not ATELIER._validate(SimpleNamespace(bodies=in_basin))
    out_of_bounds = (replace(bodies[0], position=(-7.3, 0.18, -1.5)), *bodies[1:])
    assert not ATELIER._validate(SimpleNamespace(bodies=out_of_bounds))

    only_seven_sleeping = tuple(
        replace(body, sleeping=index < 7) for index, body in enumerate(bodies)
    )
    assert not ATELIER._validate(SimpleNamespace(bodies=only_seven_sleeping))
    eleven_fallen = tuple(
        replace(body, initial_position=body.position) if index < 3 else body
        for index, body in enumerate(bodies)
    )
    assert not ATELIER._validate(SimpleNamespace(bodies=eleven_fallen))
    eleven_quiet = tuple(
        replace(body, linear_velocity=(1.0, 0.0, 0.0)) if index < 3 else body
        for index, body in enumerate(bodies)
    )
    assert not ATELIER._validate(SimpleNamespace(bodies=eleven_quiet))


def test_physics_population_has_fourteen_actors_and_only_primitive_attachments():
    world = ATELIER.create_physics_world()
    material_names = (
        "brick_coral",
        "brick_saffron",
        "brick_lime",
        "brick_teal",
        "brick_cobalt",
        "brick_lilac",
        "brick_rose",
        "brick_mint",
        "brick_ivory",
        "polished_ball",
        "frosted_glass",
    )
    materials = {name: object() for name in material_names}

    ATELIER._populate_physics(world, materials)

    assert len(world._bodies) == 14
    assert [body.category for body in world._bodies].count("brick") == 9
    assert {body.category for body in world._bodies[-5:]} == {
        "metal_ball",
        "frosted_ball",
        "capsule",
        "spot",
        "sparky",
    }
    assert len(world._source_attachments()) == 9 * 6 + 2
    for name in ("capsule_body", "spot_body", "sparky_body"):
        body = next(candidate for candidate in world._bodies if candidate.name == name)
        assert body._attachments == []
    static_names = {actor.name for actor in world._statics}
    assert {
        "studio_floor_collision",
        "basin_left_collision",
        "basin_right_collision",
        "basin_back_collision",
        "basin_front_collision",
    } <= static_names


class Resource:
    def __init__(self, kind, name, **parameters):
        self.kind = kind
        self.name = name
        self.parameters = parameters


class RecordingRenderer:
    instances = []

    def __init__(self, *, device=0, scene_name=None):
        self.device = device
        self.scene_name = scene_name
        self.integrator_parameters = None
        self.camera_parameters = None
        self.background_parameters = None
        self.textures = []
        self.materials = []
        self.meshes = []
        self.objects = []
        self.lights = []
        self.__class__.instances.append(self)

    def integrator(self, **parameters):
        self.integrator_parameters = parameters

    def camera(self, **parameters):
        self.camera_parameters = parameters

    def background(self, **parameters):
        self.background_parameters = parameters

    def texture(self, *, name, type, **parameters):
        resource = Resource(type, name, **parameters)
        self.textures.append(resource)
        return resource

    def material(self, *, name, type, **parameters):
        resource = Resource(type, name, **parameters)
        self.materials.append(resource)
        return resource

    def mesh(self, *, name, path, materials=None):
        resource = Resource("mesh", name, path=path, materials=materials)
        self.meshes.append(resource)
        return resource

    def object(self, *, name, type, **parameters):
        record = {"name": name, "type": type, **parameters}
        self.objects.append(record)
        return Resource("object", name, type=type, **parameters)

    def light(self, *, name, type, **parameters):
        self.lights.append({"name": name, "type": type, **parameters})


class SyntheticResult:
    def __init__(self, bodies):
        self.bodies = tuple(bodies)
        self.was_applied = False

    def body(self, name):
        return next(body for body in self.bodies if body.name == name)

    def apply_to(self, renderer):
        self.was_applied = True
        return renderer


def test_renderer_uses_body_poses_without_overriding_mapped_mesh_materials(
    monkeypatch, tmp_path
):
    RecordingRenderer.instances.clear()
    monkeypatch.setattr(ATELIER, "Renderer", RecordingRenderer)
    world = ATELIER.create_physics_world(device=2)
    result = SyntheticResult(accepted_bodies())
    simulation = {}

    def simulate(**parameters):
        simulation.update(parameters)
        return result

    monkeypatch.setattr(world, "simulate", simulate)
    metadata = tmp_path / "atelier.physics.json"

    renderer = ATELIER.create_renderer(world, metadata_output=metadata, verify=True)

    assert renderer is RecordingRenderer.instances[-1]
    assert renderer.device == 2 and renderer.scene_name == "atelier"
    assert renderer.integrator_parameters == {
        "direct_light_sampling": "importance",
        "clamp_direct": 64.0,
        "clamp_indirect": 16.0,
    }
    assert renderer.background_parameters["type"] == "environment"
    assert simulation == {
        "metadata_output": metadata,
        "verify": True,
        "validator": ATELIER._validate,
    }
    assert result.was_applied

    meshes = {mesh.name: mesh for mesh in renderer.meshes}
    assert len(meshes["atelier_capsule_mesh"].parameters["materials"]) == 15
    assert len(meshes["atelier_sparky_mesh"].parameters["materials"]) == 10
    assert meshes["atelier_spot_mesh"].parameters["materials"] is None

    objects = {item["name"]: item for item in renderer.objects}
    capsule = objects["capsule_settled"]
    sparky = objects["sparky_settled"]
    spot = objects["spot_settled"]
    assert "material" not in capsule
    assert "material" not in sparky
    assert "material" in spot
    assert capsule["translate"] == (-4.65, 0.0, -0.55)
    assert sparky["translate"] == (4.4, 0.0, -2.6)
    assert capsule["rotate_degrees"] == (0.0, 0.0, 0.0)
    assert objects["atelier_basin_water"]["type"] == "water_surface"

    material_types = {material.name: material.kind for material in renderer.materials}
    assert material_types["atelier_frosted_glass"] == "pbr"
    assert {light["type"] for light in renderer.lights} >= {
        "rectangle",
        "disk",
        "flame",
    }


def test_cli_accepts_device_output_dir_and_preview(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "atelier.py",
            "--device",
            "4",
            "--output-dir",
            str(tmp_path),
            "--preview",
        ],
    )

    arguments = ATELIER._parse_args()

    assert arguments.device == 4
    assert arguments.output_dir == tmp_path
    assert arguments.preview
