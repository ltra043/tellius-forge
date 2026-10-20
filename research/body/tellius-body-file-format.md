<h1 align="center">Tellius Body File Format</h1>

<p align="center"><i>
Reverse-engineering notes on the format of Fire Emblem 9 and Fire Emblem 10 body (<code>.gs</code>) files.<br>
See <a href="../skeleton/tellius-skeleton-file-format.md">Tellius Skeleton File Format</a> and <a href="../animation/tellius-animation-file-format.md">Tellius Animation File Format</a> for analysis of other asset formats.</i><br><br>
<b>Author:</b> Jade (ltra043)<br>
<b>Last Updated:</b> 2026-10-13 (v2.0.1: terminology: fraction bits; 2026-10-10 v2.0.0: submeshes, render passes, blended vertex buffer, skinning, unified terminology; texture reference wording, inverse bind matrix term)
</p>

<details>
<summary>Keywords</summary>

Fire Emblem assets, Fire Emblem model format, FE9 mesh format, FE10 mesh format, FE9 model format, FE10 model format, Path of Radiance mesh, Radiant Dawn mesh, Path of Radiance models, Radiant Dawn models, Tellius asset research, .gs format, GameCube mesh format, Wii mesh format, GameCube model format, Wii model format, reverse engineering, file format documentation, mesh reverse engineering, game asset research, 3D model format, Nintendo GameCube modding, Nintendo Wii modding, GameCube Modding, GC Modding, GC/Wii Modding

</details>

