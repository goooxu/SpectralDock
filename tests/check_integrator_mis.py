#!/usr/bin/env python3
"""Compare finite-light endpoint visibility for bound and unbound variants."""

import argparse
import sys
import tempfile
from pathlib import Path

from PIL import Image

from spectraldock import Renderer


WIDTH = 64
HEIGHT = 64
SPP = 4
MAX_DEPTH = 1
SEED = 1


def add(left, right):
    return tuple(a + b for a, b in zip(left, right))


def positive_integer(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return result


def nonnegative_integer(value: str) -> int:
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return result


def create_renderer(*, light_shape: str, bound: bool, device: int, offset) -> Renderer:
    """Build the smoke fixture, optionally binding its light to emitter geometry."""

    renderer = Renderer(
        device=device,
        scene_name=(
            f"integrator-mis-{light_shape}-"
            f"{'bound' if bound else 'unbound'}"
        ),
    )
    renderer.integrator(
        direct_light_sampling="importance", clamp_direct=0.0, clamp_indirect=0.0
    )
    renderer.camera(
        look_from=add(offset, (3.0, 2.0, 5.0)),
        look_at=add(offset, (0.0, 0.5, 0.0)),
        up=(0.0, 1.0, 0.0),
        vfov=38.0,
        aperture=0.0,
        focus_distance=5.0,
    )
    renderer.background(
        type="constant", color=(0.01, 0.01, 0.015), exposure=0.0
    )

    white = renderer.material(
        name="white", type="lambertian", base_color=(0.75, 0.75, 0.75)
    )
    red = renderer.material(
        name="red", type="lambertian", base_color=(0.75, 0.08, 0.05)
    )
    mirror = renderer.material(
        name="mirror",
        type="metal",
        base_color=(0.92, 0.92, 0.92),
        roughness=0.08,
    )
    emitter = renderer.material(
        name="light", type="emitter", emission=(12.0, 10.0, 8.0)
    )

    renderer.object(
        name="floor",
        type="rectangle",
        p1=add(offset, (-3.0, 0.0, 2.0)),
        p2=add(offset, (-3.0, 0.0, -3.0)),
        p3=add(offset, (3.0, 0.0, -3.0)),
        material=white,
    )
    renderer.object(
        name="red_ball",
        type="sphere",
        center=add(offset, (-0.7, 0.7, 0.0)),
        radius=0.7,
        material=red,
    )
    renderer.object(
        name="mirror_ball",
        type="sphere",
        center=add(offset, (0.9, 0.5, -0.4)),
        radius=0.5,
        material=mirror,
    )
    if light_shape == "rectangle":
        ceiling_light = renderer.object(
            name="ceiling_light",
            type="rectangle",
            p1=add(offset, (-0.7, 3.0, -0.7)),
            p2=add(offset, (0.7, 3.0, -0.7)),
            p3=add(offset, (0.7, 3.0, 0.7)),
            material=emitter,
        )
        light_parameters = {
            "position": add(offset, (-0.7, 3.0, -0.7)),
            "edge_u": (1.4, 0.0, 0.0),
            "edge_v": (0.0, 0.0, 1.4),
        }
    elif light_shape == "disk":
        ceiling_light = renderer.object(
            name="ceiling_light",
            type="disk",
            center=add(offset, (0.0, 3.0, 0.0)),
            normal=(0.0, -1.0, 0.0),
            radius=0.8,
            material=emitter,
        )
        light_parameters = {
            "position": add(offset, (0.0, 3.0, 0.0)),
            "normal": (0.0, -1.0, 0.0),
            "radius": 0.8,
        }
    elif light_shape == "sphere":
        ceiling_light = renderer.object(
            name="ceiling_light",
            type="sphere",
            center=add(offset, (0.0, 3.0, 0.0)),
            radius=0.65,
            material=emitter,
        )
        light_parameters = {
            "position": add(offset, (0.0, 3.0, 0.0)),
            "radius": 0.65,
        }
    else:
        raise RuntimeError(f"unsupported finite light shape: {light_shape}")

    if bound:
        light_parameters["object"] = ceiling_light
    renderer.light(
        name="ceiling_light_sample",
        type=light_shape,
        emission=(12.0, 10.0, 8.0),
        **light_parameters,
    )
    return renderer


def decoded_rgba(path: Path) -> bytes:
    with Image.open(path) as image:
        image.load()
        if image.size != (WIDTH, HEIGHT) or image.mode != "RGBA":
            raise RuntimeError(
                f"{path.name} must be {WIDTH}x{HEIGHT} RGBA, got "
                f"{image.size} {image.mode}"
            )
        return image.tobytes()


def render_variant(
    directory: Path,
    name: str,
    *,
    light_shape: str,
    bound: bool,
    device: int,
    spp: int,
    offset,
) -> bytes:
    output = directory / f"{name}.png"
    create_renderer(
        light_shape=light_shape, bound=bound, device=device, offset=offset
    ).render(
        output=output,
        width=WIDTH,
        height=HEIGHT,
        spp=spp,
        depth=MAX_DEPTH,
        seed=SEED,
        denoise=False,
    )
    return decoded_rgba(output)


def run_check(directory: Path, *, device: int, spp: int) -> None:
    for light_shape in ("rectangle", "disk", "sphere"):
        for case_name, offset in (
            ("unit", (0.0, 0.0, 0.0)),
            ("translated", (0.0, 0.0, 1.0e6)),
        ):
            label = f"{light_shape}-{case_name}"
            bound_pixels = render_variant(
                directory,
                f"{label}-bound",
                light_shape=light_shape,
                bound=True,
                device=device,
                spp=spp,
                offset=offset,
            )
            unbound_pixels = render_variant(
                directory,
                f"{label}-unbound",
                light_shape=light_shape,
                bound=False,
                device=device,
                spp=spp,
                offset=offset,
            )

            if bound_pixels != unbound_pixels:
                differences = sum(
                    left != right
                    for left, right in zip(bound_pixels, unbound_pixels)
                )
                raise RuntimeError(
                    f"{label} terminal-depth bound/unbound render mismatch: "
                    f"{differences} decoded RGBA bytes differ"
                )
            if not any(
                value
                for index, value in enumerate(bound_pixels)
                if index % 4 != 3
            ):
                raise RuntimeError(
                    f"{label} terminal-depth comparison rendered a blank image"
                )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="preserve rendered checks in this directory instead of a temporary one",
    )
    parser.add_argument("--device", type=nonnegative_integer, default=0)
    parser.add_argument("--spp", type=positive_integer, default=SPP)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output_dir is not None:
        directory = args.output_dir.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        run_check(directory, device=args.device, spp=args.spp)
    else:
        with tempfile.TemporaryDirectory(
            prefix="spectraldock-integrator-mis-"
        ) as temporary:
            run_check(Path(temporary), device=args.device, spp=args.spp)

    print("terminal-depth bound/unbound MIS comparison passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
