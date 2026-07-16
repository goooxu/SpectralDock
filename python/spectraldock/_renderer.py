"""Public Python scene-construction API for SpectralDock."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import operator
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence, TypeVar

from . import _native


_UNSET = object()
_MISSING = object()
_HandleType = TypeVar("_HandleType")


@dataclass(frozen=True, slots=True)
class TextureHandle:
    """Typed reference to a texture owned by one :class:`Renderer`."""

    name: str
    id: int
    _owner: object = field(repr=False, compare=False)
    _color_space: str = field(default="linear", repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class MaterialHandle:
    """Typed reference to a material owned by one :class:`Renderer`."""

    name: str
    id: int
    _owner: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class MeshHandle:
    """Typed reference to a mesh owned by one :class:`Renderer`."""

    name: str
    id: int
    _owner: object = field(repr=False, compare=False)
    _has_material_mapping: bool = field(default=False, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ObjectHandle:
    """Typed reference to scene geometry owned by one :class:`Renderer`."""

    name: str
    id: int
    _owner: object = field(repr=False, compare=False)


def _name(value: str, label: str = "name") -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _scalar(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise TypeError(f"{label} must be a real number") from error
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _vector(value: Sequence[float], size: int, label: str) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)):
        raise TypeError(f"{label} must be a sequence of {size} numbers")
    try:
        result = tuple(value)
    except TypeError as error:
        raise TypeError(f"{label} must be a sequence of {size} numbers") from error
    if len(result) != size:
        raise ValueError(f"{label} must contain exactly {size} values")
    return tuple(_scalar(component, f"{label}[{index}]")
                 for index, component in enumerate(result))


def _path(value: str | os.PathLike[str], label: str) -> str:
    try:
        result = os.fspath(value)
    except TypeError as error:
        raise TypeError(f"{label} must be a filesystem path") from error
    if not isinstance(result, str):
        raise TypeError(f"{label} must resolve to a text filesystem path")
    return result


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    try:
        result = operator.index(value)
    except TypeError as error:
        raise TypeError(f"{label} must be an integer") from error
    if not minimum <= result <= maximum:
        raise ValueError(f"{label} must be in [{minimum}, {maximum}]")
    return result


def _take(parameters: dict[str, Any], key: str, default: Any = _MISSING) -> Any:
    if key in parameters:
        return parameters.pop(key)
    if default is _MISSING:
        raise TypeError(f"missing required argument: {key!r}")
    return default


def _reject_extra(parameters: Mapping[str, Any], kind: str) -> None:
    if parameters:
        names = ", ".join(sorted(parameters))
        raise TypeError(f"unsupported {kind} argument(s): {names}")


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = output.name
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


class Renderer:
    """Build and render one immutable OptiX scene from ordinary Python code.

    Texture, material, mesh, and object methods return typed handles.  A handle
    can only be consumed by the renderer that created it, preventing accidental
    cross-scene references.  Lights are terminal registrations.  The native
    builder remains the authoritative validation boundary.
    """

    def __init__(self, device: int = 0, *, scene_name: str | None = None) -> None:
        self.device = _integer(device, "device", 0, 2**31 - 1)
        self.scene_name = None if scene_name is None else _name(scene_name, "scene_name")
        self._owner = object()
        self._builder = _native.SceneBuilder()
        self._scene: Any | None = None
        self._exposure = 0.0
        self._clamp_direct = 64.0
        self._clamp_indirect = 16.0

    def _editable(self) -> None:
        if self._scene is not None:
            raise RuntimeError("the scene has already been finalized by render()")

    def _handle(self, value: Any, expected: type[_HandleType], label: str,
                *, optional: bool = False) -> int:
        if value is None and optional:
            return -1
        if not isinstance(value, expected):
            raise TypeError(f"{label} must be a {expected.__name__}")
        if value._owner is not self._owner:
            raise ValueError(f"{label} belongs to a different Renderer")
        return value.id

    def integrator(
        self,
        *,
        direct_light_sampling: str = "importance",
        clamp_direct: float = 64.0,
        clamp_indirect: float = 16.0,
    ) -> None:
        self._editable()
        if direct_light_sampling not in {"uniform", "importance"}:
            raise ValueError("direct_light_sampling must be 'uniform' or 'importance'")
        direct = _scalar(clamp_direct, "clamp_direct")
        indirect = _scalar(clamp_indirect, "clamp_indirect")
        self._builder.set_integrator(direct_light_sampling, direct, indirect)
        self._clamp_direct = direct
        self._clamp_indirect = indirect

    def camera(
        self,
        *,
        look_from: Sequence[float],
        look_at: Sequence[float],
        up: Sequence[float] = (0.0, 1.0, 0.0),
        vfov: float = 45.0,
        aperture: float = 0.0,
        focus_distance: float | None = None,
    ) -> None:
        self._editable()
        origin = _vector(look_from, 3, "look_from")
        target = _vector(look_at, 3, "look_at")
        distance = math.dist(origin, target)
        focus = distance if focus_distance is None else _scalar(
            focus_distance, "focus_distance"
        )
        self._builder.set_camera(
            origin,
            target,
            _vector(up, 3, "up"),
            _scalar(vfov, "vfov"),
            _scalar(aperture, "aperture"),
            focus,
        )

    def background(self, type: str, **parameters: Any) -> None:
        self._editable()
        kind = _name(type, "type")
        exposure = _scalar(_take(parameters, "exposure", 0.0), "exposure")
        if kind == "constant":
            color = _vector(_take(parameters, "color"), 3, "color")
            _reject_extra(parameters, "constant background")
            self._builder.set_constant_background(color, exposure)
        elif kind == "sky":
            bottom = _vector(_take(parameters, "bottom", (1.0, 1.0, 1.0)), 3, "bottom")
            top = _vector(_take(parameters, "top", (0.5, 0.7, 1.0)), 3, "top")
            direction = _vector(
                _take(parameters, "sun_direction", (1.0, 0.0, 0.0)),
                3,
                "sun_direction",
            )
            sun_color = _vector(
                _take(parameters, "sun_color", (0.0, 0.0, 0.0)), 3, "sun_color"
            )
            angle = _scalar(_take(parameters, "sun_cos_angle", 2.0), "sun_cos_angle")
            _reject_extra(parameters, "sky background")
            self._builder.set_sky_background(
                bottom, top, direction, sun_color, angle, exposure
            )
        elif kind == "environment":
            path = _path(_take(parameters, "path"), "path")
            intensity = _scalar(_take(parameters, "intensity", 1.0), "intensity")
            rotation = _scalar(
                _take(parameters, "rotation_degrees", 0.0), "rotation_degrees"
            )
            _reject_extra(parameters, "environment background")
            self._builder.set_environment_background(
                path, intensity, rotation, exposure
            )
        else:
            raise ValueError(f"unsupported background type: {kind!r}")
        self._exposure = exposure

    def texture(self, name: str, type: str, **parameters: Any) -> TextureHandle:
        self._editable()
        resource_name = _name(name)
        kind = _name(type, "type")
        if kind == "constant":
            color = _vector(_take(parameters, "color"), 3, "color")
            _reject_extra(parameters, "constant texture")
            identifier = self._builder.add_constant_texture(resource_name, color)
        elif kind == "image":
            path = _path(_take(parameters, "path"), "path")
            color_space = _take(parameters, "color_space", "srgb")
            if color_space not in {"srgb", "linear"}:
                raise ValueError("color_space must be 'srgb' or 'linear'")
            wrap_u = _take(parameters, "wrap_u", "clamp_to_edge")
            wrap_v = _take(parameters, "wrap_v", "clamp_to_edge")
            wraps = {"clamp_to_edge", "repeat", "mirrored_repeat"}
            if wrap_u not in wraps:
                raise ValueError(
                    "wrap_u must be 'clamp_to_edge', 'repeat', or "
                    "'mirrored_repeat'"
                )
            if wrap_v not in wraps:
                raise ValueError(
                    "wrap_v must be 'clamp_to_edge', 'repeat', or "
                    "'mirrored_repeat'"
                )
            _reject_extra(parameters, "image texture")
            identifier = self._builder.add_image_texture(
                resource_name, path, color_space == "srgb", wrap_u, wrap_v
            )
        else:
            raise ValueError(f"unsupported texture type: {kind!r}")
        handle = TextureHandle(
            resource_name,
            identifier,
            self._owner,
            "linear" if kind == "constant" else color_space,
        )
        return handle

    def material(
        self,
        name: str,
        type: str,
        *,
        texture: TextureHandle | None = None,
        base_color_texture: TextureHandle | None = None,
        base_color: Sequence[float] | object = _UNSET,
        emission: Sequence[float] | object = _UNSET,
        metallic: float | None = None,
        roughness: float | None = None,
        metallic_roughness_texture: TextureHandle | None = None,
        normal_texture: TextureHandle | None = None,
        normal_scale: float | None = None,
        ior: float | None = None,
        absorption: Sequence[float] | object = _UNSET,
    ) -> MaterialHandle:
        self._editable()
        resource_name = _name(name)
        kind = _name(type, "type")
        if kind not in {
            "lambertian", "metal", "dielectric", "emitter", "water", "pbr"
        }:
            raise ValueError(f"unsupported material type: {kind!r}")
        if kind == "pbr":
            if texture is not None:
                raise TypeError("pbr materials use base_color_texture, not texture")
            if emission is not _UNSET:
                raise TypeError("pbr materials do not support emission")
            if ior is not None:
                raise TypeError("pbr materials do not support ior")
            if absorption is not _UNSET:
                raise TypeError("pbr materials do not support absorption")
            color = _vector(
                (1.0, 1.0, 1.0) if base_color is _UNSET else base_color,
                3,
                "base_color",
            )
            metallic_value = 1.0 if metallic is None else _scalar(
                metallic, "metallic"
            )
            roughness_value = 1.0 if roughness is None else _scalar(
                roughness, "roughness"
            )
            normal_scale_value = 1.0 if normal_scale is None else _scalar(
                normal_scale, "normal_scale"
            )
            base_texture_id = self._handle(
                base_color_texture, TextureHandle, "base_color_texture",
                optional=True,
            )
            metallic_roughness_texture_id = self._handle(
                metallic_roughness_texture,
                TextureHandle,
                "metallic_roughness_texture",
                optional=True,
            )
            normal_texture_id = self._handle(
                normal_texture, TextureHandle, "normal_texture", optional=True
            )
            for label, value in (
                ("metallic_roughness_texture", metallic_roughness_texture),
                ("normal_texture", normal_texture),
            ):
                if value is not None and value._color_space != "linear":
                    raise ValueError(f"{label} must use color_space='linear'")
            identifier = self._builder.add_pbr_material(
                resource_name,
                base_texture_id,
                metallic_roughness_texture_id,
                normal_texture_id,
                color,
                metallic_value,
                roughness_value,
                normal_scale_value,
            )
            return MaterialHandle(resource_name, identifier, self._owner)

        for label, value in (
            ("base_color_texture", base_color_texture),
            ("metallic", metallic),
            ("metallic_roughness_texture", metallic_roughness_texture),
            ("normal_texture", normal_texture),
            ("normal_scale", normal_scale),
        ):
            if value is not None:
                raise TypeError(f"{label} is supported only by pbr materials")
        if kind == "water":
            if texture is not None:
                raise TypeError("water materials do not support texture")
            if base_color is not _UNSET:
                raise TypeError("water materials do not support base_color")
            if emission is not _UNSET:
                raise TypeError("water materials do not support emission")
            color = (1.0, 1.0, 1.0)
            emitted = (0.0, 0.0, 0.0)
            absorption_value = _vector(
                (0.35, 0.08, 0.025) if absorption is _UNSET else absorption,
                3,
                "absorption",
            )
            roughness_value = 0.0 if roughness is None else _scalar(roughness, "roughness")
            ior_value = 1.333 if ior is None else _scalar(ior, "ior")
        else:
            if absorption is not _UNSET:
                raise TypeError("absorption is supported only by water materials")
            color = _vector(
                (1.0, 1.0, 1.0) if base_color is _UNSET else base_color,
                3,
                "base_color",
            )
            emitted = _vector(
                (0.0, 0.0, 0.0) if emission is _UNSET else emission,
                3,
                "emission",
            )
            absorption_value = (0.0, 0.0, 0.0)
            default_roughness = 0.0 if kind == "dielectric" else 0.5
            roughness_value = default_roughness if roughness is None else _scalar(
                roughness, "roughness"
            )
            ior_value = 1.5 if ior is None else _scalar(ior, "ior")
        texture_id = self._handle(texture, TextureHandle, "texture", optional=True)
        identifier = self._builder.add_material(
            resource_name,
            kind,
            texture_id,
            color,
            emitted,
            roughness_value,
            ior_value,
            absorption_value,
        )
        handle = MaterialHandle(resource_name, identifier, self._owner)
        return handle

    def mesh(
        self,
        name: str,
        path: str | os.PathLike[str],
        *,
        materials: Mapping[str, MaterialHandle] | None = None,
    ) -> MeshHandle:
        self._editable()
        resource_name = _name(name)
        material_mapping: list[tuple[str, int]] = []
        if materials is not None:
            if not isinstance(materials, Mapping):
                raise TypeError("materials must be a mapping")
            for slot, material in materials.items():
                slot_name = _name(slot, "materials key")
                material_mapping.append(
                    (
                        slot_name,
                        self._handle(
                            material,
                            MaterialHandle,
                            f"materials[{slot_name!r}]",
                        ),
                    )
                )
            material_mapping.sort(key=lambda item: item[0])
        identifier = self._builder.add_mesh(
            resource_name, _path(path, "path"), material_mapping
        )
        handle = MeshHandle(
            resource_name,
            identifier,
            self._owner,
            bool(material_mapping),
        )
        return handle

    def _face_ids(
        self, parameters: dict[str, Any]
    ) -> tuple[int, int, int, float]:
        shared = _take(parameters, "material", _UNSET)
        front = _take(parameters, "front_material", shared)
        back = _take(parameters, "back_material", shared)
        if front is _UNSET:
            front = None
        if back is _UNSET:
            back = None
        alpha = _take(parameters, "alpha_texture", None)
        cutoff = _scalar(_take(parameters, "alpha_cutoff", 0.5), "alpha_cutoff")
        return (
            self._handle(front, MaterialHandle, "front_material", optional=True),
            self._handle(back, MaterialHandle, "back_material", optional=True),
            self._handle(alpha, TextureHandle, "alpha_texture", optional=True),
            cutoff,
        )

    def object(self, name: str, type: str, **parameters: Any) -> ObjectHandle:
        self._editable()
        resource_name = _name(name)
        kind = _name(type, "type")

        if kind == "water_surface":
            if "front_material" in parameters or "back_material" in parameters:
                raise TypeError("water_surface requires one shared material")
            if "alpha_texture" in parameters or "alpha_cutoff" in parameters:
                raise TypeError("water_surface does not support alpha")
            material = _take(parameters, "material")
            material_id = self._handle(material, MaterialHandle, "material")
            center = _vector(_take(parameters, "center"), 3, "center")
            size = _vector(_take(parameters, "size"), 2, "size")
            input_waves = _take(parameters, "waves")
            waves: list[tuple[tuple[float, ...], float, float, float]] = []
            try:
                iterator = iter(input_waves)
            except TypeError as error:
                raise TypeError("waves must be a sequence of mappings") from error
            for index, wave in enumerate(iterator):
                if not isinstance(wave, Mapping):
                    raise TypeError(f"waves[{index}] must be a mapping")
                wave_values = dict(wave)
                waves.append(
                    (
                        _vector(_take(wave_values, "direction"), 2,
                                f"waves[{index}].direction"),
                        _scalar(_take(wave_values, "amplitude"),
                                f"waves[{index}].amplitude"),
                        _scalar(_take(wave_values, "wavelength"),
                                f"waves[{index}].wavelength"),
                        _scalar(_take(wave_values, "phase_radians"),
                                f"waves[{index}].phase_radians"),
                    )
                )
                _reject_extra(wave_values, f"waves[{index}]")
            _reject_extra(parameters, "water_surface")
            identifier = self._builder.add_water_surface(
                resource_name, center, size, material_id, waves
            )
        else:
            if kind == "mesh":
                mesh = _take(parameters, "mesh")
                mesh_id = self._handle(mesh, MeshHandle, "mesh")
                if mesh._has_material_mapping:
                    forbidden = tuple(
                        key
                        for key in ("material", "front_material", "back_material")
                        if key in parameters
                    )
                    if forbidden:
                        raise TypeError(
                            "material-mapped mesh objects do not accept "
                            + ", ".join(forbidden)
                        )
                    front = -1
                    back = -1
                    alpha_handle = _take(parameters, "alpha_texture", None)
                    alpha = self._handle(
                        alpha_handle,
                        TextureHandle,
                        "alpha_texture",
                        optional=True,
                    )
                    cutoff = _scalar(
                        _take(parameters, "alpha_cutoff", 0.5), "alpha_cutoff"
                    )
                else:
                    front, back, alpha, cutoff = self._face_ids(parameters)
            else:
                front, back, alpha, cutoff = self._face_ids(parameters)
            if kind == "sphere":
                values = (
                    resource_name,
                    _vector(_take(parameters, "center"), 3, "center"),
                    _scalar(_take(parameters, "radius"), "radius"),
                    front,
                    back,
                    alpha,
                    cutoff,
                )
                _reject_extra(parameters, "sphere")
                identifier = self._builder.add_sphere(*values)
            elif kind == "rectangle":
                values = (
                    resource_name,
                    _vector(_take(parameters, "p1"), 3, "p1"),
                    _vector(_take(parameters, "p2"), 3, "p2"),
                    _vector(_take(parameters, "p3"), 3, "p3"),
                    front,
                    back,
                    alpha,
                    cutoff,
                )
                _reject_extra(parameters, "rectangle")
                identifier = self._builder.add_rectangle(*values)
            elif kind == "disk":
                values = (
                    resource_name,
                    _vector(_take(parameters, "center"), 3, "center"),
                    _vector(_take(parameters, "normal"), 3, "normal"),
                    _scalar(_take(parameters, "radius"), "radius"),
                    front,
                    back,
                    alpha,
                    cutoff,
                )
                _reject_extra(parameters, "disk")
                identifier = self._builder.add_disk(*values)
            elif kind == "cylinder":
                values = (
                    resource_name,
                    _vector(_take(parameters, "base"), 3, "base"),
                    _vector(_take(parameters, "axis"), 3, "axis"),
                    _scalar(_take(parameters, "height"), "height"),
                    _scalar(_take(parameters, "radius"), "radius"),
                    front,
                    back,
                    alpha,
                    cutoff,
                )
                _reject_extra(parameters, "cylinder")
                identifier = self._builder.add_cylinder(*values)
            elif kind == "parabola":
                values = (
                    resource_name,
                    _vector(_take(parameters, "origin"), 3, "origin"),
                    _vector(_take(parameters, "normal"), 3, "normal"),
                    _vector(_take(parameters, "focus"), 3, "focus"),
                    _vector(_take(parameters, "clip_min"), 3, "clip_min"),
                    _vector(_take(parameters, "clip_max"), 3, "clip_max"),
                    front,
                    back,
                    alpha,
                    cutoff,
                )
                _reject_extra(parameters, "parabola")
                identifier = self._builder.add_parabola(*values)
            elif kind == "mesh":
                translate = _vector(
                    _take(parameters, "translate", (0.0, 0.0, 0.0)),
                    3,
                    "translate",
                )
                rotate = _vector(
                    _take(parameters, "rotate_degrees", (0.0, 0.0, 0.0)),
                    3,
                    "rotate_degrees",
                )
                scale = _vector(
                    _take(parameters, "scale", (1.0, 1.0, 1.0)), 3, "scale"
                )
                _reject_extra(parameters, "mesh")
                identifier = self._builder.add_mesh_instance(
                    resource_name, mesh_id, translate, rotate, scale,
                    front, back, alpha, cutoff
                )
            else:
                raise ValueError(f"unsupported object type: {kind!r}")

        handle = ObjectHandle(resource_name, identifier, self._owner)
        return handle

    def light(self, name: str, type: str, **parameters: Any) -> None:
        self._editable()
        resource_name = _name(name)
        kind = _name(type, "type")
        linked = _take(parameters, "object", None)
        object_id = self._handle(linked, ObjectHandle, "object", optional=True)
        if kind == "sphere":
            values = (
                resource_name,
                _vector(_take(parameters, "position"), 3, "position"),
                _scalar(_take(parameters, "radius"), "radius"),
                _vector(_take(parameters, "emission"), 3, "emission"),
                object_id,
            )
        elif kind == "rectangle":
            values = (
                resource_name,
                _vector(_take(parameters, "position"), 3, "position"),
                _vector(_take(parameters, "edge_u"), 3, "edge_u"),
                _vector(_take(parameters, "edge_v"), 3, "edge_v"),
                _vector(_take(parameters, "emission"), 3, "emission"),
                object_id,
            )
        elif kind == "disk":
            values = (
                resource_name,
                _vector(_take(parameters, "position"), 3, "position"),
                _vector(_take(parameters, "normal"), 3, "normal"),
                _scalar(_take(parameters, "radius"), "radius"),
                _vector(_take(parameters, "emission"), 3, "emission"),
                object_id,
            )
        elif kind == "flame":
            if linked is not None:
                raise TypeError("flame lights cannot be bound to objects")
            values = (
                resource_name,
                _vector(_take(parameters, "position"), 3, "position"),
                _vector(_take(parameters, "axis"), 3, "axis"),
                _scalar(_take(parameters, "height"), "height"),
                _scalar(_take(parameters, "radius_start"), "radius_start"),
                _scalar(_take(parameters, "radius_end"), "radius_end"),
                _vector(_take(parameters, "emission_start"), 3, "emission_start"),
                _vector(_take(parameters, "emission_end"), 3, "emission_end"),
                _scalar(_take(parameters, "extinction"), "extinction"),
                _scalar(_take(parameters, "density_scale", 1.0), "density_scale"),
                _scalar(_take(parameters, "turbulence", 0.35), "turbulence"),
                _scalar(_take(parameters, "noise_scale", 2.0), "noise_scale"),
                _integer(_take(parameters, "seed", 0), "seed", 0, 2**32 - 1),
            )
        elif kind == "point":
            if linked is not None:
                raise TypeError("point lights cannot be bound to objects")
            values = (
                resource_name,
                _vector(_take(parameters, "position"), 3, "position"),
                _vector(_take(parameters, "intensity"), 3, "intensity"),
            )
        elif kind == "directional":
            if linked is not None:
                raise TypeError("directional lights cannot be bound to objects")
            values = (
                resource_name,
                _vector(_take(parameters, "direction"), 3, "direction"),
                _vector(_take(parameters, "irradiance"), 3, "irradiance"),
            )
        else:
            raise ValueError(f"unsupported light type: {kind!r}")
        _reject_extra(parameters, f"{kind} light")
        add_light = {
            "sphere": self._builder.add_sphere_light,
            "rectangle": self._builder.add_rectangle_light,
            "disk": self._builder.add_disk_light,
            "flame": self._builder.add_flame_light,
            "point": self._builder.add_point_light,
            "directional": self._builder.add_directional_light,
        }[kind]
        add_light(*values)

    def render(
        self,
        *,
        output: str | os.PathLike[str],
        width: int = 1024,
        height: int = 1024,
        spp: int = 256,
        depth: int = 12,
        seed: int = 1,
        denoise: bool = False,
        stats_output: str | os.PathLike[str] | None = None,
        linear_output: str | os.PathLike[str] | None = None,
        clamp_direct: float | None = None,
        clamp_indirect: float | None = None,
        validation: bool | None = None,
    ) -> dict[str, Any]:
        width_value = _integer(width, "width", 1, 16384)
        height_value = _integer(height, "height", 1, 16384)
        spp_value = _integer(spp, "spp", 1, 1_000_000)
        depth_value = _integer(depth, "depth", 1, 64)
        seed_value = _integer(seed, "seed", 0, 2**32 - 1)
        if not isinstance(denoise, bool):
            raise TypeError("denoise must be a bool")
        if validation is not None and not isinstance(validation, bool):
            raise TypeError("validation must be a bool or None")

        output_path = Path(_path(output, "output"))
        linear_path = None if linear_output is None else Path(
            _path(linear_output, "linear_output")
        )
        if output_path.suffix != ".png":
            raise ValueError("output must use the .png extension")
        if linear_path is not None and linear_path.suffix != ".pfm":
            raise ValueError("linear_output must use the .pfm extension")
        direct_clamp = self._clamp_direct if clamp_direct is None else _scalar(
            clamp_direct, "clamp_direct"
        )
        indirect_clamp = self._clamp_indirect if clamp_indirect is None else _scalar(
            clamp_indirect, "clamp_indirect"
        )
        if direct_clamp < 0.0 or indirect_clamp < 0.0:
            raise ValueError("clamp_direct and clamp_indirect must be non-negative")
        if self._scene is None:
            self._scene = self._builder.finish()
        native_stats = _native.render_to_files(
            self._scene,
            os.fspath(output_path),
            self.device,
            width_value,
            height_value,
            spp_value,
            depth_value,
            seed_value,
            self._exposure,
            direct_clamp,
            indirect_clamp,
            denoise,
            bool(_native.validation_default) if validation is None else validation,
            None if linear_path is None else os.fspath(linear_path),
        )
        stats: dict[str, Any] = {
            "scene": self.scene_name or output_path.stem,
            "output": os.fspath(output_path),
        }
        stats.update(dict(native_stats))
        if linear_path is not None:
            stats["linear_output"] = os.fspath(linear_path)
        destination = output_path.with_suffix(".stats.json") if stats_output is None else Path(
            _path(stats_output, "stats_output")
        )
        _write_json_atomic(destination, stats)
        return stats


__all__ = [
    "MaterialHandle",
    "MeshHandle",
    "ObjectHandle",
    "Renderer",
    "TextureHandle",
]
