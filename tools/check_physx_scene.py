#!/usr/bin/env python3
"""Validate the baked Kinetic Foundry scene and its PhysX GPU manifest."""

import argparse
import json
import math
import re
import sys
from pathlib import Path


MASCOT_COUNT = 24
SPHERE_COUNT = 192
MASCOT_SCALE = 0.70
CAPSULE_RADIUS = 0.42
CAPSULE_HALF_HEIGHT = 0.28
MIN_TOPPLED = 12
STATIC_RECTANGLES = (
    {
        "name": "pool_floor",
        "type": "rectangle",
        "p1": [-8, 0, 5],
        "p2": [-8, 0, -5],
        "p3": [8, 0, -5],
        "material": "floor",
    },
    {
        "name": "pool_back",
        "type": "rectangle",
        "p1": [-8, 0, -4.4],
        "p2": [-8, 5.5, -4.4],
        "p3": [8, 5.5, -4.4],
        "material": "wall",
    },
    {
        "name": "left_chute",
        "type": "rectangle",
        "p1": [-7.371089, 5.253923, 1.35],
        "p2": [-7.371089, 5.253923, -1.35],
        "p3": [-1.308912, 1.753923, -1.35],
        "material": "chute_hot",
    },
    {
        "name": "right_chute",
        "type": "rectangle",
        "p1": [1.308912, 1.753923, 1.35],
        "p2": [1.308912, 1.753923, -1.35],
        "p3": [7.371089, 5.253923, -1.35],
        "material": "chute_cool",
    },
)
NUMBER = re.compile(r"(?<![A-Za-z0-9_])(-?(?:0|[1-9]\d*)(?:\.(\d+))?(?:[eE][+-]?\d+)?)")
NEGATIVE_ZERO = re.compile(r"(?<![\d.])-0(?:\.0+)?(?:[\s,}\]])")


class ContractError(RuntimeError):
    pass


