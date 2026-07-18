#!/usr/bin/env python3
"""GPU contracts for adversarial mesh shading normals."""

import argparse
import math
import sys
import tempfile
from pathlib import Path

from spectraldock import Renderer

from avif_test_utils import assert_avif_dimensions, captured_linear_rgb


ROOT = Path(__file__).resolve().parents[1]
EXTREME_MESH = ROOT / "tests/assets/extreme-shading-normal-quad.obj"
GEOMETRIC_MESH = ROOT / "tests/assets/geometric-shading-normal-quad.obj"
WIDTH = 48
HEIGHT = 48
SPP = 8
GLASS_SPP = 32
SEED = 1701

# The quad has Ng=(0,0,1) and Ns approximately=(0.995,0,0.1). The camera makes
# wo approximately equal to Ns, so no view-frame correction hides either light
# classification. FRONT_LIGHT is above Ng but below Ns; BACK_LIGHT is below Ng
# but above Ns.
CAMERA = (4.974937, 0.0, 0.5)
WRONG_VIEW_CAMERA = (-4.974937, 0.0, 0.5)
HALF_BACK_CAMERA = (0.0, 0.0, 5.0)
FRONT_LIGHT = (-0.8, 0.0, 0.6)
BACK_LIGHT = (0.8, 0.0, -0.6)


def nonnegative_integer(value: str) -> int:
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return result


