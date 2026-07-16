from pathlib import Path

import pytest

import spectraldock
from spectraldock import Renderer
from spectraldock import _native


ROOT = Path(__file__).resolve().parents[1]
MESH = ROOT / "tests/assets/uv-quad.obj"


def surface(renderer: Renderer):
    return renderer.material(
        name="surface", type="lambertian", base_color=(0.7, 0.7, 0.7)
    )


def test_removed_public_capability_and_lookup_symbols_are_absent():
    renderer = Renderer()

    assert not hasattr(spectraldock, "LightHandle")
    assert not hasattr(_native, "gpu_enabled")
    for name in (
        "gpu_enabled",
        "texture_handle",
        "material_handle",
        "mesh_handle",
        "object_handle",
        "light_handle",
    ):
        assert not hasattr(renderer, name)


def test_camera_accepts_vfov_and_rejects_the_removed_alias():
    renderer = Renderer()
    renderer.camera(look_from=(0.0, 0.0, 2.0), look_at=(0.0, 0.0, 0.0), vfov=35.0)

    with pytest.raises(TypeError, match="vertical_fov_degrees"):
        Renderer().camera(
            look_from=(0.0, 0.0, 2.0),
            look_at=(0.0, 0.0, 0.0),
            vertical_fov_degrees=35.0,
        )


def test_object_rejects_removed_geometry_and_transform_aliases():
    renderer = Renderer()
    material = surface(renderer)
    mesh = renderer.mesh("quad", MESH)

    with pytest.raises(ValueError, match="unsupported object type"):
        renderer.object(
            name="legacy-mesh", type="mesh_instance", mesh=mesh, material=material
        )
    with pytest.raises(TypeError, match="unsupported mesh argument.*transform"):
        renderer.object(
            name="nested-transform",
            type="mesh",
            mesh=mesh,
            material=material,
            transform={"translate": (1.0, 2.0, 3.0)},
        )
    with pytest.raises(ValueError, match="unsupported object type"):
        renderer.object(
            name="legacy-sketch",
            type="sketch",
            p1=(0.0, 0.0, 0.0),
            p2=(0.0, 1.0, 0.0),
            p3=(1.0, 1.0, 0.0),
            material=material,
        )


def test_parabola_requires_flat_clip_bounds():
    renderer = Renderer()
    material = surface(renderer)

    with pytest.raises(TypeError, match="clip_min"):
        renderer.object(
            name="legacy-parabola",
            type="parabola",
            origin=(0.0, 0.0, 0.0),
            normal=(0.0, 1.0, 0.0),
            focus=(0.0, 0.0, 1.0),
            clip={"min": (-1.0, -1.0, -1.0), "max": (1.0, 1.0, 1.0)},
            material=material,
        )

    handle = renderer.object(
        name="parabola",
        type="parabola",
        origin=(0.0, 0.0, 0.0),
        normal=(0.0, 1.0, 0.0),
        focus=(0.0, 0.0, 1.0),
        clip_min=(-1.0, -1.0, -1.0),
        clip_max=(1.0, 1.0, 1.0),
        material=material,
    )
    assert handle.id >= 0


def test_light_is_a_terminal_registration_operation():
    renderer = Renderer()

    assert renderer.light(
        name="key",
        type="point",
        position=(0.0, 1.0, 0.0),
        intensity=(1.0, 1.0, 1.0),
    ) is None


@pytest.mark.parametrize("keyword", ["max_depth", "exposure"])
def test_render_rejects_removed_keyword_aliases(tmp_path, keyword):
    with pytest.raises(TypeError, match=keyword):
        Renderer().render(output=tmp_path / "unused.png", **{keyword: 1})
