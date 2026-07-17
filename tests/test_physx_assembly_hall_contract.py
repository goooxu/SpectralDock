import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace

from spectraldock.physics import BodyState


ROOT = Path(__file__).resolve().parents[1]
SCENE_PATH = ROOT / "scenes" / "assembly-hall.py"


def load_scene():
    spec = importlib.util.spec_from_file_location(
        "spectraldock_assembly_hall_contract", SCENE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCENE = load_scene()


def body_state(index, *, position=None, initial=None, sleeping=False):
    initial = initial or (float(index) * 0.1, 5.0, -2.0)
    position = position or (initial[0] - 0.2, initial[1] + 0.1, initial[2])
    return BodyState(
        name=f"spot_body_{index:02d}",
        category="spot",
        initial_position=initial,
        initial_rotation=(0.0, 0.0, 0.0, 1.0),
        position=position,
        rotation=(0.0, 0.0, 0.0, 1.0),
        linear_velocity=(-1.0, 0.0, 0.0),
        angular_velocity=(0.0, 1.0, 0.0),
        sleeping=sleeping,
    )


def test_factory_owns_fixed_midair_physx_contract():
    world = SCENE.create_physics_world(device=3)

    assert world.device == 3
    assert world.seed == SCENE.SEED == 20260718
    assert world.steps == SCENE.STEPS == 36
    assert math.isclose(world.fixed_dt, 1.0 / 120.0, abs_tol=1.0e-15)
    assert world.gravity == (0.0, -9.81, 0.0)
    assert world.scene_name == "assembly-hall"

    SCENE._populate_physics(world)
    assert len(world._bodies) == SCENE.SPOT_COUNT == 12
    assert all(body.category == "spot" for body in world._bodies)
    assert all(len(body._shapes) == 1 for body in world._bodies)
    assert all(body._attachments == [] for body in world._bodies)


def test_validator_requires_bounds_airborne_motion_and_awake_state():
    valid = SimpleNamespace(bodies=tuple(body_state(index) for index in range(12)))
    assert SCENE._validate(valid)

    too_few = SimpleNamespace(bodies=valid.bodies[:-1])
    assert not SCENE._validate(too_few)

    grounded = SimpleNamespace(
        bodies=tuple(
            body_state(index, position=(float(index) * 0.1, 0.6, -2.0))
            for index in range(12)
        )
    )
    assert not SCENE._validate(grounded)

    outside = list(valid.bodies)
    outside[0] = body_state(0, position=(99.0, 5.0, -2.0))
    assert not SCENE._validate(SimpleNamespace(bodies=tuple(outside)))

    mostly_sleeping = tuple(
        body_state(index, sleeping=index >= 5) for index in range(12)
    )
    assert not SCENE._validate(SimpleNamespace(bodies=mostly_sleeping))


class RecordingRenderer:
    def __init__(self):
        self.parameters = None

    def object(self, **parameters):
        self.parameters = parameters
        return parameters


def test_body_state_pose_keeps_mapped_mesh_without_material_override():
    renderer = RecordingRenderer()
    state = body_state(
        0,
        initial=(0.0, 0.0, 0.0),
        position=(2.0, 3.0, 4.0),
    )
    mesh = object()

    SCENE._apply_body_mesh(
        renderer,
        state,
        name="mapped",
        mesh=mesh,
        scale=(0.7, 0.7, 0.7),
        local_translate=(0.0, -0.5, 0.0),
    )

    assert renderer.parameters["mesh"] is mesh
    assert renderer.parameters["translate"] == (2.0, 2.5, 4.0)
    assert renderer.parameters["rotate_degrees"] == (0.0, 0.0, 0.0)
    assert renderer.parameters["scale"] == (0.7, 0.7, 0.7)
    assert "material" not in renderer.parameters


def test_forge_uses_medium_safe_shroud_and_finite_warm_glow():
    class ForgeRecorder:
        def __init__(self):
            self.objects = []
            self.lights = []

        def object(self, **parameters):
            self.objects.append(parameters)
            return parameters

        def light(self, **parameters):
            self.lights.append(parameters)

    renderer = ForgeRecorder()
    materials = {
        name: object()
        for name in (
            "forge_dark_metal",
            "forge_copper",
            "safety_shroud",
            "safety_glow",
        )
    }

    SCENE._add_forges(renderer, materials)

    objects = {item["name"]: item for item in renderer.objects}
    assert len([name for name in objects if name.startswith("frosted_shroud_rib_")]) == 12
    assert len([name for name in objects if name.startswith("frosted_shroud_ring_")]) == 24
    assert len([name for name in objects if name.startswith("enclosed_warm_glow_")]) == 3
    assert "rough_dielectric_safety_pod" not in objects
    assert all(
        objects[f"enclosed_warm_glow_{index:02d}"]["type"] == "sphere"
        for index in range(3)
    )

    lights = {item["name"]: item for item in renderer.lights}
    assert len([name for name in lights if name.startswith("enclosed_warm_glow_light_")]) == 3
    assert {lights[f"enclosed_warm_glow_light_{index:02d}"]["type"] for index in range(3)} == {"sphere"}
    assert lights["open_fire_core"]["type"] == "flame"
    assert lights["open_fire_tongue"]["type"] == "flame"
    assert lights["absorptive_smoke_volume"]["type"] == "flame"


def test_cli_contract_uses_gallery_root_and_verified_preview(monkeypatch, tmp_path):
    calls = {}
    physics = object()

    class FakeRenderer:
        def render(self, **parameters):
            calls["render"] = parameters

    def fake_world(*, device):
        calls["device"] = device
        return physics

    def fake_renderer(value, **parameters):
        assert value is physics
        calls["factory"] = parameters
        return FakeRenderer()

    monkeypatch.setattr(SCENE, "create_physics_world", fake_world)
    monkeypatch.setattr(SCENE, "create_renderer", fake_renderer)
    SCENE.main(
        ["--device", "2", "--output-dir", str(tmp_path), "--preview"]
    )

    assert SCENE.DEFAULT_OUTPUT_DIR == ROOT / "output/gallery"
    assert calls["device"] == 2
    assert calls["factory"]["verify"] is True
    assert calls["render"]["width"] == 640
    assert calls["render"]["height"] == 360
    assert calls["render"]["spp"] == 16
    assert calls["render"]["depth"] == 8
    assert calls["render"]["seed"] == 20260718
    assert calls["render"]["denoise"] is True


def test_formal_render_contract_and_generated_asset_paths():
    assert (SCENE.FORMAL_WIDTH, SCENE.FORMAL_HEIGHT) == (2560, 1440)
    assert (SCENE.FORMAL_SPP, SCENE.FORMAL_DEPTH) == (2048, 12)
    assert SCENE.ENVIRONMENT.name == "assembly-hall-noon.hdr"
    assert SCENE.GEAR_ALPHA.name == "assembly-hall-gear-alpha.png"
