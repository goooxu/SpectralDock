import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_physx_scene", ROOT / "tools" / "check_physx_scene.py"
)
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def valid_documents():
    objects = copy.deepcopy(list(CHECK.STATIC_RECTANGLES))
    for index in range(CHECK.MASCOT_COUNT):
        toppled = index < CHECK.MIN_TOPPLED
        center_x = round(-5.0 + (index % 8) * 1.4, 6)
        center_z = round(-2.0 + (index // 8) * 1.5, 6)
        if toppled:
            rotation = [0.0, 0.0, 90.0]
            translate = [
                round(center_x + CHECK.MASCOT_SCALE, 6),
                CHECK.CAPSULE_RADIUS,
                center_z,
            ]
        else:
            rotation = [0.0, 0.0, 0.0]
            translate = [center_x, 0.0, center_z]
        objects.append(
            {
                "name": "mascot_{:02d}".format(index),
                "type": "mesh",
                "mesh": "mascot",
                "transform": {
                    "translate": translate,
                    "rotate_degrees": rotation,
                    "scale": [0.7, 0.7, 0.7],
                },
                "material": "mascot_red",
            }
        )
    for index in range(CHECK.SPHERE_COUNT):
        radius = round(0.12 + 0.01 * (index % 6), 6)
        objects.append(
            {
                "name": "bead_{:03d}".format(index),
                "type": "sphere",
                "center": [
                    round(-5.5 + (index % 24) * 0.45, 6),
                    radius,
                    round(-3.2 + (index // 24) * 0.8, 6),
                ],
                "radius": radius,
                "material": "sphere_blue",
            }
        )
    scene = {
        "schema_version": 2,
        "camera": {},
        "background": {},
        "render": {"seed": 20260711},
        "textures": [],
        "materials": [],
        "meshes": [
            {
                "name": "mascot",
                "path": "../../assets/examples/models/capsule-mascot.obj",
            }
        ],
        "objects": objects,
        "lights": [],
    }
    metadata = {
        "schema_version": 1,
        "generator": "spectraldock-physx-kinetic-foundry/1.0",
        "backend": {
            "name": "NVIDIA PhysX",
            "mode": "gpu",
            "physx_version": "5.8.0",
            "physx_commit": "fc1018a3745664a1db2b95ce03fb5e91eb585f2e",
            "cuda_context_valid": True,
            "cpu_fallback": False,
            "device_ordinal": 0,
            "device_name": "Contract Test GPU",
        },
        "simulation": {
            "seed": 20260711,
            "fixed_dt_numerator": 1,
            "fixed_dt_denominator": 120,
            "steps": 960,
            "broad_phase": "gpu",
            "flags": {
                "gpu_dynamics": True,
                "pcm": True,
                "stabilization": True,
                "enhanced_determinism": False,
            },
            "determinism_limitation": "enhanced_determinism_unsupported_on_gpu",
        },
        "geometry": {
            "mascots": 24,
            "spheres": 192,
            "mascot_scale": 0.7,
            "capsule_radius": 0.42,
            "capsule_half_height": 0.28,
        },
        "contract": {
            "dynamic_center_bounds": {
                "min": [-8.0, -0.1, -5.0],
                "max": [8.0, 9.0, 5.0],
            }
        },
        "results": {
            "toppled_mascots": CHECK.MIN_TOPPLED,
            "minimum_toppled_mascots": CHECK.MIN_TOPPLED,
        },
    }
    return scene, metadata


def test_valid_gpu_baked_scene_contract():
    scene, metadata = valid_documents()
    assert CHECK.validate(scene, metadata) == {
        "mascots": 24,
        "spheres": 192,
        "toppled_mascots": 12,
    }


@pytest.mark.parametrize(
    ("path", "value", "message"),
    (
        (("backend", "mode"), "cpu", "CPU PhysX output is forbidden"),
        (("backend", "cuda_context_valid"), False, "CUDA context was not valid"),
        (("backend", "cpu_fallback"), True, "CPU fallback must be disabled"),
        (("simulation", "broad_phase"), "cpu", "GPU broad phase is required"),
        (("simulation", "flags", "gpu_dynamics"), False, "gpu_dynamics"),
        (("simulation", "flags", "pcm"), False, "pcm"),
        (("simulation", "flags", "stabilization"), False, "stabilization"),
        (("simulation", "flags", "enhanced_determinism"), True, "unsupported on GPU"),
    ),
)
def test_gpu_only_contract_rejects_fallbacks_and_wrong_flags(path, value, message):
    scene, metadata = valid_documents()
    target = metadata
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(CHECK.ContractError, match=message):
        CHECK.validate(scene, metadata)


def test_duplicate_names_and_wrong_counts_are_rejected():
    scene, metadata = valid_documents()
    scene["objects"][-1]["name"] = scene["objects"][-2]["name"]
    with pytest.raises(CHECK.ContractError, match="unique"):
        CHECK.validate(scene, metadata)

    scene, metadata = valid_documents()
    scene["objects"].pop()
    with pytest.raises(CHECK.ContractError, match="192 spheres"):
        CHECK.validate(scene, metadata)

    scene, metadata = valid_documents()
    scene["objects"].append({"name": "extra", "type": "unknown"})
    with pytest.raises(CHECK.ContractError, match="220 scene objects"):
        CHECK.validate(scene, metadata)


def test_cross_document_seed_bounds_and_numeric_types_are_enforced():
    scene, metadata = valid_documents()
    scene["render"]["seed"] += 1
    with pytest.raises(CHECK.ContractError, match="seeds disagree"):
        CHECK.validate(scene, metadata)

    scene, metadata = valid_documents()
    metadata["contract"]["dynamic_center_bounds"]["max"][1] = 10.0
    with pytest.raises(CHECK.ContractError, match="bounds changed"):
        CHECK.validate(scene, metadata)

    scene, metadata = valid_documents()
    metadata["geometry"]["mascot_scale"] = "0.7"
    with pytest.raises(CHECK.ContractError, match="must be finite"):
        CHECK.validate(scene, metadata)


def test_ground_bounds_and_topple_contract_are_enforced():
    scene, metadata = valid_documents()
    first_sphere = next(obj for obj in scene["objects"] if obj.get("type") == "sphere")
    first_sphere["center"][1] = -1.0
    with pytest.raises(CHECK.ContractError, match="ground"):
        CHECK.validate(scene, metadata)

    scene, metadata = valid_documents()
    for obj in scene["objects"]:
        if obj.get("type") == "mesh":
            obj["transform"]["rotate_degrees"] = [0.0, 0.0, 0.0]
            obj["transform"]["translate"][1] = 0.0
    metadata["results"]["toppled_mascots"] = 0
    with pytest.raises(CHECK.ContractError, match="obvious mascot cascade"):
        CHECK.validate(scene, metadata)


def test_json_precision_and_negative_zero_are_rejected(tmp_path):
    excessive = tmp_path / "excessive.json"
    excessive.write_text('{"value": 0.1234567}\n', encoding="utf-8")
    with pytest.raises(CHECK.ContractError, match="six fractional digits"):
        CHECK.load_json(excessive)

    negative_zero = tmp_path / "negative-zero.json"
    negative_zero.write_text('{"value": -0.000000}\n', encoding="utf-8")
    with pytest.raises(CHECK.ContractError, match="negative zero"):
        CHECK.load_json(negative_zero)


def test_serialized_fixture_passes_file_level_checks(tmp_path):
    scene, metadata = valid_documents()
    scene_path = tmp_path / "kinetic-foundry.json"
    metadata_path = tmp_path / "kinetic-foundry.physics.json"
    scene_path.write_text(json.dumps(scene, indent=2) + "\n", encoding="utf-8")
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    assert CHECK.validate(CHECK.load_json(scene_path), CHECK.load_json(metadata_path))["toppled_mascots"] == 12
