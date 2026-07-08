# tinyobjloader 2.0.0

`tiny_obj_loader.h` was vendored from NVIDIA OptiX SDK 9.1.0:

`SDK/optixMotionGeometry/tiny_obj_loader.h`

The unmodified SDK header has SHA-256
`3a64a7b6d9b97590b287174c6c055cea8f5818998c96b55d579b87c2db1290f1`.
SpectralDock applies one local input-hardening patch: `fixIndex` rejects explicit
positive or relative OBJ indices that do not resolve to an existing attribute,
and the face parse error identifies zero/out-of-range indices. This prevents an
invalid optional UV/normal index from becoming the `-1` “attribute missing”
sentinel.

The upstream MIT license is preserved verbatim in `LICENSE` and at the top of
the header.
