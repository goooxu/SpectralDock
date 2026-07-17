# Third-party notices

This file records third-party code, data, or formulas present in the
SpectralDock source distribution. The repository-level Apache-2.0 license does
not replace the licenses identified below.

## PCG-XSH-RR 64/32

- Author: M. E. O'Neill
- Copyright: 2014 M. E. O'Neill
- Source: https://www.pcg-random.org/download.html
- License: Apache License 2.0
- Used in: src/device_programs.cu
- Local changes: adapted for CUDA device code; stream initialization and
  pixel/sample seed mixing are project-specific.

## lowbias32 integer mixer

- Author: Chris Wellons
- Sources: https://nullprogram.com/blog/2018/07/31/ and
  https://github.com/skeeto/hash-prospector
- License: public domain / Unlicense
- Used in: Pcg32::hash in src/device_programs.cu

## ACES-inspired fitted curve

- Author: Krzysztof Narkowicz
- Source: https://knarkowicz.wordpress.com/2016/01/06/aces-filmic-tone-mapping-curve/
- Upstream offer: CC0 or MIT; SpectralDock uses it under CC0-1.0.
- Used in: src/postprocess.cu

This compact per-channel fit is not the complete Academy Color Encoding
System, and it does not implement ACES color-space transforms, RRT, ODT, or
display selection.

## Spot model and texture

- Creator: Keenan Crane
- Source: https://www.cs.cmu.edu/~kmcrane/Projects/ModelRepository/
- Upstream archive:
  https://www.cs.cmu.edu/~kmcrane/Projects/ModelRepository/spot.zip
- License: CC0 1.0 Universal
- Included files: `assets/examples/models/spot/spot_triangulated.obj` and
  `assets/examples/models/spot/spot_texture.png`
- Local changes: none

The upstream page describes Spot as a spotted animal and permits use for any
purpose. Attribution is not required by CC0, but the author asks paper authors
to consider citing Keenan Crane, Ulrich Pinkall, and Peter Schröder, “Robust
fairing via conformal curvature flow,” ACM Transactions on Graphics 32(4),
2013.

## tinyobjloader 2.0.0

- Authors: Syoyo Fujita and tinyobjloader contributors
- License: MIT
- Vendored source: NVIDIA OptiX SDK 9.1.0 example tree
- Original header SHA-256:
  3a64a7b6d9b97590b287174c6c055cea8f5818998c96b55d579b87c2db1290f1
- Locally patched header SHA-256:
  477990b3c8dd1b8081e2440ee493188202383fec48acbcc876c30e3f4618b88d

The local input-hardening change is described in
third_party/tinyobjloader/README.md. The complete upstream license is retained
in third_party/tinyobjloader/LICENSE and in the header.

## MikkTSpace

- Author: Morten S. Mikkelsen
- Source: https://github.com/mmikk/MikkTSpace
- Pinned commit: `3e895b49d05ea07e4c2133156cfa94369e19e409`
- License: zlib-style license retained verbatim in `mikktspace.c` and
  `mikktspace.h`
- Used by: OBJ face-corner tangent generation for tangent-space normal maps

The two upstream source files are vendored without local algorithm changes.
SpectralDock supplies only the mesh callback adapter and validates the
generated tangent records before uploading them to the renderer.

## NVIDIA PhysX 5.8.0

- Authors: NVIDIA Corporation and PhysX contributors
- Source: https://github.com/NVIDIA-Omniverse/PhysX
- Upstream tag: `110.0-omni-and-physx-5.8.0`
- Pinned commit: `fc1018a3745664a1db2b95ce03fb5e91eb585f2e`
- License: BSD 3-Clause License
- Used by: the optional GPU-only PhysX worker used by Kinetic Foundry and
  Lava Temple Oracle

PhysX is obtained and built separately for the host. Its source, headers,
libraries, and binaries are not included in this source distribution. The two
Python programs call the isolated worker through private temporary IPC and
apply returned typed attachments directly to `Renderer`; their checked-in
`.physics.json` sidecars record the accepted run environment and parameters.
SpectralDock is an independent, unofficial project and is not affiliated with,
sponsored by, or endorsed by NVIDIA Corporation.

## pybind11

- Authors: Wenzel Jakob and pybind11 contributors
- Source: https://github.com/pybind/pybind11
- License: BSD 3-Clause License
- Used by: the `_native` Python extension build

pybind11 is an external build dependency and is not vendored in this source
distribution.

## External build and runtime dependencies

CUDA, OptiX, PhysX, the NVIDIA driver, libpng, Python, and pybind11 are obtained
separately from their respective distributors. Their SDK or library sources
are not included in this source distribution, and their own terms apply.
