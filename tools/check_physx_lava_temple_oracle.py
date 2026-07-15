#!/usr/bin/env python3
"""Validate the Lava Temple Oracle scene and its PhysX GPU manifest."""

import argparse
import json
import math
import re
import sys
from pathlib import Path


PHYSX_COMMIT = "fc1018a3745664a1db2b95ce03fb5e91eb585f2e"
GENERATOR = "spectraldock-physx-lava-temple-oracle/1.0"
ACTOR_CATEGORIES = (
    ("shell_plate", 24),
    ("visor_panel", 2),
    ("eye", 2),
    ("limb", 4),
    ("antenna_part", 3),
    ("compound_gear", 6),
    ("mechanical_part", 29),
    ("roof_stone", 12),
    ("spark", 48),
)
ACTOR_COUNT = sum(count for _, count in ACTOR_CATEGORIES)
EXPECTED_GEOMETRY = {
    "dynamic_actors": ACTOR_COUNT,
    "shell_plates": 24,
    "visor_panels": 2,
    "eyes": 2,
    "limbs": 4,
    "antenna_parts": 3,
    "compound_gears": 6,
    "mechanical_parts": 29,
    "roof_stones": 12,
    "sparks": 48,
    "prefractured": True,
}
EXPECTED_SCENE_FEATURES = {
    "ancient_blackstone_temple": True,
    "collapsed_roof_opening": True,
    "prefractured_mechanical_oracle": True,
    "compound_gear_actors": True,
    "analytic_water_surface": True,
    "procedural_fire_and_absorbing_smoke": True,
    "directional_dawn_light": True,
    "emissive_runes": True,
    "opaque_frost_visual_proxy": True,
    "external_meshes": False,
    "external_textures": False,
}
EXPECTED_LIGHTS = (
    ("dawn_directional", "directional"),
    ("altar_white_core", "flame"),
    ("altar_main_flame", "flame"),
    ("altar_side_tongue", "flame"),
    ("smoke_lower", "flame"),
    ("smoke_upper", "flame"),
    ("dawn_godray", "flame"),
    ("rune_point_00", "point"),
    ("rune_point_01", "point"),
    ("rune_point_02", "point"),
    ("rune_point_03", "point"),
)
REQUIRED_MATERIALS = {
    "oracle_water": "water",
    "frost_ice": "metal",
    "shell_dark_metal": "metal",
    "shell_inner_gold": "metal",
    "mechanism_gold": "metal",
    "mechanism_copper": "metal",
    "spark_emitter": "emitter",
    "rune_emitter": "emitter",
}
NUMBER = re.compile(
    r"(?<![A-Za-z0-9_])(-?(?:0|[1-9]\d*)(?:\.(\d+))?(?:[eE][+-]?\d+)?)"
)
NEGATIVE_ZERO = re.compile(r"(?<![\d.])-0(?:\.0+)?(?:[\s,}\]])")


class ContractError(RuntimeError):
    pass


def _reject_constant(value):
    raise ContractError("non-finite JSON constant: {}".format(value))


def _require(condition, message):
    if not condition:
        raise ContractError(message)


