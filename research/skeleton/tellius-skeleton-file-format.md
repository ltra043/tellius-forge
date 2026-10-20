<h1 align="center">Tellius Skeleton File Format</h1>

<p align="center"><i>
Reverse-engineering notes on the format of Fire Emblem 9 and Fire Emblem 10 skeleton (`.g`) files.<br>
See <a href="../body/tellius-body-file-format.md">Tellius Body File Format</a> and <a href="../animation/tellius-animation-file-format.md">Tellius Animation File Format</a> for analysis of other asset formats.</i><br><br>
<b>Author:</b> Jade (ltra043)<br>
<b>Last Updated:</b> 2026-10-10 (v2.0.0: value-block model, term flags, unified terminology; "inverse bind" spelling; bone palette, submesh, and inverse bind matrix terms applied)
</p>

<details>
<summary>Keywords</summary>

Fire Emblem assets, Fire Emblem model format, FE9 skeleton format, FE10 skeleton format, FE9 model format, FE10 model format, Path of Radiance skeleton, Radiant Dawn skeleton, Path of Radiance models, Radiant Dawn models, Tellius asset research, .g format, GameCube skeleton format, Wii skeleton format, GameCube model format, Wii model format, reverse engineering, file format documentation, skeleton animation data, skeleton reverse engineering, GameCube rigging, Wii rigging, game asset research, 3D model format, Nintendo GameCube modding, Nintendo Wii modding, GameCube Modding, GC Modding, GC/Wii Modding

</details>

