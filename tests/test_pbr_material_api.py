from pathlib import Path
import os

import pytest

from spectraldock import Renderer, _native


ROOT = Path(__file__).resolve().parents[1]
QUAD = ROOT / "tests/assets/pbr-quad.obj"
NO_UV_QUAD = ROOT / "tests/assets/pbr-quad-no-uv.obj"
DEGENERATE_UV_QUAD = ROOT / "tests/assets/pbr-quad-degenerate-uv.obj"


class RecordingBuilder:
    def __init__(self) -> None:
        self.image_texture_calls = []
        self.pbr_material_calls = []

    def add_image_texture(self, *arguments):
        self.image_texture_calls.append(arguments)
        return len(self.image_texture_calls) + 10

    def add_pbr_material(self, *arguments):
        self.pbr_material_calls.append(arguments)
        return len(self.pbr_material_calls) + 20


def recording_renderer() -> tuple[Renderer, RecordingBuilder]:
    renderer = Renderer()
    builder = RecordingBuilder()
    renderer._builder = builder
    return renderer, builder


def image_texture(
    renderer: Renderer,
    name: str,
    *,
    color_space: str = "linear",
):
    return renderer.texture(
        name=name,
        type="image",
        path=Path(f"{name}.avif"),
        color_space=color_space,
    )


def test_image_texture_forwards_default_and_explicit_wrap_modes():
    renderer, builder = recording_renderer()

    renderer.texture(
        name="default",
        type="image",
        path=Path("default.avif"),
        color_space="srgb",
    )
    renderer.texture(
        name="tiled",
        type="image",
        path=Path("tiled.avif"),
        color_space="linear",
        wrap_u="repeat",
        wrap_v="mirrored_repeat",
    )

    assert builder.image_texture_calls == [
        ("default", "default.avif", True, "clamp_to_edge", "clamp_to_edge"),
        ("tiled", "tiled.avif", False, "repeat", "mirrored_repeat"),
    ]


@pytest.mark.parametrize("path", ["legacy.png", "upper.AVIF", "linear.pfm"])
def test_image_texture_rejects_noncanonical_extensions(path):
    renderer, builder = recording_renderer()
    with pytest.raises(ValueError, match="lowercase \\.avif"):
        renderer.texture(name="invalid", type="image", path=path)
    assert builder.image_texture_calls == []


@pytest.mark.parametrize("axis", ["wrap_u", "wrap_v"])
@pytest.mark.parametrize("value", ["clamp", "mirror", "", None, 3])
def test_image_texture_rejects_unknown_wrap_modes(axis, value):
    renderer, builder = recording_renderer()

    with pytest.raises((TypeError, ValueError), match=axis):
        renderer.texture(
            name="invalid",
            type="image",
            path="invalid.avif",
            **{axis: value},
        )

    assert builder.image_texture_calls == []


def test_pbr_material_forwards_gltf_defaults():
    renderer, builder = recording_renderer()

    material = renderer.material(name="default-pbr", type="pbr")

    assert material.id == 21
    assert builder.pbr_material_calls == [
        (
            "default-pbr",
            -1,
            -1,
            -1,
            (1.0, 1.0, 1.0),
            1.0,
            1.0,
            1.0,
        )
    ]


def test_pbr_material_forwards_independent_texture_slots_and_factors():
    renderer, builder = recording_renderer()
    base = image_texture(renderer, "base", color_space="srgb")
    metallic_roughness = image_texture(renderer, "mr")
    normal = image_texture(renderer, "normal")

    renderer.material(
        name="paint",
        type="pbr",
        base_color=(0.8, 0.6, 0.4),
        base_color_texture=base,
        metallic=0.75,
        roughness=0.25,
        metallic_roughness_texture=metallic_roughness,
        normal_texture=normal,
        normal_scale=-2.0,
    )

    assert builder.pbr_material_calls == [
        (
            "paint",
            base.id,
            metallic_roughness.id,
            normal.id,
            (0.8, 0.6, 0.4),
            0.75,
            0.25,
            -2.0,
        )
    ]


@pytest.mark.parametrize(
    "keyword",
    ["metallic_roughness_texture", "normal_texture"],
)
def test_pbr_data_textures_must_be_linear(keyword):
    renderer, builder = recording_renderer()
    encoded = image_texture(renderer, "encoded", color_space="srgb")

    with pytest.raises(ValueError, match=rf"{keyword}.*linear"):
        renderer.material(name="invalid", type="pbr", **{keyword: encoded})

    assert builder.pbr_material_calls == []


@pytest.mark.parametrize(
    "keyword",
    ["base_color_texture", "metallic_roughness_texture", "normal_texture"],
)
def test_pbr_texture_handles_must_belong_to_the_same_renderer(keyword):
    renderer, builder = recording_renderer()
    foreign, _ = recording_renderer()
    texture = image_texture(foreign, "foreign")

    with pytest.raises(ValueError, match="different Renderer"):
        renderer.material(name="invalid", type="pbr", **{keyword: texture})

    assert builder.pbr_material_calls == []


