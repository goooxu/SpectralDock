"""Shared helpers for AVIF GPU-contract scripts.

The production API intentionally exposes no linear image file format.  GPU
contracts request an in-memory capture through the private render test hook and
exercise the persisted HDR AVIF independently.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

from spectraldock import _native


class RgbaImage:
    """Minimal decoded-image view used by standalone GPU checks."""

    mode = "RGBA"

    def __init__(self, width: int, height: int, rgba: bytes):
        self.width = width
        self.height = height
        self.size = (width, height)
        self._rgba = rgba

    def copy(self) -> "RgbaImage":
        return RgbaImage(self.width, self.height, self._rgba)

    def tobytes(self) -> bytes:
        return self._rgba

    def getpixel(self, coordinate: tuple[int, int]) -> tuple[int, int, int, int]:
        x, y = coordinate
        offset = (y * self.width + x) * 4
        return tuple(self._rgba[offset : offset + 4])

    def getdata(self):
        return (
            tuple(self._rgba[offset : offset + 4])
            for offset in range(0, len(self._rgba), 4)
        )

    def crop(self, box: tuple[int, int, int, int]) -> "RgbaImage":
        left, top, right, bottom = box
        pixels = bytearray()
        for y in range(top, bottom):
            start = (y * self.width + left) * 4
            end = (y * self.width + right) * 4
            pixels.extend(self._rgba[start:end])
        return RgbaImage(right - left, bottom - top, bytes(pixels))


class FloatRgbImage:
    """Top-to-bottom RGB float image returned only by the render test hook."""

    def __init__(self, width: int, height: int, values: tuple[float, ...]):
        self.width = width
        self.height = height
        self.size = (width, height)
        self._values = values

    def samples(self) -> tuple[float, ...]:
        return self._values

    def getpixel(self, coordinate: tuple[int, int]):
        x, y = coordinate
        offset = (y * self.width + x) * 3
        return (*self._values[offset : offset + 3], 1.0)

    def getdata(self):
        return (
            (*self._values[offset : offset + 3], 1.0)
            for offset in range(0, len(self._values), 3)
        )

    def crop(self, box: tuple[int, int, int, int]) -> "FloatRgbImage":
        left, top, right, bottom = box
        values = []
        for y in range(top, bottom):
            start = (y * self.width + left) * 3
            end = (y * self.width + right) * 3
            values.extend(self._values[start:end])
        return FloatRgbImage(right - left, bottom - top, tuple(values))


def read_avif_rgba(path: Path) -> tuple[int, int, bytes, dict]:
    decoded = _native.read_avif(os.fspath(path))
    if isinstance(decoded, dict):
        width = decoded["width"]
        height = decoded["height"]
        rgba = decoded.get("rgba", decoded.get("pixels"))
        metadata = decoded.get("metadata", decoded)
    else:
        if len(decoded) == 3:
            width, height, rgba = decoded
            metadata = {}
        else:
            width, height, rgba, metadata = decoded
    rgba = bytes(rgba)
    if len(rgba) != int(width) * int(height) * 4:
        raise RuntimeError(
            f"{path.name}: decoded RGBA payload has {len(rgba)} bytes, "
            f"expected {int(width) * int(height) * 4}"
        )
    return int(width), int(height), rgba, dict(metadata)


def assert_avif_dimensions(path: Path, width: int, height: int) -> None:
    actual_width, actual_height, _, metadata = read_avif_rgba(path)
    if (actual_width, actual_height) != (width, height):
        raise RuntimeError(
            f"{path.name}: unexpected AVIF dimensions "
            f"{actual_width}x{actual_height}, expected {width}x{height}"
        )
    expected = {
        "bit_depth": 10,
        "yuv_format": "4:4:4",
        "full_range": True,
        "cicp": (9, 16, 9),
        "premultiplied": False,
        "animated": False,
        "has_alpha": False,
    }
    for key, value in expected.items():
        actual = metadata.get(key)
        if key == "cicp" and actual is not None:
            actual = tuple(actual)
        if actual != value:
            raise RuntimeError(
                f"{path.name}: unexpected HDR AVIF {key}={actual!r}, "
                f"expected {value!r}"
            )
    for key in ("max_cll", "max_pall"):
        value = metadata.get(key)
        if not isinstance(value, int) or not 1 <= value <= 1000:
            raise RuntimeError(
                f"{path.name}: invalid HDR AVIF {key}={value!r}"
            )


def read_avif_image(path: Path) -> RgbaImage:
    width, height, rgba, _ = read_avif_rgba(path)
    return RgbaImage(width, height, rgba)


def write_texture_avif(
    path: Path,
    width: int,
    height: int,
    rgba: bytes | bytearray,
    *,
    srgb: bool,
) -> None:
    _native.write_texture_avif(
        os.fspath(path), width, height, bytes(rgba), srgb
    )


def captured_linear_rgb(
    stats: dict, width: int, height: int
) -> tuple[tuple[tuple[float, float, float], ...], tuple[float, ...]]:
    try:
        values = tuple(stats.pop("_test_linear_rgb"))
    except KeyError as error:
        raise RuntimeError("render did not return the requested linear test capture") from error
    expected = width * height * 3
    if len(values) != expected:
        raise RuntimeError(
            f"linear test capture has {len(values)} values, expected {expected}"
        )
    if any(not math.isfinite(value) for value in values):
        raise RuntimeError("linear test capture contains a non-finite value")
    render = stats.get("render", {})
    if render.get("width", width) != width or render.get("height", height) != height:
        raise RuntimeError("linear test capture dimensions disagree with render stats")
    pixels = tuple(zip(values[0::3], values[1::3], values[2::3]))
    return pixels, values


def captured_linear_image(stats: dict, width: int, height: int) -> FloatRgbImage:
    _, values = captured_linear_rgb(stats, width, height)
    return FloatRgbImage(width, height, values)
