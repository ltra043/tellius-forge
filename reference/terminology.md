# Tellius Terminology Catalogue

**Created:** 2026-10-04 (session Z2-L). 

**Last updated:** 2026-10-18 (Z14: checked against the rename sheets and plan revision 11; earlier: 2026-10-13 fraction bits, 2026-10-10 "inverse bind" without a hyphen)

**Authority (Z14):** for **code names** (functions, parameters, dict keys, stored properties) the rename sheets in `plugin/dev/refactor/` and `rename_map.csv` win over this catalogue. For **wording in the format notes**, this catalogue wins. Where the two differ on purpose, sections 4 and 5 say so.


**Purpose:** Establish standard language to use across research, docs, and code. Create reference that records which term each format note should use, which older or alternative terms it replaces, and which discrepancies are still open. Use it to update the other format notes, the plugin and (optionally) the logs.


**Rule:** where two terms exist, the more descriptive one is chosen, preferring words that are standard in 3D modeling and graphics, with exceptions the User decided. 

**Status values:** 
- *Agreed* = User decision/approved
- *Z2* = chosen in session Z2_L; apply elsewhere unless the User objects
- *Proposed* = not applied yet, needs a decision
- *Open* = no consensus
- *Previous* = terms in the User's earlier notes/plugin
- *Alt.* = independent FE9 research's term

---

## 1. Skeleton (`.g`)

| Concept | Previous | Alt. | **Chosen** | Status | Notes |
|---|---|---|---|---|---|
| Matrix at `+0x10` | bind matrix (4×4, "inverse-bind") | skin_matrix (3×4) | **inverse bind matrix** (3×4) | Z2 | Corrects the layout too: 12 floats, not 16. Spelled without a hyphen (User decision, Z6); the hyphenated form stays in the Previous column as history. |
| Pose the mesh was attached in | bind pose | skin pose | **bind pose** | Agreed | |
| Pose built from the stored values | seed pose / pose position | seed matrices chain | **seed pose** | Agreed (B3) | Term from log_B3. |
| Block `+0x40`–`+0xEB` | unknown/reserved floats | value block (43 floats) | **value block** | Z2 | Slots numbered 0–42 = animation channel numbers. |
| `+0x40` | "reserved" | scale | **scale** | Z2 | Old notes had no scale slot. |
| `+0x4C` | "unknown +76" | rotate | **rotate** | Z2 | |
| `+0x58` | local_translation / p88 | translate | **translate** | Z2 | |
| `+0x64` | local_rotation_deg / transrot | joint orient | **joint orient** | Z2 | |
| `+0x70` | position / p112 / bone head / world position (Class A) | rotate pivot | **rotate pivot** | Z2 | |
| `+0x7C` | position_dup | scale pivot | **scale pivot** | Z2 | |
| `+0x88` / `+0x94` | reserved | pivot offsets 1 and 2 | **pivot offset 1 / 2** | Z2 | Maya "pivot translations" is a hypothesis. |
| `+0xA0` | reserved | rotate axis | **rotate axis** | Z2 | |
| `+0xAC` | reserved | quaternion | **quaternion** | Z2 | Unused in shipped clips. |
| `+0xBC` | pre-computed 3×4 local transform | seed local matrix | **seed matrix** | Z2 | |
| `+0xEC` | bone_index | bone's index | **bone_index** | Z2 | |
| `+0xEE` | rotation_order | Euler rotation order | **rotation_order** | Z2 | |
| `+0xF0` | name_offset | name pointer | **name_offset** | Z2 | |
| `flags` | IS-proprietary bitfield (opcode, store, load) | which transform terms apply | **term flags** | Z2 | Opcode/store/load wording withdrawn. |
| bit 3 / 4 / 5 | (swapped in older text) | scale / rotate / translate | **scale / rotate / translate** | Z2 | Same bits as `.ga` `channel_mask`. |
| Bone categories | Class A (world position) / Class B (local transform) | — | **pivot bone (Class A) / offset bone (Class B)** | Proposed | Applied in the skeleton note (§5). Keep letters as shorthand. Plugin: `pos_source` -> `bone_class`, values 'A' / 'B' kept (plan 12.g, D19); stored name `tf_bone_class`. |
| `_s1_`-style bones | orientation bones, non-animated bones | anchor bones | **anchor bone** | Z2 | Engine finds them by token. |
| Header `+12` | first_bone_offset | bone-array offset | **bone_array_offset** | Z2 | |
| Pool entry 0 | `[unknown]` | root name | **root name** | Z2 | Always `[unknown]` in observed files. |
| Runtime matrix stack | aux_obj / matrix stack | — | **aux_obj** (world matrix array, 0x30 per bone) | Z2 | |
| Runtime value copy | eval_result / eval buffer | — | **evaluation buffer** | Z2 | Copy of the value block. Spelled out, as in the skeleton note (this row said "eval buffer" before Z14). |
| Combined flags | channel_flags | — | **channel_flags** | Z2 | `animation channel_mask \| bone.flags`. |
| Accumulated bone transform | world matrix (undefined) | world matrix | **world matrix** | Z2 | Defined in the skeleton note §6.2: bone frame → model space, i.e. the product of the local matrices from root to bone. "World" = model space, not the game world. |
| Space the whole character is stored in | model space / local space | — | **model space** | Z2 | |
| A bone's own coordinate system | local space | frame | **frame** | Z2 | The frame of a bone is defined by its world matrix. |
| Seed / bind world matrices | — | — | **seed world / bind world** | Z2 | Chain of seed matrices / inverse of the inverse bind matrix. |

