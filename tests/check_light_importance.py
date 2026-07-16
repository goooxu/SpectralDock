#!/usr/bin/env python3
"""GPU checks for finite-light selection and power-weighted sampling."""

import math
import struct
import sys
import tempfile
from pathlib import Path

from PIL import Image

from spectraldock import Renderer


WIDTH = 48
HEIGHT = 48
ROI = (4, 4, 44, 44)


def receiver_renderer(
    mode="importance",
    *,
    look_from=(0.0, 0.0, 4.0),
    look_at=(0.0, 0.0, 0.0),
    vfov=40.0,
    focus_distance=4.0,
    base_color=(0.76, 0.76, 0.76),
):
    renderer = Renderer()
    renderer.camera(
        look_from=look_from,
        look_at=look_at,
        up=(0.0, 1.0, 0.0),
        vfov=vfov,
        aperture=0.0,
        focus_distance=focus_distance,
    )
    renderer.integrator(
        direct_light_sampling=mode, clamp_direct=0.0, clamp_indirect=0.0
    )
    renderer.background(type="constant", color=(0.0, 0.0, 0.0), exposure=-3.0)
    receiver = renderer.material(
        name="receiver", type="lambertian", base_color=base_color
    )
    renderer.object(
        name="receiver",
        type="rectangle",
        p1=(-2.0, -2.0, 0.0),
        p2=(-2.0, 2.0, 0.0),
        p3=(2.0, 2.0, 0.0),
        material=receiver,
    )
    return renderer


def add_dominant_rectangle(renderer):
    renderer.light(
        name="dominant_rectangle",
        type="rectangle",
        position=(-0.6, 0.6, 1.8),
        edge_u=(1.2, 0.0, 0.0),
        edge_v=(0.0, -1.2, 0.0),
        emission=(32.0, 26.0, 18.0),
    )


def add_dim_disk(renderer):
    renderer.light(
        name="dim_disk",
        type="disk",
        position=(-1.35, 0.8, 1.5),
        normal=(0.0, 0.0, -1.0),
        radius=0.28,
        emission=(0.08, 0.10, 0.14),
    )


def add_dim_sphere(renderer):
    renderer.light(
        name="dim_sphere",
        type="sphere",
        position=(1.2, 0.75, 1.4),
        radius=0.22,
        emission=(0.12, 0.08, 0.05),
    )


def add_dim_flame(renderer):
    renderer.light(
        name="dim_flame",
        type="flame",
        position=(1.45, -0.6, 1.25),
        axis=(0.0, 1.0, 0.0),
        height=0.8,
        radius_start=0.16,
        radius_end=0.10,
        emission_start=(0.20, 0.06, 0.01),
        emission_end=(0.08, 0.01, 0.001),
        extinction=0.35,
        density_scale=0.8,
        turbulence=0.0,
        noise_scale=2.0,
        seed=811,
    )


def add_isolated_disk(renderer):
    renderer.light(
        name="dim_disk",
        type="disk",
        position=(-1.35, 0.8, 1.5),
        normal=(0.0, 0.0, -1.0),
        radius=0.28,
        emission=(18.0, 18.0, 18.0),
    )


def add_isolated_sphere(renderer):
    renderer.light(
        name="dim_sphere",
        type="sphere",
        position=(1.2, 0.75, 1.4),
        radius=0.22,
        emission=(18.0, 18.0, 18.0),
    )


def add_isolated_flame(renderer):
    renderer.light(
        name="dim_flame",
        type="flame",
        position=(1.45, -0.6, 1.25),
        axis=(0.0, 1.0, 0.0),
        height=0.8,
        radius_start=0.16,
        radius_end=0.10,
        emission_start=(20.0, 6.0, 0.5),
        emission_end=(8.0, 1.0, 0.08),
        extinction=1.2,
        density_scale=0.8,
        turbulence=0.0,
        noise_scale=2.0,
        seed=811,
    )


def add_representative_lights(renderer):
    add_dominant_rectangle(renderer)
    add_dim_disk(renderer)
    add_dim_sphere(renderer)
    add_dim_flame(renderer)


def render(renderer, directory, name, mode, spp, seed, max_depth=1):
    output = directory / (name + ".png")
    stats = renderer.render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        width=WIDTH,
        height=HEIGHT,
        spp=spp,
        depth=max_depth,
        seed=seed,
        denoise=False,
    )
    with Image.open(output) as decoded:
        decoded.load()
        if decoded.size != (WIDTH, HEIGHT) or decoded.mode != "RGBA":
            raise RuntimeError(
                "unexpected finite-light output: {} {}".format(
                    decoded.size, decoded.mode
                )
            )
        image = decoded.copy()
    actual_mode = stats.get("render", {}).get("direct_light_sampling")
    if actual_mode != mode:
        raise RuntimeError(
            "stats report direct_light_sampling={!r}, expected {!r}".format(
                actual_mode, mode
            )
        )
    return image, stats


