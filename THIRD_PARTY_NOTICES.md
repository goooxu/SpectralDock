# Third-party notices

This file records third-party code or formulas present in the SpectralDock
source distribution. The repository-level Apache-2.0 license does not replace
the licenses identified below.

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

## NVIDIA PhysX 5.8.0

- Authors: NVIDIA Corporation and PhysX contributors
- Source: https://github.com/NVIDIA-Omniverse/PhysX
- Upstream tag: `110.0-omni-and-physx-5.8.0`
- Pinned commit: `fc1018a3745664a1db2b95ce03fb5e91eb585f2e`
- License: BSD 3-Clause License
- Used by: the optional Kinetic Foundry GPU rigid-body scene generator

PhysX is fetched and built into the dedicated development container image at
image-build time. Its source, headers, libraries, binaries, and container image
are not included in this source distribution. The checked-in Kinetic Foundry
PNG is rendered by SpectralDock from an ephemeral generated scene; its
`.physics.json` sidecar records the generation environment and parameters.
SpectralDock is an independent, unofficial project and is not affiliated with,
sponsored by, or endorsed by NVIDIA Corporation.

## External build and runtime dependencies

CUDA, OptiX, PhysX, the NVIDIA driver, libpng, and nlohmann_json are obtained
separately from their respective distributors. Their SDK or library sources
are not included in this source distribution, and their own terms apply.
