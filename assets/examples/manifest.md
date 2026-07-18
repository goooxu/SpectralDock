# Example asset manifest

Runtime image paths are relative to this directory. Two planet AVIF textures were
generated for this project on 2026-07-07 through the built-in `imagegen`
workflow. They are provided as-is, without a representation of uniqueness or
exclusivity. The separate `models/sparky/sparky_albedo.avif` belongs to the
AI-generated Sparky model bundle contributed by the project owner; it is not
one of the two planet imagegen outputs documented below. The Radiance HDR
environment is an analytical, deterministic output of the Apache-2.0 Python
generator in `tools/`, not an AI-generated image. The separate
`models/spot/spot_texture.avif` is the project's canonical lossless AVIF encoding
of the third-party bitmap in Keenan Crane's Spot model archive, not a
project-authored or AI-generated image.
The two `models/showcase-panel/` AVIF files are deterministic procedural data
maps produced by the Apache-2.0 generator `tools/generate_showcase_panel.py`;
they are neither AI-generated images nor third-party assets. Geometry, byte
sizes and file digests for the complete panel bundle are recorded in
`models/showcase-panel/manifest.json`, an Apache-2.0 sidecar.
The separate `environments/assembly-hall-noon.hdr` and
`textures/assembly-hall-gear-alpha.avif` files are deterministic procedural
outputs of `tools/generate_assembly_hall_assets.py`; they are neither
AI-generated images nor third-party assets.

The compact distribution omits source-generation and seam-repair intermediate
bitmaps; their dimensions, processing steps, prompts, and SHA-256 digests remain
recorded below. Runtime textures are encoded through the project AVIF writer.

The seam-repair edits preserve the maps' composition and palette visually, but
the image model lightly redrew pixels outside the requested center band rather
than keeping those regions byte-identical. The initial-bitmap digests remain in
this manifest so this distinction stays auditable.

The seven texture/data-map AVIF files and two HDR environments listed here are
distributed under CC0-1.0. The Spot texture retains its upstream CC0
dedication; the other listed visual assets are dedicated by project
contributors. This Markdown sidecar is licensed under Apache-2.0.

## `environments/radiance-pavilion.hdr`

- Runtime size and encoding: 2048 x 1024 Radiance RGBE, linear Rec.709 RGB,
  explicit Rec.709/D65
  `PRIMARIES=0.6400 0.3300 0.3000 0.6000 0.1500 0.0600 0.3127 0.3290`,
  `FORMAT=32-bit_rle_rgbe`, `-Y 1024 +X 2048`, modern per-component
  scanline RLE.
- Runtime byte size: 2,876,959 bytes.
- Runtime SHA-256:
  `d0f26d10f7b4d732ae20488e67ba7ce40354e1c791f625ea8baaa8a53f8e0737`.
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

## `environments/assembly-hall-noon.hdr`

- Runtime size and encoding: 2048 x 1024 Radiance RGBE, linear Rec.709 RGB,
  explicit Rec.709/D65
  `PRIMARIES=0.6400 0.3300 0.3000 0.6000 0.1500 0.0600 0.3127 0.3290`,
  `FORMAT=32-bit_rle_rgbe`, `-Y 1024 +X 2048`, modern per-component
  scanline RLE.
- Runtime byte size: 249,686 bytes.
- Runtime SHA-256:
  `f931b478aae7e95f0dab598992ff259791bf55f067f3789a94fcd8c6bb4ff144`.
- Construction and rebuild: the deterministic Python generator
  `python3 tools/generate_assembly_hall_assets.py` analytically constructs a
  bright noon sky and compact solar hotspot in a fixed equirectangular order.
  It writes no timestamp or machine-dependent metadata; its alpha-map branch
  uses the renderer's pinned lossless libavif encoder.
- Licensing: the generator is Apache-2.0; the generated `.hdr` is explicitly
  dedicated under CC0-1.0.

