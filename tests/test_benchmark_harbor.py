import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "tools" / "generate_benchmark_harbor.py"


def run_generator(output: Path, seed: int):
    return subprocess.run(
        [sys.executable, str(GENERATOR), "--output", str(output), "--seed", str(seed)],
        universal_newlines=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_harbor_is_deterministic_and_seeded(tmp_path: Path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    different = tmp_path / "different.json"
    assert run_generator(first, 5090).returncode == 0
    assert run_generator(second, 5090).returncode == 0
    assert run_generator(different, 4090).returncode == 0
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes() != different.read_bytes()


def test_harbor_counts_non_overlap_and_shared_mesh(tmp_path: Path):
    output = tmp_path / "harbor.json"
    result = run_generator(output, 20260707)
    assert result.returncode == 0, result.stderr
    scene = json.loads(output.read_text(encoding="utf-8"))

    assert scene["schema_version"] == 2
    assert scene["meshes"] == [
        {"name": "mascot", "path": "../assets/examples/models/capsule-mascot.obj"}
    ]
    assert len(scene["objects"]) == 1040

    instances = [obj for obj in scene["objects"] if obj["type"] == "mesh"]
    waves = [obj for obj in scene["objects"] if obj["type"] == "sphere"]
    assert len(instances) == 16
    assert len(waves) == 1024
    assert [obj["name"] for obj in instances] == [
        "mascot_{:02d}".format(index) for index in range(16)
    ]
    assert {obj["mesh"] for obj in instances} == {"mascot"}
    assert {obj["material"] for obj in instances} == {
        "mascot_0", "mascot_1", "mascot_2", "mascot_3"
    }
    assert {tuple(obj["transform"]["scale"]) for obj in instances} == {
        (0.88, 0.88, 0.88)
    }
    assert all(
        abs(obj["transform"]["rotate_degrees"][0]) <= 1.5
        for obj in instances
    )
    assert len({tuple(obj["transform"]["translate"]) for obj in instances}) == 16

    # Include the model half-diagonal plus the small pitch/roll footprint.
    mascot_radius = 0.9
    for index, mascot in enumerate(instances):
        x, _, z = mascot["transform"]["translate"]
        for other in instances[:index]:
            ox, _, oz = other["transform"]["translate"]
            assert (x - ox) ** 2 + (z - oz) ** 2 > (2.0 * mascot_radius) ** 2

    for index, sphere in enumerate(waves):
        x, y, z = sphere["center"]
        radius = sphere["radius"]
        for other in waves[:index]:
            ox, oy, oz = other["center"]
            minimum = radius + other["radius"]
            distance_squared = (x - ox) ** 2 + (y - oy) ** 2 + (z - oz) ** 2
            assert distance_squared > minimum**2


def test_checked_in_harbor_matches_default_generator(tmp_path: Path):
    generated = tmp_path / "benchmark-harbor.json"
    result = run_generator(generated, 20260707)
    assert result.returncode == 0, result.stderr
    assert generated.read_bytes() == (ROOT / "scenes/benchmark-harbor.json").read_bytes()