## 2. Animation (`.ga`) — applied in `tellius-animation-file-format-Z2.md`

| Concept | Previous | Alt. | **Chosen** | Status | Notes |
|---|---|---|---|---|---|
| Sections | File Info / Bone Table / Channel Data / F-Curve Data / Footer Data | header / bone group table / curve table / keyframe data / footer | **Header / Bone Table / Curve Table / Keyframe Data / Footer** | Agreed | `curve_info` (earlier choice) replaced by **Curve Table**. |
| Bone Table record | 4 columns | (bone_index, channel_mask, first_curve, curve_count) | **`(bone_index, channel_mask, first_curve, curve_count)`** | Agreed | |
| Curve's target number | transform channel type | channel | **channel** | Z2 | = value-block slot. |
| Precision byte | B2 / precision scale factor / scale shift | scale_shift, key_shift, value_shift | **fraction bits** | Z8 | Number of fraction bits of the 16-bit key value: value = raw · 2^−n. "Scale" was dropped because it also names the scale transform. Plugin: `curve_type`/B2 -> `fraction_bits`. |
| Header word 3 | byte 0x0F | format flags | **format_flags** | Z2 | `0x11` in every file. |
| Header word 5 | start frame | frame a loop restarts at | **start_frame** (start and loop-restart frame) | Z2 | Replaces the earlier "loop restart frame" proposal: own tests show it also sets where playback starts. |
| Header word 6 | end frame | end frame | **end_frame** | Z2 | |
| Footer sections | Footer Data 1 / 2 | footer slot 0 (event track) | **Footer Slot 0 (event track) / Footer Slot 1 (visibility, FE10)** | Agreed | Slots are numbered by kind; FE9 has a fixed 9-entry table, FE10 lists only present slots. |
| Footer pointer entries | Footer Pointer 1 / 2 | slot pointers | **Footer Slot 0 / Footer Slot 1** (pointers) | Agreed | |
| Pointer block | Footer Pointer(s) | — | **Footer Pointer(s)** | Agreed | |
| FE10 identifier words | Footer Identifier 1 / 2 | — | **Slot Identifier 0 / 1** | Agreed | "Identifier" spelled out (ID could read as identity). Values: 0x05 = slot 0, 0x00 = slot 1. |
| FE10 third pointer | Footer Pointer 3 | — | **Slot Identifier Pointer** | Agreed | Points to Slot Identifier 0 in the two-slot layout. |
| Event codes | — | event track codes | **event codes** | Z2 | |

