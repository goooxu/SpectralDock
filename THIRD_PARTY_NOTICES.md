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

## Spot model and texture

- Creator: Keenan Crane
- Source: https://www.cs.cmu.edu/~kmcrane/Projects/ModelRepository/
- Upstream archive:
  https://www.cs.cmu.edu/~kmcrane/Projects/ModelRepository/spot.zip
- License: CC0 1.0 Universal
- Included files: `assets/examples/models/spot/spot_triangulated.obj` and
  `assets/examples/models/spot/spot_texture.avif`
- Local changes: geometry is unchanged; the source albedo bitmap is encoded to
  the canonical 8-bit BT.709/sRGB, identity-matrix, full-range 4:4:4 lossless
  AVIF texture profile without changing decoded RGBA samples.

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
- Used by: the isolated GPU-only PhysX worker used by Kinetic Foundry,
  Lava Temple Oracle, Atelier, and Assembly Hall

PhysX is obtained and built separately for the host. Its source, headers,
libraries, and binaries are not included in this source distribution. The four
Python programs call the isolated worker through private temporary IPC and
apply returned poses through typed attachments or validated `BodyState`
instances. GPU dynamics and GPU broadphase are both mandatory; CPU PhysX
fallback is forbidden. Only the two original tutorial scenes keep checked-in
`.physics.json` sidecars; the two Gallery covers do not.
SpectralDock is an independent, unofficial project and is not affiliated with,
sponsored by, or endorsed by NVIDIA Corporation.

## pybind11

- Authors: Wenzel Jakob and pybind11 contributors
- Source: https://github.com/pybind/pybind11
- License: BSD 3-Clause License
- Used by: the `_native` Python extension build

pybind11 is an external build dependency and is not vendored in this source
distribution.

## libavif 1.4.2

- Authors: Alliance for Open Media contributors
- Source: https://github.com/AOMediaCodec/libavif
- Pinned commit: `c5240fc79fe5c2407e10afd35f5505ef6333ea49`
- License: BSD 2-Clause License
- Used by: all texture decoding and texture/HDR output AVIF encoding

CMake obtains this exact revision through `FetchContent`. Optional JPEG,
legacy raster, libyuv, and libsharpyuv integration is disabled. The renderer
uses libavif with the local AOM backend and requires a single-frame AVIF profile.

## AOMedia AV1 codec 3.14.1

- Authors: Alliance for Open Media contributors
- Source: https://aomedia.googlesource.com/aom/
- Version selected by: libavif 1.4.2 local AOM dependency
- License: BSD 2-Clause License and Alliance for Open Media Patent License 1.0
- Used by: lossless AV1 coding for texture and HDR AVIF files

AOM is fetched by libavif's local-codec build. Its runtime CPU dispatch chooses
an implementation supported by the executing host; SpectralDock does not pin a
CPU microarchitecture.

## External build and runtime dependencies

CUDA, OptiX, PhysX, the NVIDIA driver, Python, and pybind11 are obtained
separately from their respective distributors. libavif and its local AOM codec
are obtained automatically at configure time from the pinned revisions above.
All upstream terms continue to apply.