def render_linear_probe(renderer, directory, name, spp, seed):
    output = directory / (name + ".png")
    linear = directory / (name + ".pfm")
    renderer.render(
        output=output,
        stats_output=output.with_suffix(".stats.json"),
        linear_output=linear,
        width=1,
        height=1,
        spp=spp,
        depth=2,
        seed=seed,
        denoise=False,
    )
    with linear.open("rb") as stream:
        if stream.readline() != b"PF\n" or stream.readline() != b"1 1\n":
            raise RuntimeError("unexpected sphere-boundary PFM header")
        if float(stream.readline()) >= 0.0:
            raise RuntimeError("expected little-endian sphere-boundary PFM")
        payload = stream.read()
    if len(payload) != 12:
        raise RuntimeError("unexpected sphere-boundary PFM payload")
    values = struct.unpack("<3f", payload)
    if any(not math.isfinite(value) for value in values):
        raise RuntimeError("non-finite sphere-boundary PFM value")
    return values


def bound_emitter_mis_renderer(mode):
    renderer = receiver_renderer(mode)
    visible_emitter = renderer.material(
        name="visible_emitter", type="emitter", emission=(12.0, 12.0, 12.0)
    )
    back_emitter = renderer.material(
        name="back_emitter", type="emitter", emission=(108.0, 108.0, 108.0)
    )
    visible_panel = renderer.object(
        name="visible_panel",
        type="rectangle",
        p1=(-2.0, 3.2, 1.0),
        p2=(-2.0, 1.2, 1.0),
        p3=(2.0, 1.2, 1.0),
        material=visible_emitter,
    )
    back_panel = renderer.object(
        name="back_panel",
        type="rectangle",
        p1=(-2.0, 1.0, -1.2),
        p2=(-2.0, -1.0, -1.2),
        p3=(2.0, -1.0, -1.2),
        material=back_emitter,
    )
    renderer.light(
        name="visible_panel_sample",
        type="rectangle",
        object=visible_panel,
        position=(-2.0, 3.2, 1.0),
        edge_u=(4.0, 0.0, 0.0),
        edge_v=(0.0, -2.0, 0.0),
        emission=(12.0, 12.0, 12.0),
    )
    renderer.light(
        name="back_panel_sample",
        type="rectangle",
        object=back_panel,
        position=(-2.0, 1.0, -1.2),
        edge_u=(4.0, 0.0, 0.0),
        edge_v=(0.0, -2.0, 0.0),
        emission=(108.0, 108.0, 108.0),
    )
    return renderer


def sphere_cone_boundary_renderer(bound):
    renderer = receiver_renderer(
        "importance",
        look_from=(10.0, 0.0, 0.02),
        look_at=(0.0, 0.0, 0.0),
        vfov=0.001,
        focus_distance=10.0,
        base_color=(1.0, 1.0, 1.0),
    )
    center = (0.0, 0.0, 1.00025)
    emitter_object = None
    if bound:
        sphere_emitter = renderer.material(
            name="sphere_emitter", type="emitter", emission=(1.0, 1.0, 1.0)
        )
        emitter_object = renderer.object(
            name="sphere_emitter",
            type="sphere",
            center=center,
            radius=1.0,
            material=sphere_emitter,
        )
    renderer.light(
        name="near_sphere",
        type="sphere",
        object=emitter_object,
        position=center,
        radius=1.0,
        emission=(1.0, 1.0, 1.0),
    )
    return renderer


def metric(tree, name):
    if isinstance(tree, dict):
        if name in tree:
            return tree[name]
        matches = [metric(child, name) for child in tree.values()]
        matches = [value for value in matches if value is not None]
        if len(matches) > 1:
            raise RuntimeError("duplicate stats metric: {}".format(name))
        return matches[0] if matches else None
    if isinstance(tree, list):
        matches = [metric(child, name) for child in tree]
        matches = [value for value in matches if value is not None]
        return matches[0] if len(matches) == 1 else None
    return None


def rgb_values(image):
    return [pixel[:3] for pixel in image.crop(ROI).getdata()]


def mean_luminance(image):
    values = rgb_values(image)
    return sum(
        0.2126 * red + 0.7152 * green + 0.0722 * blue
        for red, green, blue in values
    ) / len(values)


def mse(image, reference):
    left = rgb_values(image)
    right = rgb_values(reference)
    return sum(
        (a - b) * (a - b)
        for left_pixel, right_pixel in zip(left, right)
        for a, b in zip(left_pixel, right_pixel)
    ) / (3.0 * len(left))


