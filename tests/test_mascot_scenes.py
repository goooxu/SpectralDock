import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MASCOT_MESH = {
    "name": "mascot",
    "path": "../assets/examples/models/capsule-mascot.obj",
}
SCENE_INSTANCE_COUNTS = {
    "material-cathedral.json": 3,
    "neon-koi.json": 1,
    "celestial-archive.json": 1,
    "reflector-laboratory.json": 1,
    "benchmark-harbor.json": 16,
    "rocket-test-stand.json": 1,
}
LEGACY_TOKENS = (
    "tea" + "pot",
    "ben" + "chy",
    "bun" + "ny",
    "dra" + "gon",
    "stan" + "ford",
    "fetch_" + "models",
)


def load_scene(name):
    return json.loads((ROOT / "scenes" / name).read_text(encoding="utf-8"))


def test_all_gallery_scenes_share_only_the_mascot_mesh():
    total = 0
    for name, expected_count in SCENE_INSTANCE_COUNTS.items():
        scene = load_scene(name)
        assert scene["meshes"] == [MASCOT_MESH]
        instances = [obj for obj in scene["objects"] if obj["type"] == "mesh"]
        assert len(instances) == expected_count
        assert {obj["mesh"] for obj in instances} == {"mascot"}
        assert not any(token in json.dumps(scene).lower() for token in LEGACY_TOKENS)
        total += len(instances)

    assert total == 23


def test_static_gallery_mascot_placements_match_the_reviewed_compositions():
    expected = {
        "material-cathedral.json": {
            "ceramic_mascot": {
                "material": "ceramic",
                "transform": {
                    "translate": [-3.2, 0.72, -1.0],
                    "rotate_degrees": [0.0, -24.0, 0.0],
                    "scale": [0.78, 0.78, 0.78],
                },
            },
            "metal_mascot": {
                "material": "rough_metal",
                "transform": {
                    "translate": [0.0, 0.88, -1.4],
                    "rotate_degrees": [0.0, 18.0, 0.0],
                    "scale": [0.78, 0.78, 0.78],
                },
            },
            "glass_mascot": {
                "material": "glass",
                "transform": {
                    "translate": [3.2, 0.72, -1.0],
                    "rotate_degrees": [0.0, 52.0, 0.0],
                    "scale": [0.78, 0.78, 0.78],
                },
            },
        },
        "celestial-archive.json": {
            "bronze_mascot": {
                "material": "bronze",
                "transform": {
                    "translate": [0.0, 0.75, -2.0],
                    "rotate_degrees": [0.0, 31.2, 0.0],
                    "scale": [1.3, 1.3, 1.3],
                },
            },
        },
        "reflector-laboratory.json": {
            "ceramic_mascot": {
                "material": "ceramic",
                "transform": {
                    "translate": [0.0, 0.64, -0.9],
                    "rotate_degrees": [0.0, 24.0, 0.0],
                    "scale": [1.0, 1.0, 1.0],
                },
            },
        },
    }

    for scene_name, placements in expected.items():
        objects = load_scene(scene_name)["objects"]
        actual = {
            obj["name"]: {
                "material": obj["material"],
                "transform": obj["transform"],
            }
            for obj in objects
            if obj["type"] == "mesh"
        }
        assert actual == placements


def test_neon_koi_uses_a_central_metal_mascot():
    scene = load_scene("neon-koi.json")
    mascot = next(obj for obj in scene["objects"] if obj["name"] == "metal_mascot")
    assert mascot["type"] == "mesh"
    assert mascot["material"] == "wet_floor"
    assert mascot["transform"] == {
        "translate": [0.1, 0.0, 0.4],
        "rotate_degrees": [0.0, 0.0, 0.0],
        "scale": [1.0, 1.0, 1.0],
    }


def test_rocket_test_stand_uses_procedural_flame_without_warm_proxy_light():
    scene = load_scene("rocket-test-stand.json")
    assert scene["schema_version"] == 3
    assert scene["render"] == {
        "width": 1920,
        "height": 1080,
        "spp": 2048,
        "max_depth": 12,
        "seed": 707,
        "denoise": False,
    }
    assert scene["camera"]["aperture"] == 0.0
    assert [light["type"] for light in scene["lights"]] == ["flame", "disk"]
    flame = scene["lights"][0]
    assert flame["name"] == "rocket_plume"
    assert flame["axis"] == [0.0, -1.0, 0.0]
    assert flame["position"][1] - flame["height"] > 0.0
    assert "object" not in flame
    fill = scene["lights"][1]
    assert fill["name"] == "inspection_fill"
    assert fill["emission"][2] > fill["emission"][1] > fill["emission"][0]
    assert max(fill["emission"]) <= 3.0


def test_legacy_model_assets_and_download_tool_are_removed():
    model_dir = ROOT / "assets" / "examples" / "models"
    removed_models = (
        "utah-" + "tea" + "pot.obj",
        "3d" + "ben" + "chy.obj",
        "stan" + "ford-" + "bun" + "ny.obj",
        "stan" + "ford-" + "dra" + "gon.obj",
    )
    assert not any((model_dir / name).exists() for name in removed_models)
    assert not (ROOT / "tools" / ("fetch_" + "models.py")).exists()
    assert not (ROOT / "tests" / ("test_fetch_" + "models.py")).exists()


def test_repository_text_has_no_legacy_model_references():
    roots = (
        "assets",
        "docs",
        "include",
        "scenes",
        "scripts",
        "src",
        "tests",
        "third_party",
        "tools",
    )
    text_suffixes = {".cpp", ".cu", ".h", ".json", ".md", ".py", ".sh", ".txt"}
    paths = [
        ROOT / "README.md",
        ROOT / ".gitignore",
        ROOT / "CMakeLists.txt",
        ROOT / "Dockerfile",
    ]
    for root_name in roots:
        paths.extend((ROOT / root_name).rglob("*"))

    for candidate in paths:
        if not candidate.is_file():
            continue
        if candidate.name != "CMakeLists.txt" and candidate.suffix not in text_suffixes:
            continue
        text = candidate.read_text(encoding="utf-8").lower()
        assert not any(token in text for token in LEGACY_TOKENS), candidate
