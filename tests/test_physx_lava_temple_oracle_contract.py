import copy
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "tools" / "check_physx_lava_temple_oracle.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("lava_temple_contract", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rectangle(name, material="stone"):
    return {
        "name": name,
        "type": "rectangle",
        "p1": [-1.0, 0.0, 1.0],
        "p2": [-1.0, 0.0, -1.0],
        "p3": [1.0, 0.0, -1.0],
        "material": material,
    }


def sphere(name, center, material="stone"):
    return {
        "name": name,
        "type": "sphere",
        "center": list(center),
        "radius": 0.1,
        "material": material,
    }


def flame(name, emission):
    return {
        "name": name,
        "type": "flame",
        "position": [0.0, 1.0, 0.0],
        "axis": [0.0, 1.0, 0.0],
        "height": 1.0,
        "radius_start": 0.4,
        "radius_end": 0.1,
        "emission_start": list(emission),
        "emission_end": list(emission),
        "extinction": 1.0,
        "density_scale": 0.5,
        "turbulence": 0.5,
        "noise_scale": 3.0,
        "seed": 909,
    }


def valid_documents(checker):
    materials = [
        {"name": "stone", "type": "lambertian", "base_color": [0.1, 0.1, 0.1]},
        {"name": "oracle_water", "type": "water", "roughness": 0.1, "ior": 1.333, "absorption": [0.6, 0.2, 0.05]},
        {"name": "frost_ice", "type": "metal", "base_color": [0.65, 0.82, 0.95], "roughness": 0.42},
        {"name": "shell_dark_metal", "type": "metal", "base_color": [0.2, 0.2, 0.2], "roughness": 0.5},
        {"name": "shell_inner_gold", "type": "metal", "base_color": [0.9, 0.5, 0.1], "roughness": 0.2},
        {"name": "mechanism_gold", "type": "metal", "base_color": [0.8, 0.4, 0.1], "roughness": 0.2},
        {"name": "mechanism_copper", "type": "metal", "base_color": [0.7, 0.2, 0.05], "roughness": 0.25},
        {"name": "spark_emitter", "type": "emitter", "emission": [20.0, 5.0, 0.2]},
        {"name": "rune_emitter", "type": "emitter", "emission": [0.1, 1.0, 4.0]},
    ]
    objects = [
        rectangle("temple_floor_left"),
        rectangle("temple_back_wall"),
        rectangle("roof_left_slab"),
        rectangle("roof_back_slab"),
        rectangle("roof_right_slab"),
        rectangle("roof_front_fragment"),
        {"name": "altar_base", "type": "cylinder", "base": [0.0, 0.0, 0.0], "axis": [0.0, 1.0, 0.0], "height": 1.0, "radius": 1.0, "material": "stone"},
        {"name": "altar_lower", "type": "cylinder", "base": [0.0, 0.0, 0.0], "axis": [0.0, 1.0, 0.0], "height": 0.5, "radius": 1.2, "material": "stone"},
        {"name": "altar_upper", "type": "cylinder", "base": [0.0, 0.5, 0.0], "axis": [0.0, 1.0, 0.0], "height": 0.5, "radius": 1.0, "material": "stone"},
        {"name": "altar_bowl", "type": "disk", "center": [0.0, 1.0, 0.0], "normal": [0.0, 1.0, 0.0], "radius": 1.0, "material": "stone"},
        rectangle("pool_floor_shallow"),
        rectangle("pool_floor_deep"),
        rectangle("pool_depth_riser"),
        rectangle("pool_left_wall"),
        rectangle("pool_right_wall"),
        rectangle("pool_back_wall"),
        rectangle("pool_front_wall"),
        {
            "name": "pool_water",
            "type": "water_surface",
            "center": [5.0, 0.5, -2.0],
            "size": [4.0, 3.0],
            "material": "oracle_water",
            "waves": [
                {"direction": [1.0, 0.0], "amplitude": 0.03, "wavelength": 2.0, "phase_radians": 0.0},
                {"direction": [0.0, 1.0], "amplitude": 0.02, "wavelength": 1.0, "phase_radians": 1.0},
                {"direction": [0.7, 0.7], "amplitude": 0.01, "wavelength": 0.5, "phase_radians": 2.0},
            ],
        },
    ]
    for index in range(8):
        objects.append({"name": "column_shaft_{:02d}".format(index), "type": "cylinder", "base": [-4.0 + index, 0.0, -3.0], "axis": [0.0, 1.0, 0.0], "height": 8.0, "radius": 0.2, "material": "stone"})
    for index in range(16):
        objects.append({"name": "rune_stroke_{:02d}".format(index), "type": "cylinder", "base": [-5.0 + 0.5 * index, 2.0, -4.0], "axis": [0.0, 1.0, 0.0], "height": 0.5, "radius": 0.02, "material": "rune_emitter"})
    for index in range(12):
        frost = sphere(
            "frost_crystal_{:02d}".format(index),
            [-5.0 + index, 7.0, -3.0],
            "frost_ice",
        )
        frost["radius"] = 0.11 + 0.01 * (index % 10)
        objects.append(frost)
    for index in range(24):
        objects.append(rectangle("shell_outer_{:02d}".format(index), "shell_dark_metal"))
        objects.append(rectangle("shell_inner_{:02d}".format(index), "shell_inner_gold"))
    for index in range(2):
        objects.append(sphere("visor_panel_{:02d}".format(index), [0.0, 5.0, 0.0], "mechanism_gold"))
    for index in range(2):
        objects.append(sphere("eye_{:02d}".format(index), [0.0, 5.0, 0.0], "mechanism_gold"))
    for index in range(4):
        objects.append(sphere("limb_{:02d}".format(index), [0.0, 5.0, 0.0], "mechanism_gold"))
    for index in range(2):
        objects.append(sphere("antenna_{:02d}".format(index), [0.0, 5.0, 0.0], "mechanism_gold"))
    objects.append(sphere("antenna_tip", [0.0, 5.0, 0.0], "mechanism_gold"))
    for index in range(6):
        objects.append(sphere("gear_{:02d}".format(index), [0.0, 5.0, 0.0], "mechanism_gold"))
    for index in range(29):
        objects.append(sphere("mechanism_{:02d}".format(index), [0.0, 5.0, 0.0], "mechanism_gold"))
    for index in range(12):
        objects.append(sphere("roof_fragment_{:02d}".format(index), [0.0, 5.0, 0.0], "mechanism_gold"))
    for index in range(48):
        objects.append(sphere("spark_{:02d}".format(index), [0.0, 5.0, 0.0], "spark_emitter"))

    lights = [
        {"name": "dawn_directional", "type": "directional", "direction": [0.0, 0.8, 0.6], "irradiance": [1.0, 1.3, 2.0]},
        flame("altar_white_core", [40.0, 35.0, 25.0]),
        flame("altar_main_flame", [30.0, 8.0, 0.5]),
        flame("altar_side_tongue", [20.0, 4.0, 0.1]),
        flame("smoke_lower", [0.001, 0.001, 0.001]),
        flame("smoke_upper", [0.001, 0.001, 0.001]),
        flame("dawn_godray", [0.01, 0.02, 0.05]),
    ]
    for index in range(4):
        lights.append(
            {
                "name": "rune_point_{:02d}".format(index),
                "type": "point",
                "position": [-5.0 + index * 3.0, 2.0, -4.0],
                "intensity": [0.2, 1.0, 3.0],
            }
        )
    scene = {
        "schema_version": 6,
        "integrator": {"direct_light_sampling": "importance", "clamp_direct": 64.0, "clamp_indirect": 16.0},
        "camera": {"look_from": [12.0, 7.0, 16.0], "look_at": [0.0, 4.0, 0.0], "up": [0.0, 1.0, 0.0], "vfov": 35.0, "aperture": 0.0, "focus_distance": 20.0},
        "background": {"type": "constant", "color": [0.0, 0.0, 0.0], "exposure": 0.0},
        "render": {"width": 3840, "height": 2160, "spp": 2048, "max_depth": 12, "seed": 909, "denoise": True},
        "textures": [],
        "materials": materials,
        "meshes": [],
        "objects": objects,
        "lights": lights,
    }

    actors = []
    actor_index = 0
    for category, count in checker.ACTOR_CATEGORIES:
        for category_index in range(count):
            quadrant = actor_index % 4
            dx = 0.2 if quadrant in (0, 1) else -0.2
            dz = 0.2 if quadrant in (0, 2) else -0.2
            actors.append(
                {
                    "name": "{}_{:02d}".format(category, category_index),
                    "category": category,
                    "initial_position": [0.0, 5.0, 0.0],
                    "position": [dx, 5.1, dz],
                    "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                    "linear_velocity": [dx * 10.0, 2.0, dz * 10.0],
                    "angular_velocity": [0.1, 0.2, 0.3],
                    "sleeping": False,
                }
            )
            actor_index += 1
    metadata = {
        "schema_version": 1,
        "generator": checker.GENERATOR,
        "backend": {
            "name": "NVIDIA PhysX",
            "mode": "gpu",
            "physx_version": "5.8.0",
            "physx_commit": checker.PHYSX_COMMIT,
            "device_ordinal": 0,
            "device_name": "Synthetic GPU",
            "cuda_context_valid": True,
            "cpu_fallback": False,
        },
        "simulation": {
            "seed": 909,
            "fixed_dt": 0.008333,
            "fixed_dt_numerator": 1,
            "fixed_dt_denominator": 120,
            "steps": 24,
            "capture_seconds": 0.2,
            "gravity": [0.0, -9.81, 0.0],
            "broad_phase": "gpu",
            "solver": "tgs",
            "flags": {"gpu_dynamics": True, "pcm": True, "stabilization": True, "enhanced_determinism": False},
            "determinism_limitation": "enhanced_determinism_unsupported_on_gpu",
        },
        "geometry": {
            **checker.EXPECTED_GEOMETRY,
            "actor_order": [
                {"category": category, "count": count}
                for category, count in checker.ACTOR_CATEGORIES
            ],
        },
        "scene_features": dict(checker.EXPECTED_SCENE_FEATURES),
        "contract": {
            "dynamic_center_bounds": {"min": [-12.0, -0.2, -10.0], "max": [12.0, 15.0, 8.0]},
            "minimum_radial_displacement": 0.08,
            "minimum_moving_dynamic_actors": 120,
        },
        "actors": actors,
        "results": {
            "sleeping_dynamic_actors": 0,
            "moving_dynamic_actors": 130,
            "actors_beyond_minimum_radial_displacement": 130,
            "rotating_dynamic_actors": 130,
            "occupied_explosion_quadrants": 4,
            "maximum_upward_displacement": 0.1,
        },
    }
    return scene, metadata


