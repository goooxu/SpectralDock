#!/usr/bin/env python3
"""Compare terminal-depth MIS for bound and unbound versions of one light."""

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


def create_renderer(*, bound: bool, device: int) -> Renderer:
    """Build the smoke fixture, optionally binding its light to emitter geometry."""

    renderer = Renderer(
        device=device,
        scene_name="integrator-mis-bound" if bound else "integrator-mis-unbound",
    )
    renderer.integrator(
        direct_light_sampling="importance", clamp_direct=0.0, clamp_indirect=0.0
    )
    renderer.camera(
        look_from=(3.0, 2.0, 5.0),
        look_at=(0.0, 0.5, 0.0),
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
        p1=(-3.0, 0.0, 2.0),
        p2=(-3.0, 0.0, -3.0),
        p3=(3.0, 0.0, -3.0),
        material=white,
    )
    renderer.object(
        name="red_ball",
        type="sphere",
        center=(-0.7, 0.7, 0.0),
        radius=0.7,
        material=red,
    )
    renderer.object(
        name="mirror_ball",
        type="sphere",
        center=(0.9, 0.5, -0.4),
        radius=0.5,
        material=mirror,
    )
    ceiling_light = renderer.object(
        name="ceiling_light",
        type="rectangle",
        p1=(-0.7, 3.0, -0.7),
        p2=(0.7, 3.0, -0.7),
        p3=(0.7, 3.0, 0.7),
        material=emitter,
    )

    if bound:
        renderer.light(
            name="ceiling_light_sample",
            type="rectangle",
            object=ceiling_light,
            position=(-0.7, 3.0, -0.7),
            edge_u=(1.4, 0.0, 0.0),
            edge_v=(0.0, 0.0, 1.4),
            emission=(12.0, 10.0, 8.0),
        )
    else:
        renderer.light(
            name="ceiling_light_sample",
            type="rectangle",
            position=(-0.7, 3.0, -0.7),
            edge_u=(1.4, 0.0, 0.0),
            edge_v=(0.0, 0.0, 1.4),
            emission=(12.0, 10.0, 8.0),
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
    directory: Path, name: str, *, bound: bool, device: int, spp: int
) -> bytes:
    output = directory / f"{name}.png"
    create_renderer(bound=bound, device=device).render(
        output=output,
        width=WIDTH,
        height=HEIGHT,
        spp=spp,
        max_depth=MAX_DEPTH,
        seed=SEED,
        denoise=False,
    )
    return decoded_rgba(output)


def run_check(directory: Path, *, device: int, spp: int) -> None:
    bound_pixels = render_variant(
        directory, "bound", bound=True, device=device, spp=spp
    )
    unbound_pixels = render_variant(
        directory, "unbound", bound=False, device=device, spp=spp
    )

    if bound_pixels != unbound_pixels:
        differences = sum(
            left != right for left, right in zip(bound_pixels, unbound_pixels)
        )
        raise RuntimeError(
            "terminal-depth bound/unbound render mismatch: "
            f"{differences} decoded RGBA bytes differ"
        )
    if not any(
        value for index, value in enumerate(bound_pixels) if index % 4 != 3
    ):
        raise RuntimeError("terminal-depth comparison rendered a blank image")


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
