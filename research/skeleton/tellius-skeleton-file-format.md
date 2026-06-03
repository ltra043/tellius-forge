<h1 align="center">Tellius Skeleton File Format</h1>

<p align="center"><i>
Reverse-engineering notes on the format of Fire Emblem 9 and Fire Emblem 10 skeleton (`.g`) files.<br>
See <a href="../body/tellius-body-file-format.md">Tellius Body File Format</a> and <a href="../animation/tellius-animation-file-format.md">Tellius Animation File Format</a> for analysis of other asset formats.</i><br><br>
<b>Author:</b> Jade (ltra043)<br>
<b>Last Updated:</b> 2026-06-01
</p>
  
<details>
<summary>Keywords</summary>

Fire Emblem assets, Fire Emblem model format, FE9 skeleton format, FE10 skeleton format, FE9 model format, FE10 model format, Path of Radiance skeleton, Radiant Dawn skeleton, Path of Radiance models, Radiant Dawn models, Tellius asset research, .g format, GameCube skeleton format, Wii skeleton format, GameCube model format, Wii model format, reverse engineering, file format documentation, skeleton animation data, skeleton reverse engineering, GameCube rigging, Wii rigging, game asset research, 3D model format, Nintendo GameCube modding, Nintendo Wii modding, GameCube Modding, GC Modding, GC/Wii Modding

</details>

## Reader Information
- All multi-byte integers and floats are **big-endian** unless noted otherwise.
- **All listed offsets and size values are decimal values** unless prefixed with `0x` to indicate it is a hex value.

<details>
<summary><b>Table of Contents</b></summary>