## 3. Body (`.gs`) — applied in `tellius-body-file-format-Z2.md`

All choices below were accepted by the User on 2026-10-08. Reasoning in brief: prefer words that are standard in 3D graphics and describe what the thing is.

| Concept | Previous | Alt. | **Chosen** | Status | Notes |
|---|---|---|---|---|---|
| Draw call record (32 bytes) | chunk / Chunk Descriptor | shape | **submesh** / **Submesh Record** | Agreed | "Shape" clashes with Maya shape nodes and blend shapes; "chunk" has no 3D meaning. |
| Per-mesh record (PtrA, 36 bytes) | PtrA block | mesh | **mesh record** | Agreed | A mesh (name, bone, bounding box) owns one or more submeshes; hence header `0x76` ≤ `0x78`. |
| Header `0x76` / `0x78` | chunk count / chunk count (duplicate) | mesh count / submesh count | **Mesh Record count / Submesh count** | Agreed | They can differ (`timt` 35 vs 41). |
| Format word `+0x08` | primitive type (`0x30`/`0x38`) | shape flags | **submesh flags** | Agreed | Blended, skinning byte, material state, hidden, culling, render pass. |
| Submesh `+0x0C` | (pad) | bone | **bone index** (of the submesh) | Agreed | A label only for blended submeshes. |
| Mesh record `+0x1C` | display-list slot index | bone index | **bone index** | Agreed | uint16; not unique. |
| Attribute flags `+0x12` | GX vertex attribute flags; `hc` / `hu` | — | **attribute flags: color index present / second UV present** | Agreed | Abbreviations dropped. |
| Bit 0 of submesh flags | use IVB / `cb` | composite bit | **blended** | Agreed | |
| Bit 1 of submesh flags | `sb` (skinning byte present) | — | **skinning byte present** | Agreed | |
| Bits 2–3 of submesh flags | material batch mode (leader / inherit) | — | **material state: material leader / inherits** | Agreed | |
| Bit 10 | — | hidden | **hidden** | Agreed | |
| Bits 11–12 | — | culling | **culling** (back / front / double-sided) | Agreed | |
| Bits 13–14 | — | render pass | **render pass + 1** | Agreed | |
| Header `0x5C` / `0x60` / `0x64` | alternate chunk-list locations | render-pass lists | **render pass lists** (1 opaque, 2 alpha-tested, 3 blended) | Agreed | Confirmed on FE10 data and by the engine's per-pass settings. |
| `0x98` command stream | GX display list | display list | **display list** | Agreed | |
| Vertex's `sb` byte | sb byte (slot·3) | matrix index | **skinning byte**; **palette slot** = skinning byte / 3 | Agreed | |
| Bone palette | GX cache, palette | bone subset | **bone palette** | Agreed | Matrix-palette skinning is the standard term. |
| Header `0x68` buffer | IVB, composite buffer, CB | blended-vertex buffer | **Blended Vertex Buffer** | Agreed | |
| Records in that buffer | skinning records, gap records, gap_mapping | weight records | **weight records** | Agreed | uint8 weights out of 256. |
| Entries of that buffer | composite slots | vertex slots | **vertex slots** | Agreed | 12 bytes each. |
| Buffer `+0x0C` | scale / scale shift | shift | **fraction bits** | Z8 | Same term as header `0x7C`–`0x7E` and `.ga` (positions and normals are int16 · 2^−n). |
| Header `0x7C`–`0x7E` | scale exponent / scale shift | shift | **fraction bits** | Z8 | One byte each for positions, normals, and UVs. |
| Header `0x2C` | AABB | bounding box | **bounding box** (AABB in parentheses on first use) | Agreed | |
| Header `0x50` table | lighting multiplier table | vertex colors | **Vertex Color Table** | Agreed | Its use as a lighting multiplier is stated in the text. |
| Materials List | Materials List | — | **Material Table** | Agreed | Matches Bone Table / Curve Table. |
| TPL info block (28 bytes) | TPL info block | — | **Texture Reference** | Agreed | A material's reference to one image of the `.tpl`, plus UV scale. |
| Texture Reference `+0x04` | TPL texture slot index | — | **image index** | Agreed | |
| Texture Reference `+0x06` / `+0x07` | Sampling flag A / B (body note); `samp0` / `samp1` (code) | — | **sampling flag 0 / sampling flag 1** | Agreed (Z14, D103) | Named by position because the meaning is unknown; "sampling" is itself a guess. Code: `sampling_flag_0` / `sampling_flag_1`. Applied in the body note (Z14). |
| Reloc Table | Reloc Table | — | **Relocation Table** | Agreed | |
| Strips with different skinning bytes for one table vertex | seam / duplicate vertices | — | **skinning per display-list occurrence; instancing; seam vertices** | Agreed | |

