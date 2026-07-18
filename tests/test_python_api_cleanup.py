import json
from pathlib import Path

import pytest

import spectraldock
from spectraldock import Renderer
from spectraldock import _native


ROOT = Path(__file__).resolve().parents[1]
MESH = ROOT / "tests/assets/uv-quad.obj"


def _renderer_with_native_render_spy(monkeypatch):
    calls = []
    renderer = Renderer()
    renderer._scene = object()

    def render_to_files(*arguments):
        calls.append(arguments)
        return {"render": {"width": arguments[3], "height": arguments[4]}}

    monkeypatch.setattr(_native, "render_to_files", render_to_files)
    return renderer, calls


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


def test_scene_configuration_has_no_python_exposure_or_clamp_shadow_state():
    renderer = Renderer()

    renderer.integrator(clamp_direct=12.0, clamp_indirect=3.0)
    renderer.background(type="constant", color=(0.0, 0.0, 0.0), exposure=2.0)

    assert not hasattr(renderer, "_exposure")
    assert not hasattr(renderer, "_clamp_direct")
    assert not hasattr(renderer, "_clamp_indirect")


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


@pytest.mark.parametrize("keyword", ["max_depth", "exposure", "linear_output"])
def test_render_rejects_removed_keyword_aliases(tmp_path, keyword):
    with pytest.raises(TypeError, match=keyword):
        Renderer().render(output=tmp_path / "unused.avif", **{keyword: 1})


@pytest.mark.parametrize("name", ["unused.png", "unused.AVIF", "unused.pfm"])
def test_render_rejects_every_noncanonical_output_extension(
    monkeypatch, tmp_path, name
):
    renderer, calls = _renderer_with_native_render_spy(monkeypatch)

    with pytest.raises(ValueError, match="lowercase \\.avif"):
        renderer.render(output=tmp_path / name)

    assert calls == []


def test_render_rejects_excessive_total_pixels_before_native_render(
    monkeypatch, tmp_path
):
    renderer, calls = _renderer_with_native_render_spy(monkeypatch)

    with pytest.raises(ValueError, match=r"width \* height.*2\^25"):
        renderer.render(
            output=tmp_path / "frame.avif", width=16384, height=2049
        )

    assert calls == []


@pytest.mark.parametrize("name", ["stats.png", "stats.JSON", "stats.avif"])
def test_render_rejects_every_noncanonical_stats_extension_before_native_render(
    monkeypatch, tmp_path, name
):
    renderer, calls = _renderer_with_native_render_spy(monkeypatch)

    with pytest.raises(ValueError, match="lowercase \\.json"):
        renderer.render(
            output=tmp_path / "frame.avif",
            stats_output=tmp_path / name,
        )

    assert calls == []


def test_render_rejects_the_same_output_and_stats_path_before_native_render(
    monkeypatch, tmp_path
):
    renderer, calls = _renderer_with_native_render_spy(monkeypatch)
    output = tmp_path / "frame.avif"

    with pytest.raises(ValueError, match="must refer to different files"):
        renderer.render(output=output, stats_output=output)

    assert calls == []


def test_render_rejects_a_normalized_relative_stats_alias_before_native_render(
    monkeypatch, tmp_path
):
    renderer, calls = _renderer_with_native_render_spy(monkeypatch)
    monkeypatch.chdir(tmp_path)
    output = Path("frame.avif")
    nested = Path("nested")
    nested.mkdir()

    with pytest.raises(ValueError, match="must refer to different files"):
        renderer.render(
            output=output,
            stats_output=nested / ".." / output.name,
        )

    assert calls == []


def test_render_rejects_a_json_symlink_to_the_avif_before_native_render(
    monkeypatch, tmp_path
):
    renderer, calls = _renderer_with_native_render_spy(monkeypatch)
    output = tmp_path / "frame.avif"
    stats = tmp_path / "frame.json"
    stats.symlink_to(output.name)

    with pytest.raises(ValueError, match="must refer to different files"):
        renderer.render(output=output, stats_output=stats)

    assert calls == []


def test_render_rejects_a_json_hard_link_to_the_avif_before_native_render(
    monkeypatch, tmp_path
):
    renderer, calls = _renderer_with_native_render_spy(monkeypatch)
    output = tmp_path / "frame.avif"
    stats = tmp_path / "frame.json"
    output.write_bytes(b"existing-output")
    stats.hardlink_to(output)

    with pytest.raises(ValueError, match="must refer to different files"):
        renderer.render(output=output, stats_output=stats)

    assert calls == []


def test_render_writes_the_default_lowercase_json_sidecar(monkeypatch, tmp_path):
    renderer, calls = _renderer_with_native_render_spy(monkeypatch)
    output = tmp_path / "frame.avif"

    stats = renderer.render(output=output, width=8, height=4)

    sidecar = output.with_suffix(".stats.json")
    assert len(calls) == 1
    assert calls[0][1] == str(output)
    assert calls[0][8:10] == (None, None)
    assert sidecar.is_file()
    assert json.loads(sidecar.read_text(encoding="utf-8")) == stats


@pytest.mark.parametrize(
    ("keywords", "expected"),
    [
        ({"clamp_direct": 7.0}, (7.0, None)),
        ({"clamp_indirect": 5.0}, (None, 5.0)),
        ({"clamp_direct": 0.0, "clamp_indirect": 2.0}, (0.0, 2.0)),
    ],
)
def test_render_forwards_only_explicit_per_render_clamp_overrides(
    monkeypatch, tmp_path, keywords, expected
):
    renderer, calls = _renderer_with_native_render_spy(monkeypatch)

    renderer.render(output=tmp_path / "frame.avif", **keywords)

    assert len(calls) == 1
    assert calls[0][8:10] == expected


@pytest.mark.parametrize(
    ("keyword", "value", "message"),
    [
        ("clamp_direct", -1.0, "non-negative"),
        ("clamp_indirect", -1.0, "non-negative"),
        ("clamp_direct", float("nan"), "clamp_direct must be finite"),
        ("clamp_indirect", float("inf"), "clamp_indirect must be finite"),
    ],
)
def test_render_rejects_invalid_clamp_overrides_before_native_render(
    monkeypatch, tmp_path, keyword, value, message
):
    renderer, calls = _renderer_with_native_render_spy(monkeypatch)

    with pytest.raises(ValueError, match=message):
        renderer.render(output=tmp_path / "frame.avif", **{keyword: value})

    assert calls == []
