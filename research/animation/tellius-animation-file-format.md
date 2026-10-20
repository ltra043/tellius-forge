<h1 align="center">Tellius Animation File Format</h1>

<p align="center"><i>
Reverse-engineering notes on the format of Fire Emblem 9 and Fire Emblem 10 animation (<code>.ga</code>) files. <br>
See <a href="../body/tellius-body-file-format.md">Tellius Body File Format</a> and <a href="../skeleton/tellius-skeleton-file-format.md">Tellius Skeleton File Format</a> for analysis of other asset formats.</i><br><br>
<b>Author:</b> Jade (ltra043)<br>
<b>Last Updated:</b> 2026-10-13 (v2.0.1: terminology: fraction bits, first_key; 2026-10-04 v2.0.0: Header / Bone Table / Curve Table / Keyframe Data / Footer; channels, absolute values, footer slots and event track; unified terminology)
</p>

<details>
<summary>Keywords</summary>

 Fire Emblem animation format, Fire Emblem animations, FE9 animation format, FE10 animation format, Path of Radiance animations, PoR Animations, Radiant Dawn animations, Tellius animation research, .ga format, GameCube animation format, Wii animation format, reverse engineering, file format documentation, skeleton animation data, F-curve animation data, animation reverse engineering, game asset research, 3D animation format, Nintendo GameCube modding, Nintendo Wii modding, GameCube Modding, GC Modding, GC/Wii Modding

</details>

## Reader Information
- All multi-byte integers and floats are **big-endian** unless noted otherwise.
- **All listed offsets and size values are decimal values** unless prefixed with `0x` to indicate it is a hex value.
- **Bone index** means the index of a bone in the skeleton's bone array (the position of its record in the `.g` file, also stored in the record's `bone_index` field). Names such as *value block*, *rotate pivot*, *seed matrix*, *world matrix* and *bind pose* are used as defined in the [Tellius Skeleton File Format](../skeleton/tellius-skeleton-file-format.md) notes.

<details>
<summary><b>Table of Contents</b></summary>
 
