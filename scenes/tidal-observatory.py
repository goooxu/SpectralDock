#!/usr/bin/env python3
"""Tidal Observatory: a static, feature-dense blue-hour showcase."""

from __future__ import annotations

import argparse
from pathlib import Path

from spectraldock import Renderer


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "output/gallery/showcase"
FORMAL_WIDTH = 2560
FORMAL_HEIGHT = 1440
FORMAL_SPP = 1024
FORMAL_DEPTH = 12
PREVIEW_WIDTH = 640
PREVIEW_HEIGHT = 360
PREVIEW_SPP = 16
PREVIEW_DEPTH = 8
SEED = 909


def _capsule_materials(renderer: Renderer):
    yellow_ceramic = renderer.material(
        name="capsule_yellow_ceramic",
        type="pbr",
        base_color=(0.95, 0.72, 0.08),
        metallic=0.0,
        roughness=0.24,
    )
    visor = renderer.material(
        name="capsule_smoked_visor",
        type="pbr",
        base_color=(0.055, 0.075, 0.11),
        metallic=0.25,
        roughness=0.12,
    )
    eye = renderer.material(
        name="capsule_eye_ceramic",
        type="pbr",
        base_color=(0.96, 0.98, 1.0),
        metallic=0.0,
        roughness=0.16,
    )
    navy_metal = renderer.material(
        name="capsule_navy_metal",
        type="pbr",
        base_color=(0.035, 0.09, 0.21),
        metallic=0.82,
        roughness=0.28,
    )
    brown_rubber = renderer.material(
        name="capsule_brown_rubber",
        type="pbr",
        base_color=(0.16, 0.065, 0.025),
        metallic=0.0,
        roughness=0.74,
    )
    antenna = renderer.material(
        name="capsule_antenna_metal",
        type="pbr",
        base_color=(0.48, 0.52, 0.58),
        metallic=0.9,
        roughness=0.22,
    )
    tip = renderer.material(
        name="capsule_antenna_tip",
        type="pbr",
        base_color=(1.0, 0.72, 0.05),
        metallic=0.18,
        roughness=0.18,
    )
    return {
        "mascot_torso": yellow_ceramic,
        "mascot_arm_left": yellow_ceramic,
        "mascot_arm_right": yellow_ceramic,
        "mascot_leg_left": yellow_ceramic,
        "mascot_leg_right": yellow_ceramic,
        "mascot_visor": visor,
        "mascot_eye_left": eye,
        "mascot_eye_right": eye,
        "mascot_belt_flange": navy_metal,
        "mascot_glove_left": brown_rubber,
        "mascot_glove_right": brown_rubber,
        "mascot_boot_left": brown_rubber,
        "mascot_boot_right": brown_rubber,
        "mascot_antenna_stem": antenna,
        "mascot_antenna_tip": tip,
    }


def _sparky_materials(renderer: Renderer, screen_texture):
    screen = renderer.material(
        name="sparky_screen",
        type="lambertian",
        texture=screen_texture,
        base_color=(1.0, 1.0, 1.0),
    )
    return {
        "AccentOrange": renderer.material(
            name="sparky_accent_orange",
            type="pbr",
            base_color=(0.95, 0.30, 0.045),
            metallic=0.0,
            roughness=0.28,
        ),
        "EmitYellow": renderer.material(
            name="sparky_signal_yellow",
            type="pbr",
            base_color=(1.0, 0.78, 0.08),
            metallic=0.0,
            roughness=0.20,
        ),
        # Keep this water scene free of additional dielectric boundaries: the
        # glossy PBR shell preserves the intended transparent-head styling
        # without claiming nested medium transport.
        "GlassHead": renderer.material(
            name="sparky_glossy_head_shell",
            type="pbr",
            base_color=(0.28, 0.57, 0.82),
            metallic=0.05,
            roughness=0.08,
        ),
        "MetalGrey": renderer.material(
            name="sparky_metal_grey",
            type="pbr",
            base_color=(0.36, 0.40, 0.46),
            metallic=0.88,
            roughness=0.30,
        ),
        "PlasticBlue": renderer.material(
            name="sparky_plastic_blue",
            type="pbr",
            base_color=(0.12, 0.43, 0.72),
            metallic=0.0,
            roughness=0.34,
        ),
        "PlasticWhite": renderer.material(
            name="sparky_plastic_white",
            type="pbr",
            base_color=(0.86, 0.90, 0.94),
            metallic=0.0,
            roughness=0.31,
        ),
        "ScreenChest": screen,
        "ScreenFace": screen,
        "ScreenPalm": screen,
        "TreadOrange": renderer.material(
            name="sparky_tread_orange",
            type="pbr",
            base_color=(0.82, 0.19, 0.025),
            metallic=0.0,
            roughness=0.64,
        ),
    }


