"""Python-first API for the SpectralDock OptiX research renderer."""

from pkgutil import extend_path

# The source tree contains the Python modules while the configured build tree
# contains ``_native``.  Supporting both paths keeps editable development
# convenient without copying an extension into the source directory.
__path__ = extend_path(__path__, __name__)

from ._renderer import (
    LightHandle,
    MaterialHandle,
    MeshHandle,
    ObjectHandle,
    Renderer,
    TextureHandle,
)
from .physics import PhysicsError, PhysicsMaterial, PhysicsResult, PhysicsWorld

__all__ = [
    "LightHandle",
    "MaterialHandle",
    "MeshHandle",
    "ObjectHandle",
    "PhysicsError",
    "PhysicsMaterial",
    "PhysicsResult",
    "PhysicsWorld",
    "Renderer",
    "TextureHandle",
]