def test_synthetic_cover_satisfies_contract():
    checker = load_checker()
    scene, metadata = valid_documents(checker)
    summary = checker.validate(scene, metadata)
    assert summary["actors"] == 130
    assert summary["moving"] == 130
    assert summary["flames"] == 6


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda scene, metadata: metadata["backend"].update(mode="cpu"), "CPU PhysX"),
        (lambda scene, metadata: metadata["simulation"].update(steps=25), "step count"),
        (lambda scene, metadata: metadata["actors"][0].update(sleeping=True), "zero sleeping"),
        (lambda scene, metadata: metadata["actors"].reverse(), "category counts/order"),
        (lambda scene, metadata: scene.update(meshes=[{"name": "forbidden", "path": "asset.obj"}]), "must not use meshes"),
        (lambda scene, metadata: scene["lights"].pop(), "light names/types/order"),
    ],
)
def test_contract_rejects_semantic_mutations(mutation, message):
    checker = load_checker()
    scene, metadata = valid_documents(checker)
    mutation(scene, metadata)
    with pytest.raises(checker.ContractError, match=message):
        checker.validate(scene, metadata)


@pytest.mark.parametrize(
    "payload, message",
    [
        ('{"value": -0.000000}', "negative zero"),
        ('{"value": 0.1234567}', "more than six fractional digits"),
        ('{"value": NaN}', "non-finite JSON constant"),
        ('{"value": 1e999}', "must be finite"),
    ],
)
def test_json_loader_rejects_noncanonical_numbers(tmp_path, payload, message):
    checker = load_checker()
    document = tmp_path / "bad.json"
    document.write_text(payload, encoding="utf-8")
    with pytest.raises(checker.ContractError, match=message):
        checker.load_json(document)
