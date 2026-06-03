<h1 align="center">Tellius Body File Format</h1>

<p align="center"><i>
Reverse-engineering notes on the format of Fire Emblem 9 and Fire Emblem 10 body (<code>.gs</code>) files.<br>
See <a href="../skeleton/tellius-skeleton-file-format.md">Tellius Skeleton File Format</a> and <a href="../animation/tellius-animation-file-format.md">Tellius Animation File Format</a> for analysis of other asset formats.</i><br><br>
<b>Author:</b> Jade (ltra043)<br>
<b>Last Updated:</b> 2026-06-01
</p>

<details>
<summary>Keywords</summary>

Fire Emblem assets, Fire Emblem model format, FE9 mesh format, FE10 mesh format, FE9 model format, FE10 model format, Path of Radiance mesh, Radiant Dawn mesh, Path of Radiance models, Radiant Dawn models, Tellius asset research, .gs format, GameCube mesh format, Wii mesh format, GameCube model format, Wii model format, reverse engineering, file format documentation, mesh reverse engineering, game asset research, 3D model format, Nintendo GameCube modding, Nintendo Wii modding, GameCube Modding, GC Modding, GC/Wii Modding

</details>

## Reader Information
- **All listed offsets and size values are decimal values** unless prefixed with `0x` to indicate it is a hex value.
- All multi-byte integers and floats are **big-endian** unless noted otherwise.
- All pointers are big-endian, raw values that need to be **offset +0x20**
  - **resolved file offset** = `raw_pointer + 0x20`

<details>
<summary><b>Table of Contents</b></summary>