## 4. Poses and plugin concepts (not for the format notes)

| Concept | Term | Notes |
|---|---|---|
| Armature rest = bind pose, pose channels = seed pose | `BIND` rest mode (hidden import option since v0.31.3) | Plugin only. |
| Plugin bone categories | `bone_class` 'A' / 'B' (was `pos_source`; stored `tf_bone_class`) | Plugin only; follows flags and data (D19, plan 12.g). |
| Plugin addon-mesh types | `BLENDED` / `SINGLE` (values unchanged); operator property `addon_submesh_type` (was `addon_chunk_type`) | Plugin only (D102, User approved the name, Z14). The property's label text still says chunks and composite; it changes in the wording sweep. |
| Matrix that carries a stored vertex from the bind pose to the seed pose | `bind_to_seed_matrix` = seed world (every scale taken as 1) x inverse bind matrix | Plugin only (D22). The identity when the bone's bind pose equals its seed pose. |
| Seed world with every scale taken as 1 | `compute_unit_scale_seed_worlds` | Plugin only (D14). "Bind world" stays reserved for the inverse of the inverse bind matrix. |
| Final per-vertex matrix | `skinning_matrix` = world matrix x inverse bind matrix | Plugin (plan 6.4). This is why `+0x10` is not called "skin matrix": other engines use that name for this product. A format note may name it once. |
| Body structures in code | `submesh`, `mesh_record`, `bone_palette`, `blended`, `display_list`, `weight_record`, `skinning_byte`, `palette_slot`, `fraction_bits` | Code names equal the Chosen terms (plan 6.4, `body.md`). Differences: the Texture Reference is `tpl_block` in code (`tpl_blocks`, `tpl_block_table_offset`), with fields `tpl_index`, `sampling_flag_0` / `sampling_flag_1`, `uv_scale_x` / `uv_scale_y` (D30); a vertex slot is a `blended_slot` (`blended_slot_count`). |
| Bone dict keys of `read_g` | `bone_index`, `parent_index`, `head_position`, `rotate_pivot`, `joint_orient_deg`, `seed_matrix`, `inverse_bind_matrix`, `world_matrix`, `frame_rotation`, ... | D16 (`skeleton.md`). `head_position` is Blender's bone head in the chosen rest mode; it is not the format note's rotate pivot. |
| Flag and channel constants | `TERM_FLAG_SCALE` (0x008), `TERM_FLAGS_PIVOT` (0x180), `TERM_FLAG_BIT_0X02` (purpose unconfirmed), `GA_MASK_SCALE` / `_ROTATE` / `_TRANSLATE` (0x08 / 0x10 / 0x20) | D13, D35, D37. |
| Stored (custom) property names | `tf_` + a spelled-out name | D28, `stored_strings.md` (phase 0c). |

## 5. Open discrepancies