## `textures/assembly-hall-gear-alpha.avif`

- Runtime size and encoding: 1024 x 1024, 8-bit RGBA AVIF, BT.709 primaries,
  linear transfer, identity matrix, YUV 4:4:4 full range, AV1 lossless and no
  ICC profile. The scene registers it as linear data.
- Runtime byte size and SHA-256: 3,835 bytes,
  `0a4ed9b5a52510da6b9a707f8e307b706516c8696798f5fe6cb3161e09730592`.
- Construction and rebuild: the same deterministic Python/libavif generator
  constructs the gear silhouette and alpha edge used by an alpha-clipped
  rectangle; no image model or third-party bitmap participates.
- Licensing: the generated AVIF is explicitly dedicated under CC0-1.0; the
  generator remains Apache-2.0.

## `models/showcase-panel/showcase-panel-normal.avif`

- Runtime size and encoding: 1024 x 1024, 8-bit RGB AVIF, BT.709 primaries,
  linear transfer, identity matrix, YUV 4:4:4 full range, AV1 lossless and no
  ICC profile. The scene registers it as linear data through the typed API.
- Runtime byte size and SHA-256: 262,480 bytes,
  `c9e4f7488fce3f84c021985e62224e1657eb82d814d06e52879c6e60b2f56740`.
- Convention: tangent-space OpenGL/+Y. The OBJ has complete UVs and explicit
  `+Z` normals; its two triangles exercise the renderer's generated tangent
  frame without requiring mesh duplication.
- Source and rebuild: deterministic integer construction by
  `python3 tools/generate_showcase_panel.py`. Pixel construction uses the
  Python standard library and encoding uses the renderer's pinned libavif;
  the generator is licensed under Apache-2.0.
- Licensing: the generated runtime AVIF is explicitly dedicated under
  CC0-1.0. It is a procedural data map, not an AI-generated image.

## `models/showcase-panel/showcase-panel-metallic-roughness.avif`

- Runtime size and encoding: 1024 x 1024, 8-bit RGB AVIF, BT.709 primaries,
  linear transfer, identity matrix, YUV 4:4:4 full range, AV1 lossless and no
  ICC profile. The scene registers it as linear data through the typed API.
- Runtime byte size and SHA-256: 6,197 bytes,
  `a2c09a209e4f0d49e194ab0c482fb2cf56e58d2315d4268eabb47232a4f7acee`.
- Channel layout: R is unused and constant `1.0`; G stores roughness; B stores
  metallic. No channel is color data and no sRGB decoding applies.
- Source and rebuild: deterministic integer construction by the same
  `tools/generate_showcase_panel.py` generator.
- Licensing: the generated runtime AVIF is explicitly dedicated under
  CC0-1.0. It is a procedural data map, not an AI-generated image.

The paired geometry is
`models/showcase-panel/showcase-panel.obj` (405 bytes, 4 positions, 4 UVs,
1 explicit normal and 2 triangles), SHA-256
`d907577a7da1ea01eded6ca26cde4cce0553e4f0559e211973f51d3cf5b0e5f1`.
It is also a deterministic CC0-1.0 runtime output. The independent
`models/showcase-panel/manifest.json` records all three runtime assets and is
licensed under Apache-2.0 rather than CC0-1.0.

## `models/sparky/sparky_albedo.avif`

- Runtime size and encoding: 1024 x 1024, 8-bit RGB AVIF without an alpha
  plane, BT.709 primaries,
  sRGB transfer, identity matrix, YUV 4:4:4 full range, AV1 lossless and no
  ICC profile. The decoder synthesizes opaque alpha. The scene explicitly
  registers it as sRGB through the typed texture API.
- Runtime byte size and SHA-256: 8,604 bytes,
  `1ef9ac86df962af208ec37f8401939a9fe195fa0043c9f12fed6638fe720f2be`.