@pytest.mark.parametrize(
    "keyword, value",
    [
        ("texture", object()),
        ("emission", (1.0, 1.0, 1.0)),
        ("ior", 1.5),
        ("absorption", (0.1, 0.1, 0.1)),
    ],
)
def test_pbr_rejects_legacy_material_arguments(keyword, value):
    renderer, builder = recording_renderer()

    with pytest.raises(TypeError, match=keyword):
        renderer.material(name="invalid", type="pbr", **{keyword: value})

    assert builder.pbr_material_calls == []


@pytest.mark.parametrize(
    "keyword, value",
    [
        ("metallic", -0.001),
        ("metallic", 1.001),
        ("roughness", -0.001),
        ("roughness", 1.001),
    ],
)
def test_native_pbr_factors_are_unit_interval(keyword, value):
    with pytest.raises(RuntimeError, match=rf"{keyword}.*\[0, 1\]"):
        Renderer().material(name="invalid", type="pbr", **{keyword: value})


@pytest.mark.parametrize(
    "base_color",
    [(-0.001, 0.5, 0.5), (0.5, 1.001, 0.5)],
)
def test_native_pbr_base_color_is_unit_interval(base_color):
    with pytest.raises(RuntimeError, match=r"base_color.*\[0, 1\]"):
        Renderer().material(
            name="invalid", type="pbr", base_color=base_color
        )


def test_native_pbr_constant_base_color_texture_is_unit_interval():
    renderer = Renderer()
    texture = renderer.texture(
        name="hdr-constant", type="constant", color=(2.0, 0.5, 0.5)
    )

    with pytest.raises(
        RuntimeError, match=r"base_color_texture.*\[0, 1\]"
    ):
        renderer.material(
            name="invalid", type="pbr", base_color_texture=texture
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_normal_scale_must_be_finite(value):
    renderer, builder = recording_renderer()

    with pytest.raises(ValueError, match="normal_scale.*finite"):
        renderer.material(
            name="invalid", type="pbr", normal_scale=value
        )

    assert builder.pbr_material_calls == []


def write_linear_normal(path: Path) -> None:
    _native.write_texture_avif(
        os.fspath(path), 1, 1, bytes((128, 128, 255, 255)), False
    )


def normal_mapped_material(renderer: Renderer, path: Path):
    normal = renderer.texture(
        name="normal-map",
        type="image",
        path=path,
        color_space="linear",
    )
    return renderer.material(
        name="normal-mapped", type="pbr", normal_texture=normal
    )


def test_normal_map_is_rejected_by_analytic_geometry(tmp_path):
    path = tmp_path / "normal.avif"
    write_linear_normal(path)
    renderer = Renderer()
    material = normal_mapped_material(renderer, path)

    with pytest.raises(RuntimeError, match="normal map.*mesh"):
        renderer.object(
            name="invalid",
            type="rectangle",
            p1=(-1.0, -1.0, 0.0),
            p2=(1.0, -1.0, 0.0),
            p3=(1.0, 1.0, 0.0),
            material=material,
        )


def test_pbr_without_a_normal_map_can_bind_analytic_geometry():
    renderer = Renderer()
    material = renderer.material(name="plain-pbr", type="pbr")

    instance = renderer.object(
        name="valid",
        type="rectangle",
        p1=(-1.0, -1.0, 0.0),
        p2=(1.0, -1.0, 0.0),
        p3=(1.0, 1.0, 0.0),
        material=material,
    )

    assert instance.id >= 0


@pytest.mark.parametrize("mesh_path", [NO_UV_QUAD, DEGENERATE_UV_QUAD])
def test_normal_map_requires_a_valid_mesh_tangent_frame(tmp_path, mesh_path):
    path = tmp_path / "normal.avif"
    write_linear_normal(path)
    renderer = Renderer()
    material = normal_mapped_material(renderer, path)
    mesh = renderer.mesh(name="invalid-tangents", path=mesh_path)

    with pytest.raises(RuntimeError, match="normal map|tangent|UV"):
        renderer.object(
            name="invalid", type="mesh", mesh=mesh, material=material
        )


def test_degenerate_uvs_remain_valid_without_a_normal_map():
    renderer = Renderer()
    material = renderer.material(name="plain-pbr", type="pbr")
    mesh = renderer.mesh(name="ordinary-lookup", path=DEGENERATE_UV_QUAD)

    instance = renderer.object(
        name="valid", type="mesh", mesh=mesh, material=material
    )

    assert instance.id >= 0


def test_valid_normal_mapped_mesh_builds_without_a_gpu(tmp_path):
    path = tmp_path / "normal.avif"
    write_linear_normal(path)
    renderer = Renderer()
    material = normal_mapped_material(renderer, path)
    mesh = renderer.mesh(name="valid-tangents", path=QUAD)

    instance = renderer.object(
        name="valid", type="mesh", mesh=mesh, material=material
    )

    assert instance.id >= 0