1. [Overall Body File Layout](#1-overall-body-file-layout)
2. [File Header](#2-file-header)
3. [Vertex Tables](#3-vertex-tables)
4. [Materials List](#4-materials-list)
5. [TPL Info Blocks](#5-tpl-info-blocks)
6. [PtrA Blocks](#6-ptra-blocks)
7. [Chunk Descriptors](#7-chunk-descriptors)
8. [GX Display List](#8-gx-display-list)
9. [GX Cache / Bone Palette](#9-gx-cache--bone-palette)
10. [Interleaved Vertex Buffer (IVB)](#10-interleaved-vertex-buffer-ivb)
11. [String Pool](#11-string-pool)
12. [Reloc Table](#12-reloc-table)
13. [Remaining Unknowns](#13-remaining-unknowns)

</details>


<details>
<summary><b>Additional Resources</b></summary>
1. **gs-texture-edits.exe**, available in the [Tellius Forge Toolkit](https://github.com/ltra043/tellius-forge/releases/latest). This allows editing of material and texture slots and creates a detailed summary about the body data.
2. [Tellius Forge Blender plugin](https://github.com/ltra043/tellius-forge/releases/latest): supports import, modification, and export of FE9/FE10 assets.
3. [App for Tellius Unit Map Model Porting](https://github.com/ltra043/tellius-unit-model-ports): supports FE10 to FE9 porting  

</details>

## Research Status

**Testing Scope:**
The following observations are primarily based on comparison of `ymu` body files.

While some other body files have been investigated, there is less conclusive information about them. This includes body files from map assets in `zmap` and battle models in `zu`.

<details>
<summary><b>Research Status Legend</b></summary>

- **Confirmed** = verified through direct testing and file modification
  - Statements of fact, concluded from very strong patterns and/or in-game debugging
- **Strong evidence** = observed consistently across many files but not fully proven.
  - May be based on strong but not always applicable patterns.
  - May be based on a smaller sample size.
  - May be very consistent but not yet confirmed in-game.
  - Keywords: likely, seems, usually, corresponds
- **Hypothesis** = plausible interpretation requiring further validation. 
  - May be based on observations and trends from only a few samples. 
  - Untested or difficult to verify.
  - Keywords: Possible, may be related to..., potentially, theorize

</details>

---

## 1. Overall Body File Layout

|Offset | Content | Notes |
|-------|---------|-------|
| `0x00` | Header | Contains info about the file and pointers to each major section |
| `0x84` (if present) | Vertex Tables | **Position** → **Normal** → **UV** → **Lighting Multiplier** tables. Each table's start offset is stored as a raw pointer in the header (`0x44`/`0x48`/`0x4C`/`0x50`) |
| Raw pointer in header at `0x54` | Materials List | Contains per-material metadata and links to associated texture(s).|
| Raw pointer in **Materials List** entries at offset `0x14` | TPL Info Blocks | Contains **per-texture metadata** including TPL slot assignment, UV scaling, and unknown fields. There is one or more texture per Material. |
| Raw pointer in header at `0x58` | "PtrA" Blocks | Per-chunk metadata blocks. PtrA is a custom term created for the plugin. |
| Raw pointer in header at `0x5c`, `0x60`, or `0x64` | Chunk Descriptors | **Chunk:** A subdivision of a mesh that groups geometry with associated rendering metadata. Each chunk is represented by a Chunk Descriptor and is rendered independently. <br><br> Chunk Descriptors link to associated materials, bone palettes, and GX Diaplay Lists (rendering instructions). |
| Raw pointer in **Chunk Descriptor** entries at offset `0x14` | GX Display List | Provides per-vertex **indices into the Vertex Tables** used during GX rendering. May be absent if **IVB** is present. |
| Raw pointer in **Chunk Descriptor** entries at offset `0x1C` | GX Cache / Bone Palette | Mapping for GX matrix palette skinning mesh to bones. Only present on chunks with the `sb` flag set; may be absent when **IVB** is used. |
| Raw pointer in header at `0x68` | Interleaved Vertex Buffer (IVB) | Alternate skinning data used primarily for battle `zu` body meshes. May be absent (when GX Display List and GX Cache are present). |
| Region between end of **GX Cache** and start of **Reloc Table** | String Pool | List of null-terminated strings containing names of materials and other strings |
| Raw pointer in header at `0x04` | Reloc Table | Table of relocation pointers. This lists raw pointers identifying all pointers between end of **Header** and start of **Reloc Table** |

---

## 2. File Header 
**Size:** 0x84 bytes
**Location:** 0x00

**Format:**
>Note: This format is primarily derived from overworld `ymu` body files. There may be similar fields at different offsets in other body files.

| Offset | Size | Field | Notes |
|---|---|---|---|
| `0x00` | uint32 | File size | |
| `0x04` | uint32 | Raw ptr → Reloc Table | |
| `0x08` | uint32 | Reloc entry count | |
| `0x20` | uint32 | Raw ptr → string `unknown`| If absent, raw ptr = 0 |
| `0x24` | 4 bytes | Build date tag | Always `20 04 07 23` |
| `0x28` | 4 bytes | Unknown | Preserve verbatim |
| `0x2C` | 24 bytes | AABB (6 floats) | min XYZ, max XYZ |
| `0x44` | uint32 | Raw ptr → vertex position table | If absent, raw ptr = 0 |
| `0x48` | uint32 | Raw ptr → vertex normal table | If absent, raw ptr = 0 |
| `0x4C` | uint32 | Raw ptr → UV coordinate table | |
| `0x50` | uint32 | Raw ptr → vertex lighting multiplier table (0 if none) | If absent, raw ptr = 0 |
| `0x54` | uint32 | Raw ptr → Materials List | |
| `0x58` | uint32 | Raw ptr → PtrA block list | Points to the first PtrA Block in a series of PtrA blocks|
| `0x5C` | uint32 | Raw ptr → Chunk Descriptor list (primary) | Points to the first Chunk Descriptor in a series of Chunk Descriptors |
| `0x60` | uint32 | Raw ptr → Chunk Descriptor list (alternate) | Used when `0x5C` is zero |
| `0x64` | uint32 | Raw ptr → Chunk Descriptor list (third fallback) | May be an older format; used when both `0x5C` and `0x60` are zero |
| `0x68` | uint32 | Raw ptr → Interleaved Vertex Buffer (IVB) | Present in battle `zu` and map `zmap` models; 0 in overworld `ymu` models |
| `0x6C` | uint16 | Vertex position count | |
| `0x6E` | uint16 | Vertex normal count | |
| `0x70` | uint16 | UV coordinate count | |
| `0x72` | uint16 | Vertex lighting multiplier count | 0 if no lighting table; must be 0 when `0x50` is 0 |
| `0x74` | uint16 | Material count | Equals Materials List entry count |
| `0x76` | uint16 | Chunk count | |
| `0x78` | uint16 | Chunk count (duplicate) | |
| `0x7A` | uint16 | Padding | Always `0x0000` |
| `0x7C` | uint8 | Vertex scale exponent | `vert_scale = 1 << data[0x7C]` |
| `0x7D` | uint8 | Normal scale exponent | |
| `0x7E` | uint8 | UV scale exponent | |
| `0x7F` | uint8 | Unused VAT byte | Always `0x00`. Fourth byte of the Vertex Attribute/Scale (VAT) quad at `0x7C`-`0x7F`, which stores the three scale exponents plus this unused byte. |
| `0x80` | uint32 | Padding | Observed as `0x00000000` in all sample files |

## 3. Vertex Tables
**Location:** 0x84

Tables are stored sequentially after the header: **Position** → **Normal** → **UV** → **Lighting Multiplier**. Each table's start offset is stored as a raw pointer in the header (`0x44`/`0x48`/`0x4C`/`0x50`). If not present, the raw pointer value in the header offset is 0.

### Position Table
- **Size:** `int16 × 3` = 6 bytes per vertex
- **Decode:** `x = raw / vert_scale`
- **Alignment:** 4-byte alignment 
  - When vertex count is odd, 2 bytes of zero padding should be appended after the last position entry so the following Normal Table is 4-byte aligned.

### Normal Table
- **Size:** `int8 × 3` = 3 bytes per normal
- **Decode:** `nx = raw / norm_scale`
- **Alignment:** 4-byte alignment
  - The table is padded at the end to a 4-byte boundary so the following UV table starts 4-byte aligned. 


### UV Table
- **Size:** `int16 × 2` = 4 bytes per entry
- **Decode:** `u = raw / uv_scale` 
  - **V is stored negated** relative to Blender convention. Import flips with `v = 1.0 - raw/uv_scale`; export inverts back.
- **Alignment:** naturally 4-byte aligned

### Lighting Table
- **Size:** `uint8 × 4` = 4 bytes per entry (RGBA)
- **Purpose:** Table of colors which function as per-vertex lighting multipliers. 
- Imported into Blender as Vertex Paint colors.
- Each vertex in a chunk's display list can reference a lighting value by its index into this table (when the chunk's `hc` flag is set). 

Lighting Options
- If `0x50` = 0 and `0x72` = 0, there is **no Lighting Table**. The game uses the default game lighting (no per-vertex modulation). This may utilize normal-based directional lighting. 
- **Uniform white** (255,255,255,255) applies the maximum lighting multiplier and produces the strongest contrast between lit and shadowed areas.

## 4. Materials List 
**Size:** 32 bytes per entry
**Location:** Raw pointer in header at `0x54`

| Offset | Size | Field |
|---|---|---|
| +0x00 | uint32 | Raw ptr → material name string |
| +0x04 | 2 bytes | Padding (`0x00 0x00`) |
| +0x06 | uint8 | Texture count (N TPL info blocks) |
| +0x07 | uint8 | Padding (`0x00`) |
| +0x08 | 4 bytes | Diffuse RGBA |
| +0x0C | 4 bytes | Specular RGBA |
| +0x10 | 4 bytes | Padding (`0x00 0x00 0x00 0x00`) |
| +0x14 | uint32 | Raw ptr → first TPL info block |
| +0x18 | 8 bytes | Padding (`0x00` × 8) |


## 5. TPL Info Blocks 
**Size:** 28 bytes each (0x1C bytes)
**Location:** contiguous after Materials List entries
  - The first TPL Info Block for each material is identified by the raw pointer in Materials List entry offset `+0x14`

| Offset | Size | Field | Notes |
|--------|------|-------|-------|
| +0x00 | uint8 | Reserved | Always `0x00` |
| +0x01 | uint8 | Constant | Always `0x01` in observed files. Possibly a marker or enables the texture. |
| +0x02 | 3 bytes | Padding | `0x00 00 00` |
| +0x05 | uint8 | TPL texture slot index | 0-based index into the `.tpl` container |
| +0x06 | uint8 | Sampling flag A | `0x01` across all sampled character models. `0x00` found in sampled `bmap*` models (observed in its last TPL info block). Exact meaning unknown. |
| +0x07 | uint8 | Sampling flag B | `0x01` across all sampled character models. `0x00` found in sampled `bmap*` models (observed in its last TPL info block). Exact meaning unknown. |
| +0x08 | 8 bytes | Padding | `0x00` * 8 |
| +0x10 | float32 | UV scale X | `3F 80 00 00` = 1.0 |
| +0x14 | float32 | UV scale Y | `3F 80 00 00` = 1.0 |
| +0x18 | uint32 | Padding | Always `0x00000000` |


## 6. PtrA Blocks
**Size:** 36 bytes per chunk 
**Composition:** 32 bytes of data + 4 bytes padding
**Location:** Raw pointer in header at `0x58`
  - The PtrA Block for each chunk is identified by the raw pointer in each Chunk Descriptor entry at offset `+0x00`

**"PtrA"** is a plugin-coined name; it contains metadata describing a chunk's min/max XYZ and unique Display-list slot value.

It was named as the **PtrA block** (sometimes shortened to simply **PtrA**), because it is the block that the first pointer in a **Chunk Descriptor** targets. There is one PtrA block per chunk.

**Format:**
| Offset | Size | Field |
|---|---|---|
| +0x00 | uint32 | Raw ptr → name string (bone/node?) |
| +0x04 | float32 × 3 | AABB min XYZ |
| +0x10 | float32 × 3 | AABB max XYZ |
| +0x1C | uint8 | `0x00` |
| +0x1D | uint8 | Display-list slot index (unique across ALL chunks) |
| +0x1E | uint16 | `0x0000` |
| +0x20 | uint32 | Stride padding (mostly `0x00000000`) |


### Note about PtrA in the plugin:
**Plugin `ptra_tail` convention (implementation detail, not a format concept):** The plugin stores bytes `+0x04..+0x23` (32 bytes, omitting the name pointer) as `ptra_tail`. Slot byte sits at index 25 within this slice. 

## 7. Chunk Descriptors 
**Size:** 32 bytes each
**Location:** Raw pointer in header at `0x5C`, `0x60`, and/or `0x64`
  - Files may use the pointer at `0x5C`,`0x60`, **and/or** `0x64`. The reason for these alternate locations has not yet been determined.
  - Each following Chunk Descriptor start offset is identified in the previous Chunk Descriptor entry, at offset +0x04.

**Purpose:** A **chunk** is a subdivision of a mesh that is rendered independently. Each chunk is represented by a **Chunk Descriptor** that **provides associated rendering metadata** such as materials, bone palettes, and display lists.

**Format:**

| Offset | Size | Field |
|---|---|---|
| +0x00 | uint32 | Raw ptr → PtrA block |
| +0x04 | uint32 | Raw ptr → next descriptor (0 = last) |
| +0x08 | uint16 | Format word: high byte = primitive type, low byte = render flags |
| +0x08.hi | uint8 | Primitive type: `0x38` = tri strip, `0x30` = tri list |
| +0x09.lo | uint8 | Render flags: bit 0 = use IVB, bit 1 = sb (skinning byte present), bits 2-3 = material batch mode (`0x02` = leader/rebind, `0x0E` = inherit from leader) |
| +0x0A | uint8 | Padding (`0x00`) |
| +0x0B | uint8 | Material index |
| +0x0C | 8 bytes | GX attribute block: 4 bytes zero padding + 4 bytes GX vertex attribute flags |
| +0x0C | 4 bytes | Padding (`0x00 0x00 0x00 0x00`) |
| +0x10 | 4 bytes | GX vertex attribute flags (byte [2] bit 4 = hc, byte [2] bit 7 = hu) |
| +0x14 | uint32 | Raw ptr → GX display list data |
| +0x18 | uint32 | Display list size in bytes |
| +0x1C | uint32 | Raw ptr → GX cache / bone palette |

The `hc` (color index present) and `hu` (secondary UV present) flags are at offset `+0x12` (third byte of the GX vertex attribute flags). They describe which fields appear in the per-vertex display list stream.

## 8. GX Display List 
**Location:** Raw pointer in each **Chunk Descriptor** entry at **offset +0x14**

Per-vertex-index stream consumed by the GX GPU. Each entry references indices into the Vertex Tables (or possibly IVB). May be absent if IVB is present. 

Encoded as `0x98` (`GX_DRAW_TRIANGLE_STRIP`) commands. Each command starts with the `0x98` opcode followed by a uint16 vertex count, then per-vertex data as described below.

**Per-Vertex Byte Layout:**

| Field | Condition | Bytes |
|---|---|---|
| Skinning byte | render flags byte bit 1 (`sb`=True, skinning byte present, see §7) | 1 |
| Position index | always | 2 |
| Normal index | always | 2 |
| Color index | Chunk descriptor GX flags byte 2 bit 4 (`hc`=True, has color index) | 2 |
| UV index | always | 2 |
| Secondary UV | Chunk descriptor GX flags byte 2 bit 7 (`hu`=True, has secondary UV) | 2 |

`sb_byte / 3 = palette slot index`. GX uses 3x4 matrices in its matrix palette, so the raw skinning byte is divided by 3 to produce the actual palette slot index.

## 9. GX Cache / Bone Palette 
**Size:** 32 bytes per palette. *See note below the layout table for an exception to this size rule.*

**Location:** Raw pointer in each **Chunk Descriptor** entry at **offset +0x1C**. GX Cache blocks are stored after all Display Lists. 

**Purpose:** Bone-to-palette-slot mapping for GX matrix palette skinning. Each block lists bone IDs loaded into consecutive GX matrix palette slots. Only present on chunks with the `sb` flag set; absent when **IVB** is used.

**Layout:**

| Offset | Field | Notes |
|--------|-------|-------|
| `+0` | Constant Marker | Always `0x10` |
| `+1` | palette bone count (N) |  |
| `+2` through `N+1` | bone IDs | Sorted ascending. The same bone ID can appear in multiple palettes. |
| `N+2` | Padding | Padded with `0x00` to 32 bytes per Bone Palette. **See FE9 Exception below table.** |

**In FE9 only:** the very last Bone Palette is not padded. The **String Pool** begins immediately after the last bone ID in the last Bone Palette.

## 10. Interleaved Vertex Buffer (IVB)
**Location:** Raw pointer in header at `0x68`

**Theorized Purpose:** skinning mesh to bones for battle model (`zu`) and some map asset (`zmap`) body files. May support assignment of vertices to multiple bones and multi-bone weight blending. If present, this may replace the function of vertex position and/or normal tables. 

Present when header `0x68` is non-zero. Located at `raw_ptr + 0x20`. 
**Layout:**
| Offset | Size | Field |
|--------|------|-------|
| +0x00 | uint32 | magic 0x10 |
| +0x04 | uint32 | vertex data offset (relative to IVB header) |
| +0x08 | uint16 | skinning record count |
| +0x0A | uint16 | vertex count |
| +0x10 | 0x18 bytes each | Skinning Records begin (see below) |
| `IVB_start + vertex_data_offset` | `vertex_count × 12` | Vertex data: `int16 × 6` per vertex (pos XYZ, normal XYZ), scale 256 |

### Skinning Records 
Beginning at `IVB_start + 0x10`, 0x18 bytes each. Vertex-to-bone skinning records for GX matrix streaming. Each record assigns one or more weighted bones to a block of vertices.

| Offset | Size | Field |
|---|---|---|
| +0x00 | uint16 | bone_a (primary bone, used as child bone for skinning) |
| +0x02 | uint16 | bone_b (secondary bone, 65535 = none) |
| +0x04 | uint16 | bone_c (third bone) |
| +0x06 | uint16 | bone_d (fourth bone, 65535 = none) |
| +0x08 | int8 × 4 | Influence weights [w_a, w_b, w_c, w_d] |
| +0x0C | uint32 | Iterator (increments by 32; likely byte offset into vertex data stream) |
| +0x10 | uint16 | bone_a2 (possibly double-buffered copy of bone_a) |
| +0x12 | uint16 | bone_b2 (possibly double-buffered copy of bone_b) |
| +0x14 | uint16 | Vertex count for this record |
| +0x16 | uint16 | Padding |

### Vertex Data
**Size:** `int16 × 6` per vertex (pos XYZ, normal XYZ)

**Scale:** = 256
  - Scale might not always be 256. Scale could be stored at an unknown location.

**Per-vertex Layout:** 
| Offset | Size | Field |
|---|---|---|
| +0x00 | int16 | position X |
| +0x02 | int16 | position Y |
| +0x04 | int16 | position Z |
| +0x06 | int16 | normal X |
| +0x08 | int16 | normal Y |
| +0x0A | int16 | normal Z |


## 11. String Pool
**Location:** between the last GX Cache (or end of IVB) and the Reloc Table

The string pool is a block of null-terminated strings. It holds material names and miscellaneous strings referenced by raw pointers elsewhere in the file. Strings are alphanumerically sorted ascending.

A common material name is `lambert*` (e.g., `lambert28`). The strings `none` and `unknown` have been observed in every sample file.

## 12. Reloc Table

A sorted list of big-endian uint32 values at the end of the file. This is a list of **raw pointers targeting every pointer** between the end of the header and the start of the Reloc Table. 

Offset and entry count are in the file header:
- Header `0x04`: raw offset of the table (resolve with `+ 0x20` to get file offset)
- Header `0x08`: number of entries

Each entry is a raw pointer field position (file offset minus `0x20`). The game loader adds `0x20` to every field whose file offset is listed here. Null pointers are not included. Entries are sorted ascending.

The table tells the game which 4-byte fields in the file contain raw pointers that need the `+ 0x20` base adjustment.

## 13. Remaining Unknowns

- **IVB skinning records**: The bone weight encoding at `+0x08` (int8 x 4) is documented but the plugin currently uses single-bone assignment from `bone_a` only. Multi-weight blending is not implemented. The `bone_a2`/`bone_b2` fields at `+0x10`/`+0x12` may be double-buffered copies; their exact role is unconfirmed.
- **Header unknown at `0x28`**: 4 bytes, preserved verbatim. Appears to be a model-specific tag, not a pointer.