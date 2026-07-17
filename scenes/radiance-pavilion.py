#!/usr/bin/env python3
"""Radiance Pavilion: HDR environment importance-sampling showcase."""

from pathlib import Path

from spectraldock import Renderer


ROOT = Path(__file__).resolve().parents[1]


def create_renderer() -> Renderer:
    renderer = Renderer()
    renderer.integrator(
        direct_light_sampling="importance",
        clamp_direct=64.0,
        clamp_indirect=16.0,
    )
    renderer.camera(
        look_from=(10.5, 4.7, 14.5),
        look_at=(0.0, 1.55, -1.25),
        up=(0.0, 1.0, 0.0),
        vfov=35.0,
        aperture=0.035,
        focus_distance=19.2,
    )
    renderer.background(
        type="environment",
        path=ROOT / "assets/examples/environments/radiance-pavilion.hdr",
        intensity=1.0,
        rotation_degrees=22.0,
        exposure=0.0,
    )

    sparky_screen_texture = renderer.texture(
        name="sparky_screen_texture",
        type="image",
        path=ROOT / "assets/examples/models/sparky/sparky_albedo.png",
        color_space="srgb",
    )
    pavilion_floor = renderer.material(
        name="pavilion_floor", type="lambertian", base_color=(0.11, 0.12, 0.14)
    )
    stage = renderer.material(
        name="stage", type="lambertian", base_color=(0.30, 0.31, 0.33)
    )
    pedestal = renderer.material(
        name="pedestal", type="metal", base_color=(0.18, 0.20, 0.24), roughness=0.24
    )
    mascot_porcelain = renderer.material(
        name="mascot_porcelain", type="lambertian", base_color=(0.74, 0.79, 0.86)
    )
    terracotta = renderer.material(
        name="terracotta", type="lambertian", base_color=(0.68, 0.16, 0.055)
    )
    rough_bronze = renderer.material(
        name="rough_bronze", type="metal", base_color=(0.70, 0.35, 0.10), roughness=0.42
    )
    smooth_chrome = renderer.material(
        name="smooth_chrome", type="metal", base_color=(0.91, 0.94, 0.98), roughness=0.025
    )
    optical_glass = renderer.material(
        name="optical_glass", type="dielectric", base_color=(0.96, 0.99, 1.0), ior=1.5
    )
    instrument_frame = renderer.material(
        name="instrument_frame",
        type="metal",
        base_color=(0.13, 0.15, 0.17),
        roughness=0.30,
    )
    sparky_plastic_blue = renderer.material(
        name="sparky_plastic_blue",
        type="lambertian",
        base_color=(0.35, 0.65, 0.90),
    )
    sparky_screen = renderer.material(
        name="sparky_screen",
        type="lambertian",
        texture=sparky_screen_texture,
        base_color=(1.0, 1.0, 1.0),
    )
    sparky_glass_head = renderer.material(
        name="sparky_glass_head",
        type="dielectric",
        base_color=(0.55, 0.75, 0.95),
        ior=1.5,
        roughness=0.06,
    )
    sparky_plastic_white = renderer.material(
        name="sparky_plastic_white",
        type="lambertian",
        base_color=(0.92, 0.93, 0.95),
    )
    sparky_metal_grey = renderer.material(
        name="sparky_metal_grey",
        type="metal",
        base_color=(0.45, 0.47, 0.50),
        roughness=0.28,
    )
    sparky_accent_orange = renderer.material(
        name="sparky_accent_orange",
        type="lambertian",
        base_color=(0.95, 0.45, 0.12),
    )
    sparky_tread_orange = renderer.material(
        name="sparky_tread_orange",
        type="lambertian",
        base_color=(0.95, 0.40, 0.08),
    )
    sparky_emit_yellow = renderer.material(
        name="sparky_emit_yellow",
        type="lambertian",
        base_color=(1.0, 0.85, 0.20),
    )
    mascot = renderer.mesh(
        name="mascot",
        path=ROOT / "assets/examples/models/capsule-mascot/capsule-mascot.obj",
    )
    sparky = renderer.mesh(
        name="sparky",
        path=ROOT / "assets/examples/models/sparky/sparky.obj",
        materials={
            "AccentOrange": sparky_accent_orange,
            "EmitYellow": sparky_emit_yellow,
            "GlassHead": sparky_glass_head,
            "MetalGrey": sparky_metal_grey,
            "PlasticBlue": sparky_plastic_blue,
            "PlasticWhite": sparky_plastic_white,
            "ScreenChest": sparky_screen,
            "ScreenFace": sparky_screen,
            "ScreenPalm": sparky_screen,
            "TreadOrange": sparky_tread_orange,
        },
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

    renderer.object(
        name="open_floor",
        type="rectangle",
        p1=(-30.0, 0.0, 30.0),
        p2=(-30.0, 0.0, -30.0),
        p3=(30.0, 0.0, -30.0),
        material=pavilion_floor,
    )
    cylinder("main_stage", (0.0, 0.0, -1.0), (0.0, 1.0, 0.0), 0.34, 5.9, stage)
    disk("main_stage_top", (0.0, 0.34, -1.0), (0.0, 1.0, 0.0), 5.9, stage)
    cylinder("mascot_pedestal", (0.0, 0.34, -0.35), (0.0, 1.0, 0.0), 0.62, 2.35, pedestal)
    disk("mascot_pedestal_top", (0.0, 0.96, -0.35), (0.0, 1.0, 0.0), 2.35, pedestal)
    renderer.object(
        name="pavilion_mascot",
        type="mesh",
        mesh=mascot,
        translate=(-0.90, 0.96, 0.25),
        rotate_degrees=(0.0, 24.0, 0.0),
        scale=(0.98, 0.98, 0.98),
        material=mascot_porcelain,
    )
    renderer.object(
        name="pavilion_sparky",
        type="mesh",
        mesh=sparky,
        translate=(0.90, 0.963, -0.95),
        rotate_degrees=(0.0, 24.0, 0.0),
        scale=(0.937, 0.937, 0.937),
    )

    cylinder("wind_vane_foot", (-4.15, 0.34, 0.05), (0.0, 1.0, 0.0), 0.30, 0.62, instrument_frame)
    disk("wind_vane_foot_cap", (-4.15, 0.64, 0.05), (0.0, 1.0, 0.0), 0.62, terracotta)
    cylinder("wind_vane_mast", (-4.15, 0.64, 0.05), (0.0, 1.0, 0.0), 2.22, 0.072, rough_bronze)
    cylinder(
        "wind_vane_compass_east_west", (-4.66, 2.50, 0.05), (1.0, 0.0, 0.0), 1.02, 0.035, terracotta
    )
    cylinder(
        "wind_vane_compass_north_south", (-4.15, 2.50, -0.46), (0.0, 0.0, 1.0), 1.02, 0.035, terracotta
    )
    cylinder("wind_vane_arrow", (-4.78, 2.87, -0.39), (0.8192, 0.0, 0.5735), 1.62, 0.065, terracotta)
    renderer.object(
        name="wind_vane_tail",
        type="rectangle",
        p1=(-4.78, 2.75, -0.39),
        p2=(-4.38, 2.75, -0.11),
        p3=(-4.38, 3.36, -0.11),
        material=terracotta,
    )
    cylinder(
        "wind_vane_arrowhead_left", (-3.45, 2.87, 0.54), (-0.9990, 0.0, 0.0447), 0.38, 0.055, terracotta
    )
    cylinder(
        "wind_vane_arrowhead_right", (-3.45, 2.87, 0.54), (-0.3007, 0.0, -0.9537), 0.38, 0.055, terracotta
    )

    cylinder("sundial_plinth", (-3.70, 0.34, -1.80), (0.0, 1.0, 0.0), 0.62, 0.72, instrument_frame)
    disk("sundial_plinth_cap", (-3.70, 0.96, -1.80), (0.0, 1.0, 0.0), 0.72, rough_bronze)
    cylinder("sundial_rim", (-3.709, 1.174, -1.818), (0.18, 0.92, 0.35), 0.10, 1.05, instrument_frame)
    disk("sundial_face", (-3.691, 1.266, -1.783), (0.18, 0.92, 0.35), 1.05, rough_bronze)
    cylinder(
        "sundial_gnomon", (-3.691, 1.266, -1.783), (0.1168, 0.9157, -0.3845), 0.92, 0.052, instrument_frame
    )
    cylinder(
        "sundial_noon_marker", (-3.83, 1.315, -1.850), (0.9315, 0.0, 0.3637), 0.30, 0.028, instrument_frame
    )

    cylinder("heliostat_base", (1.05, 0.34, -4.48), (0.0, 1.0, 0.0), 0.30, 0.72, instrument_frame)
    disk("heliostat_base_cap", (1.05, 0.64, -4.48), (0.0, 1.0, 0.0), 0.72, smooth_chrome)
    cylinder("heliostat_spine", (1.05, 0.64, -4.62), (0.0, 1.0, 0.0), 1.26, 0.09, instrument_frame)
    cylinder("heliostat_pivot", (0.11, 1.83, -4.00), (2.0, 0.0, -1.0), 2.10, 0.075, rough_bronze)
    renderer.object(
        name="heliostat_mirror",
        type="parabola",
        origin=(1.05, 1.55, -4.65),
        normal=(2.0, 0.0, -1.0),
        focus=(1.25, 1.62, -4.25),
        clip_min=(0.35, 0.82, -4.90),
        clip_max=(2.02, 2.40, -3.85),
        front_material=None,
        back_material=smooth_chrome,
    )

    for values in (
        ("binocular_tripod_left", (4.20, 0.36, -0.80), (0.3436, 0.8866, -0.3092), 1.455, 0.055, instrument_frame),
        ("binocular_tripod_right", (5.30, 0.36, -0.95), (-0.4121, 0.8860, -0.2060), 1.456, 0.055, instrument_frame),
        ("binocular_tripod_rear", (4.65, 0.36, -1.85), (0.0351, 0.9065, 0.4216), 1.423, 0.055, instrument_frame),
        ("binocular_column", (4.70, 1.65, -1.25), (0.0, 1.0, 0.0), 0.62, 0.095, rough_bronze),
        ("binocular_yoke", (4.20, 2.27, -0.92), (0.8330, 0.0, -0.5533), 1.20, 0.085, instrument_frame),
        ("binocular_left_barrel", (4.09, 2.34, -1.63), (0.5518, 0.0401, 0.8330), 0.74, 0.41, instrument_frame),
        ("binocular_right_barrel", (4.81, 2.34, -2.11), (0.5518, 0.0401, 0.8330), 0.74, 0.41, instrument_frame),
        ("binocular_left_rim", (4.498, 2.370, -1.014), (0.5518, 0.0401, 0.8330), 0.12, 0.46, smooth_chrome),
        ("binocular_right_rim", (5.218, 2.370, -1.494), (0.5518, 0.0401, 0.8330), 0.12, 0.46, smooth_chrome),
    ):
        cylinder(*values)
    renderer.object(
        name="binocular_left_lens",
        type="sphere",
        center=(4.575, 2.375, -0.897),
        radius=0.35,
        material=optical_glass,
    )
    renderer.object(
        name="binocular_right_lens",
        type="sphere",
        center=(5.295, 2.375, -1.377),
        radius=0.35,
        material=optical_glass,
    )
    return renderer


def main() -> None:
    output = ROOT / "output/examples/radiance-pavilion.png"
    create_renderer().render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=1920,
        height=1080,
        spp=512,
        depth=12,
        seed=909,
        denoise=True,
    )


if __name__ == "__main__":
    main()