def _reject_constant(value):
    raise ContractError("non-finite JSON constant: {}".format(value))


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
        return json.loads(text, parse_constant=_reject_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ContractError("cannot parse {}: {}".format(path, error)) from error


def _require(condition, message):
    if not condition:
        raise ContractError(message)


def _finite_vector(value, length, where):
    _require(isinstance(value, list) and len(value) == length, where + " has wrong shape")
    _require(
        all(type(item) in (int, float) and math.isfinite(item) for item in value),
        where + " must contain finite numbers",
    )
    return tuple(float(item) for item in value)


def _finite_number(value, where):
    _require(type(value) in (int, float) and math.isfinite(value), where + " must be finite")
    return float(value)


def _rotation_xyz(degrees):
    x, y, z = (math.radians(value) for value in degrees)
    cx, sx = math.cos(x), math.sin(x)
    cy, sy = math.cos(y), math.sin(y)
    cz, sz = math.cos(z), math.sin(z)
    # Columns of Rz * Ry * Rx.
    return (
        (cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx),
        (sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx),
        (-sy, cy * sx, cy * cx),
    )


def _add(a, b):
    return tuple(a[i] + b[i] for i in range(3))


def _mul(matrix, vector):
    return tuple(sum(matrix[row][col] * vector[col] for col in range(3)) for row in range(3))


def validate(scene, metadata):
    _require(scene.get("schema_version") == 2, "scene must use schema_version 2")
    _require(isinstance(scene.get("objects"), list), "scene.objects must be an array")
    _require(
        scene.get("meshes") == [
            {
                "name": "mascot",
                "path": "../../assets/examples/models/capsule-mascot.obj",
            }
        ],
        "scene must reference only the shared mascot mesh",
    )

    objects = scene["objects"]
    _require(all(isinstance(obj, dict) for obj in objects), "scene objects must be objects")
    names = [obj.get("name") for obj in objects]
    _require(all(isinstance(name, str) and name for name in names), "every object needs a name")
    _require(len(names) == len(set(names)), "object names must be unique")
    mascots = [obj for obj in objects if obj.get("type") == "mesh"]
    spheres = [obj for obj in objects if obj.get("type") == "sphere"]
    rectangles = [obj for obj in objects if obj.get("type") == "rectangle"]
    _require(len(mascots) == MASCOT_COUNT, "expected 24 mascot instances")
    _require(len(spheres) == SPHERE_COUNT, "expected 192 spheres")
    _require(rectangles == list(STATIC_RECTANGLES), "static foundry rectangles changed")
    _require(len(objects) == 220, "expected exactly 220 scene objects")
    _require(
        [obj["name"] for obj in mascots]
        == ["mascot_{:02d}".format(index) for index in range(MASCOT_COUNT)],
        "mascot names/order do not match the contract",
    )
    _require(
        [obj["name"] for obj in spheres]
        == ["bead_{:03d}".format(index) for index in range(SPHERE_COUNT)],
        "sphere names/order do not match the contract",
    )

    bounds = metadata.get("contract", {}).get("dynamic_center_bounds", {})
    bound_min = _finite_vector(bounds.get("min"), 3, "contract.dynamic_center_bounds.min")
    bound_max = _finite_vector(bounds.get("max"), 3, "contract.dynamic_center_bounds.max")
    _require(
        bound_min == (-8.0, -0.1, -5.0) and bound_max == (8.0, 9.0, 5.0),
        "dynamic bounds changed",
    )

    toppled = 0
    for index, obj in enumerate(mascots):
        _require(obj.get("mesh") == "mascot", "mascot {} has wrong mesh".format(index))
        transform = obj.get("transform", {})
        translate = _finite_vector(transform.get("translate"), 3, "mascot translate")
        rotation = _finite_vector(transform.get("rotate_degrees"), 3, "mascot rotation")
        scale = _finite_vector(transform.get("scale"), 3, "mascot scale")
        _require(all(abs(value - MASCOT_SCALE) <= 1.0e-6 for value in scale), "mascot scale changed")
        matrix = _rotation_xyz(rotation)
        up = _mul(matrix, (0.0, 1.0, 0.0))
        center = _add(translate, _mul(matrix, (0.0, MASCOT_SCALE, 0.0)))
        _require(
            all(bound_min[axis] <= center[axis] <= bound_max[axis] for axis in range(3)),
            "mascot center is outside the pool bounds",
        )
        lowest = center[1] - CAPSULE_RADIUS - CAPSULE_HALF_HEIGHT * abs(up[1])
        _require(lowest >= -0.08, "mascot capsule penetrates the ground")
        if up[1] < math.cos(math.radians(15.0)):
            toppled += 1

    for obj in spheres:
        center = _finite_vector(obj.get("center"), 3, "sphere center")
        radius = obj.get("radius")
        _require(type(radius) in (int, float) and math.isfinite(radius), "sphere radius is not finite")
        _require(0.10 <= radius <= 0.22, "sphere radius is outside the contract")
        _require(center[1] - radius >= -0.05, "sphere penetrates the ground")
        _require(
            all(bound_min[axis] <= center[axis] <= bound_max[axis] for axis in range(3)),
            "sphere center is outside the pool bounds",
        )

    _require(toppled >= MIN_TOPPLED, "scene does not contain an obvious mascot cascade")

    _require(metadata.get("schema_version") == 1, "metadata schema_version must be 1")
    _require(
        metadata.get("generator") == "spectraldock-physx-kinetic-foundry/1.1",
        "unexpected generator identifier",
    )
    backend = metadata.get("backend", {})
    _require(backend.get("name") == "NVIDIA PhysX", "wrong physics backend")
    _require(backend.get("mode") == "gpu", "CPU PhysX output is forbidden")
    _require(backend.get("physx_version") == "5.8.0", "PhysX 5.8.0 is required")
    _require(
        backend.get("physx_commit") == "fc1018a3745664a1db2b95ce03fb5e91eb585f2e",
        "unexpected PhysX source commit",
    )
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
    simulation = metadata.get("simulation", {})
    _require(
        type(simulation.get("seed")) is int and simulation["seed"] >= 0,
        "simulation seed must be a non-negative integer",
    )
    _require(
        scene.get("render", {}).get("seed") == simulation["seed"],
        "scene and simulation seeds disagree",
    )
    _require(simulation.get("fixed_dt_numerator") == 1, "fixed dt numerator changed")
    _require(simulation.get("fixed_dt_denominator") == 120, "fixed dt denominator changed")
    _require(simulation.get("steps") == 300, "simulation step count changed")
    _require(simulation.get("broad_phase") == "gpu", "GPU broad phase is required")
    flags = simulation.get("flags", {})
    for key in ("gpu_dynamics", "pcm", "stabilization"):
        _require(flags.get(key) is True, "required PhysX flag is missing: " + key)
    _require(flags.get("enhanced_determinism") is False, "enhanced determinism is unsupported on GPU")
    _require(
        simulation.get("determinism_limitation") == "enhanced_determinism_unsupported_on_gpu",
        "GPU determinism limitation must be explicit",
    )
    geometry = metadata.get("geometry", {})
    _require(geometry.get("mascots") == MASCOT_COUNT, "metadata mascot count changed")
    _require(geometry.get("spheres") == SPHERE_COUNT, "metadata sphere count changed")
    mascot_scale = _finite_number(geometry.get("mascot_scale"), "geometry.mascot_scale")
    capsule_radius = _finite_number(geometry.get("capsule_radius"), "geometry.capsule_radius")
    capsule_half_height = _finite_number(
        geometry.get("capsule_half_height"), "geometry.capsule_half_height"
    )
    _require(abs(mascot_scale - MASCOT_SCALE) <= 1.0e-6, "metadata scale changed")
    _require(abs(capsule_radius - CAPSULE_RADIUS) <= 1.0e-6, "metadata radius changed")
    _require(
        abs(capsule_half_height - CAPSULE_HALF_HEIGHT) <= 1.0e-6,
        "metadata half height changed",
    )
    results = metadata.get("results", {})
    _require(results.get("toppled_mascots") == toppled, "metadata toppled count disagrees with scene")
    _require(
        results.get("minimum_toppled_mascots") == MIN_TOPPLED,
        "minimum toppled mascot threshold changed",
    )
    _require(
        type(results.get("sleeping_dynamic_actors")) is int
        and results["sleeping_dynamic_actors"] == 0,
        "impact-peak snapshot must have zero sleeping dynamic actors",
    )
    return {"mascots": len(mascots), "spheres": len(spheres), "toppled_mascots": toppled}


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
        "validated PhysX GPU scene: {mascots} mascots, {spheres} spheres, "
        "{toppled_mascots} toppled".format(**summary)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