## Reader Information
- **All listed offsets and size values are decimal values** unless prefixed with `0x` to indicate it is a hex value.
- All multi-byte integers and floats are **big-endian** unless noted otherwise.
- All pointers are big-endian **raw pointers**: **resolved file offset = raw pointer + 0x20**. The first 0x20 bytes of the file are a generic resource header, and every pointer is relative to the end of it.
- **Model space** is the coordinate space of the whole character, in which vertex positions are stored (see [§11](#11-skinning-and-vertex-spaces)). A **bone index** is an index into the bone array of the paired skeleton (`.g`) file. See the [Skeleton note](../skeleton/tellius-skeleton-file-format.md) for *bind pose*, *seed pose*, *inverse bind matrix* and *world matrix*.
- **Triangle winding.** The GameCube treats **clockwise** triangles as front-facing, and the stored triangle strips are clockwise. This is the reverse of the counter-clockwise convention of most modern 3D tools.
- The texture images referenced by a body live in a separate `.tpl` container (one or more images); a body, its skeleton and its `.tpl` are always used together.

<details>
<summary><b>Table of Contents</b></summary>

1. [Overall Body File Layout](#1-overall-body-file-layout)
2. [File Header](#2-file-header)
3. [Vertex Tables](#3-vertex-tables)
4. [Material Table](#4-material-table)
5. [Texture References](#5-texture-references)
6. [Mesh Records](#6-mesh-records)
7. [Submesh Records](#7-submesh-records)
8. [Display Lists](#8-display-lists)
9. [Bone Palettes](#9-bone-palettes)
10. [Blended Vertex Buffer](#10-blended-vertex-buffer)
11. [Skinning and Vertex Spaces](#11-skinning-and-vertex-spaces)
12. [Rendering Rules](#12-rendering-rules)
13. [String Pool](#13-string-pool)
14. [Relocation Table](#14-relocation-table)
15. [Terminology Notes](#15-terminology-notes)
16. [Remaining Unknowns](#16-remaining-unknowns)

</details>

<details>
<summary><b>Additional Resources</b></summary>

1. **gs-texture-edits.exe**, available in the [Tellius Forge Toolkit](https://github.com/ltra043/tellius-forge/releases/latest). Edits materials and texture references and creates a detailed summary about the body data.
2. [Tellius Forge Blender plugin](https://github.com/ltra043/tellius-forge/releases/latest): supports import, modification, and export of FE9/FE10 assets.
3. [App for Tellius Unit Map Model Porting](https://github.com/ltra043/tellius-unit-model-ports): supports FE10 to FE9 porting.
4. [TelliusModding](https://github.com/klg-tellius/TelliusModding/tree/main): independent FE9 research project (readers for `.g`, `.gs`, `.ga`, and an article archive).

</details>

## Research Status

**Credits.** This reference contains Jade's own analysis, cross-checked against the independent FE9 research published in the [TelliusModding](https://github.com/klg-tellius/TelliusModding/tree/main) project by klg-tellius. Terminology differences are listed in [§15](#15-terminology-notes).

**Testing scope.**
- TelliusModding FE9 research covers the whole FE9 disc (4,422 animation files) and rebuilds every shipped `.ga` byte-for-byte, so the physical layout of the Header, Bone Table, Curve Table, Keyframe Data and FE9 Footer is **confirmed**. Its claims are **FE9-only**.
- Own testing concentrated on `ymu` (map) bodies of both games (92 FE9 and 253 FE10 bodies scanned), plus FE9 and FE10 `zu` (battle) bodies (`timt`, `saf2`, `drm2`, `reng`, `kniaUt_ax`) including in-game tests of modified files.
- Weapon (`xwp`), effect (`yme`), scenery (`zbg`) and prop (`zmap`) bodies are less studied.

<details>
<summary><b>Research Status Legend</b></summary>

- **Confirmed** = verified through direct testing, file modification, in-game debugging, or exact reproduction of the shipped files
  - Statements of fact, concluded from very strong patterns and/or in-game debugging
- **Strong evidence** = observed consistently across many files but not fully proven.
  - May be based on strong but not always applicable patterns, a smaller sample, or consistent patterns not yet confirmed in game.
  - Keywords: likely, seems, usually, corresponds
- **Reported** = plausible statement made in external references, but not verified by Jade.
  - Keywords: in other sources, independent findings, external references, other claims
- **Hypothesis** = plausible interpretation requiring further validation.
  - Keywords: possible, may be related to..., potentially, theorize

</details>

---

## 1. Overall Body File Layout

A body holds the geometry of one model: vertex data, materials, and the drawing instructions that tie them together. The blocks appear in this order:

| Order | Block | Located by |
|:---:|-------|------------|
| 1 | **Header** (0x84 bytes: 0x20 resource header + mesh header) | — |
| 2 | **Vertex Tables**: position, normal, UV, vertex color (each 4-byte aligned) | header `0x44`–`0x50` |
| 3 | **Material Table** (32 bytes each) | header `0x54` |
| 4 | **Texture References** (28 bytes each, contiguous after the Material Table) | material `+0x14` |
| 5 | **Mesh Records** (36 bytes each) | header `0x58` |
| 6 | **Submesh lists**: chains of 32-byte **Submesh Records**, render pass list 1, then 2, then 3 | header `0x5C`, `0x60`, `0x64` |
| 7 | **Display Lists** (each starts 32-byte aligned and is padded to 32 bytes) | submesh `+0x14` |
| 8 | **Bone Palettes** (32 bytes each; palette-skinned bodies) *or* the **Blended Vertex Buffer** (32-byte aligned, directly after the last display list) | submesh `+0x1C` / header `0x68` |
| 9 | **String Pool** | pointers |
| 10 | **Relocation Table** | header `0x04` |

**Confirmed** (FE9: every shipped file rebuilds from this order and alignment).

**Body categories.**

| Folder | Content | Skinning | Notes |
|--------|---------|----------|-------|
| `ymu/<model>/` | Map model body (also used for combat on the map) in `pack.cmp` | single bone, bone palette | at most 853 visible triangles; FE9: one submesh list; FE10: up to three |
| `zu/<model>/` | Battle model body in `<model>_<wp>.pak` (FE9) or `pack.cmp` (FE10) | blended (every visible submesh), hidden weapon placeholders | at most 8,840 visible triangles |
| `yme/` | Spell effects | single bone | 7,399 of 7,515 effect submeshes are in render pass 3 |
| `xwp/` | Weapons (bows are blended) | single bone, blended for bows | about half the submeshes are hidden (`scale=0`) |
| `zmap/` | Map props, ships (blended) | single bone, blended | |
| `zbg/` | Battle scenery | single bone | |

Blended skinning is used by 324 bodies: every `zu` model, bows (`xwp`), and ships (`zmap`). **Strong evidence.**

---

## 2. File Header

**Size:** 0x84 bytes. **Location:** 0x00. The first 0x20 bytes are a generic resource header (file size, relocation table); the mesh header starts at 0x20.

> Offsets `0x44`–`0x68` hold pointers; pointers that are absent are 0.

| Offset | Size | Field | Notes |
|--------|------|-------|-------|
| `0x00` | uint32 | File size | |
| `0x04` | uint32 | Raw ptr → Relocation Table | |
| `0x08` | uint32 | Relocation entry count | |
| `0x0C` | 20 bytes | Reserved | 0 in observed files (probably symbol import/export counts of the generic resource header; **hypothesis**). |
| `0x20` | uint32 | Raw ptr → root name string (`unknown`) | |
| `0x24` | 4 bytes | Export date tag | `20 04 07 23` (2004-07-23) in almost every model. |
| `0x28` | 4 bytes | Model id | Per-model value; purpose unknown. |
| `0x2C` | 24 bytes | Bounding box (AABB, 6 floats) | min XYZ, max XYZ, in model space. May exceed the vertex extent (see [§11](#11-skinning-and-vertex-spaces)). |
| `0x44` | uint32 | Raw ptr → Position Table | |
| `0x48` | uint32 | Raw ptr → Normal Table | |
| `0x4C` | uint32 | Raw ptr → UV Table | |
| `0x50` | uint32 | Raw ptr → Vertex Color Table | |
| `0x54` | uint32 | Raw ptr → Material Table | |
| `0x58` | uint32 | Raw ptr → first Mesh Record | |
| `0x5C` | uint32 | Raw ptr → submesh list, render pass 1 | |
| `0x60` | uint32 | Raw ptr → submesh list, render pass 2 | |
| `0x64` | uint32 | Raw ptr → submesh list, render pass 3 | |
| `0x68` | uint32 | Raw ptr → Blended Vertex Buffer | Present in `zu`, bow and ship bodies. |
| `0x6C` | uint16 | Position count | Regular Vertex Tables only; blended vertices are counted in the Blended Vertex Buffer. |
| `0x6E` | uint16 | Normal count | |
| `0x70` | uint16 | UV count | |
| `0x72` | uint16 | Vertex color count | 0 when `0x50` is 0. |
| `0x74` | uint16 | Material count | |
| `0x76` | uint16 | Mesh Record count | May be smaller than the submesh count. |
| `0x78` | uint16 | Submesh count | Sum of the lengths of the three lists. |
| `0x7A` | uint16 | Reserved | Always 0. |
| `0x7C` | uint8 | Position fraction bits | Position = `raw / (1 << n)`. |
| `0x7D` | uint8 | Normal fraction bits | |
| `0x7E` | uint8 | UV fraction bits | |
| `0x7F` | uint8 | Reserved | Always 0. |
| `0x80` | uint32 | Padding | 0. |

The **fraction bits** are the number of fractional bits of a fixed-point value: `value = raw / 2^n`. Examples: `ymu` positions use 9–10, FE9 battle bodies have 14 in the header (their positions come from the Blended Vertex Buffer, which has its own fraction bits), battle-body UV fraction bits 13–14. A body with no regular table (`timt`, `drm2`) has 0 in `0x6C`/`0x6E` and null table pointers.

A body may have three lists, but a given body usually uses one or two. All 92 scanned FE9 `ymu` bodies have a single list; about two dozen of 253 FE10 `ymu` bodies have two or three. **Strong evidence.**

---

## 3. Vertex Tables

**Location:** after the header (0x84). Tables are stored sequentially: **Position** → **Normal** → **UV** → **Vertex Color**. Each table's start is given by a header pointer; an absent table has a null pointer. Submeshes that draw from the Vertex Tables refer to entries by 16-bit index (a table can hold up to 65,535 entries).

### Position Table
- **Entry:** `int16 × 3` (6 bytes). **Decode:** `x = raw / (1 << position fraction bits)`.
- **Alignment:** 4-byte. With an odd count, 2 zero bytes follow the last entry so the Normal Table is aligned. A misaligned array base makes the GPU display garbage or nothing at all. **Confirmed** in game.

### Normal Table
- **Entry:** `int8 × 3` (3 bytes). **Decode:** `n = raw / (1 << normal fraction bits)`.
- The table is padded at the end to a 4-byte boundary.

### UV Table
- **Entry:** `int16 × 2` (4 bytes). **Decode:** `u = raw / (1 << uv fraction bits)`, same for v.
- GX texture coordinates have their origin at the top-left. In a tool with a bottom-left origin, use `v' = 1 − v`.

### Vertex Color Table
- **Entry:** `uint8 × 4` (RGBA). **Purpose:** per-vertex multipliers on the lighting of a submesh.
- A submesh uses colors only if its attribute flags have the color index bit set ([§7](#7-submesh-records)); each display-list vertex then carries a color index. Use is per submesh, not per file: a single body can mix colored and uncolored submeshes.
- If `0x50` and `0x72` are 0 the body has no table and the game uses its default lighting (normal-based directional lighting). A uniform white entry (255, 255, 255, 255) applies the maximum lighting multiplier. `saf2` has one white entry used by one submesh.

---

## 4. Material Table

**Entry size:** 32 bytes. **Location:** header `0x54`. **Count:** header `0x74`.

| Offset | Size | Field | Notes |
|--------|------|-------|-------|
| `+0x00` | uint32 | Raw ptr → material name | Often `lambert*` (Maya shader names, e.g. `lambert28`). |
| `+0x04` | 2 bytes | Padding | 0. |
| `+0x06` | uint8 | Texture Reference count | A material may have 0 (`timt` `lambert1`, the hidden weapon placeholder material). |
| `+0x07` | uint8 | Padding | 0. |
| `+0x08` | 4 bytes | Diffuse color RGBA | The engine multiplies this color by **1.25 when the body is first loaded** (each channel capped at 255), so a stored gray of 204 draws as full white. **Reported.** |
| `+0x0C` | 4 bytes | Second color RGBA | Possibly specular. **Hypothesis.** |
| `+0x10` | 4 bytes | Third color RGBA | Always 0 in observed unit body files. May be shadow coloring for maps. **Hypothesis** |
| `+0x14` | uint32 | Raw ptr → first Texture Reference | |
| `+0x18` | 8 bytes | Padding | 0. |

---

## 5. Texture References

**Entry size:** 28 bytes (0x1C). **Location:** contiguous after the Material Table; the first reference of each material is given by material `+0x14`.

A Texture Reference links a material to one **image** of the `.tpl` container. The layers, from smallest to largest, are: *image* (inside the `.tpl`) → *Texture Reference* (image index and UV scale) → *material* (name, colors, one or more Texture References) → *submesh* (names its material by index). Several materials can use the same image, and one material can use several images.

| Offset | Size | Field | Notes |
|--------|------|-------|-------|
| `+0x00` | uint8 | Reserved | 0. |
| `+0x01` | uint8 | Constant | 1 in observed files; possibly an enable marker. |
| `+0x02` | uint16 | Padding | 0. |
| `+0x04` | uint16 | **Image index** | 0-based index of the image in the `.tpl` container. The high byte is 0. |
| `+0x06` | uint8 | Sampling flag 0 | 1 in all character models; 0 in the last reference of some `bmap*` models. Meaning unknown. |
| `+0x07` | uint8 | Sampling flag 1 | Same behavior. |
| `+0x08` | 8 bytes | Padding | 0. |
| `+0x10` | float32 | UV scale X | 1.0 = `3F 80 00 00`. |
| `+0x14` | float32 | UV scale Y | |
| `+0x18` | uint32 | Padding | 0. |

A new material needs a 32-byte Material Table entry plus one Texture Reference whose image index is the next free image of the `.tpl`. The new material's name is appended to the String Pool. A material already named in the file can be reused by name instead. **Confirmed** (an image appended to the `.tpl` loads correctly in game).

---

## 6. Mesh Records

**Entry size:** 36 bytes (32 bytes of data + 4 bytes padding). **Location:** header `0x58`. **Count:** header `0x76`.

A **mesh** is a named object with a bone and bounding box; it owns one or more submeshes, which refer to it by pointer. Several submeshes may share one mesh record (`timt`: 41 submeshes, 35 mesh records; one FE10 `ymu` body: 12 and 11). **Strong evidence.**

| Offset | Size | Field | Notes |
|--------|------|-------|-------|
| `+0x00` | uint32 | Raw ptr → mesh name | The same string can be shared by several records. Not known to be used by the engine. |
| `+0x04` | float32 × 3 | Bounding box min XYZ | See [§11](#11-skinning-and-vertex-spaces). |
| `+0x10` | float32 × 3 | Bounding box max XYZ | |
| `+0x1C` | uint16 | **Bone index** | The bone the mesh belongs to. Equals the first bone of the mesh's bone palette when it has one. |
| `+0x1E` | 6 bytes | Padding | 0. |

A new mesh record whose bounds come from its own vertices and whose bone is set works in game. **Confirmed.**

---

## 7. Submesh Records

A **submesh** is the part of a mesh that is drawn with one material in one draw call. Submeshes are chained: each record points to the next, and the last has a null next pointer.

**Entry size:** 32 bytes. **Location:** the three header pointers `0x5C`, `0x60`, `0x64` each start a chain; the records are stored contiguously in order (chain 1, then 2, then 3).

| Offset | Size | Field | Notes |
|--------|------|-------|-------|
| `+0x00` | uint32 | Raw ptr → Mesh Record | |
| `+0x04` | uint32 | Raw ptr → next submesh | 0 = last in its list. |
| `+0x08` | uint16 | **Submesh flags** | See below. |
| `+0x0A` | uint16 | Material index | |
| `+0x0C` | uint16 | Bone index | 0 for palette-skinned submeshes. For a single-bone submesh the bone the submesh follows. For a blended submesh only a label (skinning comes from the weight records). |
| `+0x0E` | 3 bytes | Padding | 0. |
| `+0x11` | uint8 | Reserved | 0x80 in every blended-body submesh examined. |
| `+0x12` | uint8 | **Attribute flags** | See below. |
| `+0x13` | uint8 | Reserved | |
| `+0x14` | uint32 | Raw ptr → Display List | |
| `+0x18` | uint32 | Display List size (bytes) | |
| `+0x1C` | uint32 | Raw ptr → Bone Palette | 0 when none (always 0 in blended bodies). |

### Submesh flags (`+0x08`)

| Bits | Mask | Meaning | Evidence |
|:---:|:---:|---------|---|
| 0 | `0x0001` | **Blended**: vertices come from the Blended Vertex Buffer (clear: the Vertex Tables). | Confirmed |
| 1 | `0x0002` | **Skinning byte present** in every display-list vertex (bone palette skinning). Never set together with bit 0. | Confirmed |
| 2–3 | `0x000C` | **Material state.** Clear = the submesh is a **material leader** that sets up its material (textures). `0x0C` = it **inherits** the previous submesh's material state. `ymu`: leader `0x02`, inherit `0x0E`; `zu`: leader `0x01`, inherit `0x0D`. | Confirmed (a new leader loads its textures); strong (inherit) |
| 4 | `0x0010` | Meaning unknown (seen on one submesh of `kniaUt_ax`). | — |
| 10 | `0x0400` | **Hidden**: the draw routine skips the submesh (see [§11](#11-skinning-and-vertex-spaces)). | Confirmed |
| 11–12 | `0x1800` | **Culling.** `0x1000` back faces culled; `0x0800` front faces culled (unused on the disc); `0x1800` both set = nothing culled (double-sided). | Confirmed |
| 13–14 | `0x6000` | **Render pass + 1**: `0x2000` pass 1, `0x4000` pass 2, `0x6000` pass 3. Equals the list the submesh is stored in. No engine reader for these bits has been found. | Strong |

Shipped counts: 3,469 submeshes back-culled, 13,686 double-sided. The high byte therefore reads `0x3x` in list 1, `0x5x` in list 2, `0x7x` in list 3; `0x30` = back-culled, `0x38` = double-sided.

A material leader that is removed or reordered breaks the run: a submesh whose inherited state no longer follows a submesh with the same material must be made a leader.

### Attribute flags (`+0x12`)

Describe which fields appear in each display-list vertex.

| Bit | Mask | Meaning |
|:---:|:---:|---------|
| 4 | `0x10` | **Color index present** (a Vertex Color Table index in every vertex). |
| 7 | `0x80` | **Second UV present** (a second UV index in every vertex). |
| 1, 2, 6 | `0x46` | Always set; probably position, normal and UV index present (**hypothesis**). |

Common values: `0x46` (no color), `0x56` (color index).

---

## 8. Display Lists

**Location:** submesh `+0x14` (size at `+0x18`). A display list is a ready-made GameCube GPU command stream that the engine hands to the hardware unchanged; the first byte of each command is an opcode. Every body uses the opcode `0x98`, **draw triangle strip**: `0x98`, a uint16 vertex count, then one entry per vertex. Lists begin 32-byte aligned and are padded with zeros to 32 bytes.

**Vertex entry** (fields in this order):

| Field | Present when | Bytes |
|-------|--------------|:---:|
| Skinning byte | submesh flags bit 1 | 1 |
| Position index | always | 2 |
| Normal index | always | 2 |
| Color index | attribute flags bit 4 | 2 |
| UV index | always | 2 |
| Second UV index | attribute flags bit 7 | 2 |

- Indices point into the Vertex Tables, or, for a blended submesh, into the **vertex slots** of the Blended Vertex Buffer (where the normal index always equals the position slot).
- The **skinning byte** divided by 3 is the **palette slot** (GX matrix indices are multiples of 3, one per 3×4 matrix).
- Strip structure is free: rebuilt lists with many shorter strips (for example 244 strips instead of 73) work in game, as do strips of at most 48–55 vertices instead of the original 97–133. **Confirmed.**

---

## 9. Bone Palettes

**Size:** 32 bytes per palette. **Location:** submesh `+0x1C`, stored after all display lists. Present only on submeshes with the skinning byte flag; blended bodies have none.

| Offset | Field | Notes |
|--------|-------|-------|
| `+0` | Marker | Always `0x10`. |
| `+1` | Bone count N | At most 10 (the GameCube has 10 hardware matrix slots). |
| `+2` … `N+1` | Bone indices | Ascending. The same bone can appear in several palettes. |
| `N+2` | Padding | Zeros up to 32 bytes. |

A vertex's skinning byte `/ 3` selects a bone in its submesh's palette. The palette's bones are loaded into the hardware as `world[bone] × inverse_bind[bone]` ([§11](#11-skinning-and-vertex-spaces)).

**FE9 exception:** the last palette is not padded; the String Pool begins immediately after its last bone index.

---

## 10. Blended Vertex Buffer

**Location:** header `0x68`. Used by blended submeshes (submesh flags bit 0). The buffer replaces the regular position and normal tables for them: blended submeshes index **vertex slots** of this buffer instead. Each frame the engine blends the slots by the weights of their records.

### Buffer header (16 bytes)

| Offset | Size | Field | Notes |
|--------|------|-------|-------|
| `+0x00` | uint32 | Offset of the weight records | Always `0x10`. |
| `+0x04` | uint32 | Offset of the vertex slots | From the buffer start. |
| `+0x08` | uint16 | Weight record count | |
| `+0x0A` | uint16 | Vertex slot count | |
| `+0x0C` | uint8 | **Fraction bits** | Position and normal = `raw / (1 << n)`. Shipped files use 5–11 fraction bits (`drm2` 7, `timt` 8, `saf2` 8, `kniaUt_ax` 11). |
| `+0x0D` | uint8 | Padding | |
| `+0x0E` | uint16 | Number of records that hold more than one vertex | No engine reader found. **Strong evidence** (value pattern: 362 = 362 on `kniaUt_ax`). |

### Weight records (24 bytes each)

| Offset | Size | Field | Notes |
|--------|------|-------|-------|
| `+0x00` | int16 × 4 | Bone indices | −1 = unused. |
| `+0x08` | uint8 × 4 | Weights, out of 256 | **Not renormalized.** 0 in one-bone records (which skip the blend). Some original records sum to 255 or 257; weights normalized to 256 load correctly. |
| `+0x0C` | uint32 | Block offset | 32-aligned start of the record's first block; every record starts a fresh block. |
| `+0x10` | uint16 | Block size | Bytes moved per record: a multiple of 32, at most 4 KiB. |
| `+0x12` | uint8 | First vertex | Offset of the first vertex within the block: the next multiple of 12 (0, 4 or 8). |
| `+0x13` | uint8 | Bone count | 1–4. |
| `+0x14` | uint16 | Vertex count | |
| `+0x16` | uint16 | Binormal/tangent count | 0 on the disc. |

A record covers the vertex slots `(block offset + first vertex) / 12 …` for `vertex count` slots. Records are contiguous in slot order, so every non-null slot belongs to exactly one record. **Confirmed** (rebuilt from the vertex slots, matches on `kniaUt_ax`, `timt`, `saf2`).

### Vertex slots (12 bytes each)

`int16 × 6`: position XYZ, normal XYZ, both at the buffer's fraction bits. Null slots (all zero) are block-alignment gaps and are not referenced. Unreferenced slots may be dropped.

**Blending.** Per frame, per record: the slots are moved into the CPU's locked cache in whole 32-byte blocks, blended and written to a per-actor output buffer; the submeshes then draw that output with only the actor's own matrix. A vertex weighted to bones `b_i` is drawn at `Σ w_i · world[b_i] × inverse_bind[b_i] × vertex` with at most four bones. The output must fit `int16` at the buffer's fraction bits, so animations that carry the model far from its origin (up to about five times the body's rest size) need fewer fraction bits. **Confirmed.**

**Normals.** The stored normals are the outward surface normals of the engine's clockwise-front convention; deriving normals from the stored winding with the usual counter-clockwise rule gives the opposite direction. **Strong evidence** (−0.89 mean dot product on `timt`).

---

## 11. Skinning and Vertex Spaces

### 11.1 Skinning modes

| Mode | Selected by | How a vertex follows the skeleton |
|------|-------------|-----------------------------------|
| **Single bone** | skinning byte and blended bit both clear | The whole submesh moves with the submesh's bone: it is drawn with `world[bone]`. |
| **Bone palette** | skinning byte present (bit 1) | The submesh lists up to 10 bones; each vertex names one of them by its skinning byte. Drawn with `world[bone] × inverse_bind[bone]`. |
| **Blended** | blended bit (bit 0) | Up to 4 bones per vertex, weighted, blended on the CPU ([§10](#10-blended-vertex-buffer)). |

A body can combine modes: a battle body may have a single-bone submesh (weapon placeholder) next to blended ones. A battle body rebuilt with multi-bone hardware submeshes instead of blended ones draws those parts out of place in battle, for a reason not yet traced (**confirmed** in game).

### 11.2 Skinning is per display-list occurrence

Skinning in palette-skinned bodies belongs to each **occurrence** of a vertex in a display list, not to the table vertex. The same Vertex Table entry can appear in several strips with different skinning bytes, so one table vertex can be drawn under two or more bones. Two patterns occur (FE9 `ymu`: 22 of 92 bodies, 123 vertices; FE10 `ymu`: 55 of 253 bodies, 371 vertices): **strong evidence.**
- **Instancing:** the same triangles are drawn twice, under two bones, with shared table vertices (`general_bl`: 16 triangles under `pCube5` and `pCube8`; also the fangs, talons, books and hazes of other models). Probably one mesh placed twice and shown or hidden by scale keys (**hypothesis**).
- **Seam vertices:** rigid strips share vertices with a neighboring bone's strips (`Tail2`/`Tail3`, `Face`/`Hair`, `chest`/`shoulder_l`).

Submeshes with true one-bone-per-vertex skinning contain triangles whose corners use different bones, with each vertex having exactly one bone. This is normal.

### 11.3 Vertex spaces

- **Character bodies** store vertices in **model space** in the bind pose; the bones turn about their pivots. The header bounding box is in model space.
- **Single-bone submeshes of static props** store vertices in the bone's **local space**: the engine draws them through the bone's world matrix. For an unanimated prop that is the chain of seed matrices; the map cursor's arrow, for instance, is stored at unit size and scaled up and raised by its two bones.
- **Mesh Record bounds** are stored per bone. In most bodies they match the extent of the mesh's vertices to within 0.01 (`timt`), but in some (`drm2`) they are in seed-pose space, offset from the vertices by the reference translation (Z −5).
- The header bounding box may exceed the vertex extent (`timt`: Y minimum −8.28 against vertices starting at 0.0), perhaps because it includes a posed or animated extent (**hypothesis**).

### 11.4 Hidden submeshes

The draw routine skips any submesh with the hidden flag (`0x0400`) and no code that changes it has been found. 81 battle bodies use it for weapon placeholders: meshes of the weapons the character can hold, each assigned to a bone named after its weapon type (`SW`, `AX`) while its vertices are weighted to the hand socket. The weapon actually shown in battle is the separate model of the equipped item. About half the submeshes of the weapon models themselves are hidden too, for a purpose not yet known. **Strong evidence** (`timt` submeshes 28 and 29: flags `0x3C01`, `0x3C0D`).

### 11.5 Weapon sockets and anchors

The game attaches the equipped weapon to the body's hand bone by name (the left hand for bows, the right hand otherwise) through the **anchor bones** of the skeleton. Hidden placeholders sit on socket bones wrapped in underscores (`_r_hand_`) or on bow and arrow bones (`BW001`, `_ar1_`); visible geometry essentially never uses them, and the camera, root and foot sockets carry none at all.

### 11.6 Two kinds of bone (see the Skeleton note, Pivot Bones and Offset Bones)

Most bones of a battle body are placed by an offset from their parent (offset bones) and have no rest rotation; a few (`Base`, weapon, target) turn about a pivot at their joint, which is how every bone of a map model works.

---

## 12. Rendering Rules

### 12.1 Render passes

The camera draws every model's first submesh list, then every second list, then every third, each with fixed GPU settings. The list a submesh is stored in decides how the transparency of its texture is treated.

| List | Pass | Settings | Used for |
|:---:|------|----------|----------|
| 1 (`0x5C`) | **Opaque** | No blending; texture alpha ignored; depth written | Solid geometry: weapons, ground, cliffs, most map models |
| 2 (`0x60`) | **Alpha-tested** | Pixels with alpha below 128 are discarded; depth tested after texturing and written | Cut-outs: leaves, grass cards, and about half of all battle submeshes |
| 3 (`0x64`) | **Blended** | Blended by alpha; depth tested but not written | Translucent effects: 7,399 of the 7,515 spell-effect submeshes, most of them also additive |

**Confirmed** (engine and in game). Cut-out textures are stored as CMPR with 1-bit alpha in the format's three-color block mode, whose fourth color is transparent; scenery with its leaf submeshes moved to the opaque list draws transparent pixels as dark blocks. Some model states override the lists and draw a whole model opaque, alpha-tested or blended.

Submesh flags also request additive, subtractive and depth-off blending for individual submeshes (in the blend and depth flags of the render pass setup).

### 12.2 Culling and winding

Culling uses submesh flags bits `0x1800` ([§7](#7-submesh-records)). Front faces are the **clockwise** ones. An actor-side flag can swap front and back and make double-sided submeshes cull everything. **Confirmed.**

### 12.3 Material state

Materials are loaded once per run of submeshes that share a material: the **material leader** sets up the material and the following submeshes with the inherit bits reuse its state. Material colors are multiplied by 1.25 at load ([§4](#4-material-table)).

---

## 13. String Pool

A block of null-terminated strings: material names, mesh names, and the root name `unknown`; `none` also occurs. The pool is sorted alphanumerically ascending; the strings `none` and `unknown` appear in every sample. In FE9 `ymu` bodies it begins immediately after the last bone palette; in blended bodies it follows the Blended Vertex Buffer. It ends where the Relocation Table begins.

---

## 14. Relocation Table

A sorted list of big-endian uint32 values at the end of the file, one for every **pointer field** between the end of the header and the start of the table. Each value is the raw offset of a pointer field (file offset − 0x20); null pointers are not listed. The table location and entry count are header `0x04` and `0x08`. The game loader adds 0x20 to every listed field. The pointer to the Blended Vertex Buffer (raw `0x48`, header `0x68`) is listed too. **Confirmed.**

---

## 15. Terminology Notes

Other documents, tools and earlier versions of these notes use different words for some of the same things. This reference uses the left-hand term. (The full catalogue, including the other formats, is kept in `terminology.md`.)

| This reference | Also seen as |
|---|---|
| submesh | chunk; shape; draw call |
| Submesh Record | Chunk Descriptor |
| mesh record | PtrA block; mesh |
| submesh flags | format word; primitive type |
| bone palette | GX cache; bone subset |
| display list | GX display list |
| skinning byte | `sb` byte; matrix index |
| inverse bind matrix | skin matrix; bind matrix; inverse-bind matrix |
| Blended Vertex Buffer | IVB; composite buffer; CB |
| weight records | skinning records; gap records |
| vertex slot | composite slot |
| Vertex Color Table | lighting multiplier table; vertex colors |
| Texture Reference | TPL info block |
| image index | TPL slot index; TPL texture slot |
| Sampling flag 0 / Sampling flag 1 | Sampling flag A / B |
| Material Table | Materials List |
| Relocation Table | Reloc Table |
| fraction bits | scale exponent; scale shift |
| bounding box | AABB |
| render pass lists | alternate chunk list locations |
| color index present / second UV present | `hc` / `hu` |

---

## 16. Remaining Unknowns

- Meaning of submesh flags bit 4 (`0x10`) and of the constant `0x80` at submesh `+0x11`; whether bits 1, 2, 6 of the attribute flags mean position, normal and UV present.
- Why the original header bounding box exceeds the vertex extent.
- Whether a **visible** single-bone submesh draws correctly in a battle body (a single-bone weapon submesh of `kniaUt_ax` stores coordinates around its bone's position in model space; how the engine transforms such submeshes is not verified).
- Whether the engine really treats the three lists as the passes above for FE10 bodies that mix them, and what happens after a tool collapses them into one list.
- The role of the `0x6000` submesh flag bits and of the buffer header field at `+0x0E`.
- The purpose of the unreferenced Vertex Table entries (16–70 per `ymu` file).
- The meaning of the second and third material color, the sampling flags of Texture References, and the model id at header `0x28`.
- Why the file order inside the pack archive matters for mounted-unit battle bodies (`timt`, `drm2`, `kni1`) but not for infantry (observed; cause unknown).
- Whether the second UV and multiple Texture References per material are used by any shipped body.