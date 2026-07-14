# Example asset manifest

Runtime image paths are relative to this directory. The four PNG textures were
generated for this project on 2026-07-07 through the built-in `imagegen`
workflow. They are provided as-is, without a representation of uniqueness or
exclusivity. The Radiance HDR environment is an analytical, deterministic
output of the Apache-2.0 Python generator in `tools/`, not an AI-generated
image.

The compact distribution omits PNG generation, chroma-key, and seam-repair
intermediate bitmaps; their dimensions, processing steps, prompts, and SHA-256
digests remain recorded below.

The seam-repair edits preserve the maps' composition and palette visually, but
the image model lightly redrew pixels outside the requested center band rather
than keeping those regions byte-identical. The initial-bitmap digests remain in
this manifest so this distinction stays auditable.

The four runtime texture PNG files and the HDR environment listed here are
dedicated under CC0-1.0. This Markdown sidecar is licensed under Apache-2.0 and
is not a signed provenance claim. Only textures/circuit-panel.png retains an
embedded caBX/JUMBF C2PA structure identifying OpenAI Media Service;
cryptographic validity is not verified by this project. The other three
post-processed runtime textures do not retain C2PA data.

## `environments/radiance-pavilion.hdr`

- Runtime size and encoding: 2048 x 1024 Radiance RGBE, linear Rec.709 RGB,
  `FORMAT=32-bit_rle_rgbe`, `-Y 1024 +X 2048`, modern per-component scanline
  RLE.
- Runtime byte size: 298,600 bytes.
- Runtime SHA-256:
  `610ce6a4875c62e5e5cdef4a233c9153755c29d388d84e4550f3c539cbafb186`.
- Deterministic rebuild:
  `python3 tools/generate_hdr_environment.py`.
- Construction: an analytical dim cyclorama and floor bounce are combined
  with four feathered spherical studio panels: a warm key, cool vertical fill,
  neutral overhead strip and amber rim. Pixel centers are sampled in a fixed
  equirectangular order, converted directly to RGBE, then encoded with a fixed
  literal/run partition. The file has no timestamp or machine-dependent
  metadata.
- Licensing: the generator is Apache-2.0; the generated `.hdr` file is one of
  the visual assets explicitly dedicated under CC0-1.0.

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

## `textures/koi-mask.png`

- Chroma-key bitmap (not included in the compact distribution):
  1024 x 1536 RGB PNG, SHA-256
  `99ea9e5d48b77433b7ee74fe67090d20283d056c46101e037afacb4581a8e1d0`.
- Runtime result: 1024 x 1536 RGBA PNG,
  SHA-256 `fd4376986b5622043fdb63386bc02450f9ec162d7f4517ebb154e45e3052bf60`.
- Processing: the installed imagegen `remove_chroma_key.py` helper, auto-key
  sampled from the border (`#03f80a`), soft matte, transparent threshold 12,
  opaque threshold 220, and despill (`--spill-cleanup`). Validation found all
  four corners transparent, alpha bounding box `(258, 110, 763, 1415)`,
  1,310,422 transparent pixels, 4,545 partially transparent pixels, and
  257,897 fully opaque pixels.
- Prompt:

```text
Use case: background-extraction
Asset type: alpha-mask source and decorative koi cutout texture for offline ray tracing
Primary request: a single elegant koi fish viewed perfectly from directly overhead, full body from nose to tail, gently curved swimming pose, opaque graphic silhouette with crisp readable fins.
Scene/backdrop: perfectly flat solid #00ff00 chroma-key background for background removal. The background must be one uniform color with no shadows, gradients, texture, reflections, floor plane, or lighting variation.
Subject: original koi with warm vermilion-orange and ivory-white patches, a few charcoal accents, coherent scales, symmetrical pectoral fins, complete uncut tail and whiskers; do not use green anywhere on the fish.
Style/medium: polished hand-painted natural-history cutout, clean opaque edges, subtle internal detail but no translucent fins.
Composition/framing: centered top-down orthographic view, fish fills about 75 percent of canvas height, generous green padding on all sides, no cropping.
Lighting/mood: flat diffuse color with no cast shadow, contact shadow, rim glow, or reflection.
Constraints: no other fish, no plants, no water, no bubbles, no text, no watermark, no frame; preserve one continuous clean silhouette suitable for chroma-key removal.
```

## `textures/circuit-panel.png`

- Generated source size: 1536 x 1024 RGB PNG.
- Runtime processing: none.
- Embedded provenance: caBX/JUMBF C2PA structure retained; signature validity
  is not asserted by this manifest.
- SHA-256: `9361c04d5fab6098676cee2f65efb8d222246ddba0b1828a7ab4088f9f05f0be`
- Prompt:

```text
Use case: stylized-concept
Asset type: seamless wall albedo texture for an offline ray-traced neon laboratory
Primary request: Create an original futuristic circuit-panel surface texture with no lettering.
Scene/backdrop: full-frame flat rectangular material swatch, edge-to-edge, viewed straight-on with no perspective.
Subject: matte near-black graphite panels, fine cyan and magenta luminous circuit traces, small copper contacts, subtle ceramic insets, balanced dense technical pattern.
Style/medium: premium hard-surface sci-fi material texture, detailed but readable, original non-branded design.
Composition/framing: tileable horizontal and vertical repeat; no focal object; distribute motifs so opposite edges join cleanly.
Lighting/mood: flat albedo/emissive design information only, no directional light, shadows, reflections, depth-of-field, vignette, or baked perspective.
Constraints: absolutely no text, numbers, letters, logos, UI labels, watermark, border, frame, screws cut at awkward edges, or recognizable brand marks; avoid broad pure-white areas.
```
