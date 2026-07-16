#!/usr/bin/env python3
"""Ember Forge: a busy workshop lit exclusively by procedural flame."""

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
        look_from=(-0.8, 3.20, 10.8),
        look_at=(-2.10, 1.80, -0.40),
        up=(0.0, 1.0, 0.0),
        vfov=24.0,
        aperture=0.0,
        focus_distance=11.4,
    )
    renderer.background(type="constant", color=(0.0, 0.0, 0.0), exposure=0.5)

    flagstone = renderer.material(
        name="flagstone", type="lambertian", base_color=(0.42, 0.36, 0.29)
    )
    old_brick = renderer.material(
        name="old_brick", type="lambertian", base_color=(0.55, 0.27, 0.11)
    )
    mortar = renderer.material(
        name="mortar", type="lambertian", base_color=(0.50, 0.42, 0.32)
    )
    tool_wall = renderer.material(
        name="tool_wall", type="lambertian", base_color=(0.95, 0.76, 0.48)
    )
    refractory = renderer.material(
        name="refractory", type="lambertian", base_color=(0.46, 0.29, 0.13)
    )
    soot = renderer.material(
        name="soot", type="lambertian", base_color=(0.018, 0.012, 0.008)
    )
    forged_iron = renderer.material(
        name="forged_iron", type="metal", base_color=(0.90, 0.72, 0.50), roughness=0.62
    )
    blackened_iron = renderer.material(
        name="blackened_iron",
        type="metal",
        base_color=(0.35, 0.25, 0.16),
        roughness=0.58,
    )
    polished_edge = renderer.material(
        name="polished_edge", type="metal", base_color=(0.95, 0.82, 0.60), roughness=0.30
    )
    oak = renderer.material(name="oak", type="lambertian", base_color=(0.48, 0.25, 0.09))
    leather = renderer.material(
        name="leather", type="lambertian", base_color=(0.34, 0.11, 0.035)
    )
    heated_steel = renderer.material(
        name="heated_steel", type="metal", base_color=(0.90, 0.24, 0.025), roughness=0.30
    )
    quench_surface = renderer.material(
        name="quench_surface", type="metal", base_color=(0.12, 0.13, 0.12), roughness=0.08
    )
    mascot_ivory = renderer.material(
        name="mascot_ivory", type="lambertian", base_color=(0.90, 0.83, 0.69)
    )
    mascot = renderer.mesh(
        name="mascot", path=ROOT / "assets/examples/models/capsule-mascot.obj"
    )

    def rectangle(name, p1, p2, p3, material):
        return renderer.object(
            name=name, type="rectangle", p1=p1, p2=p2, p3=p3, material=material
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

    for values in (
        ("workshop_floor", (-9.0, 0.0, 6.0), (-9.0, 0.0, -7.0), (9.0, 0.0, -7.0), flagstone),
        ("workshop_back_wall", (-9.0, 0.0, -7.0), (-9.0, 8.0, -7.0), (9.0, 8.0, -7.0), old_brick),
        ("workshop_left_wall", (-9.0, 0.0, 6.0), (-9.0, 8.0, 6.0), (-9.0, 8.0, -7.0), mortar),
        ("workshop_right_wall", (9.0, 0.0, -7.0), (9.0, 8.0, -7.0), (9.0, 8.0, 6.0), mortar),
        ("workshop_ceiling", (-9.0, 8.0, 6.0), (9.0, 8.0, 6.0), (9.0, 8.0, -7.0), soot),
        ("forge_lower_front", (-6.25, 0.0, -0.65), (-6.25, 1.10, -0.65), (-2.55, 1.10, -0.65), old_brick),
        ("forge_left_jamb", (-6.25, 1.10, -0.65), (-6.25, 3.90, -0.65), (-5.65, 3.90, -0.65), old_brick),
        ("forge_right_jamb", (-3.15, 1.10, -0.65), (-3.15, 3.90, -0.65), (-2.55, 3.90, -0.65), old_brick),
        ("forge_lintel", (-5.65, 3.35, -0.65), (-5.65, 3.90, -0.65), (-3.15, 3.90, -0.65), old_brick),
        ("forge_hearth", (-5.65, 1.10, 0.35), (-5.65, 1.10, -2.80), (-3.15, 1.10, -2.80), refractory),
        ("forge_fireback", (-5.65, 1.10, -2.82), (-5.65, 3.35, -2.82), (-3.15, 3.35, -2.82), soot),
        ("forge_left_inner_wall", (-5.65, 1.10, 0.35), (-5.65, 3.35, 0.35), (-5.65, 3.35, -2.82), refractory),
        ("forge_right_inner_wall", (-3.15, 1.10, -2.82), (-3.15, 3.35, -2.82), (-3.15, 3.35, -1.25), soot),
        ("forge_left_outer_wall", (-6.25, 0.0, -0.65), (-6.25, 3.90, -0.65), (-6.25, 3.90, -3.55), old_brick),
        ("forge_right_outer_wall", (-2.55, 0.0, -3.55), (-2.55, 3.90, -3.55), (-2.55, 3.90, -0.65), old_brick),
        ("forge_top_slab", (-6.25, 3.90, -0.65), (-6.25, 3.90, -3.55), (-2.55, 3.90, -3.55), mortar),
        ("smoke_hood_back", (-6.10, 3.75, -2.95), (-5.48, 5.55, -2.95), (-3.32, 5.55, -2.95), blackened_iron),
        ("smoke_hood_left", (-6.10, 3.75, -0.45), (-5.48, 5.55, -1.30), (-5.48, 5.55, -2.95), blackened_iron),
        ("smoke_hood_right", (-3.32, 5.55, -2.95), (-3.32, 5.55, -1.30), (-2.70, 3.75, -0.45), blackened_iron),
        ("smoke_hood_front", (-6.10, 3.75, -0.45), (-5.48, 5.55, -1.30), (-3.32, 5.55, -1.30), forged_iron),
        ("anvil_face_top", (-1.25, 1.94, -0.02), (-1.25, 1.94, -0.88), (0.80, 1.94, -0.88), polished_edge),
        ("anvil_face_front", (-1.25, 1.64, -0.02), (-1.25, 1.94, -0.02), (0.80, 1.94, -0.02), forged_iron),
        ("anvil_face_end", (0.80, 1.64, -0.88), (0.80, 1.94, -0.88), (0.80, 1.94, -0.02), forged_iron),
        ("tool_rack_backboard", (-0.20, 1.30, -1.60), (-0.20, 5.55, -1.60), (3.50, 5.55, -0.80), tool_wall),
    ):
        rectangle(*values)

    for values in (
        ("left_timber_post", (-7.85, 0.0, -5.95), (0.0, 1.0, 0.0), 7.75, 0.28, oak),
        ("center_timber_post", (0.0, 0.0, -6.75), (0.0, 1.0, 0.0), 7.75, 0.24, oak),
        ("right_timber_post", (7.75, 0.0, -5.95), (0.0, 1.0, 0.0), 7.75, 0.28, oak),
        ("rear_ceiling_beam", (-8.1, 7.45, -5.95), (1.0, 0.0, 0.0), 16.2, 0.30, oak),
        ("front_ceiling_beam", (-8.1, 7.35, 2.15), (1.0, 0.0, 0.0), 16.2, 0.28, oak),
        ("left_depth_beam", (-7.85, 7.45, -6.15), (0.0, 0.0, 1.0), 8.55, 0.24, oak),
        ("right_depth_beam", (7.75, 7.45, -6.15), (0.0, 0.0, 1.0), 8.55, 0.24, oak),
        ("forge_ash_lip", (-5.72, 1.03, -0.48), (1.0, 0.0, 0.0), 2.64, 0.10, blackened_iron),
        ("forge_left_grate", (-5.35, 1.16, 0.16), (0.0, 0.0, -1.0), 1.75, 0.045, blackened_iron),
        ("forge_center_grate", (-4.40, 1.16, 0.16), (0.0, 0.0, -1.0), 1.75, 0.045, blackened_iron),
        ("forge_right_grate", (-3.45, 1.16, 0.16), (0.0, 0.0, -1.0), 1.75, 0.045, blackened_iron),
        ("forge_mortar_course_low", (-6.20, 0.54, -0.62), (1.0, 0.0, 0.0), 3.60, 0.035, mortar),
        ("forge_mortar_course_high", (-6.20, 3.52, -0.62), (1.0, 0.0, 0.0), 3.60, 0.035, mortar),
        ("chimney_stack", (-4.40, 5.45, -2.05), (0.0, 1.0, 0.0), 2.45, 0.58, blackened_iron),
        ("chimney_band_low", (-4.40, 5.84, -2.05), (0.0, 1.0, 0.0), 0.10, 0.64, forged_iron),
        ("chimney_band_high", (-4.40, 7.28, -2.05), (0.0, 1.0, 0.0), 0.10, 0.64, forged_iron),
        ("anvil_foot", (0.05, 0.0, -0.45), (0.0, 1.0, 0.0), 0.24, 0.92, blackened_iron),
        ("anvil_base", (0.05, 0.24, -0.45), (0.0, 1.0, 0.0), 0.36, 0.70, forged_iron),
        ("anvil_waist", (0.05, 0.60, -0.45), (0.0, 1.0, 0.0), 0.82, 0.45, forged_iron),
        ("anvil_shoulder", (0.05, 1.42, -0.45), (0.0, 1.0, 0.0), 0.22, 0.72, forged_iron),
        ("anvil_horn_base", (0.80, 1.64, -0.45), (1.0, 0.02, 0.0), 0.68, 0.24, forged_iron),
        ("anvil_horn_tip", (1.48, 1.65, -0.45), (1.0, 0.07, 0.0), 0.64, 0.11, forged_iron),
        ("anvil_horn_point", (2.12, 1.69, -0.45), (1.0, 0.12, 0.0), 0.38, 0.055, polished_edge),
        ("heated_workpiece", (-0.60, 2.04, -0.58), (1.0, 0.0, 0.08), 1.45, 0.095, heated_steel),
        ("hammer_handle", (-3.17, 1.12, 0.57), (0.58, 0.80, -0.18), 2.08, 0.085, oak),
        ("hammer_head", (-2.25, 2.48, 0.27), (0.84, -0.08, -0.53), 0.88, 0.23, polished_edge),
        ("hammer_peen", (-1.51, 2.41, -0.20), (0.84, -0.08, -0.53), 0.35, 0.12, forged_iron),
        ("bellows_body", (-6.85, 0.92, 0.40), (0.0, 0.0, 1.0), 0.28, 0.82, leather),
        ("bellows_nozzle", (-6.25, 1.02, 0.52), (1.0, 0.0, -0.22), 1.28, 0.11, forged_iron),
        ("bellows_lever", (-7.20, 1.36, 0.55), (0.10, 1.0, 0.0), 1.62, 0.075, oak),
        ("quench_bucket", (3.22, 0.0, -0.50), (0.0, 1.0, 0.0), 1.28, 0.68, blackened_iron),
        ("quench_bucket_band_low", (3.22, 0.20, -0.50), (0.0, 1.0, 0.0), 0.08, 0.73, forged_iron),
        ("quench_bucket_band_high", (3.22, 1.10, -0.50), (0.0, 1.0, 0.0), 0.08, 0.73, forged_iron),
        ("quench_handle", (2.54, 1.03, -0.50), (0.0, 0.72, 0.70), 1.42, 0.045, forged_iron),
        ("tool_rack_top", (-0.10, 5.28, -0.72), (1.0, 0.0, 0.0), 5.05, 0.095, oak),
        ("tool_rack_bottom", (-0.10, 2.05, -0.72), (1.0, 0.0, 0.0), 5.05, 0.095, oak),
        ("tool_rack_left_post", (0.05, 1.55, -0.72), (0.0, 1.0, 0.0), 4.10, 0.085, oak),
        ("tool_rack_right_post", (4.80, 1.55, -0.72), (0.0, 1.0, 0.0), 4.10, 0.085, oak),
        ("rack_hammer_handle", (1.05, 2.32, -0.59), (0.0, 1.0, 0.0), 2.35, 0.060, oak),
        ("rack_hammer_head", (0.65, 4.67, -0.59), (1.0, 0.0, 0.0), 0.80, 0.17, forged_iron),
        ("rack_tongs_left", (2.03, 2.18, -0.57), (-0.10, 1.0, 0.0), 2.72, 0.045, forged_iron),
        ("rack_tongs_right", (2.40, 2.18, -0.57), (0.10, 1.0, 0.0), 2.72, 0.045, forged_iron),
        ("rack_poker", (3.22, 2.10, -0.57), (0.04, 1.0, 0.0), 3.05, 0.050, forged_iron),
        ("rack_shovel_handle", (4.04, 2.10, -0.57), (-0.04, 1.0, 0.0), 2.82, 0.060, oak),
        ("rack_round_tongs_handle", (4.56, 2.02, -0.57), (0.0, 1.0, 0.0), 1.84, 0.050, forged_iron),
        ("steel_stock_low", (3.80, 0.18, -3.82), (1.0, 0.0, 0.18), 2.15, 0.14, forged_iron),
        ("steel_stock_mid", (3.92, 0.46, -3.88), (1.0, 0.0, -0.12), 1.88, 0.12, forged_iron),
        ("steel_stock_high", (4.18, 0.71, -4.00), (1.0, 0.0, 0.08), 1.52, 0.10, forged_iron),
        ("stock_stop_left", (3.62, 0.0, -3.92), (0.0, 1.0, 0.0), 0.95, 0.09, blackened_iron),
        ("stock_stop_right", (5.92, 0.0, -3.65), (0.0, 1.0, 0.0), 0.95, 0.09, blackened_iron),
        ("floor_tongs_left", (-0.92, 0.08, 2.55), (0.95, 0.0, -0.31), 2.20, 0.045, forged_iron),
        ("floor_tongs_right", (-0.80, 0.08, 2.82), (0.96, 0.0, -0.27), 2.20, 0.045, forged_iron),
        ("coal_basket", (-7.52, 0.0, -1.42), (0.0, 1.0, 0.0), 0.72, 0.72, blackened_iron),
        ("coal_basket_rim", (-7.52, 0.68, -1.42), (0.0, 1.0, 0.0), 0.08, 0.78, forged_iron),
    ):
        cylinder(*values)

    renderer.object(
        name="smith_mascot",
        type="mesh",
        mesh=mascot,
        translate=(-2.20, 0.02, 0.25),
        rotate_degrees=(0.0, 25.0, 0.0),
        scale=(1.25, 1.25, 1.25),
        material=mascot_ivory,
    )
    for values in (
        ("bellows_front_plate", (-6.85, 0.92, 0.70), (0.0, 0.0, 1.0), 0.86, oak),
        ("bellows_back_plate", (-6.85, 0.92, 0.38), (0.0, 0.0, -1.0), 0.86, oak),
        ("quench_bucket_water", (3.22, 1.24, -0.50), (0.0, 1.0, 0.0), 0.61, quench_surface),
        ("rack_shovel_blade", (3.93, 2.12, -0.51), (0.0, 0.0, 1.0), 0.34, forged_iron),
        ("rack_round_tongs", (4.56, 4.16, -0.53), (0.0, 0.0, 1.0), 0.31, forged_iron),
    ):
        disk(*values)
    for name, center, radius in (
        ("coal_lump_left", (-7.78, 0.77, -1.30), 0.31),
        ("coal_lump_center", (-7.42, 0.84, -1.54), 0.36),
        ("coal_lump_right", (-7.12, 0.75, -1.26), 0.27),
    ):
        renderer.object(name=name, type="sphere", center=center, radius=radius, material=soot)

    renderer.light(
        name="forge_bed_core",
        type="flame",
        position=(-4.42, 1.16, -0.15),
        axis=(0.0, 1.0, 0.0),
        height=0.74,
        radius_start=0.58,
        radius_end=0.34,
        emission_start=(60.0, 18.0, 0.7),
        emission_end=(42.0, 5.0, 0.08),
        extinction=2.20,
        density_scale=0.65,
        turbulence=0.55,
        noise_scale=4.20,
        seed=707,
    )
    renderer.light(
        name="forge_main_tongue",
        type="flame",
        position=(-4.46, 1.36, -0.05),
        axis=(-0.10, 1.0, -0.04),
        height=1.75,
        radius_start=0.44,
        radius_end=0.16,
        emission_start=(55.0, 10.0, 0.25),
        emission_end=(9.0, 0.4, 0.01),
        extinction=1.90,
        density_scale=0.58,
        turbulence=0.84,
        noise_scale=3.55,
        seed=1707,
    )
    renderer.light(
        name="forge_side_tongue",
        type="flame",
        position=(-4.03, 1.34, 0.05),
        axis=(0.32, 1.0, 0.04),
        height=1.25,
        radius_start=0.27,
        radius_end=0.09,
        emission_start=(45.0, 6.0, 0.1),
        emission_end=(5.0, 0.15, 0.003),
        extinction=1.47,
        density_scale=0.50,
        turbulence=0.92,
        noise_scale=5.10,
        seed=2707,
    )
    return renderer


def main() -> None:
    output = ROOT / "output/examples/ember-forge.png"
    create_renderer().render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=1920,
        height=1080,
        spp=2048,
        depth=12,
        seed=707,
        denoise=False,
    )


if __name__ == "__main__":
    main()
