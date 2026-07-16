# Example asset manifest

Runtime image paths are relative to this directory. Two PNG textures were
generated for this project on 2026-07-07 through the built-in `imagegen`
workflow. They are provided as-is, without a representation of uniqueness or
exclusivity. The separate `models/sparky/sparky_albedo.png` is an original
project-owner contribution, not an output of that workflow. The Radiance HDR
environment is an analytical, deterministic output of the Apache-2.0 Python
generator in `tools/`, not an AI-generated image.

The compact distribution omits PNG generation and seam-repair intermediate
bitmaps; their dimensions, processing steps, prompts, and SHA-256 digests
remain recorded below.

The seam-repair edits preserve the maps' composition and palette visually, but
the image model lightly redrew pixels outside the requested center band rather
than keeping those regions byte-identical. The initial-bitmap digests remain in
this manifest so this distinction stays auditable.

The three runtime texture PNG files and the HDR environment listed here are
dedicated under CC0-1.0. This Markdown sidecar is licensed under Apache-2.0.

## `environments/radiance-pavilion.hdr`

- Runtime size and encoding: 2048 x 1024 Radiance RGBE, linear Rec.709 RGB,
  `FORMAT=32-bit_rle_rgbe`, `-Y 1024 +X 2048`, modern per-component scanline
  RLE.
- Runtime byte size: 2,876,893 bytes.
- Runtime SHA-256:
  `33b6e651abbacbf7458aac0c2610f96705a763251a1699e5548615ca36dbf6d7`.
- Deterministic rebuild:
  `python3 tools/generate_hdr_environment.py`.
- Construction: an analytical sunset coast combines a cool zenith, layered
  warm clouds, a low golden sun, a dark teal sea, a reflected-sun path and
  distant island silhouettes. Pixel centers are sampled in a fixed
  equirectangular order, converted directly to RGBE, then encoded with a fixed
  literal/run partition. The file has no timestamp or machine-dependent
  metadata.
- Licensing: the generator is Apache-2.0; the generated `.hdr` file is one of
  the visual assets explicitly dedicated under CC0-1.0.

## `models/sparky/sparky_albedo.png`

- Runtime size and encoding: 1024 x 1024, 8-bit RGBA PNG without an embedded
  color profile or sRGB chunk; every alpha sample is fully opaque. The scene
  explicitly registers it as sRGB through the typed texture API.
- Runtime byte size: 15,103 bytes.
- Runtime SHA-256:
  `e0c5f6b728a53d3cfbc1ef6f29bd55417170d5f02c53305a7a4b1a9f931e22f0`.
- Source: direct original contribution by the project owner together with
  `sparky.obj` and `sparky.mtl`; it is not represented as imagegen output and
  has no upstream archive in the distribution.
- Use: one sRGB atlas shared by the `ScreenFace`, `ScreenChest`, and
  `ScreenPalm` material slots. The full geometry/material/file record is in
  `models/sparky/manifest.json`.
- Licensing: explicitly dedicated under CC0-1.0.

## `textures/planet-azure.png`

- Initial imagegen bitmap (not included in the compact distribution):
  1774 x 887 RGB PNG (exact 2:1), SHA-256
  `b09691b1d8dafbb522301fe80267d7cbd1d3f37f5e3dd486d03051cad717bb1f`.
- Seam-repair intermediate (not included in the compact distribution):
  1774 x 887 RGB PNG, SHA-256
  `c9d6d858bdaadfb53224c0a7cec0ee61d66bf809fcb9b701abdb58c84bcc53d8`.
- Runtime processing: the initial source was rolled horizontally by 887 pixels
  so the longitude boundary appeared at canvas center; built-in imagegen
  repaired that center join using the second prompt below. ImageMagick
  6.9.10-68 rolled the repair back by -887 pixels. The first and last
  one-pixel columns were averaged and written to both edges, making every RGB
  edge pixel identical without a wide mirrored band.
- Runtime SHA-256:
  `813e73e7b89e28098d7926093268365037fd97bc68ff91f108aad1a4099096a3`.
- Initial prompt:

