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
- Used in: include/spectraldock/math.h and src/postprocess.cu

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

## External build and runtime dependencies

CUDA, OptiX, the NVIDIA driver, libpng, and nlohmann_json are obtained
separately from their respective distributors. Their SDK or library sources
are not included in this source distribution, and their own terms apply.