| Item | Detail | Status |
|---|---|---|
| Local-matrix routine address | decompilation name `fn_80062848` vs `build_bone_local_matrix` at `0x80062920` | Open: maybe the same function at different entry points. |
| Hierarchy-propagation address | `fn_80065A20` vs `gactor_build_bone_hierarchy_matrices_recursive` at `0x80065AF8` | Open. |
| Event code 0 / 1 meaning | one source: code 1 = hit frame; newer: code 0 = blow lands, code 1 = the swing | Animation note follows the newer reading; keep open until the older source is re-checked. |
| Looping animations | one source: only idle `ready` loops | Own testing: `ready`, `move`, `wait`, FE10 `twait` and probably others loop (animation note). |
| Keyframe evaluator address | `fn_8006353C` vs `interpolate_animation_frame_value` at `0x80063614` | Open (maybe the same routine at different entry points). |
| Joint-orient bit | bit 6 holds in all tested skeletons except a report of non-zero joint orient on some `0x26` bones of `lord2` | Open (not re-examined). |
| Class A/B naming | descriptive names (pivot bone / offset bone) are used in the skeleton note; letters kept; plugin key is `bone_class` (D19) | Proposed: move to Agreed when the User confirms. |
| Pivot offsets as "pivot translations" | Maya analogy | Hypothesis. |
| Material color multiplier | one source reports that material colors are multiplied by 1.25 (capped at 255) when a body loads | Not verified; body note marks it **Reported** (see §7). |
| Mesh record `+0x1C`, low byte (`+0x1D`) | The plugin calls it `slot_index` (D53, D71, D86); the code comment in `read_gs_file` (v0.34.1) says it is the low byte of the uint16 bone index. This catalogue and the body note (§6) call the field **bone index**. Data check (Z14): in `timt` (35 records) and `fighter2_n` (15), every record has a different value, and in `fighter2_n` the values are not in record order (40, 5, 7, 11, ...), which fits a bone index. The exporter, however, writes a running counter (`next_slot_index`, from the highest original value + 1) into `+0x1D` of every new mesh record and calls it a "display-list slot index". | Notes and docs: keep **bone index** (User, Z14). Code name: open, because the reader's `slot_index` (a bone label) and the exporter's `next_slot_index` (a counter) are used with two different meanings; whether a new record should hold a counter or a bone also needs a check. |
| Skeleton flag bit 1 (`0x02`) | Skeleton note: possibly "bone carries skinned geometry" (**Hypothesis**). `TERM_FLAG_BIT_0X02` comment (D37): in sysdolphin `JOBJ_FLAGS` this bit is the skeleton root. | Open: purpose not confirmed. |
| Wording inside the plugin | Print and error text still says chunk, composite, PtrA (`body.md` 4C, D54); a code comment in `make_default_tpl_block` still says "sampling flag A". | Direction decided (User, Z14): submesh. The three format notes are clean (Z14); the plugin text is a wording sweep after the splits. |

## 6. How to apply

1. Skeleton note: done in `research/skeleton/tellius-skeleton-file-format.md` (§10 lists the replaced terms; the file was `-Z2` in earlier sessions).
2. Animation note: done in `research/animation/tellius-animation-file-format.md` (§8 lists the replaced terms).
3. Body note: done in `research/body/tellius-body-file-format.md` (§15 lists the replaced terms). Apply the same table to the pack/TPL notes if any are written.
4. Plugin: the rename sheets and `rename_map.csv` decide the code names (they follow this catalogue; §4 and §5 list the differences). Stored names `fe_*` become `tf_*` in phase 0c; user-visible print and error text comes last. Avoid new underscore-prefixed names.
5. Logs: leave unchanged; they record history.

## 7. Evidence labels and crediting outside sources

The format notes use **Confirmed / Strong evidence / Hypothesis**. A fourth label is proposed for statements that come from outside research and that the User cannot check:

| Label | Meaning | Status |
|---|---|---|
| **Reported** | Stated by an outside source (credited once in the note's Research Status), not independently verified. Weaker than Strong evidence, not yet a hypothesis of our own. | Applied in the legend of all three notes (Reader Information); the dagger (†) form is not used. |

Crediting rule: paraphrase, never quote; mark the statement with the label (or a dagger †) and name the source once in Research Status ("† Reported by the TelliusModding project; not independently verified."). Move a statement up to Strong evidence or Confirmed once a file pattern or an in-game test supports it.