1. **[General Structure](#1-general-structure)**
2. **[Header](#2-header)**
3. **[Bone Table](#3-bone-table)**
4. **[Curve Table](#4-curve-table)**
5. **[Keyframe Data](#5-keyframe-data)**
6. **[Footer](#6-footer)**
    - [6.1 FE9 Footer](#61-fe9-footer)
    - [6.2 FE10 Footer](#62-fe10-footer)
    - [6.3 Footer Slot 0: Event Track](#63-footer-slot-0-event-track)
    - [6.4 Footer Slot 1: Visibility (FE10)](#64-footer-slot-1-visibility-fe10)
    - [6.5 Other Footer Slots](#65-other-footer-slots)
7. **[How an Animation Drives the Skeleton](#7-how-an-animation-drives-the-skeleton)**
8. **[Terminology Notes](#8-terminology-notes)**
9. **[Remaining Unknowns](#9-remaining-unknowns)**

</details>

<details>
<summary><b>Additional Resources</b></summary>

1. [FE9 ImHex bookmarks](https://drive.google.com/file/d/1gEC-5amlmNdOrbVD1ffcL6yReEkhC1Zu/view?usp=drive_link) for `knight’s atk1_bw.ga`  
2. [FE10 ImHex bookmarks](https://drive.google.com/file/d/1R0Uo3316i4A9-4jWofwuXbDdNJDC2d2W/view?usp=drive_link) for fe10 `fighter3_n’s atk_2.ga` (handaxe)  
3. [ga-bookmark.py](../../tools/animation/ga-bookmark.py): creates **ImHex bookmarks** for animation files
4. [App for Tellius Unit Map Model Porting](https://github.com/ltra043/tellius-unit-model-ports) 
    - Currently supports FE10 to FE9 porting  
5. [FE10 ImHex bookmarks](https://drive.google.com/file/d/1wBQgxkHshERlykjIj5WD58jmAeRpy2Wl/view?usp=drive_link) for fe10 `fighter3_n’s skeleton.g`  
6. [Skeleton file viewer](https://docs.google.com/spreadsheets/d/1zbN7nSeyl0lY_XA7-t0zFUdaRjoDEF3c_laifMrM5Pc/edit?gid=1433193727#gid=1433193727&range=A1) : spreadsheet that parses and organizes skeleton data
7. [g-analyzer.py](../../tools/skeleton/g-analyzer.py): parses skeleton data and creates detailed summary
8. [How to port and edit ymu animation files - guide](https://docs.google.com/document/d/1oIBy46jQPswIIK-ls6cR9AbOMlFR7gbLdcyi7juQHbc/edit?usp=sharing)
9. [Tellius Forge Blender plugin](https://github.com/ltra043/tellius-forge/releases/latest): supports import, modification, and export of FE9/FE10 animation files.
10. [TelliusModding](https://github.com/klg-tellius/TelliusModding/tree/main): independent FE9 research project (readers for `.g`, `.gs`, `.ga`, and an article archive)

</details>

## Research Status

**Credits.** This reference contains Jade's own analysis, cross-checked against the independent FE9 research published in the [TelliusModding](https://github.com/klg-tellius/TelliusModding/tree/main) project by klg-tellius. Terminology differences are listed in [§8](#8-terminology-notes).

**Testing scope.**
- TelliusModding FE9 research covers the whole FE9 disc (4,422 animation files) and rebuilds every shipped `.ga` byte-for-byte, so the physical layout of the Header, Bone Table, Curve Table, Keyframe Data and FE9 Footer is **confirmed**. Its claims are **FE9-only**.
- Own testing concentrated on `ymu` (map model) animations of both games, with most in-game debugging on FE9. A scan of 7,460 `ymu` animation files (FE10 6,006, FE9 1,454) found header word 3 = `0x11` and header word 10 = 0 in every file, and no channel number outside 0–8 and 12–14 ([§4](#4-curve-table)).
- `zu` (battle) animations are expected to follow the same format; `yme` (effect) and scenery animations carry much more footer data, and use the same format up to the Footer.
- FE10 behavior is assumed identical to FE9 unless a difference is stated, with the exceptions of the Footer ([§6.2](#62-fe10-footer)) and scale handling ([§3](#3-bone-table)). Whether FE10 interpolates keys linearly is untested.

<details>
<summary><b>Research Status Legend</b></summary>

- **Confirmed** = verified through direct testing, file modification, in-game debugging, or exact reproduction of the shipped files
- **Strong evidence** = observed consistently across many files but not fully proven (keywords: likely, seems, usually, corresponds)
- **Reported** = plausible statement made in external references, but not verified by Jade.
- **Hypothesis** = plausible interpretation requiring further validation (keywords: possible, may be related to, potentially, theorize)

</details>

---

## 1. General Structure

An animation file holds the curves that overwrite values of a skeleton's bones over time. There are four main sections and one optional section:

| Offset | Section | Content |
|--------|---------|---------|
| `0x00` | **Header** | 12 uint32 words (0x30 bytes): footer offset, game flag, format flags, loop flag, start/end frames, section pointers |
| `0x30` | **Bone Table** | one 16-byte record per animated bone: `(bone_index, channel_mask, first_curve, curve_count)` |
| `curve_table_offset` | **Curve Table** | one 12-byte record per curve: channel, fraction bits, end frame, key count, first key |
| `keyframe_data_offset` | **Keyframe Data** | `(frame, value)` pairs, 4 bytes each, one run per curve |
| `footer_offset` | **Footer** (optional) | pointers and data blocks; event track and, in FE10, visibility |

A **curve** is one animated value: one channel of one bone (for example *rotate Z of bone 12*). A bone's curves are consecutive in the Curve Table, and the Bone Table says which curves belong to which bone. The three sections are laid out back to back with no padding, and every shipped `.ga` rebuilds byte-for-byte from this layout. **Confirmed.**

---

## 2. Header

**Size:** 48 bytes / 0x30 bytes, 12 big-endian uint32 words.

| Word | Offset | Field | Notes |
|:---:|:---:|-------|-------|
| 0 | `0x00` | footer_offset | File offset of the Footer, or 0 when there is none. Relocated by the loader. |
| 1 | `0x04` | reserved | Always 0. Relocated by the loader. |
| 2 | `0x08` | game_flag | The byte at `0x08` is the **game flag**: `00` FE9, `01` FE10. The remaining bytes of the word are 0. |
| 3 | `0x0C` | format_flags | `0x11` on every file: bit 0 = Euler rotation, bit 1 = quaternion rotation (never set), bit 4 = int16 keys. Without bit 4 the engine reads a float/Hermite layout that no file uses. This is the "byte `0x0F`" of earlier notes. |
| 4 | `0x10` | loop_flag | `0` = plays once, `1` = loops. See below. |
| 5 | `0x14` | start_frame | The frame playback starts at, and the frame a loop restarts at. See below. |
| 6 | `0x18` | end_frame | The frame playback ends (or loops) at. May run past the last keyframe, holding the final pose. |
| 7 | `0x1C` | bone_count | Number of Bone Table records (one per animated bone). |
| 8 | `0x20` | bone_table_offset | Always `0x30`. Relocated. |
| 9 | `0x24` | curve_table_offset | `0x30 + 16 × bone_count`. Relocated. |
| 10 | `0x28` | reserved | Always 0. Relocated (the loader treats it as a pointer slot). |
| 11 | `0x2C` | keyframe_data_offset | `curve_table_offset + 12 × curve_count`. Relocated. |

Words 0, 1, 8, 9, 10 and 11 are the file offsets the loader relocates into pointers (see [§7.2](#72-engine-routines)). **Confirmed.**

**The curve count is not stored.** The Curve Table runs from `curve_table_offset` to `keyframe_data_offset`, always an exact multiple of 12 bytes: `curve_count = (keyframe_data_offset − curve_table_offset) / 12`.

**Playback range.**
- **start_frame** is usually 0 or 1. In FE10 it is also commonly 0 or 1, except for the `motion*2_#.ga` animations. Raising it makes playback begin later in the data, which shortens an animation; lowering `end_frame` shortens it from the other end. **Confirmed**
- Both must remain compatible with the event track ([§6.3](#63-footer-slot-0-event-track)): events are only collected from frames the playback actually passes. An event outside `[start_frame, end_frame]` is never received and the combat code falls back to its failsafe. **Confirmed** in game (own testing: the damage event frame must lie strictly inside the range).
- Frame numbers are 16-bit in the file; in practice every frame is below 256.

**Looping.** `loop_flag` is nonzero for looping animations. These include the idle `ready` animations, `move` and `wait` animations, FE10's `twait` animations, and possibly others. A looping animation restarts at `start_frame` when it reaches `end_frame`; event codes 3 and 4 mark the loop's start and end ([§6.3](#63-footer-slot-0-event-track)).

---

## 3. Bone Table

**Location:** `0x30` (`bone_table_offset`). **Size:** `bone_count × 16` bytes. One record per animated bone. The table ties bones of the skeleton to curves in the Curve Table.

| Offset | Type | Field | Notes |
|:---:|------|-------|-------|
| `+0x00` | uint32 | bone_index | Index of the animated bone in the skeleton. Records are in **strictly ascending** bone_index order; a file with rows out of order may behave unexpectedly. |
| `+0x04` | uint32 | channel_mask | Which transform terms the bone's curves cover: `0x08` scale, `0x10` rotate, `0x20` translate. Add the values for several. Rotate-pivot curves add **no** bit (see below). |
| `+0x08` | uint32 | first_curve | Index (in the Curve Table) of the bone's first curve. |
| `+0x0C` | uint32 | curve_count | Number of consecutive curves belonging to the bone. Common values: 1, 3, 4, 5, 6, 9. |

**Consistency rules (confirmed on every shipped file).** `bone_count` equals the number of records; the first record's `first_curve` is 0; each record's `first_curve` equals the previous record's `first_curve + curve_count`; the last record's end equals the curve count of [§2](#2-header). The first animated record usually names the hip (bone 1, just below the root locator); some files start at bone 0.

**channel_mask bits** use the same positions as the term flags of a skeleton bone ([Skeleton note §4](../skeleton/tellius-skeleton-file-format.md)): bit 3 = scale, bit 4 = rotate, bit 5 = translate. A term is applied if the animation supplies it *or* the bone's own flags have it (`channel_flags = channel_mask | bone.flags`). The mask matches the channels of the bone's own curves, with one exception: the **rotate-pivot** curves (channels 12–14) appear under a mask with no corresponding bit. Groups with `channel_mask = 0` exist (109 in the FE10 and 159 in the FE9 `ymu` files); every one of them carries a rotate-pivot curve. **Confirmed.**

**Bones that are not listed** keep their seed matrix ([§7](#7-how-an-animation-drives-the-skeleton)).

**Invisibility.** Every bone is visible by default. A bone is hidden by an animated scale of 0 (see [§5](#5-keyframe-data)). In FE9 this is done with ordinary scale curves. In FE10 it is usually done by the visibility block in the Footer ([§6.4](#64-footer-slot-1-visibility-fe10)) and only sometimes with scale curves; FE10 bone records rarely have scale in their mask.

---

## 4. Curve Table

**Location:** `curve_table_offset`. **Size:** `curve_count × 12` bytes. One record per curve; the curves of one bone are consecutive, in ascending channel order.

| Offset | Type | Field | Notes |
|:---:|------|-------|-------|
| `+0x00` | uint16 | channel | Which slot of the bone's value block the curve overwrites (table below). The high byte is always 0. |
| `+0x02` | uint16 | fraction_bits_raw | The number of **fraction bits** is its high byte (`fraction_bits_raw >> 8`, 6 bits used); the low byte is 0. Values are decoded as `raw × 2^(−n)`, where n is the number of fraction bits. |
| `+0x04` | uint16 | end_frame | The frame of the curve's last keyframe, in every real file. |
| `+0x06` | uint16 | key_count | Number of keyframes. |
| `+0x08` | uint32 | first_key | Index (in keyframes, 4 bytes each) of the curve's first keyframe within the Keyframe Data. The upper 16 bits are always 0. |

**Channels.** The channel number is the *index of the slot it overwrites in the 43-float `value block` of the skeleton bone record* (offset `64 + 4 × channel` within the record). **Confirmed.**

| Channel | Skeleton offset | Meaning | Seen in files |
|:---:|:---:|---------|---|
| 0–2 | `+64` | scale X/Y/Z | yes |
| 3–5 | `+76` | rotate X/Y/Z (degrees) | yes |
| 6–8 | `+88` | translate X/Y/Z | yes |
| 9–11 | `+100` | joint orient X/Y/Z | **never** (static value) |
| 12–14 | `+112` | rotate pivot X/Y/Z | yes, rare |
| 15+ | `+124` ... | other value-block slots | never |

Over all 7,460 `ymu` animations of both games the only channels that occur are 0–8 and 12–14.

**Rotate-pivot curves.** About 3,000 pivot curves occur in the `ymu` files (FE10 688 curves in up to 210 files, FE9 2,391 in up to 365 files). **Every one has exactly one key**, i.e. a constant for the whole clip. The two bones studied in `lord` (`arml2`, `sword1`) and one in `dragon` (`polySurface19`: pivot X key 2.939 against a rest pivot of 1.974, the same constant in every animation of that model) all differ from the bone's rest pivot, and all have flags `0x180` (rotate pivot term, bit 7, set). Since the rotate pivot has no bit in `channel_mask`, it can only take effect through the bone's own flag, so these curves plausibly override the pivot the bone rotates about. Whether the engine applies them is **not yet confirmed**.

**Fraction bits observations.** A weapon that is hidden for the whole animation usually has `0x0F` fraction bits; a weapon hidden for only part of the animation usually `0x0E`.

---

## 5. Keyframe Data

**Location:** `keyframe_data_offset`, up to the Footer (or end of file). One run of keyframes per curve, **in Curve Table order**, with no sharing between curves.

| Offset | Type | Field | Notes |
|:---:|------|-------|-------|
| `+0x00` | uint16 | frame | Frame number. The game reads a 16-bit value; the high byte is always 0 in practice. |
| `+0x02` | int16 | value | Signed 16-bit raw value; the real value is `value × 2^(−fraction bits)`. |

Frames ascend within a curve. A curve's `end_frame` equals the frame of its last key.

**Values are absolute.** A keyframe value *replaces* the skeleton's stored value for that slot; it is not a delta. The slots decode as: scale unitless, rotate in **degrees** (Euler, XYZ order), translate in model units. **Confirmed** (decompilation, and animated translate keys sitting next to the bone's rest value: for example `joint8` of `lord2` has a translate Y key of 10.076 against a rest value of 10.077). Consequences:
- A **scale curve of 0 hides the bone** regardless of its rest scale; a **scale curve of 1 shows it**. A weapon that is hidden for the whole animation typically has one key at the start frame with value 0.
- **Translate** values are expressed in the parent's frame (the same frame as the skeleton's `translate`).
- Slots a file does not animate keep the skeleton's stored **seed pose** value.

**Interpolation is linear** between keys, and the first and last values are held before the first and after the last key. **Confirmed** for FE9 (decompilation of the keyframe evaluator); FE10 untested.

**Moving an animation to another skeleton.** Keys are absolute values tied to bone indices. An animation can be moved to a skeleton with other proportions by matching bones by name, shifting translate (and rotate-pivot) keys by the difference between the two skeletons' rest values, and copying rotation and scale keys as they are (this assumes matching bone orientations). **Strong evidence.**

---

## 6. Footer

The Footer is optional: `footer_offset` (header word 0) is 0 when there is none, and the file then ends with the Keyframe Data. It holds data blocks called **footer slots**, reached through the **Footer Pointer(s)**. All pointers in it are absolute file offsets, so moving the Footer, or changing the size of the sections before it, requires rewriting them.

**Slots.** A footer slot is a block of data of one kind. Slot numbers identify the kind:

| Slot | Content | Games |
|:---:|---------|---|
| 0 | **Event track**: timed event codes (damage, swing, loop markers, sound, effects) | FE9, FE10 |
| 1 | **Visibility**: timed show/hide of bones | FE10 only |
| 2–8 | not decoded; appear on effect and scenery animations | FE9 |

FE9 keeps a fixed table of nine slot pointers, so an unused slot is a zero entry. FE10 lists only the slots that are present, each tagged with a **Slot Identifier**, so slot 1 can be present without slot 0. Whether FE10 slot 1 corresponds to an FE9 slot is unknown.

Which animations have an event track: attacks, criticals, magic, tackles, and moves; never damage, dead, escape, ready or wait. In `ymu`, FE9 files have either no footer or a single slot 0; most FE10 files have both slots, some have one, some none. **Strong evidence.**

### 6.1 FE9 Footer

`footer_offset` points directly at the Footer Pointer(s):

| Offset | Size | Content |
|:---:|:---:|---------|
| `+0x00` | 36 | **Footer Pointer(s)**: nine uint32 slot pointers, slot 0 first; 0 = empty slot |
| `+0x24` | 4 | pad word (0) |
| `+0x28` | var | the slot blocks, back to back in file order, running to the end of the file |

The first used block starts at `+0x28`. In `ymu` animations only slot 0 is used, so the 36 bytes after the pointer are zero ("Footer Pointer 1 followed by `0x24` zero bytes" in earlier notes). An all-zero pointer table is a valid empty Footer. In effect (`yme`) and scenery animations further slots are non-zero. **Confirmed.**

### 6.2 FE10 Footer

FE10 puts the Footer Pointer(s) at the **end of the file**, after the slot blocks. `footer_offset` points to the last `0x0C` bytes of the file, i.e. the last Slot Identifier. Two layouts exist:

| Case | Footer Pointer(s) size | Layout |
|------|:---:|--------|
| One slot present | `0x0C` | `Slot Identifier`, `Footer Slot Pointer`, 4 zero bytes |
| Both slots present | `0x18` | `Slot Identifier 0`, `Footer Slot 0`, 4 zero bytes, `Slot Identifier 1`, `Footer Slot 1`, `Slot Identifier Pointer` |

- A **Footer Slot Pointer** holds the file offset of its slot block. **Slot Identifier** words tag the slot that follows: `0x05` for slot 0 (event track), `0x00` for slot 1 (visibility). **Slot Identifier 0** and **Slot Identifier 1** are the identifiers of **Slot 0** and **Slot 1** in the two-slot layout.
- In the two-slot layout `footer_offset` points to **Slot Identifier 1**, and the **Slot Identifier Pointer** (the last word of the file) points to **Slot Identifier 0**, normally `0x18` bytes before the end of the file.
- **How to tell the cases apart:** if the `footer_offset` is non-zero and the last 4 bytes of the file are 0, only one slot is present. Its identifier value says which one (`0x05` = slot 0, `0x00` = slot 1). If the `footer_offset` and the last 4 bytes of the file are non-zero, both are present.
- **Block extents.** One slot: the block runs from its **Footer Slot Pointer** to the **Footer Pointer(s)**. Two slots: slot 0 runs from `Footer Slot 0` to `Footer Slot 1`, and slot 1 from `Footer Slot 1` to the start of the Footer Pointer(s) (Slot Identifier 0).

**Confirmed** on FE10 `ymu` animations (fighter3_n `atk_2.ga` for the two-slot case).

### 6.3 Footer Slot 0: Event Track

The event track lists frames at which the animation emits **event codes**. As the animation plays, the engine collects the codes of every frame it passes (at most four per update) and hands them to the battle or map code. **Confirmed.**

| Offset | Type | Field |
|:---:|------|-------|
| `+0x00` | uint16 | key_count |
| `+0x02` | uint16 | pad (0) |
| `+0x04` | uint32 | runtime pointer word (0 on disc; the loader stores `block + 8` here) |
| `+0x08` | uint16[key_count] | key offsets, from the start of the block |
| then | keys | `frame` uint16, `code_count` uint16, `codes` uint16 × code_count |

The block is padded to 4 bytes. FE9 files carry exactly this layout; FE10 event keys have been observed to end with two extra zero bytes (not yet reconciled).

**Event codes.**

| Code | Meaning | Level |
|:---:|---------|---|
| 0 | the blow lands (damage, HP gauge) | reported (engine + files) |
| 1 | the swing; moves the round on after a miss | reported (engine + files) |
| 2 | releases a thrown weapon | reported (engine + files) |
| 3 / 4 | loop start / loop end | reported |
| 0x14–0x1B | weapon trails (0x19 ends the trail) | reported, strong evidence |
| 0x1C / 0x1D | set / clear a battle flag | reported |
| 0x28 / 0x29 | spawn camera and light effects | reported |
| 50 | footsteps and dust | reported, strong evidence |
| 1000 and up | sound effects | reported, strong evidence |

Melee attacks and criticals carry codes 0 and 1, throws carry 2. An attack without them leaves the combat round waiting; with them, retargeted and re-timed attacks play through in game. Another source reads code 1 as the hit frame; the table follows the later and more detailed observations. At least one event handles the damage display, and its frame has to lie inside the playback range ([§2](#2-header)).

### 6.4 Footer Slot 1: Visibility (FE10)

Slot 1 makes bones, usually unequipped weapons, invisible (scale 0) for all or part of an animation. It is present in some FE10 animations. It uses the same container as the event track:

| Offset | Type | Field |
|:---:|------|-------|
| `+0x00` | uint16 | entry_count |
| `+0x02` | 6 bytes | pad / runtime pointer word (0) |
| `+0x08` | uint16[entry_count] | entry offsets, from the start of the block |
| then | entries | see below |

Each entry: `key_count` uint16, `bone_index` uint16, then `key_count` keys of `frame` uint16 and `visible` uint16 (`0` = invisible, `1` = visible), padded to a multiple of 4 bytes. **Strong evidence.**

### 6.5 Other Footer Slots

FE9 effect (`yme`) and scenery (`zbg`, `zmap`) animations have non-zero data in slots 2–8. These blocks are not decoded. They can be copied as raw bytes when a file is rebuilt, with their pointers rebased. **Hypothesis** for any further interpretation.

---

## 7. How an Animation Drives the Skeleton

### 7.1 Evaluation

For a requested frame, the engine does the following for every bone listed in the Bone Table:
1. Each curve of the bone is evaluated (linear interpolation, ends held) and the value is written into the matching **value block** slot of the bone, replacing the skeleton's value ([§5](#5-keyframe-data)).
2. The bone's local matrix is rebuilt from the value block, using the terms enabled by `channel_flags = channel_mask | bone.flags`: translate, rotation about the rotate pivot (joint orient, rotate, rotate axis), scale about the scale pivot. See the Skeleton note ([§6.1](../skeleton/tellius-skeleton-file-format.md)).
3. Bones not listed keep their **seed matrix**.
4. World matrices are chained from the root down (first child, then next sibling), and a vertex is drawn through `world[bone] × skin[bone]`.

Consequently an animation key is an absolute value in the skeleton's own terms: it only means the same thing on another skeleton if that skeleton's rest values, joint orients and bind pose agree ([§5](#5-keyframe-data), moving an animation).

### 7.2 Engine routines

Names from decompilation; addresses from the GameCube `main.dol`.

| Name | Role |
|------|------|
| `gactor_update_animation_timer` (`0x80060060`) | Advances playback; reads header words 3–6 (format flags, loop flag, start frame, end frame). |
| `fn_8006353C` / `interpolate_animation_frame_value` (`0x80063614`) | Evaluates one curve at a frame: linear interpolation between int16 keys, ends held. |
| `fn_80061930` | Main pose evaluation; forms `channel_flags = channel_mask \| bone.flags`. |
| `fn_80062848` / `build_bone_local_matrix` | Builds a bone's local matrix from the evaluated values. |
| `find_animation_frames_in_time_range` (`0x800651FC`) | Collects the event codes of the frames passed since the last update (up to four). |
| `fixup_animation_pointer_offsets` (`0x80063A14`) | Loader relocation: header words 0, 1, 8, 9, 10, 11 and the nine slot pointers of the FE9 Footer (for the first eight slots it also stores `block + 8` in the block's second word). |

### 7.3 Where animations are used

- **Map models** (`ymu`): one animation file per action and weapon (`wait`, `move`, `atk1`, ...); an action the unit record does not enable plays `tackle` instead. Map weapons are part of the body, one bone each; each animation shows the weapon in use by scaling its bone to 1 and the others to 0.
- **Battle models** (`zu`): each battle model's `.dbx` names the animation for every situation and weapon (idle, ready, two attacks, two crits, dodge, damage, death, run, sidestep, throw, crit throw, follow-ups). Situations may share a file: the Fighter's 29 files hold 14 distinct motions. An archer's bow bone is animated with scale 0 whenever the bow should not be seen.
- `_root_` follows the hips, so a step taken in one battle animation carries into the next.

---

## 8. Terminology Notes

Other documents, tools and earlier versions of these notes use different words for some of the same things. This reference uses the left-hand term. (The full catalogue is kept in `terminology.md`.)

| This reference | Also seen as |
|---|---|
| Header | File Info |
| start_frame | start frame; "frame a loop restarts at"; loop restart frame |
| format_flags (word 3) | byte `0x0F`; "format" |
| Bone Table, record `(bone_index, channel_mask, first_curve, curve_count)` | bone table; bone-group table; "Starting entry index in Channel Data" |
| Curve Table | Channel Data; curve data; `curve_info` |
| channel | transform channel type |
| fraction bits | B2; precision scale factor; scale shift; `curve_type` |
| Keyframe Data | F-curve data |
| Footer | Footer Data section |
| Footer Slot 0 / Footer Slot 1 | Footer Pointer 1 / Footer Pointer 2 |
| Slot 0: event track | Footer Data 1 |
| Slot 1: visibility | Footer Data 2 |
| Footer Pointer(s) | footer pointer block |
| Slot Identifier 0 / 1 | Footer Identifier 1 / 2 |
| Slot Identifier Pointer | Footer Pointer 3 |
| event code | footer entry data |

---

## 9. Remaining Unknowns

- **Rotate-pivot curves:** whether the engine applies them (all observed ones are single constants on bones with flag bit 7 set), and the exact effect.
- **Rotate-pivot flag gating:** whether bit 7 of the bone's flags is the only gate, and whether every bone with a pivot curve has it.
- **FE10 interpolation:** linear interpolation is confirmed for FE9 only.
- **FE10 event-track entries:** the two extra trailing bytes, and the meaning of the remaining event data beyond the codes listed.
- **FE10 slot 1 vs FE9 slots:** whether visibility corresponds to one of FE9's undecoded slots 1–8.
- **Footer slots 2–8** on effect and scenery animations (undecoded).
- **start_frame** values in FE10 `motion*2_#.ga`, and the full set of animations that loop.
- **Event codes** in the 0x14–0x1B range and the exact roles of codes above 1000.
- **Joint-orient channels (9–11):** never seen; whether any engine path would honour them is unknown.
- **FE10 testing:** rotation, translate and scale behavior comes mainly from FE9.