```text
Use case: stylized-concept
Asset type: seamless equirectangular planet albedo texture for offline ray tracing
Primary request: Create an original 2:1 equirectangular albedo map for a fictional azure ocean planet, edge-to-edge surface texture only.
Scene/backdrop: the entire canvas is the planet surface map, not a view of a globe and not outer space.
Subject: deep cobalt oceans, pale turquoise archipelagos, warm ochre highlands, scattered white polar ice and sparse soft cloud bands.
Style/medium: detailed painterly-realistic planetary texture, physically plausible color variation.
Composition/framing: exact 2:1 equirectangular world map, north pole along top edge and south pole along bottom edge; left and right edges must join seamlessly with no visible discontinuity.
Lighting/mood: flat albedo, completely unlit; no directional shading, highlights, terminator, atmosphere rim, cast shadows, or baked illumination.
Constraints: no text, no labels, no border, no stars, no globe silhouette, no watermark; preserve seamless horizontal wrap; avoid features cut abruptly at the seam.
```

- Seam-repair prompt:

```text
Use case: precise-object-edit
Asset type: horizontally seamless 2:1 equirectangular planet albedo texture
Input image: edit target. It is a longitude-rotated version of the final map, with one visible straight vertical join exactly at the center of the canvas.
Primary request: remove only that center vertical join by naturally continuing ocean currents, cloud bands, coastlines, archipelagos, polar ice, colors, and fine texture across a narrow band around the center. The repaired center must look like ordinary continuous terrain, with no line, mirror symmetry, repeated motif, blur stripe, or tonal step.
Invariants: keep the exact 2:1 equirectangular framing; preserve the outer 40 percent on both the left and right completely unchanged so those outer edges remain a naturally adjacent longitude cut; preserve the azure/ocean/ochre/white palette and flat unlit albedo character.
Constraints: no globe, space, lighting, shadows, terminator, atmosphere, border, labels, text, or watermark. Change only the narrow center seam.
```

## `textures/planet-ember.png`

- Initial imagegen bitmap (not included in the compact distribution):
  1774 x 887 RGB PNG (exact 2:1), SHA-256
  `9339d0b1459ad9d5ef955a6514695ce62dac45c0c6b18f801cfcc7ad4880fd73`.
- Seam-repair intermediate (not included in the compact distribution):
  1774 x 887 RGB PNG, SHA-256
  `e338eca937a6e510df9804d30c69e8f8b6919d06a5548591fdb0206d9e1dc009`.
- Runtime processing: the same 887-pixel roll, center repair, -887-pixel
  inverse roll and single-column edge averaging procedure used for
  `planet-azure.png`, with ImageMagick 6.9.10-68.
- Runtime SHA-256:
  `14cb336904b10e18758aa1923ad786a2651e326e4f92dd116fd689675d1d5d52`.
- Initial prompt:

```text
Use case: stylized-concept
Asset type: seamless equirectangular planet albedo texture for offline ray tracing
Primary request: Create an original 2:1 equirectangular albedo map for a fictional ember desert planet, edge-to-edge surface texture only.
Scene/backdrop: the entire canvas is the planet surface map, not a view of a globe and not outer space.
Subject: rust-red dune seas, charcoal volcanic plateaus, pale cream salt basins, thin branching canyon systems, small muted teal mineral regions, light polar frost.
Style/medium: detailed painterly-realistic planetary texture, physically plausible color variation and geological scale.
Composition/framing: exact 2:1 equirectangular world map; left and right edges must join seamlessly without a visible discontinuity.
Lighting/mood: flat albedo, completely unlit; no directional shading, highlights, terminator, atmosphere rim, cast shadows, or baked illumination.
Constraints: no text, no labels, no border, no stars, no globe silhouette, no watermark; preserve seamless horizontal wrap; avoid features cut abruptly at the seam.
```

- Seam-repair prompt:

```text
Use case: precise-object-edit
Asset type: horizontally seamless 2:1 equirectangular planet albedo texture
Input image: edit target. It is a longitude-rotated version of the final map, with one visible straight vertical join exactly at the center of the canvas.
Primary request: remove only that center vertical join by naturally continuing dunes, canyons, crater fields, volcanic plateaus, salt basins, frost bands, colors, and fine texture across a narrow band around the center. The repaired center must look like ordinary continuous terrain, with no line, mirror symmetry, repeated motif, blur stripe, or tonal step.
Invariants: keep the exact 2:1 equirectangular framing; preserve the outer 40 percent on both the left and right completely unchanged so those outer edges remain a naturally adjacent longitude cut; preserve the rust-red/charcoal/cream/muted-teal palette and flat unlit albedo character.
Constraints: no globe, space, lighting, shadows, terminator, atmosphere, border, labels, text, or watermark. Change only the narrow center seam.
```
