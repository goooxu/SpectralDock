# Example asset manifest

Runtime image paths are relative to this directory. Two planet PNG textures were
generated for this project on 2026-07-07 through the built-in `imagegen`
workflow. They are provided as-is, without a representation of uniqueness or
exclusivity. The separate `models/sparky/sparky_albedo.png` belongs to the
AI-generated Sparky model bundle contributed by the project owner; it is not
one of the two planet imagegen outputs documented below. The Radiance HDR
environment is an analytical, deterministic output of the Apache-2.0 Python
generator in `tools/`, not an AI-generated image. The separate
`models/spot/spot_texture.png` is an unmodified third-party bitmap from Keenan
Crane's Spot model archive, not a project-authored or AI-generated image.
The two `models/showcase-panel/` PNG files are deterministic procedural data
maps produced by the Apache-2.0 generator `tools/generate_showcase_panel.py`;
they are neither AI-generated images nor third-party assets. Geometry, byte
sizes and file digests for the complete panel bundle are recorded in
`models/showcase-panel/manifest.json`, an Apache-2.0 sidecar.

The compact distribution omits PNG generation and seam-repair intermediate
bitmaps; their dimensions, processing steps, prompts, and SHA-256 digests
remain recorded below.

The seam-repair edits preserve the maps' composition and palette visually, but
the image model lightly redrew pixels outside the requested center band rather
than keeping those regions byte-identical. The initial-bitmap digests remain in
this manifest so this distinction stays auditable.

The six texture/data-map PNG files and the HDR environment listed here are
distributed under CC0-1.0. The Spot texture retains its upstream CC0
dedication; the other listed visual assets are dedicated by project
contributors. This Markdown sidecar is licensed under Apache-2.0.

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

## `models/showcase-panel/showcase-panel-normal.png`

- Runtime size and encoding: 1024 x 1024, 8-bit RGB PNG without an embedded
  color profile or sRGB chunk. The scene registers it as linear data through
  the typed texture API.
- Convention: tangent-space OpenGL/+Y. The OBJ has complete UVs and explicit
  `+Z` normals; its two triangles exercise the renderer's generated tangent
  frame without requiring mesh duplication.
- Runtime byte size: 100,434 bytes.
- Runtime SHA-256:
  `aafd558f3057f2ad25e9fec041603ced9d2ebf743b5e25c1fca3752c3766fe49`.
- Source and rebuild: deterministic integer construction by
  `python3 tools/generate_showcase_panel.py`. The generator uses only the
  Python standard library and is licensed under Apache-2.0.
- Licensing: the generated runtime PNG is explicitly dedicated under
  CC0-1.0. It is a procedural data map, not an AI-generated image.

## `models/showcase-panel/showcase-panel-metallic-roughness.png`

- Runtime size and encoding: 1024 x 1024, 8-bit RGB PNG without an embedded
  color profile or sRGB chunk. The scene registers it as linear data through
  the typed texture API.
- Channel layout: R is unused and constant `1.0`; G stores roughness; B stores
  metallic. No channel is color data and no sRGB decoding applies.
- Runtime byte size: 10,643 bytes.
- Runtime SHA-256:
  `b9ecec85c490fc0377d4c39260cf175b98da10d5e0c8bdfd8694ea3e57109329`.
- Source and rebuild: deterministic integer construction by the same
  `tools/generate_showcase_panel.py` generator.
- Licensing: the generated runtime PNG is explicitly dedicated under
  CC0-1.0. It is a procedural data map, not an AI-generated image.

The paired geometry is
`models/showcase-panel/showcase-panel.obj` (405 bytes, 4 positions, 4 UVs,
1 explicit normal and 2 triangles), SHA-256
`d907577a7da1ea01eded6ca26cde4cce0553e4f0559e211973f51d3cf5b0e5f1`.
It is also a deterministic CC0-1.0 runtime output. The independent
`models/showcase-panel/manifest.json` records all three runtime assets and is
licensed under Apache-2.0 rather than CC0-1.0.

## `models/sparky/sparky_albedo.png`

- Runtime size and encoding: 1024 x 1024, 8-bit RGBA PNG without an embedded
  color profile or sRGB chunk; every alpha sample is fully opaque. The scene
  explicitly registers it as sRGB through the typed texture API.
- Runtime byte size: 15,103 bytes.
- Runtime SHA-256:
  `e0c5f6b728a53d3cfbc1ef6f29bd55417170d5f02c53305a7a4b1a9f931e22f0`.
- Source: AI-generated asset contributed by the project owner together with
  `sparky.obj` and `sparky.mtl`. It is not one of the two planet
  images produced by the recorded built-in imagegen workflow, and no upstream
  archive is included in the distribution.
- Use: one sRGB atlas shared by the `ScreenFace`, `ScreenChest`, and
  `ScreenPalm` material slots. The full geometry/material/file record is in
  `models/sparky/manifest.json`.
- Licensing: explicitly dedicated under CC0-1.0.

## `models/spot/spot_texture.png`

- Runtime size and encoding: 1024 x 1024, 8-bit RGB PNG with an embedded IEC
  sRGB color profile.
- Runtime byte size: 78,699 bytes.
- Runtime SHA-256:
  `cddabbae52a666173e7953e238b88340d285044dc20b36f8ed3f1a41db534fa5`.
- Source: the `spot_texture.png` bitmap in Keenan Crane's upstream
  [`spot.zip`](https://www.cs.cmu.edu/~kmcrane/Projects/ModelRepository/spot.zip)
  archive.
- Use: albedo atlas matching `models/spot/spot_triangulated.obj`; a scene must
  register it explicitly as an sRGB image texture with repeat wrapping because
  the upstream UVs extend slightly outside the unit square.
- Licensing: unmodified upstream asset dedicated under CC0-1.0 by Keenan
  Crane.

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
