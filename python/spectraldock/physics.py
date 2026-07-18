"""GPU-only PhysX scene construction for SpectralDock.

The renderer and PhysX intentionally live in different processes: the renderer is
built with CUDA 13.x, while the supported PhysX SDK is built with CUDA 12.8.  A
small, versioned binary protocol keeps those runtimes out of one address space.
That protocol is private IPC, exists only under a temporary directory, and is
neither a scene format nor a public API.  Persistent metadata is JSON.  There is
deliberately no CPU fallback; failure to create a PhysX CUDA scene is a hard
error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import tempfile
from typing import Any, Callable, Iterable, Sequence


_REQUEST_MAGIC = b"SDPXRQ2\0"
_RESULT_MAGIC = b"SDPXRS2\0"
_PROTOCOL_VERSION = 2
_MAX_ITEMS = 1_000_000
_PHYSX_COMMIT = "fc1018a3745664a1db2b95ce03fb5e91eb585f2e"


class PhysicsError(RuntimeError):
    """Raised when a PhysX request is invalid or GPU simulation fails."""


class _RejectedState(PhysicsError):
    pass


def _finite_scalar(value: float, label: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    return value


def _positive(value: float, label: str) -> float:
    value = _finite_scalar(value, label)
    if value <= 0.0:
        raise ValueError(f"{label} must be greater than zero")
    return value


def _vec(value: Sequence[float], size: int, label: str) -> tuple[float, ...]:
    if len(value) != size:
        raise ValueError(f"{label} must contain exactly {size} values")
    return tuple(_finite_scalar(component, f"{label}[{index}]")
                 for index, component in enumerate(value))


def _quat(value: Sequence[float], label: str) -> tuple[float, float, float, float]:
    quaternion = _vec(value, 4, label)
    length = math.sqrt(sum(component * component for component in quaternion))
    if length <= 1.0e-12:
        raise ValueError(f"{label} must not be the zero quaternion")
    return tuple(component / length for component in quaternion)  # type: ignore[return-value]


def _name(value: str, label: str = "name") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    encoded = value.encode("utf-8")
    if len(encoded) > 1_048_576:
        raise ValueError(f"{label} is too long")
    return value


def _rounded(value: float) -> float:
    result = round(float(value), 6)
    return 0.0 if abs(result) < 0.5e-6 else result


class _Writer:
    def __init__(self) -> None:
        self.data = bytearray()

    def raw(self, value: bytes) -> None:
        self.data.extend(value)

    def u8(self, value: int) -> None:
        self.data.extend(struct.pack("<B", value))

    def u32(self, value: int) -> None:
        self.data.extend(struct.pack("<I", value))

    def i32(self, value: int) -> None:
        self.data.extend(struct.pack("<i", value))

    def u64(self, value: int) -> None:
        self.data.extend(struct.pack("<Q", value))

    def f32(self, value: float) -> None:
        self.data.extend(struct.pack("<f", value))

    def floats(self, values: Iterable[float]) -> None:
        for value in values:
            self.f32(value)

    def string(self, value: str) -> None:
        encoded = value.encode("utf-8")
        self.u32(len(encoded))
        self.raw(encoded)


class _Reader:
    def __init__(self, data: bytes) -> None:
        self._data = memoryview(data)
        self._offset = 0

    def _take(self, size: int) -> memoryview:
        end = self._offset + size
        if size < 0 or end > len(self._data):
            raise PhysicsError("truncated PhysX result")
        value = self._data[self._offset:end]
        self._offset = end
        return value

    def raw(self, size: int) -> bytes:
        return bytes(self._take(size))

    def _unpack(self, format_string: str) -> Any:
        size = struct.calcsize(format_string)
        return struct.unpack(format_string, self._take(size))[0]

    def u8(self) -> int:
        return int(self._unpack("<B"))

    def boolean(self, label: str) -> bool:
        value = self.u8()
        if value not in (0, 1):
            raise PhysicsError(f"PhysX result {label} is not a protocol boolean")
        return bool(value)

    def u32(self) -> int:
        return int(self._unpack("<I"))

    def i32(self) -> int:
        return int(self._unpack("<i"))

    def u64(self) -> int:
        return int(self._unpack("<Q"))

    def f32(self) -> float:
        value = float(self._unpack("<f"))
        if not math.isfinite(value):
            raise PhysicsError("PhysX result contains a non-finite float")
        return value

    def floats(self, count: int) -> tuple[float, ...]:
        return tuple(self.f32() for _ in range(count))

    def string(self) -> str:
        size = self.u32()
        if size > 1_048_576:
            raise PhysicsError("PhysX result string exceeds the protocol limit")
        try:
            return self.raw(size).decode("utf-8")
        except UnicodeDecodeError as error:
            raise PhysicsError("PhysX result contains invalid UTF-8") from error

    def count(self, label: str) -> int:
        value = self.u32()
        if value > _MAX_ITEMS:
            raise PhysicsError(f"PhysX result {label} count exceeds the protocol limit")
        return value

    def finish(self) -> None:
        if self._offset != len(self._data):
            raise PhysicsError("PhysX result has trailing bytes")


@dataclass(frozen=True)
class PhysicsMaterial:
    """A PhysX contact material owned by one :class:`PhysicsWorld`."""

    name: str
    static_friction: float
    dynamic_friction: float
    restitution: float
    _world_token: object = field(repr=False, compare=False)
    _index: int = field(repr=False, compare=False)


@dataclass(frozen=True)
class _Shape:
    kind: int
    material: PhysicsMaterial
    local_position: tuple[float, float, float]
    local_rotation: tuple[float, float, float, float]
    values: tuple[float, ...]


@dataclass(frozen=True)
class _Action:
    delta_velocity: tuple[float, float, float]
    position: tuple[float, float, float]


@dataclass(frozen=True)
class _Attachment:
    kind: int
    name: str
    values: tuple[float, ...]
    material: Any
    mesh: Any | None = None


@dataclass(frozen=True)
class _StaticActor:
    kind: int
    name: str
    material: PhysicsMaterial
    position: tuple[float, float, float]
    rotation: tuple[float, float, float, float]
    values: tuple[float, ...]


class RigidBody:
    """A dynamic rigid body and its renderer-space attachments."""

    def __init__(
        self,
        world: "PhysicsWorld",
        name: str,
        category: str,
        position: Sequence[float],
        rotation: Sequence[float],
        density: float,
        linear_damping: float,
        angular_damping: float,
        sleep_threshold: float,
        solver_iterations: tuple[int, int],
    ) -> None:
        self._world = world
        self.name = _name(name)
        self.category = _name(category, "category")
        self.position = _vec(position, 3, "position")
        self.rotation = _quat(rotation, "rotation")
        self.density = _positive(density, "density")
        self.linear_damping = _finite_scalar(linear_damping, "linear_damping")
        self.angular_damping = _finite_scalar(angular_damping, "angular_damping")
        self.sleep_threshold = _finite_scalar(sleep_threshold, "sleep_threshold")
        if self.linear_damping < 0.0 or self.angular_damping < 0.0:
            raise ValueError("damping must be non-negative")
        if self.sleep_threshold < 0.0:
            raise ValueError("sleep_threshold must be non-negative")
        if len(solver_iterations) != 2:
            raise ValueError("solver_iterations must contain position and velocity counts")
        self.solver_iterations = (int(solver_iterations[0]), int(solver_iterations[1]))
        if not 1 <= self.solver_iterations[0] <= 255 or not 1 <= self.solver_iterations[1] <= 255:
            raise ValueError("solver iteration counts must be in [1, 255]")
        self.initial_linear_velocity = (0.0, 0.0, 0.0)
        self.initial_angular_velocity = (0.0, 0.0, 0.0)
        self._shapes: list[_Shape] = []
        self._actions: list[_Action] = []
        self._attachments: list[_Attachment] = []

    def _material(self, material: PhysicsMaterial) -> PhysicsMaterial:
        self._world._check_material(material)
        return material

    def box(
        self,
        half_extents: Sequence[float],
        material: PhysicsMaterial,
        *,
        local_position: Sequence[float] = (0.0, 0.0, 0.0),
        local_rotation: Sequence[float] = (0.0, 0.0, 0.0, 1.0),
    ) -> "RigidBody":
        extents = tuple(_positive(value, f"half_extents[{index}]")
                        for index, value in enumerate(_vec(half_extents, 3, "half_extents")))
        self._shapes.append(_Shape(1, self._material(material),
                                   _vec(local_position, 3, "local_position"),
                                   _quat(local_rotation, "local_rotation"), extents))
        return self

    def sphere(
        self,
        radius: float,
        material: PhysicsMaterial,
        *,
        local_position: Sequence[float] = (0.0, 0.0, 0.0),
        local_rotation: Sequence[float] = (0.0, 0.0, 0.0, 1.0),
    ) -> "RigidBody":
        self._shapes.append(_Shape(2, self._material(material),
                                   _vec(local_position, 3, "local_position"),
                                   _quat(local_rotation, "local_rotation"),
                                   (_positive(radius, "radius"),)))
        return self

    def capsule(
        self,
        radius: float,
        half_height: float,
        material: PhysicsMaterial,
        *,
        local_position: Sequence[float] = (0.0, 0.0, 0.0),
        local_rotation: Sequence[float] = (0.0, 0.0, 0.0, 1.0),
    ) -> "RigidBody":
        self._shapes.append(_Shape(3, self._material(material),
                                   _vec(local_position, 3, "local_position"),
                                   _quat(local_rotation, "local_rotation"),
                                   (_positive(radius, "radius"),
                                    _positive(half_height, "half_height"))))
        return self

    def linear_velocity(self, value: Sequence[float]) -> "RigidBody":
        self.initial_linear_velocity = _vec(value, 3, "linear_velocity")
        return self

    def angular_velocity(self, value: Sequence[float]) -> "RigidBody":
        self.initial_angular_velocity = _vec(value, 3, "angular_velocity")
        return self

    def mass_scaled_impulse_at_position(
        self,
        delta_velocity: Sequence[float],
        position: Sequence[float],
    ) -> "RigidBody":
        self._actions.append(_Action(_vec(delta_velocity, 3, "delta_velocity"),
                                     _vec(position, 3, "position")))
        return self

    def _attach(
        self,
        kind: int,
        name: str,
        values: Sequence[float],
        material: Any,
        mesh: Any | None = None,
    ) -> "RigidBody":
        if material is None:
            raise ValueError("a renderer material handle is required")
        self._attachments.append(_Attachment(kind, _name(name),
                                             tuple(float(value) for value in values),
                                             material, mesh))
        return self

    def attach_sphere(self, name: str, center: Sequence[float], radius: float,
                      material: Any) -> "RigidBody":
        return self._attach(1, name, (*_vec(center, 3, "center"),
                                     _positive(radius, "radius")), material)

    def attach_rectangle(self, name: str, p1: Sequence[float], p2: Sequence[float],
                         p3: Sequence[float], material: Any) -> "RigidBody":
        return self._attach(2, name, (*_vec(p1, 3, "p1"), *_vec(p2, 3, "p2"),
                                     *_vec(p3, 3, "p3")), material)

    def attach_cylinder(self, name: str, base: Sequence[float], axis: Sequence[float],
                        height: float, radius: float, material: Any) -> "RigidBody":
        return self._attach(3, name, (*_vec(base, 3, "base"), *_vec(axis, 3, "axis"),
                                     _positive(height, "height"),
                                     _positive(radius, "radius")), material)

    def attach_disk(self, name: str, center: Sequence[float], normal: Sequence[float],
                    radius: float, material: Any) -> "RigidBody":
        return self._attach(4, name, (*_vec(center, 3, "center"),
                                     *_vec(normal, 3, "normal"),
                                     _positive(radius, "radius")), material)

    def attach_mesh(
        self,
        name: str,
        mesh: Any,
        *,
        local_translate: Sequence[float] = (0.0, 0.0, 0.0),
        local_rotation: Sequence[float] = (0.0, 0.0, 0.0, 1.0),
        scale: Sequence[float] = (1.0, 1.0, 1.0),
        material: Any,
    ) -> "RigidBody":
        if mesh is None:
            raise ValueError("a renderer mesh handle is required")
        scale_value = tuple(_positive(value, f"scale[{index}]")
                            for index, value in enumerate(_vec(scale, 3, "scale")))
        values = (*_vec(local_translate, 3, "local_translate"),
                  *_quat(local_rotation, "local_rotation"), *scale_value)
        return self._attach(5, name, values, material, mesh)


@dataclass(frozen=True)
class BodyState:
    name: str
    category: str
    initial_position: tuple[float, float, float]
    initial_rotation: tuple[float, float, float, float]
    position: tuple[float, float, float]
    rotation: tuple[float, float, float, float]
    linear_velocity: tuple[float, float, float]
    angular_velocity: tuple[float, float, float]
    sleeping: bool


@dataclass(frozen=True)
class _BakedAttachment:
    index: int
    body_index: int
    kind: int
    values: tuple[float, ...]


@dataclass(frozen=True)
class _GpuPipelineStatistics:
    samples: int
    heap_bytes: int
    broad_phase_bytes: int
    narrow_phase_bytes: int
    solver_bytes: int
    simulation_bytes: int


class PhysicsResult:
    """Validated GPU PhysX output that can be applied to one renderer."""

    def __init__(
        self,
        *,
        scene_name: str,
        seed: int,
        device: int,
        device_name: str,
        backend: str,
        physx_version: int,
        physx_commit: str,
        cuda_runtime_version: int,
        cuda_context_valid: bool,
        gpu_dynamics: bool,
        gpu_broad_phase: bool,
        tgs_solver: bool,
        pcm: bool,
        stabilization: bool,
        cpu_fallback: bool,
        enhanced_determinism: bool,
        gpu_statistics: _GpuPipelineStatistics,
        fixed_dt: float,
        steps: int,
        gravity: tuple[float, float, float],
        bodies: tuple[BodyState, ...],
        attachments: tuple[_BakedAttachment, ...],
        source_attachments: tuple[_Attachment, ...],
    ) -> None:
        self.scene_name = scene_name
        self.seed = seed
        self.device = device
        self.device_name = device_name
        self.backend = backend
        self.physx_version = physx_version
        self.physx_commit = physx_commit
        self.cuda_runtime_version = cuda_runtime_version
        self.cuda_context_valid = bool(cuda_context_valid)
        self.gpu_dynamics = bool(gpu_dynamics)
        self.gpu_broad_phase = bool(gpu_broad_phase)
        self.tgs_solver = bool(tgs_solver)
        self.pcm = bool(pcm)
        self.stabilization = bool(stabilization)
        self.cpu_fallback = bool(cpu_fallback)
        self.enhanced_determinism = bool(enhanced_determinism)
        self._gpu_statistics = gpu_statistics
        self.fixed_dt = fixed_dt
        self.steps = steps
        self.gravity = gravity
        self.bodies = bodies
        self._attachments = attachments
        self._source_attachments = source_attachments
        self._independent_verification = False

    @property
    def physx_version_string(self) -> str:
        return ".".join(str(value) for value in (
            (self.physx_version >> 24) & 0xFF,
            (self.physx_version >> 16) & 0xFF,
            (self.physx_version >> 8) & 0xFF,
        ))

    @property
    def simulated_seconds(self) -> float:
        return self.fixed_dt * self.steps

    def body(self, name: str) -> BodyState:
        for body in self.bodies:
            if body.name == name:
                return body
        raise KeyError(name)

    def metadata(self) -> dict[str, Any]:
        """Return the stable, human-readable simulation manifest."""
        self.validate()
        return {
            "schema_version": 2,
            "generator": "spectraldock.physics/2",
            "scene": self.scene_name,
            "backend": {
                "name": "NVIDIA PhysX",
                "mode": "gpu",
                "physx_version": self.physx_version_string,
                "physx_commit": self.physx_commit,
                "cuda_runtime_version": self.cuda_runtime_version,
                "device_ordinal": self.device,
                "device_name": self.device_name,
                "cuda_context_valid": self.cuda_context_valid,
                "cpu_fallback": self.cpu_fallback,
                "cpu_dispatcher_role": "host-task-scheduling-only",
                "gpu_heap_bytes": {
                    "samples": self._gpu_statistics.samples,
                    "total": self._gpu_statistics.heap_bytes,
                    "broad_phase": self._gpu_statistics.broad_phase_bytes,
                    "narrow_phase": self._gpu_statistics.narrow_phase_bytes,
                    "solver": self._gpu_statistics.solver_bytes,
                    "simulation": self._gpu_statistics.simulation_bytes,
                },
            },
            "simulation": {
                "seed": self.seed,
                "fixed_dt": _rounded(self.fixed_dt),
                "steps": self.steps,
                "simulated_seconds": _rounded(self.simulated_seconds),
                "gravity": [_rounded(value) for value in self.gravity],
                "broad_phase": "gpu" if self.gpu_broad_phase else "cpu",
                "solver": "tgs" if self.tgs_solver else "unknown",
                "flags": {
                    "gpu_dynamics": self.gpu_dynamics,
                    "pcm": self.pcm,
                    "stabilization": self.stabilization,
                    "enhanced_determinism": self.enhanced_determinism,
                },
                "determinism_limitation":
                    "enhanced_determinism_unsupported_on_gpu",
                "independent_gpu_verification": self._independent_verification,
            },
            "bodies": [
                {
                    "name": body.name,
                    "category": body.category,
                    "initial_position": [_rounded(value) for value in body.initial_position],
                    "initial_rotation_xyzw": [_rounded(value) for value in body.initial_rotation],
                    "position": [_rounded(value) for value in body.position],
                    "rotation_xyzw": [_rounded(value) for value in body.rotation],
                    "linear_velocity": [_rounded(value) for value in body.linear_velocity],
                    "angular_velocity": [_rounded(value) for value in body.angular_velocity],
                    "sleeping": body.sleeping,
                }
                for body in self.bodies
            ],
            "render_attachments": len(self._attachments),
        }

    def validate(self) -> None:
        if self.backend != "physx-gpu":
            raise PhysicsError(f"unsupported PhysX backend {self.backend!r}; CPU fallback is forbidden")
        if self.physx_version_string != "5.8.0" or self.physx_commit != _PHYSX_COMMIT:
            raise PhysicsError("PhysX worker does not match the pinned 5.8.0 source revision")
        if self.cuda_runtime_version != 12080:
            raise PhysicsError("PhysX worker must use the CUDA 12.8 runtime")
        if not self.device_name:
            raise PhysicsError("PhysX result does not identify its CUDA device")
        if not self.cuda_context_valid:
            raise PhysicsError("PhysX result reports an invalid CUDA context")
        if self.cpu_fallback:
            raise PhysicsError("PhysX result reports a CPU fallback")
        if not self.gpu_dynamics:
            raise PhysicsError("PhysX result did not use GPU dynamics")
        if not self.gpu_broad_phase:
            raise PhysicsError("PhysX result did not use GPU broadphase")
        if not self.tgs_solver:
            raise PhysicsError("PhysX result did not use the required TGS solver")
        if not self.pcm or not self.stabilization or self.enhanced_determinism:
            raise PhysicsError("PhysX result changed the required GPU scene flags")
        statistics = self._gpu_statistics
        if statistics.samples != self.steps:
            raise PhysicsError("PhysX result does not contain one GPU statistics sample per step")
        heaps = (
            statistics.heap_bytes,
            statistics.broad_phase_bytes,
            statistics.narrow_phase_bytes,
            statistics.solver_bytes,
            statistics.simulation_bytes,
        )
        if any(not isinstance(value, int) or value <= 0 for value in heaps):
            raise PhysicsError("PhysX result has zero GPU pipeline heap statistics")
        if any(value > statistics.heap_bytes for value in heaps[1:]):
            raise PhysicsError("PhysX result has inconsistent GPU heap statistics")
        if len(self._attachments) != len(self._source_attachments):
            raise PhysicsError("PhysX result attachment count does not match the request")
        seen: set[int] = set()
        for body in self.bodies:
            rotation_length = math.sqrt(sum(value * value for value in body.rotation))
            if not math.isclose(rotation_length, 1.0, rel_tol=0.0, abs_tol=2.0e-4):
                raise PhysicsError(f"PhysX body {body.name!r} has a non-unit rotation")
        for attachment in self._attachments:
            if attachment.index in seen or attachment.index >= len(self._source_attachments):
                raise PhysicsError("PhysX result has an invalid attachment index")
            seen.add(attachment.index)
            if attachment.kind != self._source_attachments[attachment.index].kind:
                raise PhysicsError("PhysX result changed an attachment type")
            if attachment.body_index >= len(self.bodies):
                raise PhysicsError("PhysX result has an invalid attachment body index")

    def apply_to(self, renderer: Any) -> Any:
        """Create baked world-space objects through the public Renderer API."""
        self.validate()
        for baked in sorted(self._attachments, key=lambda value: value.index):
            source = self._source_attachments[baked.index]
            values = baked.values
            if baked.kind == 1:
                renderer.object(name=source.name, type="sphere", center=values[0:3],
                                radius=values[3], material=source.material)
            elif baked.kind == 2:
                renderer.object(name=source.name, type="rectangle", p1=values[0:3],
                                p2=values[3:6], p3=values[6:9],
                                material=source.material)
            elif baked.kind == 3:
                renderer.object(name=source.name, type="cylinder", base=values[0:3],
                                axis=values[3:6], height=values[6], radius=values[7],
                                material=source.material)
            elif baked.kind == 4:
                renderer.object(name=source.name, type="disk", center=values[0:3],
                                normal=values[3:6], radius=values[6],
                                material=source.material)
            elif baked.kind == 5:
                renderer.object(name=source.name, type="mesh", mesh=source.mesh,
                                translate=values[0:3], rotate_degrees=values[3:6],
                                scale=values[6:9], material=source.material)
            else:  # pragma: no cover - guarded by parser and validate
                raise PhysicsError(f"unsupported baked attachment kind {baked.kind}")
        return renderer


Validator = Callable[[PhysicsResult], bool | None]


class PhysicsWorld:
    """A typed request for an isolated, GPU-only PhysX simulation."""

    def __init__(
        self,
        *,
        device: int = 0,
        seed: int = 0,
        fixed_dt: float = 1.0 / 120.0,
        steps: int = 1,
        gravity: Sequence[float] = (0.0, -9.81, 0.0),
        scene_name: str = "physx-scene",
        worker: str | os.PathLike[str] | None = None,
    ) -> None:
        self.device = int(device)
        if self.device < 0:
            raise ValueError("device must be non-negative")
        self.seed = int(seed)
        if not 0 <= self.seed <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("seed must fit an unsigned 64-bit integer")
        self.fixed_dt = _positive(fixed_dt, "fixed_dt")
        self.steps = int(steps)
        if not 1 <= self.steps <= 10_000_000:
            raise ValueError("steps must be in [1, 10000000]")
        self.gravity = _vec(gravity, 3, "gravity")
        self.scene_name = _name(scene_name, "scene_name")
        self.worker = Path(worker) if worker is not None else None
        self._token = object()
        self._materials: list[PhysicsMaterial] = []
        self._statics: list[_StaticActor] = []
        self._bodies: list[RigidBody] = []
        self._names: set[str] = set()

    def _claim_name(self, name: str) -> str:
        name = _name(name)
        if name in self._names:
            raise ValueError(f"duplicate PhysX actor name {name!r}")
        self._names.add(name)
        return name

    def material(
        self,
        name: str,
        *,
        static_friction: float,
        dynamic_friction: float,
        restitution: float,
    ) -> PhysicsMaterial:
        name = _name(name)
        if any(material.name == name for material in self._materials):
            raise ValueError(f"duplicate PhysX material name {name!r}")
        values = tuple(_finite_scalar(value, label) for value, label in (
            (static_friction, "static_friction"),
            (dynamic_friction, "dynamic_friction"),
            (restitution, "restitution"),
        ))
        if values[0] < 0.0 or values[1] < 0.0 or not 0.0 <= values[2] <= 1.0:
            raise ValueError("friction must be non-negative and restitution must be in [0, 1]")
        material = PhysicsMaterial(name, *values, self._token, len(self._materials))
        self._materials.append(material)
        return material

    def _check_material(self, material: PhysicsMaterial) -> None:
        if not isinstance(material, PhysicsMaterial) or material._world_token is not self._token:
            raise ValueError("PhysX material belongs to a different PhysicsWorld")

    def static_plane(
        self,
        name: str,
        *,
        normal: Sequence[float] = (0.0, 1.0, 0.0),
        distance: float = 0.0,
        material: PhysicsMaterial,
    ) -> None:
        self._check_material(material)
        normal_value = _vec(normal, 3, "normal")
        length = math.sqrt(sum(component * component for component in normal_value))
        if length <= 1.0e-12:
            raise ValueError("plane normal must not be zero")
        normal_value = tuple(component / length for component in normal_value)
        self._statics.append(_StaticActor(1, self._claim_name(name), material,
                                          (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0),
                                          (*normal_value, _finite_scalar(distance, "distance"))))

    def static_box(
        self,
        name: str,
        *,
        position: Sequence[float],
        half_extents: Sequence[float],
        material: PhysicsMaterial,
        rotation: Sequence[float] = (0.0, 0.0, 0.0, 1.0),
    ) -> None:
        self._check_material(material)
        extents = tuple(_positive(value, f"half_extents[{index}]")
                        for index, value in enumerate(_vec(half_extents, 3, "half_extents")))
        self._statics.append(_StaticActor(2, self._claim_name(name), material,
                                          _vec(position, 3, "position"),
                                          _quat(rotation, "rotation"), extents))

    def rigid_body(
        self,
        name: str,
        *,
        category: str,
        position: Sequence[float],
        rotation: Sequence[float] = (0.0, 0.0, 0.0, 1.0),
        density: float = 1.0,
        linear_damping: float = 0.05,
        angular_damping: float = 0.05,
        sleep_threshold: float = 0.005,
        solver_iterations: tuple[int, int] = (8, 2),
    ) -> RigidBody:
        body = RigidBody(self, self._claim_name(name), category, position, rotation,
                         density, linear_damping, angular_damping, sleep_threshold,
                         solver_iterations)
        self._bodies.append(body)
        return body

    def _worker_path(self) -> Path:
        if self.worker is not None:
            candidate = self.worker
        elif os.environ.get("SPECTRALDOCK_PHYSX_WORKER"):
            candidate = Path(os.environ["SPECTRALDOCK_PHYSX_WORKER"])
        else:
            root = Path(__file__).resolve().parents[2]
            candidates = (
                root / "build/PhysX/spectraldock_physx_worker",
                root / "build/spectraldock_physx_worker",
            )
            candidate = next((path for path in candidates if path.is_file()), candidates[0])
        if not candidate.is_file():
            raise PhysicsError(
                f"PhysX worker not found at {candidate}; build spectraldock_physx_worker "
                "with the CUDA 12.8 PhysX toolchain or set SPECTRALDOCK_PHYSX_WORKER"
            )
        if not os.access(candidate, os.X_OK):
            raise PhysicsError(f"PhysX worker is not executable: {candidate}")
        return candidate

    def _source_attachments(self) -> tuple[_Attachment, ...]:
        return tuple(attachment for body in self._bodies for attachment in body._attachments)

    def _encode(self, seed: int) -> bytes:
        if not self._materials:
            raise PhysicsError("PhysicsWorld requires at least one contact material")
        if not self._bodies:
            raise PhysicsError("PhysicsWorld requires at least one rigid body")
        for body in self._bodies:
            if not body._shapes:
                raise PhysicsError(f"rigid body {body.name!r} has no collision shape")

        writer = _Writer()
        writer.raw(_REQUEST_MAGIC)
        writer.u32(_PROTOCOL_VERSION)
        writer.i32(self.device)
        writer.u64(seed)
        writer.f32(self.fixed_dt)
        writer.u32(self.steps)
        writer.floats(self.gravity)
        writer.string(self.scene_name)

        writer.u32(len(self._materials))
        for material in self._materials:
            writer.string(material.name)
            writer.floats((material.static_friction, material.dynamic_friction,
                           material.restitution))

        writer.u32(len(self._statics))
        for actor in self._statics:
            writer.u8(actor.kind)
            writer.string(actor.name)
            writer.u32(actor.material._index)
            writer.floats(actor.position)
            writer.floats(actor.rotation)
            writer.u32(len(actor.values))
            writer.floats(actor.values)

        writer.u32(len(self._bodies))
        for body in self._bodies:
            writer.string(body.name)
            writer.string(body.category)
            writer.floats(body.position)
            writer.floats(body.rotation)
            writer.floats((body.density, body.linear_damping, body.angular_damping,
                           body.sleep_threshold))
            writer.u32(body.solver_iterations[0])
            writer.u32(body.solver_iterations[1])
            writer.floats(body.initial_linear_velocity)
            writer.floats(body.initial_angular_velocity)

            writer.u32(len(body._shapes))
            for shape in body._shapes:
                writer.u8(shape.kind)
                writer.u32(shape.material._index)
                writer.floats(shape.local_position)
                writer.floats(shape.local_rotation)
                writer.u32(len(shape.values))
                writer.floats(shape.values)

            writer.u32(len(body._actions))
            for action in body._actions:
                writer.u8(1)
                writer.floats(action.delta_velocity)
                writer.floats(action.position)

            writer.u32(len(body._attachments))
            for attachment in body._attachments:
                writer.u8(attachment.kind)
                writer.string(attachment.name)
                writer.u32(len(attachment.values))
                writer.floats(attachment.values)
        return bytes(writer.data)

    def _decode(self, data: bytes, expected_seed: int) -> PhysicsResult:
        reader = _Reader(data)
        if reader.raw(8) != _RESULT_MAGIC:
            raise PhysicsError("PhysX worker returned an unknown result format")
        if reader.u32() != _PROTOCOL_VERSION:
            raise PhysicsError("PhysX worker protocol version does not match Python")
        device = reader.i32()
        seed = reader.u64()
        fixed_dt = reader.f32()
        steps = reader.u32()
        physx_version = reader.u32()
        cuda_runtime_version = reader.u32()
        physx_commit = reader.string()
        scene_name = reader.string()
        backend = reader.string()
        device_name = reader.string()
        cuda_context_valid = reader.boolean("cuda_context_valid")
        gpu_dynamics = reader.boolean("gpu_dynamics")
        gpu_broad_phase = reader.boolean("gpu_broad_phase")
        tgs_solver = reader.boolean("tgs_solver")
        pcm = reader.boolean("pcm")
        stabilization = reader.boolean("stabilization")
        cpu_fallback = reader.boolean("cpu_fallback")
        enhanced_determinism = reader.boolean("enhanced_determinism")
        gpu_statistics = _GpuPipelineStatistics(
            samples=reader.u32(),
            heap_bytes=reader.u64(),
            broad_phase_bytes=reader.u64(),
            narrow_phase_bytes=reader.u64(),
            solver_bytes=reader.u64(),
            simulation_bytes=reader.u64(),
        )
        if device != self.device or seed != expected_seed or steps != self.steps:
            raise PhysicsError("PhysX worker result does not match its request")
        if scene_name != self.scene_name or not math.isclose(
                fixed_dt, self.fixed_dt, rel_tol=2.0e-6, abs_tol=1.0e-9):
            raise PhysicsError("PhysX worker changed scene identity or time step")

        bodies: list[BodyState] = []
        for _ in range(reader.count("body")):
            bodies.append(BodyState(
                name=reader.string(), category=reader.string(),
                initial_position=reader.floats(3), initial_rotation=reader.floats(4),
                position=reader.floats(3), rotation=reader.floats(4),
                linear_velocity=reader.floats(3), angular_velocity=reader.floats(3),
                sleeping=bool(reader.u8()),
            ))
        if len(bodies) != len(self._bodies):
            raise PhysicsError("PhysX worker returned the wrong number of bodies")
        for state, request in zip(bodies, self._bodies):
            if state.name != request.name or state.category != request.category:
                raise PhysicsError("PhysX worker changed body identity or ordering")

        value_counts = {1: 4, 2: 9, 3: 8, 4: 7, 5: 9}
        attachments: list[_BakedAttachment] = []
        for _ in range(reader.count("attachment")):
            index = reader.u32()
            body_index = reader.u32()
            kind = reader.u8()
            if kind not in value_counts:
                raise PhysicsError(f"PhysX worker returned unknown attachment kind {kind}")
            attachments.append(_BakedAttachment(index, body_index, kind,
                                                 reader.floats(value_counts[kind])))
        reader.finish()
        expected_body_indices = tuple(
            body_index
            for body_index, body in enumerate(self._bodies)
            for _ in body._attachments
        )
        for attachment in attachments:
            if (attachment.index >= len(expected_body_indices) or
                    attachment.body_index != expected_body_indices[attachment.index]):
                raise PhysicsError("PhysX worker reassigned a render attachment")
        result = PhysicsResult(
            scene_name=scene_name, seed=seed, device=device, device_name=device_name,
            backend=backend, physx_version=physx_version,
            physx_commit=physx_commit,
            cuda_runtime_version=cuda_runtime_version,
            cuda_context_valid=cuda_context_valid,
            gpu_dynamics=gpu_dynamics,
            gpu_broad_phase=gpu_broad_phase,
            tgs_solver=tgs_solver,
            pcm=pcm,
            stabilization=stabilization,
            cpu_fallback=cpu_fallback,
            enhanced_determinism=enhanced_determinism,
            gpu_statistics=gpu_statistics,
            fixed_dt=fixed_dt, steps=steps,
            gravity=self.gravity,
            bodies=tuple(bodies), attachments=tuple(attachments),
            source_attachments=self._source_attachments(),
        )
        result.validate()
        return result

    @staticmethod
    def _accept(result: PhysicsResult, validator: Validator | None) -> None:
        result.validate()
        if validator is not None and validator(result) is False:
            raise _RejectedState("scene-specific PhysX validator rejected the simulation")

    def _run_once(self, worker: Path, request: bytes, expected_seed: int,
                  directory: Path, suffix: str) -> PhysicsResult:
        request_path = directory / f"request-{suffix}.sdp"
        result_path = directory / f"result-{suffix}.sdp"
        request_path.write_bytes(request)
        command = (str(worker), "--request", str(request_path),
                   "--result", str(result_path))
        completed = subprocess.run(command, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, check=False)
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "no diagnostic"
            raise PhysicsError(
                f"GPU PhysX worker failed with exit code {completed.returncode}: {detail}"
            )
        if not result_path.is_file():
            raise PhysicsError("GPU PhysX worker did not create its result file")
        return self._decode(result_path.read_bytes(), expected_seed)

    def simulate(
        self,
        *,
        metadata_output: str | os.PathLike[str] | None = None,
        verify: bool = False,
        validator: Validator | None = None,
        max_attempts: int = 8,
    ) -> PhysicsResult:
        """Run PhysX in a CUDA-12.8 subprocess and return baked attachments.

        ``verify=True`` performs a second independent GPU launch for the accepted
        seed and validates its contract.  It intentionally does not demand byte
        identity from a parallel floating-point simulation.
        """
        attempts = int(max_attempts)
        if not 1 <= attempts <= 1024:
            raise ValueError("max_attempts must be in [1, 1024]")
        destination = None if metadata_output is None else Path(metadata_output)
        if destination is not None and destination.suffix.lower() != ".json":
            raise ValueError("metadata_output must name a .json file")
        worker = self._worker_path()
        last_error: Exception | None = None
        with tempfile.TemporaryDirectory(prefix="spectraldock-physx-") as temporary:
            directory = Path(temporary)
            for attempt in range(attempts):
                # Retrying is for rare GPU scheduling variance in a scene-level
                # validator.  The authored initial layout and its reported seed
                # must remain identical across attempts.
                seed = self.seed
                request = self._encode(seed)
                try:
                    result = self._run_once(worker, request, seed, directory,
                                            f"{attempt}-primary")
                    self._accept(result, validator)
                    if verify:
                        verification = self._run_once(worker, request, seed, directory,
                                                      f"{attempt}-verify")
                        self._accept(verification, validator)
                        if len(verification.bodies) != len(result.bodies):
                            raise PhysicsError("independent PhysX verification changed body count")
                        result._independent_verification = True
                    if destination is not None:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        temporary_output = destination.with_name(
                            f".{destination.name}.tmp-{os.getpid()}"
                        )
                        try:
                            with temporary_output.open("w", encoding="utf-8") as output:
                                json.dump(result.metadata(), output, ensure_ascii=False,
                                          indent=2, sort_keys=True)
                                output.write("\n")
                            os.replace(temporary_output, destination)
                        finally:
                            temporary_output.unlink(missing_ok=True)
                    return result
                except _RejectedState as error:
                    last_error = error
        assert last_error is not None
        raise PhysicsError(f"PhysX simulation did not produce an accepted state: {last_error}")


__all__ = [
    "BodyState",
    "PhysicsError",
    "PhysicsMaterial",
    "PhysicsResult",
    "PhysicsWorld",
    "RigidBody",
]
