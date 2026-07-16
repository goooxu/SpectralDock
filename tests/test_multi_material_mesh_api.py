from pathlib import Path

import pytest

from spectraldock import MaterialHandle, Renderer


ROOT = Path(__file__).resolve().parents[1]
MESH = ROOT / "tests/assets/multi-material-mesh.obj"


class RecordingBuilder:
    def __init__(self) -> None:
        self.mesh_calls = []
        self.instance_calls = []

    def add_mesh(self, *arguments):
        self.mesh_calls.append(arguments)
        return 17

    def add_mesh_instance(self, *arguments):
        self.instance_calls.append(arguments)
        return 23


def material(renderer: Renderer, name: str, identifier: int) -> MaterialHandle:
    return MaterialHandle(name, identifier, renderer._owner)


def recording_renderer() -> tuple[Renderer, RecordingBuilder]:
    renderer = Renderer()
    builder = RecordingBuilder()
    renderer._builder = builder
    return renderer, builder


def test_mesh_forwards_a_sorted_explicit_material_mapping():
    renderer, builder = recording_renderer()
    red = material(renderer, "red", 4)
    screen = material(renderer, "screen", 9)
    metal = material(renderer, "metal", 2)

    mesh = renderer.mesh(
        "fixture",
        MESH,
        materials={
            "ScreenPanel": screen,
            "RedPanel": red,
            "MetalPanel": metal,
        },
    )

    assert builder.mesh_calls == [
        (
            "fixture",
            str(MESH),
            [("MetalPanel", 2), ("RedPanel", 4), ("ScreenPanel", 9)],
        )
    ]
    assert mesh._has_material_mapping is True


def test_unmapped_mesh_forwards_an_empty_mapping_and_retains_instance_materials():
    renderer, builder = recording_renderer()
    surface = material(renderer, "surface", 6)
    mesh = renderer.mesh("fixture", MESH)

    renderer.object(name="instance", type="mesh", mesh=mesh, material=surface)

    assert builder.mesh_calls == [("fixture", str(MESH), [])]
    assert mesh._has_material_mapping is False
    assert builder.instance_calls == [
        (
            "instance",
            17,
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0),
            (1.0, 1.0, 1.0),
            6,
            6,
            -1,
            0.5,
        )
    ]


def test_explicit_empty_mapping_keeps_legacy_mesh_behavior():
    renderer, builder = recording_renderer()
    surface = material(renderer, "surface", 6)
    mesh = renderer.mesh("fixture", MESH, materials={})

    renderer.object(name="instance", type="mesh", mesh=mesh, material=surface)

    assert builder.mesh_calls == [("fixture", str(MESH), [])]
    assert mesh._has_material_mapping is False
    assert builder.instance_calls[0][5:7] == (6, 6)


@pytest.mark.parametrize(
    "materials, error, message",
    [
        ([], TypeError, "mapping"),
        ({"": object()}, ValueError, "materials key"),
        ({1: object()}, ValueError, "materials key"),
        ({"RedPanel": object()}, TypeError, "MaterialHandle"),
    ],
)
def test_mesh_rejects_invalid_material_mappings(materials, error, message):
    renderer, builder = recording_renderer()

    with pytest.raises(error, match=message):
        renderer.mesh("fixture", MESH, materials=materials)

    assert builder.mesh_calls == []


def test_mesh_rejects_material_handles_from_another_renderer():
    renderer, builder = recording_renderer()
    foreign, _ = recording_renderer()

    with pytest.raises(ValueError, match="different Renderer"):
        renderer.mesh(
            "fixture",
            MESH,
            materials={"RedPanel": material(foreign, "foreign", 3)},
        )

    assert builder.mesh_calls == []


@pytest.mark.parametrize("keyword", ["material", "front_material", "back_material"])
def test_mapped_mesh_instance_rejects_material_overrides(keyword):
    renderer, builder = recording_renderer()
    surface = material(renderer, "surface", 6)
    mesh = renderer.mesh("fixture", MESH, materials={"RedPanel": surface})

    with pytest.raises(TypeError, match="do not accept"):
        renderer.object(
            name="instance",
            type="mesh",
            mesh=mesh,
            **{keyword: surface},
        )

    assert builder.instance_calls == []


def test_mapped_mesh_instance_uses_embedded_material_ids_and_may_omit_material():
    renderer, builder = recording_renderer()
    surface = material(renderer, "surface", 6)
    mesh = renderer.mesh("fixture", MESH, materials={"RedPanel": surface})

    renderer.object(
        name="instance",
        type="mesh",
        mesh=mesh,
        translate=(1.0, 2.0, 3.0),
        rotate_degrees=(4.0, 5.0, 6.0),
        scale=(0.5, 0.75, 1.25),
    )

    assert builder.instance_calls == [
        (
            "instance",
            17,
            (1.0, 2.0, 3.0),
            (4.0, 5.0, 6.0),
            (0.5, 0.75, 1.25),
            -1,
            -1,
            -1,
            0.5,
        )
    ]


def test_public_api_builds_a_material_mapped_mesh_without_a_gpu():
    renderer = Renderer()
    red = renderer.material(
        name="red", type="lambertian", base_color=(0.8, 0.1, 0.05)
    )
    screen = renderer.material(
        name="screen", type="lambertian", base_color=(0.2, 0.7, 0.9)
    )
    metal = renderer.material(
        name="metal",
        type="metal",
        base_color=(0.7, 0.7, 0.7),
        roughness=0.25,
    )

    mesh = renderer.mesh(
        "fixture",
        MESH,
        materials={
            "RedPanel": red,
            "ScreenPanel": screen,
            "MetalPanel": metal,
        },
    )
    instance = renderer.object(name="instance", type="mesh", mesh=mesh)

    assert mesh.id >= 0
    assert instance.id >= 0