def main():
    if len(sys.argv) != 1:
        raise RuntimeError("check_light_importance.py does not accept arguments")

    with tempfile.TemporaryDirectory(prefix="spectraldock-light-importance-") as tmp:
        directory = Path(tmp)

        # This epsilon-scale geometry exercises bound NEE + BSDF-hit MIS at
        # the sphere-cone/area fallback boundary. The unbound light is the
        # NEE-only reference.
        boundary_spp = 16384
        bound_boundary = render_linear_probe(
            sphere_cone_boundary_renderer(True),
            directory,
            "sphere-cone-bound",
            boundary_spp,
            1709,
        )
        unbound_boundary = render_linear_probe(
            sphere_cone_boundary_renderer(False),
            directory,
            "sphere-cone-unbound",
            boundary_spp,
            1811,
        )
        for channel, (bound_value, unbound_value) in enumerate(
            zip(bound_boundary, unbound_boundary)
        ):
            comparison_scale = max(0.5 * (bound_value + unbound_value), 1.0e-6)
            if min(bound_value, unbound_value) <= 0.5:
                raise RuntimeError("sphere-cone boundary probe rendered dark")
            if abs(bound_value - unbound_value) > 0.025 * comparison_scale:
                raise RuntimeError(
                    "sphere-cone bound/unbound MIS mismatch in channel {}: "
                    "{} versus {}".format(channel, bound_value, unbound_value)
                )

        # Exercise rectangle, disk, sphere, and flame sampling independently.
        isolated_builders = (
            ("rectangle", add_dominant_rectangle, False),
            ("disk", add_isolated_disk, False),
            ("sphere", add_isolated_sphere, False),
            ("flame", add_isolated_flame, True),
        )
        for index, (kind, add_light, is_flame) in enumerate(isolated_builders):
            isolated = receiver_renderer("importance")
            add_light(isolated)
            image, stats = render(
                isolated,
                directory,
                "single-{}".format(kind),
                "importance",
                64,
                821 + index,
            )
            if mean_luminance(image) <= 0.1:
                raise RuntimeError("{} light did not illuminate the receiver".format(kind))
            if is_flame and metric(stats, "volume_light_samples") in (None, 0):
                raise RuntimeError("flame NEE branch was not sampled")

        # Bound emitter-hit MIS must use the same finite-light selection q_i as
        # NEE in both uniform and power-weighted modes.
        bound_uniform, _ = render(
            bound_emitter_mis_renderer("uniform"),
            directory,
            "bound-mis-uniform",
            "uniform",
            768,
            1451,
            max_depth=2,
        )
        bound_importance, _ = render(
            bound_emitter_mis_renderer("importance"),
            directory,
            "bound-mis-importance",
            "importance",
            768,
            1559,
            max_depth=2,
        )
        bound_uniform_mean = mean_luminance(bound_uniform)
        bound_importance_mean = mean_luminance(bound_importance)
        if min(bound_uniform_mean, bound_importance_mean) <= 1.0:
            raise RuntimeError("bound-emitter MIS comparison rendered blank")
        bound_relative_error = abs(
            bound_uniform_mean - bound_importance_mean
        ) / max(0.5 * (bound_uniform_mean + bound_importance_mean), 1.0)
        if bound_relative_error > 0.08:
            raise RuntimeError(
                "bound-emitter uniform/importance means disagree; emitter-hit "
                "MIS may not include q_i: {:.3f}".format(bound_relative_error)
            )

        reference_renderer = receiver_renderer("importance")
        add_representative_lights(reference_renderer)
        reference, _ = render(
            reference_renderer, directory, "reference", "importance", 1024, 907
        )
        uniform_high_renderer = receiver_renderer("uniform")
        add_representative_lights(uniform_high_renderer)
        uniform_high, uniform_stats = render(
            uniform_high_renderer,
            directory,
            "uniform-high",
            "uniform",
            2048,
            1013,
        )
        reference_mean = mean_luminance(reference)
        uniform_mean = mean_luminance(uniform_high)
        relative_mean_error = abs(reference_mean - uniform_mean) / max(
            reference_mean, 1.0
        )
        if relative_mean_error > 0.12:
            raise RuntimeError(
                "finite-light uniform/importance high-spp means did not "
                "converge: {:.3f}".format(relative_mean_error)
            )
        if metric(uniform_stats, "volume_light_samples") in (None, 0):
            raise RuntimeError("mixed-light uniform run did not sample flame NEE")

        uniform_error = 0.0
        importance_error = 0.0
        for index, seed in enumerate((1103, 1213, 1321)):
            uniform_renderer = receiver_renderer("uniform")
            add_representative_lights(uniform_renderer)
            uniform, _ = render(
                uniform_renderer,
                directory,
                "uniform-low-{}".format(index),
                "uniform",
                8,
                seed,
            )
            importance_renderer = receiver_renderer("importance")
            add_representative_lights(importance_renderer)
            importance, _ = render(
                importance_renderer,
                directory,
                "importance-low-{}".format(index),
                "importance",
                8,
                seed,
            )
            uniform_error += mse(uniform, reference)
            importance_error += mse(importance, reference)
        if not importance_error < 0.85 * uniform_error:
            raise RuntimeError(
                "power-weighted light selection did not reduce low-spp MSE: "
                "importance={:.3f}, uniform={:.3f}".format(
                    importance_error, uniform_error
                )
            )

    print("finite-light importance sampling checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as error:
        print("error: {}".format(error), file=sys.stderr)
        raise SystemExit(1)