def load_json(path):
    text = Path(path).read_text(encoding="utf-8")
    if NEGATIVE_ZERO.search(text):
        raise ContractError("{} contains negative zero".format(path))
    for match in NUMBER.finditer(text):
        fraction = match.group(2)
        if fraction is not None and len(fraction) > 6:
            raise ContractError(
                "{} contains more than six fractional digits: {}".format(
                    path, match.group(1)
                )
            )
    try:
        document = json.loads(text, parse_constant=_reject_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ContractError("cannot parse {}: {}".format(path, error)) from error
    _walk_finite(document, str(path))
    return document


def _walk_finite(value, where):
    if isinstance(value, dict):
        for key, child in value.items():
            _walk_finite(child, "{}.{}".format(where, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_finite(child, "{}[{}]".format(where, index))
    elif type(value) is float:
        _require(math.isfinite(value), where + " must be finite")


def _finite_number(value, where):
    _require(
        type(value) in (int, float) and math.isfinite(value),
        where + " must be a finite number",
    )
    return float(value)


def _finite_vector(value, length, where):
    _require(isinstance(value, list) and len(value) == length, where + " has wrong shape")
    return tuple(
        _finite_number(component, "{}[{}]".format(where, index))
        for index, component in enumerate(value)
    )


def _length(vector):
    return math.sqrt(sum(component * component for component in vector))


def _subtract(a, b):
    return tuple(a[index] - b[index] for index in range(len(a)))


def _validate_backend(metadata):
    _require(metadata.get("schema_version") == 1, "metadata schema_version must be 1")
    _require(metadata.get("generator") == GENERATOR, "unexpected generator identifier")
    backend = metadata.get("backend", {})
    _require(backend.get("name") == "NVIDIA PhysX", "wrong physics backend")
    _require(backend.get("mode") == "gpu", "CPU PhysX output is forbidden")
    _require(backend.get("physx_version") == "5.8.0", "PhysX 5.8.0 is required")
    _require(backend.get("physx_commit") == PHYSX_COMMIT, "unexpected PhysX source commit")
    _require(backend.get("cuda_context_valid") is True, "CUDA context was not valid")
    _require(backend.get("cpu_fallback") is False, "CPU fallback must be disabled")
    _require(
        type(backend.get("device_ordinal")) is int and backend["device_ordinal"] >= 0,
        "device ordinal must be a non-negative integer",
    )
    _require(
        isinstance(backend.get("device_name"), str) and backend["device_name"].strip(),
        "device name must not be empty",
    )


def _validate_simulation(scene, metadata):
    simulation = metadata.get("simulation", {})
    _require(
        type(simulation.get("seed")) is int and simulation["seed"] >= 0,
        "simulation seed must be a non-negative integer",
    )
    _require(
        scene.get("render", {}).get("seed") == simulation["seed"],
        "scene and simulation seeds disagree",
    )
    fixed_dt = _finite_number(simulation.get("fixed_dt"), "simulation.fixed_dt")
    _require(abs(fixed_dt - 1.0 / 120.0) <= 1.0e-6, "fixed dt changed")
    _require(simulation.get("fixed_dt_numerator") == 1, "fixed dt numerator changed")
    _require(simulation.get("fixed_dt_denominator") == 120, "fixed dt denominator changed")
    _require(simulation.get("steps") == 24, "simulation step count changed")
    capture = _finite_number(simulation.get("capture_seconds"), "simulation.capture_seconds")
    _require(abs(capture - 0.2) <= 1.0e-6, "capture time changed")
    gravity = _finite_vector(simulation.get("gravity"), 3, "simulation.gravity")
    _require(gravity == (0.0, -9.81, 0.0), "normal Earth gravity is required")
    _require(simulation.get("broad_phase") == "gpu", "GPU broad phase is required")
    _require(simulation.get("solver") == "tgs", "TGS solver is required")
    flags = simulation.get("flags", {})
    for key in ("gpu_dynamics", "pcm", "stabilization"):
        _require(flags.get(key) is True, "required PhysX flag is missing: " + key)
    _require(
        flags.get("enhanced_determinism") is False,
        "enhanced determinism is unsupported on GPU",
    )
    _require(
        simulation.get("determinism_limitation")
        == "enhanced_determinism_unsupported_on_gpu",
        "GPU determinism limitation must be explicit",
    )


def _validate_actors(metadata):
    geometry = metadata.get("geometry", {})
    for key, expected in EXPECTED_GEOMETRY.items():
        _require(geometry.get(key) == expected, "geometry.{} changed".format(key))
    expected_order = [
        {"category": category, "count": count}
        for category, count in ACTOR_CATEGORIES
    ]
    _require(geometry.get("actor_order") == expected_order, "geometry.actor_order changed")
    _require(
        metadata.get("scene_features") == EXPECTED_SCENE_FEATURES,
        "metadata scene feature declaration changed",
    )

    contract = metadata.get("contract", {})
    bounds = contract.get("dynamic_center_bounds", {})
    bound_min = _finite_vector(bounds.get("min"), 3, "contract.dynamic_center_bounds.min")
    bound_max = _finite_vector(bounds.get("max"), 3, "contract.dynamic_center_bounds.max")
    _require(
        all(bound_min[axis] < bound_max[axis] for axis in range(3)),
        "dynamic actor bounds are empty",
    )
    _require(
        bound_min == (-12.0, -0.2, -10.0)
        and bound_max == (12.0, 15.0, 8.0),
        "dynamic actor bounds changed",
    )
    minimum_radial = _finite_number(
        contract.get("minimum_radial_displacement"),
        "contract.minimum_radial_displacement",
    )
    _require(abs(minimum_radial - 0.08) <= 1.0e-6, "minimum radial displacement changed")
    _require(
        contract.get("minimum_moving_dynamic_actors") == 120,
        "minimum moving actor count changed",
    )

    actors = metadata.get("actors")
    _require(isinstance(actors, list) and len(actors) == ACTOR_COUNT, "expected 130 actor states")
    expected_categories = [
        category
        for category, count in ACTOR_CATEGORIES
        for _ in range(count)
    ]
    actual_categories = [actor.get("category") for actor in actors if isinstance(actor, dict)]
    _require(len(actual_categories) == ACTOR_COUNT, "actor states must be objects")
    _require(actual_categories == expected_categories, "actor category counts/order changed")
    names = [actor.get("name") for actor in actors]
    _require(
        all(isinstance(name, str) and name for name in names),
        "every actor state needs a name",
    )
    _require(len(names) == len(set(names)), "actor state names must be unique")
    expected_names = [
        "{}_{:02d}".format(category, index)
        for category, count in ACTOR_CATEGORIES
        for index in range(count)
    ]
    _require(names == expected_names, "actor state names/order changed")

    radial_count = 0
    moving_count = 0
    sleeping_count = 0
    angular_count = 0
    quadrants = set()
    vertical_displacements = []
    actor_keys = {
        "name",
        "category",
        "initial_position",
        "position",
        "rotation_xyzw",
        "linear_velocity",
        "angular_velocity",
        "sleeping",
    }
    for index, actor in enumerate(actors):
        where = "actors[{}]".format(index)
        _require(set(actor) == actor_keys, where + " fields changed")
        initial = _finite_vector(actor.get("initial_position"), 3, where + ".initial_position")
        position = _finite_vector(actor.get("position"), 3, where + ".position")
        rotation = _finite_vector(actor.get("rotation_xyzw"), 4, where + ".rotation_xyzw")
        linear = _finite_vector(actor.get("linear_velocity"), 3, where + ".linear_velocity")
        angular = _finite_vector(actor.get("angular_velocity"), 3, where + ".angular_velocity")
        _require(
            abs(_length(rotation) - 1.0) <= 2.0e-4,
            where + " rotation must be a unit quaternion",
        )
        _require(
            all(bound_min[axis] <= position[axis] <= bound_max[axis] for axis in range(3)),
            where + " center is outside the temple bounds",
        )
        sleeping = actor.get("sleeping")
        _require(type(sleeping) is bool, where + ".sleeping must be boolean")
        sleeping_count += int(sleeping)
        displacement = _subtract(position, initial)
        distance = _length(displacement)
        if distance >= minimum_radial:
            radial_count += 1
            if abs(displacement[0]) > 1.0e-6 and abs(displacement[2]) > 1.0e-6:
                quadrants.add((displacement[0] > 0.0, displacement[2] > 0.0))
        if _length(linear) > 1.0e-3 or _length(angular) > 1.0e-3:
            moving_count += 1
        if _length(angular) > 0.02:
            angular_count += 1
        vertical_displacements.append(displacement[1])

    _require(sleeping_count == 0, "impact-peak snapshot must have zero sleeping actors")
    _require(moving_count >= 120, "too few actors are moving at the impact peak")
    _require(radial_count >= 120, "explosion did not disperse enough actors")
    _require(len(quadrants) == 4, "explosion must occupy all four horizontal quadrants")
    _require(angular_count >= 12, "off-centre impulses produced too little angular motion")
    _require(max(vertical_displacements) >= 0.08, "explosion has no visible upward spread")

    results = metadata.get("results", {})
    _require(
        results.get("sleeping_dynamic_actors") == sleeping_count,
        "sleeping actor result disagrees with actor states",
    )
    _require(
        results.get("moving_dynamic_actors") == moving_count,
        "moving actor result disagrees with actor states",
    )
    _require(
        results.get("actors_beyond_minimum_radial_displacement") == radial_count,
        "radial displacement result disagrees with actor states",
    )
    _require(
        results.get("occupied_explosion_quadrants") == len(quadrants),
        "quadrant result disagrees with actor states",
    )
    _require(
        results.get("rotating_dynamic_actors") == angular_count,
        "rotating actor result disagrees with actor states",
    )
    maximum_upward = _finite_number(
        results.get("maximum_upward_displacement"),
        "results.maximum_upward_displacement",
    )
    _require(
        abs(maximum_upward - max(vertical_displacements)) <= 2.0e-6,
        "maximum upward displacement disagrees with actor states",
    )
    return {
        "actors": len(actors),
        "moving": moving_count,
        "radial": radial_count,
    }


def _validate_primitive(obj, where):
    kind = obj.get("type")
    _require(kind in ("sphere", "rectangle", "cylinder", "disk", "water_surface"), where + " is not analytic")
    if kind == "sphere":
        _finite_vector(obj.get("center"), 3, where + ".center")
        _require(_finite_number(obj.get("radius"), where + ".radius") > 0.0, where + " radius must be positive")
    elif kind == "rectangle":
        p1 = _finite_vector(obj.get("p1"), 3, where + ".p1")
        p2 = _finite_vector(obj.get("p2"), 3, where + ".p2")
        p3 = _finite_vector(obj.get("p3"), 3, where + ".p3")
        u = _subtract(p2, p1)
        v = _subtract(p3, p2)
        cross = (
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        )
        _require(_length(cross) > 1.0e-8, where + " rectangle is degenerate")
    elif kind == "cylinder":
        _finite_vector(obj.get("base"), 3, where + ".base")
        axis = _finite_vector(obj.get("axis"), 3, where + ".axis")
        _require(abs(_length(axis) - 1.0) <= 2.0e-4, where + " axis is not normalized")
        _require(_finite_number(obj.get("height"), where + ".height") > 0.0, where + " height must be positive")
        _require(_finite_number(obj.get("radius"), where + ".radius") > 0.0, where + " radius must be positive")
    elif kind == "disk":
        _finite_vector(obj.get("center"), 3, where + ".center")
        normal = _finite_vector(obj.get("normal"), 3, where + ".normal")
        _require(abs(_length(normal) - 1.0) <= 2.0e-4, where + " normal is not normalized")
        _require(_finite_number(obj.get("radius"), where + ".radius") > 0.0, where + " radius must be positive")
    else:
        _finite_vector(obj.get("center"), 3, where + ".center")
        size = _finite_vector(obj.get("size"), 2, where + ".size")
        _require(all(component > 0.0 for component in size), where + " size must be positive")
        waves = obj.get("waves")
        _require(isinstance(waves, list) and len(waves) >= 3, where + " needs at least three waves")


def _dynamic_object_category(name):
    prefixes = (
        ("shell_outer_", "shell_plate"),
        ("shell_inner_", "shell_plate"),
        ("visor_panel_", "visor_panel"),
        ("eye_", "eye"),
        ("limb_", "limb"),
        ("antenna_", "antenna_part"),
        ("gear_", "compound_gear"),
        ("mechanism_", "mechanical_part"),
        ("roof_fragment_", "roof_stone"),
        ("spark_", "spark"),
    )
    for prefix, category in prefixes:
        if name.startswith(prefix):
            return category
    return None


def _primitive_min_y(obj):
    kind = obj["type"]
    if kind == "sphere":
        return float(obj["center"][1]) - float(obj["radius"])
    if kind == "rectangle":
        return min(float(obj[key][1]) for key in ("p1", "p2", "p3"))
    if kind == "cylinder":
        return min(
            float(obj["base"][1]),
            float(obj["base"][1])
            + float(obj["axis"][1]) * float(obj["height"]),
        ) - float(obj["radius"])
    if kind == "disk":
        return float(obj["center"][1]) - float(obj["radius"])
    return float(obj["center"][1])


def _validate_scene(scene, metadata):
    _require(scene.get("schema_version") == 6, "scene must use schema_version 6")
    _require(scene.get("textures") == [], "cover scene must not use textures")
    _require(scene.get("meshes") == [], "cover scene must not use meshes")
    integrator = scene.get("integrator", {})
    _require(integrator.get("direct_light_sampling") == "importance", "importance sampling is required")
    _require(integrator.get("clamp_direct") == 64.0, "direct clamp changed")
    _require(integrator.get("clamp_indirect") == 16.0, "indirect clamp changed")
    render = scene.get("render", {})
    _require(render.get("width") == 3840 and render.get("height") == 2160, "cover render must be UHD 4K")
    _require(render.get("spp") == 2048, "cover render must default to 2048 spp")
    _require(render.get("max_depth") == 12, "cover path depth changed")
    _require(render.get("denoise") is True, "cover denoising must be enabled")
    _require(render.get("seed") == metadata.get("simulation", {}).get("seed"), "render seed changed")
    camera = scene.get("camera", {})
    _finite_vector(camera.get("look_from"), 3, "camera.look_from")
    _finite_vector(camera.get("look_at"), 3, "camera.look_at")
    up = _finite_vector(camera.get("up"), 3, "camera.up")
    _require(abs(_length(up) - 1.0) <= 2.0e-4, "camera up vector is not normalized")
    vfov = _finite_number(camera.get("vfov"), "camera.vfov")
    _require(15.0 <= vfov <= 60.0, "cover camera field of view is implausible")
    background = scene.get("background", {})
    if background.get("type") == "constant":
        background_color = _finite_vector(background.get("color"), 3, "background.color")
        _require(max(background_color) <= 0.02, "temple background must remain near-black")
    elif background.get("type") == "sky":
        bottom = _finite_vector(background.get("bottom"), 3, "background.bottom")
        top = _finite_vector(background.get("top"), 3, "background.top")
        _require(max(bottom + top) <= 0.03, "temple sky fill must remain near-black")
        sun_color = _finite_vector(background.get("sun_color"), 3, "background.sun_color")
        _require(max(sun_color) == 0.0, "dawn sun must come only from the directional light")
    else:
        raise ContractError("temple must use a controlled constant or sky background")

    materials = scene.get("materials")
    _require(isinstance(materials, list), "scene.materials must be an array")
    material_by_name = {}
    for material in materials:
        _require(isinstance(material, dict), "materials must be objects")
        name = material.get("name")
        _require(isinstance(name, str) and name, "every material needs a name")
        _require(name not in material_by_name, "material names must be unique")
        material_by_name[name] = material
    for name, kind in REQUIRED_MATERIALS.items():
        _require(name in material_by_name, "missing required material: " + name)
        _require(material_by_name[name].get("type") == kind, name + " has wrong material type")
    water = material_by_name["oracle_water"]
    absorption = _finite_vector(water.get("absorption"), 3, "oracle_water.absorption")
    _require(min(absorption) > 0.0 and max(absorption) > min(absorption), "water needs chromatic Beer absorption")
    frost_material = material_by_name["frost_ice"]
    frost_color = _finite_vector(
        frost_material.get("base_color"), 3, "frost_ice.base_color"
    )
    _require(
        frost_color == (0.65, 0.82, 0.95),
        "opaque frost proxy color changed",
    )
    frost_roughness = _finite_number(
        frost_material.get("roughness"), "frost_ice.roughness"
    )
    _require(
        abs(frost_roughness - 0.42) <= 1.0e-6,
        "opaque frost proxy roughness changed",
    )

    objects = scene.get("objects")
    _require(isinstance(objects, list) and objects, "scene.objects must be a non-empty array")
    _require(len(objects) <= 450, "scene exceeded the analytic teaching-object budget")
    names = []
    dynamic_categories = []
    prefix_counts = {prefix: 0 for prefix in ("temple_", "column_", "roof_", "altar_", "pool_", "rune_", "frost_")}
    frost = []
    water_surfaces = []
    for index, obj in enumerate(objects):
        _require(isinstance(obj, dict), "scene objects must be objects")
        name = obj.get("name")
        _require(isinstance(name, str) and name, "every object needs a name")
        names.append(name)
        _validate_primitive(obj, "objects[{}]".format(index))
        _require("transform" not in obj, "analytic primitives must contain baked world-space poses")
        for field in ("material", "front_material", "back_material"):
            material = obj.get(field)
            if material is not None:
                _require(material in material_by_name, name + " references an unknown material")
        for prefix in prefix_counts:
            if name.startswith(prefix):
                prefix_counts[prefix] += 1
        category = _dynamic_object_category(name)
        if category is not None:
            dynamic_categories.append(category)
            _require(_primitive_min_y(obj) >= -0.1, name + " penetrates the temple floor")
        if name.startswith("frost_"):
            _require(
                obj.get("type") == "sphere"
                and obj.get("material") == "frost_ice",
                "frost must use opaque metal proxy spheres",
            )
            radius = _finite_number(obj.get("radius"), name + ".radius")
            _require(
                0.10 <= radius <= 0.21,
                "opaque frost proxy radius must remain a small roof-edge accent",
            )
            frost.append(obj)
        if obj.get("type") == "water_surface":
            water_surfaces.append(obj)
        if name.startswith("spark_"):
            _require(
                obj.get("type") == "sphere" and obj.get("material") == "spark_emitter",
                "sparks must be emissive PhysX-baked spheres",
            )
    _require(len(names) == len(set(names)), "object names must be unique")
    name_set = set(names)
    required_static = {
        "temple_floor_left",
        "temple_back_wall",
        "roof_left_slab",
        "roof_back_slab",
        "roof_right_slab",
        "roof_front_fragment",
        "altar_lower",
        "altar_upper",
        "altar_bowl",
        "pool_floor_shallow",
        "pool_floor_deep",
        "pool_depth_riser",
        "pool_left_wall",
        "pool_right_wall",
        "pool_back_wall",
        "pool_front_wall",
        "pool_water",
    }
    _require(required_static <= name_set, "sealed temple/pool static geometry changed")
    for prefix, count in prefix_counts.items():
        _require(count > 0, "missing scene feature prefix: " + prefix)
    _require(len(water_surfaces) == 1, "scene must contain one sealed analytic water surface")
    _require(water_surfaces[0].get("material") == "oracle_water", "pool must use oracle_water")
    _require(len(frost) == 12, "roof opening needs exactly twelve frost crystals")
    _require(
        len({round(float(obj["radius"]), 3) for obj in frost}) >= 6,
        "frost proxy cluster must retain irregular crystal sizes",
    )
    for left in range(len(frost)):
        a_center = tuple(float(value) for value in frost[left]["center"])
        a_radius = float(frost[left]["radius"])
        for right in range(left + 1, len(frost)):
            b_center = tuple(float(value) for value in frost[right]["center"])
            b_radius = float(frost[right]["radius"])
            _require(
                _length(_subtract(a_center, b_center)) >= a_radius + b_radius - 1.0e-5,
                "opaque frost proxy spheres intersect",
            )
    _require(
        sum(name.startswith("rune_stroke_") for name in names) == 16,
        "temple must retain sixteen emissive rune strokes",
    )
    _require(
        sum(name.startswith("column_shaft_") for name in names) == 8,
        "temple must retain eight monumental columns",
    )

    def object_indices(prefix):
        pattern = re.compile(r"^{}(\d{{2}})(?:_|$)".format(re.escape(prefix)))
        return {
            int(match.group(1))
            for name in names
            for match in [pattern.match(name)]
            if match is not None
        }

    expected_indices = {
        "shell_outer_": 24,
        "shell_inner_": 24,
        "visor_panel_": 2,
        "eye_": 2,
        "limb_": 4,
        "gear_": 6,
        "mechanism_": 29,
        "roof_fragment_": 12,
        "spark_": 48,
    }
    for prefix, count in expected_indices.items():
        _require(
            object_indices(prefix) == set(range(count)),
            prefix + " PhysX-to-renderer mapping changed",
        )
    _require("antenna_tip" in name_set, "antenna tip mapping is missing")
    _require(object_indices("antenna_") == {0, 1}, "antenna rod mapping changed")
    shell_outer = [obj for obj in objects if obj["name"].startswith("shell_outer_")]
    shell_inner = [obj for obj in objects if obj["name"].startswith("shell_inner_")]
    _require(
        all(obj["type"] == "rectangle" and obj.get("material") == "shell_dark_metal" for obj in shell_outer),
        "outer shell plates must be dark-metal rectangles",
    )
    _require(
        all(obj["type"] == "rectangle" and obj.get("material") == "shell_inner_gold" for obj in shell_inner),
        "inner shell cutaways must be gold rectangles",
    )
    rank = {category: index for index, (category, _) in enumerate(ACTOR_CATEGORIES)}
    _require(dynamic_categories, "scene contains no PhysX-baked oracle fragments")
    _require(
        [rank[category] for category in dynamic_categories]
        == sorted(rank[category] for category in dynamic_categories),
        "dynamic primitive category blocks changed order",
    )

    lights = scene.get("lights")
    _require(isinstance(lights, list), "scene.lights must be an array")
    _require(
        [(light.get("name"), light.get("type")) for light in lights]
        == list(EXPECTED_LIGHTS),
        "cover light names/types/order changed",
    )
    flames = [light for light in lights if light.get("type") == "flame"]
    _require(len(flames) == 6, "cover needs exactly six flame volumes")
    optical_thickness = 0.0
    for index, flame in enumerate(flames):
        where = "flames[{}]".format(index)
        axis = _finite_vector(flame.get("axis"), 3, where + ".axis")
        _require(abs(_length(axis) - 1.0) <= 2.0e-4, where + " axis is not normalized")
        height = _finite_number(flame.get("height"), where + ".height")
        extinction = _finite_number(flame.get("extinction"), where + ".extinction")
        density = _finite_number(flame.get("density_scale"), where + ".density_scale")
        _require(height > 0.0 and extinction > 0.0 and density > 0.0, where + " volume parameters must be positive")
        optical_thickness += height * extinction * density
        start = _finite_vector(flame.get("emission_start"), 3, where + ".emission_start")
        end = _finite_vector(flame.get("emission_end"), 3, where + ".emission_end")
        _require(max(start + end) > 0.0, where + " must retain non-zero renderer emission")
    _require(optical_thickness <= 64.0, "flame volumes exceed the conservative optical-depth budget")
    light_by_name = {light["name"]: light for light in lights}
    directional = light_by_name["dawn_directional"]
    direction = _finite_vector(directional.get("direction"), 3, "dawn_directional.direction")
    _require(abs(_length(direction) - 1.0) <= 2.0e-4, "dawn direction is not normalized")
    dawn = _finite_vector(directional.get("irradiance"), 3, "dawn_directional.irradiance")
    _require(dawn[2] > dawn[0] > 0.0, "dawn directional light must be cold")
    for name in ("altar_white_core", "altar_main_flame", "altar_side_tongue"):
        emission = tuple(light_by_name[name]["emission_start"]) + tuple(light_by_name[name]["emission_end"])
        _require(max(emission) >= 1.0, name + " is not a visible flame source")
    for name in ("smoke_lower", "smoke_upper"):
        emission = tuple(light_by_name[name]["emission_start"]) + tuple(light_by_name[name]["emission_end"])
        _require(0.0 < max(emission) <= 0.05, name + " must remain a near-dark absorptive proxy")
    godray = light_by_name["dawn_godray"]
    godray_emission = tuple(godray["emission_start"]) + tuple(godray["emission_end"])
    _require(max(godray_emission) <= 0.5, "godray proxy must stay low-emission")
    _require(
        max(godray["emission_start"][2], godray["emission_end"][2])
        > max(godray["emission_start"][0], godray["emission_end"][0]),
        "godray proxy must be cool colored",
    )
    for light in lights:
        if light.get("type") == "point":
            intensity = _finite_vector(light.get("intensity"), 3, light["name"] + ".intensity")
            _require(intensity[2] > intensity[0], light["name"] + " must be cyan/blue")
    return {"objects": len(objects), "flames": len(flames), "frost": len(frost)}


def validate(scene, metadata):
    _validate_backend(metadata)
    _validate_simulation(scene, metadata)
    actor_summary = _validate_actors(metadata)
    scene_summary = _validate_scene(scene, metadata)
    summary = {}
    summary.update(actor_summary)
    summary.update(scene_summary)
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("metadata", type=Path)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        summary = validate(load_json(args.scene), load_json(args.metadata))
    except (OSError, ContractError) as error:
        print("error: {}".format(error), file=sys.stderr)
        return 2
    print(
        "validated Lava Temple Oracle: {actors} GPU actors, {moving} moving, "
        "{radial} dispersed, {objects} analytic primitives, {flames} volumes, "
        "{frost} frost crystals".format(**summary)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