- Source: AI-generated asset contributed by the project owner together with
  `sparky.obj` and `sparky.mtl`. It is not one of the two planet
  images produced by the recorded built-in imagegen workflow, and no upstream
  archive is included in the distribution.
- Use: one sRGB atlas shared by the `ScreenFace`, `ScreenChest`, and
  `ScreenPalm` material slots. The full geometry/material/file record is in
  `models/sparky/manifest.json`.
- Licensing: explicitly dedicated under CC0-1.0.

## `models/spot/spot_texture.avif`

- Runtime size and encoding: 1024 x 1024, 8-bit RGB AVIF, BT.709 primaries,
  sRGB transfer, identity matrix, YUV 4:4:4 full range, AV1 lossless and no
  ICC profile.
- Runtime byte size and SHA-256: 65,222 bytes,
  `9cb5eb3a7a184a7085c93d330698b9df324697db83a083b343a771f55b42fc16`.
- Source: the albedo bitmap in Keenan Crane's upstream
  [`spot.zip`](https://www.cs.cmu.edu/~kmcrane/Projects/ModelRepository/spot.zip)
  archive; the project converts it to its canonical AVIF profile without
  changing the decoded RGBA samples.
- Use: albedo atlas matching `models/spot/spot_triangulated.obj`; a scene must
  register it explicitly as an sRGB image texture with repeat wrapping because
  the upstream UVs extend slightly outside the unit square.
- Licensing: upstream asset dedicated under CC0-1.0 by Keenan Crane; the local
  format-only encoding does not change that dedication.

## `textures/planet-azure.avif`

- Initial imagegen bitmap (not included in the compact distribution):
  1774 x 887 RGB (exact 2:1), SHA-256
  `b09691b1d8dafbb522301fe80267d7cbd1d3f37f5e3dd486d03051cad717bb1f`.
- Seam-repair intermediate (not included in the compact distribution):
  1774 x 887 RGB, SHA-256
  `c9d6d858bdaadfb53224c0a7cec0ee61d66bf809fcb9b701abdb58c84bcc53d8`.
- Runtime processing: the initial source was rolled horizontally by 887 pixels
  so the longitude boundary appeared at canvas center; built-in imagegen
  repaired that center join using the second prompt below. ImageMagick
  6.9.10-68 rolled the repair back by -887 pixels. The first and last
  one-pixel columns were averaged and written to both edges, making every RGB
  edge pixel identical without a wide mirrored band.
- Runtime encoding: 1774 x 887, 8-bit AVIF, BT.709 primaries, sRGB transfer,
  identity matrix, YUV 4:4:4 full range, AV1 lossless and no ICC profile.
- Runtime byte size and SHA-256: 2,488,159 bytes,
  `9233abab289782a9e1f93e81e6d84d461c083227e71d1605a3e1543e08e5bd61`.
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

## `textures/planet-ember.avif`

- Initial imagegen bitmap (not included in the compact distribution):
  1774 x 887 RGB (exact 2:1), SHA-256
  `9339d0b1459ad9d5ef955a6514695ce62dac45c0c6b18f801cfcc7ad4880fd73`.
- Seam-repair intermediate (not included in the compact distribution):
  1774 x 887 RGB, SHA-256
  `e338eca937a6e510df9804d30c69e8f8b6919d06a5548591fdb0206d9e1dc009`.
- Runtime processing: the same 887-pixel roll, center repair, -887-pixel
  inverse roll and single-column edge averaging procedure used for
  `planet-azure.avif`, with ImageMagick 6.9.10-68.
- Runtime encoding: 1774 x 887, 8-bit AVIF, BT.709 primaries, sRGB transfer,
  identity matrix, YUV 4:4:4 full range, AV1 lossless and no ICC profile.
- Runtime byte size and SHA-256: 2,407,774 bytes,
  `12feceb14a29b0aba84152eb564f382c6212fc941b7a79e2bab2a677ede21fbc`.
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
