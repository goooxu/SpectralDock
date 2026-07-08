#!/usr/bin/env python3
"""Compare terminal-depth MIS for bound and unbound versions of one light."""

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image


def render(renderer: Path, scene: Path, output: Path) -> None:
    subprocess.run(
        [
            str(renderer),
            "--scene",
            str(scene),
            "--output",
            str(output),
            "--width",
            "64",
            "--height",
            "64",
            "--spp",
            "4",
            "--max-depth",
            "1",
            "--seed",
            "1",
            "--no-denoise",
        ],
        check=True,
    )


def decoded_rgba(path: Path) -> bytes:
    with Image.open(path) as image:
        image.load()
        if image.size != (64, 64) or image.mode != "RGBA":
            raise RuntimeError(
                f"{path.name} must be 64x64 RGBA, got "
                f"{image.size} {image.mode}"
            )
        return image.tobytes()


def main() -> int:
    if len(sys.argv) != 3:
        raise RuntimeError(
            "usage: check_integrator_mis.py RENDERER SMOKE_SCENE"
        )
    renderer = Path(sys.argv[1]).resolve()
    source_scene = Path(sys.argv[2]).resolve()
    if not renderer.is_file():
        raise RuntimeError(f"renderer not found: {renderer}")

    bound = json.loads(source_scene.read_text(encoding="utf-8"))
    unbound = copy.deepcopy(bound)
    removed = 0
    for light in unbound.get("lights", []):
        if "object" in light:
            del light["object"]
            removed += 1
    if removed == 0:
        raise RuntimeError("smoke scene has no light object binding to remove")

    with tempfile.TemporaryDirectory(prefix="spectraldock-integrator-mis-") as tmp:
        directory = Path(tmp)
        bound_scene = directory / "bound.json"
        unbound_scene = directory / "unbound.json"
        bound_scene.write_text(
            json.dumps(bound, indent=2) + "\n", encoding="utf-8"
        )
        unbound_scene.write_text(
            json.dumps(unbound, indent=2) + "\n", encoding="utf-8"
        )
        bound_image = directory / "bound.png"
        unbound_image = directory / "unbound.png"
        render(renderer, bound_scene, bound_image)
        render(renderer, unbound_scene, unbound_image)
        bound_pixels = decoded_rgba(bound_image)
        unbound_pixels = decoded_rgba(unbound_image)

        if bound_pixels != unbound_pixels:
            differences = sum(
                left != right
                for left, right in zip(bound_pixels, unbound_pixels)
            )
            raise RuntimeError(
                "terminal-depth bound/unbound render mismatch: "
                f"{differences} decoded RGBA bytes differ"
            )
        if not any(
            value
            for index, value in enumerate(bound_pixels)
            if index % 4 != 3
        ):
            raise RuntimeError("terminal-depth comparison rendered a blank image")

    print("terminal-depth bound/unbound MIS comparison passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        json.JSONDecodeError,
        OSError,
        RuntimeError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
