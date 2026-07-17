import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCENES = ROOT / "scenes"


def load_scene(name):
    return runpy.run_path(str(SCENES / name))


def finish(renderer):
    scene = renderer._builder.finish()
    assert scene is not None


def test_tidal_observatory_factory_builds_complete_host_scene():
    module = load_scene("tidal-observatory.py")
    renderer = module["create_renderer"](device=3)

    assert renderer.device == 3
    assert renderer.scene_name == "tidal-observatory"
    assert (module["FORMAL_WIDTH"], module["FORMAL_HEIGHT"]) == (2560, 1440)
    assert (module["FORMAL_SPP"], module["FORMAL_DEPTH"], module["SEED"]) == (
        1024,
        12,
        909,
    )
    finish(renderer)


def test_light_transport_comparison_factory_builds_host_scene():
    module = load_scene("compare-light-transport.py")
    renderer = module["create_light_transport_renderer"](device=0)

    assert module["FORMAL_SIZE"] == 1024
    assert (module["INDIRECT_SEED"], module["DENOISER_SEED"]) == (1101, 1102)
    finish(renderer)


def test_hdr_comparison_factory_accepts_both_sampling_modes():
    module = load_scene("compare-hdr-sampling.py")

    assert module["FORMAL_SIZE"] == 1024
    assert (module["ENVIRONMENT_SEED"], module["FIREFLY_SEED"]) == (2201, 909)
    for mode in ("uniform", "importance"):
        finish(
            module["create_hdr_sampling_renderer"](
                direct_light_sampling=mode, device=0
            )
        )


def test_normal_mapping_comparison_binds_both_scale_endpoints():
    module = load_scene("compare-normal-mapping.py")

    assert (module["FORMAL_SIZE"], module["SEED"]) == (1024, 3301)
    for scale in (0.0, 1.0):
        finish(
            module["create_normal_mapping_renderer"](
                normal_scale=scale, device=0
            )
        )


def test_water_absorption_comparison_binds_both_media():
    module = load_scene("compare-water-absorption.py")

    assert (module["FORMAL_SIZE"], module["SEED"]) == (1024, 808)
    assert module["CLEAR_ABSORPTION"] == (0.0, 0.0, 0.0)
    assert module["DISPLAY_ABSORPTION"] == (0.45, 0.09, 0.025)
    for absorption in (
        module["CLEAR_ABSORPTION"],
        module["DISPLAY_ABSORPTION"],
    ):
        finish(
            module["create_water_absorption_renderer"](
                absorption=absorption, device=0
            )
        )
