#!/usr/bin/env python3
"""GPU contracts for PBR texture semantics and tangent-space normals."""

import argparse
import math
import struct
import sys
import tempfile
from pathlib import Path

from PIL import Image

from spectraldock import Renderer


ROOT = Path(__file__).resolve().parents[1]
QUAD = ROOT / "tests/assets/pbr-quad.obj"
MIRRORED_QUAD = ROOT / "tests/assets/pbr-quad-mirrored.obj"
REVERSED_NORMAL_QUAD = ROOT / "tests/assets/pbr-quad-reversed-normal.obj"
SEED = 2957
IRRADIANCE = tuple(12.0 * math.pi for _ in range(3))


def nonnegative_integer(value: str) -> int:
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return result


def write_rgba(path: Path, size: tuple[int, int], pixels) -> None:
    image = Image.new("RGBA", size)
    image.putdata(tuple(pixels))
    image.save(path)


def write_constant_uv_quad(path: Path, u: float, v: float = 0.5) -> None:
    # A degenerate UV chart remains valid for ordinary color lookup. Tangent
    # validation must be conditional on an actually bound normal map.
    path.write_text(
        "\n".join(
            [
                "v -2.0 -2.0 0.0",
                "v  2.0 -2.0 0.0",
                "v  2.0  2.0 0.0",
                "v -2.0  2.0 0.0",
                f"vt {u:.9g} {v:.9g}",
                f"vt {u:.9g} {v:.9g}",
                f"vt {u:.9g} {v:.9g}",
                f"vt {u:.9g} {v:.9g}",
                "vn 0.0 0.0 1.0",
                "s 1",
                "f 1/1/1 2/2/1 3/3/1",
                "f 1/1/1 3/3/1 4/4/1",
                "",
            ]
        ),
        encoding="utf-8",
    )


def read_single_pixel_pfm(path: Path) -> tuple[float, float, float]:
    with path.open("rb") as stream:
        if stream.readline() != b"PF\n" or stream.readline() != b"1 1\n":
            raise RuntimeError(f"{path.name}: expected a 1x1 RGB PFM")
        if float(stream.readline()) >= 0.0:
            raise RuntimeError(f"{path.name}: expected little-endian PFM data")
        payload = stream.read()
    if len(payload) != 12:
        raise RuntimeError(f"{path.name}: expected 12 data bytes, got {len(payload)}")
    pixel = struct.unpack("<3f", payload)
    if any(not math.isfinite(value) for value in pixel):
        raise RuntimeError(f"{path.name}: linear output contains a non-finite value")
    return pixel