def create_renderer(device: int = 0) -> Renderer:
    """Build the immutable, non-PhysX Tidal Observatory scene."""
    renderer = Renderer(device=device, scene_name="tidal-observatory")
    renderer.integrator(
        direct_light_sampling="importance",
        clamp_direct=64.0,
        clamp_indirect=16.0,
    )
    renderer.camera(
        look_from=(10.8, 5.9, 15.4),
        look_at=(0.0, 1.25, -0.65),
        up=(0.0, 1.0, 0.0),
        vfov=34.0,
        aperture=0.025,
        focus_distance=19.9,
    )
    renderer.background(
        type="environment",
        path=ROOT / "assets/examples/environments/radiance-pavilion.hdr",
        intensity=0.72,
        rotation_degrees=205.0,
        exposure=-0.25,
    )

    spot_albedo = renderer.texture(
        name="spot_srgb_albedo",
        type="image",
        path=ROOT / "assets/examples/models/spot/spot_texture.avif",
        color_space="srgb",
        wrap_u="repeat",
        wrap_v="repeat",
    )
    sparky_screen = renderer.texture(
        name="sparky_srgb_screen_atlas",
        type="image",
        path=ROOT / "assets/examples/models/sparky/sparky_albedo.avif",
        color_space="srgb",
    )
    panel_normal = renderer.texture(
        name="showcase_panel_linear_normal",
        type="image",
        path=(
            ROOT
            / "assets/examples/models/showcase-panel/showcase-panel-normal.avif"
        ),
        color_space="linear",
        wrap_u="repeat",
        wrap_v="repeat",
    )
    panel_metallic_roughness = renderer.texture(
        name="showcase_panel_linear_metallic_roughness",
        type="image",
        path=(
            ROOT
            / "assets/examples/models/showcase-panel/"
            "showcase-panel-metallic-roughness.avif"
        ),
        color_space="linear",
        wrap_u="repeat",
        wrap_v="repeat",
    )

    deck = renderer.material(
        name="salt_darkened_deck",
        type="pbr",
        base_color=(0.105, 0.125, 0.145),
        metallic=0.10,
        roughness=0.58,
    )
    terrace = renderer.material(
        name="observatory_terrace",
        type="pbr",
        base_color=(0.20, 0.235, 0.26),
        metallic=0.22,
        roughness=0.43,
    )
    dark_frame = renderer.material(
        name="dark_instrument_frame",
        type="pbr",
        base_color=(0.045, 0.060, 0.075),
        metallic=0.86,
        roughness=0.30,
    )
    rough_copper = renderer.material(
        name="weathered_copper",
        type="pbr",
        base_color=(0.62, 0.25, 0.075),
        metallic=1.0,
        roughness=0.40,
    )
    chrome = renderer.material(
        name="polished_chrome",
        type="metal",
        base_color=(0.92, 0.95, 0.98),
        roughness=0.035,
    )
    glazed_ceramic = renderer.material(
        name="glazed_ceramic",
        type="pbr",
        base_color=(0.80, 0.86, 0.88),
        metallic=0.0,
        roughness=0.20,
    )
    optical_shell = renderer.material(
        name="glossy_optical_shell",
        type="pbr",
        base_color=(0.18, 0.46, 0.68),
        metallic=0.22,
        roughness=0.06,
    )
    panel_material = renderer.material(
        name="calibration_panel_pbr",
        type="pbr",
        base_color=(0.34, 0.47, 0.58),
        metallic=0.78,
        roughness=0.36,
        metallic_roughness_texture=panel_metallic_roughness,
        normal_texture=panel_normal,
        normal_scale=1.0,
    )
    spot_coat = renderer.material(
        name="spot_textured_coat",
        type="pbr",
        base_color_texture=spot_albedo,
        base_color=(1.0, 1.0, 1.0),
        metallic=0.0,
        roughness=0.54,
    )
    tidal_water = renderer.material(
        name="tidal_water",
        type="water",
        roughness=0.105,
        ior=1.333,
        absorption=(0.45, 0.09, 0.025),
    )
    pool_floor = renderer.material(
        name="submerged_basalt",
        type="lambertian",
        base_color=(0.045, 0.10, 0.12),
    )
    warm_emitter = renderer.material(
        name="warm_beacon_emitter",
        type="emitter",
        emission=(18.0, 5.2, 1.25),
    )
    cool_emitter = renderer.material(
        name="cool_orb_emitter",
        type="emitter",
        emission=(2.2, 7.5, 13.0),
    )

    capsule = renderer.mesh(
        name="capsule_mascot_mesh",
        path=(
            ROOT
            / "assets/examples/models/capsule-mascot/capsule-mascot.obj"
        ),
        materials=_capsule_materials(renderer),
    )
    sparky = renderer.mesh(
        name="sparky_mesh",
        path=ROOT / "assets/examples/models/sparky/sparky.obj",
        materials=_sparky_materials(renderer, sparky_screen),
    )
    spot = renderer.mesh(
        name="spot_mesh",
        path=ROOT / "assets/examples/models/spot/spot_triangulated.obj",
    )
    showcase_panel = renderer.mesh(
        name="showcase_panel_mesh",
        path=(
            ROOT / "assets/examples/models/showcase-panel/showcase-panel.obj"
        ),
    )

    def rectangle(name, p1, p2, p3, material):
        return renderer.object(
            name=name,
            type="rectangle",
            p1=p1,
            p2=p2,
            p3=p3,
            material=material,
        )

    def cylinder(name, base, axis, height, radius, material):
        return renderer.object(
            name=name,
            type="cylinder",
            base=base,
            axis=axis,
            height=height,
            radius=radius,
            material=material,
        )

    def disk(name, center, normal, radius, material):
        return renderer.object(
            name=name,
            type="disk",
            center=center,
            normal=normal,
            radius=radius,
            material=material,
        )

    # Coastal platform and the recessed tidal channel in the foreground.
    rectangle(
        "main_deck",
        (-11.0, 0.0, 1.8),
        (-11.0, 0.0, -8.0),
        (11.0, 0.0, -8.0),
        deck,
    )
    rectangle(
        "submerged_channel_floor",
        (-6.0, -1.45, 9.4),
        (-6.0, -1.45, 1.8),
        (6.0, -1.45, 1.8),
        pool_floor,
    )
    rectangle(
        "left_channel_promenade",
        (-11.0, 0.0, 10.5),
        (-11.0, 0.0, 1.8),
        (-6.0, 0.0, 1.8),
        deck,
    )
    rectangle(
        "right_channel_promenade",
        (6.0, 0.0, 1.8),
        (6.0, 0.0, 10.5),
        (11.0, 0.0, 10.5),
        deck,
    )
    rectangle(
        "channel_back_wall",
        (-6.0, -1.45, 1.8),
        (-6.0, 0.0, 1.8),
        (6.0, 0.0, 1.8),
        terrace,
    )
    rectangle(
        "channel_front_wall",
        (6.0, -1.45, 9.4),
        (6.0, 0.0, 9.4),
        (-6.0, 0.0, 9.4),
        terrace,
    )
    for name, x in (("channel_left_wall", -6.0), ("channel_right_wall", 6.0)):
        if x < 0.0:
            points = ((x, -1.45, 9.4), (x, 0.0, 9.4), (x, 0.0, 1.8))
        else:
            points = ((x, -1.45, 1.8), (x, 0.0, 1.8), (x, 0.0, 9.4))
        rectangle(name, *points, terrace)
    renderer.object(
        name="tidal_channel",
        type="water_surface",
        center=(0.0, -0.36, 5.6),
        size=(12.0, 7.6),
        material=tidal_water,
        waves=(
            {
                "direction": (1.0, 0.18),
                "amplitude": 0.070,
                "wavelength": 2.80,
                "phase_radians": 0.30,
            },
            {
                "direction": (-0.30, 1.0),
                "amplitude": 0.044,
                "wavelength": 1.70,
                "phase_radians": 1.85,
            },
            {
                "direction": (0.65, 1.0),
                "amplitude": 0.024,
                "wavelength": 1.05,
                "phase_radians": 3.40,
            },
            {
                "direction": (-1.0, 0.10),
                "amplitude": 0.010,
                "wavelength": 0.72,
                "phase_radians": 5.10,
            },
        ),
    )
    for name, center, radius, material in (
        ("submerged_ceramic_marker", (-2.6, -0.95, 4.2), 0.42, glazed_ceramic),
        ("submerged_copper_marker", (0.1, -1.02, 5.3), 0.48, rough_copper),
        ("submerged_chrome_marker", (2.8, -0.90, 3.8), 0.38, chrome),
    ):
        renderer.object(
            name=name,
            type="sphere",
            center=center,
            radius=radius,
            material=material,
        )

    # A raised central inspection dais gives Spot the visual hierarchy.
    cylinder(
        "central_dais",
        (0.0, 0.0, -0.65),
        (0.0, 1.0, 0.0),
        0.48,
        2.65,
        dark_frame,
    )
    disk("central_dais_cap", (0.0, 0.48, -0.65), (0.0, 1.0, 0.0), 2.65, terrace)
    cylinder(
        "spot_plinth",
        (0.0, 0.48, -0.55),
        (0.0, 1.0, 0.0),
        0.34,
        1.32,
        rough_copper,
    )
    disk("spot_plinth_cap", (0.0, 0.82, -0.55), (0.0, 1.0, 0.0), 1.32, chrome)
    renderer.object(
        name="spot_centerpiece",
        type="mesh",
        mesh=spot,
        translate=(0.0, 1.92, -0.58),
        rotate_degrees=(0.0, 16.0, 0.0),
        scale=(1.50, 1.50, 1.50),
        material=spot_coat,
    )

    # Capsule Mascot calibrates two instances of the same textured panel mesh.
    cylinder(
        "capsule_station",
        (-3.65, 0.0, -0.20),
        (0.0, 1.0, 0.0),
        0.42,
        1.30,
        dark_frame,
    )
    disk("capsule_station_cap", (-3.65, 0.42, -0.20), (0.0, 1.0, 0.0), 1.30, terrace)
    renderer.object(
        name="capsule_calibrator",
        type="mesh",
        mesh=capsule,
        translate=(-3.65, 0.43, -0.20),
        rotate_degrees=(0.0, -18.0, 0.0),
        scale=(0.78, 0.78, 0.78),
    )
    cylinder(
        "panel_bench",
        (-5.72, 0.0, -1.45),
        (0.0, 1.0, 0.0),
        0.86,
        0.82,
        dark_frame,
    )
    disk("panel_bench_cap", (-5.72, 0.86, -1.45), (0.0, 1.0, 0.0), 0.82, chrome)
    renderer.object(
        name="panel_reference_instance",
        type="mesh",
        mesh=showcase_panel,
        translate=(-5.72, 1.72, -1.40),
        rotate_degrees=(-8.0, 16.0, 0.0),
        scale=(0.62, 0.62, 0.62),
        material=panel_material,
    )
    renderer.object(
        name="panel_secondary_instance",
        type="mesh",
        mesh=showcase_panel,
        translate=(-4.92, 1.31, -2.28),
        rotate_degrees=(6.0, -22.0, 0.0),
        scale=(0.44, 0.44, 0.44),
        material=panel_material,
    )

    # Sparky operates a compact two-lens optical instrument on the right.
    cylinder(
        "sparky_station",
        (3.55, 0.0, -0.20),
        (0.0, 1.0, 0.0),
        0.42,
        1.30,
        dark_frame,
    )
    disk("sparky_station_cap", (3.55, 0.42, -0.20), (0.0, 1.0, 0.0), 1.30, terrace)
    renderer.object(
        name="sparky_operator",
        type="mesh",
        mesh=sparky,
        translate=(3.55, 0.425, -0.20),
        rotate_degrees=(0.0, 18.0, 0.0),
        scale=(0.75, 0.75, 0.75),
    )
    for name, base, axis, height, radius, material in (
        ("optics_tripod_left", (4.62, 0.03, -2.12), (0.24, 0.97, 0.02), 1.42, 0.045, dark_frame),
        ("optics_tripod_right", (5.64, 0.03, -2.12), (-0.24, 0.97, 0.02), 1.42, 0.045, dark_frame),
        ("optics_tripod_rear", (5.12, 0.03, -2.85), (0.0, 0.91, 0.42), 1.45, 0.045, dark_frame),
        ("optics_column", (5.12, 1.33, -2.20), (0.0, 1.0, 0.0), 0.64, 0.085, rough_copper),
        ("optics_left_barrel", (4.54, 1.93, -2.40), (0.12, 0.02, 0.99), 0.76, 0.31, dark_frame),
        ("optics_right_barrel", (5.28, 1.93, -2.49), (0.12, 0.02, 0.99), 0.76, 0.31, dark_frame),
    ):
        cylinder(name, base, axis, height, radius, material)
    for name, center in (
        ("optics_left_glass", (4.63, 1.945, -1.65)),
        ("optics_right_glass", (5.37, 1.945, -1.74)),
    ):
        renderer.object(
            name=name,
            type="sphere",
            center=center,
            radius=0.255,
            material=optical_shell,
        )

    # A parabolic observing mirror and a warm volumetric beacon anchor the rear.
    cylinder(
        "reflector_pier",
        (-4.30, 0.0, -5.05),
        (0.0, 1.0, 0.0),
        1.05,
        0.58,
        dark_frame,
    )
    renderer.object(
        name="observatory_reflector",
        type="parabola",
        origin=(-4.30, 1.08, -5.05),
        normal=(0.0, 1.0, 0.0),
        focus=(-3.56, 1.08, -5.05),
        clip_min=(-4.62, 0.95, -6.60),
        clip_max=(-2.05, 4.02, -3.50),
        front_material=None,
        back_material=chrome,
    )
    cylinder(
        "beacon_base",
        (6.65, 0.0, -4.75),
        (0.0, 1.0, 0.0),
        1.16,
        0.58,
        rough_copper,
    )
    disk("beacon_bowl", (6.65, 1.16, -4.75), (0.0, 1.0, 0.0), 0.70, chrome)
    renderer.light(
        name="procedural_beacon_flame",
        type="flame",
        position=(6.65, 1.27, -4.75),
        axis=(-0.04, 1.0, 0.03),
        height=2.15,
        radius_start=0.47,
        radius_end=0.13,
        emission_start=(12.0, 2.8, 0.35),
        emission_end=(2.3, 0.32, 0.06),
        extinction=0.92,
        density_scale=1.05,
        turbulence=0.47,
        noise_scale=2.25,
        seed=909,
    )

    # Visible finite emitters supplement the blue-hour HDR environment.
    ceiling_light = renderer.object(
        name="overhead_rectangle_emitter",
        type="rectangle",
        p1=(-3.0, 5.65, 0.35),
        p2=(2.8, 5.65, 0.35),
        p3=(2.8, 5.65, -1.25),
        front_material=warm_emitter,
    )
    renderer.light(
        name="overhead_rectangle_key",
        type="rectangle",
        object=ceiling_light,
        position=(-3.0, 5.65, 0.35),
        edge_u=(0.0, 0.0, -1.60),
        edge_v=(5.80, 0.0, 0.0),
        emission=(18.0, 5.2, 1.25),
    )
    cool_orb = renderer.object(
        name="cool_sphere_emitter",
        type="sphere",
        center=(5.85, 3.25, -3.65),
        radius=0.24,
        material=cool_emitter,
    )
    renderer.light(
        name="cool_sphere_fill",
        type="sphere",
        object=cool_orb,
        position=(5.85, 3.25, -3.65),
        radius=0.24,
        emission=(2.2, 7.5, 13.0),
    )
    return renderer


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", type=int, default=0, help="CUDA device index")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="directory for the HDR AVIF and temporary stats JSON",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="render a fast 640x360 composition preview",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "tidal-observatory.avif"
    if args.preview:
        width, height, spp, depth = (
            PREVIEW_WIDTH,
            PREVIEW_HEIGHT,
            PREVIEW_SPP,
            PREVIEW_DEPTH,
        )
    else:
        width, height, spp, depth = (
            FORMAL_WIDTH,
            FORMAL_HEIGHT,
            FORMAL_SPP,
            FORMAL_DEPTH,
        )
    create_renderer(device=args.device).render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=width,
        height=height,
        spp=spp,
        depth=depth,
        seed=SEED,
        denoise=True,
        clamp_direct=64.0,
        clamp_indirect=16.0,
    )


if __name__ == "__main__":
    main()