## Reader Information
- All multi-byte integers and floats are **big-endian** unless noted otherwise.
- **All listed offsets and size values are decimal values** unless prefixed with `0x` to indicate it is a hex value. Record offsets are written `+N` (decimal) or `+0xNN` (hex) from the start of the bone record.
- Matrices are **3×4 affine, row-major, translation in the 4th column** (12 floats), column-vector convention (`p' = R·p + t`). Euler angles are **degrees**, XYZ order, `R = Rz·Ry·Rx`.
- **Model space** is the coordinate space of the whole character (the space the `.gs` vertices are stored in); it is not the game-world position of the unit, which the engine applies on top.
- A bone's **frame** is the coordinate system its own numbers (translate, pivots, children's offsets) are expressed in. Its **world matrix** is the transform from that frame to model space; see [§6.2](#62-world-matrices-and-joint-position) for the exact definition.

<details>
<summary><b>Table of Contents</b></summary>

1. [Overall Skeleton File Layout](#1-overall-skeleton-file-layout)
2. [File Header](#2-file-header)
3. [Bone Record Format](#3-bone-record-format)
4. [Term Flags](#4-term-flags)
5. [Pivot Bones and Offset Bones (Class A / Class B)](#5-pivot-bones-and-offset-bones-class-a--class-b)
6. [Bone Matrices, Poses and Skinning](#6-bone-matrices-poses-and-skinning)
7. [Hierarchy and Loading](#7-hierarchy-and-loading)
8. [Runtime Structures and Engine Routines](#8-runtime-structures-and-engine-routines)
9. [String Pool and Bone Names](#9-string-pool-and-bone-names)
10. [Terminology Notes](#10-terminology-notes)
11. [Remaining Unknowns](#11-remaining-unknowns)

</details>

<details>
<summary><b>Additional Resources</b></summary>

1. [FE10 ImHex bookmarks](https://drive.google.com/file/d/1wBQgxkHshERlykjIj5WD58jmAeRpy2Wl/view?usp=drive_link) for fe10 `fighter3_n's skeleton.g`  
2. [Skeleton file viewer](https://docs.google.com/spreadsheets/d/1zbN7nSeyl0lY_XA7-t0zFUdaRjoDEF3c_laifMrM5Pc/edit?gid=1433193727#gid=1433193727&range=A1) : spreadsheet that parses and organizes skeleton data
3. [g-analyzer.py](../../tools/skeleton/g-analyzer.py): parses skeleton data and creates detailed summary
4. [Tellius Forge Blender plugin](https://github.com/ltra043/tellius-forge/releases/latest): supports import, modification, and export of FE9/FE10 skeleton files.
5. [App for Tellius Unit Map Model Porting](https://github.com/ltra043/tellius-unit-model-ports): supports FE10 to FE9 porting  
6. [TelliusModding](https://github.com/klg-tellius/TelliusModding/tree/main): independent FE9 research project by klg-tellius (readers for `.g`, `.gs`, `.ga`, and an archived articles)

</details>

## Research Status

**Credits.** This reference contains Jade's own analysis, cross-checked against the independent FE9 research published in the [TelliusModding](https://github.com/klg-tellius/TelliusModding/tree/main) project by klg-tellius. Terminology differences are listed in [§10](#10-terminology-notes).

**Testing scope.**
- TelliusModding FE9 research covers the whole FE9 disc (1,785 skeletons, 56,836 bones) and rebuilds every shipped `.g` byte-for-byte; its claims are **FE9-only**. FE10 behavior is assumed identical unless a difference is stated, and has been tested far less.
- Own testing concentrated on `ymu` skeletons (map models, FE9 and FE10) and on a few FE9 `zu` skeletons (battle models), notably `drm2` (134 bones, six root trees).
- Scale and rotation behavior is better documented than the two pivot-offset slots (`+136`, `+148`).

<details>
<summary><b>Research Status Legend</b></summary>

- **Confirmed** = verified through direct testing, file modification, in-game debugging, or exact reproduction of stored values across the shipped files
- **Strong evidence** = observed consistently across many files but not fully proven (keywords: likely, seems, usually, corresponds)
- **Reported** = plausible statement made in external references, but not verified by Jade.
- **Hypothesis** = plausible interpretation requiring further validation (keywords: possible, may be related to, potentially, theorize)

</details>

---

## 1. Overall Skeleton File Layout

| Offset | Content |
|--------|---------|
| `0x00` | **Header** (16 bytes) |
| `0x10` | Bone record 0 (244 bytes) |
| `0x104` | Bone record 1 (244 bytes) |
| ... | Remaining bone records |
| `0x10 + n*0xF4` | **String pool:** `rootname\0name0\0name1\0...name(n-1)\0` |

Total file size = `0x10 + bone_count * 0xF4 + string_pool_size`. There is no padding between sections and no trailing padding after the last name. Every shipped `.g` rebuilds byte-for-byte from this layout. **Confirmed.**

---

## 2. File Header

**Size:** 16 bytes / 0x10 bytes

| Offset | Type | Field | Notes |
|--------|------|-------|-------|
| `+0` | uint32 | reserved | Always 0. |
| `+4` | uint32 | string_pool_offset | Absolute byte offset of the string pool from file start. Equals `0x10 + bone_count * 0xF4`. |
| `+8` | uint32 | bone_count | Total number of bone records. |
| `+12` | uint32 | bone_array_offset | Always `0x10`. |

The loader relocates `string_pool_offset` and `bone_array_offset` into memory pointers (see [§7](#7-hierarchy-and-loading)).

---

## 3. Bone Record Format

**Size:** 244 bytes / 0xF4 bytes. The record is a header of tree links and flags, an inverse bind matrix, a **value block** of 43 floats, and a footer.

| Offset | Size | Type | Field | Notes |
|--------|------|------|-------|-------|
| `+0x00` (0) | 4 | int32 | parent_index | `-1` = root. |
| `+0x04` (4) | 4 | int32 | next_sibling | `-1` = last child of its parent. Root bones are chained through this field too (see [§7](#7-hierarchy-and-loading)). |
| `+0x08` (8) | 4 | int32 | first_child | `-1` = leaf. |
| `+0x0C` (12) | 4 | uint32 | flags | Which terms of the value block are used; see [§4](#4-term-flags). |
| `+0x10` (16) | 48 | f32×12 | inverse bind matrix | 3×4. Inverse of the bone's world matrix in the **bind pose**; multiplied after the bone's world matrix when drawing. See [§3.3](#33-inverse-bind-matrix). |
| `+0x40` (64) | 172 | f32×43 | **value block** | The values the animation system reads and overwrites; see [§3.2](#32-value-block). |
| `+0xEC` (236) | 2 | uint16 | bone_index | This bone's own index. The loader overwrites it with the true index. |
| `+0xEE` (238) | 2 | uint16 | rotation_order | Euler rotation order; always `1` (XYZ). See [§3.5](#35-euler-rotation-order). |
| `+0xF0` (240) | 4 | uint32 | name_offset | Byte offset of the bone's null-terminated name within the string pool (relative to pool start). |

**Confirmed.** The first three fields, the value block and the footer use the same offsets in the runtime bone array ([§8](#8-runtime-structures-and-engine-routines)).

### 3.1 Conventions used by the value block

- **Rotate pivot and scale pivot** are positions in the **parent's frame** (the parent's frame is the parent's world matrix; for a root, model space).
- **Translate** is a position offset, also in the parent's frame.
- The pivot positions and translate are **not** independent in effect: only their sum matters for where the joint ends up (see [§6.1](#61-local-matrix)), but they are used differently when the bone rotates or scales (see [§5](#5-pivot-bones-and-offset-bones-class-a--class-b)).

### 3.2 Value block

The value block is 43 floats at `+0x40`. Each animation curve targets one slot by its slot number (the "channel" number in `.ga` files); a curve overwrites that slot with an absolute value. **Confirmed.**

| Slot | Record offset | Field | Used when flag bit set | Default |
|:---:|:---:|-------|:---:|---------|
| 0–2 | `+0x40` (64) | **scale** X/Y/Z | 3 (`0x008`) | (1, 1, 1) |
| 3–5 | `+0x4C` (76) | **rotate** X/Y/Z, degrees | 4 (`0x010`) | (0, 0, 0) |
| 6–8 | `+0x58` (88) | **translate** X/Y/Z | 5 (`0x020`) | (0, 0, 0) |
| 9–11 | `+0x64` (100) | **joint orient** X/Y/Z, degrees | 6 (`0x040`) | (0, 0, 0) |
| 12–14 | `+0x70` (112) | **rotate pivot** X/Y/Z | 7 (`0x080`) | (0, 0, 0) |
| 15–17 | `+0x7C` (124) | **scale pivot** X/Y/Z | 8 (`0x100`) | (0, 0, 0) |
| 18–20 | `+0x88` (136) | **pivot offset 1** X/Y/Z | 9 (`0x200`) | (0, 0, 0) |
| 21–23 | `+0x94` (148) | **pivot offset 2** X/Y/Z | 10 (`0x400`) | (0, 0, 0) |
| 24–26 | `+0xA0` (160) | **rotate axis** X/Y/Z, degrees | 11 (`0x800`) | (0, 0, 0) |
| 27–30 | `+0xAC` (172) | **quaternion** X/Y/Z/W | — | unused |
| 31–42 | `+0xBC` (188) | **seed matrix** (3×4) | — | see [§3.4](#34-seed-matrix) |

Notes:
- **Scale pivot** repeats the rotate pivot in every observed bone. **Confirmed** (the stored seed matrices rebuild exactly with scale pivot = rotate pivot).
- **Pivot offset 1** is added to translate when building the local matrix; verified on all 51 bones of `bishop2_cef` (including `Face_locator`, flag bit 9). **Confirmed.** Pivot offset 2 has not been observed with non-default values; its role (if any) is open. The two offsets are likely the "rotate pivot translation" and "scale pivot translation" of a Maya-style transform. **Hypothesis.**
- **Joint orient** has never been seen as an animation curve (static value). **Confirmed** over the whole FE9 and FE10 `ymu` collections.
- **Quaternion** (slots 27–30): described as a rotation quaternion used only when an animation's format flags select quaternion rotation (header word 3 bit 1); no shipped animation does so (word 3 is `0x11` in every file). The routine that would consume it (`fn_8020B198`) has not been decompiled. **Hypothesis.**
- The value block slots are the same slots that `.ga` curve channels 0–14 address (channels 9–11 and 15+ are never animated).

### 3.3 Inverse bind matrix

The 12 floats at `+0x10` form a 3×4 matrix: rows at `+0x10`, `+0x20`, `+0x30`, translation in the 4th column (floats 3, 7, 11). Its 3×3 part is the bone's *inverse bind rotation*.

- It is the **inverse of the bone's world matrix in the bind pose** — the pose the mesh was attached in. **Strong evidence.**
- Bone palette submeshes and blended vertices are drawn through `world[bone] × inverse_bind[bone]`; single-bone submeshes use `world[bone]` only. **Confirmed.**
- An identity inverse bind matrix (most pivot bones) means the bone's bind world matrix is the identity. Vertices skinned only to such bones are stored in model space when the bone's seed world is also the identity, or in the bone's own space when the seed chain carries rotation (the seed pose then assembles them). See [§6.3](#63-bind-pose-and-seed-pose).
- Applying the inverse of this matrix to a bone's rotate pivot gives the bone's joint position in the bind pose.

### 3.4 Seed matrix

The 12 floats at `+0xBC` are the parent-relative **bind transform the engine seeds each frame's bone hierarchy from**: the local matrix that the bone's own value-block values produce ([§6.1](#61-local-matrix)).

- It matches the matrix rebuilt from the values on 56,463 of 56,836 disc bones (FE9) and on 131 of 134 bones of `drm2`. **Confirmed.**
- A pivot bone with no translate, rotation or scale has an **identity** seed matrix (the pivot cancels out: `T(p)·T(−p)`); its seed translation column is the `translate` value, not the pivot. An offset bone's seed translation column is its translate.
- Mismatches (373 of 56,836 on FE9): in `drm2`, `prefix_rope_03` (stored rotation −90° about Y that its values do not contain) and both wing tips (`prefix_l_wing_bone_tip`, `prefix_r_wing_bone_tip`; an extra rotation with first column (0.8275, −0.3332, 0.4519)). All three are leaf tips; joint positions are unaffected. Cause unknown.
- Bones that no animation drives keep this matrix; bones an animation drives have their local matrix rebuilt from the curve values every frame.

### 3.5 Euler rotation order

`+0xEE` selects how the three axis rotations are composed. The engine builds a single-axis matrix per axis and concatenates them in the listed sequence. **Confirmed** (decompilation); every observed bone uses `1`.

| Value | Order | First axis | Second axis | Third axis |
|-------|-------|-----------|-------------|-----------|
| 1 | XYZ | X | Y | Z |
| 2 | YZX | Y | Z | X |
| 3 | ZXY | Z | X | Y |
| 4 | XZY | X | Z | Y |
| 5 | YXZ | Y | X | Z |
| 6 | ZYX | Z | Y | X |

Order 1 gives `R = Rz·Ry·Rx`:

```
row0:  cz·cy    cz·sy·sx − sz·cx    cz·sy·cx + sz·sx
row1:  sz·cy    sz·sy·sx + cz·cx    sz·sy·cx − cz·sx
row2: −sy       cy·sx               cy·cx
```

---

## 4. Term Flags

The 32-bit `flags` field at `+0x0C` records **which terms of the value block the bone uses**. Bits 3–11 map one-to-one onto the value-block slot groups of [§3.2](#32-value-block). **Strong evidence**: on `drm2`, a bit is set exactly when its group holds non-default values (no counterexample across all 134 bones for bits 3–8 and 11); the scale bit is confirmed by the rest-scale survey of the `ymu` collection (every scale-0 bone has bit 3 set), bit 9 by `bishop2_cef`.

| Bit | Mask | Term | Value-block slots |
|:---:|:---:|------|:---:|
| 3 | `0x008` | scale | 0–2 |
| 4 | `0x010` | rotate | 3–5 |
| 5 | `0x020` | translate | 6–8 |
| 6 | `0x040` | joint orient | 9–11 |
| 7 | `0x080` | rotate pivot | 12–14 |
| 8 | `0x100` | scale pivot | 15–17 |
| 9 | `0x200` | pivot offset 1 | 18–20 |
| 10 | `0x400` | pivot offset 2 | 21–23 |
| 11 | `0x800` | rotate axis | 24–26 |

**Combination with animation.** When the engine evaluates a bone it works with `channel_flags = animation_channel_mask | bone.flags`, so a term is applied if the animation supplies that channel *or* the bone's own flag has the bit set. The animation's per-bone `channel_mask` uses the same bit positions for scale (`0x08`), rotate (`0x10`) and translate (`0x20`). **Confirmed.**

**Bits not explained.**
- **Bit 2 (`0x04`)** is set on most bones that have a scale, rotate or translate term (on `drm2` it is set on exactly the 103 bones that have bit 5), but not on all (e.g. `0x190`). Meaning unknown.
- **Bit 1 (`0x02`)** is set on `0x26`, `0x66`, `0x76`, `0x826`, `0x866`, `0x46` and clear on `0x24`, `0x2C`, `0x34`, `0x14`, `0x1AC`. Possibly "bone carries skinned geometry". **Hypothesis.**
- **Bit 0 (`0x01`)** is set on the FE10 counterparts of the FE9 chain flags (`0x27`, `0x67`, `0x77`) and is otherwise absent.
- **Bits 12–17** are never set. **Bits 18+** appear on a few FE10 bones (`0x401AC`, `0x407BC`; bit 18).
- Load-time bits derived from the bone *name* are ORed in by the loader (see [§7](#7-hierarchy-and-loading)); the on-disc value does not contain them.
- One counter-observation to the bit-6 rule: on `lord2`, some `0x26` bones were reported with non-zero joint orient although bit 6 is clear. Not re-examined.

### 4.1 Observed flag values

Decoded with the term bits above (bits 0–2 listed separately because their meaning is open).

| Flags | Terms used | Other bits | Seen in |
|-------|-----------|-----------|---------|
| `0x000` | none | — | root / identity bone |
| `0x00C` | scale | 2 | rare, some FE9 models |
| `0x014` | rotate | 2 | rare (`d_knight1_j`) |
| `0x180` | rotate pivot, scale pivot | — | **most common bone in both games** |
| `0x18C` | pivots, scale | 2 | weapon bones that can be hidden (rest scale 0 in every case seen) |
| `0x190` | pivots, rotate | — | rare (`beast_ti`) |
| `0x194` | pivots, rotate | 2 | rare |
| `0x1A4` | pivots, translate | 2 | weapon attachment bones |
| `0x1AC` | pivots, translate, scale | 2 | rare (`pegasu2`, `drm2` `Base`, `polySurface1`) |
| `0x024` | translate | 2 | roots, anchors, chain tips |
| `0x026` | translate | 2, 1 | FE9 animated chain bone |
| `0x027` | translate | 2, 1, 0 | FE10 counterpart of `0x26` |
| `0x02C` | translate, scale | 2 | `drm2` `transform1` |
| `0x02F` | translate, scale | 2, 1, 0 | rare (overworld variant) |
| `0x034` | translate, rotate | 2 | `drm2` |
| `0x046` | joint orient | 2, 1 | rare (`tiamat` horse tail) |
| `0x066` | translate, joint orient | 2, 1 | FE9 chain bone below a joint-orient root |
| `0x067` | translate, joint orient | 2, 1, 0 | FE10 counterpart |
| `0x076` | translate, joint orient, rotate | 2, 1 | FE9 horse/cloth variant |
| `0x077` | translate, joint orient, rotate | 2, 1, 0 | FE10 cloth/skirt variant |
| `0x826` | translate, rotate axis | 2, 1 | `drm2` `Tail2` |
| `0x866` | translate, joint orient, rotate axis | 2, 1 | `drm2` dragon bones, `tiamat` |
| `0x394` | pivots, pivot offset 1, rotate | 2 | FE10 / `bishop2_cef` |
| `0x3B4` | pivots, pivot offset 1, translate, rotate | 2 | FE10 / `bishop2_cef` |
| `0x7BC` | pivots, offsets 1 and 2, translate, rotate, scale | 2 | FE10 |
| `0x401AC`, `0x407BC` | as `0x1AC` / `0x7BC` | bit 18 | FE10 |

### 4.2 FE9 vs FE10

FE10 skeletons use the `…7` variants (`0x27`, `0x67`, `0x77`) where FE9 uses `…6`; the term bits are identical. FE10 additionally uses bits 9, 10 and 18+. `0x46` (joint orient only) is present in FE9 (`tiamat`) and very rare or absent in FE10.

---

## 5. Pivot Bones and Offset Bones (Class A / Class B)

Bones are conventionally sorted into two categories by `flags & 0x180`:

| Test | Name | Shorthand | Meaning |
|------|------|:---:|---------|
| `flags & 0x180 ≠ 0` | **pivot bone** | Class A | The bone's position is stored as its **rotate pivot** (and scale pivot). It rotates and scales about that point. Translate is normally zero. |
| `flags & 0x180 = 0` | **offset bone** | Class B | The bone's position is stored as its **translate**, an offset from the parent's frame. Pivots are zero. |

**What the distinction means.** The engine has no notion of a class: it only applies the terms whose flags are set ([§4](#4-term-flags)). Both kinds of bone put their joint at the same place, `world[parent] · (translate + offset1 + pivot)` ([§6.1](#61-local-matrix)). The difference is **how the position is encoded**, and therefore what the stored numbers are relative to:

- A **pivot bone** with no rotation or scale has an identity local matrix, so its frame origin is the parent's. A chain of unrotated pivot bones therefore all share one frame origin, and every pivot is effectively an **absolute model-space position**. Rotating the bone turns it about its joint.
- An **offset bone** has pivot 0, so its frame origin sits **at its own joint**. The translate is an **offset from the parent's joint** (rotated by the parent's chain rotation). Rotating the bone also turns it about its joint.

Both therefore rotate about their joints; they differ in what their numbers are relative to.

**Typical use in the shipped files.**
- Map models (`ymu`): almost every bone is a pivot bone (`0x180`) with an identity inverse bind matrix; the skeleton is placed in model space and each bone rotates about its joint. Offset bones (`0x26`, `0x66`, `0x76`) appear in chains such as capes, hair, wings, and replacement limb chains, and carry real inverse bind matrices.
- Battle bodies (`zu`): most bones are offset bones placed from their parent with no rest rotation; a few (`Base`, weapon sockets, `target`) are pivot bones. `drm2` is the known exception to "no rest rotation" (seven dragon bones have a −180° rotate axis).
- Census of three `ymu` skeletons: `lord` 22 `0x180` bones with identity inverse bind matrices, 2 `0x24`, 4 `0x26` with real ones (no joint orient); `bishop2` 20 / 3 `0x26` / 13 `0x66` with joint orient; `fighter2` 37 / 1 / 7.

**Limits of the classification.**
- It is a property of the flag bits, not a separate field. A bone may combine both conventions (`0x1AC`: pivots plus translate plus scale; `drm2` `Base` has translate `(0, −0.555, 0)` and scale 0.909).
- A pivot bone's position is "absolute" only while the ancestors do not rotate or scale; below a joint-orient or rotate-axis bone the pivot is expressed in that bone's rotated frame.
- Old descriptions of a "ClassA1 sandwich" rotation block and of A bones storing "world positions" described this convention before the term-flag meaning was known; they are superseded by [§6](#6-bone-matrices-poses-and-skinning).

---

## 6. Bone Matrices, Poses and Skinning

### 6.1 Local matrix

The local matrix of a bone is built the way a Maya transform is: translate, then rotation about the rotate pivot (joint orient, rotate, rotate axis), then scale about the scale pivot.

```
L = T(translate + offset1) · T(p) · JO · Rot · RO · S · T(−p)
```

`p` = rotate pivot (equal to the scale pivot), `JO` = joint orient, `Rot` = rotate, `RO` = rotate axis, `S` = scale (diagonal), each rotation `Rz·Ry·Rx`. **Confirmed** (reproduces the stored seed matrix, including all seven rotate-axis bones of `drm2` to 5 decimals).

- The order of `Rot` and `RO` is not determined: every bone with a rotate axis has a zero rest `Rot`. The order shown follows the Maya convention. Only animated rotation on a rotate-axis bone can decide it. **Open.**
- A flag-gated term whose flag bit is clear is treated as its default.

### 6.2 World matrices and joint position

**Definition.** The **world matrix** of a bone, `world[b]`, is a 3×4 affine matrix that converts coordinates from the bone's own frame to model space. It is the product of the local matrices ([§6.1](#61-local-matrix)) of the bone and all its ancestors, applied root first: `world[b] = L[root] · … · L[parent] · L[b]`. "World" therefore means *model space*, not the game world. A point `v` stored in the bone's frame is at `world[b] · v` in model space, and the frame itself is the coordinate system defined by that matrix.

- A bone's own `translate`, pivots and children's offsets are all expressed in the parent's frame, i.e. they pass through `world[parent]`.
- The **origin of a bone's frame** is `world[b]` applied to (0, 0, 0). It is *not* generally the joint. For an offset bone (pivot 0) the origin is the joint; for a pivot bone the origin is wherever the parent's frame origin is (shifted only if the bone itself rotates or scales about its pivot). The joint is `world[b]` applied to the rotate pivot.
- Which world matrix is meant depends on which local matrices are chained. The **seed world** chains the seed matrices (`+0xBC`), i.e. the values stored in the skeleton; this is what the engine computes for a bone no animation drives, and what it builds when an animation drives the bone with curve values. The **bind world** is the inverse of the inverse bind matrix. When this note writes plain `world[b]` it means the seed world (or its animated equivalent); see [§6.3](#63-bind-pose-and-seed-pose) for how the two relate.
- The engine stores one 3×4 world matrix per bone in a runtime array (`aux_obj`, 0x30 bytes per bone, indexed by bone_index; see [§8](#8-runtime-structures-and-engine-routines)).

```
world[b] = world[parent] · L[b]          (roots: world = L)
joint[b] = world[b] applied to p  =  world[parent] applied to (translate + offset1 + p)
```

The joint position is independent of the bone's own rotation and scale. A child's translate and pivots pass through the parent's `JO · Rot · RO · S`, so a **rotate axis (or joint orient, or scale) on a parent affects the position of all its descendants**. **Confirmed.**

The engine walks the tree first child, then next sibling, from bone 0, so parents are evaluated before children. In every analysed skeleton the file order also has parents before children.

### 6.3 Bind pose and seed pose

Two poses are stored in the file at once:

- **Bind pose** — the pose the mesh was attached in. Mesh vertices are stored in this space and the inverse bind matrices are its inverse.
- **Seed pose** — the pose obtained by chaining the seed matrices (`world[b] = world[parent] · seed[b]`). The engine uses it for every bone that no animation drives (and as the starting point of each frame).

The game draws a vertex through `world_seed[b] × inverse_bind[b]`. Consequences:

- **Real inverse bind matrix:** bind world = `inverse(inverse_bind[b])`. On `lord`, `bishop2` and `fighter2` every bone with a real inverse bind matrix has `world_seed × inverse_bind` = identity, i.e. seed pose = bind pose.
- **Identity inverse bind matrix:** bind world = identity, so the drawn matrix is the seed world itself. Where the seed chain carries rotation (pivot bones below joint-orient chains such as `lord2`'s legs), the seed pose is what assembles the stored vertices into the finished character.
- **Bind ≠ seed** on whole rigs: in `drm2` the rider's `Reference` root has translate (0, 0, −5) and `Base` has scale 0.909, but the mesh was bound with `Reference` at 0 and `Base` unscaled. Bind positions implied by the inverse bind matrices differ from the seed chain by (0, 0.555, −5) for the rider and (0, 0, −5) for the dragon.
- Six `drm2` dragon leaf tips (`TailTip`, `Top`, both hand tips, both `HoofEnd`) have positions implied by their inverse bind matrices that disagree with the rest of their rig (off by 1.6–27 units); none carries skinned vertices. Unexplained.

### 6.4 Scale and visibility

- Animation scale curves are **absolute**; a scale of 0 hides the bone and everything below it. A **rest scale of 0** in the skeleton therefore hides a bone in the seed pose unless an animation keys its scale to 1.
- In the FE9 `ymu` collection, 20 of 92 skeletons have a rest scale ≠ 1 and 12 of those contain a 0; every scale-0 bone has flags `0x18C`.
- Two weapon-visibility patterns exist: **rest 1, animations hide** (the common case) and **rest 0, animations show the weapon in use** (`dragon`, `dragon2`: one weapon bone is keyed to 1 in each weapon set's animations, the others stay hidden at rest 0).
- Weapon bones are children of a hand bone; map models keep every weapon as part of the body, one bone per weapon.

### 6.5 Drawing

- A draw call that follows one bone loads that bone's world matrix. A draw call with a bone palette (up to 10 bones, the number of GameCube hardware matrix slots) loads `world × inverse_bind` for each bone into a slot. Blended vertices are skinned on the CPU with the same matrices. See the Body format notes.
- Character rigs mostly store body vertices in model space with identity inverse bind matrices and pivots placed at the joints. Single-bone submeshes on static models store vertices in the bone's local space.

---

## 7. Hierarchy and Loading

**Tree.** Parent, next sibling and first child indices form a first-child / next-sibling tree. **Confirmed.**

**Multiple roots.** A skeleton may contain several root bones (parent `-1`). They are linked through their `next_sibling` fields in index order. `drm2` (6 roots) chains `0 → 56 → 57 → 73 → 123 → 133`; since the engine starts at bone 0 and follows these links, a root with `next_sibling = -1` would hide every later tree. **Confirmed.**

| Root (`drm2`) | Bones | Content |
|---|---:|---|
| `Reference` (0, `0x24`, translate (0, 0, −5)) | 56 | rider body rig |
| `target` (56, `0x180`) | 1 | camera-related |
| `drm1_model` (57) | 16 | unskinned leftover rig (carries `SP`/`AX` anchors) |
| `prefix_rdr2_Reference` (73, `0x24`, translate (0, 0, −5)) | 50 | dragon |
| `rdr2_model` (123) | 10 | unskinned leftover rig |
| `_cam_` (133) | 1 | camera anchor |

**Loader** (`0x80065F48`). On load the engine:
1. relocates the string-pool offset and bone-array offset into pointers;
2. converts each record's parent, next-sibling and first-child indices into pointers (`-1` → null);
3. ORs **name-derived bits** into `flags` (see [§9](#9-string-pool-and-bone-names): anchor bones, `persp`, names containing `_bl_` / `_by_`);
4. overwrites the record's own-index field (`+0xEC`) with the bone's true index (always equal on disc).

---

## 8. Runtime Structures and Engine Routines

The loader keeps the bone records as a runtime array with the **same 0xF4 stride and field offsets** as the file; the array pointer is at `bone_table_obj + 0x0C`. The value block is the live scratch space of the animation system: keyframe evaluation writes curve values straight into the slots of [§3.2](#32-value-block), and the 43 floats are copied as the evaluation buffer (`eval_result`) that the transform routine reads. **Confirmed.**

| Eval offset | Slot group | Flag bit | Transform block |
|:---:|-----------|:---:|---------|
| `+0x00` | scale | 3 | scale matrix |
| `+0x0C` | rotate | 4 | primary Euler rotation |
| `+0x18` | translate | 5 | translation matrix |
| `+0x24` | joint orient | 6 | secondary Euler rotation |
| `+0x30` | rotate pivot | 7 | pivot sandwich around the rotation |
| `+0x3C` | scale pivot | 8 | pivot sandwich around the scale |
| `+0x48` | pivot offset 1 | 9 | second pivot term |
| `+0x54` | pivot offset 2 | 10 | extra translation frame |
| `+0x60` | rotate axis | 11 | tertiary Euler rotation |
| `+0x6C` | quaternion | clip flag `0x2` | pre-built rotation (unused by shipped clips) |

**Routines** (names from decompilation; addresses from the GameCube `main.dol`).

| Name | Role |
|------|------|
| `fn_80062848` / `build_bone_local_matrix` | Builds one bone's local 3×4 matrix from the evaluation buffer, gated by `channel_flags`, and writes it to `aux_obj + bone_index * 0x30`. |
| `fn_80061930` | Main pose evaluation; forms `channel_flags = channel_mask \| bone.flags`. |
| `fn_80065A20` / `gactor_build_bone_hierarchy_matrices_recursive` (`0x80065AF8`) | Walks first child then next sibling and chains `aux[node] = aux[parent] · aux[node]`. |
| Skeleton loader (`0x80065F48`) | See [§7](#7-hierarchy-and-loading). |
| `fn_8020AB1C`, `fn_8020AB7C` | Identity 3×4; 3×4 concatenation (like `PSMTXConcat`). |
| `fn_8020AE58` / `fn_8020AEC8` | Single-axis rotation matrix (angle converted from degrees). |
| `fn_8020B098`, `fn_8020B118` | Translation matrix; diagonal scale matrix. |

**Hierarchy propagation** (confirmed by decompilation and live traces): for each node with a parent, `aux[node] = concat(aux[parent], aux[node])` — the parent's current matrix combined with the node's own, written into the **node's own** slot — then recursion into `first_child` and `next_sibling`. A pre-order walk is therefore sufficient. Combined with the local-matrix routine's output, this reproduces the bone's true world rotation to high precision. One translation-magnitude discrepancy on a single bone (`0x18`, Y component) remained unexplained in a live comparison.

---

## 9. String Pool and Bone Names

The pool begins at `string_pool_offset` as a run of null-terminated ASCII strings:

```
[unknown]\0        ← root name; referenced by no bone (always "[unknown]" in observed files)
bone_name_0\0
bone_name_1\0
...
```

`name_offset` is relative to the **start of the pool**, not the file. The first entry occupies offset 0. Names are stored in bone order, one per bone.

### 9.1 Anchor bones

A bone whose name is **wrapped in underscores** (`_s1_`, `_sw1_`, `_cam_`) is flagged as an **anchor** when the skeleton loads. Anchors are the only bones the engine ever finds by name: it asks for the first anchor containing a token, such as `s1` / `s2` (present on every class rig), weapon-trail pairs (`sw1` / `sw2`, `sp`, `ax`, `ja`, `ha`, `bw`, `ex`), `root`, `cam`, `sun`, `ref`, `tail`, `r_hand` / `l_hand`, and the feet. Names containing `_bl_` and `_by_` receive two further loader bits whose effect is open; a bone named `persp` is marked specially. Every other name is free: a skeleton with entirely different names and proportions works in game once it has the anchors the code asks for. **Confirmed** (engine and in game).

Use of anchors:
- **Battle:** `_r_hand_` holds the weapon (`_l_hand_` for bows), `_root_` follows the hips so a step in one animation carries into the next, `_cam_` is a camera target, feet and `_pl_` sockets are optional.
- **Map:** `_s1_` / `_s2_` place the feet and shadow; pairs such as `_ax1_` / `_ax2_` mark the ends of a weapon's swing trail.
- Anchors carry no mesh influence; they have been observed with flag `0x24` in several skeletons.

### 9.2 Naming conventions
Note: these are naming conventions observed mostly for FE9 ymu character overworld models.

- **Path names.** The `|` character encodes the parent-to-child chain within one name (a DAG path): `R_arm1|R_arm2|R_hand` can be thought of as the bone `R_hand` below `R_arm1|R_arm2` below `R_arm1`, although the bone's name is technically the fully expanded `R_arm1|R_arm2|R_hand`.
- **Namespace.** `:` separates a namespace from a name (`armor_enemy:kensyu:body1` on the FE9 general), probably distinguishing modular body parts. Names may also legitimately contain `__` (`prefix__l_hand_`).
- **bone 0** is often `all` or `*_locator` (`wayu_locator`). `hip`, `hip0`, `hip_locator` is normally the main body bone, a direct child of bone 0 and the parent of every body-influencing bone. In ymu models and non-mounted zu models, other direct children of `bone 0` usually influence no mesh and may be modelling leftovers; they can share naming similarity with an active bone (`hip0` unused, `hip` active).
- **Torso and limbs.** `body` / `chest` normally parents the upper body. Infantry rigs have three bones per arm (shoulder, forearm, hand) and three per leg (thigh, calf, foot), plus a non-influencing anchor at the front of each foot. An extra hand anchor (`_r_hand_`) is common, and `L_skirt` or similar bones can interrupt leg sequences.
- **Laterality.** `L`, `l`, `left` / `R`, `r`, `right` refer to the model's own left and right.
- **Mounted units.** For a rider with a mount, the main skeleton is usually the mount's; the rider's skeleton is a child of the mount's `body` (or equivalent).
- **Weapons**, if present, are usually children of the right hand bone. They typically have 2 children (occasionally more or less), named in the format: `_{wp}{#}_` (such as `_sw1_` and `_sw2_`).
- **Language.** Body parts and weapons are mostly English or English shorthand (`l_leg2`, `R_arm1`, `Sword`); accessories often use romanized Japanese (`saya` sheath, `manto` cape).
- Auto-generated names (`joint8`, `pCube6`, `plane4`) are common and say nothing about the body part. Names are not consistent between models.

---

## 10. Terminology Notes

Other documents, tools and earlier versions of these notes use different words for some of the same things. This reference uses the left-hand term. (The full catalogue, including other formats, is kept in `terminology.md`.)

| This reference | Also seen as |
|---|---|
| inverse bind matrix (`+0x10`) | bind matrix, inverse-bind matrix, `skin_matrix` |
| bone palette | bone subset |
| submesh | shape; chunk |
| value block (`+0x40`) | unknown floats, reserved block |
| translate (`+0x58`) | local translation, `p88` |
| joint orient (`+0x64`) | local rotation, `transrot` |
| rotate pivot (`+0x70`) | bone position, bone head, `p112` |
| scale pivot (`+0x7C`) | position duplicate |
| rotate axis (`+0xA0`) | — (previously undocumented) |
| seed matrix (`+0xBC`) | pre-computed 3×4 local transform |
| term flags | IS-proprietary bitfield with opcode / store / load bits |
| pivot bone / offset bone (Class A / Class B) | Class A "world position" / Class B "local transform" |
| anchor bone | orientation bone, non-animated bone |
| bind pose / seed pose | skin pose (bind), rest pose or pose position (seed) |
| bone array offset (header `+12`) | first bone offset |
| root name (pool entry 0) | `[unknown]` entry |

---

## 11. Remaining Unknowns

- **Flag bits 0, 1, 2** (see [§4](#4-term-flags)); whether the load-time name bit (`_bl_`, `_by_`) corresponds to anything on disc.
- **Pivot offset 2** (`+148`, flag bit 10): never seen non-default; role in the matrix unknown.
- **Order of rotate and rotate axis** for animated rotation on a rotate-axis bone.
- **Quaternion slots** (`+172`): consumer (`fn_8020B198`) not decompiled; unused by shipped animations.
- **Seed matrices that do not rebuild** (373 on FE9; three on `drm2`).
- **Inverse bind matrices that disagree with their rig's bind offset** (six `drm2` dragon leaf tips) and why bind and seed differ on some rigs only.
- **Rest-pose pivot outlier** bones such as `polySurface4` of `fighter2`, whose pivot lies far from its parent and children.
- **Cape / cloth chains** (`0x66`, `0x67`, `0x77`): whether the engine applies runtime physics to them.
- **FE10 flags `0x27` / `0x67`:** whether bit 0 has a behavioral meaning or only distinguishes the game.
- **Function-address mismatches** between decompilation names (for example `fn_80062848` vs `build_bone_local_matrix` at `0x80062920`; `fn_80065A20` vs `0x80065AF8`) are unresolved: they may be the same routines at different entry points.
- **FE10-specific testing:** the rotate-axis, pivot-offset and bind-versus-seed findings come mainly from FE9; FE10 is expected, but not shown, to match.