def common_renderer(*, device: int) -> Renderer:
    renderer = Renderer(device=device)
    renderer.integrator(
        direct_light_sampling="importance", clamp_direct=0.0, clamp_indirect=0.0
    )
    renderer.camera(
        look_from=(0.0, 0.0, 4.0),
        look_at=(0.0, 0.0, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=2.0,
        aperture=0.0,
        focus_distance=4.0,
    )
    renderer.background(type="constant", color=(0.0, 0.0, 0.0), exposure=0.0)
    return renderer


def render_probe(renderer: Renderer, directory: Path, name: str) -> tuple[float, ...]:
    png = directory / f"{name}.png"
    pfm = directory / f"{name}.pfm"
    stats = renderer.render(
        output=png,
        stats_output=png.with_suffix(".stats.json"),
        linear_output=pfm,
        width=1,
        height=1,
        spp=1,
        depth=1,
        seed=SEED,
        denoise=False,
        clamp_direct=0.0,
        clamp_indirect=0.0,
    )
    with Image.open(png) as decoded:
        decoded.load()
        if decoded.size != (1, 1) or decoded.mode != "RGBA":
            raise RuntimeError(
                f"{name}: unexpected PNG output {decoded.size} {decoded.mode}"
            )
    render = stats.get("render", {})
    if (
        render.get("denoised") is not False
        or render.get("clamp_direct") != 0.0
        or render.get("clamp_indirect") != 0.0
    ):
        raise RuntimeError(f"{name}: PBR contract used biased render settings")
    return read_single_pixel_pfm(pfm)


def textured_emitter_renderer(
    *,
    device: int,
    texture_path: Path,
    mesh_path: Path,
    color_space: str,
    wrap_u: str = "clamp_to_edge",
    wrap_v: str = "clamp_to_edge",
) -> Renderer:
    renderer = common_renderer(device=device)
    texture = renderer.texture(
        name="probe-texture",
        type="image",
        path=texture_path,
        color_space=color_space,
        wrap_u=wrap_u,
        wrap_v=wrap_v,
    )
    emitter = renderer.material(
        name="probe-emitter",
        type="emitter",
        texture=texture,
        emission=(1.0, 1.0, 1.0),
    )
    mesh = renderer.mesh(name="probe-quad", path=mesh_path)
    renderer.object(name="probe", type="mesh", mesh=mesh, material=emitter)
    return renderer


def pbr_renderer(
    *,
    device: int,
    mesh_path: Path = QUAD,
    scale=(1.0, 1.0, 1.0),
    base_color=(0.8, 0.42, 0.16),
    base_color_path: Path | None = None,
    base_color_space="linear",
    metallic=0.45,
    roughness=0.38,
    mr_path: Path | None = None,
    normal_path: Path | None = None,
    normal_scale=1.0,
    legacy_metal=False,
    light_direction=(0.8, 0.0, 0.6),
) -> Renderer:
    renderer = common_renderer(device=device)
    if legacy_metal:
        material = renderer.material(
            name="surface",
            type="metal",
            base_color=base_color,
            roughness=roughness,
        )
    else:
        base_texture = None
        if base_color_path is not None:
            base_texture = renderer.texture(
                name="base-color",
                type="image",
                path=base_color_path,
                color_space=base_color_space,
            )
        mr = None
        if mr_path is not None:
            mr = renderer.texture(
                name="metallic-roughness",
                type="image",
                path=mr_path,
                color_space="linear",
            )
        normal = None
        if normal_path is not None:
            normal = renderer.texture(
                name="normal",
                type="image",
                path=normal_path,
                color_space="linear",
            )
        material = renderer.material(
            name="surface",
            type="pbr",
            base_color=base_color,
            base_color_texture=base_texture,
            metallic=metallic,
            roughness=roughness,
            metallic_roughness_texture=mr,
            normal_texture=normal,
            normal_scale=normal_scale,
        )
    mesh = renderer.mesh(name="surface-quad", path=mesh_path)
    renderer.object(
        name="surface",
        type="mesh",
        mesh=mesh,
        scale=scale,
        material=material,
    )
    renderer.light(
        name="probe-light",
        type="directional",
        direction=light_direction,
        irradiance=IRRADIANCE,
    )
    return renderer


def assert_close(
    actual: tuple[float, ...],
    expected: tuple[float, ...],
    label: str,
    *,
    relative: float = 2.0e-5,
    absolute: float = 2.0e-6,
) -> None:
    for channel, (left, right) in enumerate(zip(actual, expected)):
        tolerance = max(absolute, relative * max(abs(left), abs(right)))
        if abs(left - right) > tolerance:
            raise RuntimeError(
                f"{label}: channel {channel} differs: {left:.9g} vs "
                f"{right:.9g} (tolerance {tolerance:.3g})"
            )


def luminance(pixel: tuple[float, ...]) -> float:
    return 0.2126 * pixel[0] + 0.7152 * pixel[1] + 0.0722 * pixel[2]


def check_srgb_filtering_and_wrap(directory: Path, *, device: int) -> None:
    midpoint = directory / "black-white.png"
    write_rgba(midpoint, (2, 1), [(0, 0, 0, 255), (255, 255, 255, 255)])
    midpoint_mesh = directory / "uv-midpoint.obj"
    write_constant_uv_quad(midpoint_mesh, 0.5)

    srgb = render_probe(
        textured_emitter_renderer(
            device=device,
            texture_path=midpoint,
            mesh_path=midpoint_mesh,
            color_space="srgb",
        ),
        directory,
        "srgb-midpoint",
    )
    linear = render_probe(
        textured_emitter_renderer(
            device=device,
            texture_path=midpoint,
            mesh_path=midpoint_mesh,
            color_space="linear",
        ),
        directory,
        "linear-midpoint",
    )
    assert_close(srgb, (0.5, 0.5, 0.5), "sRGB pre-filter decode", absolute=0.015)
    assert_close(srgb, linear, "sRGB/linear black-white midpoint", absolute=0.015)

    red_blue = directory / "red-blue.png"
    write_rgba(red_blue, (2, 1), [(255, 0, 0, 255), (0, 0, 255, 255)])
    outside_mesh = directory / "uv-outside.obj"
    write_constant_uv_quad(outside_mesh, 1.25)
    wrapped = {}
    for mode in ("clamp_to_edge", "repeat", "mirrored_repeat"):
        wrapped[mode] = render_probe(
            textured_emitter_renderer(
                device=device,
                texture_path=red_blue,
                mesh_path=outside_mesh,
                color_space="linear",
                wrap_u=mode,
            ),
            directory,
            f"wrap-{mode}",
        )
    if not (
        wrapped["repeat"][0] > 0.95
        and wrapped["repeat"][2] < 0.05
        and wrapped["clamp_to_edge"][2] > 0.95
        and wrapped["clamp_to_edge"][0] < 0.05
        and wrapped["mirrored_repeat"][2] > 0.95
        and wrapped["mirrored_repeat"][0] < 0.05
    ):
        raise RuntimeError(f"unexpected CUDA wrap samples: {wrapped!r}")

    top_bottom = directory / "top-bottom.png"
    write_rgba(top_bottom, (1, 2), [(255, 0, 0, 255), (0, 0, 255, 255)])
    inside_v_mesh = directory / "uv-v-inside.obj"
    write_constant_uv_quad(inside_v_mesh, 0.5, 0.25)
    flipped_v = render_probe(
        textured_emitter_renderer(
            device=device,
            texture_path=top_bottom,
            mesh_path=inside_v_mesh,
            color_space="linear",
        ),
        directory,
        "v-origin-flip",
    )
    if not (flipped_v[2] > 0.95 and flipped_v[0] < 0.05):
        raise RuntimeError(f"scene/CUDA V-origin flip failed: {flipped_v!r}")

    outside_v_mesh = directory / "uv-v-outside.obj"
    write_constant_uv_quad(outside_v_mesh, 0.5, 1.25)
    wrapped_v = {}
    for mode in ("clamp_to_edge", "repeat", "mirrored_repeat"):
        wrapped_v[mode] = render_probe(
            textured_emitter_renderer(
                device=device,
                texture_path=top_bottom,
                mesh_path=outside_v_mesh,
                color_space="linear",
                wrap_v=mode,
            ),
            directory,
            f"wrap-v-{mode}",
        )
    if not (
        wrapped_v["clamp_to_edge"][0] > 0.95
        and wrapped_v["clamp_to_edge"][2] < 0.05
        and wrapped_v["repeat"][2] > 0.95
        and wrapped_v["repeat"][0] < 0.05
        and wrapped_v["mirrored_repeat"][0] > 0.95
        and wrapped_v["mirrored_repeat"][2] < 0.05
    ):
        raise RuntimeError(f"unexpected CUDA V-wrap samples: {wrapped_v!r}")


def check_metallic_roughness(directory: Path, *, device: int) -> None:
    base = directory / "base-color.png"
    write_rgba(base, (1, 1), [(128, 64, 255, 255)])
    textured_base = render_probe(
        pbr_renderer(
            device=device,
            base_color=(0.8, 0.6, 0.4),
            base_color_path=base,
            metallic=0.35,
            roughness=0.4,
        ),
        directory,
        "base-color-textured-factor",
    )
    equivalent_base = render_probe(
        pbr_renderer(
            device=device,
            base_color=(0.8 * 128.0 / 255.0, 0.6 * 64.0 / 255.0, 0.4),
            metallic=0.35,
            roughness=0.4,
        ),
        directory,
        "base-color-equivalent-factor",
    )
    assert_close(
        textured_base,
        equivalent_base,
        "PBR base-color texture and factor multiplication",
    )

    mr = directory / "mr.png"
    mr_red_variant = directory / "mr-red-variant.png"
    # R is deliberately unrelated data. G and B are the glTF roughness and
    # metallic channels and must multiply, rather than replace, their factors.
    write_rgba(mr, (1, 1), [(17, 128, 64, 255)])
    write_rgba(mr_red_variant, (1, 1), [(239, 128, 64, 255)])
    mapped = render_probe(
        pbr_renderer(
            device=device, mr_path=mr, metallic=0.8, roughness=0.6
        ),
        directory,
        "mr-mapped",
    )
    equivalent = render_probe(
        pbr_renderer(
            device=device,
            metallic=0.8 * 64.0 / 255.0,
            roughness=0.6 * 128.0 / 255.0,
        ),
        directory,
        "mr-equivalent-factors",
    )
    ignored_red = render_probe(
        pbr_renderer(
            device=device,
            mr_path=mr_red_variant,
            metallic=0.8,
            roughness=0.6,
        ),
        directory,
        "mr-ignored-red",
    )
    assert_close(mapped, equivalent, "MR G/B routing and factor multiplication")
    assert_close(mapped, ignored_red, "MR R channel must be ignored")

    pbr_metal = render_probe(
        pbr_renderer(device=device, metallic=1.0, roughness=0.32),
        directory,
        "pbr-metal-endpoint",
    )
    legacy_metal = render_probe(
        pbr_renderer(
            device=device,
            metallic=1.0,
            roughness=0.32,
            legacy_metal=True,
        ),
        directory,
        "legacy-metal-endpoint",
    )
    assert_close(pbr_metal, legacy_metal, "PBR metallic=1 legacy endpoint")


def check_normal_mapping(directory: Path, *, device: int) -> None:
    # Bilinear lookup at the center produces exactly (0.5, 0.5, 1), avoiding
    # the unavoidable 8-bit bias of a one-texel neutral normal map.
    flat = directory / "normal-flat-texture.png"
    write_rgba(
        flat,
        (2, 2),
        [
            (127, 127, 255, 255),
            (128, 127, 255, 255),
            (127, 128, 255, 255),
            (128, 128, 255, 255),
        ],
    )
    tilted = directory / "normal-tilted-texture.png"
    write_rgba(tilted, (1, 1), [(185, 128, 241, 255)])
    tilted_y = directory / "normal-tilted-y-texture.png"
    write_rgba(tilted_y, (1, 1), [(128, 185, 241, 255)])

    control = render_probe(
        pbr_renderer(device=device, metallic=1.0, roughness=0.16),
        directory,
        "normal-control",
    )
    flat_result = render_probe(
        pbr_renderer(
            device=device,
            metallic=1.0,
            roughness=0.16,
            normal_path=flat,
        ),
        directory,
        "normal-flat",
    )
    disabled = render_probe(
        pbr_renderer(
            device=device,
            metallic=1.0,
            roughness=0.16,
            normal_path=tilted,
            normal_scale=0.0,
        ),
        directory,
        "normal-scale-zero",
    )
    tilted_result = render_probe(
        pbr_renderer(
            device=device,
            metallic=1.0,
            roughness=0.16,
            normal_path=tilted,
        ),
        directory,
        "normal-tilted",
    )
    mirrored_result = render_probe(
        pbr_renderer(
            device=device,
            mesh_path=MIRRORED_QUAD,
            metallic=1.0,
            roughness=0.16,
            normal_path=tilted,
        ),
        directory,
        "normal-mirrored-chart",
    )
    reversed_normal_result = render_probe(
        pbr_renderer(
            device=device,
            mesh_path=REVERSED_NORMAL_QUAD,
            metallic=1.0,
            roughness=0.16,
            normal_path=tilted,
        ),
        directory,
        "normal-reversed-vertex-normal",
    )
    tilted_y_result = render_probe(
        pbr_renderer(
            device=device,
            metallic=1.0,
            roughness=0.16,
            normal_path=tilted_y,
            light_direction=(0.0, 0.8, 0.6),
        ),
        directory,
        "normal-open-gl-plus-y",
    )
    backlit = render_probe(
        pbr_renderer(
            device=device,
            metallic=1.0,
            roughness=0.16,
            normal_path=tilted,
            light_direction=(0.8, 0.0, -0.6),
        ),
        directory,
        "normal-geometric-back-light",
    )
    assert_close(
        flat_result,
        control,
        "flat normal map",
        relative=0.02,
        absolute=2.0e-6,
    )
    assert_close(disabled, control, "normal_scale=0")
    if luminance(tilted_result) <= 2.0 * max(luminance(control), 1.0e-8):
        raise RuntimeError(
            "tilted normal map did not move the specular lobe toward the light: "
            f"control={control!r}, tilted={tilted_result!r}"
        )
    if luminance(tilted_result) <= 5.0 * max(luminance(mirrored_result), 1.0e-8):
        raise RuntimeError(
            "mirrored UV chart did not reverse the tangent-space X response: "
            f"ordinary={tilted_result!r}, mirrored={mirrored_result!r}"
        )
    reversed_luminance = luminance(reversed_normal_result)
    ordinary_luminance = luminance(tilted_result)
    if not (0.5 * ordinary_luminance < reversed_luminance <
            2.0 * ordinary_luminance):
        raise RuntimeError(
            "reversed OBJ vertex normal reversed the tangent-space X axis: "
            f"ordinary={tilted_result!r}, reversed={reversed_normal_result!r}"
        )
    if luminance(tilted_y_result) <= 2.0 * max(luminance(control), 1.0e-8):
        raise RuntimeError(
            "OpenGL +Y normal map did not move the lobe toward +bitangent: "
            f"control={control!r}, tilted_y={tilted_y_result!r}"
        )
    if max(abs(channel) for channel in backlit) > 1.0e-7:
        raise RuntimeError(
            "normal map changed geometric-side light classification: "
            f"backlit={backlit!r}"
        )

    # The tilted texture decodes to roughly (0.451, 0.004, 0.890). Applying
    # inverse-transpose for scale=(2,1,0.5) gives the same world-space normal
    # as the quantized adjusted texture below on an unscaled instance.
    adjusted = directory / "normal-adjusted.png"
    write_rgba(adjusted, (1, 1), [(144, 128, 254, 255)])
    transformed = render_probe(
        pbr_renderer(
            device=device,
            scale=(2.0, 1.0, 0.5),
            metallic=1.0,
            roughness=0.35,
            normal_path=tilted,
        ),
        directory,
        "normal-nonuniform-scale",
    )
    adjusted_control = render_probe(
        pbr_renderer(
            device=device,
            metallic=1.0,
            roughness=0.35,
            normal_path=adjusted,
        ),
        directory,
        "normal-inverse-transpose-control",
    )
    assert_close(
        transformed,
        adjusted_control,
        "normal-map inverse-transpose instance transform",
        relative=0.08,
        absolute=2.0e-5,
    )


def run_check(directory: Path, *, device: int) -> None:
    check_srgb_filtering_and_wrap(directory, device=device)
    check_metallic_roughness(directory, device=device)
    check_normal_mapping(directory, device=device)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="preserve rendered probes in this directory instead of a temporary one",
    )
    parser.add_argument("--device", type=nonnegative_integer, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output_dir is not None:
        directory = args.output_dir.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        run_check(directory, device=args.device)
    else:
        with tempfile.TemporaryDirectory(
            prefix="spectraldock-pbr-materials-"
        ) as temporary:
            run_check(Path(temporary), device=args.device)
    print("PBR material and tangent-space normal GPU checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