def common_renderer(*, device: int, camera=CAMERA) -> Renderer:
    renderer = Renderer(device=device)
    renderer.integrator(
        direct_light_sampling="importance", clamp_direct=0.0, clamp_indirect=0.0
    )
    renderer.camera(
        look_from=camera,
        look_at=(0.0, 0.0, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=2.0,
        aperture=0.0,
        focus_distance=5.0,
    )
    return renderer


def direct_renderer(
    *, material_type: str, light_direction, device: int, camera=CAMERA
) -> Renderer:
    renderer = common_renderer(device=device, camera=camera)
    renderer.background(type="constant", color=(0.0, 0.0, 0.0), exposure=0.0)
    if material_type == "lambertian":
        material = renderer.material(
            name="receiver", type="lambertian", base_color=(0.8, 0.7, 0.6)
        )
    elif material_type == "metal":
        material = renderer.material(
            name="receiver",
            type="metal",
            base_color=(0.9, 0.75, 0.55),
            roughness=0.55,
        )
    elif material_type == "pbr":
        material = renderer.material(
            name="receiver",
            type="pbr",
            base_color=(0.9, 0.75, 0.55),
            metallic=0.65,
            roughness=0.55,
        )
    else:
        raise RuntimeError(f"unsupported direct-light material: {material_type}")
    mesh = renderer.mesh(name="adversarial-quad", path=EXTREME_MESH)
    renderer.object(
        name="receiver", type="mesh", mesh=mesh, material=material
    )
    renderer.light(
        name="probe",
        type="directional",
        direction=light_direction,
        irradiance=(64.0 * math.pi, 64.0 * math.pi, 64.0 * math.pi),
    )
    return renderer


def finite_light_renderer(*, device: int, material_type="lambertian") -> Renderer:
    renderer = common_renderer(device=device)
    renderer.background(type="constant", color=(0.0, 0.0, 0.0), exposure=0.0)
    if material_type == "lambertian":
        receiver = renderer.material(
            name="receiver", type="lambertian", base_color=(0.8, 0.7, 0.6)
        )
    elif material_type == "pbr":
        receiver = renderer.material(
            name="receiver",
            type="pbr",
            base_color=(0.8, 0.7, 0.6),
            metallic=0.65,
            roughness=0.55,
        )
    else:
        raise RuntimeError(f"unsupported finite-light material: {material_type}")
    emitter = renderer.material(
        name="probe-emitter", type="emitter", emission=(64.0, 64.0, 64.0)
    )
    mesh = renderer.mesh(name="adversarial-quad", path=EXTREME_MESH)
    renderer.object(name="receiver", type="mesh", mesh=mesh, material=receiver)

    # The disk occupies the same Ng-front/Ns-back directional region as
    # FRONT_LIGHT. Binding it to an emitter makes the light and BSDF techniques
    # compete, even though this direction is outside the BSDF sampler support.
    center = (-4.0, 0.0, 3.0)
    normal = (0.8, 0.0, -0.6)
    disk = renderer.object(
        name="finite-probe",
        type="disk",
        center=center,
        normal=normal,
        radius=0.2,
        front_material=emitter,
    )
    renderer.light(
        name="finite-probe",
        type="disk",
        object=disk,
        position=center,
        normal=normal,
        radius=0.2,
        emission=(64.0, 64.0, 64.0),
    )
    return renderer


def glass_renderer(*, mesh_path: Path, device: int) -> Renderer:
    renderer = common_renderer(device=device)
    renderer.background(
        type="sky",
        bottom=(0.015, 0.08, 0.7),
        top=(1.3, 0.12, 0.02),
        sun_direction=(0.0, 1.0, 0.0),
        sun_color=(3.0, 1.0, 0.2),
        sun_cos_angle=0.985,
        exposure=0.0,
    )
    glass = renderer.material(
        name="smooth-glass",
        type="dielectric",
        base_color=(0.98, 0.99, 1.0),
        roughness=0.0,
        ior=1.5,
    )
    mesh = renderer.mesh(name="glass-quad", path=mesh_path)
    renderer.object(name="glass", type="mesh", mesh=mesh, material=glass)
    return renderer


def sampled_pbr_renderer(*, mesh_path: Path, metallic: float, device: int) -> Renderer:
    """PBR probe whose only energy arrives after one sampled BSDF event."""
    renderer = common_renderer(device=device)
    renderer.background(
        type="constant", color=(0.7, 0.5, 0.3), exposure=0.0
    )
    material = renderer.material(
        name="sampled-pbr",
        type="pbr",
        base_color=(0.82, 0.47, 0.18),
        metallic=metallic,
        roughness=0.48,
    )
    mesh = renderer.mesh(name="sampled-pbr-quad", path=mesh_path)
    renderer.object(name="sampled-pbr", type="mesh", mesh=mesh, material=material)
    return renderer


def render_linear(
    renderer: Renderer,
    directory: Path,
    name: str,
    *,
    spp: int = SPP,
    depth: int = 1,
) -> tuple[tuple[tuple[float, float, float], ...], bytes]:
    avif = directory / f"{name}.avif"
    stats = renderer.render(
        output=avif,
        stats_output=avif.with_suffix(".stats.json"),
        width=WIDTH,
        height=HEIGHT,
        spp=spp,
        depth=depth,
        seed=SEED,
        denoise=False,
        clamp_direct=0.0,
        clamp_indirect=0.0,
        _test_capture_linear=True,
    )
    assert_avif_dimensions(avif, WIDTH, HEIGHT)
    pixels, linear_values = captured_linear_rgb(stats, WIDTH, HEIGHT)
    render_stats = stats["render"]
    if (
        render_stats["denoised"] is not False
        or render_stats["clamp_direct"] != 0.0
        or render_stats["clamp_indirect"] != 0.0
    ):
        raise RuntimeError(f"{name}: linear shading-normal check used biased output")
    geometry = stats["geometry"]
    if geometry["unique_meshes"] != 1 or geometry["mesh_triangles"] != 2:
        raise RuntimeError(f"{name}: adversarial double-triangle mesh was not rendered")
    return pixels, linear_values


def luminance(pixel: tuple[float, float, float]) -> float:
    return 0.2126 * pixel[0] + 0.7152 * pixel[1] + 0.0722 * pixel[2]


def interior_luminances(pixels):
    margin = 5
    return [
        luminance(pixels[y * WIDTH + x])
        for y in range(margin, HEIGHT - margin)
        for x in range(margin, WIDTH - margin)
    ]


def assert_front_response(pixels, label: str) -> None:
    values = interior_luminances(pixels)
    mean = sum(values) / len(values)
    if not mean > 1.0e-7:
        raise RuntimeError(
            f"{label}: geometrically front-facing light produced a black surface"
        )
    minimum = min(values)
    if minimum <= max(1.0e-10, mean * 1.0e-5):
        raise RuntimeError(
            f"{label}: dark or invalid double-triangle seam "
            f"(minimum={minimum:.8g}, mean={mean:.8g})"
        )

    # The fixture has constant material and vertex normals. A shared-edge bug
    # therefore appears as a near-black step, while legitimate perspective
    # variation remains smooth across neighboring pixels.
    maximum_contrast = 0.0
    margin = 5
    for y in range(margin, HEIGHT - margin):
        for x in range(margin, WIDTH - margin):
            current = luminance(pixels[y * WIDTH + x])
            if x + 1 < WIDTH - margin:
                adjacent = luminance(pixels[y * WIDTH + x + 1])
                maximum_contrast = max(
                    maximum_contrast,
                    abs(current - adjacent) / max(current, adjacent, mean * 1.0e-8),
                )
            if y + 1 < HEIGHT - margin:
                adjacent = luminance(pixels[(y + 1) * WIDTH + x])
                maximum_contrast = max(
                    maximum_contrast,
                    abs(current - adjacent) / max(current, adjacent, mean * 1.0e-8),
                )
    if maximum_contrast >= 0.995:
        raise RuntimeError(
            f"{label}: near-black mesh seam or discontinuity "
            f"(neighbor contrast={maximum_contrast:.6f})"
        )


def assert_back_rejected(pixels, label: str) -> None:
    maximum = max(abs(channel) for pixel in pixels for channel in pixel)
    if maximum > 1.0e-7:
        raise RuntimeError(
            f"{label}: geometrically back-facing light leaked through "
            f"(maximum={maximum:.8g})"
        )


def mean_interior_luminance(pixels) -> float:
    values = interior_luminances(pixels)
    return sum(values) / len(values)


def run_check(directory: Path, *, device: int) -> None:
    lambert_front, lambert_bytes = render_linear(
        direct_renderer(
            material_type="lambertian", light_direction=FRONT_LIGHT, device=device
        ),
        directory,
        "lambert-front",
    )
    assert_front_response(lambert_front, "Lambert")
    lambert_repeat, repeat_bytes = render_linear(
        direct_renderer(
            material_type="lambertian", light_direction=FRONT_LIGHT, device=device
        ),
        directory,
        "lambert-front-repeat",
    )
    if lambert_front != lambert_repeat or lambert_bytes != repeat_bytes:
        raise RuntimeError("fixed-seed linear shading-normal output is not deterministic")

    metal_front, _ = render_linear(
        direct_renderer(
            material_type="metal", light_direction=FRONT_LIGHT, device=device
        ),
        directory,
        "metal-front",
    )
    assert_front_response(metal_front, "rough metal")

    # With this view, h=normalize(wo+wi) lies behind Ns even though wo and the
    # physical reflection both remain above Ng. Metal evaluation must use the
    # absolute shading half-vector cosine without flipping h away from wo.
    metal_half_back, _ = render_linear(
        direct_renderer(
            material_type="metal",
            light_direction=FRONT_LIGHT,
            device=device,
            camera=HALF_BACK_CAMERA,
        ),
        directory,
        "metal-half-vector-back",
    )
    assert_front_response(metal_half_back, "rough metal back half-vector")

    pbr_front, _ = render_linear(
        direct_renderer(
            material_type="pbr", light_direction=FRONT_LIGHT, device=device
        ),
        directory,
        "pbr-front",
    )
    assert_front_response(pbr_front, "mixed PBR")

    pbr_half_back, _ = render_linear(
        direct_renderer(
            material_type="pbr",
            light_direction=FRONT_LIGHT,
            device=device,
            camera=HALF_BACK_CAMERA,
        ),
        directory,
        "pbr-half-vector-back",
    )
    assert_front_response(pbr_half_back, "mixed PBR back half-vector")

    finite_front, _ = render_linear(
        finite_light_renderer(device=device),
        directory,
        "lambert-finite-front",
        depth=2,
    )
    assert_front_response(finite_front, "Lambert finite-light zero-PDF MIS")

    pbr_finite_front, _ = render_linear(
        finite_light_renderer(device=device, material_type="pbr"),
        directory,
        "pbr-finite-front",
        depth=2,
    )
    assert_front_response(pbr_finite_front, "PBR finite-light zero-PDF MIS")

    # Force both endpoints of the PBR lobe mixture through sample_bsdf.  The
    # constant environment contributes only after the secondary ray; replacing
    # the extreme vertex normal with Ng must therefore change the sampled
    # transport for both the diffuse-heavy and pure-specular endpoints.
    for metallic, label in ((0.0, "dielectric"), (1.0, "metallic")):
        sampled_extreme, _ = render_linear(
            sampled_pbr_renderer(
                mesh_path=EXTREME_MESH, metallic=metallic, device=device
            ),
            directory,
            f"pbr-sampled-{label}-extreme",
            spp=32,
            depth=2,
        )
        sampled_geometric, _ = render_linear(
            sampled_pbr_renderer(
                mesh_path=GEOMETRIC_MESH, metallic=metallic, device=device
            ),
            directory,
            f"pbr-sampled-{label}-geometric",
            spp=32,
            depth=2,
        )
        extreme_mean = mean_interior_luminance(sampled_extreme)
        geometric_mean = mean_interior_luminance(sampled_geometric)
        if min(extreme_mean, geometric_mean) <= 1.0e-5:
            raise RuntimeError(
                f"sampled PBR {label} endpoint rendered black: "
                f"extreme={extreme_mean:.8g}, geometric={geometric_mean:.8g}"
            )
        relative_difference = abs(extreme_mean - geometric_mean) / max(
            extreme_mean, geometric_mean
        )
        if relative_difference <= 0.05:
            raise RuntimeError(
                f"sampled PBR {label} endpoint ignored the shading frame: "
                f"extreme={extreme_mean:.8g}, geometric={geometric_mean:.8g}"
            )

    # Raw Ns points away from this camera even though Ng remains front-facing.
    # The corrected shading frame must stay finite and retain the front-light
    # response instead of producing a black silhouette or shared-edge seam.
    wrong_view, _ = render_linear(
        direct_renderer(
            material_type="lambertian",
            light_direction=FRONT_LIGHT,
            device=device,
            camera=WRONG_VIEW_CAMERA,
        ),
        directory,
        "lambert-wrong-view",
    )
    assert_front_response(wrong_view, "Lambert wrong-view correction")

    for material_type in ("lambertian", "metal", "pbr"):
        back, _ = render_linear(
            direct_renderer(
                material_type=material_type,
                light_direction=BACK_LIGHT,
                device=device,
            ),
            directory,
            f"{material_type}-back",
        )
        assert_back_rejected(back, material_type)

    extreme_glass, extreme_bytes = render_linear(
        glass_renderer(mesh_path=EXTREME_MESH, device=device),
        directory,
        "glass-extreme",
        spp=GLASS_SPP,
        depth=2,
    )
    geometric_glass, geometric_bytes = render_linear(
        glass_renderer(mesh_path=GEOMETRIC_MESH, device=device),
        directory,
        "glass-geometric",
        spp=GLASS_SPP,
        depth=2,
    )
    if not any(luminance(pixel) > 0.0 for pixel in geometric_glass):
        raise RuntimeError("smooth-dielectric control rendered black")
    if extreme_glass != geometric_glass or extreme_bytes != geometric_bytes:
        raise RuntimeError(
            "smooth dielectric output changed when only vertex normals changed"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="preserve rendered checks in this directory instead of a temporary one",
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
            prefix="spectraldock-shading-normals-"
        ) as temporary:
            run_check(Path(temporary), device=args.device)
    print("adversarial shading-normal GPU checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