1. [Summary of Skeleton File Layout](#1-summary-of-skeleton-file-layout)
2. [File Header](#2-file-header)
3. [Bone Record Format](#3-bone-record-format)
4. [Bone Flag System](#4-bone-flag-system)
5. [Position and World-Space Accumulation](#5-position-and-world-space-accumulation)
6. [String Pool Format](#6-string-pool-format)
7. [Bone Naming Conventions](#7-bone-naming-conventions)
8. [Remaining Unknowns](#8-remaining-unknowns)

</details>


<details>
<summary><b>Additional Resources</b></summary>

1. [FE10 ImHex bookmarks](https://drive.google.com/file/d/1wBQgxkHshERlykjIj5WD58jmAeRpy2Wl/view?usp=drive_link) for fe10 `fighter3_n’s skeleton.g`  
2. [Skeleton file viewer](https://docs.google.com/spreadsheets/d/1zbN7nSeyl0lY_XA7-t0zFUdaRjoDEF3c_laifMrM5Pc/edit?gid=1433193727#gid=1433193727&range=A1) : spreadsheet that parses and organizes skeleton data
3. [g-analyzer.py](../../tools/skeleton/g-analyzer.py): parses skeleton data and creates detailed summary
4. [Tellius Forge Blender plugin](https://github.com/ltra043/tellius-forge/releases/latest): suuports import, modification, and export of FE9/FE10 skeleton files.
5. [App for Tellius Unit Map Model Porting](https://github.com/ltra043/tellius-unit-model-ports): supports FE10 to FE9 porting  

</details>

## Research Status

**Testing Scope:**
The following observations are primarily based on comparison of `ymu` skeletons. They might not be true for EVERY skeleton. 

Information related to bone rotation and location is more strongly documented than information related to scale. We believe scale is not often modified via skeleton data, so it is difficult to draw conclusions related to scale from skeleton data alone.

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

## 1. Overall Skeleton File Layout

|Offset | Content |
|-------|---------|  
`0x00` | **Header** (16 bytes): reserved, string_pool_offset, bone_count, `0x10` |
`0x10` | Bone record 0 (244 bytes) |
`0x104` | Bone record 1 (244 bytes) |
...  | Remaining bone records |
`0x10 + n*0xF4`  | **String pool:** `[unknown]\0name0\0name1\0...\0`  |


Total file size = `0x10 + bone_count * 0xF4 + string_pool_size`.
---

## 2. File Header 
**Size:** 16 bytes / 0x10 bytes

| Offset | Type | Field | Notes |
|--------|------|-------|-------|
| `+0` | uint32 | reserved | Always 0. |
| `+4` | uint32 | string_pool_offset | Absolute byte offset of the null-terminated name string pool from file start. **Acts as a pointer to the start of the string pool.** |
| `+8` | uint32 | bone_count | Total number of bone records. |
| `+12` | uint32 | first_bone_offset | Always `0x10` (constant: first bone record starts at this address, immediately after the header). |

Bone records follow contiguously from `0x10` onward. Record stride = `0xF4` (244 bytes). String pool starts at `bone_count * 244 + 0x10` = `string_pool_offset`.

---

## 3. Bone Record Format 
**Size:** 244 bytes / 0xF4 bytes

| Offset | Size | Type | Field | Notes |
|--------|------|------|-------|-------|
| `+0`   | 4    | int32   | parent_index     | `-1` = root bone. |
| `+4`   | 4    | int32   | next_sibling     | Index of next sibling, `-1` = last child of parent. |
| `+8`   | 4    | int32   | first_child      | Index of first child, `-1` = leaf bone. |
| `+12`  | 4    | uint32  | flags            | IS-proprietary bitfield (see §4 below). |
| `+16`  | 64   | f32×16  | bind matrix      | 4×4 column-major matrix. Class A: identity-like (last 3 diag entries = 1.0, rest ≈ 0). Class B: inverse-bind matrix, column 3 = negated world position of bone. See §3.2 below for what this means in plain terms. |
| `+80`  | 8    | f32×2   | reserved         | Always zero in tested files. Purpose unknown. |
| `+88`  | 12   | f32×3   | local_translation | Class B only: local XYZ offset from nearest Class B ancestor, expressed in that ancestor's local frame. Class A: all zeros. |
| `+100` | 12   | f32×3   | local_rotation_deg | Class B only: XYZ Euler rotation angles in **degrees**. Used to build the 3×3 rotation matrix `R = Rz * Ry * Rx`. Class A: all zeros. |
| `+112` | 12   | f32×3   | position         | Class A: bone head world-space position. Class B: all zeros. For Class A children of Class B bones, this is a local offset from the parent chain's anchor (not absolute world space). |
| `+124` | 12   | f32×3   | position_dup     | Always identical to `+112`. Presumably a copy for alignment or caching. |
| `+136` | 52   | f32×13  | reserved         | Zero in all tested bones. |
| `+188` | 48   | f32×12  | pre-computed_3×4_local_transform | See §3.1 below. |

### Per-bone footer (last 8 bytes of the 244-byte record):

| Offset | Size | Type | Field | Notes |
|--------|------|------|-------|-------|
| `+236` | 2    | uint16 | bone_index   | This bone's own index in the file. Recomputed on export to match the list position. |
| `+238` | 2    | uint16 | constant     | Always `0x0001` in all observed skeletons. If the two footer uint16s at `+236`/`+238` are read together as one big-endian uint32, the value is `(bone_index << 16) \| 1`. This packed form may be how the game engine indexes bones, but it is unconfirmed. |
| `+240` | 4    | uint32 | name_offset  | Byte offset of this bone's null-terminated ASCII name within the string pool, relative to pool start. |

### 3.1 Pre-computed 3×4 Local-Transform Matrix

The 12 floats at `+188` through `+235` form a 3×4 transformation matrix (3 rows × 4 columns):

```
R = Rz(local_rotation_deg[2]) * Ry(local_rotation_deg[1]) * Rx(local_rotation_deg[0])
```

Matrix layout (row-major storage within the 12-float block):

| Address | Component | Value |
|---------|-----------|-------|
| `+188`  | row0col0  | `cos(rotY)·cos(rotZ)` |
| `+192`  | row0col1  | `cos(rotZ)·sin(rotY)·sin(rotX) - sin(rotZ)·cos(rotX)` |
| `+196`  | row0col2  | `cos(rotZ)·sin(rotY)·cos(rotX) + sin(rotZ)·sin(rotX)` |
| `+200`  | row0col3  | **Location X** — `local_translation.x` (Class B) or `position.x` (Class A) |
| `+204`  | row1col0  | `sin(rotZ)·cos(rotY)` |
| `+208`  | row1col1  | `sin(rotZ)·sin(rotY)·sin(rotX) + cos(rotZ)·cos(rotX)` |
| `+212`  | row1col2  | `sin(rotZ)·sin(rotY)·cos(rotX) - cos(rotZ)·sin(rotX)` |
| `+216`  | row1col3  | **Location Y** |
| `+220`  | row2col0  | `-sin(rotY)` |
| `+224`  | row2col1  | `cos(rotY)·sin(rotX)` |
| `+228`  | row2col2  | `cos(rotY)·cos(rotX)` |
| `+232`  | row2col3  | **Location Z** |

For Class A bones with zero rotation, this reduces to the identity 3×3 with location = `position`.  
For Class B bones, the rotation columns are populated and location = `local_translation`.

### 3.2 What Is the Bind Matrix?

Skinned character meshes are modeled in a neutral pose called "bind pose." Each vertex stores which bone influences it, with positions measured relative to that bone's local frame in bind pose.

At runtime the game must transform each vertex from bind-pose space into the bone's current animated world position. The bind matrix is the pre-computed inverse of the bone's rest-pose world matrix. It undoes the rest-pose transform so animation data can move the vertex from there.

Numerically:
- **Class A**: Bind matrix is identity-like. Class A bones have no accumulated rotation in the skeleton, so the rest transform is just a location offset (a translation). The inverse of a pure translation is trivial (negate the offset), which equals column 3 of the inverse-bind matrix.
- **Class B**: The 3x3 portion is the inverse of the bone's accumulated rotation. Column 3 (the location column) stores the negated world-space position of the bone head.

The plugin preserves this matrix verbatim from the original file on import and writes it back unchanged on export. You do not need to modify it for model editing.

---

## 4. Bone Flag System

The 32-bit `flags` field at `+12` is an **Intelligent Systems-proprietary bitfield**. It is NOT a standard Nintendo format (not J3D, not G3D MDL0, not NSBMD SBC), though it shares **conceptual DNA** with NSBMD SBC (the skeleton/scene-graph bytecode format used in Nintendo DS model files, publicly documented on GBATEK), but it is not a copy of any known Nintendo format.

### 4.1 Proposed Bit Layout

```
+--------+------+------+-------+------+------+------+------+
| 31-18  | 17-12| 11-9 |   8   |  7   |  6   |  5   | 4-0  |
+--------+------+------+-------+------+------+------+------+
|Extended|Unused|Extra |ClassA |ClassA|Load  |Store |Opcode|
| flags  |      |Flags |(0x100)|(0x80)|(0x40)|(0x20)|(0x1F)|
+--------+------+------+-------+------+------+------+------+
```

| Bits | Mask  | Label | Interpretation |
|------|-------|-------|----------------|
| 4-0  | 0x1F  | Opcode | Low-level matrix operation this bone performs. See §4.3 below. |
| 5    | 0x20  | Store  | If set: compute matrix then **store** result to a stack slot (analogous to NSBMD SBC bit 5). |
| 6    | 0x40  | Load   | If set: **load** a matrix from stack before the multiply (analogous to NSBMD SBC bit 6). |
| 7    | 0x80  | ClassA1 | Class A indicator (see §5). Nearly always paired with bit 8. |
| 8    | 0x100 | ClassA2 | Class A indicator. Nearly always paired with bit 7. |
| 9-11 | -     | Extra   | Higher flags seen on some FE9 bones; more common in FE10 (Wii extras). |
| 12-17| -     | Unused  | Not observed in any known skeleton. |
| 18+  | -     | Extended| Rare Wii-specific bits (e.g., 0x401AC, 0x407BC in FE10 only). |

**The names and semantics in this table are our best interpretation and are speculative.** The operation-codes and stack flags are inferred from hierarchy patterns and the NSBMD SBC precedent, but have not been verified against the actual game engine.

### 4.2 Class A vs Class B
Bones can be broadly sorted into two categories: **Class A (World Position)** and **Class B (Local Transorm)**. These classifications are based primarily on observed flag patterns and how position data is stored within the skeleton. 

Class B bones exhibit more variation than Class A bones, and aspects of their position and animation behavior remain only partially understood.

The primary class division is determined by **bits 7-8** (`flags & 0x180`):

| Test | Class | Meaning |
|------|-------|---------|
| `flags & 0x180 != 0` | **Class A** | Bone stores its rest position as a **world-space position** at `+112`. Bind matrix is identity-like. Animation is straightforward to combine with skeleton position. |
| `flags & 0x180 == 0` | **Class B** | Bone stores a **local transform** (offset + rotation) relative to the nearest Class B ancestor at `+88`/`+100`. Bind matrix contains inverse-bind data. Animation data combines with the local transform — the full world position is the accumulated result of the B-chain hierarchy. |

Both classes can have animation data in `.ga` files. The distinction is about how each bone's rest-pose position is encoded in the skeleton:

- **Class A** positions are directly usable as world-space bone head positions. Animation data for Class A bones is simple additive translation/rotation deltas.
- **Class B** positions must be accumulated through a parent-relative transform chain. Animation data for Class B bones applies to their local transform (the values at `+88`/`+100`), and the full world-space result can only be computed after accumulating the entire ancestor chain with rotation.

**Animation of Class A bones is the most well-understood.** Animation of Class B bones combines with the skeleton's local transforms in ways that we have not fully reverse-engineered — the current plugin applies animation to the pose bones' transform channels, which works for many cases but may not perfectly match the game's internal matrix computation for all Class B chains.

### 4.3 Observed Flag Values

#### Class A (`flags & 0x180 != 0`)

| Flag | Opcode (bits 4-0) | Notes |
|------|-------------------|-------|
| `0x180` | `0x00` | **Most common Class A flag in both games.** World position at `+112`. Identity bind matrix. |
| `0x18C` | `0x0C` | Possibly **attachment points** — weapon grip / hand attachment. Same position semantics as 0x180. |
| `0x190` | `0x10` | **Unknown** — rare, seen in `beast_ti`. |
| `0x194` | `0x14` | **Unknown** — rare. |
| `0x1A4` | `0x04` | **Possibly attachment point variant** — alternate weapon attachment. |
| `0x1AC` | `0x2C` | **Unknown** — rare, seen in `pegasu2`. |

#### Class B (`flags & 0x180 == 0`)

| Flag | Opcode | Store (0x20) | Load (0x40) | Notes |
|------|--------|:---:|:---:|-------|
| `0x00` | `0x00` | — | — | **Observed in root / identity bone** — no transform operation. |
| `0x0C` | `0x0C` | — | — | Rare — appears in some FE9 models. |
| `0x14` | `0x14` | — | — | Rare — `d_knight1_j` overworld. |
| `0x24` | `0x04` | ✓ | — | **Possibly IK / solver bone** — has not yet been observed to be animated. The "solver" label is a guess based on naming (`_s1_`, `_s2_`, `_sw1_`, `_sw2_`). |
| `0x26` | `0x06` | ✓ | — | **FE9 animated chain bone** (store only). Can have `0x66` or `0x26` children. |
| `0x27` | `0x07` | ✓ | — | **FE10 animated chain bone** — replaces the `0x26` used in FE9. Same stack behavior as `0x26` (store only). |
| `0x2C` | `0x0C` | ✓ | — | Rare variant — seen in FE10 with multiple flags. |
| `0x2F` | `0x0F` | ✓ | — | Rare — overworld model variant. |
| `0x46` | `0x06` | — | ✓ | **Load-only variant** — rare; seen in `tiamat` horse tail. Transient bone (loads but doesn't store). |
| `0x66` | `0x06` | ✓ | ✓ | **FE9 chain bone** (load + store). Often at end of a 0x26 chain. **Can have Class A children** — the "load" operation may anchor descendants to the chain root's frame. |
| `0x67` | `0x07` | ✓ | ✓ | **FE10 chain variant** — counterpart of FE9's `0x67`|
| `0x76` | `0x06` | ✓ | ✓ | **FE9 horse/cloth variant** — 0x66 + bit 4 set. |
| `0x77` | `0x07` | ✓ | ✓ | **FE10 cloth/skirt variant** — 0x67 + bit 4 set. |
| `0x866`| `0x06` | ✓ | ✓ | **FE9 extended variant** — 0x66 with bit 11 set. `tiamat` only. |

#### Extended / Wii-specific flags (FE10 only)

| Flag | Notes |
|------|-------|
| `0x3B4`, `0x394` | Bits 9+8+7 set. Purpose unknown. |
| `0x7BC` | Bits 10+9+8+7 set. |
| `0x401AC`, `0x407BC` | Bit 18 set — Wii extension beyond the GameCube flag range. |

**All proposed purpose labels (e.g., "solver," "terminal chain," "variant") are inferred guesses based on hierarchy position and bone naming conventions.** They have not been verified by analysis of the game's executable.

### 4.4 NSBMD SBC Parallel

>The remainder of *Section 3* is relevant for understanding how bones interact with animation data. 
>
>Skip to [*Section 5*](#5-position-and-world-space-accumulation) to understand how bone position is determined. Or skip to [*Section 6*](#6-string-pool-format) to learn about the String Pool, which is the last part of a skeleton file.

The **store bit (bit 5)** and **load bit (bit 6)** map directly to the NSBMD SBC modifier bits for the `NODEDESC` (0x06) command:

| FE bits | NSBMD SBC equivalent | Runtime behavior (likely) |
|---------|----------------------|--------------------------|
| Store only (e.g., 0x26) | `NODEDESC + store` | Multiply bone matrix into current matrix, store result to stack for children |
| Load + Store (e.g., 0x66) | `NODEDESC + load + store` | Load matrix from stack (resets to chain root's frame), multiply, store again |
| Load only (e.g., 0x46) | `NODEDESC + load` | Load matrix, multiply, do NOT store (transient) |

Hypothesized runtime pseudocode:
```
if flags & 0x40:                # bit 6: load
    current_matrix = stack[bone_index]
current_matrix *= bone_local_transform(bone_index)
if flags & 0x20:                # bit 5: store
    stack[bone_index] = current_matrix
```

The FE opcode values (low 5 bits) **do not** match NSBMD SBC one-to-one. FE uses 0x06 for its standard animated chain; NSBMD SBC uses 0x06 for `NODEDESC`. The 0x07 family (FE10: 0x27, 0x67, 0x77) may map to NSBMD SBC's 0x07 = `BB` (billboard), but this is **speculative**.

### 4.5 FE9 vs FE10 Flag Differences

| Aspect | FE9 | FE10 |
|--------|-----|------|
| Primary animated class B flag | `0x26` (store) / `0x66` (load+store) | `0x27` (store) |
| Chain variant | `0x66` (load+store, common) | `0x67` (less common; `0x27` mostly suffices) |
| Extended bits | Only up to bit 11 (`0x866`) | Up to bit 18+ (`0x401AC`) |
| Opcode for animated bones | `0x06` | `0x07` |
| `0x46` load-only | Present (tiamat) | Very rare or absent |

FE10 appears to have simplified the flag system by making more animated bones use opcode `0x07` with store-only behavior, reducing the need for the `0x67` distinction.

---

## 5. Position and World-Space Accumulation
We have classified skeleton bones into two different encoding schemes (Class A and Class B) which inform how bone position is determined. Understanding how these positions are accumulated is necessary to reconstruct the skeleton correctly.

### 5.1 Terminology

- **Raw file positions:** The values stored at `+112` (p112) and `+88` (p88) in each bone record.
- **Rest position (naive):** The bone head position used for mesh skinning. For Class A this is p112 directly. For Class B this is p88 accumulated from the nearest Class B ancestor **without rotation**.
- **True world position:** The bone head position computed with **rotation-aware accumulation** (see §5.3). Used for pose transforms and determining bone tail direction.
- **Pose transform (fe_pose):** The difference between a bone's true world position and its naive rest position, stored as a pose-bone location/rotation offset in Blender.

### 5.2 Data Source Selection

```
IF Class B (flags & 0x180 == 0) OR Class A with p88 non-zero:
    raw_position = p88     (local offset)
    raw_rotation = p100    (local rotation degrees)
ELSE (Class A):
    raw_position = p112    (world or anchored position)
    raw_rotation = zero
```

The dual-test (`flags & 0x180 == 0` OR `p112 ≈ 0 AND p88 ≠ 0`) catches edge cases where a bone's stored data disagrees with its flag classification.

### 5.3 World-Space Accumulation Algorithm

```
For each bone in file order (parents always before children):

  ── Class A, no Class B ancestor ─────────────────────────────
  true_world = p112
  true_rot   = identity

  ── Class B ───────────────────────────────────────────────────
  Find the nearest Class B ancestor (skip all Class A bones in between).
  If none exists, base = (0,0,0), anc_rot = identity.
  Otherwise, base = that ancestor's accumulated b_chain_pos,
             anc_rot = that ancestor's accumulated rotation.

  local_t = p88
  local_R = Rz(p100[2]) * Ry(p100[1]) * Rx(p100[0])

  rotated_offset = apply(anc_rot, local_t)
  b_chain_pos[idx] = base + rotated_offset
  b_chain_rot[idx] = anc_rot * local_R
  true_world = b_chain_pos[idx]

  ── Class A with Class B ancestor ────────────────────────────
  Find the nearest Class B ancestor (same as above).
  local_t = p112     (NOT p88 — p88 is zero for Class A)
  rotated_offset = apply(anc_rot, local_t)
  true_world = base + rotated_offset
  true_rot   = identity                   (Class A has no rotation accumulation)
```

Key insight: **Class A ancestors are transparent to B-chain accumulation.** A Class B bone bases its position on the nearest *Class B* ancestor, ignoring any Class A bones in between. Class A children of Class B bones similarly offset from the B-chain anchor rather than their direct parent.

### 5.4 Rest Position vs Pose Position

The **naive rest position** (used for Blender bone head placement and mesh skinning) is:

| Category | Rest Position |
|----------|--------------|
| Class A, no B ancestor | `p112` (absolute world) |
| Class A with B ancestor | `p112` (this IS the correct rest position — p112 is the offset from B-chain anchor) |
| Class B | `base + apply(parent_rot, p88)` where `base` = nearest B ancestor's rest position |

The **pose transform** (applied as Blender pose bone location + rotation) captures the difference between the true world position and the rest position:

| Category | Pose Location | Pose Rotation |
|----------|:---:|:---:|
| Class A, no B ancestor | Zero | Zero |
| Class A, direct B parent | `true_world - p112` (difference between accumulated world and stored position) | Combined rotation from all B ancestors (so the bone's tail points correctly along the B-chain) |
| Class B | Zero | Zero (rotation is part of the bone's local transform) |
| Class A with indirect (non-direct) B parent | Negated sum of ancestors' pose locations | Combined rotation from B ancestors |

**Animation of Class B bones** remains partially unresolved. The skeleton stores local transforms (p88 + p100) at rest pose, and animation `.ga` files store deltas to these values. The current plugin applies animation to pose bone transform channels, which produces visually correct results for some cases, but the exact way the game engine combines skeleton rest and pose data with animation keyframes for Class B bones has not been fully reverse-engineered.

---

## 6. String Pool Format

The string pool begins at `string_pool_offset` (from the file header). It is a sequence of null-terminated ASCII strings:

```
[unknown]\0                    # First entry is has always been observed as "[unknown]"
bone_name_0\0
bone_name_1\0
bone_name_2\0
...
\0                             # Null-terminated
```

Bones reference their name via `name_offset` (at `+240` within the bone record), which is a relative offset from the *start of the string pool*, not from the file start. The first entry (`[unknown]` in every observed skeleton) occupies offset 0 in the pool.


---

## 7. Bone Naming Conventions

### 7.1 Hierarchy Encoding in Names

The `|` character in a bone name encodes the parent→child chain within a single string. For example:

- `R_arm1|R_arm2|R_hand` → bone named `R_arm1|R_arm2|R_hand` is a child of `R_arm1|R_arm2` (forearm), which is a child of `R_arm1` (shoulder). Its full display name is `R_hand`.
- In markdown tables the `|` may be rendered as `→` or `│` to avoid table formatting conflicts.

### 7.2 Other Descriptors in Names
Bone names may use `:` as a namespace separator to provide more detail about the model. For example, `armor_enemy:kensyu:body1` in the FE9 general's skeleton. This may have been used as a descriptor to distinguish modular body part options.

In the Blender plugin, `:` is converted to `__` (double underscore) for compatibility with Blender's naming rules, and converted back on export.

### 7.3 Non-Animated (Orientation) Bones

Bone names enclosed in underscores (e.g., `_sw1_`, `_s1_`, `_s2_`, `_s_`) have **not** been observed with animation data. They likely exist purely as orientation/reference guides for modellers and animators, not as skinned bones. These have been observed to correspond to `0x24` flag bones in the skeleton.

### 7.4 bone0 and Root Conventions

- **bone0** is often named `all` or `*_locator` (e.g., `wayu_locator`).
- `hip`, `hip0`, `hip_locator`, or a similar `hip` variant is usually the **main body bone**. It is a direct child of bone0 and is the parent of all other body-influencing bones.
- Other direct children of bone0 typically **do not influence any mesh** and may be leftover artifacts from model creation. They may share names with mesh-influencing bones (e.g., `hip0` for an unused bone, `hip` for the active bone).

### 7.5 Torso and Limbs

- `body`, `chest`, or similarly named bones usually correspond to the torso. It is typically the parent of all bones in the upper half of the body.
- Infantry skeletons typically have **3 bones per arm** (shoulder, forearm, hand) and **3 bones per leg** (thigh, calf, foot), plus one non-influencing bone at the front of each foot (`_s1_` or `_s2_`). 
    - An extra non-influencing hand bone (`_r_hand_` or similar name) is sometimes present. 
    - There may be additional bones like `L_skirt` interrupting the sequencing and relationships bewteen leg bones.

### 7.6 Laterality

`L`, `l`, `left` and `R`, `r`, `right` indicate the **model's own left and right** (anatomical laterality), not the viewer's perspective.

### 7.7 Rider + Mount Skeletons

For characters with a rider and mount together, the "main" skeleton is usually the **mount's**. The rider's skeleton is typically a child of the mount's `body` or equivalent bone.

### 7.8 Weapons

Weapons, if present in the skeleton, are usually children of the right hand bone.

### 7.9 Name Inconsistency

Bone names are **not completely consistent** between models.

Many models use default/auto-generated names such as `joint8`, `pCube6`, or `plane4` that do not meaningfully describe which body part they influence.

### 7.10 Language Patterns

- Body parts and weapons are usually named in English or English shorthand (e.g., `l_leg2`, `R_arm1`, `Sword`).
- Accessories are often named in romanized Japanese (e.g., `saya` = sheath, `manto`/`mantle` = cape).

---
## 8. Remaining Unknowns

- **`+80` and `+84`** (two floats): Always zero in tested files. Could be reserved, pre-rotation scale, or an older format field. **Not yet decoded.**
- **`+136` through `+184`** (13 floats): Zero in all tested bones. Possibly reserved or batch-animation scratch space. **Not yet decoded.**
- **Flag opcode semantics:** The low 5 bits of the flag field may encode an operation code for the game's matrix engine. Our mapping of opcode 0x06 = "matrix multiply" and 0x07 = "billboard/special" is inferred from NSBMD SBC precedent and has not been verified via runtime analysis. **Not confirmed.**
- **Cape/cloth physics at runtime:** Bones with `0x66`/`0x67`/`0x77` flags may undergo runtime physics modification in-game. Their Blender positions after import are the **rest pose** positions, not the animated positions seen in-game.
- **Bind matrix at `+16`:** For Class A this is identity-like. For Class B it stores an inverse-bind matrix with the negated world position in column 3. The plugin preserves this verbatim from the original file when re-exporting. Its exact use in the game engine has not been analyzed.
- **FE10 0x27 bones and billboarding:** The 0x27 flag (opcode 0x07) may indicate a billboard bone whose transform ignores parent orientation. This has not been confirmed and may simply be IS's opcode for "standard animated bone" in FE10, distinct from FE9's 0x06.

