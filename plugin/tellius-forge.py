bl_info = {
    "name": "Tellius Forge",
    "description": "Fire Emblem 9 & 10 Asset Handler",
    "author": "Jade (ltra043), based on work by Zheneq and ATMachine",
    "version": (0, 27, 1),
    "blender": (4, 2, 0),
    "location": "File > Import, File > Export",
    "category": "Import-Export",
}

# -----------------------------------------------------------------------------
# Credits / Acknowledgements
# -----------------------------------------------------------------------------
# Based originally on:
# - FE9/FE10 Noesis plugin by Zheneq
# - Blender conversion by ATMachine
#
# Expanded with additional format research, export and animation
# support, and Blender integration by Jade.
# -----------------------------------------------------------------------------

import bpy
import struct
import os
import math
from collections import defaultdict, Counter
from bpy.props import StringProperty, BoolProperty, IntProperty, EnumProperty
from bpy_extras.io_utils import ImportHelper, ExportHelper
from mathutils import Vector, Euler, Matrix

plugin_version: str = f'v{bl_info["version"][0]}.{bl_info["version"][1]}.{bl_info["version"][2]}'

# Mapping from ga channel_type int → pose bone custom property name for B2
CH_TO_B2_PROP = {
    0: 'ga_b2_ScX', 1: 'ga_b2_ScY', 2: 'ga_b2_ScZ',
    3: 'ga_b2_RtX', 4: 'ga_b2_RtY', 5: 'ga_b2_RtZ',
    6: 'ga_b2_TrX', 7: 'ga_b2_TrY', 8: 'ga_b2_TrZ',
}

# Which channel_type indices each Blender constraint type covers
CONSTRAINT_CHANNELS = {
    'COPY_TRANSFORMS': list(range(9)),
    'COPY_ROTATION':   [3, 4, 5],
    'COPY_LOCATION':   [6, 7, 8],
    'COPY_SCALE':      [0, 1, 2],
}

# Default Mix Shader factor for newly created materials
DEFAULT_MIX_SHADER_FACTOR = 0.5


# =============================================================================
# BLENDER VERSION COMPATIBILITY — FCurves API
# =============================================================================
#
# In Blender 5.0 the legacy  action.fcurves  collection was removed.
# FCurves now live on a "channelbag" object fetched through the slotted-action
# API (bpy_extras.anim_utils).  In Blender 4.x and earlier, action.fcurves
# existed directly on the action.
#
# _get_fcurves(action, arm_obj, ensure=False)
#   ensure=True  → create slot + channelbag if missing  (use during import)
#   ensure=False → return None if nothing exists         (use during export)

def _get_fcurves(action, arm_obj, ensure=False):
    """Return the FCurves collection for *action*, compatible with Blender 4.x and 5.0+."""
    if bpy.app.version >= (5, 0, 0):
        from bpy_extras import anim_utils

        anim_data = arm_obj.animation_data
        slot = anim_data.action_slot if anim_data else None

        if slot is None:
            if ensure:
                slot = action.slots.new(id_type=arm_obj.id_type, name=arm_obj.name)
                if anim_data:
                    anim_data.action_slot = slot
            else:
                if action.slots:
                    slot = action.slots[0]
                    if anim_data:
                        anim_data.action_slot = slot
                else:
                    return None

        if ensure:
            channelbag = anim_utils.action_ensure_channelbag_for_slot(action, slot)
        else:
            channelbag = anim_utils.action_get_channelbag_for_slot(action, slot)
        return channelbag.fcurves if channelbag is not None else None

    else:
        return action.fcurves


# =============================================================================
# UTILITY — C-STRING READER
# =============================================================================

def _read_cstring(data, offset, max_len=256):
    """Read a null-terminated ASCII string from *data* at *offset*.

    Returns an empty string if the offset is out of range or the first byte
    is not printable ASCII.
    """
    if offset < 0 or offset >= len(data):
        return ''
    out = []
    for i in range(max_len):
        b = data[offset + i]
        if b == 0:
            break
        if b < 32 or b > 126:
            # Non-printable — likely not a string pointer
            return ''
        out.append(chr(b))
    return ''.join(out)


# =============================================================================
# UTILITY — RELOCATION TABLE BUILDER
# =============================================================================
#
# The .gs reloc table is a sorted list of big-endian uint32 values.
# Each entry is a RAW pointer value (file_offset_of_field - 0x20).
# The game loader adds 0x20 to every field whose file offset is in the table.
#
# Rules:
#   - Null pointer fields (raw stored value == 0) are NOT registered.
#   - The file-size field (header[0x00]) and the reloc-table-offset field
#     (header[0x04]) are NOT registered — they are not pointer fields.
#   - All other pointer fields in the file MUST be registered.
#   - Entries are sorted ascending.
#
# Usage:
#   pointer_fields = [
#       (file_offset_of_field, raw_stored_value),  # raw = value before +0x20
#       ...
#   ]
#   reloc_bytes = _build_reloc_table(pointer_fields)

def _build_reloc_table(pointer_fields):
    """Build a .gs relocation table bytearray from a list of pointer field descriptors.

    Args:
        pointer_fields: iterable of (file_offset, raw_value) tuples.
            file_offset  — the byte position in the file where the pointer lives.
            raw_value    — the raw (pre-+0x20) value stored at that position.
                           Pass 0 to skip (null pointers are not registered).

    Returns:
        bytearray of big-endian uint32 entries, sorted ascending.
    """
    OFFSET = 0x20
    entries = sorted(
        (file_offset - OFFSET)
        for file_offset, raw_value in pointer_fields
        if raw_value != 0
    )
    out = bytearray()
    for e in entries:
        out += struct.pack('>I', e)
    return out


# =============================================================================
# .g SKELETON FORMAT — VERIFIED CONSTANTS
# =============================================================================
#
# FILE HEADER (16 bytes):
#   0x00  uint32  0 (unused)
#   0x04  uint32  Absolute byte offset of string pool from file start
#   0x08  uint32  Total bone count
#   0x0C  uint32  0x10 (constant = first bone offset)
#
# BONE RECORDS:  start at 0x10,  stride = 0xF4 (244 bytes),  count = bone_count.
#
# PER-BONE RECORD (244 bytes, all big-endian):
#   +0    int32   parent_index    (-1 = root)
#   +4    int32   next_sibling    (-1 = last child)
#   +8    int32   first_child     (-1 = leaf)
#   +12   uint32  flags           (0x00000180 = Class A; 0x26 or 0x66 = Class B)
#   +16   f32×16  4×4 bind-pose matrix
#               Class A: identity-like (all zeros in translation column)
#               Class B: inverse bind matrix, column 3 = negated world position
#   +80   f32×8   zeros  (Class A)  OR  +80 zeros, +88 local offset XYZ  (Class B)
#   +88   f32×3   local offset (X, Y, Z) — Class B ONLY; zeros for Class A
#   +112  f32×3   bone head position (X, Y, Z) in world space  [Class A ONLY]
#   +124  f32×3   duplicate of head position  [Class A ONLY]
#   +136  f32×13  zeros
#   +188  f32     1.0
#   +192  f32×4   zeros
#   +208  f32     1.0
#   +212  f32×4   zeros
#   +228  f32     1.0
#   +232  uint32  0
#   +236  uint16  bone_index (own index, recomputed on export)
#   +238  uint16  0x0001     (constant)
#   +240  uint32  byte offset of bone name within string pool  [LAST 4 BYTES]
#
# TWO-CLASS BONE SYSTEM (v10):
#
#   Class A — flags 0x00000180 (or 0x0000018C for root locator):
#     World position is stored directly at +112/+124 (absolute world space).
#     +88 block is all zeros.
#     Bind matrix at +16 is identity-like.
#
#   Class B — flags 0x00000026 or 0x00000066:
#     Position at +112/+124 is all zeros.
#     Local offset from nearest Class B ancestor stored at +88/+92/+96.
#     Bind matrix at +16 stores inverse bind (column 3 = negated world pos).
#     ACCUMULATION RULE: walk up parent chain, skipping any Class A ancestors,
#     until a Class B ancestor is found. Add that ancestor's world position
#     to this bone's local offset to get world position.
#     If no Class B ancestor exists, the local offset IS the world position.
#
# Detection:
#   is_B = (flags & 0x180) == 0
#   OR by data pattern: +112 block is all zeros AND +88 block is non-zero.

FIRST_BONE_OFFSET = 0x10
BONE_STRIDE       = 0xF4   # 244 bytes

# Default identity-like matrix written for Class A bones (and new bones with no stored matrix).
# 16 big-endian floats. The last three diagonal entries are 1.0; all else are 0.0.
_BONE_MATRIX_FLOATS = [1.0, 0.0, 0.0, 0.0,
                       0.0, 1.0, 0.0, 0.0,
                       0.0, 0.0, 1.0, 0.0,
                       1.0, 1.0, 1.0, 0.0]


# =============================================================================
# BONE TYPE CONSTANTS
# =============================================================================
#
# fe_bone_flags values observed in FE9 & FE10 skeletons.
# The flag field is a 32-bit IS-proprietary bitfield:
#   Bits 4-0:  Operation code (0x06=matrix multiply, 0x07=FE10 unified, etc.)
#   Bit  5:    Store matrix to stack (present on all animated Class B bones)
#   Bit  6:    Load matrix from stack (0x66/0x67 only — changes reference frame)
#   Bits 7-8:  Class A indicator (0x180); both clear → Class B
#   Bits 9+:   Extended flags (Wii-specific in FE10)
#
# Short summary of common values:
#   0x0180 — Class A static bone (most bones in both games)
#   0x0026 — FE9 animated bone, standard chain (store only)
#   0x0066 — FE9 animated bone, chain with load (cloth/cape branches)
#   0x0027 — FE10 animated bone (unified, replaces both 0x26 and 0x66)
#   0x0024 — FE9 solver/IK bone (position-only, no rotation animation)
#   0x002F — Rare overworld bone (seen only in d_knight1_j)
#   0x0000 — Root / identity bone
#   0x018C — Attachment point (weapon grip)
#   0x01A4 — Attachment point variant
#
# Stored as 'fe_bone_flags' integer custom property on every Blender bone.

_FE_BONE_TYPE_ITEMS = [
    (0x0180,  "Static Bone",       "Standard static skeleton bone (flags = 0x0180)"),
    (0x018C,  "Attachment Point",  "Weapon grip or hand attachment (flags = 0x018C)"),
    (0x01A4,  "Attachment Alt",    "Alternate weapon attachment (flags = 0x01A4)"),
    (0x0024,  "IK/Solver",         "IK solver, position-only (flags = 0x0024)"),
    (0x0000,  "Root / Identity",   "Root bone, identity matrix (flags = 0x0000)"),
]

_FE_BONE_TYPE_ITEMS_BATTLE = [
    (0x0180,  "Static Detail",     "Static mesh-proxy bone (flags = 0x0180)"),
    (0x0026,  "Animated (FE9)",    "FE9 standard animated bone (flags = 0x0026)"),
    (0x0066,  "Chain End (FE9)",   "FE9 cloth/cape chain (flags = 0x0066)"),
    (0x0027,  "Animated (FE10)",   "FE10 standard animated bone (flags = 0x0027)"),
    (0x0067,  "Chain End (FE10)",  "FE10 cloth/cape variant (flags = 0x0067)"),
]


# =============================================================================
# .ga ANIMATION FORMAT — VERIFIED CONSTANTS
# =============================================================================

_GA_CHANNEL = {
    0x00: ('scale',          0, 'Scale.X'),
    0x01: ('scale',          1, 'Scale.Y'),
    0x02: ('scale',          2, 'Scale.Z'),
    0x03: ('rotation_euler', 0, 'Rot.X'),
    0x04: ('rotation_euler', 1, 'Rot.Y'),
    0x05: ('rotation_euler', 2, 'Rot.Z'),
    0x06: ('location',       0, 'Loc.X'),
    0x07: ('location',       1, 'Loc.Y'),
    0x08: ('location',       2, 'Loc.Z'),
}


# =============================================================================
# DECODE / ENCODE  (v8 — rotation uses s16/32768.0, no pi)
# =============================================================================

def _ga_decode(b1, s16_val, b2=15):
    """Convert a raw signed int16 frame-data value to a Blender float.

    B2 is the GQR scale exponent: float = s16 / (1 << B2).
    Rotation channels (B1 3-5) store degrees in the file; converted to radians for Blender.
    Translation channels (B1 6-8) are negated per game convention.
    Scale channels (B1 0-2) are direct.
    """
    scale = float(1 << b2)
    if 0x03 <= b1 <= 0x05:
        return (s16_val / scale) * (math.pi / 180.0)
    elif 0x06 <= b1 <= 0x08:
        return s16_val / scale
    else:
        return s16_val / scale


def _ga_encode(b1, blender_val, b2=15):
    """Convert a Blender float back to a raw signed int16.

    Inverse of _ga_decode. Rotation channels convert radians → degrees before encoding.
    Translation channels are negated. Scale channels are direct.
    """
    scale = float(1 << b2)
    if 0x03 <= b1 <= 0x05:      # Rotation
        # Convert Blender Radians to File Degrees, then apply B2 scale
        raw = int(round((blender_val * (180.0 / math.pi)) * scale))
    elif 0x06 <= b1 <= 0x08:        # Translation
        raw = int(round(blender_val * scale))
    else:       # Scale
        raw = int(round(blender_val * scale))
    return max(-32768, min(32767, raw))


# =============================================================================
# UTILITY — B2 EXPONENT CALCULATION
# =============================================================================

def _compute_b2(float_values):
    """Compute the optimal GQR scale exponent B2 for a sequence of float values.

    The GQR S16 decode formula used by the GameCube is:
        float = s16_signed / (1 << B2)

    The optimal B2 maximises precision (largest exponent) without int16 overflow:
        B2 = floor(log2(32767 / max_abs_value))

    This is purely value-range-driven — it does not depend on channel type.
    A scale channel at 1.0 and a rotation channel at 1.0 rad both get B2=14.
    A small rotation of 0.5 rad gets B2=15.  A translation of 8 units gets B2=11.

    The result is clamped to [0, 15].  B2=15 is the finest precision (s16 max
    → ~1.0).  Values above 15 are theoretically valid per the 6-bit GQR field
    but would only arise for sub-unit-scale animations; the clamp can be raised
    if such a case is encountered.

    Returns 15 (finest precision) when all values are zero or the list is empty.
    """
    if not float_values:
        return 15
    max_abs = max(abs(v) for v in float_values)
    if max_abs < 1e-9:
        return 15
    b2 = int(math.floor(math.log2(32767.0 / max_abs)))
    return max(0, min(15, b2))


# =============================================================================
# UTILITY — EULER ANGLE UNWRAPPING
# =============================================================================

def _unwrap_euler(values_rad):
    """Return a new list with 2π discontinuities removed."""
    if len(values_rad) <= 1:
        return list(values_rad)
    TWO_PI = 2.0 * math.pi
    out    = [values_rad[0]]
    for i in range(1, len(values_rad)):
        diff = values_rad[i] - out[i - 1]
        diff -= TWO_PI * math.floor((diff + math.pi) / TWO_PI)
        out.append(out[i - 1] + diff)
    return out


# =============================================================================
# UTILITY — SKELETON FILE LOCATOR
# =============================================================================

def find_skeleton_file(start_path):
    """Search for skeleton.g near *start_path*."""
    base_dir   = os.path.dirname(os.path.abspath(start_path))
    candidate  = os.path.join(base_dir, 'skeleton.g')
    if os.path.isfile(candidate):
        return candidate
    pack_dir   = os.path.join(base_dir, 'pack')
    candidate2 = os.path.join(pack_dir, 'skeleton.g')
    if os.path.isfile(candidate2):
        return candidate2
    # Added check for when body/skeleton have non-standard name
    # Example: maps are named bmap01.gs, bmap02.g, etc 
    body_stem = start_path.stem
    candidate3  = os.path.join(base_dir, f'{body_stem}.g')
    if os.path.isfile(candidate3):
        return candidate3
    return None


# =============================================================================
# UTILITY — CLASS B BONE DETECTION
# =============================================================================

def _is_class_b_by_flags(flags):
    return (flags & 0x180) == 0


def _is_class_b_by_data(px112, py112, pz112, px88, py88, pz88):
    zero112 = abs(px112) + abs(py112) + abs(pz112) < 1e-6
    nonz88  = abs(px88)  + abs(py88)  + abs(pz88)  > 1e-6
    return zero112 and nonz88


# =============================================================================
# SKELETON (.g) — READING
# =============================================================================

def read_skeleton_file(filepath):
    """Parse a .g skeleton file."""
    with open(filepath, 'rb') as f:
        raw = f.read()

    def ru4(o): return struct.unpack('>I', raw[o:o+4])[0]
    def ri4(o): return struct.unpack('>i', raw[o:o+4])[0]
    def rf4(o): return struct.unpack('>f', raw[o:o+4])[0]

    string_pool_offset = ru4(0x04)
    bone_count         = ru4(0x08)

    print(f"\n=== READING SKELETON: {os.path.basename(filepath)} ===")
    print(f"  {bone_count} bones,  string pool @ 0x{string_pool_offset:X},  "
          f"file size {len(raw)} bytes")

    string_map = {}
    pos = string_pool_offset
    while pos < len(raw):
        try:
            end = raw.index(0, pos)
        except ValueError:
            break
        name = raw[pos:end].decode('ascii', errors='replace')
        string_map[pos - string_pool_offset] = name
        pos = end + 1
        if name == '':
            break

    bones = []
    for b in range(bone_count):
        base       = FIRST_BONE_OFFSET + b * BONE_STRIDE
        parent_raw = ri4(base)
        bone_flags = ru4(base + 12)

        px112 = rf4(base + 112)
        py112 = rf4(base + 116)
        pz112 = rf4(base + 120)

        px88  = rf4(base + 88)
        py88  = rf4(base + 92)
        pz88  = rf4(base + 96)

        # Local rotation in degrees (XYZ Euler) stored at +100/+104/+108.
        # These are only non-zero on Class B bones (0x0026/0x0066).
        # The pre-computed 3×4 local transform matrix lives at +188–+232:
        #   rows 0-2 of a 3×3 rotation matrix, with translation in column 3.
        # +76/+80/+84 purpose is still unknown; treated as reserved.
        prot_x = rf4(base + 100)
        prot_y = rf4(base + 104)
        prot_z = rf4(base + 108)

        bind_matrix_hex = raw[base + 16 : base + 80].hex()

        name_off   = ru4(base + BONE_STRIDE - 4)
        name       = string_map.get(name_off, f'bone_{b}')
        parent_idx = parent_raw if parent_raw >= 0 else None

        flags_say_b = _is_class_b_by_flags(bone_flags)
        data_say_b  = _is_class_b_by_data(px112, py112, pz112, px88, py88, pz88)

        if flags_say_b or data_say_b:
            pos_source = 'B'
            raw_p88    = (px88, py88, pz88)
            position   = (px88, py88, pz88)
        else:
            pos_source = 'A'
            raw_p88    = (0.0, 0.0, 0.0)
            position   = (px112, py112, pz112)

        # v15.0 ver
        # bones.append({
        #     'index':           b,
        #     'name':            name,
        #     'parent_idx':      parent_idx,
        #     'position':        position,
        #     'raw_p88':         raw_p88,
        #     'pos_source':      pos_source,
        #     'bone_flags':      bone_flags,
        #     'bind_matrix_hex': bind_matrix_hex,
        # })
        # v16.0 ver
        raw_rec_hex = raw[base : base + BONE_STRIDE].hex()

        bones.append({
            'index':           b,
            'name':            name,
            'parent_idx':      parent_idx,
            'position':        position,   # naive rest-pose position (matches mesh skinning)
            'raw_p88':         raw_p88,
            'p112':            (px112, py112, pz112),
            'pos_source':      pos_source,
            'bone_flags':      bone_flags,
            'bind_matrix_hex': bind_matrix_hex,
            'raw_rec_hex':     raw_rec_hex,
            # Local rotation angles in degrees for transform accumulation
            'local_rot_deg':   (prot_x, prot_y, prot_z),
        })

    # ── World-space accumulation (v0.25.1) ────────────────────────────────────
    #
    # NAIVE REST-POSE POSITIONS (stored in b['position'], used for bone head placement
    # and mesh skinning):
    #   Class A, no B ancestor:  b['position'] = p112  (absolute world)
    #   Class B:                 b['position'] = p88 accumulated from (0,0,0), no rotation
    #   Class A with B ancestor: b['position'] = TRUE accumulated world position
    #                            (same as v0.25.1 true_world — matches mesh verts because
    #                             p112 is stored as an offset from the B-chain anchor)
    #
    # TRUE WORLD POSITIONS (computed with rotation-aware accumulation):
    #   Used for Class B bones to compute pose_location and world_rot for tail direction.
    #   Class A-under-B uses true_world as its rest position directly.

    def _mat3_identity():
        return [[1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0]]

    def _mat3_mul(A, B):
        return [[sum(A[r][k] * B[k][c] for k in range(3))
                 for c in range(3)] for r in range(3)]

    def _rot_x(deg):
        a = math.radians(deg); c, s = math.cos(a), math.sin(a)
        return [[1, 0, 0], [0, c, -s], [0, s, c]]

    def _rot_y(deg):
        a = math.radians(deg); c, s = math.cos(a), math.sin(a)
        return [[c, 0, s], [0, 1, 0], [-s, 0, c]]

    def _rot_z(deg):
        a = math.radians(deg); c, s = math.cos(a), math.sin(a)
        return [[c, -s, 0], [s, c, 0], [0, 0, 1]]

    def _apply_rot(mat3, vec3):
        return tuple(sum(mat3[r][c] * vec3[c] for c in range(3)) for r in range(3))

    def _local_rotation(deg_xyz):
        """Rz * Ry * Rx from XYZ Euler degrees."""
        return _mat3_mul(_rot_z(deg_xyz[2]),
                         _mat3_mul(_rot_y(deg_xyz[1]), _rot_x(deg_xyz[0])))

    def _has_b_ancestor(bone_idx):
        par = bones[bone_idx]['parent_idx']
        while par is not None:
            if bones[par]['pos_source'] == 'B':
                return True
            par = bones[par]['parent_idx']
        return False

    # Step 1: compute true world positions using rotation-aware accumulation
    b_chain_pos = {}   # B-chain position from (0,0,0), ignoring Class A ancestors
    b_chain_rot = {}
    true_world  = {}
    true_rot    = {}

    for b in bones:
        idx  = b['index']
        is_b = (b['pos_source'] == 'B')
        par  = b['parent_idx']
        deg  = b['local_rot_deg']
        local_R = _local_rotation(deg) if any(abs(d) > 1e-6 for d in deg) else _mat3_identity()

        if par is None:
            true_world[idx] = b['p112']
            true_rot[idx]   = _mat3_identity()
            continue

        if not is_b and not _has_b_ancestor(idx):
            true_world[idx] = b['p112']
            true_rot[idx]   = _mat3_identity()
            continue

        if is_b:
            pw = b_chain_pos[par] if par in b_chain_pos else (0.0, 0.0, 0.0)
            pR = b_chain_rot[par] if par in b_chain_rot else _mat3_identity()
            rt = _apply_rot(pR, b['raw_p88'])
            wx, wy, wz = pw[0]+rt[0], pw[1]+rt[1], pw[2]+rt[2]
            b_chain_pos[idx] = (wx, wy, wz)
            b_chain_rot[idx] = _mat3_mul(pR, local_R)
            true_world[idx]  = (wx, wy, wz)
            true_rot[idx]    = _mat3_mul(pR, local_R)
            continue

        # Class A with B ancestor: add p112 to nearest B ancestor's b_chain_pos
        nb_pos = (0.0, 0.0, 0.0)
        nb_rot = _mat3_identity()
        anc = par
        while anc is not None:
            if bones[anc]['pos_source'] == 'B':
                nb_pos = b_chain_pos.get(anc, (0.0, 0.0, 0.0))
                nb_rot = b_chain_rot.get(anc, _mat3_identity())
                break
            anc = bones[anc]['parent_idx']
        rt = _apply_rot(nb_rot, b['p112'])
        wx, wy, wz = nb_pos[0]+rt[0], nb_pos[1]+rt[1], nb_pos[2]+rt[2]
        true_world[idx] = (wx, wy, wz)
        true_rot[idx]   = _mat3_identity()

    # Step 2: set rest-pose positions and pose transforms
    #   Rest position = v0-25-2 calculation (correct rest position)
    #   Pose transforms = v0-25-1_pos - v0-25-2_pos (difference between old "pose" and new "rest")
    #
    # v0-25-1 "pose position" was calculated as:
    #   Class B: naive = base + p88 (no parent rotation applied)
    #   Class A: true_world (rotation-aware accumulation)
    #
    # v0-25-2 "rest position" is:
    #   Class B: base + apply(parent_rot, p88)
    #   Class A: p112
    #
    # Pose transforms:
    #   pose_location: ONLY on Class A bones with DIRECT Class B parent
    #   pose_rotation: combined from all B ancestors for Class A with direct B parent
    for b in bones:
        idx = b['index']
        par = b['parent_idx']
        parent_is_b = par is not None and bones[par]['pos_source'] == 'B'

        if b['pos_source'] == 'B':
            # v0-25-2 rest position (current, with parent rotation)
            lx, ly, lz = b['raw_p88']
            base = (0.0, 0.0, 0.0)
            parent_rot = _mat3_identity()
            anc = b['parent_idx']
            while anc is not None:
                if bones[anc]['pos_source'] == 'B':
                    base = bones[anc]['position']
                    parent_rot = true_rot.get(anc, _mat3_identity())
                    break
                anc = bones[anc]['parent_idx']
            rotated_p88 = _apply_rot(parent_rot, (lx, ly, lz))
            rest_pos = (base[0] + rotated_p88[0], base[1] + rotated_p88[1], base[2] + rotated_p88[2])
            b['position'] = rest_pos

            # pose_location computed in two-pass block below
            b['pose_location'] = None
        else:
            # Class A: rest = p112
            b['position'] = b['p112']
            # pose_location computed in two-pass block below
            b['pose_location'] = None

        b['world_rot'] = true_rot.get(idx, _mat3_identity())

    # ── Two-pass pose_location computation ────────────────────────────
    # Pass 1: flag==0x180 bones get current plugin behavior.
    #         (Class A with direct B parent: true_world - p112; else zero)
    #         flag!=0x180 bones remain None (placeholder) for pass 2.
    for b in bones:
        if b['bone_flags'] == 0x180:
            par = b['parent_idx']
            if par is not None and bones[par]['pos_source'] == 'B':
                v0251_rest = true_world.get(b['index'], b['p112'])
                b['pose_location'] = (
                    v0251_rest[0] - b['p112'][0],
                    v0251_rest[1] - b['p112'][1],
                    v0251_rest[2] - b['p112'][2],
                )
            else:
                b['pose_location'] = (0.0, 0.0, 0.0)

    # Pass 2: iterate in file order (parent before child), replace
    #          placeholders with negated sum of ancestors' pose_locations.
    for b in bones:
        if b['pose_location'] is None:
            sx = sy = sz = 0.0
            anc = b['parent_idx']
            while anc is not None:
                anc_loc = bones[anc]['pose_location']
                if anc_loc is not None:
                    sx += anc_loc[0]
                    sy += anc_loc[1]
                    sz += anc_loc[2]
                anc = bones[anc]['parent_idx']
            b['pose_location'] = (-sx, -sy, -sz)

    # Pass 3: for 0x180 bones whose direct parent has flag=0x66, trace up
    #          the uninterrupted 0x66 ancestor chain and subtract the OLDEST
    #          0x66 ancestor's pose_location from the child's.
    for b in bones:
        if b['bone_flags'] == 0x180:
            par = b['parent_idx']
            if par is not None and bones[par]['bone_flags'] == 0x66:
                oldest_66 = par
                anc = bones[par]['parent_idx']
                while anc is not None and bones[anc]['bone_flags'] == 0x66:
                    oldest_66 = anc
                    anc = bones[anc]['parent_idx']
                oldest_loc = bones[oldest_66].get('pose_location', (0.0, 0.0, 0.0))
                current = b.get('pose_location', (0.0, 0.0, 0.0))
                b['pose_location'] = (
                    current[0] - oldest_loc[0],
                    current[1] - oldest_loc[1],
                    current[2] - oldest_loc[2],
                )

    # Add combined rotation for Class A bones with direct B parent
    # Walk up the ancestor chain, collecting rotations from all B bones
    for b in bones:
        par = b['parent_idx']
        if b['pos_source'] == 'A' and par is not None and bones[par]['pos_source'] == 'B':
            # Collect all B ancestor rotations in order from nearest to farthest
            anc_rotations = []
            anc = par
            while anc is not None:
                if bones[anc]['pos_source'] == 'B':
                    anc_rot = bones[anc].get('local_rot_deg', (0.0, 0.0, 0.0))
                    anc_rotations.append(anc_rot)
                anc = bones[anc]['parent_idx']
            
            # Combine rotations: apply nearest first, then farthest last
            # R_combined = R_nearest * ... * R_farthest
            combined = _mat3_identity()
            for rot_deg in anc_rotations:
                local_R = _local_rotation(rot_deg)
                combined = _mat3_mul(local_R, combined)  # Apply new rotation on LEFT (before existing)
            
            # Store combined rotation as Euler XYZ
            # Convert rotation matrix to Euler angles (XYZ order)
            # sy = sqrt(m00^2 + m10^2)
            sy = math.sqrt(combined[0][0]**2 + combined[1][0]**2)
            if sy > 1e-6:
                x = math.atan2(combined[2][1], combined[2][2])
                y = math.atan2(-combined[2][0], sy)
                z = math.atan2(combined[1][0], combined[0][0])
            else:
                x = math.atan2(-combined[1][2], combined[1][1])
                y = math.atan2(-combined[2][0], sy)
                z = 0.0
            
            b['pose_rotation'] = (math.degrees(x), math.degrees(y), math.degrees(z))
        else:
            b['pose_rotation'] = (0.0, 0.0, 0.0)

    # DEBUG: Uncomment to see bone position list
    for b in bones:
        px, py, pz = b['position']
        pstr = str(b['parent_idx']) if b['parent_idx'] is not None else 'ROOT'
        print(f"  [{b['index']:2d}] {b['name']:<32} parent={pstr:<4}  "
              f"pos=({px:8.4f},{py:8.4f},{pz:8.4f})  [src={b['pos_source']}  "
              f"flags=0x{b['bone_flags']:08X}]")

    # DEBUG: Uncomment to see pose transforms table
    print("\n=== POSE TRANSFORMS TABLE ===")
    print("BoneID | BoneName                        | ParentID | transloc(X, Y, Z)                     | transrot(X, Y, Z)              | ClassFlag")
    print("------ | ------------------------------- | -------- | ------------------------------------- | ------------------------------ | -----------------")
    for b in bones:
        idx = b['index']
        name = b['name']
        par = b['parent_idx'] if b['parent_idx'] is not None else -1
        loc = b.get('pose_location', (0.0, 0.0, 0.0))
        # Use pose_rotation for display (combined for A bones, original for B bones)
        rot = b.get('pose_rotation', (0.0, 0.0, 0.0))
        src = b.get('pos_source', 'A')
        flags = b.get('bone_flags', 0x180)
        print(f"{idx:2d} | {name:<32} | {par:2d} | transloc({loc[0]: 8.4f}, {loc[1]: 8.4f}, {loc[2]: 8.4f}) | transrot({rot[0]: 7.2f}, {rot[1]: 7.2f}, {rot[2]: 7.2f}) | src={src}, flag=0x{flags:04X}")

    bone_names = [b['name'] for b in bones]
    # DEBUG: Uncomment to see bone names list
    print(f"  Bone names: {bone_names}")

    return bones


def read_g_bone_name_map(filepath):
    """Read a .g skeleton file and return ({bone_name: index}, bone_count).
    Used by the exporter to enforce original bone ordering when combining skeletons.
    Returns ({}, 0) if the file cannot be read."""
    try:
        with open(filepath, 'rb') as f:
            raw = f.read()
        str_off    = struct.unpack('>I', raw[0x04:0x08])[0]
        bone_count = struct.unpack('>I', raw[0x08:0x0C])[0]
        rec_start  = struct.unpack('>I', raw[0x0C:0x10])[0]
        rec_size   = (str_off - rec_start) // bone_count
        pos = str_off
        string_map = {}
        while pos < len(raw):
            try:
                end = raw.index(0, pos)
            except ValueError:
                break
            name = raw[pos:end].decode('ascii', errors='replace')
            string_map[pos - str_off] = name
            pos = end + 1
            if name == '':
                break
        name_to_index = {}
        for b in range(bone_count):
            base     = rec_start + b * rec_size
            name_off = struct.unpack('>I', raw[base + rec_size - 4: base + rec_size])[0]
            name     = string_map.get(name_off, f'bone_{b}')
            name_to_index[name] = b
        return name_to_index, bone_count
    except Exception as e:
        print(f"WARNING: could not read reference skeleton '{filepath}': {e}")
        return {}, 0


# =============================================================================
# SKELETON (.g) — WRITING
# =============================================================================
def write_skeleton_file(armature_obj, filepath, source_filepath="", append_new_bones=True):
    """Serialise a Blender Armature back to the .g binary format."""
    arm = armature_obj.data

    # --- Phase 1: Collect bones, storing Blender parent NAME (not index yet) ---
    bones_raw = []
    for bone in arm.bones:
        idx      = bone.get('fe_bone_index', None)
        par_name = bone.parent.name if bone.parent else None
        pos      = bone.head_local
        # Get the export name (convert __ back to :)
        export_name = bone.name.replace('__', ':')
        bones_raw.append({
            'blender_bone':    bone,
            'fe_index':        idx,
            'par_name':        par_name,
            'parent_idx':      None,          # resolved in Phase 3
            'name':            export_name,  # Use export name with original colons
            'position':        (float(pos.x), float(pos.y), float(pos.z)),
            'pos_source':      str(bone.get('fe_pos_source', 'A')),
            'bone_flags':      int(bone.get('fe_bone_flags', 0x180)),
            'bind_matrix_hex': str(bone.get('fe_bind_matrix_hex', '')),
            'raw_rec_hex':     str(bone.get('fe_raw_rec_hex', '')),
        })

    # --- Phase 2: Assign indices ---
    ref_name_to_idx, ref_bone_count = (
        read_g_bone_name_map(source_filepath)
        if source_filepath and os.path.isfile(source_filepath)
        else ({}, 0)
    )

    if not append_new_bones:
        # Hierarchy mode: assign indices 0..n-1 in Blender's bone display
        # order (parent before child).  Reference skeleton is still used
        # for raw_rec_hex matching but not for index preservation.
        for i, b in enumerate(bones_raw):
            b['fe_index'] = i

    elif ref_name_to_idx:
        # Append-new-bones mode with reference: bones matching the reference
        # keep their original index.  All other bones are treated as new and
        # assigned indices >= ref_bone_count.
        # 
        # Matching priority:
        # 1. Match by name (original behavior) - for bones that exist in reference
        # 2. Match by raw_rec_hex presence in reference file - for renamed bones
        #    (if bone has raw_rec_hex that exists in reference, keep original index)
        
        # Build a set of raw_rec_hex values from reference file
        ref_raw_hex_set = set()
        if source_filepath and os.path.isfile(source_filepath):
            ref_bones = read_skeleton_file(source_filepath)
            for rb in ref_bones:
                if rb.get('raw_rec_hex'):
                    ref_raw_hex_set.add(rb['raw_rec_hex'])
        
        for b in bones_raw:
            # First: try matching by name (original behavior)
            ref_idx = ref_name_to_idx.get(b['name'], None)
            if ref_idx is not None:
                b['fe_index'] = ref_idx
            else:
                # Second: if bone has raw_rec_hex that exists in reference, it's a renamed bone
                # Find which index in reference matches this raw_rec_hex
                b_raw_hex = b.get('raw_rec_hex', '')
                if b_raw_hex and b_raw_hex in ref_raw_hex_set:
                    # Find the index in reference
                    for rb in ref_bones:
                        if rb.get('raw_rec_hex') == b_raw_hex:
                            b['fe_index'] = rb['index']
                            break
                    else:
                        b['fe_index'] = None
                else:
                    b['fe_index'] = None   # will be assigned below

        new_bones = [b for b in bones_raw if b['fe_index'] is None]
        next_free = ref_bone_count
        for b in new_bones:
            b['fe_index'] = next_free
            next_free += 1

    else:
        # Append-new-bones mode, no reference: fall back to collision-detection approach.
        index_owners = {}
        for b in bones_raw:
            if b['fe_index'] is not None:
                index_owners.setdefault(b['fe_index'], []).append(b['name'])

        for idx, owners in index_owners.items():
            if len(owners) > 1:
                owners_sorted = sorted(owners)
                keep = owners_sorted[0]
                for dup in owners_sorted[1:]:
                    print(f"WARNING: fe_bone_index {idx} collision: "
                          f"'{keep}' keeps it, '{dup}' will be reassigned.")
                for b in bones_raw:
                    if b['name'] in owners_sorted[1:] and b['fe_index'] == idx:
                        b['fe_index'] = None

        assigned = {b['fe_index'] for b in bones_raw if b['fe_index'] is not None}
        next_free = 0
        for b in bones_raw:
            if b['fe_index'] is None:
                while next_free in assigned:
                    next_free += 1
                b['fe_index'] = next_free
                assigned.add(next_free)
                next_free += 1

    # --- Phase 3: Resolve parent indices using the finalised name→index map ---
    name_to_idx = {b['name']: b['fe_index'] for b in bones_raw}
    for b in bones_raw:
        if b['par_name'] is not None:
            resolved = name_to_idx.get(b['par_name'], None)
            if resolved is None:
                print(f"WARNING: bone '{b['name']}' parent '{b['par_name']}' "
                      f"not found in armature — treating as root.")
            b['parent_idx'] = resolved
        else:
            b['parent_idx'] = None

    # --- Phase 4: Sort by fe_index (original order preserved, new bones appended) ---
    bones_sorted = sorted(bones_raw, key=lambda b: b['fe_index'])
    n = len(bones_sorted)

    # Write back finalised fe_bone_index to every Blender bone so that a
    # subsequent mesh export immediately uses the correct (post-reassignment)
    # bone indices rather than the stale values carried from the source skeleton.
    for b in bones_sorted:
        b['blender_bone']['fe_bone_index'] = b['fe_index']
        if 'fe_original_bone_id' not in b['blender_bone']:
            b['blender_bone']['fe_original_bone_id'] = b['fe_index']

    # Resolve duplicate fe_original_bone_id values.  When a bone is duplicated
    # in Blender the copy inherits custom properties, including the original
    # fe_original_bone_id of the source bone, which would cause the old_to_new
    # map in export_gs_full_rebuild to map the original bone ID to the wrong
    # index.  Prefer the bone whose new index matches its original ID (it kept
    # its position), otherwise the first bone encountered.
    seen_orig_ids = {}
    for b in bones_sorted:
        oid = b['blender_bone'].get('fe_original_bone_id')
        if oid is not None:
            if oid in seen_orig_ids:
                prev = seen_orig_ids[oid]
                # One of them must give up its fe_original_bone_id.
                # Keep the one whose new index == original id (unchanged position).
                keep = prev
                drop = b
                if b['fe_index'] == oid:
                    keep = b
                    drop = prev
                elif prev['fe_index'] == oid:
                    keep = prev
                    drop = b
                # If neither matches by position, keep the first (prev).
                del drop['blender_bone']['fe_original_bone_id']
                print(f"NOTE: Duplicate fe_original_bone_id {oid} on "
                      f"'{b['name']}' and '{prev['name']}'; cleared on "
                      f"'{drop['name']}' (new index {drop['fe_index']}).")
            else:
                seen_orig_ids[oid] = b

    bones_by_idx = {b['fe_index']: b for b in bones_sorted}

    # --- Phase 5: Build sibling / first-child chains ---
    next_sib    = [-1] * n
    first_child = [-1] * n
    children_of = defaultdict(list)

    for b in bones_sorted:
        par = b['parent_idx']
        if par is not None:
            children_of[par].append(b['fe_index'])

    for par_idx, clist in children_of.items():
        clist_sorted = sorted(clist)
        first_child[par_idx] = clist_sorted[0]
        for i in range(len(clist_sorted) - 1):
            next_sib[clist_sorted[i]] = clist_sorted[i + 1]
        next_sib[clist_sorted[-1]] = -1

    # --- Phase 6: Build string pool ---
    pool         = b'[unknown]\x00'
    name_offsets = []
    for b in bones_sorted:
        name_offsets.append(len(pool))
        # Check if bone was truncated during import - restore original name
        if b['name'].startswith('_edit_') and 'fe_original_name' in b.get('blender_bone', {}):
            export_name = b['blender_bone']['fe_original_name']
        else:
            export_name = b['name']
        pool += export_name.encode('ascii') + b'\x00'

    string_pool_offset = FIRST_BONE_OFFSET + n * BONE_STRIDE

    # --- Phase 7: Write file header ---
    out  = [struct.pack('>I', 0)]
    out.append(struct.pack('>I', string_pool_offset))
    out.append(struct.pack('>I', n))
    out.append(struct.pack('>I', FIRST_BONE_OFFSET))

    pf = struct.Struct('>f')
    si = struct.Struct('>i')
    pI = struct.Struct('>I')

    # --- Rotation helpers for Class B ancestor-relative p88 ---
    def _identity_3x3():
        return (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    def _mul_3x3(A, B):
        a00,a01,a02,a10,a11,a12,a20,a21,a22 = A
        b00,b01,b02,b10,b11,b12,b20,b21,b22 = B
        return (
            a00*b00 + a01*b10 + a02*b20,
            a00*b01 + a01*b11 + a02*b21,
            a00*b02 + a01*b12 + a02*b22,
            a10*b00 + a11*b10 + a12*b20,
            a10*b01 + a11*b11 + a12*b21,
            a10*b02 + a11*b12 + a12*b22,
            a20*b00 + a21*b10 + a22*b20,
            a20*b01 + a21*b11 + a22*b21,
            a20*b02 + a21*b12 + a22*b22,
        )
    def _rot_deg_to_3x3(deg):
        if not any(abs(d) > 1e-6 for d in deg):
            return _identity_3x3()
        rx = math.radians(deg[0])
        ry = math.radians(deg[1])
        rz = math.radians(deg[2])
        cx, sx = math.cos(rx), math.sin(rx)
        cy, sy = math.cos(ry), math.sin(ry)
        cz, sz = math.cos(rz), math.sin(rz)
        return (
            cz*cy, cz*sy*sx - sz*cx, cz*sy*cx + sz*sx,
            sz*cy, sz*sy*sx + cz*cx, sz*sy*cx - cz*sx,
            -sy,   cy*sx,            cy*cx,
        )
    def _apply_3x3(m, v):
        return (m[0]*v[0] + m[1]*v[1] + m[2]*v[2],
                m[3]*v[0] + m[4]*v[1] + m[5]*v[2],
                m[6]*v[0] + m[7]*v[1] + m[8]*v[2])
    def _transpose_3x3(m):
        return (m[0], m[3], m[6],
                m[1], m[4], m[7],
                m[2], m[5], m[8])

    # Pre-compute accumulated rotation (true_rot) for all bones.
    # Used to compute p88 offset relative to nearest Class B ancestor.
    _true_rot = {}
    for _b in bones_sorted:
        _idx = _b['fe_index']
        _parent_rot = _true_rot.get(_b['parent_idx'], _identity_3x3())
        _deg = _b['blender_bone'].get('fe_local_rot_deg', (0.0, 0.0, 0.0))
        try:
            _deg = (float(_deg[0]), float(_deg[1]), float(_deg[2]))
        except Exception:
            _deg = (0.0, 0.0, 0.0)
        _local_R = _rot_deg_to_3x3(_deg)
        _true_rot[_idx] = _mul_3x3(_parent_rot, _local_R)

    # --- Phase 8: Write bone records ---
    for b in bones_sorted:
        idx        = b['fe_index']
        par        = b['parent_idx'] if b['parent_idx'] is not None else -1
        wx, wy, wz = b['position']
        is_b       = (b['pos_source'] == 'B')
        bone_flags = b['bone_flags']

        if is_b:
            # Find nearest Class B ancestor; compute p88 as local offset
            # from that ancestor in its local frame: p88 = anc_rot^T * (pos - base)
            base_world = (0.0, 0.0, 0.0)
            anc_rot = _identity_3x3()
            anc_idx = b['parent_idx']
            while anc_idx is not None:
                anc_bone = bones_by_idx.get(anc_idx)
                if anc_bone is None:
                    break
                if anc_bone['pos_source'] == 'B':
                    base_world = anc_bone['position']
                    anc_rot = _true_rot.get(anc_idx, _identity_3x3())
                    break
                anc_idx = anc_bone['parent_idx']
            dx = wx - base_world[0]
            dy = wy - base_world[1]
            dz = wz - base_world[2]
            rot_T = _transpose_3x3(anc_rot)
            lx, ly, lz = _apply_3x3(rot_T, (dx, dy, dz))
            p88_vals  = (lx, ly, lz)
            p112_vals = (0.0, 0.0, 0.0)
        else:
            p88_vals  = (0.0, 0.0, 0.0)
            p112_vals = (wx, wy, wz)

        raw_hex = b['raw_rec_hex']

        # ── v25.9: Constraint-target raw record override ──────────────────────
        #
        # If this pose bone has a copy-type constraint pointing at another bone
        # on any armature, we borrow bytes +12 through +235 of that bone's
        # raw record.  This transfers:
        #   bone_flags (+12), bind matrix (+16..+79), unknowns (+80..+87),
        #   local translation p88 (+88..+99), local rotation degrees (+100..+111),
        #   world/local position p112 (+112..+123), duplicate (+124..+135),
        #   unknown floats (+136..+187), pre-computed 3×4 matrix (+188..+235).
        #
        # Bytes that remain per-owner:
        #   parent/sibling/child (+0..+11) — computed from Blender hierarchy
        #   bone index field (+236..+239)  — computed from fe_index
        #   name pool offset (+240..+243)  — computed from string pool
        #
        # Precedence: first matching constraint with a valid target wins.
        # Constraint types checked: COPY_TRANSFORMS, COPY_ROTATION,
        #   COPY_LOCATION, COPY_SCALE.
        _COPY_TYPES = {'COPY_TRANSFORMS', 'COPY_ROTATION',
                       'COPY_LOCATION', 'COPY_SCALE'}
        _OVERRIDE_START = 12    # first byte to copy from target record
        _OVERRIDE_END   = 236   # one past last byte to copy (exclusive)

        blender_bone = b['blender_bone']
        arm_data     = armature_obj.data  # the armature being exported

        # Pose bones live on the armature *object*, not its data.  We need the
        # object to access pose bones and their constraints.
        # write_skeleton_file receives the armature *object* as its first arg.
        pose_bone = armature_obj.pose.bones.get(blender_bone.name)

        if pose_bone is not None:
            for con in pose_bone.constraints:
                if con.type not in _COPY_TYPES:
                    continue
                tgt_obj    = getattr(con, 'target',    None)
                tgt_name   = getattr(con, 'subtarget', '')
                if tgt_obj is None or tgt_obj.type != 'ARMATURE' or not tgt_name:
                    continue

                tgt_bone = tgt_obj.data.bones.get(tgt_name)
                if tgt_bone is None:
                    continue

                tgt_raw_hex = str(tgt_bone.get('fe_raw_rec_hex', ''))
                if len(tgt_raw_hex) != BONE_STRIDE * 2:
                    print(f"  [v25.9] Bone '{blender_bone.name}': constraint target "
                          f"'{tgt_name}' has no valid fe_raw_rec_hex — skipping override")
                    continue

                # Splice bytes +12..+235 from target into owner's raw record.
                # If the owner has no raw record yet (new bone), build a zeroed
                # 244-byte base so the splice still has somewhere to land.
                if len(raw_hex) == BONE_STRIDE * 2:
                    owner_rec = bytearray(bytes.fromhex(raw_hex))
                else:
                    owner_rec = bytearray(BONE_STRIDE)  # all-zero base

                tgt_rec = bytes.fromhex(tgt_raw_hex)
                owner_rec[_OVERRIDE_START:_OVERRIDE_END] = \
                    tgt_rec[_OVERRIDE_START:_OVERRIDE_END]

                raw_hex = owner_rec.hex()
                b['raw_rec_hex'] = raw_hex  # keep dict consistent

                # Also update the derived fields that the code below reads
                # before it reaches the raw_hex restore branch.
                tgt_flags  = struct.unpack_from('>I', tgt_rec, 12)[0]
                b['bone_flags'] = tgt_flags
                bone_flags      = tgt_flags
                is_b_new = _is_class_b_by_flags(tgt_flags)
                b['pos_source'] = 'B' if is_b_new else 'A'
                is_b = is_b_new

                print(f"  [v25.9] Bone '{blender_bone.name}': copied raw bytes "
                      f"+12..+235 from constraint target '{tgt_name}' "
                      f"(flags=0x{tgt_flags:04X}, src={b['pos_source']})")
                break   # first matching constraint wins

        # New bone detection: in append mode, new bones have idx >= ref_bone_count.
        # In hierarchy mode (append_new_bones=False), new bones have no raw_rec_hex.
        if not append_new_bones:
            is_new_bone = not raw_hex or len(raw_hex) != BONE_STRIDE * 2
        else:
            is_new_bone = (ref_bone_count > 0 and idx >= ref_bone_count)
        
        # v24.6: Debug - show renamed bones
        if is_new_bone or not raw_hex:
            print(f"  Export Bone {idx} '{b['name']}': raw_rec_hex={len(raw_hex) > 0}, is_new={is_new_bone}")
        
        # DEBUG: trace position/rotation detection for 'hair' bone
        if b['name'] == 'hair':
            print(f"  [DEBUG hair BEFORE] idx={idx} is_b={is_b} raw_hex_len={len(raw_hex)} raw_hex_nonempty={bool(raw_hex)} is_new={is_new_bone}")
            print(f"  [DEBUG hair BEFORE] head_local=({b['position'][0]:.6f}, {b['position'][1]:.6f}, {b['position'][2]:.6f})")
            print(f"  [DEBUG hair BEFORE] pos_source={b['pos_source']} bone_flags=0x{b['bone_flags']:X} parent_idx={b['parent_idx']}")
        
        if raw_hex and len(raw_hex) == BONE_STRIDE * 2:
            if idx < 3:
                print(f"    >>> Using RAW_REC_HEX branch!")
            # Restore original record bytes verbatim
            # Update sibling/child pointers for ALL bones to reflect hierarchy including new bones
            try:
                rec = bytearray(bytes.fromhex(raw_hex))
                struct.pack_into('>i', rec, 0,  par)
                struct.pack_into('>I', rec, 12, bone_flags)
                
                # Update sibling/child pointers to account for new bones in hierarchy
                if idx < 3:
                    print(f"      >>> Updating sibling/child: next_sib={next_sib[idx]}, first_child={first_child[idx]}")
                struct.pack_into('>i', rec, 4,  next_sib[idx])
                struct.pack_into('>i', rec, 8,  first_child[idx])
                
                # Detect position and rotation changes by comparing current Blender
                # state against what is stored in the raw record.  Any bone whose
                # head position or fe_local_rot_deg differs from the preserved
                # record gets the relevant fields (and the pre-computed 3x4 matrix)
                # updated.  This lets users move bones in Blender and have the
                # changes reflected in the exported skeleton.
                pos_changed = False
                if is_b:
                    old_x = struct.unpack_from('>f', rec, 88)[0]
                    old_y = struct.unpack_from('>f', rec, 92)[0]
                    old_z = struct.unpack_from('>f', rec, 96)[0]
                    pos_changed = any(abs(a - b) > 1e-6 for a, b in zip((old_x, old_y, old_z), p88_vals))
                else:
                    old_x = struct.unpack_from('>f', rec, 112)[0]
                    old_y = struct.unpack_from('>f', rec, 116)[0]
                    old_z = struct.unpack_from('>f', rec, 120)[0]
                    pos_changed = any(abs(a - b) > 1e-6 for a, b in zip((old_x, old_y, old_z), p112_vals))

                # DEBUG: trace p88 computation for Class B bones
                if is_b and b['pos_source'] == 'B':
                    old_p88 = (struct.unpack_from('>f', rec, 88)[0],
                               struct.unpack_from('>f', rec, 92)[0],
                               struct.unpack_from('>f', rec, 96)[0])
                    if any(abs(a - b) > 1e-6 for a, b in zip(old_p88, p88_vals)):
                        print(f"  [DEBUG BONE {idx}] '{b['name']}' old_p88=({old_p88[0]:.6f},{old_p88[1]:.6f},{old_p88[2]:.6f}) "
                              f"p88_vals=({p88_vals[0]:.6f},{p88_vals[1]:.6f},{p88_vals[2]:.6f}) "
                              f"diff=({p88_vals[0]-old_p88[0]:.6f},{p88_vals[1]-old_p88[1]:.6f},{p88_vals[2]-old_p88[2]:.6f})")
                        # Also show the ancestor info
                        _anc = b['parent_idx']
                        while _anc is not None:
                            _ab = bones_by_idx.get(_anc)
                            if _ab and _ab['pos_source'] == 'B':
                                print(f"    -> B ancestor idx={_anc} '{_ab['name']}' pos=({_ab['position'][0]:.4f},{_ab['position'][1]:.4f},{_ab['position'][2]:.4f})")
                                print(f"    -> delta=({wx-_ab['position'][0]:.4f},{wy-_ab['position'][1]:.4f},{wz-_ab['position'][2]:.4f})")
                                break
                            _anc = _ab['parent_idx'] if _ab else None

                old_rx = struct.unpack_from('>f', rec, 100)[0]
                old_ry = struct.unpack_from('>f', rec, 104)[0]
                old_rz = struct.unpack_from('>f', rec, 108)[0]
                current_rot = b['blender_bone'].get('fe_local_rot_deg', (0.0, 0.0, 0.0))
                try:
                    current_rot = (float(current_rot[0]), float(current_rot[1]), float(current_rot[2]))
                except Exception:
                    current_rot = (0.0, 0.0, 0.0)
                rot_changed = any(abs(a - b) > 1e-6 for a, b in zip((old_rx, old_ry, old_rz), current_rot))

                # DEBUG: trace position/rotation detection for 'hair' bone
                if b['name'] == 'hair':
                    old_pos_str = f"old_p88=({old_x:.6f}, {old_y:.6f}, {old_z:.6f})" if is_b else f"old_p112=({old_x:.6f}, {old_y:.6f}, {old_z:.6f})"
                    new_pos_str = f"p88_vals=({p88_vals[0]:.6f}, {p88_vals[1]:.6f}, {p88_vals[2]:.6f})" if is_b else f"p112_vals=({p112_vals[0]:.6f}, {p112_vals[1]:.6f}, {p112_vals[2]:.6f})"
                    print(f"  [DEBUG hair INSIDE] {old_pos_str}")
                    print(f"  [DEBUG hair INSIDE] {new_pos_str}")
                    print(f"  [DEBUG hair INSIDE] old_rot=({old_rx:.6f}, {old_ry:.6f}, {old_rz:.6f})  current_rot=({current_rot[0]:.6f}, {current_rot[1]:.6f}, {current_rot[2]:.6f})")
                    print(f"  [DEBUG hair INSIDE] pos_changed={pos_changed} rot_changed={rot_changed}")

                if is_new_bone or pos_changed or rot_changed:
                    if b['name'] == 'hair':
                        print(f"  [DEBUG hair] ENTERED update block: writing {'B p88' if is_b else 'A p112'}")
                    if is_b:
                        struct.pack_into('>f', rec, 88, p88_vals[0])
                        struct.pack_into('>f', rec, 92, p88_vals[1])
                        struct.pack_into('>f', rec, 96, p88_vals[2])
                        tx, ty, tz = p88_vals
                    else:
                        struct.pack_into('>f', rec, 112, p112_vals[0])
                        struct.pack_into('>f', rec, 116, p112_vals[1])
                        struct.pack_into('>f', rec, 120, p112_vals[2])
                        struct.pack_into('>f', rec, 124, p112_vals[0])
                        struct.pack_into('>f', rec, 128, p112_vals[1])
                        struct.pack_into('>f', rec, 132, p112_vals[2])
                        tx, ty, tz = p112_vals

                    if rot_changed:
                        struct.pack_into('>f', rec, 100, current_rot[0])
                        struct.pack_into('>f', rec, 104, current_rot[1])
                        struct.pack_into('>f', rec, 108, current_rot[2])
                        # Recompute pre-computed 3x4 local-transform matrix at +188
                        # R = Rz(rotZ) * Ry(rotY) * Rx(rotX), translation = (tx,ty,tz)
                        if any(abs(d) > 1e-6 for d in current_rot):
                            rx = math.radians(current_rot[0])
                            ry = math.radians(current_rot[1])
                            rz = math.radians(current_rot[2])
                            cx, sx = math.cos(rx), math.sin(rx)
                            cy, sy = math.cos(ry), math.sin(ry)
                            cz, sz = math.cos(rz), math.sin(rz)
                            r00 = cz * cy
                            r01 = cz * sy * sx - sz * cx
                            r02 = cz * sy * cx + sz * sx
                            r10 = sz * cy
                            r11 = sz * sy * sx + cz * cx
                            r12 = sz * sy * cx - cz * sx
                            r20 = -sy
                            r21 = cy * sx
                            r22 = cy * cx
                        else:
                            r00, r01, r02 = 1.0, 0.0, 0.0
                            r10, r11, r12 = 0.0, 1.0, 0.0
                            r20, r21, r22 = 0.0, 0.0, 1.0

                        struct.pack_into('>f', rec, 188, r00)
                        struct.pack_into('>f', rec, 192, r01)
                        struct.pack_into('>f', rec, 196, r02)
                        struct.pack_into('>f', rec, 200, tx)
                        struct.pack_into('>f', rec, 204, r10)
                        struct.pack_into('>f', rec, 208, r11)
                        struct.pack_into('>f', rec, 212, r12)
                        struct.pack_into('>f', rec, 216, ty)
                        struct.pack_into('>f', rec, 220, r20)
                        struct.pack_into('>f', rec, 224, r21)
                        struct.pack_into('>f', rec, 228, r22)
                        struct.pack_into('>f', rec, 232, tz)
                    else:
                        # Position changed only — update the translation column of
                        # the pre-computed matrix at +200/+216/+232; rotation part unchanged.
                        struct.pack_into('>f', rec, 200, tx)
                        struct.pack_into('>f', rec, 216, ty)
                        struct.pack_into('>f', rec, 232, tz)

                # Always update: bone index and name offset
                struct.pack_into('>H', rec, BONE_STRIDE - 8, idx)   # +236: bone index uint16
                # +238 (0x0001) preserved verbatim from raw record
                struct.pack_into('>I', rec, BONE_STRIDE - 4, name_offsets[idx])
                out.append(bytes(rec))
                assert len(rec) == BONE_STRIDE
                continue
            except (ValueError, struct.error) as e:
                print(f"WARNING: could not restore raw record for bone '{b['name']}': {e}. "
                      f"Falling back to computed record.")

        # --- Fallback: build record from scratch (new bones, or import before v16) ---
        # New bones are always written as Class A (flags 0x0180) with world position
        # at +112/+124. All rotation, scale, and pre-computed matrix fields are zeroed,
        # except the identity diagonal at +188, +208, +228.
        bone_flags = 0x0180   # Force Class A for all new/scratch-built bones
        wx, wy, wz = b['position']

        bind_bytes = b''.join(struct.pack('>f', v) for v in _BONE_MATRIX_FLOATS)

        rec  = si.pack(par)
        rec += si.pack(next_sib[idx])
        rec += si.pack(first_child[idx])
        rec += pI.pack(bone_flags)
        rec += bind_bytes          # +16: identity-like bind matrix (64 bytes)
        rec += b'\x00' * 8         # +80: reserved (zeros)
        rec += b'\x00' * 12        # +88: p88 XYZ (zeros — Class A)
        rec += b'\x00' * 12        # +100: local rotation degrees (zeros)
        rec += pf.pack(wx)         # +112: world position X
        rec += pf.pack(wy)         # +116: world position Y
        rec += pf.pack(wz)         # +120: world position Z
        rec += pf.pack(wx)         # +124: duplicate world position X
        rec += pf.pack(wy)         # +128: duplicate world position Y
        rec += pf.pack(wz)         # +132: duplicate world position Z
        rec += b'\x00' * 52        # +136: unknown zeros (13 floats)
        rec += pf.pack(1.0)        # +188: pre-computed matrix row0col0 (identity)
        rec += b'\x00' * 16        # +192–+207: row0col1,row0col2,row0col3, row1col0
        rec += pf.pack(1.0)        # +208: pre-computed matrix row1col1 (identity)
        rec += b'\x00' * 16        # +212–+227: row1col2,row1col3, row2col0,row2col1
        rec += pf.pack(1.0)        # +228: pre-computed matrix row2col2 (identity)
        rec += b'\x00' * 4         # +232: row2col3 = translation Z (zero)
        rec += struct.pack('>H', idx)   # +236: bone index uint16
        rec += struct.pack('>H', 1)     # +238: constant 0x0001
        rec += pI.pack(name_offsets[idx])  # +240: name offset

        assert len(rec) == BONE_STRIDE, f"Bone {idx} record wrong size: {len(rec)}"
        out.append(rec)

    out.append(pool)

    # ── Post-write: sweep all bone records and update +236 with bone index ────
    # +236 stores the bone's own index as a uint16 (2 bytes).
    # +238 stores the constant 0x0001 (preserved from raw records or already
    # written correctly by the scratch-built path above).
    # Doing a final sweep ensures every record is correct regardless of how it was built.
    out = b''.join(out)  # Convert list to bytes for struct.pack_into
    HEADER_SIZE = 16  # .g header is 16 bytes
    out_ba = bytearray(out)
    for i in range(n):
        rec_offset = HEADER_SIZE + i * BONE_STRIDE
        struct.pack_into('>H', out_ba, rec_offset + BONE_STRIDE - 8, i)
    out = out_ba

    with open(filepath, 'wb') as f:
        f.write(out)

    print(f"\n=== EXPORTED SKELETON: {os.path.basename(filepath)} ===")
    print(f"  {n} bones,  {len(out)} bytes written")
    return True


# =============================================================================
# BLENDER ARMATURE CREATION
# =============================================================================

def _safe_bone_name(raw_name, max_len=50):
    """Truncate bone name to fit Blender's 50-char limit, matching create_armature."""
    if len(raw_name) > max_len:
        name = raw_name
        if '|' in name:
            name = name.split('|', 1)[1]
        if len(name) > max_len - 6:
            name = name[-(max_len - 6):]
        name = "_edit_" + name
        return name
    return raw_name


def _generate_unique_bone_names(bones, max_len=50):
    """Return dict {bone_index: unique_safe_name}, deduplicating truncated names."""
    from collections import Counter
    # First pass: apply truncation
    names = {}
    for b in bones:
        names[b['index']] = _safe_bone_name(b['name'], max_len)
    counter = Counter(names.values())
    # Second pass: deduplicate
    result = {}
    used = set()
    for b in sorted(bones, key=lambda x: x['index']):
        idx = b['index']
        base = names[idx]
        if counter[base] > 1:
            num = 1
            while True:
                suffix = f"_{num:02d}"
                cand = base
                if len(base) + len(suffix) > max_len:
                    if base.startswith('_edit_'):
                        keep = max_len - len(suffix)
                        cand = '_edit_' + base[6:][-(keep - 6):]
                    else:
                        cand = base[-(max_len - len(suffix)):]
                cand += suffix
                if cand not in used:
                    result[idx] = cand
                    used.add(cand)
                    break
                num += 1
        else:
            result[idx] = base
            used.add(base)
    return result


def create_armature(obj_name, bones, armature_data_name=None, skeleton_filepath=None):
    """Create a Blender Armature from parsed bone data.
    
    obj_name: Name for the armature object
    bones: Bone data
    armature_data_name: Optional name for armature data (defaults to obj_name + '_skeleton')
    skeleton_filepath: Optional path to the imported skeleton .g file (stored as custom property)
    """
    if armature_data_name is None:
        armature_data_name = obj_name + '_skeleton'
    
    print(f"\n=== CREATING ARMATURE '{obj_name}' ({len(bones)} bones) ===")

    from mathutils import Matrix, Vector

    DEFAULT_LENGTH = 0.5

    arm_data = bpy.data.armatures.new(armature_data_name)
    arm_data.display_type = 'OCTAHEDRAL'
    arm_obj  = bpy.data.objects.new(obj_name, arm_data)
    bpy.context.collection.objects.link(arm_obj)

    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='EDIT')

    edit_bones = arm_data.edit_bones
    created    = {}

    unique_names = _generate_unique_bone_names(bones)
    name_to_idx  = {v: k for k, v in unique_names.items()}

    for bone in bones:
        idx       = bone['index']
        bone_name = unique_names[idx]

        eb        = edit_bones.new(bone_name)
        eb.head   = Vector(bone['position'])

        # Force all bone tails to +Y direction (rotation=0)
        # This matches v0-25-1 behavior where all bones had rotation=0
        eb.tail = eb.head + Vector((0, DEFAULT_LENGTH, 0))

        eb.roll   = 0.0
        created[idx] = (eb, bone_name)  # Store tuple of (edit_bone, safe_name)

    for bone in bones:
        idx = bone['index']
        p   = bone['parent_idx']
        if p is not None and p in created:
            created[idx][0].parent      = created[p][0]
            dist = (created[idx][0].head - created[p][0].tail).length
            created[idx][0].use_connect = dist < 0.05

    bpy.ops.object.mode_set(mode='OBJECT')

    # ── Custom properties ─────────────────────────────────────────────────────
    for bone in bones:
        safe_name = unique_names[bone['index']]
        bbone = arm_data.bones[safe_name]
        bbone['fe_bone_index']      = bone['index']
        bbone['fe_bone_flags']      = bone.get('bone_flags', 0x180)
        bbone['fe_pos_source']      = bone.get('pos_source', 'A')
        bbone['fe_bind_matrix_hex'] = bone.get('bind_matrix_hex', '')
        bbone['fe_raw_rec_hex']     = bone.get('raw_rec_hex', '')
        bbone['fe_local_rot_deg']  = bone.get('local_rot_deg', (0.0, 0.0, 0.0))
        bbone['fe_original_name']   = bone['name']
        bbone['fe_original_bone_id'] = bone['index']

    # ── Pose bone transforms ───────────────────────────────────────────────────
    # Apply the difference between true world position and naive rest-pose position
    # as pose bone location (in bone local space = world space for unrotated bones).
    # Apply local_rot_deg for Class B bones as pose bone XYZ Euler rotation.
    # This means clearing the pose shows the raw skeleton matching the mesh,
    # while the pose shows anatomically correct positions.
    arm_obj.animation_data_create()
    for bone in bones:
        safe_name = bone['name']
        if len(safe_name) > 50:
            if '|' in safe_name:
                parts = safe_name.split('|', 1)
                safe_name = parts[1]
            if len(safe_name) > 44:
                safe_name = safe_name[-44:]
            safe_name = "_edit_" + safe_name

        pbone = arm_obj.pose.bones.get(safe_name)
        if pbone is None:
            continue

        pbone.rotation_mode = 'XYZ'

        # Location: pose_location (only for Class A with direct B parent and Class B with direct A parent)
        loc = bone.get('pose_location', (0.0, 0.0, 0.0))
        if any(abs(v) > 1e-6 for v in loc):
            pbone.location = Vector(loc)

        # Rotation: ONLY Class A bones with direct B parent get non-zero rotation
        # (combined B ancestor rotations)
        # All other bones have rotation = (0,0,0)
        par = bone.get('parent_idx')
        parent_is_b = par is not None and bones[par]['pos_source'] == 'B' if par is not None else False
        
        if bone.get('pos_source') == 'A' and parent_is_b:
            # Class A with direct B parent: use combined pose_rotation
            rot = bone.get('pose_rotation', (0.0, 0.0, 0.0))
        else:
            # All other bones: no rotation (0,0,0)
            rot = (0.0, 0.0, 0.0)
        
        # Apply rotation (in radians)
        if any(abs(d) > 1e-6 for d in rot):
            pbone.rotation_euler = Euler(
                (math.radians(rot[0]),
                 math.radians(rot[1]),
                 math.radians(rot[2])), 'XYZ'
            )

        # Store pose transform custom properties on pose bone
        pbone['fe_bone_index'] = bone.get('index', idx)
        pbone['fe_bone_flags'] = bone.get('bone_flags', 0x180)
        pbone['fe_pose_location'] = bone.get('pose_location', (0.0, 0.0, 0.0))
        pbone['fe_pose_rotation'] = bone.get('pose_rotation', (0.0, 0.0, 0.0))
        
        # Store original transrot (local_rot_deg from bone record) - before rewriting
        # This is useful for animation export/import adjustments
        pbone['fe_original_transrot'] = bone.get('local_rot_deg', (0.0, 0.0, 0.0))

    print(f"  Armature '{obj_name}' created.")
    print(f"  Stored on all bones: fe_bone_index, fe_bone_flags, "
          f"fe_pos_source, fe_bind_matrix_hex")
    
    # Store the skeleton filepath if provided (for auto-filling reference skeleton in exports)
    if skeleton_filepath:
        arm_obj['fe_skeleton_filepath'] = skeleton_filepath
        print(f"  Stored skeleton filepath: {skeleton_filepath}")
    
    return arm_obj


# =============================================================================
# ANIMATION (.ga) — READING
# =============================================================================

def read_ga_file(filepath):
    """Parse a .ga animation file.  Returns a dict with all data + raw bytes."""
    with open(filepath, 'rb') as f:
        raw = f.read()

    def ru4(o): return struct.unpack_from('>I', raw, o)[0]
    def rs2(o): return struct.unpack_from('>h', raw, o)[0]
    def ru2(o): return struct.unpack_from('>H', raw, o)[0]

    print(f"\n=== READING ANIMATION: {os.path.basename(filepath)} ===")
    print(f"  File size: {len(raw)} bytes")

    footer_ptr       = ru4(0x00)
    game_flag        = raw[0x08]
    byte_0f          = raw[0x0F]
    loop_flag        = ru4(0x10)
    start_frame      = ru4(0x14)
    end_frame        = ru4(0x18)
    bone_table_count = ru4(0x1C)
    ptr_bone_table   = ru4(0x20)
    ptr_metadata     = ru4(0x24)
    ptr_unknown      = ru4(0x28)
    ptr_frame_data   = ru4(0x2C)

    game_str = 'FE10' if game_flag == 1 else 'FE9'
    print(f"  Game: {game_str},  frames {start_frame}–{end_frame},  "
          f"{bone_table_count} bone table entries")

    bone_table = []
    pos = ptr_bone_table
    for i in range(bone_table_count):
        bone_id      = ru4(pos + 0x00)
        channel_mask = ru4(pos + 0x04)
        meta_start   = ru4(pos + 0x08)
        meta_count   = ru4(pos + 0x0C)
        bone_table.append({'bone_id': bone_id, 'channel_mask': channel_mask,
                           'meta_start': meta_start, 'meta_count': meta_count})
        pos += 0x10

    total_meta = 0
    if bone_table:
        last       = bone_table[-1]
        total_meta = last['meta_start'] + last['meta_count']

    metadata = []
    pos = ptr_metadata
    for i in range(total_meta):
        channel_type = raw[pos + 0x01]
        curve_type   = raw[pos + 0x02]
        last_frame   = ru2(pos + 0x04)
        num_kf       = ru2(pos + 0x06)
        fd_start     = ru4(pos + 0x08)
        metadata.append({
            'b0':            raw[pos + 0x00],
            'channel_type':  channel_type,
            'curve_type':    curve_type,
            'b3':            raw[pos + 0x03],
            'last_frame':    last_frame,
            'num_keyframes': num_kf,
            'fd_start_idx':  fd_start,
        })
        pos += 0x0C

    max_fd_end = 0
    for m in metadata:
        end = m['fd_start_idx'] + m['num_keyframes']
        if end > max_fd_end:
            max_fd_end = end

    frame_data = []
    pos = ptr_frame_data
    for i in range(max_fd_end):
        frame_num = ru2(pos)
        value     = rs2(pos + 2)
        frame_data.append({'frame': frame_num, 'value': value})
        pos += 4

    print(f"  Bone table: {len(bone_table)} entries")
    print(f"  Metadata:   {len(metadata)} entries")
    print(f"  Frame data: {len(frame_data)} keyframe entries")
    if footer_ptr:
        print(f"  Footer pointer @ 0x{footer_ptr:X}")

    return {
        'footer_ptr':        footer_ptr,
        'game_flag':         game_flag,
        'byte_0f':           byte_0f,
        'loop_flag':         loop_flag,
        'start_frame':       start_frame,
        'end_frame':         end_frame,
        'bone_table_count':  bone_table_count,
        'ptr_bone_table':    ptr_bone_table,
        'ptr_metadata':      ptr_metadata,
        'ptr_unknown':       ptr_unknown,
        'ptr_frame_data':    ptr_frame_data,
        'bone_table':        bone_table,
        'metadata':          metadata,
        'frame_data':        frame_data,
        'raw_hex':           raw.hex(),
    }


# =============================================================================
# ANIMATION (.ga) — IMPORT INTO BLENDER
# =============================================================================

def import_ga_to_blender(context, ga_data, armature_obj, action_name):
    """Create a Blender Action from parsed .ga data and apply it to *armature_obj*."""
    arm = armature_obj

    bone_id_to_name = {}
    for bone in arm.data.bones:
        idx = bone.get('fe_bone_index')
        if idx is not None:
            bone_id_to_name[int(idx)] = bone.name

    if not bone_id_to_name:
        print("  Warning: no fe_bone_index on armature bones.")
        skel_path = find_skeleton_file(context.scene.get('ga_skeleton_hint', ''))
        if skel_path:
            for b in read_skeleton_file(skel_path):
                bone_id_to_name[b['index']] = _safe_bone_name(b['name'])

    action = bpy.data.actions.new(name=action_name)
    arm.animation_data_create()
    arm.animation_data.action = action

    action['ga_raw_hex']      = ga_data['raw_hex']
    action['ga_game_flag']    = ga_data['game_flag']
    action['Start Frame']  = ga_data['start_frame']
    action['End Frame']    = ga_data['end_frame']
    action['ga_loop_flag']    = ga_data['loop_flag']

    context.scene.frame_start = int(ga_data['start_frame'])
    context.scene.frame_end   = int(ga_data['end_frame'])
    context.scene.frame_set(int(ga_data['start_frame']))

    for pb in arm.pose.bones:
        pb.rotation_mode = 'XYZ'

    fcurves = _get_fcurves(action, arm, ensure=True)
    if fcurves is None:
        print("  ERROR: could not obtain FCurves collection.")
        return action

    curves_created = 0
    bones_missing  = set()
    b2_map         = {}

    for bt in ga_data['bone_table']:
        bone_id   = bt['bone_id']
        bone_name = bone_id_to_name.get(bone_id)
        if bone_name is None:
            bones_missing.add(bone_id)
            continue
        arm.data.bones[bone_name]['fe_ga_animated'] = True

        # ── Pass 1: decode all channels for this bone ──────────────────────
        _bone_channels = []  # list of (ch_type, arr_idx, b2, frames_and_vals, prop_name, data_path)

        for mi in range(bt['meta_start'], bt['meta_start'] + bt['meta_count']):
            meta         = ga_data['metadata'][mi]
            channel_type = meta['channel_type']
            b2           = meta['curve_type']

            ch_info = _GA_CHANNEL.get(channel_type)
            if ch_info is None:
                continue

            prop_name, arr_idx, _label = ch_info

            num_kf   = meta['num_keyframes']
            fd_start = meta['fd_start_idx']
            if num_kf == 0:
                continue

            data_path = f'pose.bones["{bone_name}"].{prop_name}'

            b2_key = f"{bone_name}.{prop_name}[{arr_idx}]"
            b2_map[b2_key] = b2

            frames_and_vals = []
            for ki in range(num_kf):
                fd_idx = fd_start + ki
                if fd_idx >= len(ga_data['frame_data']):
                    break
                fd = ga_data['frame_data'][fd_idx]
                frames_and_vals.append(
                    (float(fd['frame']),
                     _ga_decode(channel_type, fd['value'], b2))
                )

            if not frames_and_vals:
                continue

            _bone_channels.append((channel_type, arr_idx, b2, frames_and_vals, prop_name, data_path))

        # ── Pass 2: create FCurves from decoded data ───────────────────────
        for channel_type, arr_idx, b2, frames_and_vals, prop_name, data_path in _bone_channels:
            fcurve = fcurves.find(data_path, index=arr_idx)
            if fcurve is None:
                fcurve = fcurves.new(data_path, index=arr_idx)

            use_bezier = (b2 != 0x0F)

            actual_kf = len(frames_and_vals)
            fcurve.keyframe_points.add(actual_kf)
            for ki, (frame_num, blender_val) in enumerate(frames_and_vals):
                kp           = fcurve.keyframe_points[ki]
                kp.co        = (frame_num, blender_val)
                if use_bezier:
                    kp.interpolation      = 'BEZIER'
                    kp.handle_left_type   = 'AUTO_CLAMPED'
                    kp.handle_right_type  = 'AUTO_CLAMPED'
                else:
                    kp.interpolation = 'LINEAR'

            fcurve.update()
            curves_created += 1

    # Write ga_b2_<ch> custom properties directly onto each pose bone so that
    # B2 values are available for constraint-transfer and from-scratch workflows.
    b2_prop_written = 0
    for (bone_name_key, prop_name_key, arr_idx_key), b2_val in [
        ((k.split('.')[0], k.split('.')[1].split('[')[0], int(k.split('[')[1].rstrip(']'))), v)
        for k, v in b2_map.items()
    ]:
        # Resolve channel_type from (prop_name, arr_idx) → find matching CH_TO_B2_PROP key
        ch_prop = None
        for ch_int, ch_name in CH_TO_B2_PROP.items():
            ch_info = _GA_CHANNEL.get(ch_int)
            if ch_info and ch_info[0] == prop_name_key and ch_info[1] == arr_idx_key:
                ch_prop = ch_name
                break
        if ch_prop is None:
            continue
        pbone = arm.pose.bones.get(bone_name_key)
        if pbone is not None:
            pbone[ch_prop] = b2_val
            b2_prop_written += 1
    print(f"  Wrote {b2_prop_written} ga_b2_* properties to pose bones "
          f"(0 means bone name mismatch or no pose bones matched)")

    if bones_missing:
        print(f"  Warning: bone IDs not in armature: {sorted(bones_missing)}")
    print(f"  Created {curves_created} FCurves in action '{action_name}'")
    return action


# =============================================================================
# ANIMATION (.ga) — EXPORT FROM BLENDER
# =============================================================================

def _rebase_footer(raw_orig, game_flag, new_footer_offset):
    """Rebase absolute pointers in the footer block for a .ga file.

    When the animation data section changes size (different keyframe count,
    bone count, etc.), the footer block containing absolute file offsets
    must be patched so pointers reference the correct positions in the
    newly-built file.

    Returns the complete footer byte string (pointer block + FD data) with
    corrected pointers, suitable for appending at *new_footer_offset*.
    """
    filesize = len(raw_orig)
    orig_hdr_ptr = struct.unpack_from('>I', raw_orig, 0)[0]
    if orig_hdr_ptr == 0 or orig_hdr_ptr >= filesize:
        return b''

    is_fe10 = (game_flag == 1)

    if not is_fe10:
        # ── FE9 footer ──────────────────────────────────────────────────
        # Layout at orig_hdr_ptr:
        #   [Footer Pointer 1 (4)]  = absolute offset to FD1
        #   [padding (0x24 bytes)]  = zeros
        #   [FD1 data (variable)]
        # Footer Pointer 1 must be rebased to new_footer_offset + 0x28.
        footer_data = bytes(raw_orig[orig_hdr_ptr:])
        if len(footer_data) < 4:
            return b''
        ptr1 = struct.unpack_from('>I', footer_data, 0)[0]
        if ptr1 == 0:
            return footer_data
        # Rebase: new FD1 offset = new_footer_offset + 0x28
        ptr1_new = new_footer_offset + 0x28
        out = bytearray(footer_data)
        struct.pack_into('>I', out, 0, ptr1_new)
        return bytes(out)

    # ── FE10 footer ─────────────────────────────────────────────────────
    # orig_hdr_ptr points to the middle of a pointer block 0x0c bytes
    # before EOF (single section) or earlier (dual section).
    # The FD data lives BEFORE the pointer block.
    #
    # Single section layout (0x0c byte pointer block):
    #   [ftr_ID (4)] [ftr_ptr (4)] [padding (4)]
    #   FD data: from ftr_ptr to orig_hdr_ptr
    #
    # Dual section layout (0x18 byte pointer block):
    #   ... [ftr_ID_1 (4)] [ftr_ptr_1 (4)] [padding (4)] [ftr_ID_2 (4)] [ftr_ptr_2 (4)] [ftr_ptr_3 (4)]
    #   FD1: from ftr_ptr_1 to ftr_ptr_2
    #   FD2: from ftr_ptr_2 to ftr_ID_1
    #   orig_hdr_ptr points to ftr_ID_2

    # Determine structure from the last 4 bytes of the file
    last_4 = struct.unpack_from('>I', raw_orig, filesize - 4)[0] if filesize >= 4 else 0
    has_dual = (last_4 != 0)

    if not has_dual:
        # Single section: pointer block is 0x0c bytes
        ptr_block_start = filesize - 0x0c
    else:
        # Dual section
        # ftr_ptr_3 (at orig_hdr_ptr + 8) points to ftr_ID_1
        ftr_ptr_3 = struct.unpack_from('>I', raw_orig, orig_hdr_ptr + 8)[0]
        if ftr_ptr_3 >= filesize:
            return b''
        ptr_block_start = ftr_ptr_3

    if ptr_block_start < orig_hdr_ptr:
        return b''

    # Grab everything from the start of the pointer block to EOF
    footer_data = bytes(raw_orig[ptr_block_start:])
    old_ptr_block_start = ptr_block_start
    delta = new_footer_offset - old_ptr_block_start

    # Known pointer block layouts for FE10:
    #   Single (0x0c):  [ftr_ID (4)] [ftr_ptr (4)] [padding (4)]
    #   Dual   (0x18):  [ftr_ID_1 (4)] [ftr_ptr_1 (4)] [padding (4)]
    #                   [ftr_ID_2 (4)] [ftr_ptr_2 (4)] [ftr_ptr_3 (4)]
    # Only specific byte positions contain absolute file offsets.
    if has_dual:
        offset_offsets = [4, 16, 20]
    else:
        offset_offsets = [4]

    out = bytearray(footer_data)
    for pos in offset_offsets:
        if pos + 4 > len(out):
            continue
        val = struct.unpack_from('>I', out, pos)[0]
        if val != 0:
            new_val = val + delta
            struct.pack_into('>I', out, pos, new_val)

    return bytes(out)


def export_ga_from_blender(armature_obj, action, filepath):
    """Rebuild a .ga binary from scratch from the Blender Action's FCurves.

    B2 (GQR scale exponent) is always computed from FCurve value ranges.
    Rotation channels (ch 3-5) use degrees for B2 computation since the
    .ga encode formula operates on degrees.
    """
    import json as _json

    game_flag   = int(action.get('ga_game_flag',   0))
    byte_0f     = 0x11
    loop_flag   = int(action.get('ga_loop_flag', action.get('ga_skip_flag', 0)))
    ptr_unknown = 0
    start_frame = int(action.get('Start Frame', 1))
    end_frame   = int(action.get('End Frame',   bpy.context.scene.frame_end))

    footer_data = b''
    raw_orig = None
    if 'ga_raw_hex' in action:
        try:
            raw_orig = bytes.fromhex(str(action['ga_raw_hex']))
            orig_hdr_ptr = struct.unpack_from('>I', raw_orig, 0)[0]
            if orig_hdr_ptr != 0 and orig_hdr_ptr < len(raw_orig):
                # For FE9, everything from orig_hdr_ptr to EOF is the footer.
                # For FE10, FD data sits before the pointer block; capture
                # from the start of the full footer region to EOF.
                if game_flag == 1:
                    # FE10: determine footer span from pointer layout
                    fs = len(raw_orig)
                    last_4 = struct.unpack_from('>I', raw_orig, fs - 4)[0] if fs >= 4 else 0
                    if last_4 == 0:
                        ft = struct.unpack_from('>I', raw_orig, orig_hdr_ptr + 4)[0]
                        if 0 < ft < orig_hdr_ptr:
                            footer_data = bytes(raw_orig[ft:])
                    else:
                        ftr_ptr_3 = struct.unpack_from('>I', raw_orig, orig_hdr_ptr + 8)[0]
                        if 0 < ftr_ptr_3 < orig_hdr_ptr:
                            footer_data = bytes(raw_orig[ftr_ptr_3:])
                else:
                    footer_data = bytes(raw_orig[orig_hdr_ptr:])
        except Exception:
            pass

    fcurves = _get_fcurves(action, armature_obj, ensure=False)
    if not fcurves:
        print("  ERROR: no FCurves found on action.")
        print(f"  DEBUG: _get_fcurves returned {fcurves}")
        return False

    print(f"  DEBUG: Found {len(fcurves)} FCurves total in _get_fcurves result")
    for i, fc in enumerate(fcurves):
        if i >= 10: break
        print(f"  DEBUG:   FCurve {i}: data_path='{fc.data_path}', array_index={fc.array_index}, keyframes={len(fc.keyframe_points)}")

    # Build a robust FCurve lookup dict by iterating actual FCurves.
    # This avoids relying on fcurves.find() which behaves differently
    # between Blender 4.x (action.fcurves) and 5.0+ (channelbag.fcurves).
    fcurve_lookup = {}
    for fc in fcurves:
        fcurve_lookup[(fc.data_path, fc.array_index)] = fc
    print(f"  DEBUG: fcurve_lookup has {len(fcurve_lookup)} entries")

    bone_id_to_name = {}
    for bone in armature_obj.data.bones:
        idx   = bone.get('fe_bone_index')
        flags = int(bone.get('fe_bone_flags', 0x180))
        if idx is None:
            continue
        if (flags & 0x180) == 0 and (flags & 0x02) == 0:   # non-animated Class B (solver/root, e.g. 0x24, 0x00)
            continue
        bone_name = bone.name
        # Check each channel type directly to identify which ones match
        matching_channels = []
        for info in _GA_CHANNEL.values():
            data_path = f'pose.bones["{bone_name}"].{info[0]}'
            arr_idx = info[1]
            if (data_path, arr_idx) in fcurve_lookup:
                matching_channels.append(f"{info[2]} (idx={arr_idx})")
        if not matching_channels:
            continue
        bone_id_to_name[int(idx)] = bone_name
        print(f"  DEBUG: Bone '{bone_name}' idx={idx} flags=0x{flags:X} matched {len(matching_channels)} channels: {matching_channels}")

    print(f"  DEBUG: {len(bone_id_to_name)} bones passed the FCurve check ({len(armature_obj.data.bones)} total bones in armature)")

    bone_channels = defaultdict(list)
    resolved_b2_map = {}

    for bone_id in sorted(bone_id_to_name.keys()):
        bone_name = bone_id_to_name[bone_id]
        for channel_type in sorted(_GA_CHANNEL.keys()):
            prop_name, arr_idx, _ = _GA_CHANNEL[channel_type]
            data_path = f'pose.bones["{bone_name}"].{prop_name}'
            fcurve    = fcurve_lookup.get((data_path, arr_idx))
            if fcurve is None or not fcurve.keyframe_points:
                continue

            b2_key = f"{bone_name}.{prop_name}[{arr_idx}]"

            # B2 is always computed from FCurve value ranges
            encode_vals = [kp.co[1] for kp in fcurve.keyframe_points]
            if 3 <= channel_type <= 5:
                encode_vals = [v * (180.0 / math.pi) for v in encode_vals]
            b2 = _compute_b2(encode_vals)


            # ── Encode keyframe pairs ─────────────────────────────────────
            # Euler wrapping is applied here at encode time, separate from the
            # B2 lookup above so that the two concerns do not interfere.
            kf_pairs = []
            for kp in fcurve.keyframe_points:
                fn  = int(round(kp.co[0]))
                val = kp.co[1]
                kf_pairs.append((fn, _ga_encode(channel_type, val, b2)))

            if not kf_pairs:
                continue

            # Deduplicate by frame number (last value wins)
            seen = {}
            for fn, s16 in kf_pairs:
                seen[fn] = s16
            kf_pairs = sorted(seen.items())

            bone_channels[bone_id].append({
                'channel_type': channel_type,
                'curve_type':   b2,
                'kf_pairs':     kf_pairs,
            })
            resolved_b2_map[b2_key] = b2

    if not bone_channels:
        print("  ERROR: no animated channels found.")
        return False

    # Write resolved B2 values back to the exported action for post-export
    # verification in the Action Editor custom properties.
    action['ga_b2_map'] = _json.dumps(resolved_b2_map)
    print(f"  Resolved B2 map written to action '{action.name}' "
          f"({len(resolved_b2_map)} channels)")

    # ── Pack binary sections ──────────────────────────────────────────────────

    bone_table_entries = []
    meta_entries       = []
    fd_entries         = []
    meta_idx = 0
    fd_idx   = 0

    for bone_id in sorted(bone_channels.keys()):
        channels = bone_channels[bone_id]

        channel_mask = 0
        for ch in channels:
            b1 = ch['channel_type']
            if   0x00 <= b1 <= 0x02: channel_mask |= 0x08
            elif 0x03 <= b1 <= 0x05: channel_mask |= 0x10
            else:                    channel_mask |= 0x20

        meta_start = meta_idx
        for ch in channels:
            kfs        = ch['kf_pairs']
            last_frame = kfs[-1][0]
            meta_entries.append({
                'channel_type':  ch['channel_type'],
                'curve_type':    ch['curve_type'],
                'last_frame':    last_frame,
                'num_keyframes': len(kfs),
                'fd_start_idx':  fd_idx,
            })
            fd_entries.extend(kfs)
            meta_idx += 1
            fd_idx   += len(kfs)

        bone_table_entries.append({
            'bone_id':      bone_id,
            'channel_mask': channel_mask,
            'meta_start':   meta_start,
            'meta_count':   len(channels),
        })

    n_bones = len(bone_table_entries)
    n_meta  = len(meta_entries)
    n_fd    = len(fd_entries)

    PTR_BONE_TABLE = 0x30
    ptr_metadata   = PTR_BONE_TABLE + n_bones * 0x10
    ptr_frame_data = ptr_metadata   + n_meta  * 0x0C
    main_data_end  = ptr_frame_data + n_fd    * 0x04
    footer_ptr     = main_data_end if footer_data else 0

    out = bytearray()

    out += struct.pack('>I', footer_ptr)
    out += struct.pack('>I', 0)
    out += bytes([game_flag])
    out += bytes(6)
    out += bytes([byte_0f])
    out += struct.pack('>I', loop_flag)
    out += struct.pack('>I', start_frame)
    out += struct.pack('>I', end_frame)
    out += struct.pack('>I', n_bones)
    out += struct.pack('>I', PTR_BONE_TABLE)
    out += struct.pack('>I', ptr_metadata)
    out += struct.pack('>I', ptr_unknown)
    out += struct.pack('>I', ptr_frame_data)
    assert len(out) == 0x30, f"Header size error: {len(out)}"

    for bt in bone_table_entries:
        out += struct.pack('>IIII',
                           bt['bone_id'], bt['channel_mask'],
                           bt['meta_start'], bt['meta_count'])

    for m in meta_entries:
        out += struct.pack('BB',  0x00, m['channel_type'])
        out += struct.pack('BB',  m['curve_type'], 0x00)
        out += struct.pack('>HH', m['last_frame'], m['num_keyframes'])
        out += struct.pack('>I',  m['fd_start_idx'])

    for fn, s16 in fd_entries:
        out += struct.pack('>Hh', fn, s16)

    if footer_data and raw_orig is not None:
        rebased = _rebase_footer(raw_orig, game_flag, main_data_end)
        out += rebased
    elif footer_data:
        out += footer_data

    action['ga_raw_hex'] = out.hex()

    with open(filepath, 'wb') as f:
        f.write(out)

    print(f"\n=== EXPORTED ANIMATION (full rebuild): {os.path.basename(filepath)} ===")
    print(f"  {len(out)} bytes  |  {n_bones} bones  |  "
          f"{n_meta} channels  |  {n_fd} keyframes")
    return True


# =============================================================================
# MESH (.gs) — READING
# =============================================================================
#
# v11 additions:
#   - Reads material table from header[0x54] (addrs[4]).
#   - Records per-chunk material index (byte at chunk+0x0B).
#   - Tracks which faces came from which chunk, for material slot export.
#   - Returns 'materials', 'face_mat_indices', 'chunk_list_addr',
#     'chunk_face_starts', 'chunk_face_counts', 'chunk_mat_indices'.
#
# .gs POINTER CONVENTION (applies throughout this file):
#   All pointer values stored in the file are RAW (runtime - 0x20).
#   To resolve a raw pointer to a file byte offset, add base_offset (0x20).
#   The relocation table tells the game loader which fields to apply +0x20 to.

def read_gs_file(filepath, bones=None):
    """Read and parse a .gs mesh file."""
    with open(filepath, 'rb') as f:
        data = f.read()

    print(f"\n=== READING .GS FILE === ({len(data)} bytes)")

    base_offset    = 0x20
    addrs_relative = [struct.unpack('>I', data[0x44+i*4:0x48+i*4])[0] for i in range(10)]
    addrs          = [a + base_offset if a > 0 else 0 for a in addrs_relative]
    nums           = [struct.unpack('>H', data[0x6C+i*2:0x6E+i*2])[0] for i in range(8)]
    vert_scale     = 1 << data[0x7C]
    norm_scale     = 1 << data[0x7D]
    uv_scale       = 1 << data[0x7E]
    
    # v24.6: Debug - print all header addresses
    # addr_names = ['verts', 'normals', 'uvs', 'colors', 'materials', '??5', '??6', '??7', '??8', 'composite']
    # print(f"  Header addrs: " + ", ".join(f"{addr_names[i]}@{addrs_relative[i]:X}" for i in range(10)))
    # print(f"  Header nums:  " + ", ".join(f"{addr_names[i]}={nums[i]}" for i in range(8)))

    # ── Palette reader ────────────────────────────────────────────────────────
    def _read_chunk_palette(chunk_entry_ptr):
        """Read the GX-cache bone palette for a chunk.

        Palette block layout at GX cache offset:
            byte 0:   0x10  (marker)
            byte 1:   N     (palette entry count)
            bytes 2+: N bone IDs, one byte each
        """
        rel = struct.unpack('>I', data[chunk_entry_ptr+28:chunk_entry_ptr+32])[0]
        palette_ptr = rel + base_offset
        if palette_ptr >= len(data) or data[palette_ptr] != 0x10:
            return None
        n = data[palette_ptr + 1]
        if palette_ptr + 2 + n > len(data):
            return None
        return [data[palette_ptr + 2 + i] for i in range(n)]

    # ── Gap record parser for battle models ───────────────────────────────────
    def _read_gap_records(data, cb_base):
        """Parse GX matrix streaming gap records from CB.
        
        Records at 0xb070, 0x18 bytes each.
        Count at 0xb068 = 517 records.
        
        Format:
          +0x00: bone_a1 (uint16)
          +0x02: bone_b1 (uint16)
          +0x10: bone_a2 (uint16)
          +0x12: bone_b2 (uint16)
        
        Each record covers ~6.35 vertices.
        Returns list of (bone_a, bone_b, vertex_start) for each record.
        """
        # If cb_base is 0, scan for CB marker (0x10) starting at known offset 0xB000
        if not cb_base:
            cb_base = 0xB060  # Default CB location for battle models
        
        # Find CB sub-header by scanning for 0x10 marker
        cb_start = cb_base
        found = False
        for offset in range(0, 0x100, 4):
            if cb_start + offset + 4 > len(data):
                break
            val = struct.unpack('>I', data[cb_start+offset:cb_start+offset+4])[0]
            if val == 0x10:
                cb_start = cb_start + offset
                found = True
                break
        
        if not found:
            return []
        
        # Get record count from header at cb_start + 8
        # Format: +0x08 uint16 record_count, uint16 vertex_count
        record_count = struct.unpack('>H', data[cb_start+8:cb_start+10])[0]
        vertex_count = struct.unpack('>H', data[cb_start+0xA:cb_start+0xC])[0]
        
        if record_count == 0:
            return []
        
        # First record offset = first 4 bytes of header (cb_start + 0)
        rec_offset = struct.unpack('>I', data[cb_start:cb_start+4])[0]
        gap_start = cb_start + rec_offset
        
        record_size = 0x18
        
        verts_per_record = vertex_count / record_count
        
        mappings = []
        
        for i in range(record_count):
            off = gap_start + i * record_size
            if off + record_size > len(data):
                break
            rec = data[off:off+record_size]
            
            # Get bone pairs from both positions
            bone_a1 = struct.unpack('>H', rec[0:2])[0]
            bone_b1 = struct.unpack('>H', rec[2:4])[0]
            bone_a2 = struct.unpack('>H', rec[0x10:0x12])[0]
            bone_b2 = struct.unpack('>H', rec[0x12:0x14])[0]
            
            # Calculate vertex range
            vert_start = int(i * verts_per_record)
            
            # Use first bone pair (child, parent)
            mappings.append((bone_a1, bone_b1, vert_start))
        
        # v24.6 debug
        print(f"  [GAP] Parsed {len(mappings)} records from 0x18-byte format at 0x{gap_start:X}")
        
        return mappings

    # ── Vertex arrays ─────────────────────────────────────────────────────────
    vertices = []
    if addrs[0] and nums[0]:
        pos = addrs[0]
        for _ in range(nums[0]):
            x = struct.unpack('>h', data[pos:pos+2])[0] / vert_scale
            y = struct.unpack('>h', data[pos+2:pos+4])[0] / vert_scale
            z = struct.unpack('>h', data[pos+4:pos+6])[0] / vert_scale
            vertices.append((x, y, z))
            pos += 6

    normals = []
    if addrs[1] and nums[1]:
        pos = addrs[1]
        for _ in range(nums[1]):
            x = struct.unpack('>b', data[pos:pos+1])[0]   / norm_scale
            y = struct.unpack('>b', data[pos+1:pos+2])[0] / norm_scale
            z = struct.unpack('>b', data[pos+2:pos+3])[0] / norm_scale
            normals.append((x, y, z))
            pos += 3

    uvs = []
    if addrs[2] and nums[2]:
        pos = addrs[2]
        for _ in range(nums[2]):
            u = struct.unpack('>h', data[pos:pos+2])[0]   / uv_scale
            v = struct.unpack('>h', data[pos+2:pos+4])[0] / uv_scale
            uvs.append((u, 1.0 - v))  # Flip V coordinate
            pos += 4

    colors = []
    if addrs[3] and nums[3]:
        pos = addrs[3]
        for _ in range(nums[3]):
            colors.append([data[pos+j] for j in range(4)])
            pos += 4

    # ── Composite vertex buffer ────────────────────────────────────────────────
    comp_vertices = []; comp_normals = []; use_composite = False
    cb_base = 0  # Store CB base for gap record lookup
    
    # v24.6: Find CB via header pointer at 0x68
    raw_cb_ptr = struct.unpack('>I', data[0x68:0x6C])[0]
    cb_header = raw_cb_ptr + 0x20 if raw_cb_ptr > 0 else 0
    
    if cb_header > 0 and len(data) > cb_header + 0x10:
        cb_magic = struct.unpack('>I', data[cb_header:cb_header+4])[0]
        if cb_magic == 0x10:
            cb_base = cb_header
            # Vertex offset = +0x04 (uint32)
            addr_verts = struct.unpack('>I', data[cb_base+4:cb_base+8])[0]
            # Vertex count = +0x0A (uint16)
            num_verts = struct.unpack('>H', data[cb_base+0xA:cb_base+0xC])[0]
            if num_verts > 0 and addr_verts > 0:
                CS = 256
                vp = cb_base + addr_verts  # vertex data offset from CB header
                for _ in range(num_verts):
                    x  = struct.unpack('>h', data[vp:vp+2])[0]    / CS
                    y  = struct.unpack('>h', data[vp+2:vp+4])[0]  / CS
                    z  = struct.unpack('>h', data[vp+4:vp+6])[0]  / CS
                    nx = struct.unpack('>h', data[vp+6:vp+8])[0]  / CS
                    ny = struct.unpack('>h', data[vp+8:vp+10])[0] / CS
                    nz = struct.unpack('>h', data[vp+10:vp+12])[0]/ CS
                    comp_vertices.append((x, y, z))
                    comp_normals.append((nx, ny, nz))
                    vp += 12
                use_composite = True
                print(f"  [CB] Loaded {num_verts} composite vertices from 0x{cb_base:X}")
    
    # Fallback: check header[0x64] for composite buffer (older format)
    if not use_composite and addrs[9]:
        pos        = addrs[9]
        addr_verts = struct.unpack('>I', data[pos+4:pos+8])[0]
        num_verts  = struct.unpack('>H', data[pos+10:pos+12])[0]
        CS = 256
        # CS = 0x800
        vp = addrs[9] + addr_verts
        for _ in range(num_verts):
            x  = struct.unpack('>h', data[vp:vp+2])[0]    / CS
            y  = struct.unpack('>h', data[vp+2:vp+4])[0]  / CS
            z  = struct.unpack('>h', data[vp+4:vp+6])[0]  / CS
            nx = struct.unpack('>h', data[vp+6:vp+8])[0]  / CS
            ny = struct.unpack('>h', data[vp+8:vp+10])[0] / CS
            nz = struct.unpack('>h', data[vp+10:vp+12])[0]/ CS
            comp_vertices.append((x, y, z))
            comp_normals.append((nx, ny, nz))
            vp += 12
        use_composite = True

    reg_v = vertices; reg_n = normals

    # ── v25.0: GAP RECORD SKINNING IMPLEMENTATION ────────────────────────────────
    # 
    # NEW APPROACH: Use gap records to skin to Reference bones
    # 
    # Gap records are stored at CB header + 0x10 (0xB070 for smf1.gs)
    # Each record is 0x18 bytes:
    #   +0x00: bone_a (uint16) - primary bone
    #   +0x02: bone_b (uint16) - secondary bone  
    #   +0x04: bone_c (uint16) - third bone
    #   +0x06: bone_d (uint16) - fourth bone (65535 = none)
    #   +0x08: weights[4] (int8) - influence weights
    #   +0x0C: iterator (increments by 32)
    #   +0x10: unknown
    #   +0x14: vertex_count (uint16) - how many vertices this record applies to
    # 
    # Key insight: Gap records apply to unique vertices in FIRST-APPEARANCE order
    # from ALL display lists (globally, not per-chunk).
    #
    # Implementation:
    # 1. First pass: collect unique CB vertex indices in global first-appearance order
    # 2. Build gap_mapping: apply gap records sequentially to ordered vertices
    # 3. Apply: use gap_mapping bone for covered vertices, fallback to slot_idx
    # ───────────────────────────────────────────────────────────────────────────────

    # ── Chunk descriptors ──────────────────────────────────────────────────────
    #
    # Each chunk descriptor is 32 bytes at a contiguous offset:
    #   +0x00  uint32  raw ptr → PtrA (per-chunk AABB + bone name + slot index)
    #   +0x04  uint32  raw ptr → next chunk (0 = last chunk)
    #   +0x08  uint8   primitive type  (0x30 = tri list, 0x38 = tri strip)
    #   +0x09  uint8   vertex format   (0x02 or 0x0E)
    #   +0x0A  uint8   0x00
    #   +0x0B  uint8   *** MATERIAL INDEX ***  ← read by v11
    #   +0x0C  uint32  0x00000000
    #   +0x10  uint32  0x00004601 (vertex attribute flags)
    #   +0x14  uint32  raw ptr → display list data
    #   +0x18  uint32  display list data size in bytes
    #   +0x1C  uint32  raw ptr → GX cache (bone palette)
    #
    # addrs[4] = header[0x54] resolved = material table start
    # addrs[5] = header[0x58] resolved = first PtrA block
    # addrs[6] = header[0x5C] resolved = chunk list start   ← chunk_addr below

    faces         = []
    skin_weights  = {}
    face_mat_indices  = []   # v11: parallel to faces, records mat_idx per face
    chunk_face_starts = []   # v11: face index where each chunk's faces begin
    chunk_face_counts = []   # v11: how many faces came from each chunk
    chunk_mat_indices_raw = []  # v11: original mat_idx per chunk

    chunk_addr = addrs[6] or addrs[7] or addrs[8]
    chunk_processed = False

    if chunk_addr and nums[6]:
        chunk_processed = True
        pos = chunk_addr; chunks = []
        for _ in range(nums[6]):
            # v24.6: Fixed - display list pointer is at +0x14, not +0x20
            tri_raw = struct.unpack('>I', data[pos+0x14:pos+0x18])[0]
            tri_size = struct.unpack('>I', data[pos+0x18:pos+0x1C])[0]
            
            # Get slot index from PtrA (chunk entry_ptr + 0 -> PtrA block + 0x1D)
            ptr_a_raw = struct.unpack('>I', data[pos:pos+4])[0]
            ptr_a = ptr_a_raw + 0x20 if ptr_a_raw > 0 else 0
            slot_idx = data[ptr_a + 0x1D] if ptr_a > 0 and ptr_a < len(data) else 2
            
            chunks.append({
                'format':    struct.unpack('>H', data[pos+8:pos+10])[0],
                'format2':   data[pos+18],
                'tri_addr':  tri_raw + base_offset if tri_raw > 0 else 0,
                'tri_size':  tri_size,
                'entry_ptr': pos,
                'mat_idx':   data[pos + 11],
                'slot_idx':  slot_idx,
            })
            pos += 32
        
        # v24.6: Debug chunk info
        # print(f"  Chunk debug: {len(chunks)} chunks")
        # for i, c in enumerate(chunks):
        #     print(f"    Chunk {i}: tri_size={c['tri_size']}, mat_idx={c['mat_idx']}, slot={c['slot_idx']}")

        # ── v25.0: First pass - collect unique vertices in global DL order ────────
        # This must be done BEFORE chunk processing to get the correct order
        global_unique_verts_ordered = []
        global_seen_verts = set()
        
        # Also collect per-chunk vertex lists for later use
        all_chunk_verts = []
        
        for ci, chunk in enumerate(chunks):
            use_cb = (chunk['format'] & 1) != 0
            sb     = (chunk['format'] & 2) != 0
            hc     = (chunk['format2'] & 0x10) != 0
            hu     = (chunk['format2'] & 0x80) != 0
            bpv    = 6 + (1 if sb else 0) + (2 if hc else 0) + (2 if hu else 0)
            tp, te = chunk['tri_addr'], chunk['tri_addr'] + chunk['tri_size']
            
            chunk_verts_this_pass = []
            
            if tp >= len(data) or chunk['tri_size'] == 0:
                all_chunk_verts.append([])
                continue
            
            while tp < te and tp < len(data):
                if data[tp] != 0x98:
                    break
                tp += 1
                if tp + 2 > len(data):
                    break
                slen = struct.unpack('>H', data[tp:tp+2])[0]; tp += 2
                if slen > 1000:
                    break
                for _ in range(slen):
                    if tp + bpv > len(data):
                        break
                    sb_byte = 0
                    if sb:
                        sb_byte = data[tp]
                        tp += 1
                    vi = struct.unpack('>H', data[tp:tp+2])[0]; tp += 2
                    ni = struct.unpack('>H', data[tp:tp+2])[0]; tp += 2
                    if hc: tp += 2
                    ui = struct.unpack('>H', data[tp:tp+2])[0]; tp += 2
                    if hu: tp += 2
                    
                    # Add to global unique list in first-appearance order
                    if vi not in global_seen_verts:
                        global_unique_verts_ordered.append(vi)
                        global_seen_verts.add(vi)
                    
                    chunk_verts_this_pass.append(vi)
            
            # v24.6: Debug - show which vertices each chunk contains
            chunk_v_set = set(chunk_verts_this_pass)
            wing_roots_in_chunk = [v for v in [128,129,130,131,132,133,134,135] if v in chunk_v_set]
            if wing_roots_in_chunk:
                print(f"    Chunk {ci} contains wing roots: {wing_roots_in_chunk}")
            
            all_chunk_verts.append(chunk_verts_this_pass)
        
        # ── v25.0: Build gap_mapping ────────────────────────────────────────────
        # Apply gap records sequentially to CB non-null vertices in order
        # - Parse CB vertex data sequentially (0 to 3282)
        # - Skip null entries (all 12 bytes = 0x00)
        # - For each non-null vertex, apply current gap record
        # - Gap records specify count of vertices they apply to
        gap_mapping = {}  # cb_vertex_index -> bone_id
        
        if use_composite and bones is not None:
            # Use dynamically discovered CB location (from 0x68 pointer)
            cb_header = cb_base if cb_base else 0xB060
            if not cb_header:
                print("    WARNING: cb_base not set, skipping gap_mapping")
            vertex_offset = struct.unpack('>I', data[cb_header+4:cb_header+8])[0]
            num_gap_records = struct.unpack('>H', data[cb_header+0x08:cb_header+0x0A])[0]
            num_cb_verts = struct.unpack('>H', data[cb_header+0x0A:cb_header+0x0C])[0]
            vert_start = cb_header + vertex_offset
            
            # First, find all non-null CB vertex indices in order
            non_null_cb_indices = []
            for cb_idx in range(num_cb_verts):
                vpx = vert_start + cb_idx * 12
                vertex_data = data[vpx:vpx+12]
                if vertex_data != b'\x00' * 12:
                    non_null_cb_indices.append(cb_idx)
            
            print(f"  [GAP v25.0] CB declares {num_cb_verts} vertices, {len(non_null_cb_indices)} non-null")
            
            # Now apply gap records to non-null vertices in order
            gap_record_base = cb_header + 0x10
            gap_record_idx = 0
            non_null_idx = 0
            
            for i in range(num_gap_records):
                off = gap_record_base + i * 0x18
                if off + 0x18 > len(data):
                    break
                    
                bone_a = struct.unpack('>H', data[off:off+2])[0]
                bone_b = struct.unpack('>H', data[off+2:off+4])[0]
                vertex_count = struct.unpack('>H', data[off+0x14:off+0x16])[0]
                
                # Use first bone as primary (single-bone approach)
                if bone_a != 65535:
                    primary_bone = bone_a
                elif bone_b != 65535:
                    primary_bone = bone_b
                else:
                    primary_bone = 0  # Invalid
                
                # Apply to next 'vertex_count' non-null CB vertices
                for j in range(vertex_count):
                    if non_null_idx < len(non_null_cb_indices):
                        cb_vert_idx = non_null_cb_indices[non_null_idx]
                        if 0 < primary_bone < len(bones):
                            gap_mapping[cb_vert_idx] = primary_bone
                        non_null_idx += 1
                    else:
                        break
                gap_record_idx += 1
            
            # Track vertices that should fallback (null CB entries)
            null_count = num_cb_verts - len(non_null_cb_indices)
            print(f"    Gap mapping: {len(gap_mapping)} vertices mapped")
            print(f"    Null CB entries (fallback): {null_count}")
            print(f"    Gap records used: {gap_record_idx}")
        
        # ── v25.0: Debug - show gap_mapping bone distribution with X,Y ranges ──────────
        if gap_mapping and use_composite:
            bone_counts = Counter(gap_mapping.values())
            print(f"    Bones in gap_mapping: {dict(bone_counts.most_common(10))}")
            
            # Get vertex positions for X,Y range analysis
            cb_header = cb_base if cb_base else 0xB060
            vertex_offset = struct.unpack('>I', data[cb_header+4:cb_header+8])[0]
            vert_start = cb_header + vertex_offset
            CS = 256
            
            # Group vertices by bone and get X,Y ranges
            bone_vert_positions = defaultdict(list)
            for cb_idx, bone_id in gap_mapping.items():
                vpx = vert_start + cb_idx * 12
                x = struct.unpack('>h', data[vpx:vpx+2])[0] / CS
                y = struct.unpack('>h', data[vpx+2:vpx+4])[0] / CS
                bone_vert_positions[bone_id].append((x, y))
            
            print(f"    Bone X,Y ranges (for spatial clustering check):")
            for bone_id in sorted(bone_vert_positions.keys())[:10]:
                positions = bone_vert_positions[bone_id]
                xs = [p[0] for p in positions]
                ys = [p[1] for p in positions]
                bone_name = bones[bone_id]['name'] if bone_id < len(bones) else f'bone_{bone_id}'
                print(f"      Bone {bone_id} ({bone_name}): {len(positions)} verts, X=[{min(xs):.1f},{max(xs):.1f}], Y=[{min(ys):.1f},{max(ys):.1f}]")
        
        # ── v25.0: Second pass - Process chunks with gap_mapping ────────────────────
        for ci, chunk in enumerate(chunks):
            use_cb = (chunk['format'] & 1) != 0
            sb     = (chunk['format'] & 2) != 0
            hc     = (chunk['format2'] & 0x10) != 0
            hu     = (chunk['format2'] & 0x80) != 0
            bpv    = 6 + (1 if sb else 0) + (2 if hc else 0) + (2 if hu else 0)
            tp, te = chunk['tri_addr'], chunk['tri_addr'] + chunk['tri_size']

            face_start = len(faces)   # v11: record where this chunk starts

            if tp >= len(data) or chunk['tri_size'] == 0:
                chunk_face_starts.append(face_start)
                chunk_face_counts.append(0)
                chunk_mat_indices_raw.append(chunk['mat_idx'])
                continue

            chunk_palette = _read_chunk_palette(chunk['entry_ptr']) if (sb and not use_cb) else None

            chunk_verts = []   # v24.1: collect (vertex_idx, sb_byte) for skinning
            skipped_verts = 0  # v24.6: debug tracking

            while tp < te and tp < len(data):
                if data[tp] != 0x98:
                    break
                tp += 1
                if tp + 2 > len(data):
                    break
                slen = struct.unpack('>H', data[tp:tp+2])[0]; tp += 2
                if slen > 1000:
                    break
                sv = []
                for _ in range(slen):
                    if tp + bpv > len(data):
                        break
                    sb_byte = 0
                    if sb:
                        sb_byte = data[tp]
                        tp += 1
                    vi = struct.unpack('>H', data[tp:tp+2])[0]; tp += 2
                    ni = struct.unpack('>H', data[tp:tp+2])[0]; tp += 2
                    if hc:
                        col_i = struct.unpack('>H', data[tp:tp+2])[0]; tp += 2
                    else:
                        col_i = 0
                    ui = struct.unpack('>H', data[tp:tp+2])[0]; tp += 2
                    if hu: tp += 2
                    
                    # v24.6: Clamp indices to valid ranges instead of skipping faces
                    # This handles cases where vert/norm/uv counts don't match (e.g., pegasus2: 390 verts, 363 norms, 215 UVs)
                    ui_safe = ui if ui < len(uvs) else (len(uvs) - 1 if uvs else 0)
                    ni_safe = ni
                    
                    # Determine which vertex buffer and get valid normal count
                    if vi < len(comp_vertices):
                        norm_count = len(comp_normals) if comp_normals else 0
                        ni_safe = ni if ni < norm_count else (norm_count - 1 if norm_count > 0 else 0)
                        if ui < len(uvs):
                            sv.append((vi, ni, ui, col_i))
                        elif norm_count > 0:
                            sv.append((vi, ni_safe, ui_safe, col_i))
                            skipped_verts += 1
                    elif vi < len(reg_v):
                        norm_count = len(reg_n) if reg_n else 0
                        ni_safe = ni if ni < norm_count else (norm_count - 1 if norm_count > 0 else 0)
                        if ui < len(uvs):
                            sv.append((vi, ni, ui, col_i))
                        elif norm_count > 0:
                            sv.append((vi, ni_safe, ui_safe, col_i))
                            skipped_verts += 1
                    chunk_verts.append((vi, sb_byte))

                for i in range(len(sv) - 2):
                    tri = ([sv[i], sv[i+1], sv[i+2]] if i % 2 == 0
                           else [sv[i], sv[i+2], sv[i+1]])
                    vi0, vi1, vi2 = tri[0][0], tri[1][0], tri[2][0]
                    if vi0 != vi1 and vi1 != vi2 and vi0 != vi2:
                        faces.append(tri)

            # v11: record face range and mat_idx for this chunk
            face_count = len(faces) - face_start
            chunk_face_starts.append(face_start)
            chunk_face_counts.append(face_count)
            chunk_mat_indices_raw.append(chunk['mat_idx'])
            face_mat_indices.extend([chunk['mat_idx']] * face_count)
            
            # v24.6: Debug - show if any faces needed index clamping
            if skipped_verts > 0:
                print(f"    Chunk {ci}: {skipped_verts} verts needed index clamping (vert/norm/uv mismatch)")

            # v24.1: Apply skin weights using GX palette
            # sb_byte encodes palette_slot * 3, so slot = sb_byte // 3.
            #
            # IMPORTANT: do NOT guard with "if vi not in skin_weights".
            # A vertex can appear in the display lists of two adjacent chunks
            # (seam vertex on a boundary).  Each chunk encodes the correct slot
            # via its own sb_byte — the game always uses the sb_byte from the
            # actual draw call, so the last chunk to draw the vertex wins.
            # Removing the first-wins guard matches that behaviour and prevents
            # boundary vertices from being mis-assigned to the wrong bone.
            if chunk_palette and bones is not None:
                for vi, sb_byte in chunk_verts:
                    slot = sb_byte // 3
                    if slot < len(chunk_palette):
                        bone_id = chunk_palette[slot]
                        if bone_id < len(bones):
                            skin_weights[vi] = bone_id

            # v26.0: Skin using slot_idx from ptrA (chunk entry).
            # slot_idx is a coarse single-bone fallback so first-wins is kept —
            # only set if nothing more precise (palette sb_byte) has been set.
            unique_verts = set(all_chunk_verts[ci])
            slot_idx = chunk['slot_idx']

            if raw_cb_ptr == 0 and bones is not None:
                if slot_idx < len(bones):
                    for vi in unique_verts:
                        if vi not in skin_weights:
                            skin_weights[vi] = slot_idx

            elif raw_cb_ptr != 0 and use_composite and bones is not None:
                # Has CB - use gap_mapping only
                in_gap = 0
                for vi in unique_verts:
                    if vi not in skin_weights:
                        if vi in gap_mapping:
                            skin_weights[vi] = gap_mapping[vi]
                            in_gap += 1

            # ── Per-chunk import debug ────────────────────────────────────────
            # Mirrors the export debug so the two can be compared side-by-side.
            _n_unique  = len(unique_verts)
            _n_faces_c = face_count
            _mat_idx_c = chunk['mat_idx']

            # Reconstruct palette string.  chunk_palette may be None for CB
            # chunks; fall back to slot_idx label for the single-bone path.
            if chunk_palette is not None and bones is not None:
                _bone_labels = [
                    f"{bid}:{bones[bid]['name']}" if bid < len(bones) else str(bid)
                    for bid in chunk_palette
                ]
                _palette_str = "[" + ", ".join(_bone_labels) + "]"
            elif chunk_palette is not None:
                _palette_str = str(chunk_palette)
            elif raw_cb_ptr == 0:
                _palette_str = f"[{slot_idx}] (slot_idx fallback)"
            else:
                _palette_str = "(CB / gap_mapping)"

            print(f"  [IMPORT] Chunk {ci:2d}: mat={_mat_idx_c}  "
                  f"verts={_n_unique:4d}  faces={_n_faces_c:4d}  "
                  f"palette={_palette_str}")

    # ── Post-loop skin summary ─────────────────────────────────────────────────
    if bones is not None and skin_weights:
        _bvc: dict = {}
        for _vi, _bid in skin_weights.items():
            _bvc[_bid] = _bvc.get(_bid, 0) + 1
        _total_verts = len(comp_vertices if use_composite else vertices)
        _unskinned   = _total_verts - len(skin_weights)
        print(f"  [IMPORT] Skinning: {len(skin_weights)}/{_total_verts} verts "
              f"across {len(_bvc)} bones, {_unskinned} unskinned")
        for _bid in sorted(_bvc):
            _bn = bones[_bid]['name'] if _bid < len(bones) else f"bone_{_bid}"
            print(f"    bone {_bid:3d} ({_bn}): {_bvc[_bid]} verts")

    # if skin_weights:
    #     print(f"  Skin weights: {len(skin_weights)} verts across "
    #           f"{len(set(skin_weights.values()))} bones")

    unskinned = [i for i in range(len(vertices)) if i not in skin_weights]
    # if unskinned:
    #     print(f"  Unskinned vertices ({len(unskinned)}): {unskinned[:10]}{'...' if len(unskinned) > 10 else ''}")
    #     for idx in unskinned[:5]:
    #         if idx < len(vertices):
    #             v = vertices[idx]
    #             print(f"    vert[{idx}] pos=({v[0]:.2f}, {v[1]:.2f}, {v[2]:.2f})")

    # ── Material table ─────────────────────────────────────────────────────────
    #
    # Located at addrs[4] = header[0x54] resolved.
    # 32 bytes per entry, N entries (N = max material index + 1 across all chunks).
    #
    # Entry layout:
    #   +0x00  uint32  raw ptr → material name string
    #   +0x04  uint8   0x00
    #   +0x05  uint8   0x00
    #   +0x06  uint8   texture count (number of TPL info blocks)
    #   +0x07  uint8   0x00
    #   +0x08  4 bytes diffuse color RGBA
    #   +0x0C  4 bytes secondary color RGBA
    #   +0x10  4 bytes 0x00 padding
    #   +0x14  uint32  raw ptr → first TPL info block
    #   +0x18  8 bytes 0x00 padding
    #
    # TPL info block layout (28 bytes each):
    #   +0x00  1 byte  0x00
    #   +0x01  1 byte  0x01 (texture enabled)
    #   +0x02  2 bytes 0x00
    #   +0x04  1 byte  0x00
    #   +0x05  1 byte  TPL texture index (0-based slot in the .tpl container)
    #   +0x06  1 byte  sampling flag (0x01 = standard; shadow maps differ)
    #   +0x07  1 byte  sampling flag
    #   +0x08–0x0F  8 bytes  0x00 padding
    #   +0x10  float32  UV scale X  (3F 80 00 00 = 1.0)
    #   +0x14  float32  UV scale Y  (3F 80 00 00 = 1.0)
    #   +0x18  4 bytes  0x00 padding

    materials = []
    mat_addr  = addrs[4]   # header[0x54] resolved

    if mat_addr and chunk_mat_indices_raw:
        num_mats = max(chunk_mat_indices_raw) + 1
        for mi in range(num_mats):
            me = mat_addr + mi * 32

            # Name string
            name_raw = struct.unpack('>I', data[me:me+4])[0]
            name_p   = name_raw + base_offset
            mat_name = _read_cstring(data, name_p) or f'material_{mi}'

            tex_count   = data[me + 6]
            diffuse_rgba = list(data[me+8:me+12])
            spec_rgba    = list(data[me+12:me+16])

            # TPL info blocks
            tpl_ptr_raw = struct.unpack('>I', data[me+20:me+24])[0]
            tpl_ptr     = tpl_ptr_raw + base_offset if tpl_ptr_raw else 0

            tpl_blocks = []
            for ti in range(tex_count):
                tb      = tpl_ptr + ti * 28
                tpl_idx = data[tb + 5]
                samp0   = data[tb + 6]
                samp1   = data[tb + 7]
                uv_sx   = struct.unpack('>f', data[tb+16:tb+20])[0]
                uv_sy   = struct.unpack('>f', data[tb+20:tb+24])[0]
                tpl_blocks.append({
                    'tpl_idx': tpl_idx,
                    'samp0':   samp0,
                    'samp1':   samp1,
                    'uv_sx':   uv_sx,
                    'uv_sy':   uv_sy,
                })

            materials.append({
                'name':         mat_name,
                'diffuse_rgba': diffuse_rgba,
                'spec_rgba':    spec_rgba,
                'tpl_blocks':   tpl_blocks,
            })

            tpl_str = ', '.join(
                f"TPL[{t['tpl_idx']}]" for t in tpl_blocks
            )
            # print(f"  Material {mi}: '{mat_name}'  diffuse={diffuse_rgba}  "
            #       f"textures=[{tpl_str}]")

    active_v = comp_vertices if use_composite else reg_v
    # print(f"  Parsed: {len(active_v)} verts, {len(uvs)} UVs, {len(faces)} faces, "
    #       f"{len(materials)} materials")

    # if uvs:
    #     uv_min = (min(u for u, v in uvs), min(v for u, v in uvs))
    #     uv_max = (max(u for u, v in uvs), max(v for u, v in uvs))
    #     print(f"  UV range: min={uv_min}, max={uv_max}")
    #     print(f"  UV addresses: verts@{addrs[0]:X}, normals@{addrs[1]:X}, uvs@{addrs[2]:X}, colors@{addrs[3]:X}")
    #     print(f"  UV counts: verts={nums[0]}, normals={nums[1]}, uvs={nums[2]}, colors={nums[3]}")

    # Check max UV index used in faces
    max_uv_idx_used = 0
    min_uv_idx_used = 999999
    uv_vertex_map = defaultdict(list)
    for face in faces:
        for fv in face:
            vi, ni, ui, ci = (fv[0], fv[1], fv[2], fv[3] if len(fv) > 3 else 0)
            uv_vertex_map[ui].append(vi)
            if ui > max_uv_idx_used:
                max_uv_idx_used = ui
            if ui < min_uv_idx_used:
                min_uv_idx_used = ui
    # print(f"  UV check: {len(uvs)} UVs read, max UV index in faces: {max_uv_idx_used}")
    if max_uv_idx_used >= len(uvs):
        print(f"  NOTE: Some faces used clamped UV indices due to vert/norm/uv count mismatch")
    
    # v24.6: Debug UV usage distribution
    # print(f"  UV usage: {len(uv_vertex_map)} unique UV indices used")
    # Show vertices with lowest UV indices (these might be cape/wing)
    low_uv_verts = []
    for ui in sorted(uv_vertex_map.keys())[:5]:
        verts = uv_vertex_map[ui]
        low_uv_verts.extend(verts[:3])
    # if low_uv_verts and vertices:
    #     print(f"    Vertices using lowest UV indices: {low_uv_verts[:10]}...")
    #     for vi in low_uv_verts[:5]:
    #         if vi < len(vertices):
    #             print(f"      vert[{vi}] pos=({vertices[vi][0]:.2f}, {vertices[vi][1]:.2f}, {vertices[vi][2]:.2f})")
    
    # v24.6: Find vertices in expected cape position (low Y, high Z around -4 to 5 based on unskinned verts)
    cape_candidates = [i for i, v in enumerate(vertices) if v[1] < 1.0 and 3.0 < v[2] < 5.5]
    # if cape_candidates:
    #     print(f"  Cape candidates ({len(cape_candidates)} verts): {cape_candidates[:10]}")
    #     for vi in cape_candidates[:5]:
    #         # Find which UV index this vertex uses
    #         uv_idx_for_vert = None
    #         for fi, face in enumerate(faces):
    #             for fv in face:
    #                 if fv[0] == vi:
    #                     uv_idx_for_vert = fv[2]
    #                     break
    #             if uv_idx_for_vert is not None:
    #                 break
    #         if uv_idx_for_vert is not None and uv_idx_for_vert < len(uvs):
    #             print(f"    vert[{vi}] pos=({vertices[vi][0]:.2f}, {vertices[vi][1]:.2f}, {vertices[vi][2]:.2f}) uses UV[{uv_idx_for_vert}]={uvs[uv_idx_for_vert]}")
    
    # v24.6: Find UV indices used by wing root area (known unskinned verts)
    known_wing_roots = [128, 129, 130, 131, 132, 133, 134, 135]
    # print(f"  Wing root UVs (known unskinned verts):")
    for vi in known_wing_roots:
        if vi < len(vertices):
            # Find which UV index this vertex uses
            uv_idx_for_vert = None
            for fi, face in enumerate(faces):
                for fv in face:
                    if fv[0] == vi:
                        uv_idx_for_vert = fv[2]
                        break
                if uv_idx_for_vert is not None:
                    break
            # if uv_idx_for_vert is not None and uv_idx_for_vert < len(uvs):
            #     print(f"    vert[{vi}] pos=({vertices[vi][0]:.2f}, {vertices[vi][1]:.2f}, {vertices[vi][2]:.2f}) uses UV[{uv_idx_for_vert}]={uvs[uv_idx_for_vert]}")

    # v24.5: DISABLED - submesh format interpretation was incorrect
    # The vertex counts in submesh entries don't match actual mesh vertices
    # Need to analyze data format more carefully
    # submesh_to_real_bone = {
    #     56: 19,   # ear -> Head
    #     57: 2,    # legs -> Hips
    #     58: 10,   # body -> Spine1
    #     59: 19,   # hair -> Head
    #     60: 12,   # l_arm -> LeftArm
    #     61: 26,   # r_arm -> RightArm
    #     62: 2,    # group1 -> Hips
    #     63: 2,   # SW -> Hips (sword/weapon - attach to root)
    # }
    # try:
    #     format_flag = struct.unpack('>I', data[0x08:0x0C])[0] & 0xFF
    #     print(f"  v24.5: format_flag={format_flag}, bones is not None={bones is not None}")
    #     if format_flag in (0x58, 0x2C) and bones is not None:
    #     ... (disabled)
    pass

    if skin_weights:
        print(f"  Skin weights: {len(skin_weights)} verts across "
              f"{len(set(skin_weights.values()))} bones")

    vo = (addrs[9] + struct.unpack('>I', data[addrs[9]+4:addrs[9]+8])[0]
          if use_composite and addrs[9] else addrs[0])

    return {
        'vertices': active_v, 'normals': comp_normals if use_composite else reg_n,
        'uvs': uvs, 'colors': colors, 'faces': faces,
        'raw_file_data': data.hex(), 'vertex_offset': vo,
        'vertex_count': len(active_v), 'vertex_scale': vert_scale,
        'used_composite': use_composite,
        'composite_offset': addrs[9] if addrs[9] else 0,
        'skin_weights': skin_weights,
        'uv_offset':    addrs[2],
        'uv_count':     nums[2],
        'uv_scale':     uv_scale,
        'norm_offset':  0       if use_composite else addrs[1],
        'norm_count':   0       if use_composite else nums[1],
        'norm_scale':   norm_scale,
        # v11 material + chunk data
        'materials':          materials,
        'face_mat_indices':   face_mat_indices,
        'chunk_list_addr':    chunk_addr,   # resolved file offset of chunk list
        'chunk_face_starts':  chunk_face_starts,
        'chunk_face_counts':  chunk_face_counts,
        'chunk_mat_indices':  chunk_mat_indices_raw,
        # v28: track degenerate faces removed at import (computed in create_mesh_from_data)
        'culled_faces':       0,  # Will be updated in create_mesh_from_data
    }


# =============================================================================
# MATERIAL SHADER SETUP — UTILITY
# =============================================================================
#
# Sets up a shader tree for newly created materials during import.
# Tree structure:
#   - Image Texture (disconnected)
#   - Transparent BSDF → Mix Shader
#   - Principled BSDF → Mix Shader
#   - Mix Shader → Material Output

def setup_shader_tree(material, mix_factor=None):
    """Set up the default shader tree for a newly created material.
    
    Creates nodes for:
    - Image Texture (disconnected)
    - Transparent BSDF
    - Principled BSDF
    - Mix Shader (with configurable factor)
    - Material Output
    
    Args:
        material: bpy.types.Material to configure
        mix_factor: Float value for Mix Shader factor (0.0-1.0). 
                   If None, uses DEFAULT_MIX_SHADER_FACTOR
    """
    if mix_factor is None:
        mix_factor = DEFAULT_MIX_SHADER_FACTOR
    
    # Enable node-based shader editing
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    
    # Clear default nodes
    nodes.clear()
    
    # Create nodes
    img_tex = nodes.new(type='ShaderNodeTexImage')
    transparent = nodes.new(type='ShaderNodeBsdfTransparent')
    principled = nodes.new(type='ShaderNodeBsdfPrincipled')
    mix_shader = nodes.new(type='ShaderNodeMixShader')
    mat_output = nodes.new(type='ShaderNodeOutputMaterial')
    
    # Set factor on Mix Shader
    mix_shader.inputs['Fac'].default_value = mix_factor
    
    # Position nodes for visibility (approximate layout matching reference image)
    # Left side: Image Texture
    img_tex.location = (-400, 0)
    # Middle-left: Transparent BSDF
    transparent.location = (-100, 100)
    # Middle-left: Principled BSDF
    principled.location = (-100, -100)
    # Middle-right: Mix Shader
    mix_shader.location = (200, 0)
    # Right: Material Output
    mat_output.location = (500, 0)
    
    # Create connections
    # Transparent BSDF → Mix Shader input 1 (first shader input)
    links.new(transparent.outputs['BSDF'], mix_shader.inputs[1])
    # Principled BSDF → Mix Shader input 2 (second shader input)
    links.new(principled.outputs['BSDF'], mix_shader.inputs[2])
    # Mix Shader → Material Output
    links.new(mix_shader.outputs['Shader'], mat_output.inputs['Surface'])
    
    # Image Texture remains disconnected per spec


# =============================================================================
# MESH (.gs) — BLENDER OBJECT CREATION
# =============================================================================
#
# v11 additions:
#   - Creates one Blender material per game material entry.
#   - Assigns poly.material_index from face_mat_indices.
#   - Stores chunk_list_addr, chunk_face_starts/counts, chunk_mat_indices
#     in gs_original_data for the patch-in-place exporter.
#   - v19.2 addition: Calls setup_shader_tree for newly created materials.

def create_blender_mesh(name, mesh_data):
    """Create a Blender mesh object from parsed .gs data."""
    import json
    print(f"\n=== CREATING MESH '{name}' ===")

    mesh = bpy.data.meshes.new(name)
    obj  = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)

    obj['gs_original_data'] = json.dumps({
        'file_data_hex':    mesh_data.get('raw_file_data', ''),
        'vertex_offset':    mesh_data.get('vertex_offset', 0),
        'vertex_count':     mesh_data.get('vertex_count', 0),
        'vertex_scale':     mesh_data.get('vertex_scale', 1024),
        'used_composite':   mesh_data.get('used_composite', False),
        'composite_offset': mesh_data.get('composite_offset', 0),
        'uv_offset':        mesh_data.get('uv_offset', 0),
        'uv_count':         mesh_data.get('uv_count', 0),
        'uv_scale':         mesh_data.get('uv_scale', 1),
        'norm_offset':      mesh_data.get('norm_offset', 0),
        'norm_count':       mesh_data.get('norm_count', 0),
        'norm_scale':       mesh_data.get('norm_scale', 1),
        # v11 chunk + material data
        'chunk_list_addr':   mesh_data.get('chunk_list_addr', 0),
        'chunk_face_starts': mesh_data.get('chunk_face_starts', []),
        'chunk_face_counts': mesh_data.get('chunk_face_counts', []),
        'chunk_mat_indices': mesh_data.get('chunk_mat_indices', []),
        # v28: track degenerate faces removed at import
        'culled_faces':      mesh_data.get('culled_faces', 0),
    })

    vertices  = mesh_data['vertices']
    faces_raw = mesh_data['faces']
    uvs       = mesh_data['uvs']

    if not vertices:
        print("  ERROR: no vertices found!")
        return obj

    faces         = [[f[0] for f in face] for face in faces_raw]
    face_uvs      = [[f[2] for f in face] for face in faces_raw]
    face_colors   = [[f[3] if len(f) > 3 else 0 for f in face] for face in faces_raw]
    colors_table  = mesh_data.get('colors', [])
    face_mat_indices = mesh_data.get('face_mat_indices', [])

    # ── Build per-face payload lookup BEFORE from_pydata / validate() ─────────
    #
    # Problem: mesh.validate() can silently remove zero-area or non-manifold
    # faces and then renumbers survivors from 0.  Any pi-based assignment done
    # after validate() is therefore shifted for every removed face.
    #
    # Problem: triangle strips produce back-face pairs with identical vertex
    # tuples (v0,v1,v2) == (v0,v2,v1) under a frozenset key, so a simple
    # dict keyed on frozenset gives the wrong UV set for one of the pair.
    #
    # Solution: build a dict keyed on the ORDERED vertex tuple, storing a
    # deque of payloads.  Each payload holds (uv_indices, mat_index).
    # When a polygon is matched during assignment, popleft() consumes one
    # entry — so a second face with the same vertex triple gets the NEXT
    # correct payload rather than repeating the first.  Both the forward
    # winding and the reversed winding are stored so Blender's possible
    # winding flip during validate() is also handled.
    #
    # Key insight: from_pydata preserves face ORDER even though validate()
    # may remove some.  The surviving polygons appear in their original
    # relative order.  We therefore populate the deques in original order
    # and rely on the fact that any two faces with the same vertex triple
    # must have appeared consecutively in the strip (adjacent back-face pair).

    from collections import deque as _deque

    # Build a face-index → chunk-index map from the raw chunk face ranges.
    # This is used to label each pre-validate() face with its original chunk,
    # so that the label survives into the post-validate() mesh via the deque.
    _chunk_face_starts = mesh_data.get('chunk_face_starts', [])
    _chunk_face_counts = mesh_data.get('chunk_face_counts', [])
    _face_to_chunk = {}   # pre-validate face index → chunk index (-1 = unknown)
    for _ci, (_fs, _fc) in enumerate(zip(_chunk_face_starts, _chunk_face_counts)):
        for _fi in range(_fs, _fs + _fc):
            _face_to_chunk[_fi] = _ci

    vtuple_to_payloads = {}  # ordered-tuple → deque of (face_uvs, mat_idx, chunk_idx)

    for fi, fv in enumerate(faces):
        fu  = face_uvs[fi] if fi < len(face_uvs) else []
        fc  = face_colors[fi] if fi < len(face_colors) else []
        mi  = int(face_mat_indices[fi]) if fi < len(face_mat_indices) else 0
        ci  = _face_to_chunk.get(fi, -1)
        payload = (fu, mi, ci, fc)

        key_fwd = tuple(fv)
        key_rev = tuple(reversed(fv))

        # Store under forward key
        if key_fwd not in vtuple_to_payloads:
            vtuple_to_payloads[key_fwd] = _deque()
        vtuple_to_payloads[key_fwd].append(payload)

        # Store reversed-UV payload under reversed key (handles winding flips)
        if key_rev not in vtuple_to_payloads:
            vtuple_to_payloads[key_rev] = _deque()
        vtuple_to_payloads[key_rev].append((list(reversed(fu)), mi, ci, list(reversed(fc))))

    # ── Build mesh geometry ───────────────────────────────────────────────────
    mesh.from_pydata(vertices, [], faces)
    mesh.update()

    n_faces_before   = len(mesh.polygons)
    validate_changed = mesh.validate(verbose=False)
    n_faces_after    = len(mesh.polygons)
    n_removed        = n_faces_before - n_faces_after

    if validate_changed:
        print(f"  mesh.validate() corrected geometry in '{name}': "
              f"{n_faces_before} → {n_faces_after} faces ({n_removed} removed)")
        # Store culled faces as separate property (gs_original_data can be too large)
        obj['gs_culled_faces'] = n_removed
    else:
        print(f"  Mesh '{name}': {n_faces_before} faces (no degenerate faces removed)")
    
    print(f"  IMPORT UV DEBUG: {len(uvs)} UVs in mesh_data, {len(faces)} faces")
    
    # UV per chunk debug for import - show basic chunk structure
    chunk_face_starts = mesh_data.get('chunk_face_starts', [])
    chunk_face_counts = mesh_data.get('chunk_face_counts', [])
    print(f"  IMPORT CHUNK DEBUG: {len(chunk_face_starts)} chunks: {chunk_face_counts} faces")
    
    # Store UV info as separate properties (gs_original_data may be too large)
    obj['gs_uv_count'] = len(uvs)
    obj['gs_uv_offset'] = mesh_data.get('uv_offset', 0)
    # Store the face count right after import so the exporter can detect
    # faces appended later by Blender's Join operation (those always get
    # indices >= the original count).
    obj['gs_orig_poly_count'] = n_faces_after

    # ── Create Blender materials ───────────────────────────────────────────────
    game_materials = mesh_data.get('materials', [])
    for mat_info in game_materials:
        mat_name = mat_info['name']
        mat = bpy.data.materials.get(mat_name)
        if mat is None:
            mat = bpy.data.materials.new(name=mat_name)
            setup_shader_tree(mat)

        rgba = mat_info.get('diffuse_rgba', [204, 204, 204, 255])
        if hasattr(mat, 'diffuse_color') and len(rgba) >= 4:
            mat.diffuse_color = tuple(c / 255.0 for c in rgba[:4])

        tpl_blocks = mat_info.get('tpl_blocks', [])
        if tpl_blocks:
            mat['fe_tpl_index'] = tpl_blocks[0]['tpl_idx']
            if len(tpl_blocks) > 1:
                mat['fe_tpl_indices'] = json.dumps(
                    [t['tpl_idx'] for t in tpl_blocks]
                )

        obj.data.materials.append(mat)

    # ── Assign UVs, material indices, and build loop_uv_indices in one pass ───
    #
    # All three are done together using the vtuple_to_payloads deque so they
    # stay aligned even when validate() has removed faces.  We peek at the
    # deque rather than popleft() during the matched-UV pass so that the
    # reversed-winding entry (which shares the same deque slot) is not consumed
    # prematurely — instead we consume only the canonical forward entry.
    #
    # loop_uv_indices is rebuilt from the surviving polygons in post-validate
    # order so it stays aligned with the mesh as it now exists (used by the
    # patch-in-place exporter).

    uvl          = mesh.uv_layers.new(name="UVMap") if uvs else None
    uv_assigned  = 0
    uv_skipped   = 0
    uv_missing   = 0
    mat_assigned = 0
    mat_missing  = 0

    # Create a per-face integer attribute to store chunk index.
    # This survives vertex/face deletion because Blender tracks attributes
    # by face, not by index position.  -1 means "not from any original chunk"
    # (i.e. new geometry added by the user).
    chunk_attr = mesh.attributes.new(name="fe_chunk_index",
                                     type='INT', domain='FACE')

    # Per-loop UV index list — built during the polygon loop below and stored
    # as a mesh custom property.  This replaces the old gs_original_data entry
    # so the JSON blob stays a reasonable size.
    surviving_loop_uv = []
    surviving_loop_colors = []

    # Used to rebuild loop_uv_indices in surviving-polygon order.
    # (kept as comment for history)

    for poly in mesh.polygons:
        key = tuple(poly.vertices)
        dq  = vtuple_to_payloads.get(key)

        if dq and len(dq) > 0:
            payload = dq.popleft()
            fu, mi, ci, fc = (payload if len(payload) >= 4 else (payload[0], payload[1], payload[2], []))
            # Also consume the mirrored reversed entry so the deque stays in sync.
            key_rev = tuple(reversed(key))
            if key_rev != key:
                dq_rev = vtuple_to_payloads.get(key_rev)
                if dq_rev and len(dq_rev) > 0:
                    dq_rev.popleft()
        else:
            fu = []
            mi = 0
            ci = -1
            fc = []
            uv_missing  += len(poly.vertices)
            mat_missing += 1

        # Chunk index attribute (survives face deletion).
        # We store (ci + 1) so that Blender's default value of 0 for newly-added
        # faces is distinguishable from chunk 0 (stored as 1).
        # Decode at export: stored_value - 1 = real ci (-1 = unclaimed/new).
        chunk_attr.data[poly.index].value = ci + 1  # -1 → 0, 0 → 1, N-1 → N

        # Material index
        if game_materials:
            poly.material_index = mi
            mat_assigned += 1

        # UV coordinates + per-loop UV index tracking
        for corner_i, li in enumerate(poly.loop_indices):
            if corner_i < len(fu):
                ui = fu[corner_i]
                surviving_loop_uv.append(ui)
                if uvl is not None:
                    if ui < len(uvs):
                        uvl.data[li].uv = uvs[ui]
                        uv_assigned += 1
                    else:
                        uv_skipped += 1
            else:
                surviving_loop_uv.append(0)
                uv_skipped += 1

        # Vertex color assignment per loop corner
        for corner_i, li in enumerate(poly.loop_indices):
            if corner_i < len(fc):
                ci = fc[corner_i]
            else:
                ci = 0
            surviving_loop_colors.append(ci)

    # ── Create vertex color attribute ─────────────────────────────────────────
    if colors_table and surviving_loop_colors:
        col_attr = mesh.color_attributes.new(name="Col",
                                             type='BYTE_COLOR', domain='CORNER')
        for li, ci in enumerate(surviving_loop_colors):
            if ci < len(colors_table):
                rgba_bytes = colors_table[ci]
                col_attr.data[li].color = tuple(c / 255.0 for c in rgba_bytes[:4])

    # ── Store per-loop UV indices for export ──────────────────────────────────
    # Store as a separate mesh custom property to keep gs_original_data small.
    # This flat list is in post-validate polygon/loop order and aligns with
    # the current mesh loops at import time.  At export, if the mesh has had
    # faces deleted (list length mismatch), we fall back to the seam-safe
    # Blender UV coordinate lookup instead.
    import json as _json
    obj['gs_loop_uv_indices'] = _json.dumps(surviving_loop_uv)
    obj['gs_loop_color_indices'] = _json.dumps(surviving_loop_colors)
    mat_names = [m['name'] for m in game_materials]
    print(f"  Mesh '{name}': {len(mesh.vertices)} verts, {len(mesh.polygons)} faces, "
          f"{len(game_materials)} materials {mat_names}")
    print(f"  UV assignment : {uv_assigned} ok, {uv_skipped} out-of-range, "
          f"{uv_missing} loops on unmatched faces")
    if uv_missing > 0:
        print(f"    WARNING: {uv_missing // 3} faces had no vtuple match "
              f"(removed by validate or unseen vertex triple). "
              f"Those faces will have UV=(0,0) and material_index=0.")
    if n_removed > 0:
        print(f"    INFO: {n_removed} degenerate face(s) removed by validate() "
              f"— UV/mat data rebuilt from surviving polygon order.")

    return obj


# =============================================================================
# MESH (.gs) — SKINNING
# =============================================================================

def apply_skin_weights(mesh_obj, armature_obj, skin_weights, bones):
    """Assign vertex groups and add an Armature modifier to *mesh_obj*."""
    if not skin_weights:
        print("  apply_skin_weights: no skin data — skipping")
        return

    bone_name_by_id = {}
    for bone in armature_obj.data.bones:
        idx = bone.get('fe_bone_index')
        if idx is not None:
            bone_name_by_id[int(idx)] = bone.name

    verts_for_bone = defaultdict(list)
    for vi, bone_id in skin_weights.items():
        verts_for_bone[bone_id].append(vi)

    groups_created = 0
    verts_assigned = 0
    for bone_id, vert_list in sorted(verts_for_bone.items()):
        bone_name = bone_name_by_id.get(bone_id)
        if bone_name is None:
            print(f"  Warning: bone_id {bone_id} not in skeleton — "
                  f"{len(vert_list)} verts unassigned")
            continue
        vg = mesh_obj.vertex_groups.get(bone_name)
        if vg is None:
            vg = mesh_obj.vertex_groups.new(name=bone_name)
        vg.add(vert_list, 1.0, 'REPLACE')
        groups_created += 1
        verts_assigned += len(vert_list)
        
        # Debug: print positions for Sword bone (bone_id 84)
        if bone_id == 84:
            print(f"  DEBUG IMPORT: Sword bone (id=84) vertices:")
            for vi in sorted(vert_list):
                if vi < len(mesh_obj.data.vertices):
                    co = mesh_obj.data.vertices[vi].co
                    print(f"    vertex {vi}: ({co.x:.4f}, {co.y:.4f}, {co.z:.4f})")

    mesh_obj.parent = armature_obj
    if 'Armature' not in mesh_obj.modifiers:
        mod        = mesh_obj.modifiers.new('Armature', 'ARMATURE')
        mod.object = armature_obj

    print(f"  Skinning applied: {verts_assigned} verts in {groups_created} "
          f"vertex groups, Armature modifier added")


def create_unit_vertex_groups(mesh_obj, armature_obj, bones):
    """Create UnitN vertex groups based on hip bone hierarchies.

    Finds all bones containing 'hip' or 'Hip' in their name, then recursively
    collects all descendant bones. Creates a UnitN vertex group for each hip
    hierarchy and adds all vertices from bone vertex groups within that hierarchy.
    """
    if not bones or not mesh_obj.vertex_groups:
        return

    bone_name_to_index = {}
    bone_index_to_name = {}
    for bone in armature_obj.data.bones:
        idx = bone.get('fe_bone_index')
        if idx is not None:
            idx_int = int(idx)
            bone_name_to_index[bone.name] = idx_int
            bone_index_to_name[idx_int] = bone.name

    parent_map = {}
    for b in bones:
        parent_map[b['index']] = b['parent_idx']

    def get_descendants(bone_idx):
        descendants = set()
        stack = [bone_idx]
        while stack:
            current = stack.pop()
            for idx, par in parent_map.items():
                if par == current:
                    descendants.add(idx)
                    stack.append(idx)
        return descendants

    hip_bones = [b for b in bones if 'hip' in b['name'].lower()]

    if hip_bones:
        print(f"  Found {len(hip_bones)} hip bone(s): {[b['name'] for b in hip_bones]}")
    if not hip_bones:
        bone_names_lower = [b['name'].lower() for b in bones]
        print(f"  No hip bones found — skipping Unit vertex groups")
        print(f"  All bone names: {bone_names_lower}")
        return

    unit_num = 1
    for hip_bone in hip_bones:
        unit_group_name = f"Unit{unit_num}"
        unit_vg = mesh_obj.vertex_groups.get(unit_group_name)
        if unit_vg is None:
            unit_vg = mesh_obj.vertex_groups.new(name=unit_group_name)

        descendants = get_descendants(hip_bone['index'])
        descendant_names = {bone_index_to_name[idx] for idx in descendants}
        descendant_names.add(bone_index_to_name[hip_bone['index']])

        verts_in_unit = set()
        for bone_name in descendant_names:
            bone_vg = mesh_obj.vertex_groups.get(bone_name)
            if bone_vg is not None:
                for v in mesh_obj.data.vertices:
                    for g in v.groups:
                        if g.group == bone_vg.index:
                            verts_in_unit.add(v.index)

        if verts_in_unit:
            unit_vg.add(list(verts_in_unit), 1.0, 'REPLACE')
            print(f"  Created {unit_group_name}: {len(verts_in_unit)} verts from "
                  f"{len(descendant_names)} bones (hip: {hip_bone['name']})")

        unit_num += 1

    print(f"  Unit vertex groups created: {unit_num - 1}")


# =============================================================================
# MESH (.gs) — EXPORT (patch vertex/normal/UV tables in-place + material indices)
# =============================================================================
#
# v11 additions over v10:
#   - After patching vertex/normal/UV data, also patches the material index byte
#     (chunk descriptor +0x0B) for each chunk, based on the current Blender
#     material slot assignments of the faces belonging to that chunk.
#   - The dominant (most common) material slot among a chunk's faces is used.
#     In a well-formed mesh all faces within a chunk share the same slot.
#
# Limitations (unchanged from v10):
#   - Cannot add or remove vertices, normals, or UV entries.
#   - Cannot add or remove faces or change triangle-strip topology.
#   - Full strip rebuilder (needed to add/remove geometry) is a future version.

def export_gs_file(mesh_obj, filepath):
    """Patch-write a .gs file with current mesh data.

    Returns (True, message) on success or (False, reason) on failure.
    """
    import json as _json

    gs_json = mesh_obj.get('gs_original_data')
    if not gs_json:
        return False, "No gs_original_data found — was this mesh imported with this plugin?"

    gs  = _json.loads(str(gs_json))
    raw = bytearray(bytes.fromhex(gs['file_data_hex']))
    mesh           = mesh_obj.data
    used_composite = gs['used_composite']

    # ── Vertices (and normals for composite) ──────────────────────────────────
    v_offset = gs['vertex_offset']
    v_count  = gs['vertex_count']

    if len(mesh.vertices) != v_count:
        return False, (f"Vertex count mismatch: Blender has {len(mesh.vertices)}, "
                       f"original file has {v_count}.  "
                       f"Adding/removing vertices is not supported in v11.")

    if used_composite:
        CS = 256
        # CS = 0x800
        mesh.calc_normals()
        for i, vert in enumerate(mesh.vertices):
            co = vert.co
            n  = vert.normal
            x  = max(-32768, min(32767, int(round(co.x * CS))))
            y  = max(-32768, min(32767, int(round(co.y * CS))))
            z  = max(-32768, min(32767, int(round(co.z * CS))))
            nx = max(-32768, min(32767, int(round(n.x  * CS))))
            ny = max(-32768, min(32767, int(round(n.y  * CS))))
            nz = max(-32768, min(32767, int(round(n.z  * CS))))
            struct.pack_into('>hhhhhh', raw, v_offset + i * 12, x, y, z, nx, ny, nz)
    else:
        vs = gs['vertex_scale']
        for i, vert in enumerate(mesh.vertices):
            co = vert.co
            x  = max(-32768, min(32767, int(round(co.x * vs))))
            y  = max(-32768, min(32767, int(round(co.y * vs))))
            z  = max(-32768, min(32767, int(round(co.z * vs))))
            struct.pack_into('>hhh', raw, v_offset + i * 6, x, y, z)
        n_offset = gs.get('norm_offset', 0)
        n_count  = gs.get('norm_count',  0)
        ns       = gs.get('norm_scale',  1)
        if n_offset and n_count:
            mesh.calc_normals()
            for i in range(min(n_count, len(mesh.vertices))):
                n  = mesh.vertices[i].normal
                nx = max(-128, min(127, int(round(n.x * ns))))
                ny = max(-128, min(127, int(round(n.y * ns))))
                nz = max(-128, min(127, int(round(n.z * ns))))
                struct.pack_into('>bbb', raw, n_offset + i * 3, nx, ny, nz)

    # ── UVs ───────────────────────────────────────────────────────────────────
    uv_offset       = gs.get('uv_offset', 0)
    uv_count_orig   = gs.get('uv_count',  0)  # From file header (stored at import)
    
    # Use mesh property as the source of truth for original UV count
    mesh_uv_count = mesh_obj.get('gs_uv_count', 0)
    if mesh_uv_count > 0:
        uv_count_orig = mesh_uv_count
    
    uv_scale        = gs.get('uv_scale',  1)
    loop_uv_indices = gs.get('loop_uv_indices', [])

    print(f"  EXPORT UV: uv_offset={uv_offset}, uv_count_orig={uv_count_orig}, loop_uv_indices len={len(loop_uv_indices)}")
    print(f"  EXPORT UV: uv_offset is zero? {uv_offset == 0}")

    # Always build uv_bytes - either with original indices or fallback
    uv_bytes = bytearray()
    
    # Always rebuild uv_table from mesh
    print(f"  EXPORT UV: condition uv_offset={uv_offset}, uv_count_orig={uv_count_orig}, loop_uv_indices={bool(loop_uv_indices)}")
    if uv_offset and uv_count_orig and loop_uv_indices:
        print("  >>> ENTERING UV EXPORT BLOCK <<<")
        uvl = mesh.uv_layers.active
        if uvl is None:
            print("  Warning: no active UV layer — UVs not exported")
        else:
            # Create uv_table with correct original size (NOT deduplicated)
            uv_table = [None] * uv_count_orig
            assigned_count = 0
            
            # First pass: fill all UV slots that are used by current mesh
            for poly in mesh.polygons:
                for corner_i in range(len(poly.loop_indices)):
                    li = poly.loop_start + corner_i
                    if li < len(loop_uv_indices):
                        ui = loop_uv_indices[li]
                        if 0 <= ui < uv_count_orig:
                            uv_table[ui] = uvl.data[li].uv
                            assigned_count += 1
            
            # Second pass: fill any remaining None slots with default UVs
            # This ensures we have the correct number of UVs even if duplicates existed
            default_uv = (0.0, 0.0)
            unfilled = 0
            for i in range(len(uv_table)):
                if uv_table[i] is None:
                    uv_table[i] = default_uv
                    unfilled += 1
            
            print(f"  EXPORT UV: assigned {assigned_count} UV entries, filled {unfilled} gaps")
            print(f"  EXPORT UV: final uv_table size: {len(uv_table)}")
            
            # Debug: show what's in first few uv_table entries
            print(f"  EXPORT UV: uv_table[0:5] = {uv_table[0:5]}")
            
            # Build uv_bytes while writing (for later sections that need it)
            uv_bytes = bytearray()
            for ui, uv in enumerate(uv_table):
                u = max(-32768, min(32767, int(round(uv[0] * uv_scale))))
                v = max(-32768, min(32767, int(round((1.0 - uv[1]) * uv_scale))))
                uv_bytes += struct.pack('>hh', u, v)
                struct.pack_into('>hh', raw, uv_offset + ui * 4, u, v)
    else:
        # Fallback: create empty uv_bytes if no loop_uv_indices
        uv_bytes = bytearray()
        print("  EXPORT UV: no loop_uv_indices, using fallback")

    # ── v11: Material index patching ──────────────────────────────────────────
    #
    # For each chunk, determine the dominant Blender material slot among its
    # faces (should be uniform within a correctly-formed mesh).  If it differs
    # from the originally stored material index, patch byte at:
    #   chunk_list_addr + chunk_index * 32 + 11
    #
    # The dominant slot value IS the game material index (slot 0 = material 0,
    # slot 1 = material 1, etc.) because create_blender_mesh adds materials
    # to slots in the same order as the game material table.

    chunk_list_addr   = gs.get('chunk_list_addr', 0)
    chunk_face_starts = gs.get('chunk_face_starts', [])
    chunk_face_counts = gs.get('chunk_face_counts', [])
    orig_mat_indices  = gs.get('chunk_mat_indices', [])
    mats_patched      = 0

    if chunk_list_addr and chunk_face_starts:
        for ci, (face_start, face_count) in enumerate(
                zip(chunk_face_starts, chunk_face_counts)):

            # Count material slot occurrences among this chunk's faces
            slot_counts = {}
            for fi in range(face_start, face_start + face_count):
                if fi < len(mesh.polygons):
                    si = mesh.polygons[fi].material_index
                    slot_counts[si] = slot_counts.get(si, 0) + 1

            if not slot_counts:
                continue

            dominant_slot = max(slot_counts, key=slot_counts.get)
            mat_byte_off  = chunk_list_addr + ci * 32 + 11

            if mat_byte_off < len(raw):
                orig = orig_mat_indices[ci] if ci < len(orig_mat_indices) else None
                if dominant_slot != orig:
                    raw[mat_byte_off] = dominant_slot & 0xFF
                    mats_patched += 1

    # ── Write ─────────────────────────────────────────────────────────────────
    with open(filepath, 'wb') as f:
        f.write(raw)

    print(f"\n=== EXPORTED MESH: {os.path.basename(filepath)} ===")
    print(f"  {len(raw)} bytes  |  {v_count} verts  |  "
          f"{uv_count} UVs  |  {mats_patched} chunk material indices updated")
    return True, f"{len(raw)} bytes written"


# =============================================================================
# MESH (.gs) — FULL-REBUILD EXPORT
# =============================================================================
#
# Rebuilds the entire .gs binary from scratch using the current Blender mesh,
# armature, and material slots.  Supports adding or removing vertices, bones,
# chunks, and materials relative to the original binary.
#
# Chunk boundaries are defined by vertex groups on mesh_obj.  Each vertex
# group that has at least one weight-assigned vertex produces one chunk.
# Vertex groups with no weights (locator/attachment bones such as _s1_) are
# silently skipped and produce no chunk, PtrA block, or display list.
#
# The following are fully rebuilt from Blender state:
#   - Vertex position table   (int16 × 3, from mesh.vertices)
#   - Vertex normal table     (int8  × 3, from vertex normals)
#   - UV coordinate table     (int16 × 2, deduped from active UV layer)
#   - Display lists           (one GX tri-strip draw call per face, per chunk)
#   - GX caches               (bone palette per chunk, from armature fe_bone_index)
#   - Material entries        (from mesh_obj.data.materials slot order)
#   - TPL info blocks         (verbatim for existing mats; synthesised for new)
#   - PtrA blocks             (name + AABB; tail verbatim if chunk existed)
#   - Chunk descriptors       (format fields from original or character default)
#   - String pool             (rebuilt from all used name strings)
#   - Relocation table        (fully recomputed from new pointer layout)
#
# Current limitation: composite-vertex meshes (used_composite=True) are not
# yet supported; the patch-in-place exporter handles those.
#
# FILE LAYOUT PRODUCED:
#   [Header         0x88 bytes ]
#   [Position table 6 bytes × V]
#   [Normal table   3 bytes × N + 0–3 padding bytes to 4-byte boundary]
#   [UV table       4 bytes × U]
#   [Material table 32 bytes × M]
#   [TPL info blocks 28 bytes each, contiguous per material]
#   [PtrA blocks    36 bytes × C chunks]
#   [Chunk descriptors 32 bytes × C chunks]
#   [Display list data, one block per chunk, contiguous]
#   [GX cache data,     one block per chunk if present, contiguous]
#   [String pool        null-terminated ASCII strings]
#   [Relocation table   4 bytes × K entries, sorted ascending]

def export_gs_full_rebuild(mesh_obj, filepath, addon_mesh_objs=None, vc_mode='BLENDER', append_new_bones=True):
    """Full-rebuild .gs exporter — v13.

    Drives chunk structure from vertex groups, rebuilds display lists and
    GX caches from the current mesh and armature, and supports adding new
    materials and bones beyond those in the original binary.

    addon_mesh_objs: optional list of additional Mesh objects whose geometry
        is appended as new chunks after the main mesh's chunks.  Each addon
        mesh must be parented to / modified by the same armature.  Addon
        vertices are appended to the vertex/normal tables after the main
        mesh vertices, with UV indices extending the UV table.

    append_new_bones: when True (default), the skeleton has been exported
        with append mode (original indices preserved, new bones appended at
        end). When False (hierarchy mode), all bone indices were recalculated
        in hierarchy order, so the orig_bone_count filter is bypassed.

    Returns (True, message) on success or (False, reason) on failure.
    """
    import json

    print(">>> ENTERED export_gs_full_rebuild <<<")
    print(f"  Vertex color mode: {vc_mode}")

    gs_json = mesh_obj.get('gs_original_data')
    if not gs_json:
        return False, ("No gs_original_data found — "
                       "import the mesh with this plugin first.")

    gs       = json.loads(str(gs_json))
    raw_orig = bytearray(bytes.fromhex(gs['file_data_hex']))
    mesh     = mesh_obj.data

    print(f"\n=== EXPORT START DEBUG ===")
    print(f"  mesh_obj.data.name: {mesh.name}")
    print(f"  mesh.vertices count: {len(mesh.vertices)}")
    print(f"  mesh.polygons count: {len(mesh.polygons)}")
    print(f"  gs['vertex_count'] from import: {gs.get('vertex_count', 'NOT SET')}")

    # Every raw pointer stored in the file resolves to: raw_value + BASE.
    # To store a pointer: raw = resolved_file_offset - BASE.
    BASE = 0x20

    # ── Early checks ─────────────────────────────────────────────────────────

    if gs.get('used_composite', False):
        return False, ("Full rebuild is not yet supported for composite-vertex "
                       "meshes.  Use the patch-in-place exporter instead.")

    # ── Preserved verbatim header regions ────────────────────────────────────

    uses_field_0x5C = struct.unpack_from('>I', raw_orig, 0x5C)[0] != 0

    model_name_raw = struct.unpack_from('>I', raw_orig, 0x20)[0]
    model_name = (_read_cstring(raw_orig, model_name_raw + BASE)
                  if model_name_raw else 'unknown')

    build_date_tag  = bytes(raw_orig[0x24:0x28])   # always 20 04 07 23
    header_unk_0x28 = bytes(raw_orig[0x28:0x2C])
    # header_aabb now computed dynamically from new vertex positions
    vat_bytes       = bytes(raw_orig[0x7C:0x80])

    vert_scale = 1 << raw_orig[0x7C]
    norm_scale = 1 << raw_orig[0x7D]
    uv_scale   = 1 << raw_orig[0x7E]

    # ── Dynamically adjust vertex scale to fit all vertices (main + addon) ──
    _all_coords = []
    for v in mesh_obj.data.vertices:
        _all_coords.extend([abs(v.co.x), abs(v.co.y), abs(v.co.z)])
    if addon_mesh_objs:
        for a_obj in addon_mesh_objs:
            if a_obj and a_obj.type == 'MESH':
                for v in a_obj.data.vertices:
                    _all_coords.extend([abs(v.co.x), abs(v.co.y), abs(v.co.z)])
    if _all_coords:
        max_abs_coord = max(_all_coords)
        if max_abs_coord > 1e-9:
            optimal_exp = int(math.floor(math.log2(32767.0 / max_abs_coord)))
            optimal_exp = max(0, min(15, optimal_exp))
            new_vert_scale = 1 << optimal_exp
            if new_vert_scale != vert_scale:
                print(f"  Adjusted vertex scale from {vert_scale} (exp={raw_orig[0x7C]}) "
                      f"to {new_vert_scale} (exp={optimal_exp}) "
                      f"to accommodate coordinate range up to {max_abs_coord:.2f}")
                vert_scale = new_vert_scale
                vat_bytes = bytes([optimal_exp, raw_orig[0x7D], raw_orig[0x7E], raw_orig[0x7F]])

    # ── Parse original materials from binary (for carry-over by name) ─────────
    #
    # Build a dict of mat_name → original data record so that existing
    # materials can have their TPL info blocks carried over verbatim.
    # New materials (not found by name) get synthesised TPL blocks instead.

    mat_table_raw  = struct.unpack_from('>I', raw_orig, 0x54)[0]
    mat_table_addr = mat_table_raw + BASE if mat_table_raw else 0
    orig_chunk_mat_idxs = gs.get('chunk_mat_indices', [])
    n_orig_mats = (max(orig_chunk_mat_idxs) + 1) if orig_chunk_mat_idxs else 0

    orig_mat_by_name = {}
    for mi in range(n_orig_mats):
        me       = mat_table_addr + mi * 32
        name_raw = struct.unpack_from('>I', raw_orig, me)[0]
        mat_name = (_read_cstring(raw_orig, name_raw + BASE)
                    if name_raw else f'material_{mi}')
        tex_count = raw_orig[me + 6]
        diff_rgba = list(raw_orig[me + 8  : me + 12])
        spec_rgba = list(raw_orig[me + 12 : me + 16])
        tpl_raw   = struct.unpack_from('>I', raw_orig, me + 20)[0]
        tpl_addr  = tpl_raw + BASE if tpl_raw else 0
        tpl_blocks = [
            bytes(raw_orig[tpl_addr + ti * 28 : tpl_addr + ti * 28 + 28])
            for ti in range(tex_count)
        ]
        orig_mat_by_name[mat_name] = {
            'name':       mat_name,
            'diff_rgba':  diff_rgba,
            'spec_rgba':  spec_rgba,
            'tpl_blocks': tpl_blocks,
        }

    # ── Build material list from Blender material slots ───────────────────────
    #
    # n_mats = len(mesh.materials) so that newly added Blender materials are
    # included.  Order follows the Blender material slot order.
    #
    # Existing materials (name found in orig_mat_by_name): use original data.
    # New materials: count TEX_IMAGE nodes in the shader tree for tex_count,
    # and build default TPL info blocks using the fe_tpl_index custom property.

    n_mats = len(mesh.materials)

    def make_default_tpl_block(tpl_idx):
        """Return a 28-byte default TPL info block for the given .tpl slot."""
        # Byte layout (28 bytes):
        #  +0   0x00  reserved
        #  +1   0x01  texture enabled
        #  +2   0x00 0x00  padding
        #  +4   0x00  padding
        #  +5   tpl_idx (slot in the .tpl container)
        #  +6   0x01  sampling flag A
        #  +7   0x01  sampling flag B
        #  +8   8 × 0x00  padding
        # +16   float32 BE 1.0  UV scale X
        # +20   float32 BE 1.0  UV scale Y
        # +24   4 × 0x00  padding
        blk = bytearray(28)
        blk[1] = 0x01
        blk[5] = tpl_idx & 0xFF
        blk[6] = 0x01
        blk[7] = 0x01
        struct.pack_into('>f', blk, 16, 1.0)
        struct.pack_into('>f', blk, 20, 1.0)
        return bytes(blk)

    # Build material list from Blender material slots.
    # TPL texture indices are assigned sequentially (0, 1, 2, ...) across all
    # materials in slot order.  Existing materials carry their original TPL
    # blocks verbatim; the sequential counter is advanced past those blocks.
    # Synthesised blocks for new materials get the next available index.

    tpl_seq_idx  = 0    # running counter: next TPL slot to assign
    materials_out = []
    for mi, blmat in enumerate(mesh.materials):
        blmat_name = blmat.name if blmat else f'material_{mi}'

        if blmat_name in orig_mat_by_name:
            # Existing material — carry original data over exactly and advance
            # the counter past however many TPL blocks this material owns.
            mat = dict(orig_mat_by_name[blmat_name])
            tpl_seq_idx += len(mat['tpl_blocks'])
            materials_out.append(mat)
        else:
            # New material — synthesise TPL info blocks with sequential indices.
            tex_node_count = 0
            if blmat and blmat.use_nodes and blmat.node_tree:
                tex_node_count = sum(
                    1 for nd in blmat.node_tree.nodes
                    if nd.type == 'TEX_IMAGE'
                )
            if tex_node_count == 0:
                tex_node_count = 1   # always write at least one TPL block

            tpl_blocks = [
                make_default_tpl_block(tpl_seq_idx + ti)
                for ti in range(tex_node_count)
            ]
            tpl_seq_idx += tex_node_count

            diff_rgba = [0xCC, 0xCC, 0xCC, 0xFF]
            spec_rgba = [0x00, 0x00, 0x00, 0xFF]
            if blmat and hasattr(blmat, 'diffuse_color'):
                dc = blmat.diffuse_color
                diff_rgba = [max(0, min(255, round(c * 255))) for c in dc[:4]]

            materials_out.append({
                'name':       blmat_name,
                'diff_rgba':  diff_rgba,
                'spec_rgba':  spec_rgba,
                'tpl_blocks': tpl_blocks,
            })

    # Also scan addon mesh materials — any not already in materials_out get a
    # new entry so the addon chunk code can assign them by name.
    if addon_mesh_objs:
        existing_names = {m['name'] for m in materials_out}
        for addon_obj in addon_mesh_objs:
            if addon_obj is None:
                continue
            addon_mesh_data = addon_obj.data
            for amat in addon_mesh_data.materials:
                if amat is None:
                    continue
                amat_name = amat.name
                if amat_name in existing_names:
                    continue
                tex_node_count = 0
                if amat.use_nodes and amat.node_tree:
                    tex_node_count = sum(
                        1 for nd in amat.node_tree.nodes
                        if nd.type == 'TEX_IMAGE'
                    )
                if tex_node_count == 0:
                    tex_node_count = 1
                tpl_blocks = [
                    make_default_tpl_block(tpl_seq_idx + ti)
                    for ti in range(tex_node_count)
                ]
                tpl_seq_idx += tex_node_count
                diff_rgba = [0xCC, 0xCC, 0xCC, 0xFF]
                spec_rgba = [0x00, 0x00, 0x00, 0xFF]
                if hasattr(amat, 'diffuse_color'):
                    dc = amat.diffuse_color
                    diff_rgba = [max(0, min(255, round(c * 255))) for c in dc[:4]]
                materials_out.append({
                    'name': amat_name,
                    'diff_rgba': diff_rgba,
                    'spec_rgba': spec_rgba,
                    'tpl_blocks': tpl_blocks,
                })
                existing_names.add(amat_name)
                print(f"  [Addon] Added new material '{amat_name}' from addon mesh to materials_out (index {len(materials_out)-1})")

    # Update n_mats to reflect the full materials_out count (includes addon
    # mesh materials that were synthesised above).
    n_mats = len(materials_out)

    # ── Find armature and build bone-name → fe_bone_index lookup ─────────────

    armature_obj = None
    for mod in mesh_obj.modifiers:
        if mod.type == 'ARMATURE' and mod.object:
            armature_obj = mod.object
            break

    bone_id_by_name = {}   # Blender bone name → fe_bone_index int
    bone_id_by_vgroup_idx = {}  # vertex group index → fe_bone_index int
    if armature_obj:
        # Read the original skeleton bone count stored at import time.
        # Any bone with fe_bone_index >= orig_bone_count is either user-added
        # or transplanted from a secondary model, and must be treated as "new"
        # (not looked up in existing chunk palettes) regardless of whether it
        # already carries an fe_bone_index from its source skeleton.
        orig_bone_count = mesh_obj.get('gs_orig_bone_count', None)

        for ab in armature_obj.data.bones:
            if 'fe_bone_index' in ab:
                bone_idx = int(ab['fe_bone_index'])
                # In hierarchy mode (append_new_bones=False), all indices are
                # recalculated — register every bone regardless of index range.
                # In append mode, only register bones within the original range.
                if append_new_bones and orig_bone_count is not None:
                    if bone_idx >= orig_bone_count:
                        continue
                bone_id_by_name[ab.name] = bone_idx

        # Build a direct vgroup-index → fe_bone_index map to avoid name collisions.
        # Some skeletons have duplicate bone names after Blender truncation (e.g.
        # "shoulder_L" and "shoulder_l" both become the same Blender name).
        # bone_id_by_name only stores one mapping per name, so the wrong fe_bone_index
        # would be returned for any vertex group whose bone name was overwritten.
        # Mapping through vertex group index is unambiguous.
        vgroups_obj = mesh_obj.vertex_groups
        for vgi in range(len(vgroups_obj)):
            vg_name = vgroups_obj[vgi].name
            ab = armature_obj.data.bones.get(vg_name)
            if ab is not None and 'fe_bone_index' in ab:
                bone_idx = int(ab['fe_bone_index'])
                if append_new_bones and orig_bone_count is not None:
                    if bone_idx >= orig_bone_count:
                        continue
                bone_id_by_vgroup_idx[vgi] = bone_idx

        # Auto-assign fe_bone_index for bones added by the user that have no
        # fe_bone_index yet (i.e. they were not imported from a .g file).
        # Without an index, their vertex groups would be silently ignored and
        # any geometry skinned to them would be dropped from the export.
        # We assign the next available index above all currently-used ones,
        # store it back onto the Blender bone so subsequent exports are stable,
        # and add it to both lookup dicts so the rest of the exporter finds it.
        assigned_ids = set(bone_id_by_name.values())
        next_free_id = max(assigned_ids) + 1 if assigned_ids else 0
        for vgi in range(len(vgroups_obj)):
            if vgi not in bone_id_by_vgroup_idx:
                vg_name = vgroups_obj[vgi].name
                ab = armature_obj.data.bones.get(vg_name)
                if ab is not None:
                    # Either no fe_bone_index, or fe_bone_index >= orig_bone_count
                    # (transplanted bone treated as new).
                    bone_idx = int(ab['fe_bone_index']) if 'fe_bone_index' in ab else None
                    is_transplant = (bone_idx is not None
                                     and orig_bone_count is not None
                                     and bone_idx >= orig_bone_count)
                    if bone_idx is None or is_transplant:
                        if bone_idx is None:
                            # Brand-new bone — assign fresh index.
                            ab['fe_bone_index'] = next_free_id
                            bone_idx = next_free_id
                            next_free_id += 1
                        else:
                            # Transplanted bone — keep its existing index value,
                            # but it is still treated as "new" for this export.
                            pass
                        bone_id_by_name[ab.name] = bone_idx
                        bone_id_by_vgroup_idx[vgi] = bone_idx
                        print(f"  NEW bone '{ab.name}' → fe_bone_index={bone_idx} "
                              f"({'transplanted' if is_transplant else 'auto-assigned'})")

        if len(bone_id_by_vgroup_idx) < len(vgroups_obj):
            # Remaining unmatched vertex groups have no armature bone at all
            # (e.g. Unit* groups).  That is expected and not a problem.
            unmatched = [vgroups_obj[vgi].name for vgi in range(len(vgroups_obj))
                         if vgi not in bone_id_by_vgroup_idx]
            print(f"  EXPORT NOTE: {len(unmatched)} vertex groups have no matching "
                  f"armature bone (expected for Unit* groups): "
                  f"{unmatched[:5]}{'…' if len(unmatched) > 5 else ''}")
    
    # Debug: print ALL bone mappings
    # print(f"  DEBUG: bone_id_by_name has {len(bone_id_by_name)} entries")
    # print(f"  DEBUG: bone_id_by_name keys: {list(bone_id_by_name.keys())}")

    # ── Parse original chunk/PtrA records for carry-over by index ──────────────
    #
    # Original chunks are carried over positionally (chunk index ci) since the
    # face-range derivation preserves chunk order exactly.  New chunks (beyond
    # n_orig_chunks) use character format defaults computed later.

    chunk_list_addr = gs['chunk_list_addr']
    n_orig_chunks   = len(gs.get('chunk_face_starts', []))

    # ── Preserve original string pool ────────────────────────────────────────
    mat_table_raw = struct.unpack_from('>I', raw_orig, 0x54)[0]
    mat_table_addr = mat_table_raw + BASE if mat_table_raw else 0
    orig_chunk_mat_idxs = gs.get('chunk_mat_indices', [])
    n_orig_mats = (max(orig_chunk_mat_idxs) + 1) if orig_chunk_mat_idxs else 0
    
    all_orig_str_offsets = []
    
    if model_name_raw:
        all_orig_str_offsets.append((model_name_raw, model_name))
    
    for mi in range(n_orig_mats):
        me = mat_table_addr + mi * 32
        name_raw = struct.unpack_from('>I', raw_orig, me)[0]
        if name_raw:
            mat_name = _read_cstring(raw_orig, name_raw + BASE) if name_raw else f'material_{mi}'
            all_orig_str_offsets.append((name_raw, mat_name))
    
    ptra_list_raw = struct.unpack_from('>I', raw_orig, 0x58)[0]
    for ci in range(n_orig_chunks):
        cp = chunk_list_addr + ci * 32
        ptr_a_raw = struct.unpack_from('>I', raw_orig, cp)[0]
        pa = ptr_a_raw + BASE if ptr_a_raw > 0 else 0
        name_raw = struct.unpack_from('>I', raw_orig, pa)[0]
        if name_raw:
            ptra_name = _read_cstring(raw_orig, name_raw + BASE) if name_raw else f'chunk_{ci}'
            all_orig_str_offsets.append((name_raw, ptra_name))
    
    all_orig_str_offsets.sort(key=lambda x: x[0])
    
    string_pool = bytearray()
    string_offsets = {}
    
    for name_raw, name in all_orig_str_offsets:
        if name not in string_offsets:
            string_offsets[name] = len(string_pool)
            string_pool.extend(name.encode('ascii') + b'\x00')
    
    model_name_pool_off = string_offsets.get(model_name, 0)
    mat_name_pool_offs = []
    for mi in range(n_orig_mats):
        me = mat_table_addr + mi * 32
        name_raw = struct.unpack_from('>I', raw_orig, me)[0]
        mat_name = _read_cstring(raw_orig, name_raw + BASE) if name_raw else f'material_{mi}'
        mat_name_pool_offs.append(string_offsets.get(mat_name, 0))
    
    ptra_name_pool_offs = []

    ptra_list_raw  = struct.unpack_from('>I', raw_orig, 0x58)[0]
    ptra_list_addr = ptra_list_raw + BASE if ptra_list_raw else 0

    orig_chunk_records = []   # list indexed by ci, each a dict of carried fields
    for ci in range(n_orig_chunks):
        cp          = chunk_list_addr + ci * 32
        
        # Get the actual PtrA address from the chunk entry (not from ptra_list!)
        ptr_a_raw = struct.unpack_from('>I', raw_orig, cp)[0]
        pa = ptr_a_raw + BASE if ptr_a_raw > 0 else 0
        
        name_raw = struct.unpack_from('>I', raw_orig, pa)[0]
        ptra_nm  = (_read_cstring(raw_orig, name_raw + BASE)
                    if name_raw else f'chunk_{ci}')
        # Bytes 4–35 of the PtrA block: AABB floats + slot index + padding.
        ptra_tail = bytes(raw_orig[pa + 4 : pa + 36])   # 32 bytes, no ptrs
        
        # Debug: verify slot from chunk entry method
        # NOTE: slot is at PtrA offset +0x1D (= pa+29). pa+25 is inside AABB max Z.
        slot_from_chunk_entry = raw_orig[pa + 0x1D] if pa > 0 else 0
        raw_tail = raw_orig[pa + 4 : pa + 36]
        # raw_tail[20:26] covers AABB max Z tail + 0x00 byte + slot byte
        # print(f"  DEBUG: Chunk {ci} from chunk entry: pa=0x{pa:06X}, slot@{pa+0x1D}={slot_from_chunk_entry}, raw_tail[20:26]={raw_tail[20:26].hex()}, raw_tail[16:30].hex()={raw_tail[16:30].hex()}")

        prim_type   = raw_orig[cp + 8]
        fmt2        = raw_orig[cp + 9]
        gx_attr_blk = bytes(raw_orig[cp + 12 : cp + 20])

        orig_chunk_records.append({
            'name':        ptra_nm,
            'prim_type':   prim_type,
            'fmt2':        fmt2,
            'gx_attr_blk': gx_attr_blk,
            'sb':          bool(fmt2 & 2),
            'hc':          bool(gx_attr_blk[6] & 0x10),
            'hu':          bool(gx_attr_blk[6] & 0x80),
            'ptra_tail':   ptra_tail,
        })

    # Derive the default PtrA name for new chunks by taking the most-common
    # name across all original chunk records (e.g. "none" for lord body).
    # This keeps the string pool clean — new chunks follow the same convention
    # as the original model rather than introducing a new placeholder string.
    if orig_chunk_records:
        name_freq = {}
        for r in orig_chunk_records:
            name_freq[r['name']] = name_freq.get(r['name'], 0) + 1
        default_new_chunk_name = max(name_freq, key=name_freq.get)
    else:
        default_new_chunk_name = 'none'

    # Debug: show original chunk tails with raw bytes
    # print(f"\n=== ORIGINAL CHUNK TAILS ===")
    # for ci, rec in enumerate(orig_chunk_records):
    #     tail = rec['ptra_tail']
    #     slot = tail[25] if len(tail) > 25 else 0  # tail[25] = PtrA offset 0x1D = slot
    #     print(f"  Chunk {ci}: slot={slot}, tail bytes[20:26]={tail[20:26].hex()}, tail full={tail.hex()}")

    # Find the highest display-list slot index used by existing PtrA blocks so
    # new chunks can assign the next available slot number.
    # Use the slot values already stored in orig_chunk_records (ptra_tail[25])
    max_ptra_slot = -1
    for rec in orig_chunk_records:
        slot = rec['ptra_tail'][25] if len(rec['ptra_tail']) > 25 else 0  # ptra_tail[25] = PtrA offset 0x1D = slot
        if slot > max_ptra_slot:
            max_ptra_slot = slot
    # print(f"  DEBUG: max_ptra_slot (from orig_chunk_records) = {max_ptra_slot}")

    # Debug: show original slots for each chunk
    # print(f"\n=== ORIGINAL CHUNK SLOTS ===")
    # for ci, rec in enumerate(orig_chunk_records):
    #     tail = rec['ptra_tail']
    #     slot = tail[25] if len(tail) > 25 else 0  # tail[25] = PtrA offset 0x1D = slot
    #     print(f"  Chunk {ci}: original slot = {slot}, name = {rec['name']!r}, bytes[20:26]={tail[20:26].hex()}")

    # Detect whether original GX caches use FE10's 0x20-byte padded format.
    fe10_padded = False
    for ci in range(n_orig_chunks):
        cp         = chunk_list_addr + ci * 32
        gc_ptr_raw = struct.unpack_from('>I', raw_orig, cp + 28)[0]
        if gc_ptr_raw:
            gc_addr     = gc_ptr_raw + BASE
            n_pal       = raw_orig[gc_addr + 1]
            gc_raw_size = 2 + n_pal
            if (gc_raw_size < 0x20
                    and all(b == 0 for b in
                            raw_orig[gc_addr + gc_raw_size : gc_addr + 0x20])):
                fe10_padded = True
            break   # one sample is sufficient

    # ── Vertex group map (needed for bone palette building per chunk) ─────────
    #
    # Map every vertex to the vertex group index it is most strongly weighted to.
    # Used ONLY for building GX cache bone palettes and sb_byte values inside
    # display lists — NOT used to assign faces to chunks.

    # vert_group_map stores only the best (highest-weighted) vgroup per vertex.
    # For GX palette building, we need ALL bones affecting vertices in a chunk,
    # not just the best one per vertex.
    vert_group_map = {}   # vertex index → vgroup list-index (best only, for display list)
    vgroups = mesh_obj.vertex_groups
    for v in mesh.vertices:
        best_gi = None
        best_wt = -1.0
        for vge in v.groups:
            if vge.weight > best_wt:
                best_wt = vge.weight
                best_gi = vge.group
        if best_gi is not None:
            vert_group_map[v.index] = best_gi

    # v27.0: Build ALL bones per vertex for GX palette (not just best)
    # This is needed because a chunk's GX palette must contain ALL bones that
    # any vertex in that chunk is weighted to, not just the highest-weighted.
    vert_all_bones = {}  # vertex index → list of bone_ids (all vgroups, for palette)
    for v in mesh.vertices:
        bone_ids_for_v = []
        for vge in v.groups:
            bid = bone_id_by_vgroup_idx.get(vge.group, bone_id_by_name.get(vgroups[vge.group].name, None))
            if bid is not None:
                bone_ids_for_v.append(bid)
        if bone_ids_for_v:
            vert_all_bones[v.index] = bone_ids_for_v

    # ── Derive chunk list from original face ranges + new faces ──────────────
    #
    # Original chunks are defined by the face ranges stored in gs_original_data
    # (chunk_face_starts / chunk_face_counts).  These map directly to the chunk
    # descriptors in the original binary, so the chunk count and face assignment
    # are faithful to the file format regardless of how Blender vertex groups
    # are named or weighted.
    #
    # Any face whose index is not covered by any original range is new geometry
    # added by the user.  New faces are grouped by poly.material_index — one
    # extra chunk per unique material slot among those faces.

    # ── Derive chunk list from fe_chunk_index face attribute ─────────────────
    #
    # Each face was labelled at import time with its original chunk index via
    # the "fe_chunk_index" integer face attribute.  This label survives vertex
    # and face deletion because Blender tracks per-face attributes by face
    # identity, not by absolute index position.
    #
    # Faces with fe_chunk_index == -1 are new geometry added by the user;
    # they are handled by the new-geometry merging block further below.
    #
    # We read the attribute directly into chunk_face_lists, one list per
    # original chunk.  n_orig_face_chunks is the number of original chunks
    # stored in gs_original_data (len of chunk_face_starts).

    orig_face_starts = gs.get('chunk_face_starts', [])
    orig_face_counts = gs.get('chunk_face_counts', [])
    n_orig_face_chunks = len(orig_face_starts)

    n_mesh_faces = len(mesh.polygons)

    # Read fe_chunk_index attribute
    chunk_attr = mesh.attributes.get("fe_chunk_index")

    # Blender's Join operation always appends new geometry at the end of the
    # existing mesh's polygon array.  Any polygon with index >= gs_orig_poly_count
    # was added after import (either by the user or by joining another mesh) and
    # must be treated as new geometry regardless of what its fe_chunk_index says.
    # This is the primary split between "original" and "new" faces.
    gs_orig_poly_count = mesh_obj.get('gs_orig_poly_count', None)

    if chunk_attr is not None:
        # Attribute exists — use it.  Initialise one list per original chunk.
        # Values are stored as (ci + 1): 0 = unclaimed/new, 1 = chunk 0, etc.
        # This ensures Blender's default of 0 for newly-added faces is treated
        # as new geometry rather than silently falling into chunk 0.
        chunk_face_lists = [[] for _ in range(n_orig_face_chunks)]
        new_faces_unclaimed = []   # faces with stored value 0 (new geometry)
        for poly in mesh.polygons:
            # Primary check: polygon index beyond original import count → new.
            if gs_orig_poly_count is not None and poly.index >= gs_orig_poly_count:
                new_faces_unclaimed.append(poly.index)
                continue
            stored = chunk_attr.data[poly.index].value
            ci = stored - 1   # decode: 0→-1 (new), 1→0, 2→1, …
            if 0 <= ci < n_orig_face_chunks:
                chunk_face_lists[ci].append(poly.index)
            else:
                new_faces_unclaimed.append(poly.index)
        n_culled = sum(orig_face_counts) - sum(len(fl) for fl in chunk_face_lists)
        print(f"  [Chunk build] Using fe_chunk_index attribute: "
              f"{n_orig_face_chunks} orig chunks, {len(new_faces_unclaimed)} unclaimed faces")
        # Emit per-chunk counts for diagnostics
        for ci, fl in enumerate(chunk_face_lists):
            if len(fl) != orig_face_counts[ci]:
                print(f"    Chunk {ci}: {len(fl)} faces "
                      f"(orig={orig_face_counts[ci]}, "
                      f"diff={orig_face_counts[ci]-len(fl)} deleted)")
    else:
        # Fallback for meshes imported before v0.25.6: use the old index-range
        # method.  This is correct only when no geometry has been deleted.
        n_culled = mesh_obj.get('gs_culled_faces', 0)
        total_orig_faces = sum(orig_face_counts)
        # gs_orig_poly_count is more reliable than the index-range method when
        # available: it captures the exact face count at import time regardless
        # of culled faces.
        if gs_orig_poly_count is not None:
            first_new_idx = gs_orig_poly_count
        else:
            first_new_idx = total_orig_faces - n_culled
        new_faces_unclaimed = []
        chunk_face_lists = []
        for ci, (fs, fc) in enumerate(zip(orig_face_starts, orig_face_counts)):
            face_list = [fi for fi in range(fs, fs + fc) if fi < n_mesh_faces]
            chunk_face_lists.append(face_list)
        for fi in range(n_mesh_faces):
            if fi >= first_new_idx:
                new_faces_unclaimed.append(fi)
        print(f"  [Chunk build] Fallback index-range method (no fe_chunk_index attr)")

    print(f"  DEBUG: n_culled faces = {n_culled} (total_orig={sum(orig_face_counts)}, mesh_faces={n_mesh_faces})")

    # ── v26.1: Read GX caches to determine which bone each chunk uses ───────────────
    # Read the bone palette (GX cache) from each original chunk to map bones to chunks.
    def read_chunk_palette(chunk_entry_ptr):
        rel = struct.unpack_from('>I', raw_orig, chunk_entry_ptr + 28)[0]
        palette_ptr = rel + BASE if rel > 0 else 0
        if palette_ptr >= len(raw_orig) or raw_orig[palette_ptr] != 0x10:
            return None
        n = raw_orig[palette_ptr + 1]
        if palette_ptr + 2 + n > len(raw_orig):
            return None
        
        # Calculate original padded size (to 0x20, except last GC)
        raw_size = 2 + n
        padded_size = raw_size + (0x20 - raw_size) if raw_size < 0x20 else raw_size
        
        return [raw_orig[palette_ptr + 2 + i] for i in range(n)], padded_size

    chunk_palettes = {}  # chunk_index -> list of bone_ids
    chunk_palette_sizes = {}  # chunk_index -> padded size
    for ci in range(n_orig_chunks):
        cp = chunk_list_addr + ci * 32
        result = read_chunk_palette(cp)
        if result:
            palette, padded_size = result
            chunk_palettes[ci] = palette
            chunk_palette_sizes[ci] = padded_size
            # print(f"  DEBUG: Chunk {ci} GX palette = {palette} (padded size: {padded_size})")

    # Build bone -> chunk mapping by checking if bone is IN the palette
    bone_to_chunk = {}
    for ci, palette in chunk_palettes.items():
        for bone_id in palette:
            if bone_id not in bone_to_chunk:
                bone_to_chunk[bone_id] = ci
    
    # print(f"  DEBUG: bone_to_chunk (any palette position) = {bone_to_chunk}")

    # ── v26.1: Collect and merge new faces ─────────────────────────────────────────
    # If new geometry uses an existing bone, merge into that chunk instead of creating new chunk.
    all_vgroup_names = [vgroups[gi].name for gi in range(len(vgroups))]
    
    new_faces_by_bone = {}  # bone_id -> [face indices]
    new_faces_by_vgname = {}  # vgroup name -> [face indices] for debugging
    
    print(f"\n=== NEW GEOMETRY DETECTION DEBUG ===")
    for poly_index in new_faces_unclaimed:
        poly = mesh.polygons[poly_index]
        vi = poly.vertices[0]  # check first vertex for bone
        
        # Get all vertex groups on this vertex (not just the highest weighted)
        all_vgs_on_vertex = [(vge.group, vge.weight) for vge in mesh.vertices[vi].groups]
        
        found_bone_id = None
        found_vg_name = None
        
        # Iterate through all VGs on this vertex, find first one with a bone
        for gi, weight in all_vgs_on_vertex:
            bid = bone_id_by_vgroup_idx.get(gi, bone_id_by_name.get(vgroups[gi].name))
            if bid is not None:
                found_bone_id = bid
                found_vg_name = vgroups[gi].name
                break  # Found first bone, stop searching
        
        if found_bone_id is not None:
            if found_bone_id not in new_faces_by_bone:
                new_faces_by_bone[found_bone_id] = []
            new_faces_by_bone[found_bone_id].append(poly_index)
        else:
            # Debug: show which VGs didn't have bones
            vg_names_no_bone = [vgroups[gi].name for gi, _ in all_vgs_on_vertex]
            print(f"  Face {poly_index}: vertex {vi} has VGs {vg_names_no_bone}, no bone found")
        
        # Track by VG name for debug
        if found_vg_name:
            if found_vg_name not in new_faces_by_vgname:
                new_faces_by_vgname[found_vg_name] = []
            new_faces_by_vgname[found_vg_name].append(poly_index)

    print(f"  New faces by vertex group (with bones): {new_faces_by_vgname}")
    print(f"  New faces bone matches: {list(new_faces_by_bone.keys())}")

    for bone_id, face_list in new_faces_by_bone.items():
        target_ci = bone_to_chunk.get(bone_id)
        if target_ci is not None:
            chunk_face_lists[target_ci].extend(face_list)
            print(f"  Merged {len(face_list)} new faces into chunk {target_ci} (bone {bone_id})")
            # Debug: show position range of new faces AND full chunk
            new_verts = set()
            for fi in face_list:
                new_verts.update(mesh.polygons[fi].vertices)
            if new_verts:
                xs = [mesh.vertices[v].co.x for v in new_verts]
                ys = [mesh.vertices[v].co.y for v in new_verts]
                zs = [mesh.vertices[v].co.z for v in new_verts]
                print(f"    NEW geometry float bounds: X=[{min(xs):.2f}, {max(xs):.2f}], Y=[{min(ys):.2f}, {max(ys):.2f}], Z=[{min(zs):.2f}, {max(zs):.2f}]")
            # Show full chunk bounds after merge
            all_verts_in_chunk = set()
            for fi in chunk_face_lists[target_ci]:
                all_verts_in_chunk.update(mesh.polygons[fi].vertices)
            if all_verts_in_chunk:
                xs_all = [mesh.vertices[v].co.x for v in all_verts_in_chunk]
                ys_all = [mesh.vertices[v].co.y for v in all_verts_in_chunk]
                zs_all = [mesh.vertices[v].co.z for v in all_verts_in_chunk]
                print(f"    FULL CHUNK {target_ci} bounds after merge: X=[{min(xs_all):.2f}, {max(xs_all):.2f}], Y=[{min(ys_all):.2f}, {max(ys_all):.2f}], Z=[{min(zs_all):.2f}, {max(zs_all):.2f}]")
        else:
            chunk_face_lists.append(face_list)
            print(f"  Created NEW chunk for bone {bone_id} with {len(face_list)} faces")
            # Debug: print positions of vertices in this new chunk (Sword)
            new_chunk_verts = set()
            for fi in face_list:
                new_chunk_verts.update(mesh.polygons[fi].vertices)
            print(f"    New chunk vertex indices ({len(new_chunk_verts)} unique): {sorted(new_chunk_verts)}")
            for vi in sorted(new_chunk_verts):
                co = mesh.vertices[vi].co
                print(f"      vertex {vi}: ({co.x:.4f}, {co.y:.4f}, {co.z:.4f})")

    n_chunks = len(chunk_face_lists)

    if n_chunks == 0:
        return False, ("No faces found in mesh — cannot build chunk structure.")

    # ── Step 2: Build vertex / normal tables ──────────────────────────────────

    v_count = len(mesh.vertices)
    print(f"\n=== VERTEX COUNT DEBUG ===")
    print(f"  mesh.vertices count: {v_count}")
    print(f"  gs['vertex_count']: {gs.get('vertex_count', 'NOT SET')}")
    print(f"  Will use v_count = {v_count} for export")

    pos_bytes = bytearray()
    # Track AABB as vertices are added
    pos_min = [32767, 32767, 32767]
    pos_max = [-32767, -32767, -32767]
    for i in range(v_count):
        co = mesh.vertices[i].co
        x  = max(-32768, min(32767, round(co.x * vert_scale)))
        y  = max(-32768, min(32767, round(co.y * vert_scale)))
        z  = max(-32768, min(32767, round(co.z * vert_scale)))
        pos_bytes += struct.pack('>hhh', x, y, z)
        pos_min[0] = min(pos_min[0], x)
        pos_min[1] = min(pos_min[1], y)
        pos_min[2] = min(pos_min[2], z)
        pos_max[0] = max(pos_max[0], x)
        pos_max[1] = max(pos_max[1], y)
        pos_max[2] = max(pos_max[2], z)

    print(f"\n=== VERTEX DEBUG ===")
    print(f"  Total vertices: {v_count}")
    print(f"  Raw coord range: X=[{pos_min[0]}, {pos_max[0]}], Y=[{pos_min[1]}, {pos_max[1]}], Z=[{pos_min[2]}, {pos_max[2]}]")
    print(f"  Float range (scale={vert_scale}): X=[{pos_min[0]/vert_scale:.2f}, {pos_max[0]/vert_scale:.2f}], Y=[{pos_min[1]/vert_scale:.2f}, {pos_max[1]/vert_scale:.2f}], Z=[{pos_min[2]/vert_scale:.2f}, {pos_max[2]/vert_scale:.2f}]")

    # Deduplicate normals at int8 storage precision (same idea as UV dedup).
    # Two vertices whose rounded (nx, ny, nz) are identical share one table entry.
    nrm_table      = []          # list of (nx_i8, ny_i8, nz_i8) unique normals
    nrm_key_to_idx = {}          # (nx_i8, ny_i8, nz_i8) → index in nrm_table
    vert_to_nrm_idx = [0] * v_count   # vertex index → normal table index

    for i in range(v_count):
        n  = mesh.vertices[i].normal
        nx = max(-128, min(127, round(n.x * norm_scale)))
        ny = max(-128, min(127, round(n.y * norm_scale)))
        nz = max(-128, min(127, round(n.z * norm_scale)))
        key = (nx, ny, nz)
        if key not in nrm_key_to_idx:
            nrm_key_to_idx[key] = len(nrm_table)
            nrm_table.append(key)
        vert_to_nrm_idx[i] = nrm_key_to_idx[key]

    n_count   = len(nrm_table)
    nrm_bytes = bytearray()
    for (nx, ny, nz) in nrm_table:
        nrm_bytes += struct.pack('>bbb', nx, ny, nz)
    # Pad to 4-byte boundary so the UV table is 4-byte aligned.
    nrm_pad = (4 - len(nrm_bytes) % 4) % 4
    nrm_bytes += b'\x00' * nrm_pad

    # ── Step 3: Build UV table and loop_uv_arr ───────────────────────────────
    #
    # loop_uv_arr[li] → original UV table index for loop li.
    #
    # SOURCE PRIORITY:
    #   1. fe_loop_uv_index per-loop attribute (v0.25.6+): survives face deletion
    #      correctly.  Each loop carries its original UV index regardless of
    #      whether earlier faces were deleted.
    #   2. loop_uv_indices flat JSON list (legacy, v0.25.5 and earlier): only
    #      correct when no faces have been deleted since import.
    #   3. Fallback: deduplicate Blender UV coordinates to synthesise indices.
    #      Used for meshes imported before the UV index machinery existed.

    UV_ROUND = 8

    uvl           = mesh.uv_layers.active
    uv_table      = []
    uv_key_to_idx = {}

    # Always build the Blender-UV-coordinate dedup table so we can write
    # UV bytes for the UV table section, even if loop_uv_arr comes from the attribute.
    if uvl:
        uv_data_len = len(uvl.data)
        for poly in mesh.polygons:
            for li in poly.loop_indices:
                raw_uv = uvl.data[li].uv if li < uv_data_len else (0.0, 0.0)
                key = (round(float(raw_uv[0]), UV_ROUND),
                       round(float(raw_uv[1]), UV_ROUND))
                if key not in uv_key_to_idx:
                    uv_key_to_idx[key] = len(uv_table)
                    uv_table.append(key)
    else:
        uv_table = [(0.0, 0.0)]

    uv_count = len(uv_table)
    original_uv_count = mesh_obj.get('gs_uv_count', uv_count)

    print(f"\n=== UV DEBUG ===")
    print(f"  UV count after deduplication: {uv_count}")
    print(f"  Original UV count (from import): {original_uv_count}")

    # ── Establish UV scale/offset and read original UV table ─────────────────
    # These are needed both by the loop_uv_arr fallback (UV coordinate lookup)
    # and by the UV-bytes-for-export builder below.  Define them once here.
    orig_uv_count = mesh_obj.get('gs_uv_count', uv_count)
    uv_scale      = gs.get('uv_scale', 1)
    uv_offset     = gs.get('uv_offset', 0)

    # Read original UV table from raw_orig for seam-safe closest-value selection.
    orig_uv_table = {}
    if uv_offset > 0:
        for i in range(orig_uv_count):
            pos = uv_offset + i * 4
            if pos + 4 <= len(raw_orig):
                u_raw = struct.unpack_from('>h', raw_orig, pos)[0]
                v_raw = struct.unpack_from('>h', raw_orig, pos + 2)[0]
                orig_uv_table[i] = (u_raw, v_raw)

    # Build loop_uv_arr — maps each loop index li → original UV table index.
    loop_uv_arr = {}   # li → orig_uv_idx

    # Source 1: gs_loop_uv_indices stored on the mesh object (v0.25.6+)
    # This is a flat list in polygon/loop order from import.
    # It is valid when the list length matches the current total loop count
    # (i.e. no faces have been deleted since import).  If faces were deleted
    # the list is stale and we fall through to the seam-safe UV lookup.
    import json as _json_uv
    _stored_loop_uv = mesh_obj.get('gs_loop_uv_indices', None)
    if _stored_loop_uv is not None:
        try:
            _stored = _json_uv.loads(str(_stored_loop_uv))
        except Exception:
            _stored = []
    else:
        # Legacy: check inside gs_original_data (v0.25.5 and earlier)
        _stored = gs.get('loop_uv_indices', [])

    _n_loops_current = sum(p.loop_total for p in mesh.polygons)

    # Pre-initialize lookup dict used in the UV fix section below.
    _float_to_orig = {}

    if _stored and len(_stored) == _n_loops_current:
        # Exact length match — list aligns with current loops; use directly.
        flat_i = 0
        for poly in mesh.polygons:
            for li in poly.loop_indices:
                loop_uv_arr[li] = _stored[flat_i]
                flat_i += 1
        print(f"  Using stored loop_uv_indices ({len(_stored)} entries, exact match)")
    else:
        # Length mismatch — faces were deleted, stored list is stale.
        # Fall back to seam-safe UV coordinate lookup: for each loop, find
        # the original UV table entry whose float value is closest to the
        # current Blender UV coordinate.  This is less precise than the stored
        # index (can't distinguish genuinely identical UV values), but is
        # correct for all practical cases since the UV table has unique entries.
        if _stored:
            print(f"  WARNING: stored loop_uv_indices length {len(_stored)} "
                  f"!= current loops {_n_loops_current} — faces were deleted, "
                  f"falling back to UV coordinate lookup")
        else:
            print(f"  No stored loop_uv_indices — using UV coordinate lookup")

        if uvl and orig_uv_table:
            # Build a lookup from float UV value (rounded) → original UV index.
            # Use orig_uv_table (raw file values converted to float) so the
            # lookup keys match what Blender stored when we set uvl.data[li].uv.
            _float_to_orig = {}
            for _oi, (u_raw, v_raw) in orig_uv_table.items():
                _uf = round(u_raw / uv_scale, 6)
                _vf = round(1.0 - v_raw / uv_scale, 6)
                _float_to_orig[(_uf, _vf)] = _oi

            # Extended UV table for new/edited UV values not in orig_uv_table.
            # Maps float key → new index (>= orig_uv_count).
            _new_uv_slots = {}   # float_key → allocated index
            _next_new_ui  = orig_uv_count   # first slot beyond original table

            for poly in mesh.polygons:
                for li in poly.loop_indices:
                    bl_uv = uvl.data[li].uv if li < len(uvl.data) else (0.0, 0.0)
                    key = (round(float(bl_uv[0]), 6), round(float(bl_uv[1]), 6))
                    if key in _float_to_orig:
                        loop_uv_arr[li] = _float_to_orig[key]
                    else:
                        # UV was edited — allocate a new slot.
                        if key not in _new_uv_slots:
                            _new_uv_slots[key] = _next_new_ui
                            _next_new_ui += 1
                        loop_uv_arr[li] = _new_uv_slots[key]

            if _new_uv_slots:
                print(f"  UV fallback: allocated {len(_new_uv_slots)} new slots "
                      f"for edited UVs (indices {orig_uv_count}..{_next_new_ui-1})")
                # Store new UV entries so the UV table writer includes them.
                # orig_uv_count is updated to cover the extended range.
                orig_uv_count = _next_new_ui
                for (uf, vf), new_idx in sorted(_new_uv_slots.items(), key=lambda x: x[1]):
                    orig_uv_table[new_idx] = (
                        round(uf * uv_scale),
                        round((1.0 - vf) * uv_scale),
                    )
                # Update the stored count so the header reflects new UV count.
                mesh_obj['gs_uv_count'] = orig_uv_count
        else:
            for poly in mesh.polygons:
                for li in poly.loop_indices:
                    loop_uv_arr[li] = 0
        print(f"  UV coordinate lookup mapped {len(loop_uv_arr)} loops")

    print(f"  loop_uv_arr sample (first 10 li values): "
          f"{[loop_uv_arr.get(i, '?') for i in range(10)]}")

    # ── Build color table and loop_color_arr ─────────────────────────────────
    col_table = []
    col_key_to_idx = {}
    loop_color_arr = {}
    col_bytes = bytearray()
    col_count = 0

    if vc_mode in ('BLENDER', 'WHITE'):
        if vc_mode == 'WHITE':
            col_key_to_idx[(255, 255, 255, 255)] = 0
            col_table = [bytearray([255, 255, 255, 255])]
            for poly in mesh.polygons:
                for li in poly.loop_indices:
                    loop_color_arr[li] = 0
            print(f"  White vertex color table (1 entry) for {len(loop_color_arr)} loops")
        else:  # BLENDER
            _col_attr = mesh.color_attributes.get("Col")
            if _col_attr:
                for poly in mesh.polygons:
                    for li in poly.loop_indices:
                        r, g, b, a = _col_attr.data[li].color
                        key = (round(r * 255), round(g * 255), round(b * 255), round(a * 255))
                        if key not in col_key_to_idx:
                            col_key_to_idx[key] = len(col_table)
                            col_table.append(bytearray(key))
                        loop_color_arr[li] = col_key_to_idx[key]
                print(f"  Blender vertex color table: {len(col_table)} unique entries for {len(loop_color_arr)} loops")
            else:
                print(f"  WARNING: No color attribute found on mesh, using index 0 for all")
                for poly in mesh.polygons:
                    for li in poly.loop_indices:
                        loop_color_arr[li] = 0
                if not col_table:
                    col_table = [bytearray([255, 255, 255, 255])]
                    col_key_to_idx[(255, 255, 255, 255)] = 0

        col_count = len(col_table)
        for c in col_table:
            col_bytes += c

        print(f"  Color table: {col_count} entries, {len(col_bytes)} bytes")

    # ── Fix loop_uv_arr for modified UVs ──────────────────────────────────────
    # When UVs are scaled in Blender, loop_uv_arr may point to wrong original indices.
    # We need to detect this and update loop_uv_arr to point to correct UV slots.
    # This runs unconditionally after loop_uv_arr is built (whether from stored or fallback).
    # Also sets uv_was_modified flag to force greedy mode (original-order mode would use stale orig_ui).
    uv_was_modified = False
    if uvl and orig_uv_table:
        # Extended UV table for new/edited UV values
        _new_uv_slots = {}   # float_key → allocated index
        _next_new_ui  = max(orig_uv_count, len(orig_uv_table))
        
        fix_count = 0
        for poly in mesh.polygons:
            for li in poly.loop_indices:
                orig_idx = loop_uv_arr.get(li, 0)
                blender_uv = tuple(uvl.data[li].uv) if li < len(uvl.data) else (0.0, 0.0)
                bl_key = (round(float(blender_uv[0]), 6), round(float(blender_uv[1]), 6))
                
                # Check if the original mapping is still correct
                if orig_idx in orig_uv_table:
                    u_raw, v_raw = orig_uv_table[orig_idx]
                    orig_u = round(u_raw / uv_scale, 6)
                    orig_v = round(1.0 - (v_raw / uv_scale), 6)
                    # If Blender UV doesn't match what orig_idx should be, fix it
                    if bl_key != (orig_u, orig_v):
                        uv_was_modified = True  # Force greedy mode later
                        # Find correct existing index or allocate new one
                        if bl_key in _float_to_orig:
                            loop_uv_arr[li] = _float_to_orig[bl_key]
                        else:
                            if bl_key not in _new_uv_slots:
                                _new_uv_slots[bl_key] = _next_new_ui
                                orig_uv_table[_next_new_ui] = (
                                    round(blender_uv[0] * uv_scale),
                                    round((1.0 - blender_uv[1]) * uv_scale)
                                )
                                _next_new_ui += 1
                                fix_count += 1
                                if fix_count <= 10:
                                    print(f"  FIXED UV: li={li}, orig_idx={orig_idx} -> "
                                          f"new slot, blender=({blender_uv[0]:.4f}, {blender_uv[1]:.4f})")
                            loop_uv_arr[li] = _new_uv_slots[bl_key]
        
        if _new_uv_slots:
            print(f"  Fixed {fix_count} UV mappings, allocated {len(_new_uv_slots)} new slots")
            orig_uv_count = _next_new_ui
            mesh_obj['gs_uv_count'] = orig_uv_count
        if uv_was_modified:
            print(f"  UV was modified (scaled/edited) — will use greedy mode for all chunks")

    print(f"\n=== UV DEBUG ===")
    print(f"  UV count after deduplication: {uv_count}")
    print(f"  Original UV count (from import): {original_uv_count}")
    print(f"  UV scale: {uv_scale}")
    print(f"  Unique UV keys found: {len(uv_key_to_idx)}")
    print(f"  loop_uv_arr entries: {len(loop_uv_arr)}")

    # ── Build UV data for export ──────────────────────────────────────────────
    # The UV table has orig_uv_count entries (from the original file header).
    # For each original UV index, we need the correct Blender UV value.
    # We collect all Blender UV values seen for each original index, then pick
    # the one closest to the original file value (seam-safe, v0.25.5 fix).
    # (orig_uv_count, uv_scale, uv_offset, orig_uv_table defined above)

    print(f"  Building UV data: orig_uv_count={orig_uv_count}, "
          f"uv_offset={uv_offset}, uv_scale={uv_scale}")

    # Rebuild orig_uv_candidates with corrected loop_uv_arr (after the fix above)
    orig_uv_candidates = {}   # orig_idx → list of Blender UV tuples
    if uvl:
        for poly in mesh.polygons:
            for li in poly.loop_indices:
                orig_idx  = loop_uv_arr.get(li, 0)
                blender_uv = tuple(uvl.data[li].uv) if li < len(uvl.data) else (0.0, 0.0)
                if orig_idx not in orig_uv_candidates:
                    orig_uv_candidates[orig_idx] = []
                orig_uv_candidates[orig_idx].append(blender_uv)
    
    # Build orig_uv_to_blender mapping
    # For each orig_idx, use the original UV coordinates from orig_uv_table
    # (which was already updated with corrected values during the fix above)
    orig_uv_to_blender = {}
    for orig_idx, candidates in orig_uv_candidates.items():
        if orig_idx in orig_uv_table:
            u_raw, v_raw = orig_uv_table[orig_idx]
            orig_u = u_raw / uv_scale
            orig_v = 1.0 - (v_raw / uv_scale)
            orig_uv_to_blender[orig_idx] = (orig_u, orig_v)
        elif candidates:
            # New index - use Blender UV
            orig_uv_to_blender[orig_idx] = candidates[0]
        else:
            orig_uv_to_blender[orig_idx] = (0.0, 0.0)

    uv_bytes = bytearray()
    # Write entries for 0..orig_uv_count-1 (original range)
    for ui in range(orig_uv_count):
        if ui in orig_uv_to_blender:
            uv = orig_uv_to_blender[ui]
            u  = max(-32768, min(32767, int(round(uv[0] * uv_scale))))
            v  = max(-32768, min(32767, int(round((1.0 - uv[1]) * uv_scale))))
        elif ui in orig_uv_table:
            u, v = orig_uv_table[ui]
        else:
            u, v = 0, 0
        uv_bytes += struct.pack('>hh', u, v)
        if uv_offset > 0 and uv_offset + ui * 4 + 4 <= len(raw_orig):
            struct.pack_into('>hh', raw_orig, uv_offset + ui * 4, u, v)
    
    # Write entries for new UV indices (>= orig_uv_count)
    # These were added during the fallback for edited UVs
    if orig_uv_count < len(orig_uv_table):
        print(f"  Writing additional {len(orig_uv_table) - orig_uv_count} UV entries for edited UVs")
        for ui in range(orig_uv_count, len(orig_uv_table)):
            if ui in orig_uv_to_blender:
                uv = orig_uv_to_blender[ui]
                u  = max(-32768, min(32767, int(round(uv[0] * uv_scale))))
                v  = max(-32768, min(32767, int(round((1.0 - uv[1]) * uv_scale))))
            elif ui in orig_uv_table:
                u, v = orig_uv_table[ui]
            else:
                u, v = 0, 0
            uv_bytes += struct.pack('>hh', u, v)
            if uv_offset > 0 and uv_offset + ui * 4 + 4 <= len(raw_orig):
                struct.pack_into('>hh', raw_orig, uv_offset + ui * 4, u, v)

    print(f"  Built {len(uv_bytes)//4} UV entries")

    # Debug: verify addon UV range is in uv_bytes
    print(f"  UV bytes buffer size: {len(uv_bytes)} bytes ({len(uv_bytes)//4} entries)")
    #
    # Character display list format (prim_type=0x38, fmt2=0x0E, sb=True):
    #
    #   Each face (triangle) is written as one GX DRAW_TRIANGLE_STRIP call
    #   covering 3 vertices:
    #
    #     0x98          — GX_DRAW_TRIANGLE_STRIP command byte
    #     uint16 BE = 3 — vertex count for this draw call
    #     Per vertex (7 bytes):
    #       1 byte  sb_byte  = palette_slot × 3
    #       2 bytes pos_idx  (uint16 BE = Blender vertex index)
    #       2 bytes nrm_idx  (uint16 BE = index into deduplicated normal table)
    #       2 bytes uv_idx   (uint16 BE = index into the UV table)
    #
    # The palette_slot is the bone's position in this chunk's GX cache list.
    # Single-bone chunks always use slot 0, so sb_byte = 0x00.
    #
    # Character defaults for new chunks:
    CHAR_PRIM    = 0x38
    CHAR_FMT2    = 0x0E
    if vc_mode == 'NONE':
        CHAR_GX_ATTR = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46, 0x01])
    else:
        CHAR_GX_ATTR = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x56, 0x01])

    def build_display_list(face_indices, chunk_bone_ids, use_sb=True, hc=False, hu=False,
                           orig_vert_tuples=None, orig_strip_lengths=None,
                           orig_to_blender_map=None):
        """Build the GX display list bytes for one chunk.

        Two modes depending on whether original DL data is available:

        ORIGINAL-ORDER MODE (orig_vert_tuples is not None):
          Replays the original file's DL exactly — same (vi, ni, ui) per
          occurrence, same strip structure.  This is the round-trip path.
          Only the sb_byte is re-derived from the current Blender mesh bone
          weights (it cannot change for original geometry).
          The pos_idx (vi) written is the ORIGINAL file's vertex index, which
          is valid because the new vertex table is built in the same Blender
          vertex order that the original file used.
          Falls back to greedy mode if any orig_vi in the tuple list has no
          corresponding Blender vertex (i.e. geometry was deleted).

        GREEDY-BUILDER MODE (orig_vert_tuples is None, or fallback):
          Builds triangle strips from the current Blender mesh using a greedy
          greedy algorithm.  Handles seam vertices correctly by keying the
          full (sb, pos_idx, nrm_idx, uv_idx) tuple — two face-corners with
          the same geometric vertex but different UV/normal indices are treated
          as distinct DL vertices and never merged into the same strip.  This
          is the path for new geometry and for geometry with removed vertices.

        Parameters
        ----------
        face_indices      : list of Blender polygon indices in this chunk
        chunk_bone_ids    : ordered palette [bone_id, ...]
        use_sb / hc / hu  : vertex format flags from original chunk record
        orig_vert_tuples  : flat list of (vi, ni, ui, ci) in original DL order,
                            or None for greedy mode
        orig_strip_lengths: list of strip vertex counts (parallel to tuples),
                            required when orig_vert_tuples is provided
        orig_to_blender_map: {orig_vi: [bl_vi, ...]} for sb_byte lookup
        """
        bone_id_to_slot = {bid: si for si, bid in enumerate(chunk_bone_ids)}

        # ── ORIGINAL-ORDER MODE ───────────────────────────────────────────────
        if orig_vert_tuples is not None and orig_strip_lengths is not None:
            # Build orig_vi -> (sb_byte, bl_vi) lookup from current mesh.
            #
            # pos_idx written to DL must be the CURRENT Blender vertex index
            # (bl_vi), NOT the original file index (orig_vi).  The vertex table
            # is always built from current mesh.vertices in Blender order.
            # For a round-trip with no deletions, bl_vi == orig_vi because
            # no renumbering occurred.  After vertex deletion Blender renumbers
            # survivors, so orig_vi and bl_vi diverge — writing orig_vi would
            # index into the wrong position in the new (shorter) vertex table.
            #
            # nrm_idx is similarly re-derived from vert_to_nrm_idx[bl_vi]
            # because the normal table is rebuilt from the current mesh.
            #
            # uv_idx (orig_ui) is kept verbatim: the UV table is preserved
            # from the original file with the same content and same indices.
            #
            # orig_to_blender_map[orig_vi] = [bl_vi, ...] — guaranteed non-empty
            # for all orig_vi when we reach this mode (the 'missing' check in the
            # caller ensures any chunk with a missing orig_vi falls back to greedy).

            orig_vi_to_bl = {}   # orig_vi → (sb_byte, bl_vi)
            for orig_vi, bl_vis in orig_to_blender_map.items():
                if not bl_vis:
                    continue
                bl_vi = bl_vis[0]
                gi = vert_group_map.get(bl_vi)
                if gi is not None:
                    bid = bone_id_by_vgroup_idx.get(gi, bone_id_by_name.get(vgroups[gi].name, 0))
                else:
                    bid = 0
                slot = bone_id_to_slot.get(bid, 0)
                orig_vi_to_bl[orig_vi] = (slot * 3, bl_vi)

            dl = bytearray()
            idx = 0
            for strip_len in orig_strip_lengths:
                dl += b'\x98'
                dl += struct.pack('>H', strip_len)
                for _ in range(strip_len):
                    if idx >= len(orig_vert_tuples):
                        break
                    tup = orig_vert_tuples[idx]
                    orig_vi, orig_ni, orig_ui = tup[0], tup[1], tup[2]
                    orig_ci = tup[3] if len(tup) > 3 else 0
                    idx += 1
                    sb_byte, bl_vi = orig_vi_to_bl.get(orig_vi, (0, orig_vi))
                    nrm_idx = vert_to_nrm_idx[bl_vi] if bl_vi < len(vert_to_nrm_idx) else 0
                    if use_sb:
                        dl += struct.pack('>B', sb_byte)
                    dl += struct.pack('>H', bl_vi)      # current vertex table index
                    dl += struct.pack('>H', nrm_idx)    # current normal table index
                    if hc:
                        dl += struct.pack('>H', orig_ci)
                    dl += struct.pack('>H', orig_ui)    # original UV table index (preserved)
                    if hu:
                        dl += b'\x00\x00'
            pad = (32 - len(dl) % 32) % 32
            dl += b'\x00' * pad
            return bytes(dl)

        # ── GREEDY-BUILDER MODE ───────────────────────────────────────────────
        #
        # Step 1: compute full (sb_byte, pos_idx, nrm_idx, uv_idx) tuple per
        # face corner.  Keying edge_face on the full tuple means UV seams
        # correctly break strip extension — two corners with the same pos_idx
        # but different uv_idx are treated as distinct DL vertices.
        #
        # pos_idx and nrm_idx are Blender vertex/normal indices, which index
        # into the vertex and normal tables that the exporter builds from the
        # current Blender mesh.  For new geometry this is correct; for original
        # geometry that lost vertices the indices have shifted, which is why
        # we only reach greedy mode when the original-order path is unavailable.

        use_original_palette_order = (ci < n_orig_face_chunks and ci in orig_palettes)

        face_vtx = {}   # face_index -> [(sb, pos, nrm, uv), (sb, pos, nrm, uv), (sb, pos, nrm, uv)]
        for fi in face_indices:
            poly = mesh.polygons[fi]
            verts = []
            for corner, vi in enumerate(poly.vertices):
                li = poly.loop_start + corner
                if use_original_palette_order:
                    gi = vert_group_map.get(vi)
                    if gi is not None:
                        bid = bone_id_by_vgroup_idx.get(gi, bone_id_by_name.get(vgroups[gi].name, 0))
                    else:
                        bid = 0
                    slot = bone_id_to_slot.get(bid, 0)
                else:
                    all_bids = vert_all_bones.get(vi, [])
                    gi = vert_group_map.get(vi)
                    if gi is not None:
                        bid = bone_id_by_vgroup_idx.get(gi, bone_id_by_name.get(vgroups[gi].name, 0))
                    elif all_bids:
                        bid = all_bids[0]
                    else:
                        bid = 0
                    slot = bone_id_to_slot.get(bid, 0)
                col_idx = loop_color_arr.get(li, 0) if hc else 0
                verts.append((slot * 3, vi, vert_to_nrm_idx[vi], col_idx, loop_uv_arr.get(li, 0)))
            face_vtx[fi] = verts

        # Step 2: directed-edge adjacency keyed on full vertex tuples.
        edge_face = {}
        for fi in face_indices:
            verts = face_vtx[fi]
            for i in range(3):
                va = verts[i]
                vb = verts[(i + 1) % 3]
                edge_face[(va, vb)] = fi

        # Step 3: greedy strip building.
        visited = set()
        strips  = []

        for fi in face_indices:
            if fi in visited:
                continue

            verts      = face_vtx[fi]
            best_strip = None

            for rot in range(3):
                v0 = verts[rot]
                v1 = verts[(rot + 1) % 3]
                v2 = verts[(rot + 2) % 3]
                strip        = [v0, v1, v2]
                temp_visited = {fi}

                while True:
                    n = len(strip)
                    if n % 2 == 1:
                        key = (strip[-1], strip[-2])
                    else:
                        key = (strip[-2], strip[-1])

                    next_fi = edge_face.get(key)
                    if next_fi is None or next_fi in visited or next_fi in temp_visited:
                        break

                    shared_pos = {strip[-2][1], strip[-1][1]}
                    cands = [v for v in face_vtx[next_fi] if v[1] not in shared_pos]
                    if len(cands) != 1:
                        break

                    strip.append(cands[0])
                    temp_visited.add(next_fi)

                if best_strip is None or len(strip) > len(best_strip):
                    best_strip        = strip
                    best_temp_visited = temp_visited

            visited.update(best_temp_visited)
            strips.append(best_strip)

        # Step 4: serialise strips.
        dl = bytearray()
        for strip in strips:
            dl += b'\x98'
            dl += struct.pack('>H', len(strip))
            for (sb, pos, nrm, col, uv) in strip:
                if use_sb:
                    dl += struct.pack('>B', sb)
                dl += struct.pack('>H', pos)
                dl += struct.pack('>H', nrm)
                if hc:
                    dl += struct.pack('>H', col)
                dl += struct.pack('>H', uv)
                if hu:
                    dl += b'\x00\x00'

        pad = (32 - len(dl) % 32) % 32
        dl += b'\x00' * pad
        return bytes(dl)

    def build_gx_cache(bone_ids, original_palette=None):
        """Build the GX cache (bone palette) block for one chunk.

        bone_ids — list of integer bone IDs in palette slot order.
        original_palette — if provided, use this exact palette (for original chunks)
        Returns bytes, or b'' if bone_ids is empty.
        
        Note: GX caches are padded to 0x20 bytes each, except the last one.
        The file layout handles spacing between sections elsewhere.
        """
        if not bone_ids:
            return b''
        
        # For original chunks, preserve the exact original palette
        if original_palette is not None:
            raw = bytes([0x10, len(original_palette)]) + bytes(original_palette)
            return raw
        
        # For new chunks: build from scratch with 0x20 padding (handled in file layout)
        raw = bytes([0x10, len(bone_ids)]) + bytes(bone_ids)
        return raw

    # Build per-chunk output records.
    chunks_out     = []
    next_ptra_slot = max_ptra_slot + 1

    # ── Addon mesh injection ─────────────────────────────────────────────────
    # Each addon mesh contributes its own vertices, normals, and UVs appended
    # after the main mesh's tables, plus one or more new chunks.
    #
    # Addon face vertex indices (0..N_addon-1) are remapped to the global
    # index space (v_count_main + 0 .. v_count_main + N_addon-1).  The greedy
    # strip builder receives remapped face lists that reference the global
    # vertex/normal tables directly.
    #
    # We process addon meshes before the main chunk loop so that chunk_face_lists,
    # vert_to_nrm_idx, v_count, and n_chunks are all final before the loop runs.

    # Track the current total vertex count (grows as addons are processed).
    _addon_vert_offset = v_count   # global vertex index for addon vertex 0

    if addon_mesh_objs:
        for addon_obj in addon_mesh_objs:
            if addon_obj is None or addon_obj.type != 'MESH':
                continue
            addon_mesh = addon_obj.data

            if len(addon_mesh.polygons) == 0:
                print(f"  [Addon] Skipping '{addon_obj.name}': no faces")
                continue

            print(f"  [Addon] Processing '{addon_obj.name}': "
                  f"{len(addon_mesh.vertices)} verts, {len(addon_mesh.polygons)} faces")
            
            # Debug: print materials on addon mesh
            if addon_mesh.materials:
                mat_names = [m.name if m else 'None' for m in addon_mesh.materials]
                print(f"  [Addon] Materials: {mat_names}")
            else:
                print(f"  [Addon] No materials assigned")
            
            # Debug: print vertex groups
            if addon_obj.vertex_groups:
                vg_names = [vg.name for vg in addon_obj.vertex_groups]
                print(f"  [Addon] Vertex groups: {vg_names}")
            else:
                print(f"  [Addon] No vertex groups")

            # Check if addon mesh has gs_original_data (from secondary vanilla mesh).
            addon_gs_json = addon_obj.get('gs_original_data')
            addon_has_gs_data = False
            addon_gs = None
            addon_orig_uv_table = {}   # orig_uv_idx → (u, v) in game coords
            addon_chunk_face_starts = []  # original chunk face starts
            addon_chunk_face_counts = []  # original chunk face counts
            addon_orig_bid_to_chunk = {}  # original bone ID → original chunk index
            addon_chunk_palettes = {}     # original chunk index → list of bone IDs
            if addon_gs_json:
                try:
                    addon_gs = json.loads(str(addon_gs_json))
                    addon_raw = bytearray(bytes.fromhex(addon_gs['file_data_hex']))
                    addon_uv_scale = 1 << addon_raw[0x7E]
                    addon_uv_off = addon_gs.get('uv_offset', 0)
                    addon_uv_cnt = addon_gs.get('uv_count', 0)
                    if addon_uv_cnt > 0:
                        addon_has_gs_data = True
                        for ui in range(addon_uv_cnt):
                            uv_ptr_off = addon_uv_off + 4 + ui * 8
                            if uv_ptr_off + 8 <= len(addon_raw):
                                pu = struct.unpack_from('>h', addon_raw, uv_ptr_off)[0]
                                pv = struct.unpack_from('>h', addon_raw, uv_ptr_off + 4)[0]
                                addon_orig_uv_table[ui] = (pu, pv)
                        print(f"    Loaded {addon_uv_cnt} original UVs from gs_original_data")
                    
                    # Parse original chunk structure and palettes
                    addon_chunk_face_starts = addon_gs.get('chunk_face_starts', [])
                    addon_chunk_face_counts = addon_gs.get('chunk_face_counts', [])
                    print(f"    Original chunks: {len(addon_chunk_face_starts)}")
                    
                    # Parse chunk palettes from binary - read GX cache for each chunk
                    addon_chunk_list_addr = addon_gs.get('chunk_list_addr', 0)
                    BASE = 0x20
                    if addon_chunk_list_addr > 0 and len(addon_raw) > addon_chunk_list_addr:
                        n_orig_chunks = len(addon_chunk_face_starts)
                        for ci in range(n_orig_chunks):
                            chunk_rec_off = addon_chunk_list_addr + ci * 48
                            if chunk_rec_off + 48 <= len(addon_raw):
                                # Read DL pointer to find GX cache after DL data
                                dl_ptr = struct.unpack_from('>I', addon_raw, chunk_rec_off + 24)[0]
                                dl_len = struct.unpack_from('>I', addon_raw, chunk_rec_off + 28)[0]
                                if dl_ptr > 0 and dl_len > 0:
                                    dl_end = dl_ptr + BASE + dl_len
                                    # GX cache comes after DL, aligned to 32 bytes
                                    gc_start = (dl_end + 31) & ~31
                                    if gc_start < len(addon_raw):
                                        try:
                                            gc_count = addon_raw[gc_start + 1] if gc_start + 1 < len(addon_raw) else 0
                                            if gc_count > 0 and gc_start + 2 + gc_count <= len(addon_raw):
                                                bone_ids = list(addon_raw[gc_start + 2 : gc_start + 2 + gc_count])
                                                addon_chunk_palettes[ci] = bone_ids
                                                for bid in bone_ids:
                                                    addon_orig_bid_to_chunk[bid] = ci
                                        except Exception as e:
                                            pass
                    
                    if addon_chunk_palettes:
                        print(f"    Chunk palettes: {dict((k, v) for k, v in addon_chunk_palettes.items())}")
                        print(f"    Bone → Chunk map: {addon_orig_bid_to_chunk}")
                    
                except Exception as e:
                    print(f"    Warning: failed to parse addon gs_original_data: {e}")

            # Append vertices to pos_bytes.
            for i in range(len(addon_mesh.vertices)):
                co = addon_mesh.vertices[i].co
                x  = max(-32768, min(32767, round(co.x * vert_scale)))
                y  = max(-32768, min(32767, round(co.y * vert_scale)))
                z  = max(-32768, min(32767, round(co.z * vert_scale)))
                pos_bytes += struct.pack('>hhh', x, y, z)
                pos_min[0] = min(pos_min[0], x)
                pos_min[1] = min(pos_min[1], y)
                pos_min[2] = min(pos_min[2], z)
                pos_max[0] = max(pos_max[0], x)
                pos_max[1] = max(pos_max[1], y)
                pos_max[2] = max(pos_max[2], z)

            # Build per-loop normal indices for addon mesh.
            # Uses loop.normal (respects custom split normals from import)
            # instead of vert.normal (face-averaged).
            addon_loop_to_nrm = {}   # (poly_index, vertex_index) → global normal index
            for poly in addon_mesh.polygons:
                for corner, vi in enumerate(poly.vertices):
                    li = poly.loop_start + corner
                    n  = addon_mesh.loops[li].normal
                    nx = max(-128, min(127, round(n.x * norm_scale)))
                    ny = max(-128, min(127, round(n.y * norm_scale)))
                    nz = max(-128, min(127, round(n.z * norm_scale)))
                    nkey = (nx, ny, nz)
                    if nkey not in nrm_key_to_idx:
                        nrm_key_to_idx[nkey] = len(nrm_table)
                        nrm_table.append(nkey)
                    addon_loop_to_nrm[(poly.index, vi)] = nrm_key_to_idx[nkey]

            # Build UV mapping for addon mesh.
            addon_uvl = addon_mesh.uv_layers.active
            addon_loop_uv = {}   # addon loop index → global UV table index

            # For addon meshes with gs_data, build a float-to-UV mapping from original UVs.
            addon_float_to_orig = {}   # (round_u, round_v) → orig_uv_idx
            addon_uv_scale_local = addon_uv_scale if addon_has_gs_data else uv_scale
            if addon_has_gs_data and addon_orig_uv_table:
                for orig_ui, (pu, pv) in addon_orig_uv_table.items():
                    key = (round(pu / addon_uv_scale_local, 6), round((1.0 - pv / addon_uv_scale_local), 6))
                    addon_float_to_orig[key] = orig_ui

            if addon_uvl:
                # Rebuild fresh UV table for addon mesh from Blender UVs.
                # Don't try to match original UVs since the mesh was modified.
                _addon_uv_map = {}   # float_key → global uv index
                addon_uv_start_idx = orig_uv_count  # Record starting index for addon UVs
                
                # Verify UV layer data
                total_loops = sum(len(poly.loop_indices) for poly in addon_mesh.polygons)
                print(f"  [Addon] UV layer has {len(addon_uvl.data)} entries, addon mesh has {total_loops} loops")
                
                sample_count = 0
                duplicate_count = 0
                unique_count = 0
                for poly in addon_mesh.polygons:
                    for li in poly.loop_indices:
                        if li < len(addon_uvl.data):
                            bl_uv = addon_uvl.data[li].uv
                        else:
                            bl_uv = (0.0, 0.0)
                            print(f"    WARNING: loop index {li} out of range for UV layer!")
                        # Debug: print first few raw UV values
                        if sample_count < 5:
                            print(f"    Blender UV[{li}] = ({bl_uv[0]:.6f}, {bl_uv[1]:.6f})")
                            sample_count += 1
                        key = (round(float(bl_uv[0]), 6), round(float(bl_uv[1]), 6))
                        if key in _addon_uv_map:
                            addon_loop_uv[li] = _addon_uv_map[key]
                            duplicate_count += 1
                        else:
                            new_idx = orig_uv_count
                            orig_uv_count += 1
                            orig_uv_table[new_idx] = (
                                round(key[0] * uv_scale),
                                round((1.0 - key[1]) * uv_scale),
                            )
                            _addon_uv_map[key] = new_idx
                            addon_loop_uv[li] = new_idx
                            unique_count += 1
                addon_uv_end_idx = orig_uv_count
                print(f"  [Addon] UV stats: {unique_count} unique, {duplicate_count} duplicates, total loops {total_loops}")
                print(f"  [Addon] UV indices range: {addon_uv_start_idx} to {addon_uv_end_idx - 1}")
                print(f"  [Addon] Sample raw UV values:")
                for idx in range(addon_uv_start_idx, min(addon_uv_start_idx + 5, addon_uv_end_idx)):
                    if idx in orig_uv_table:
                        u, v = orig_uv_table[idx]
                        u_float = u / uv_scale
                        v_float = 1.0 - v / uv_scale
                        print(f"    UV[{idx}] raw=({u}, {v}), float=({u_float:.4f}, {v_float:.4f})")
                
                # Extend uv_bytes with addon UV entries
                addon_uv_count = addon_uv_end_idx - addon_uv_start_idx
                for idx in range(addon_uv_start_idx, addon_uv_end_idx):
                    if idx in orig_uv_table:
                        u, v = orig_uv_table[idx]
                    else:
                        u, v = 0, 0
                    uv_bytes += struct.pack('>hh', u, v)
                print(f"  [Addon] Extended uv_bytes by {addon_uv_count} entries")
                
                mesh_obj['gs_uv_count'] = orig_uv_count
            else:
                print(f"  [Addon] No UV layer found!")
                for poly in addon_mesh.polygons:
                    for li in poly.loop_indices:
                        addon_loop_uv[li] = 0

            # Build per-loop color indices for addon mesh.
            addon_loop_color = {}
            if vc_mode == 'BLENDER':
                _acol = addon_mesh.color_attributes.get("Col")
                if _acol:
                    for poly in addon_mesh.polygons:
                        for li in poly.loop_indices:
                            r, g, b, a = _acol.data[li].color
                            key = (round(r * 255), round(g * 255), round(b * 255), round(a * 255))
                            if key not in col_key_to_idx:
                                ci = len(col_table)
                                col_key_to_idx[key] = ci
                                col_table.append(bytearray(key))
                                col_bytes += bytearray(key)
                                col_count = len(col_table)
                            addon_loop_color[li] = col_key_to_idx[key]
                    print(f"  [Addon] Color: {len(addon_loop_color)} loops, "
                          f"{len(col_table)} total colors after dedup")
                else:
                    print(f"  [Addon] WARNING: No color attribute on addon mesh, using index 0")
                    for poly in addon_mesh.polygons:
                        for li in poly.loop_indices:
                            addon_loop_color[li] = 0
            elif vc_mode == 'WHITE':
                for poly in addon_mesh.polygons:
                    for li in poly.loop_indices:
                        addon_loop_color[li] = 0
            else:  # NONE
                for poly in addon_mesh.polygons:
                    for li in poly.loop_indices:
                        addon_loop_color[li] = 0

            # Find armature and build bone lookups for this addon mesh.
            addon_arm = None
            for mod in addon_obj.modifiers:
                if mod.type == 'ARMATURE' and mod.object:
                    addon_arm = mod.object
                    break
            
            print(f"  [Addon] Armature: {addon_arm.name if addon_arm else 'None'}")
            if addon_arm:
                bone_indices = {b.name: int(b['fe_bone_index']) if 'fe_bone_index' in b else -1 for b in addon_arm.data.bones}
                print(f"  [Addon] Bones in armature: {bone_indices}")

            # Build vertex group → bone id map for addon mesh.
            # IMPORTANT: Use MAIN skeleton for lookups, not the addon mesh's secondary skeleton.
            # The addon mesh's vertex groups have the SAME names as bones in the main skeleton.
            addon_vgroups = addon_obj.vertex_groups
            addon_bid_by_vgi = {}   # addon vgi → current fe_bone_index (from main skeleton)
            addon_orig_bid_by_vgi = {}   # addon vgi → fe_original_bone_id (for chunk grouping)
            
            # Build bone lookup from MAIN skeleton
            main_bones_by_name = {b.name: b for b in armature_obj.data.bones}
            for vgi in range(len(addon_vgroups)):
                vg_name = addon_vgroups[vgi].name
                # Look up in main skeleton
                main_bone = main_bones_by_name.get(vg_name)
                if main_bone is not None:
                    fe_idx = int(main_bone['fe_bone_index']) if 'fe_bone_index' in main_bone else -1
                    orig_idx = int(main_bone['fe_original_bone_id']) if 'fe_original_bone_id' in main_bone and main_bone['fe_original_bone_id'] != -1 else fe_idx
                    addon_bid_by_vgi[vgi] = fe_idx
                    addon_orig_bid_by_vgi[vgi] = orig_idx
                    print(f"    VG '{vg_name}' -> Main Bone: fe_bone_index={fe_idx}, fe_original_bone_id={orig_idx}")
                else:
                    print(f"    VG '{vg_name}' -> NOT FOUND in main skeleton!")

            # Best bone per addon vertex (for greedy strip sb_byte).
            addon_vert_group_map = {}
            addon_orig_bid_map = {}   # addon vi → original bone id
            for v in addon_mesh.vertices:
                best_gi, best_wt = None, -1.0
                for vge in v.groups:
                    if vge.weight > best_wt:
                        best_wt = vge.weight
                        best_gi = vge.group
                if best_gi is not None:
                    addon_vert_group_map[v.index] = best_gi
                    addon_orig_bid_map[v.index] = addon_orig_bid_by_vgi.get(best_gi, -1)

            # Group addon faces by original chunk index to preserve palette boundaries.
            # Bones in the same original chunk share the same palette → one new chunk.
            # Bones in different original chunks → separate new chunks.
            addon_faces_by_orig_chunk = {}
            for poly in addon_mesh.polygons:
                vi0 = poly.vertices[0]
                orig_bid = addon_orig_bid_map.get(vi0, -1)
                # Use bone → chunk mapping if available, otherwise use bone ID directly
                if addon_has_gs_data and orig_bid in addon_orig_bid_to_chunk:
                    chunk_key = addon_orig_bid_to_chunk[orig_bid]  # Group by original chunk
                else:
                    chunk_key = orig_bid  # Fallback to bone ID
                if chunk_key not in addon_faces_by_orig_chunk:
                    addon_faces_by_orig_chunk[chunk_key] = {'orig_bids': set(), 'faces': []}
                addon_faces_by_orig_chunk[chunk_key]['orig_bids'].add(orig_bid)
                addon_faces_by_orig_chunk[chunk_key]['faces'].append(poly.index)
            
            print(f"  [Addon] Grouped into {len(addon_faces_by_orig_chunk)} chunk groups: "
                  f"{[(k, list(v['orig_bids'])) for k, v in addon_faces_by_orig_chunk.items()]}")

            # Create a fake "face list" entry for each addon chunk.
            for chunk_key, chunk_data in addon_faces_by_orig_chunk.items():
                face_list = chunk_data['faces']
                orig_bids = list(chunk_data['orig_bids'])
                
                # Get current bone ID for export from first vertex
                vi0 = addon_mesh.polygons[face_list[0]].vertices[0]
                vgi = addon_vert_group_map.get(vi0)
                current_bid = addon_bid_by_vgi.get(vgi, -1) if vgi is not None else -1
                
                chunk_face_lists.append({
                    '__addon__': True,
                    'addon_obj': addon_obj,
                    'addon_mesh': addon_mesh,
                    'addon_vert_offset': _addon_vert_offset,
                    'addon_loop_uv': addon_loop_uv,
                    'addon_loop_color': addon_loop_color,
                    'addon_loop_to_nrm': addon_loop_to_nrm,
                    'addon_vert_group_map': addon_vert_group_map,
                    'addon_bid_by_vgi': addon_bid_by_vgi,
                    'addon_orig_bid_map': addon_orig_bid_map,
                    'face_indices': face_list,
                    'primary_bone_id': current_bid,
                    'original_bone_ids': orig_bids,  # All original bone IDs in this chunk
                    'addon_has_gs_data': addon_has_gs_data,
                    'addon_orig_uv_table': addon_orig_uv_table,
                    'addon_uv_scale': addon_gs.get('uv_scale', 1) if addon_has_gs_data else 1,
                    'addon_chunk_face_ranges': list(zip(addon_chunk_face_starts, addon_chunk_face_counts)),
                })
                gs_note = f" (orig_chunk={chunk_key}, orig_bids={orig_bids})"
                print(f"    Addon chunk: current_bid={current_bid}, {len(face_list)} faces{gs_note}")

            _addon_vert_offset += len(addon_mesh.vertices)

        # Recompute v_count to include addon vertices.
        v_count = _addon_vert_offset
        # Rebuild nrm_bytes to include addon normals.
        nrm_bytes = bytearray()
        for (nx, ny, nz) in nrm_table:
            nrm_bytes += struct.pack('>bbb', nx, ny, nz)
        nrm_pad = (4 - len(nrm_bytes) % 4) % 4
        nrm_bytes += b'\x00' * nrm_pad
        n_count = len(nrm_table)   # update count to include addon normals

    n_chunks = len(chunk_face_lists)
    addon_chunk_count = sum(1 for fc in chunk_face_lists if isinstance(fc, dict) and fc.get('__addon__'))
    orig_palettes = {}
    for ci in range(min(n_orig_face_chunks, n_orig_chunks)):
        if ci in chunk_palettes:
            orig_palettes[ci] = chunk_palettes[ci]

    # In hierarchy mode (append_new_bones=False), all bone indices were
    # reassigned by write_skeleton_file.  Original chunk palettes still
    # reference the old indices and must be remapped using the bones'
    # fe_original_bone_id → fe_bone_index mapping.
    if not append_new_bones and armature_obj is not None:
        old_to_new = {}
        for ab in armature_obj.data.bones:
            old_id = ab.get('fe_original_bone_id')
            new_id = ab.get('fe_bone_index')
            if old_id is not None and new_id is not None:
                old_id = int(old_id)
                new_id = int(new_id)
                # If old_id already mapped, prefer the entry with matching index
                # (bone that kept its position) or keep the first mapping.
                if old_id in old_to_new:
                    existing_new = old_to_new[old_id]
                    # Prefer the new one if its new_id matches old_id (stable)
                    if new_id == old_id:
                        old_to_new[old_id] = new_id
                    elif existing_new == old_id:
                        pass  # keep existing (it's the stable one)
                    else:
                        # Neither matches; keep existing with a warning
                        print(f"  WARNING: duplicate fe_original_bone_id {old_id} "
                              f"on '{ab.name}' (maps to {new_id}, kept {existing_new})")
                else:
                    old_to_new[old_id] = new_id
        if old_to_new:
            remap_count = 0
            for ci in orig_palettes:
                orig_palettes[ci] = [old_to_new.get(bid, bid) for bid in orig_palettes[ci]]
                remap_count += 1
            print(f"  Remapped {remap_count} chunk palettes (hierarchy mode, {len(old_to_new)} bone ID mappings)")

    print(f"\n=== CHUNK DEBUG ===")
    print(f"  Original chunks: {n_orig_face_chunks}")
    print(f"  Addon chunks: {addon_chunk_count}")
    print(f"  Total chunks after merge: {n_chunks}")
    for ci, face_list in enumerate(chunk_face_lists):
        if isinstance(face_list, dict) and face_list.get('__addon__'):
            print(f"  Chunk {ci} (ADDON): {len(face_list['face_indices'])} faces "
                  f"from '{face_list['addon_obj'].name}'")
            continue
        n_faces = len(face_list)
        orig_vs_new = "original" if ci < n_orig_face_chunks else "NEW"
        print(f"  Chunk {ci} ({orig_vs_new}): {n_faces} faces")
        if ci < n_orig_face_chunks:
            if ci in orig_palettes:
                print(f"    GX palette: {orig_palettes[ci]}")
            else:
                print(f"    GX palette: (none)")

    # v27.0: Debug - count skinned vertices per bone for export
    # NOTE: This counts each vertex once per bone it's weighted to, so sum > total verts
    export_bone_vert_counts = defaultdict(int)
    for ci in range(n_chunks):
        face_data = chunk_face_lists[ci]
        if isinstance(face_data, dict) and face_data.get('__addon__'):
            continue   # addon chunks counted separately
        if ci < n_orig_face_chunks and ci in orig_palettes:
            chunk_bone_ids = list(orig_palettes[ci])
        else:
            chunk_bone_ids = []
            seen_ids = {}
            for fi in face_data:
                for vi in mesh.polygons[fi].vertices:
                    all_bids = vert_all_bones.get(vi, [])
                    for bid in all_bids:
                        if bid not in seen_ids:
                            seen_ids[bid] = len(chunk_bone_ids)
                            chunk_bone_ids.append(bid)
        for fi in face_data:
            for vi in mesh.polygons[fi].vertices:
                all_bids = vert_all_bones.get(vi, [])
                for bid in all_bids:
                    if bid in chunk_bone_ids:
                        export_bone_vert_counts[bid] += 1

    print(f"\n=== GX PALETTE COMPARISON ===")
    for ci in range(min(n_orig_face_chunks, 10)):
        if ci in orig_palettes:
            print(f"  Chunk {ci}: palette={orig_palettes[ci]}")

    # v27.3 / v25.6: Read original file's display list vertex tuples.
    # Store (orig_vi, orig_ni, orig_ui) per occurrence in flat order, plus strip
    # lengths.  Seam vertices appear multiple times with DIFFERENT ni/ui each time,
    # so we must store the full tuple per occurrence rather than per vertex index.
    #
    # orig_dl_vert_tuples[ci]  — flat list of (vi, ni, ui) in DL order
    # orig_dl_strip_lengths[ci] — list of strip vertex counts (sum == len of above)
    orig_dl_vert_tuples = {}   # replaces old orig_dl_vertex_order
    orig_dl_strip_lengths = {}
    for ci in range(n_orig_chunks):
        cp = chunk_list_addr + ci * 32
        dl_ptr_raw = struct.unpack_from('>I', raw_orig, cp + 20)[0]
        dl_addr = dl_ptr_raw + BASE if dl_ptr_raw > 0 else 0
        if dl_addr > 0 and dl_addr < len(raw_orig):
            tuples_ordered = []   # list of (vi, ni, ui)
            strip_lengths = []
            fmt2 = raw_orig[cp + 9]
            sb = bool(fmt2 & 2)
            hc = bool(raw_orig[cp + 18] & 0x10)
            hu = bool(raw_orig[cp + 18] & 0x80)
            bpv = 6 + (1 if sb else 0) + (2 if hc else 0) + (2 if hu else 0)

            ptr = dl_addr
            while ptr < len(raw_orig):
                if raw_orig[ptr] != 0x98:
                    break
                ptr += 1
                if ptr + 2 > len(raw_orig):
                    break
                slen = struct.unpack('>H', raw_orig[ptr:ptr+2])[0]
                strip_lengths.append(slen)
                ptr += 2
                for _ in range(slen):
                    if ptr + bpv > len(raw_orig):
                        break
                    if sb:
                        ptr += 1          # skip sb_byte
                    vi = struct.unpack('>H', raw_orig[ptr:ptr+2])[0]; ptr += 2
                    ni = struct.unpack('>H', raw_orig[ptr:ptr+2])[0]; ptr += 2
                    if hc:
                        col_i = struct.unpack('>H', raw_orig[ptr:ptr+2])[0]; ptr += 2
                    else:
                        col_i = 0
                    ui = struct.unpack('>H', raw_orig[ptr:ptr+2])[0]; ptr += 2
                    if hu: ptr += 2
                    tuples_ordered.append((vi, ni, ui, col_i))
            orig_dl_vert_tuples[ci] = tuples_ordered
            orig_dl_strip_lengths[ci] = strip_lengths

    if 0 in orig_dl_vert_tuples:
        sample = orig_dl_vert_tuples[0][:5]
        print(f"  DEBUG: Original chunk 0 DL tuples (vi,ni,ui,ci) first 5: {sample}")
        print(f"  DEBUG: Total DL vert occurrences chunk 0: {len(orig_dl_vert_tuples[0])}")

    # v27.5: Build mapping from original file vertex indices to Blender vertex indices
    # Original vertex indices in the display lists refer to global vertex array positions
    # We need to map these to Blender's vertex indices by matching vertex data
    orig_to_blender_map = {}  # orig file vi -> blender vi
    
    v_offset = gs['vertex_offset']
    n_offset = gs.get('norm_offset', 0)
    u_offset = gs.get('uv_offset', 0)
    orig_v_count = gs['vertex_count']  # Original file's vertex count (for reading original data)
    orig_n_count = gs.get('norm_count', 0)
    u_count = gs.get('uv_count', 0)
    vs = gs['vertex_scale']
    ns = gs.get('norm_scale', 1)
    us = gs.get('uv_scale', 1)
    
    # Read original file vertex positions using orig_v_count (NOT v_count - preserve export count)
    orig_vert_pos_by_idx = {}  # orig vi -> (x, y, z) rounded to int
    for vi in range(orig_v_count):
        off = v_offset + vi * 6
        if off + 6 <= len(raw_orig):
            x, y, z = struct.unpack_from('>hhh', raw_orig, off)
            orig_vert_pos_by_idx[vi] = (
                round(x / vs * 1000),
                round(y / vs * 1000),
                round(z / vs * 1000)
            )
    
    # Build mapping by matching position data
    # For each Blender vertex, find its matching original file vertex index
    # NOTE: Multiple Blender vertices can map to the same original vertex (duplicates)
    orig_to_blender_map = {}  # orig vi -> list of blender vis
    for bl_vi in range(len(mesh.vertices)):
        co = mesh.vertices[bl_vi].co
        bl_key = (round(co.x * 1000), round(co.y * 1000), round(co.z * 1000))
        
        # Find matching original vertex
        for orig_vi, pos_data in orig_vert_pos_by_idx.items():
            if pos_data == bl_key:
                if orig_vi not in orig_to_blender_map:
                    orig_to_blender_map[orig_vi] = []
                orig_to_blender_map[orig_vi].append(bl_vi)
                break
    
    print(f"  DEBUG: Built orig_to_blender_map: {len(orig_to_blender_map)} vertices mapped")

    for ci in range(min(n_orig_face_chunks, 10)):  # First 10 chunks
        if ci in orig_palettes:
            orig_pal = orig_palettes[ci]
            print(f"  Chunk {ci}: original palette = {orig_pal}")
            # Check what bones the current mesh vertices want
            chunk_face_data = chunk_face_lists[ci]
            if isinstance(chunk_face_data, dict):
                continue
            chunk_verts = set()
            for fi in chunk_face_data:
                chunk_verts.update(mesh.polygons[fi].vertices)
            mesh_bones = set()
            for vi in chunk_verts:
                for bid in vert_all_bones.get(vi, []):
                    mesh_bones.add(bid)
            print(f"    -> mesh wants bones: {sorted(mesh_bones)}")
            missing = [b for b in mesh_bones if b not in orig_pal]
            if missing:
                print(f"    -> NOTE: mesh has bones NOT in original: {missing}")
                # Debug: show which vertices have these missing bones
                for vi in list(chunk_verts)[:5]:  # Show first 5 verts with missing bones
                    vgroups_on_vert = [vge.group for vge in mesh.vertices[vi].groups]
                    bones_on_vert = []
                    for vgi in vgroups_on_vert:
                        bid = bone_id_by_vgroup_idx.get(vgi, bone_id_by_name.get(vgroups[vgi].name, None) if vgi < len(vgroups) else None)
                        if bid is not None:
                            vg_name = vgroups[vgi].name if vgi < len(vgroups) else "?"
                            bones_on_vert.append((vgi, vg_name, bid))
                    if any(b[2] in missing for b in bones_on_vert):
                        print(f"       vertex {vi}: vgroups={bones_on_vert}")
            # Check which slot each bone gets using ORIGINAL palette order
            bone_id_to_slot = {bid: si for si, bid in enumerate(orig_pal)}
            slots_used = {}
            for fi in chunk_face_lists[ci] if not isinstance(chunk_face_lists[ci], dict) else []:
                for vi in mesh.polygons[fi].vertices:
                    gi = vert_group_map.get(vi)
                    if gi is not None:
                        bid = bone_id_by_vgroup_idx.get(gi, bone_id_by_name.get(vgroups[gi].name, 0))
                    elif vert_all_bones.get(vi):
                        bid = vert_all_bones[vi][0]
                    else:
                        bid = 0
                    slot = bone_id_to_slot.get(bid, -1)
                    if slot >= 0:
                        slots_used[bid] = slot
            if slots_used:
                print(f"    -> slots (orig pal order): {slots_used}")
            # Debug: verify display list will use these slots
            print(f"    -> Will export with slots: {bone_id_to_slot}")

    print(f"\n=== EXPORT SKINNING DEBUG ===")
    print(f"  Total skinned vertices: {sum(export_bone_vert_counts.values())}")
    for bid in sorted(export_bone_vert_counts.keys()):
        bone_name = None
        if armature_obj:
            for b in armature_obj.data.bones:
                if b.get('fe_bone_index') == bid:
                    bone_name = b.name
                    break
        name_str = f" ({bone_name})" if bone_name else ""
        print(f"    bone {bid:3d}{name_str}: {export_bone_vert_counts[bid]} verts")

    for ci in range(n_chunks):
        face_indices = chunk_face_lists[ci]

        # ── Addon chunk: separate mesh object ────────────────────────────────
        # Addon chunks are stored as dicts rather than plain face index lists.
        # Handle them separately: build greedy DL directly from addon mesh data.
        if isinstance(face_indices, dict) and face_indices.get('__addon__'):
            ainfo       = face_indices
            addon_obj   = ainfo['addon_obj']
            addon_mesh  = ainfo['addon_mesh']
            a_vert_off  = ainfo['addon_vert_offset']
            a_loop_uv   = ainfo['addon_loop_uv']
            a_loop_col  = ainfo.get('addon_loop_color', {})
            a_loop_to_nrm = ainfo.get('addon_loop_to_nrm', {})
            a_vgm       = ainfo['addon_vert_group_map']
            a_bid_vgi   = ainfo['addon_bid_by_vgi']
            a_orig_bid_map = ainfo.get('addon_orig_bid_map', {})
            addon_faces = ainfo['face_indices']
            primary_bid = ainfo['primary_bone_id']
            orig_bids = ainfo.get('original_bone_ids', [ainfo.get('original_bone_id', -1)])
            addon_has_gs = ainfo.get('addon_has_gs_data', False)
            addon_orig_uv = ainfo.get('addon_orig_uv_table', {})

            # Collect bone IDs from addon faces.
            seen_ids       = {}
            chunk_bone_ids = []
            debug_bone_count = 0
            debug_no_bone_count = 0
            for fi in addon_faces:
                for vi in addon_mesh.polygons[fi].vertices:
                    gi = a_vgm.get(vi)
                    bid = a_bid_vgi.get(gi, -1) if gi is not None else -1
                    if bid >= 0:
                        debug_bone_count += 1
                        if bid not in seen_ids:
                            seen_ids[bid] = len(chunk_bone_ids)
                            chunk_bone_ids.append(bid)
                    else:
                        debug_no_bone_count += 1
            if not chunk_bone_ids and primary_bid >= 0:
                chunk_bone_ids = [primary_bid]
            
            print(f"  [Addon] Chunk {ci}: {debug_bone_count} verts with bone, {debug_no_bone_count} verts without, collected bones: {chunk_bone_ids}")

            bone_id_to_slot = {bid: si for si, bid in enumerate(chunk_bone_ids)}

            # Greedy strip builder for addon mesh faces.
            addon_face_vtx = {}
            for fi in addon_faces:
                poly = addon_mesh.polygons[fi]
                verts = []
                for corner, vi in enumerate(poly.vertices):
                    li  = poly.loop_start + corner
                    gi  = a_vgm.get(vi)
                    bid = a_bid_vgi.get(gi, -1) if gi is not None else -1
                    slot = bone_id_to_slot.get(bid, 0)
                    global_vi  = a_vert_off + vi
                    global_nrm = a_loop_to_nrm.get((poly.index, vi), 0)
                    global_ui  = a_loop_uv.get(li, 0)
                    verts.append((slot * 3, global_vi, global_nrm, a_loop_col.get(li, 0), global_ui))
                addon_face_vtx[fi] = verts

            if addon_has_gs:
                print(f"  [Addon] Chunk {ci} has gs_data: {len(addon_orig_uv)} original UVs, orig_bone_ids={orig_bids}")

            edge_face = {}
            for fi in addon_faces:
                verts = addon_face_vtx[fi]
                for i in range(3):
                    edge_face[(verts[i], verts[(i+1)%3])] = fi

            visited = set()
            strips  = []
            for fi in addon_faces:
                if fi in visited:
                    continue
                verts = addon_face_vtx[fi]
                best_strip, best_vis = None, set()
                for rot in range(3):
                    strip = [verts[rot], verts[(rot+1)%3], verts[(rot+2)%3]]
                    temp_vis = {fi}
                    while True:
                        n = len(strip)
                        key = (strip[-1], strip[-2]) if n % 2 == 1 else (strip[-2], strip[-1])
                        nfi = edge_face.get(key)
                        if nfi is None or nfi in visited or nfi in temp_vis:
                            break
                        shared = {strip[-2][1], strip[-1][1]}
                        cands = [v for v in addon_face_vtx[nfi] if v[1] not in shared]
                        if len(cands) != 1:
                            break
                        strip.append(cands[0])
                        temp_vis.add(nfi)
                    if best_strip is None or len(strip) > len(best_strip):
                        best_strip, best_vis = strip, temp_vis
                visited.update(best_vis)
                strips.append(best_strip)

            # Debug: collect UV values from strips
            all_uvs_in_chunk = set()
            uv_to_blender = {}  # debug: UV idx -> blender float UV
            for strip in strips:
                for (sb_b, pos, nrm, col, uv) in strip:
                    all_uvs_in_chunk.add(uv)
                    # Find the blender UV that maps to this index
                    for li_idx, ui_idx in addon_loop_uv.items():
                        if ui_idx == uv and li_idx < len(addon_uvl.data):
                            uv_to_blender[uv] = addon_uvl.data[li_idx].uv
                            break
            print(f"  [Addon] Chunk {ci}: {len(all_uvs_in_chunk)} unique UV indices: {sorted(all_uvs_in_chunk)[:20]}...")
            print(f"  [Addon] Sample UV values in DL:")
            for uv_idx in sorted(all_uvs_in_chunk)[:5]:
                if uv_idx in orig_uv_table:
                    u, v = orig_uv_table[uv_idx]
                    print(f"    DL UV[{uv_idx}] = raw({u}, {v}), float({u/uv_scale:.4f}, {1-v/uv_scale:.4f})")
                if uv_idx in uv_to_blender:
                    bv = uv_to_blender[uv_idx]
                    print(f"      -> Blender UV: ({bv[0]:.6f}, {bv[1]:.6f})")
            
            dl = bytearray()
            for strip in strips:
                dl += b'\x98'
                dl += struct.pack('>H', len(strip))
                _ac_hc = bool(CHAR_GX_ATTR[6] & 0x10)
                _ac_hu = bool(CHAR_GX_ATTR[6] & 0x80)
                for (sb_b, pos, nrm, col, uv) in strip:
                    dl += struct.pack('>B', sb_b)  # sb always True for new chunks
                    dl += struct.pack('>H', pos)
                    dl += struct.pack('>H', nrm)
                    if _ac_hc:
                        dl += struct.pack('>H', col)
                    dl += struct.pack('>H', uv)
                    if _ac_hu:
                        dl += b'\x00\x00'
            pad = (32 - len(dl) % 32) % 32
            dl += b'\x00' * pad
            dl_bytes = bytes(dl)

            gc_bytes = build_gx_cache(chunk_bone_ids)

            # AABB from addon faces.
            a_xs = [addon_mesh.vertices[v].co.x for fi in addon_faces for v in addon_mesh.polygons[fi].vertices]
            a_ys = [addon_mesh.vertices[v].co.y for fi in addon_faces for v in addon_mesh.polygons[fi].vertices]
            a_zs = [addon_mesh.vertices[v].co.z for fi in addon_faces for v in addon_mesh.polygons[fi].vertices]
            aabb_min = (min(a_xs), min(a_ys), min(a_zs)) if a_xs else (0,0,0)
            aabb_max = (max(a_xs), max(a_ys), max(a_zs)) if a_xs else (0,0,0)

            ptra_tail_ba = bytearray(32)
            struct.pack_into('>fff', ptra_tail_ba, 0,  *aabb_min)
            struct.pack_into('>fff', ptra_tail_ba, 12, *aabb_max)
            ptra_tail_ba[25] = next_ptra_slot & 0xFF
            ptra_tail = bytes(ptra_tail_ba)
            next_ptra_slot += 1

            # Determine material from addon mesh - use polygon's material index first, then slot 0.
            addon_mat_idx = 0
            poly_mat_idx = None
            if addon_faces:
                first_poly = addon_mesh.polygons[addon_faces[0]]
                poly_mat_idx = first_poly.material_index
                print(f"  [Addon] Chunk {ci}: first face material_index = {poly_mat_idx}")
            
            if poly_mat_idx is not None and poly_mat_idx < len(addon_mesh.materials) and addon_mesh.materials[poly_mat_idx]:
                amat_name = addon_mesh.materials[poly_mat_idx].name
                print(f"  [Addon] Chunk {ci}: addon mesh material at slot {poly_mat_idx} = '{amat_name}'")
                # Find in materials_out by name
                found = False
                for mi, m in enumerate(materials_out):
                    if m['name'] == amat_name:
                        addon_mat_idx = mi
                        found = True
                        print(f"  [Addon] Chunk {ci}: found '{amat_name}' in materials_out at index {mi}")
                        break
                if not found:
                    print(f"  [Addon] Chunk {ci}: WARNING '{amat_name}' not found in materials_out! Available: {[m['name'] for m in materials_out]}")
                print(f"  [Addon] Chunk {ci}: final addon_mat_idx = {addon_mat_idx}")
            elif addon_mesh.materials:
                # Fallback to first material slot
                amat_name = addon_mesh.materials[0].name if addon_mesh.materials[0] else 'unknown'
                for mi, m in enumerate(materials_out):
                    if m['name'] == amat_name:
                        addon_mat_idx = mi
                        break
                print(f"  [Addon] Chunk {ci}: using fallback material '{amat_name}'")

            print(f"  [DL] Addon chunk {ci}: greedy, {len(strips)} strips, "
                  f"palette={chunk_bone_ids}, mat={addon_mat_idx}")

            # Debug: verify _mat_idx before storing
            print(f"  [Addon] Storing _mat_idx={addon_mat_idx} for chunk {ci}")

            chunks_out.append({
                'name':        default_new_chunk_name,
                'prim_type':   CHAR_PRIM,
                'fmt2':        CHAR_FMT2,
                'gx_attr_blk': CHAR_GX_ATTR,
                'dl_bytes':    dl_bytes,
                'gc_bytes':    gc_bytes,
                'ptra_tail':   ptra_tail,
                '_mat_idx':    addon_mat_idx,
            })
            continue   # Skip the rest of the main chunk loop body.

        # For original chunks, use the original GX palette to preserve slot indices
        if ci < n_orig_face_chunks and ci in orig_palettes:
            chunk_bone_ids = list(orig_palettes[ci])
        else:
            # Collect unique bone IDs referenced by this chunk's vertices, in
            # first-seen order (preserves a stable palette ordering).
            seen_ids       = {}   # bone_id -> first-seen position (preserves order)
            chunk_bone_ids = []
            for fi in face_indices:
                for vi in mesh.polygons[fi].vertices:
                    all_bids = vert_all_bones.get(vi, [])
                    for bid in all_bids:
                        if bid not in seen_ids:
                            seen_ids[bid] = len(chunk_bone_ids)
                            chunk_bone_ids.append(bid)
            # Debug: print chunk bone IDs for new chunks
            if ci >= n_orig_face_chunks:
                print(f"  DEBUG: New chunk {ci} bone IDs: {chunk_bone_ids}")

        # Determine sb/hc/hu from the original chunk record before building the
        # display list. The importer reads 1 sb byte per vertex when sb=True
        # (fmt2 bit 1), 2 color-index bytes when hc=True (format2 bit 4), and
        # 2 secondary-UV bytes when hu=True (bit 7).
        # The exporter must write exactly the same bytes so the re-imported
        # vertex byte stream stays aligned.
        if ci < n_orig_face_chunks:
            chunk_sb = orig_chunk_records[ci]['sb']
            chunk_hc = orig_chunk_records[ci]['hc']
            chunk_hu = orig_chunk_records[ci]['hu']
        else:
            chunk_sb = bool(CHAR_FMT2 & 2)
            chunk_hc = bool(CHAR_GX_ATTR[6] & 0x10)
            chunk_hu = bool(CHAR_GX_ATTR[6] & 0x80)

        # ── Decide which build_display_list mode to use ─────────────────────
        #
        # ORIGINAL-ORDER MODE: available when this is an original chunk AND
        # every orig_vi that appears in the original DL can still be found in
        # the current Blender mesh (via orig_to_blender_map).  If any orig_vi
        # is missing the chunk has had geometry deleted; fall back to greedy.
        #
        # GREEDY MODE: new chunks, or original chunks with removed geometry,
        # or when UVs were modified (uv_was_modified=True) because the
        # orig_vert_tuples contain stale orig_ui values.
        use_orig_tuples = False
        orig_tuples_for_chunk = None
        orig_strip_lens_for_chunk = None

        if uv_was_modified:
            print(f"  [DL] Chunk {ci}: greedy mode (UVs were modified, forcing greedy)")
        elif ci < n_orig_face_chunks and ci in orig_dl_vert_tuples:
            tuples = orig_dl_vert_tuples[ci]
            slens  = orig_dl_strip_lengths.get(ci, [])
            # Verify every orig_vi in the tuple list is still present in Blender.
            # A missing vertex means geometry was deleted → greedy fallback.
            missing = set()
            for tup in tuples:
                orig_vi = tup[0]
                if orig_vi not in orig_to_blender_map:
                    missing.add(orig_vi)
            if not missing:
                use_orig_tuples = True
                orig_tuples_for_chunk = tuples
                orig_strip_lens_for_chunk = slens
                print(f"  [DL] Chunk {ci}: original-order mode "
                      f"({len(tuples)} vert occurrences, {len(slens)} strips)")
            else:
                print(f"  [DL] Chunk {ci}: greedy mode "
                      f"({len(missing)} orig vertices removed from mesh)")

        if not use_orig_tuples and ci < n_orig_face_chunks:
            print(f"  [DL] Chunk {ci}: greedy mode (no orig tuples available)")
        elif ci >= n_orig_face_chunks:
            print(f"  [DL] Chunk {ci}: greedy mode (new chunk)")

        # Build display list
        dl_bytes = build_display_list(
            face_indices, chunk_bone_ids, chunk_sb, chunk_hc, chunk_hu,
            orig_vert_tuples  = orig_tuples_for_chunk,
            orig_strip_lengths= orig_strip_lens_for_chunk,
            orig_to_blender_map = orig_to_blender_map,
        )
        
        # For original chunks, preserve the exact original GX palette
        original_palette = orig_palettes.get(ci) if ci < n_orig_face_chunks else None
        gc_bytes = build_gx_cache(chunk_bone_ids, original_palette) if chunk_sb else b''

        if ci < n_orig_face_chunks:
            # Original chunk — carry over format fields and update AABB from new vertices
            orig = orig_chunk_records[ci]
            chunk_name  = orig['name']
            prim_type   = orig['prim_type']
            fmt2        = orig['fmt2']
            gx_attr_blk = orig['gx_attr_blk']
            
            # Recalculate AABB from current vertex positions (in case new geometry extended bounds)
            chunk_verts = set()
            for fi in chunk_face_lists[ci]:
                chunk_verts.update(mesh.polygons[fi].vertices)
            
            if chunk_verts:
                xs = [mesh.vertices[v].co.x for v in chunk_verts]
                ys = [mesh.vertices[v].co.y for v in chunk_verts]
                zs = [mesh.vertices[v].co.z for v in chunk_verts]
                aabb_min = (min(xs), min(ys), min(zs))
                aabb_max = (max(xs), max(ys), max(zs))
            else:
                aabb_min = (0.0, 0.0, 0.0)
                aabb_max = (0.0, 0.0, 0.0)
            
            # Preserve original slot index from ptra_tail but update AABB
            # ptra_tail[25] = PtrA offset 0x1D = slot
            # orig['ptra_tail'] was read from original file bytes. Need to read from orig_tail[25].
            orig_tail = orig['ptra_tail']
            old_slot = orig_tail[25] if len(orig_tail) > 25 else 0  # tail[25] = PtrA offset 0x1D = slot
            ptra_tail_ba = bytearray(32)
            struct.pack_into('>fff', ptra_tail_ba, 0,  *aabb_min)
            struct.pack_into('>fff', ptra_tail_ba, 12, *aabb_max)
            ptra_tail_ba[25] = old_slot  # Write slot to tail[25] = PtrA offset 0x1D
            ptra_tail = bytes(ptra_tail_ba)
            
            print(f"  DEBUG: Chunk {ci} updated AABB: min=({aabb_min[0]:.2f}, {aabb_min[1]:.2f}, {aabb_min[2]:.2f}), max=({aabb_max[0]:.2f}, {aabb_max[1]:.2f}, {aabb_max[2]:.2f}), slot={old_slot}")
        else:
            # New chunk (user-added geometry) — use character format defaults.
            # PtrA name follows the convention of the original model (e.g. "none"
            # for FE9 lord body) so no unexpected strings enter the pool.
            new_ci = ci - n_orig_face_chunks
            chunk_name  = default_new_chunk_name
            prim_type   = CHAR_PRIM
            fmt2        = CHAR_FMT2
            gx_attr_blk = CHAR_GX_ATTR

            # Compute AABB from this chunk's vertex positions.
            chunk_verts = set()
            for fi in face_indices:
                chunk_verts.update(mesh.polygons[fi].vertices)

            if chunk_verts:
                xs = [mesh.vertices[v].co.x for v in chunk_verts]
                ys = [mesh.vertices[v].co.y for v in chunk_verts]
                zs = [mesh.vertices[v].co.z for v in chunk_verts]
                aabb_min = (min(xs), min(ys), min(zs))
                aabb_max = (max(xs), max(ys), max(zs))
            else:
                aabb_min = (0.0, 0.0, 0.0)
                aabb_max = (0.0, 0.0, 0.0)

            # Build the 32-byte PtrA tail:
            #   bytes  0-11: AABB min XYZ (3 float32 BE)
            #   bytes 12-23: AABB max XYZ (3 float32 BE)
            #   byte     24: 0x00
            #   byte     25: display-list slot index (unique across all chunks)
            #   bytes 26-31: 0x00 padding
            ptra_tail_ba = bytearray(32)
            struct.pack_into('>fff', ptra_tail_ba, 0,  *aabb_min)
            struct.pack_into('>fff', ptra_tail_ba, 12, *aabb_max)
            ptra_tail_ba[25] = next_ptra_slot & 0xFF  # tail[25] = PtrA offset 0x1D = slot
            ptra_tail = bytes(ptra_tail_ba)
            next_ptra_slot += 1

        chunks_out.append({
            'name':        chunk_name,
            'prim_type':   prim_type,
            'fmt2':        fmt2,
            'gx_attr_blk': gx_attr_blk,
            'dl_bytes':    dl_bytes,
            'gc_bytes':    gc_bytes,
            'ptra_tail':   ptra_tail,
        })

    # ── Step 5: Per-chunk material index from Blender face data ──────────────
    #
    # For original chunks: use the stored chunk_mat_indices value (authoritative).
    # For new chunks: use the dominant material slot among the chunk's faces.
    # For addon chunks: use the _mat_idx stored in the chunk dict.

    def get_mat_idx_for_chunk(ci):
        """Get material index for chunk ci, using appropriate source."""
        if ci < len(chunks_out):
            ch = chunks_out[ci]
            if '_mat_idx' in ch:
                return ch['_mat_idx']
        if ci < n_orig_face_chunks and ci < len(orig_chunk_mat_idxs):
            return orig_chunk_mat_idxs[ci]
        if ci < len(chunk_mat_out):
            return chunk_mat_out[ci]
        return 0

    orig_chunk_mat_idxs = gs.get('chunk_mat_indices', [])
    chunk_mat_out = []
    for ci in range(n_chunks):
        face_data = chunk_face_lists[ci]
        if isinstance(face_data, dict) and face_data.get('__addon__'):
            mat_val = face_data.get('_mat_idx', 'NOT FOUND')
            print(f"  DEBUG chunk_mat_out: ci={ci}, _mat_idx={mat_val}, face_data keys={list(face_data.keys())}")
            chunk_mat_out.append(mat_val if mat_val != 'NOT FOUND' else 0)
        elif ci < n_orig_face_chunks and ci < len(orig_chunk_mat_idxs):
            chunk_mat_out.append(orig_chunk_mat_idxs[ci])
        else:
            slot_counts = {}
            for fi in face_data:
                si = mesh.polygons[fi].material_index
                slot_counts[si] = slot_counts.get(si, 0) + 1
            chunk_mat_out.append(
                max(slot_counts, key=slot_counts.get) if slot_counts else 0
            )

    # Simplified: Just use chunks_out directly for material index
    def get_mat_idx_for_chunk(ci):
        ch = chunks_out[ci]
        if '_mat_idx' in ch:
            return ch['_mat_idx']
        elif ci < n_orig_face_chunks and ci < len(orig_chunk_mat_idxs):
            return orig_chunk_mat_idxs[ci]
        else:
            return chunk_mat_out[ci] if ci < len(chunk_mat_out) else 0

    print(f"\n=== MATERIAL INDEX DEBUG ===")
    print(f"  Total materials in Blender: {n_mats}")
    print(f"  materials_out: {[(mi, mat['name']) for mi, mat in enumerate(materials_out)]}")
    print(f"  chunk_mat_out length: {len(chunk_mat_out)}")
    for ci in range(n_chunks):
        orig_vs_new = "original" if ci < n_orig_face_chunks else "NEW"
        # Use the same function as the write code
        mat_idx = get_mat_idx_for_chunk(ci)
        extra = ""
        if ci >= n_orig_face_chunks:
            ch = chunks_out[ci]
            stored = ch.get('_mat_idx', 'MISSING')
            extra = f", stored_idx={stored}"
        mat_name = materials_out[mat_idx]['name'] if mat_idx < len(materials_out) else f"ERROR_index_{mat_idx}"
        print(f"  Chunk {ci} ({orig_vs_new}): material_index = {mat_idx} ({mat_name!r}){extra}")
        mat_name = materials_out[mat_idx]['name'] if mat_idx < len(materials_out) else f"index_{mat_idx}"
        print(f"  Chunk {ci} ({orig_vs_new}): material_index = {mat_idx} ({mat_name!r}){extra}")
        mat_name = materials_out[mat_idx]['name'] if mat_idx < len(materials_out) else f"index_{mat_idx}"
        print(f"  Chunk {ci} ({orig_vs_new}): material_index = {mat_idx} ({mat_name!r}){extra}")

    # ── UV per chunk debug ─────────────────────────────────────────────────────
    print(f"\n=== UV PER CHUNK DEBUG ===")
    print(f"  Total UVs in table: {len(uv_table)}, orig_uv_count: {orig_uv_count}")
    for ci in range(n_chunks):
        face_data = chunk_face_lists[ci]
        if isinstance(face_data, dict) and face_data.get('__addon__'):
            print(f"  Chunk {ci}: addon mesh '{face_data['addon_obj'].name}'")
            continue
        chunk_uvs = set()
        for fi in face_data:
            poly = mesh.polygons[fi]
            for li in poly.loop_indices:
                uv_idx = loop_uv_arr.get(li, 0)
                if uv_idx < orig_uv_count:
                    chunk_uvs.add(uv_idx)
        sorted_uvs = sorted(chunk_uvs)
        first_coords = [(i, uv_table[i]) if i < len(uv_table) else (i, (0.0, 0.0))
                        for i in sorted_uvs[:3]]
        last_coords  = [(i, uv_table[i]) if i < len(uv_table) else (i, (0.0, 0.0))
                        for i in sorted_uvs[-3:]]
        print(f"  Chunk {ci}: {len(chunk_uvs)} unique UVs, "
              f"first 3: {first_coords}, last 3: {last_coords}")

    # ── Step 6: Build string pool ─────────────────────────────────────────────
    # String pool already built in original order above, just add new strings

    def intern_string(s):
        """Add s to the pool if absent; return its byte offset within the pool."""
        if s not in string_offsets:
            string_offsets[s] = len(string_pool)
            string_pool.extend(s.encode('ascii') + b'\x00')
        return string_offsets[s]

    # Add any new names (materials, chunks) that weren't in original
    for m in materials_out:
        if m['name'] not in string_offsets:
            intern_string(m['name'])
    
    for ch in chunks_out:
        if ch['name'] not in string_offsets:
            intern_string(ch['name'])

    # Rebuild mat_name_pool_offs from materials_out (not just n_orig_mats).
    # The original pre-built list only covers the original binary's materials;
    # if the user added new material slots, those entries would be out of range.
    mat_name_pool_offs = [string_offsets.get(m['name'], 0) for m in materials_out]

    ptra_name_pool_offs = [intern_string(ch['name']) for ch in chunks_out]

    # Debug: show all chunk slots after building
    print(f"\n=== SLOT DEBUG ===")
    print(f"  max_ptra_slot (original): {max_ptra_slot}")
    print(f"  next_ptra_slot (starting for new): {next_ptra_slot}")
    print(f"  Final chunk slots (n_chunks={n_chunks}, n_orig_face_chunks={n_orig_face_chunks}):")
    for ci, ch in enumerate(chunks_out):
        if ch['ptra_tail']:
            # Read raw bytes to debug
            raw_tail = ch['ptra_tail']
            slot_from_raw = raw_tail[25] if len(raw_tail) > 25 else 0  # tail[25] = PtrA offset 0x1D = slot
            orig_vs_new = "original" if ci < n_orig_face_chunks else "NEW"
            print(f"    ci={ci}: slot={slot_from_raw}, raw bytes[20:26]={raw_tail[20:26].hex()}, name={ch['name']!r} ({orig_vs_new})")

    # ── Step 7: Compute section offsets ──────────────────────────────────────

    # Ensure uv_bytes is always defined (for edge cases)
    if 'uv_bytes' not in locals():
        uv_bytes = bytearray()
        print("  WARNING: uv_bytes was not defined, using fallback")

    HEADER_SIZE = 0x84

    pos_pad   = (4 - len(pos_bytes) % 4) % 4   # align norm table to 4-byte boundary
    pos_off   = HEADER_SIZE
    nrm_off   = pos_off + len(pos_bytes) + pos_pad
    uv_off    = nrm_off + len(nrm_bytes)   # nrm_bytes already padded to 4-byte
    if col_count > 0:
        col_off   = uv_off  + len(uv_bytes)
        mat_off   = col_off + len(col_bytes)
    else:
        col_off = 0
        mat_off   = uv_off  + len(uv_bytes)
    tpl_off   = mat_off + n_mats * 32
    ptra_off  = tpl_off + sum(len(m['tpl_blocks']) * 28 for m in materials_out)
    chunk_off = ptra_off + n_chunks * 36

    dl_offs_list = []
    cursor = chunk_off + n_chunks * 32
    # GameCube GX_CallDispList requires display lists to start at a 32-byte-
    # aligned file offset.  Insert zero-padding between the chunk descriptor
    # table and the first DL if the table doesn't end on a 32-byte boundary.
    pre_dl_pad = (32 - cursor % 32) % 32
    cursor += pre_dl_pad
    for ch in chunks_out:
        dl_offs_list.append(cursor)
        cursor += len(ch['dl_bytes'])   # dl_bytes is already padded to 32 bytes

    gc_offs_list = []
    gc_chunks = [(i, ch) for i, ch in enumerate(chunks_out) if ch['gc_bytes']]
    last_gc_index = gc_chunks[-1][0] if gc_chunks else -1
    
    cursor_gc = cursor
    for ci, ch in enumerate(chunks_out):
        if ch['gc_bytes']:
            raw_size = len(ch['gc_bytes'])
            is_last_gc = (ci == last_gc_index)
            
            # Pad to 0x20 unless this is the last GX palette
            if is_last_gc:
                pad = 0
            else:
                pad = (0x20 - raw_size) % 0x20 if raw_size < 0x20 else 0
            
            gc_offs_list.append(cursor_gc)
            cursor_gc += raw_size + pad
        else:
            gc_offs_list.append(0)   # null — no GX cache block for this chunk
    
    # Update cursor to the end of last GC section for subsequent data
    if gc_chunks:
        cursor = cursor_gc

    string_pool_off = cursor
    reloc_table_off = string_pool_off + len(string_pool)
    reloc_pre_pad   = (4 - reloc_table_off % 4) % 4
    reloc_table_off += reloc_pre_pad

    # ── Step 8: Collect relocation entries ───────────────────────────────────
    #
    # Every non-null pointer field must appear in the relocation table.
    # Null pointer fields (raw stored value == 0) must NOT be registered.

    reloc_fields = []   # list of (file_offset_of_field, raw_value_stored)

    def add_ptr(field_off, target_off):
        """Register a non-null pointer field for the relocation table.

        field_off  — byte offset of the pointer field within the output file.
        target_off — resolved file offset that the field points to.
        """
        reloc_fields.append((field_off, target_off - BASE))

    add_ptr(0x20, string_pool_off + model_name_pool_off)
    add_ptr(0x44, pos_off)
    add_ptr(0x48, nrm_off)
    add_ptr(0x4C, uv_off)
    if col_count > 0:
        add_ptr(0x50, col_off)
    add_ptr(0x54, mat_off)
    add_ptr(0x58, ptra_off)
    if uses_field_0x5C:
        add_ptr(0x5C, chunk_off)
    else:
        add_ptr(0x60, chunk_off)

    tpl_cursor = tpl_off
    for mi, mat in enumerate(materials_out):
        me = mat_off + mi * 32
        add_ptr(me + 0, string_pool_off + mat_name_pool_offs[mi])
        if mat['tpl_blocks']:
            add_ptr(me + 20, tpl_cursor)
        tpl_cursor += len(mat['tpl_blocks']) * 28

    for ci in range(n_chunks):
        add_ptr(ptra_off + ci * 36, string_pool_off + ptra_name_pool_offs[ci])

    for ci, ch in enumerate(chunks_out):
        cp = chunk_off + ci * 32
        add_ptr(cp + 0,  ptra_off + ci * 36)
        if ci < n_chunks - 1:
            add_ptr(cp + 4, chunk_off + (ci + 1) * 32)
        add_ptr(cp + 20, dl_offs_list[ci])
        if ch['gc_bytes']:
            add_ptr(cp + 28, gc_offs_list[ci])

    reloc_bytes = _build_reloc_table(reloc_fields)

    # ── Step 9: Assemble header ───────────────────────────────────────────────

    file_size = reloc_table_off + len(reloc_bytes)

    header = bytearray(HEADER_SIZE)
    struct.pack_into('>I', header, 0x00, file_size)
    struct.pack_into('>I', header, 0x04, reloc_table_off - BASE)
    struct.pack_into('>I', header, 0x08, len(reloc_fields))

    # Compute header AABB from new vertex positions
    # Convert int16 vertex coords back to float using vert_scale
    float_min = (pos_min[0] / vert_scale, pos_min[1] / vert_scale, pos_min[2] / vert_scale)
    float_max = (pos_max[0] / vert_scale, pos_max[1] / vert_scale, pos_max[2] / vert_scale)
    new_header_aabb = struct.pack('>ffffff', *float_min, *float_max)
    print(f"  DEBUG: New header AABB: min=({float_min[0]:.2f}, {float_min[1]:.2f}, {float_min[2]:.2f}), max=({float_max[0]:.2f}, {float_max[1]:.2f}, {float_max[2]:.2f})")

    struct.pack_into('>I', header, 0x20,
                     (string_pool_off + model_name_pool_off) - BASE)
    header[0x24:0x28] = build_date_tag
    header[0x28:0x2C] = header_unk_0x28
    header[0x2C:0x44] = new_header_aabb

    struct.pack_into('>I', header, 0x44, pos_off  - BASE)
    struct.pack_into('>I', header, 0x48, nrm_off  - BASE)
    struct.pack_into('>I', header, 0x4C, uv_off   - BASE)
    if col_count > 0:
        struct.pack_into('>I', header, 0x50, col_off - BASE)
    else:
        struct.pack_into('>I', header, 0x50, 0)
    struct.pack_into('>I', header, 0x54, mat_off  - BASE)
    struct.pack_into('>I', header, 0x58, ptra_off - BASE)
    if uses_field_0x5C:
        struct.pack_into('>I', header, 0x5C, chunk_off - BASE)
    else:
        struct.pack_into('>I', header, 0x60, chunk_off - BASE)

    struct.pack_into('>H', header, 0x6C, v_count)
    struct.pack_into('>H', header, 0x6E, n_count)
    # Use original UV count from mesh property (not deduplicated count)
    header_uv_count = mesh_obj.get('gs_uv_count', uv_count)
    print(f"  Writing {header_uv_count} UVs to header (vs {uv_count} deduplicated)")
    struct.pack_into('>H', header, 0x70, header_uv_count)
    print(f"\n=== HEADER WRITE DEBUG ===")
    print(f"  v_count RIGHT BEFORE header write: {v_count}")
    print(f"  id(v_count) type: {type(v_count)}, value: {v_count}")
    print(f"  header[0x6C:0x70] = {list(header[0x6C:0x70].hex().split(' '))} (should be {v_count} verts)")
    struct.pack_into('>H', header, 0x72, col_count)
    struct.pack_into('>H', header, 0x74, n_mats)   # material count (was wrong hardcoded 1)
    struct.pack_into('>H', header, 0x76, n_chunks)
    struct.pack_into('>H', header, 0x78, n_chunks)
    struct.pack_into('>H', header, 0x7A, 0)
    header[0x7C:0x80] = vat_bytes
    
    # Debug: verify UV offset and count in header
    print(f"  Header UV offset: 0x{struct.unpack_from('>I', header, 0x4C)[0]:08X}")
    print(f"  Header UV count: {struct.unpack_from('>H', header, 0x70)[0]}")
    struct.pack_into('>H', header, 0x78, n_chunks)
    struct.pack_into('>H', header, 0x7A, 0)
    header[0x7C:0x80] = vat_bytes

    # ── Step 10: Assemble output bytearray ───────────────────────────────────

    out = bytearray()
    out += header
    out += pos_bytes
    out += b'\x00' * pos_pad   # align norm table to 4-byte boundary
    out += nrm_bytes   # includes trailing alignment padding
    out += uv_bytes
    out += col_bytes

    # Material entries (32 bytes each)
    tpl_cursor = tpl_off
    for mi, mat in enumerate(materials_out):
        name_raw = (string_pool_off + mat_name_pool_offs[mi]) - BASE
        tpl_raw  = (tpl_cursor - BASE) if mat['tpl_blocks'] else 0
        entry    = struct.pack('>I', name_raw)
        entry   += b'\x00\x00'
        entry   += bytes([len(mat['tpl_blocks']), 0x00])
        entry   += bytes(mat['diff_rgba'])
        entry   += bytes(mat['spec_rgba'])
        entry   += b'\x00' * 4
        entry   += struct.pack('>I', tpl_raw)
        entry   += b'\x00' * 8
        out     += entry
        tpl_cursor += len(mat['tpl_blocks']) * 28

    # TPL info blocks (28 bytes each per material)
    for mat in materials_out:
        for tb in mat['tpl_blocks']:
            out += tb

    # PtrA blocks (36 bytes each: 4-byte name ptr + 32-byte tail)
    for ci, ch in enumerate(chunks_out):
        name_raw = (string_pool_off + ptra_name_pool_offs[ci]) - BASE
        out += struct.pack('>I', name_raw)
        out += ch['ptra_tail']   # 32 bytes

    # Chunk descriptors (32 bytes each)
    for ci, ch in enumerate(chunks_out):
        ptra_raw = (ptra_off + ci * 36)        - BASE
        next_raw = (chunk_off + (ci+1) * 32 - BASE) if ci < n_chunks - 1 else 0
        # Get material index: prefer _mat_idx from chunk dict (addon chunks),
        # then chunk_mat_out[ci] (original chunks)
        mat_to_write = get_mat_idx_for_chunk(ci)
        if mat_to_write >= len(materials_out):
            print(f"  WARNING: Clamping mat index {mat_to_write} to 0 (only {len(materials_out)} materials)")
            mat_to_write = 0
        if ci >= n_orig_face_chunks:
            print(f"  DEBUG: Writing chunk {ci}: chunk_mat_out[{ci}]={chunk_mat_out[ci] if ci < len(chunk_mat_out) else 'N/A'}, "
                  f"ch['_mat_idx']={ch.get('_mat_idx', 'MISSING')}, using {mat_to_write}")
        dl_raw   = dl_offs_list[ci]           - BASE
        gc_raw   = (gc_offs_list[ci] - BASE)   if ch['gc_bytes'] else 0
        desc     = struct.pack('>I', ptra_raw)
        desc    += struct.pack('>I', next_raw)
        desc    += bytes([ch['prim_type'], ch['fmt2'], 0x00, mat_to_write])
        desc    += ch['gx_attr_blk']   # 8 bytes: zero block + GX attr flags
        desc    += struct.pack('>I', dl_raw)
        desc    += struct.pack('>I', len(ch['dl_bytes']))
        desc    += struct.pack('>I', gc_raw)
        out     += desc

    # Display lists (one block per chunk, each already padded to 32-byte multiple)
    out += b'\x00' * pre_dl_pad   # align DL section start to 32-byte boundary
    for ch in chunks_out:
        out += ch['dl_bytes']

    # GX caches (one block per chunk, with 0x20 padding between them)
    gc_chunks = [(i, ch) for i, ch in enumerate(chunks_out) if ch['gc_bytes']]
    last_gc_index = gc_chunks[-1][0] if gc_chunks else -1
    
    for i, ch in enumerate(chunks_out):
        if ch['gc_bytes']:
            out += ch['gc_bytes']
            # Add 0x20 padding after each GC except the last one
            if i != last_gc_index:
                raw_size = len(ch['gc_bytes'])
                pad = (0x20 - raw_size) % 0x20 if raw_size < 0x20 else 0
                if pad:
                    out += b'\x00' * pad

    # String pool
    out += string_pool

    print(f"\n=== STRING POOL DEBUG ===")
    print(f"  String pool size: {len(string_pool)} bytes")
    for name, off in sorted(string_offsets.items(), key=lambda x: x[1]):
        print(f"    offset {off:4d}: {name!r}")

    # Pre-reloc alignment padding
    if reloc_pre_pad:
        out += b'\x00' * reloc_pre_pad

    # Relocation table
    out += reloc_bytes

    # Patch final file size into header.
    struct.pack_into('>I', out, 0x00, len(out))

    print(f"\n=== FILE OFFSET DEBUG ===")
    print(f"  File size: {len(out)} bytes")
    print(f"  pos_off=0x{pos_off:04X}, nrm_off=0x{nrm_off:04X}, uv_off=0x{uv_off:04X}")
    print(f"  mat_off=0x{mat_off:04X}, tpl_off=0x{tpl_off:04X}")
    print(f"  ptra_off=0x{ptra_off:04X}, chunk_off=0x{chunk_off:04X}")
    print(f"  dl_offs: {[hex(d) for d in dl_offs_list[:5]]}{'...' if len(dl_offs_list)>5 else ''}")
    print(f"  gc_offs: {[hex(g) if g else '0' for g in gc_offs_list[:5]]}{'...' if len(gc_offs_list)>5 else ''}")
    print(f"  string_pool_off=0x{string_pool_off:04X}")
    print(f"  reloc_table_off=0x{reloc_table_off:04X}")

    # ── Step 11: Write to disk ────────────────────────────────────────────────

    with open(filepath, 'wb') as f:
        f.write(out)

    tpl_total = sum(len(m['tpl_blocks']) for m in materials_out)
    total_faces = sum(len(fc) if not isinstance(fc, dict) else len(fc['face_indices']) for fc in chunk_face_lists)
    print(f"\n=== EXPORTED .gs (FULL REBUILD v13): {os.path.basename(filepath)} ===")
    print(f"  {len(out)} bytes  |  {v_count} verts  |  {total_faces} faces  |  {n_count} normals  |  "
          f"{uv_count} UVs  |  {n_chunks} chunks  |  {n_mats} materials  |  "
          f"{tpl_total} TPL blocks  |  {len(reloc_fields)} reloc entries")
    return True, (f"{len(out)} bytes written (full rebuild v13, {n_chunks} chunks, "
                  f"{n_mats} materials, {tpl_total} TPL blocks)")


# =============================================================================
# BONE TYPE PANEL
# =============================================================================
#
# # Adds a "Fire Emblem Bone Type" panel to Properties > Bone.
# # Displays the current fe_bone_flags value and three buttons to change it.
# #
# # The three flag values and their meanings:
# #   0x002F  Normal Bone      — standard animated skeleton bone
# #   0x0180  Deform Proxy     — mesh-proxy node, not directly animated
# #   0x018C  Attachment Point — weapon grip or hand attachment (type 0x018C)
# #
# # Operator: FE_OT_SetBoneType
# #   Accepts an int 'bone_type' parameter and writes it to
# #   context.active_bone['fe_bone_flags'].
# 
# class FE_OT_SetBoneType(bpy.types.Operator):
#     """Set the Fire Emblem bone type flag (fe_bone_flags) on the active bone"""
#     bl_idname  = "fe.set_bone_type"
#     bl_label   = "Set FE9 & FE10 Bone Type"
#     bl_options = {'UNDO', 'INTERNAL'}
# 
#     bone_type: IntProperty(
#         name="Bone Type",
#         description="fe_bone_flags value to write to the active bone",
#         default=0x002F,
#     )
# 
#     def execute(self, context):
#         bone = context.active_bone
#         if bone is None:
#             self.report({'WARNING'}, "No active bone selected.")
#             return {'CANCELLED'}
#         bone['fe_bone_flags'] = self.bone_type
#         label = next((n for v, n, _ in _FE_BONE_TYPE_ITEMS if v == self.bone_type),
#                      f"0x{self.bone_type:04X}")
#         self.report({'INFO'}, f"Set fe_bone_flags = {label} (0x{self.bone_type:04X})")
#         return {'FINISHED'}
# 
# 
# class FE_PT_BoneTypePanel(bpy.types.Panel):
#     """Fire Emblem bone type selector in Properties > Bone"""
#     bl_label       = "Fire Emblem Bone Type"
#     bl_idname      = "FE_PT_bone_type"
#     bl_space_type  = 'PROPERTIES'
#     bl_region_type = 'WINDOW'
#     bl_context     = "bone"
# 
#     @classmethod
#     def poll(cls, context):
#         return context.active_bone is not None
# 
#     def draw(self, context):
#         layout  = self.layout
#         bone    = context.active_bone
#         current = bone.get('fe_bone_flags', None)
#         mode    = context.scene.fe_bone_panel_mode
# 
#         # ── Status box ───────────────────────────────────────────────────────
#         all_items = _FE_BONE_TYPE_ITEMS + _FE_BONE_TYPE_ITEMS_BATTLE
#         box = layout.box()
#         if current is not None:
#             label = next((n for v, n, _ in all_items if v == current), "Unknown")
#             box.label(text=f"Current: {label}  (0x{current:04X})", icon='BONE_DATA')
#         else:
#             box.label(text="fe_bone_flags: (not set — bone not from FE9 & FE10 file)",
#                       icon='ERROR')
# 
#         # ── Model type selector ───────────────────────────────────────────────
#         layout.separator()
#         layout.label(text="Model type:")
#         row = layout.row(align=True)
#         row.prop_enum(context.scene, 'fe_bone_panel_mode', 'OVERWORLD')
#         row.prop_enum(context.scene, 'fe_bone_panel_mode', 'BATTLE')
# 
#         # ── Overworld section ─────────────────────────────────────────────────
#         layout.separator()
#         col = layout.column(align=True)
#         col.label(text="Overworld (ymu):")
#         col.enabled = (mode == 'OVERWORLD')
#         for val, name, desc in _FE_BONE_TYPE_ITEMS:
#             is_active = (current == val)
#             row = col.row(align=True)
#             row.alert = is_active and (mode == 'OVERWORLD')
#             op = row.operator(
#                 "fe.set_bone_type",
#                 text=f"{'✓ ' if is_active else ''}{name}  (0x{val:04X})",
#                 depress=is_active,
#             )
#             op.bone_type = val
# 
#         # ── Battle section ────────────────────────────────────────────────────
#         layout.separator()
#         col = layout.column(align=True)
#         col.label(text="Battle (zu):")
#         col.enabled = (mode == 'BATTLE')
#         for val, name, desc in _FE_BONE_TYPE_ITEMS_BATTLE:
#             is_active = (current == val)
#             row = col.row(align=True)
#             row.alert = is_active and (mode == 'BATTLE')
#             op = row.operator(
#                 "fe.set_bone_type",
#                 text=f"{'✓ ' if is_active else ''}{name}  (0x{val:04X})",
#                 depress=is_active,
#             )
#             op.bone_type = val


# =============================================================================
# IMPORT OPERATORS
# =============================================================================

class ImportGSkeleton(bpy.types.Operator, ImportHelper):
    """Import a Fire Emblem 9/10 .g skeleton file as a Blender Armature"""
    bl_idname  = "import_scene.g_skeleton"
    bl_label   = "Import .g Skeleton"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".g"
    filter_glob: StringProperty(default="*.g", options={'HIDDEN'})

    def execute(self, context):
        try:
            bones = read_skeleton_file(self.filepath)
            name  = os.path.splitext(os.path.basename(self.filepath))[0]
            create_armature(name, bones, skeleton_filepath=self.filepath)
            self.report({'INFO'}, f"Imported skeleton: {len(bones)} bones")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Skeleton import failed: {e}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}


class ImportGSMesh(bpy.types.Operator, ImportHelper):
    """Import a Fire Emblem 9/10 .gs mesh file"""
    bl_idname  = "import_mesh.gs"
    bl_label   = "Import .gs Mesh"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".gs"
    filter_glob: StringProperty(default="*.gs", options={'HIDDEN'})

    def execute(self, context):
        try:
            md   = read_gs_file(self.filepath)
            name = os.path.splitext(os.path.basename(self.filepath))[0]
            mesh_obj = create_blender_mesh(name, md)
            self.report({'INFO'},
                f"Imported: {len(md['vertices'])} verts, {len(md['faces'])} faces, "
                f"{len(md['materials'])} materials")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Mesh import failed: {e}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}


class ImportGSWithSkeleton(bpy.types.Operator, ImportHelper):
    """Import a .gs mesh and its paired .g skeleton together."""
    bl_idname  = "import_scene.gs_with_skeleton"
    bl_label   = "Import .gs + .g  (Mesh + Skeleton)"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".gs"
    filter_glob: StringProperty(default="*.gs", options={'HIDDEN'})

    def execute(self, context):
        try:
            folder = os.path.dirname(self.filepath)
            stem   = os.path.splitext(os.path.basename(self.filepath))[0]

            candidates = [
                os.path.join(folder, 'skeleton.g'),
                os.path.join(folder, stem.replace('body', 'skeleton') + '.g'),
                os.path.join(folder, stem + '.g'),
            ]
            skel_path = next((p for p in candidates if os.path.isfile(p)), None)
            if not skel_path:
                g_files = [f for f in os.listdir(folder)
                           if f.endswith('.g') and not f.endswith('.gs')
                           and not f.endswith('.ga')]
                if g_files:
                    skel_path = os.path.join(folder, g_files[0])
                    self.report({'WARNING'}, f"Guessed skeleton: {g_files[0]}")

            bones = None
            if skel_path and os.path.isfile(skel_path):
                bones = read_skeleton_file(skel_path)

            md       = read_gs_file(self.filepath, bones=bones)
            
            # Determine naming based on body filename
            # If body file is "body.gs", use grandparent directory as model_name
            basename = os.path.basename(self.filepath)
            if basename.lower() == 'body.gs':
                # Use grandparent (great-grandparent?) directory name
                # e.g., "pegasus/pack/body.gs" -> "pegasus"
                parent_dir = os.path.dirname(self.filepath)
                grandparent_dir = os.path.dirname(parent_dir)
                model_name = os.path.basename(grandparent_dir)
            else:
                # Use stem (filename without extension)
                model_name = stem
            
            # Create mesh with "_body" suffix
            mesh_obj = create_blender_mesh(model_name + '_body', md)

            if bones is not None:
                arm_obj = create_armature(model_name, bones, skeleton_filepath=skel_path)
                apply_skin_weights(mesh_obj, arm_obj,
                                   md.get('skin_weights', {}), bones)
                create_unit_vertex_groups(mesh_obj, arm_obj, bones)
                # Store original skeleton bone count so the exporter can
                # distinguish original bones from user-added or transplanted ones.
                mesh_obj['gs_orig_bone_count'] = len(bones)
                # Link mesh to its armature by name so the armature-select
                # exporter can find the main body mesh.
                mesh_obj['gs_armature_name'] = arm_obj.name
                arm_obj['gs_main_mesh_name'] = mesh_obj.name
                skinned = len(md.get('skin_weights', {}))
                self.report({'INFO'},
                    f"Imported '{model_name}': {len(md['vertices'])} verts + {len(bones)}-bone armature. "
                    f"Auto-skinned {skinned} verts. "
                    f"{len(md['materials'])} materials assigned.")
            else:
                self.report({'INFO'},
                    f"Imported '{model_name}': {len(md['vertices'])} verts (no skeleton found). "
                    f"{len(md['materials'])} materials assigned.")

            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Import failed: {e}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}


class ImportGAnimation(bpy.types.Operator, ImportHelper):
    """Import one or more Fire Emblem 9/10 .ga animation files onto an existing Armature."""
    bl_idname  = "import_anim.ga"
    bl_label   = "Import .ga Animation"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".ga"
    filter_glob: StringProperty(default="*.ga", options={'HIDDEN'})
    
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)

    skeleton_path: StringProperty(
        name="Skeleton File (optional)",
        description=(
            "Path to the .g skeleton file. "
            "Leave blank to auto-detect (same folder, then 'pack' sub-folder)."
        ),
        default="",
        subtype='FILE_PATH',
    )

    prefix_override: StringProperty(
        name="Action Prefix Override",
        description=(
            "Override the default prefix (source model name) for imported actions. "
            "Default: parent folder name (or grandparent if parent is 'pack'). "
            "Format: 'prefix - animation_name'"
        ),
        default="",
    )

    def get_prefix(self, filepath):
        """Calculate the action prefix from the file's parent folder."""
        # If user provided an override, check if it's a "nullifier"
        if self.prefix_override:
            # Nullifier characters: space, minus/dash, forward slash
            # If override is just one of these, use no prefix
            if self.prefix_override.strip() in ('-', '/'):
                return ""
            return self.prefix_override
        
        # Get parent directory name
        parent_dir = os.path.basename(os.path.dirname(filepath))
        
        # If parent is "pack", use grandparent
        if parent_dir.lower() == "pack":
            grandparent = os.path.dirname(os.path.dirname(filepath))
            if grandparent:
                return os.path.basename(grandparent)
            return "unknown"
        
        return parent_dir if parent_dir else "unknown"

    def execute(self, context):
        try:
            arm_obj = None
            obj = context.active_object
            if obj:
                if obj.type == 'ARMATURE':
                    arm_obj = obj
                elif obj.parent and obj.parent.type == 'ARMATURE':
                    arm_obj = obj.parent

            bone_id_to_name = {}
            if arm_obj:
                for bone in arm_obj.data.bones:
                    idx = bone.get('fe_bone_index')
                    if idx is not None:
                        bone_id_to_name[int(idx)] = bone.name

            if not bone_id_to_name:
                skel = self.skeleton_path if self.skeleton_path else None
                if not skel:
                    skel = find_skeleton_file(self.filepath)
                if skel:
                    for b in read_skeleton_file(skel):
                        bone_id_to_name[b['index']] = _safe_bone_name(b['name'])
                    if not arm_obj:
                        self.report({'WARNING'},
                            "No armature selected — animation imported but not "
                            "linked to any object.")

            if arm_obj is None:
                arm_data = bpy.data.armatures.new("anim_target")
                arm_obj  = bpy.data.objects.new("anim_target", arm_data)
                context.collection.objects.link(arm_obj)
                self.report({'WARNING'},
                    "No armature found. Action created on a placeholder object.")

            # Get list of files to import
            import_dir = os.path.dirname(self.filepath)
            if self.files:
                filepaths = [os.path.join(import_dir, f.name) for f in self.files if f.name.endswith('.ga')]
            else:
                filepaths = [self.filepath]
            
            imported_count = 0
            for filepath in filepaths:
                if not os.path.exists(filepath):
                    continue
                    
                ga_data = read_ga_file(filepath)
                anim_name = os.path.splitext(os.path.basename(filepath))[0]
                
                # Get prefix and create full action name
                prefix = self.get_prefix(filepath)
                if prefix:
                    full_action_name = f"{prefix} - {anim_name}"
                else:
                    full_action_name = anim_name
                
                action = import_ga_to_blender(context, ga_data, arm_obj, full_action_name)
                imported_count += 1

            self.report({'INFO'},
                f"Imported {imported_count} animation(s)")
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Animation import failed: {e}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}

    def draw(self, context):
        self.layout.prop(self, "files")
        self.layout.prop(self, "prefix_override")
        self.layout.prop(self, "skeleton_path")


# =============================================================================
# EXPORT OPERATORS
# =============================================================================

class ExportGSMesh(bpy.types.Operator, ExportHelper):
    """Export the active Mesh object as a Fire Emblem 9/10 body.gs file.

    Rebuilds the entire file from scratch: vertex positions, normals, and UVs
    are taken from the current Blender mesh; all other sections (display lists,
    GX caches, PtrA blocks, materials, string pool) are reconstructed from the
    original binary stored in gs_original_data with recomputed pointers.
    The original multi-chunk structure is preserved exactly.
    """
    bl_idname  = "export_mesh.gs"
    bl_label   = "Export .gs Mesh"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".gs"
    filter_glob: StringProperty(default="*.gs", options={'HIDDEN'})

    vertex_color_mode: EnumProperty(
        name="Vertex Colors:",
        description="Vertex color lighting handling on export",
        items=[
            ('BLENDER', "From Blender",
             "Read vertex colors from Blender's color attribute"),
            ('WHITE', "White",
             "Replace all vertex colors with uniform white (255,255,255,255) — full brightness"),
            ('NONE', "None",
             "Strip all vertex color data — no color table written"),
        ],
        default='BLENDER',
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text="Vertex Colors:")
        layout.prop(self, "vertex_color_mode", expand=True)

    def execute(self, context):
        print(">>> EXPORTGS MESH EXECUTE CALLED <<<")
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "Select a Mesh object first.")
            return {'CANCELLED'}
        if not obj.get('gs_original_data'):
            self.report({'ERROR'},
                "This mesh has no gs_original_data — import it with this plugin first.")
            return {'CANCELLED'}
        try:
            ok, msg = export_gs_full_rebuild(obj, self.filepath,
                                             vc_mode=self.vertex_color_mode)
            if ok:
                self.report({'INFO'}, f"Exported mesh: {msg}")
                return {'FINISHED'}
            else:
                self.report({'ERROR'}, f"Export failed: {msg}")
                return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"Mesh export error: {e}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}


class ExportGSkeleton(bpy.types.Operator, ExportHelper):
    """Export the active Armature as an FE9 & FE10 skeleton.g file."""
    bl_idname  = "export_scene.g_skeleton"
    bl_label   = "Export .g Skeleton"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".g"
    filter_glob: StringProperty(default="*.g", options={'HIDDEN'})

    source_g_filepath: StringProperty(
        name="Reference .g File",
        description=(
            "Path to the original skeleton .g file. In preserve mode, matching bones "
            "keep their original index. In hierarchy mode, used for raw record data. "
            "Auto-filled from the armature's stored import path."
        ),
        default="",
        subtype='FILE_PATH',
    )

    bone_order: bpy.props.EnumProperty(
        name="Bone Order",
        description="How bone ordering is determined during skeleton export",
        items=[
            ('RELATIONSHIPS', "Blender Hierarchy",
             "Bone order is re-structured based on bone hierarchy (relationships) "
             "in Blender.  New bones are inserted at their correct hierarchy "
             "position and all indices are recalculated."),
            ('REFERENCE', "Preserve Original",
             "Bone order from the reference skeleton is preserved, with new "
             "bone data appended at the end."),
        ],
        default='RELATIONSHIPS',
    )

    def invoke(self, context, event):
        obj = context.active_object
        if obj and obj.type == 'ARMATURE':
            if obj.get('fe_skeleton_filepath'):
                self.source_g_filepath = obj['fe_skeleton_filepath']
                print(f"  Auto-filled reference skeleton: {self.source_g_filepath}")
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Select an Armature object first.")
            return {'CANCELLED'}

        ref_skel = None
        if self.source_g_filepath and os.path.isfile(self.source_g_filepath):
            ref_skel = self.source_g_filepath
        
        try:
            ok = write_skeleton_file(obj, self.filepath,
                                     source_filepath=ref_skel,
                                     append_new_bones=(self.bone_order == 'REFERENCE'))
            if ok:
                self.report({'INFO'}, f"Exported skeleton: {self.filepath}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Skeleton export failed: {e}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "source_g_filepath")
        layout.label(text="Bone Order:")
        layout.prop(self, "bone_order", expand=True)


def _get_export_action_items(self, context):
    """Callback to populate the Action to Export dropdown."""
    obj = context.active_object
    items = [('NONE', 'None', 'Select an action')]
    if obj and obj.animation_data:
        linked_actions = set()
        anim_data = obj.animation_data
        
        if anim_data.action:
            linked_actions.add(anim_data.action.name)
        
        if hasattr(anim_data, 'action_slot') and anim_data.action_slot:
            slot = anim_data.action_slot
            for act in bpy.data.actions:
                if any(s.handle == slot.handle for s in act.slots):
                    linked_actions.add(act.name)
        
        for act in bpy.data.actions:
            if act.name not in linked_actions:
                if 'Start Frame' in act or 'ga_game_flag' in act or 'ga_loop_flag' in act:
                    linked_actions.add(act.name)
        
        sorted_names = sorted(linked_actions)
        for name in sorted_names:
            items.append((name, name, name))
    
    return items


class ExportGAnimation(bpy.types.Operator, ExportHelper):
    """Export one or more Actions on the active Armature as .ga animation file(s)."""
    bl_idname  = "export_anim.ga"
    bl_label   = "Export .ga Animation"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".ga"
    filter_glob: StringProperty(default="*.ga", options={'HIDDEN'})

    export_all: bpy.props.BoolProperty(
        name="Export All Actions",
        description="Export all Actions on the armature as separate .ga files",
        default=False,
    )
    
    remove_prefix: bpy.props.BoolProperty(
        name="Remove prefix from name",
        description="Remove the prefix before the first space in action names. "
                    "Example: 'swordref - wait_N' becomes 'wait_N'",
        default=False,
    )
    
    action_filter: bpy.props.StringProperty(
        name="Action Filter",
        description=(
            "Filter actions by name. Use * as wildcard. "
            "Example: 'lord - *' exports all actions starting with 'lord - '. "
            "Comma-separated: 'atk,idle' exports both."
        ),
        default="",
    )

    def get_actions_to_export(self, context):
        """Get list of actions matching the filter."""
        actions_to_export = []
        obj = context.active_object
        
        # Get the active action from the armature
        active_action = None
        if obj and obj.animation_data:
            active_action = obj.animation_data.action
        
        if self.export_all:
            # Export all actions (both imported and baked)
            for act in bpy.data.actions:
                actions_to_export.append(act)
        else:
            # Filter actions by name pattern
            filter_text = self.action_filter.strip()
            
            if not filter_text:
                # No filter - export the current active action
                if active_action:
                    actions_to_export.append(active_action)
                return actions_to_export
            
            # Support comma-separated and wildcards
            filters = [f.strip() for f in filter_text.split(',')]
            
            for act in bpy.data.actions:
                # Check if action matches any filter
                for filt in filters:
                    # Convert glob * to regex
                    import re
                    pattern = filt.replace('*', '.*').replace('?', '.')
                    if re.match(pattern, act.name, re.IGNORECASE):
                        actions_to_export.append(act)
                        break
        
        return actions_to_export

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Select an Armature with an active Action.")
            return {'CANCELLED'}

        export_dir = os.path.dirname(self.filepath)
        
        # Get list of actions to export
        actions_to_export = self.get_actions_to_export(context)
        
        if not actions_to_export:
            self.report({'ERROR'}, "No actions match the filter.")
            return {'CANCELLED'}
        
        exported_count = 0
        for act in actions_to_export:
            # Get start/end frames from action properties
            start_frame = int(act.get('Start Frame', context.scene.frame_preview_start))
            end_frame = int(act.get('End Frame', context.scene.frame_preview_end))
            
            # Temporarily set the action as active for export
            original_action = None
            if obj.animation_data:
                original_action = obj.animation_data.action
                obj.animation_data.action = act
            
            # Use action name as filename stem, preserve .ga extension
            # If remove_prefix is enabled, split by space and use last part
            if self.remove_prefix and ' ' in act.name:
                name_stem = act.name.rsplit(' ', 1)[-1]
            else:
                name_stem = act.name
            out_filename = f"{name_stem}.ga"
            out_path = os.path.join(export_dir, out_filename)
            
            try:
                ok = export_ga_from_blender(obj, act, out_path)
                if ok:
                    exported_count += 1
            except Exception as e:
                self.report({'ERROR'}, f"Export failed for {act.name}: {e}")
            finally:
                # Restore original action
                if obj.animation_data and original_action:
                    obj.animation_data.action = original_action
        
        if exported_count > 0:
            self.report({'INFO'}, f"Exported {exported_count} animation(s)")
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, "No animations were successfully exported.")
            return {'CANCELLED'}
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "export_all")
        layout.prop(self, "remove_prefix")
        if not self.export_all:
            layout.prop(self, "action_filter")
            # Show matching actions preview
            matching = self.get_actions_to_export(context)
            if matching:
                box = layout.box()
                box.label(text=f"Will export {len(matching)} action(s):")
                for act in matching[:5]:  # Show first 5
                    box.label(text=f"  - {act.name}")
                if len(matching) > 5:
                    box.label(text=f"  ... and {len(matching)-5} more")
            elif self.action_filter:
                layout.label(text="No actions match filter")


# =============================================================================
# ARMATURE-SELECT EXPORT OPERATOR — select armature, pick mesh roles
# =============================================================================
#
# Workflow:
#   1. Select the Armature in the 3D viewport.
#   2. File > Export > FE9 & FE10 from Armature …
#   3. The file-browser panel shows every mesh object that uses this armature
#      (via Armature modifier or parent).  Each mesh has two checkboxes:
#        • "Main" — exactly one mesh must be checked as main; it is exported
#          as the primary body .gs using its gs_original_data for chunk layout.
#          If no mesh is checked as main, all geometry is treated as all-new.
#        • "Include" — if unchecked the mesh is skipped entirely.
#   4. All "Include"-checked non-main meshes become addon chunks.
#
# The operator stores the per-mesh selections as a scene-level string property
# so they survive invoke → execute round-trips.

def _get_armature_meshes(arm_obj):
    """Return all mesh objects in the scene that use arm_obj as their armature."""
    result = []
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        uses = False
        for mod in obj.modifiers:
            if mod.type == 'ARMATURE' and mod.object == arm_obj:
                uses = True
                break
        if not uses and obj.parent == arm_obj:
            uses = True
        if uses:
            result.append(obj)
    return result


class ExportFromArmature(bpy.types.Operator, ExportHelper):
    """Export .gs body + .g skeleton by selecting the Armature.
    Lets you designate one mesh as the 'main' original body and any number of
    additional meshes as addon geometry that becomes new chunks."""
    bl_idname  = "export_scene.fe_from_armature"
    bl_label   = "Export .gs + .g from Armature"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".gs"
    filter_glob: StringProperty(default="*.gs", options={'HIDDEN'})

    gs_filename: StringProperty(
        name="Body Filename",
        description="Filename for the exported .gs body mesh",
        default="body",
    )
    g_filename: StringProperty(
        name="Skeleton Filename",
        description="Filename for the exported .g skeleton",
        default="skeleton",
    )
    source_g_filepath: StringProperty(
        name="Reference .g File",
        description=(
            "Path to the original skeleton .g file. In preserve mode, matching bones "
            "keep their original index. In hierarchy mode, used for raw record data. "
            "Auto-filled from the armature's stored import path."
        ),
        default="",
        subtype='FILE_PATH',
    )

    bone_order: bpy.props.EnumProperty(
        name="Bone Order",
        description="How bone ordering is determined during skeleton export",
        items=[
            ('RELATIONSHIPS', "Blender Hierarchy",
             "Bone order is re-structured based on bone hierarchy (relationships) "
             "in Blender.  New bones are inserted at their correct hierarchy "
             "position and all indices are recalculated."),
            ('REFERENCE', "Preserve Original",
             "Bone order from the reference skeleton is preserved, with new "
             "bone data appended at the end."),
        ],
        default='RELATIONSHIPS',
    )

    # Comma-separated names of meshes to include; prefix '*' = the main mesh.
    # Example: "*d_knight3_h_body,dragon_sword_mesh"
    # Empty string = auto-detect (first mesh with gs_original_data is main).
    mesh_selection: StringProperty(default="", options={'HIDDEN'})

    vertex_color_mode: EnumProperty(
        name="Vertex Colors:",
        description="Vertex color lighting handling on export",
        items=[
            ('BLENDER', "From Blender",
             "Read vertex colors from Blender's color attribute"),
            ('WHITE', "White",
             "Replace all vertex colors with uniform white (255,255,255,255) — full brightness"),
            ('NONE', "None",
             "Strip all vertex color data — no color table written"),
        ],
        default='BLENDER',
    )

    # Per-instance state set in invoke, read in draw/execute.
    # Can't use CollectionProperty easily with ExportHelper, so we serialise
    # the checklist as a compact string stored on the operator instance.
    # Format:  "main=<name>|include=<name1>,<name2>"
    # "main=" may be empty (all-new).
    selection_str: StringProperty(default="", options={'HIDDEN'})

    def _parse_selection(self):
        """Return (main_name_or_None, {included_name: bool}) from selection_str."""
        import re
        s = self.selection_str
        main_name = None
        included  = {}
        m = re.search(r'main=([^|]*)', s)
        if m:
            v = m.group(1).strip()
            main_name = v if v else None
        m = re.search(r'include=([^|]*)', s)
        if m:
            for tok in m.group(1).split(','):
                tok = tok.strip()
                if tok:
                    included[tok] = True
        return main_name, included

    def _build_selection(self, main_name, included):
        inc_str = ','.join(k for k, v in included.items() if v)
        self.selection_str = f"main={main_name or ''}|include={inc_str}"

    def invoke(self, context, event):
        arm_obj = context.active_object
        if arm_obj is None or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Select an Armature object first.")
            return {'CANCELLED'}

        meshes = _get_armature_meshes(arm_obj)
        if not meshes:
            self.report({'ERROR'}, "No mesh objects found using this armature.")
            return {'CANCELLED'}

        # Auto-fill reference skeleton from armature's stored filepath
        if arm_obj.get('fe_skeleton_filepath'):
            self.source_g_filepath = arm_obj['fe_skeleton_filepath']
            print(f"  Auto-filled reference skeleton: {self.source_g_filepath}")

        # Auto-select defaults: first mesh with gs_original_data is main,
        # all meshes included.
        main_name = None
        included  = {}
        for obj in meshes:
            included[obj.name] = True
            if main_name is None and obj.get('gs_original_data'):
                main_name = obj.name

        self._build_selection(main_name, included)
        # Also seed the scene scratchpad so draw() reads consistent state
        # before the user presses any toggle buttons.
        context.scene['_fe_export_sel'] = self.selection_str
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        layout = self.layout
        arm_obj = context.active_object
        if arm_obj is None or arm_obj.type != 'ARMATURE':
            layout.label(text="No armature selected.", icon='ERROR')
            return

        meshes = _get_armature_meshes(arm_obj)

        # Read current selection state from the scene scratchpad
        # (written by FE_OT_ToggleMeshRole).  Fall back to self.selection_str
        # on the very first draw before any toggles have been pressed.
        import re
        raw = context.scene.get('_fe_export_sel', self.selection_str)
        main_name = ''
        inc_set   = set()
        m = re.search(r'main=([^|]*)', raw)
        if m: main_name = m.group(1).strip()
        m = re.search(r'include=([^|]*)', raw)
        if m:
            for t in m.group(1).split(','):
                t = t.strip()
                if t: inc_set.add(t)

        layout.label(text="Mesh objects using this armature:", icon='MESH_DATA')
        box = layout.box()
        for obj in meshes:
            row = box.row(align=True)
            has_orig = bool(obj.get('gs_original_data'))
            is_main  = (obj.name == main_name)
            is_inc   = (obj.name in inc_set)

            # "Include" toggle
            inc_icon = 'CHECKBOX_HLT' if is_inc else 'CHECKBOX_DEHLT'
            op = row.operator("export_scene.fe_toggle_mesh_role",
                              text="", icon=inc_icon, emboss=False)
            op.mesh_name   = obj.name
            op.toggle_what = 'include'

            # "Main" radio button
            main_icon = 'RADIOBUT_ON' if is_main else 'RADIOBUT_OFF'
            op2 = row.operator("export_scene.fe_toggle_mesh_role",
                               text="", icon=main_icon, emboss=False)
            op2.mesh_name   = obj.name
            op2.toggle_what = 'main'

            label = obj.name
            if has_orig:
                label += "  [has gs_data]"
            if is_main:
                label += "  ← MAIN"
            row.label(text=label)

        layout.separator()
        layout.prop(self, "gs_filename")
        layout.prop(self, "g_filename")
        layout.prop(self, "source_g_filepath")

        layout.separator()
        layout.label(text="Bone Order:")
        layout.prop(self, "bone_order", expand=True)

        layout.separator()
        layout.label(text="Vertex Colors:")
        layout.prop(self, "vertex_color_mode", expand=True)

    def execute(self, context):
        arm_obj = context.active_object
        if arm_obj is None or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Select an Armature object first.")
            return {'CANCELLED'}

        # Read selection from scene scratchpad (set by FE_OT_ToggleMeshRole
        # via the draw() buttons), falling back to self.selection_str.
        import re
        raw = context.scene.get('_fe_export_sel', self.selection_str)
        main_name = ''
        inc_set   = set()
        m = re.search(r'main=([^|]*)', raw)
        if m: main_name = m.group(1).strip()
        m = re.search(r'include=([^|]*)', raw)
        if m:
            for t in m.group(1).split(','):
                t = t.strip()
                if t: inc_set.add(t)

        meshes = _get_armature_meshes(arm_obj)
        main_obj   = None
        addon_objs = []
        for obj in meshes:
            if obj.name not in inc_set:
                continue
            if obj.name == main_name:
                main_obj = obj
            else:
                addon_objs.append(obj)

        # Auto-pick main if none selected
        if main_obj is None:
            for obj in meshes:
                if obj.get('gs_original_data') and obj.name in inc_set:
                    main_obj = obj
                    break

        if main_obj is None and not addon_objs:
            self.report({'ERROR'}, "No mesh objects selected for export.")
            return {'CANCELLED'}

        if main_obj is None:
            self.report({'ERROR'},
                "No main mesh selected. At least one mesh with gs_original_data "
                "must be designated as main.")
            return {'CANCELLED'}

        if not main_obj.get('gs_original_data'):
            self.report({'ERROR'},
                f"'{main_obj.name}' has no gs_original_data — "
                "import it with this plugin first.")
            return {'CANCELLED'}

        # Resolve output paths.
        if hasattr(self, 'filepath') and self.filepath:
            export_dir = os.path.dirname(self.filepath)
        else:
            export_dir = bpy.path.abspath("//") or os.path.expanduser("~")

        g_name  = self.g_filename  if self.g_filename.endswith('.g')  else self.g_filename  + '.g'
        gs_name = self.gs_filename if self.gs_filename.endswith('.gs') else self.gs_filename + '.gs'
        g_out   = os.path.join(export_dir, g_name)
        gs_out  = os.path.join(export_dir, gs_name)

        # Validate reference skeleton.
        ref_skel = None
        if self.source_g_filepath and os.path.isfile(self.source_g_filepath):
            ref_skel = self.source_g_filepath

        # Step 1: export skeleton.
        try:
            write_skeleton_file(arm_obj, g_out, source_filepath=ref_skel,
                                append_new_bones=(self.bone_order == 'REFERENCE'))
        except Exception as e:
            self.report({'ERROR'}, f"Skeleton export failed: {e}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}

        # Step 2: export body with addon meshes.
        try:
            ok, msg = export_gs_full_rebuild(
                main_obj, gs_out,
                addon_mesh_objs=addon_objs if addon_objs else None,
                vc_mode=self.vertex_color_mode,
                append_new_bones=(self.bone_order == 'REFERENCE'),
            )
            if ok:
                addon_note = f" + {len(addon_objs)} addon mesh(es)" if addon_objs else ""
                self.report({'INFO'}, f"Exported: {g_out}, {gs_out}{addon_note}")
                return {'FINISHED'}
            else:
                self.report({'ERROR'}, f"Mesh export failed: {msg}")
                return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"Mesh export error: {e}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}


class FE_OT_ToggleMeshRole(bpy.types.Operator):
    """Toggle a mesh's role (include / main) in the armature export panel."""
    bl_idname  = "export_scene.fe_toggle_mesh_role"
    bl_label   = "Toggle Mesh Role"
    bl_options = {'INTERNAL'}

    mesh_name:   StringProperty()
    toggle_what: StringProperty()   # 'include' or 'main'

    def execute(self, context):
        # Find the ExportFromArmature operator instance via the active operator.
        # In Blender, draw() buttons that call operators share state through the
        # operator's properties on the window manager.  We piggyback on a scene
        # custom property as a shared scratchpad since operator instances
        # can't directly call back to the parent FileSelectOperator.
        scene = context.scene
        raw = scene.get('_fe_export_sel', '')
        # Parse: "main=X|include=A,B,C"
        import re
        main_name = ''
        inc_set   = set()
        m = re.search(r'main=([^|]*)', raw)
        if m: main_name = m.group(1).strip()
        m = re.search(r'include=([^|]*)', raw)
        if m:
            for t in m.group(1).split(','):
                t = t.strip()
                if t: inc_set.add(t)

        if self.toggle_what == 'main':
            main_name = self.mesh_name if main_name != self.mesh_name else ''
            # When setting a new main, also ensure it's included.
            if main_name:
                inc_set.add(main_name)
        elif self.toggle_what == 'include':
            if self.mesh_name in inc_set:
                inc_set.discard(self.mesh_name)
                if self.mesh_name == main_name:
                    main_name = ''
            else:
                inc_set.add(self.mesh_name)

        scene['_fe_export_sel'] = f"main={main_name}|include={','.join(sorted(inc_set))}"
        # Force the file browser to redraw so checkboxes update.
        for area in context.screen.areas:
            area.tag_redraw()
        return {'FINISHED'}

# =============================================================================
# OPERATOR — Prepare Custom Action Properties
# =============================================================================

class FE_OT_PrepareActionExport(bpy.types.Operator):
    bl_idname  = "fe.prepare_action_export"
    bl_label   = "Prepare Action for Export (FE9 & FE10)"
    bl_description = (
        "Set Start Frame, End Frame, game flag, and loop flag "
        "on the current action for .ga export."
    )

    def execute(self, context):
        arm_obj = context.active_object
        if arm_obj is None or arm_obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Active object must be an armature.")
            return {'CANCELLED'}
        
        action = None
        if arm_obj.animation_data:
            action = arm_obj.animation_data.action
        
        if action is None:
            self.report({'ERROR'}, "No active action on the armature.")
            return {'CANCELLED'}
        
        scene = bpy.context.scene
        
        start_f = int(scene.frame_start)
        end_f = int(scene.frame_end)
        
        if 'Start Frame' in action:
            del action['Start Frame']
        if 'End Frame' in action:
            del action['End Frame']
        
        action['Start Frame'] = start_f
        action['End Frame'] = end_f
        
        if 'ga_game_flag' not in action:
            action['ga_game_flag'] = 0
        
        if 'ga_loop_flag' not in action:
            action['ga_loop_flag'] = 0
        
        self.report({'INFO'},
                    f"Action '{action.name}' prepared: "
                    f"Start={start_f}, End={end_f}, "
                    f"ga_game_flag={action['ga_game_flag']}, "
                    f"ga_loop_flag={action['ga_loop_flag']}")
        return {'FINISHED'}


def _menu_prepare_action(self, context):
    self.layout.operator(FE_OT_PrepareActionExport.bl_idname,
                         text="Prepare Action for Export (FE9 & FE10)")


class FE_PT_ActionExportProps(bpy.types.Panel):
    bl_label = "Tellius Forge"
    bl_idname = "FE_PT_ActionExportProps"
    bl_space_type = 'DOPESHEET_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Action"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return (context.area.type == 'DOPESHEET_EDITOR'
                and space and space.mode == 'ACTION'
                and context.active_object
                and context.active_object.type == 'ARMATURE'
                and context.active_object.animation_data
                and context.active_object.animation_data.action)

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.operator(FE_OT_PrepareActionExport.bl_idname, text="Prepare Action for Export (FE9 & FE10)", icon='EXPORT')
        action = context.active_object.animation_data.action
        if action:
            box = layout.box()
            col = box.column(align=True)
            col.label(text="Current Properties:", icon='INFO')
            start = action.get('Start Frame', '—')
            end = action.get('End Frame', '—')
            game = action.get('ga_game_flag', '—')
            loop = action.get('ga_loop_flag', '—')
            col.label(text=f"  Start Frame: {start}")
            col.label(text=f"  End Frame:   {end}")
            col.label(text=f"  Game Flag:   {game}")
            col.label(text=f"  Loop Flag:   {loop}")


class FE_OT_ApplyFePoseToPose(bpy.types.Operator):
    bl_idname = "pose.apply_fe_pose_to_pose"
    bl_label = "Apply fe_pose to Pose (FE9 & Fe10)"
    bl_description = "Apply fe_pose_location and fe_pose_rotation to selected pose bones"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected_pose_bones = [pb for pb in context.selected_pose_bones]
        if not selected_pose_bones:
            self.report({'WARNING'}, "No pose bones selected")
            return {'CANCELLED'}

        applied_count = 0
        for pbone in selected_pose_bones:
            # Get fe_pose custom properties
            fe_pose_loc = pbone.get('fe_pose_location')
            fe_pose_rot = pbone.get('fe_pose_rotation')

            if fe_pose_loc is None and fe_pose_rot is None:
                continue

            # Set rotation mode to XYZ Euler
            pbone.rotation_mode = 'XYZ'

            # Apply fe_pose_location to pose bone location
            if fe_pose_loc is not None and any(abs(v) > 1e-6 for v in fe_pose_loc):
                pbone.location = fe_pose_loc

            # Apply fe_pose_rotation to pose bone rotation
            if fe_pose_rot is not None and any(abs(v) > 1e-6 for v in fe_pose_rot):
                pbone.rotation_euler = Euler(fe_pose_rot, 'XYZ')

            applied_count += 1

        self.report({'INFO'}, f"Applied fe_pose to {applied_count} pose bone(s)")
        return {'FINISHED'}


def _menu_apply_fe_pose(self, context):
    self.layout.operator(FE_OT_ApplyFePoseToPose.bl_idname,
                         text="Apply fe_pose to Pose (FE9 & FE10)")


# =============================================================================
# MENU REGISTRATION
# =============================================================================

def _menu_mesh(self, context):
    self.layout.operator(ImportGSMesh.bl_idname,
                         text=f"FE9 & FE10 Body {plugin_version} (.gs)")

def _menu_skel_import(self, context):
    self.layout.operator(ImportGSkeleton.bl_idname,
                         text=f"FE9 & FE10 Skeleton {plugin_version} (.g)")

def _menu_both(self, context):
    self.layout.operator(ImportGSWithSkeleton.bl_idname,
                         text=f"FE9 & FE10 Body + Skeleton {plugin_version} (.gs + .g)")

def _menu_from_armature(self, context):
    self.layout.operator(ExportFromArmature.bl_idname,
                         text=f"FE9 & FE10 Body + Skeleton from Armature {plugin_version} (.gs + .g)")

def _menu_anim_import(self, context):
    self.layout.operator(ImportGAnimation.bl_idname,
                         text=f"FE9 & FE10 Animation {plugin_version} (.ga)")

def _menu_mesh_export(self, context):
    self.layout.operator(ExportGSMesh.bl_idname,
                         text=f"FE9 & FE10 Body {plugin_version} (.gs)")

def _menu_skel_export(self, context):
    self.layout.operator(ExportGSkeleton.bl_idname,
                         text=f"FE9 & FE10 Skeleton {plugin_version} (.g)")

def _menu_anim_export(self, context):
    self.layout.operator(ExportGAnimation.bl_idname,
                         text=f"FE9 & FE10 Animation {plugin_version} (.ga)")


def register():
    # bpy.types.Scene.fe_bone_panel_mode = bpy.props.EnumProperty(
    #     name="FE9 & FE10 Bone Panel Mode",
    #     description="Which model type's bone flags to display and edit",
    #     items=[
    #         ('OVERWORLD', "Overworld (ymu)", "Flags used in overworld character models"),
    #         ('BATTLE',    "Battle (zu)",     "Flags used in battle character models"),
    #     ],
    #     default='OVERWORLD',
    # )
    bpy.utils.register_class(ImportGSMesh)
    bpy.utils.register_class(ImportGSkeleton)
    bpy.utils.register_class(ImportGSWithSkeleton)
    bpy.utils.register_class(ImportGAnimation)
    bpy.utils.register_class(ExportGSMesh)
    bpy.utils.register_class(ExportGSkeleton)
    bpy.utils.register_class(ExportFromArmature)
    bpy.utils.register_class(FE_OT_ToggleMeshRole)
    bpy.utils.register_class(ExportGAnimation)
    # bpy.utils.register_class(FE_OT_SetBoneType)
    # bpy.utils.register_class(FE_PT_BoneTypePanel)
    bpy.utils.register_class(FE_OT_PrepareActionExport)
    bpy.utils.register_class(FE_PT_ActionExportProps)
    bpy.utils.register_class(FE_OT_ApplyFePoseToPose)

    bpy.types.TOPBAR_MT_file_import.append(_menu_mesh)
    bpy.types.TOPBAR_MT_file_import.append(_menu_skel_import)
    bpy.types.TOPBAR_MT_file_import.append(_menu_both)
    bpy.types.TOPBAR_MT_file_import.append(_menu_anim_import)
    bpy.types.TOPBAR_MT_file_export.append(_menu_mesh_export)
    bpy.types.TOPBAR_MT_file_export.append(_menu_skel_export)
    bpy.types.TOPBAR_MT_file_export.append(_menu_from_armature)
    bpy.types.TOPBAR_MT_file_export.append(_menu_anim_export)
    bpy.types.VIEW3D_MT_pose.append(_menu_prepare_action)
    bpy.types.VIEW3D_MT_pose.append(_menu_apply_fe_pose)
    bpy.types.DOPESHEET_MT_action.append(_menu_prepare_action)


def unregister():
    bpy.utils.unregister_class(ImportGSMesh)
    bpy.utils.unregister_class(ImportGSkeleton)
    bpy.utils.unregister_class(ImportGSWithSkeleton)
    bpy.utils.unregister_class(ImportGAnimation)
    bpy.utils.unregister_class(ExportGSMesh)
    bpy.utils.unregister_class(ExportGSkeleton)
    bpy.utils.unregister_class(ExportFromArmature)
    bpy.utils.unregister_class(FE_OT_ToggleMeshRole)
    bpy.utils.unregister_class(ExportGAnimation)
    # bpy.utils.unregister_class(FE_OT_SetBoneType)
    # bpy.utils.unregister_class(FE_PT_BoneTypePanel)
    bpy.utils.unregister_class(FE_OT_PrepareActionExport)
    bpy.utils.unregister_class(FE_PT_ActionExportProps)
    bpy.utils.unregister_class(FE_OT_ApplyFePoseToPose)

    bpy.types.TOPBAR_MT_file_import.remove(_menu_mesh)
    bpy.types.TOPBAR_MT_file_import.remove(_menu_skel_import)
    bpy.types.TOPBAR_MT_file_import.remove(_menu_both)
    bpy.types.TOPBAR_MT_file_import.remove(_menu_anim_import)
    bpy.types.TOPBAR_MT_file_export.remove(_menu_mesh_export)
    bpy.types.TOPBAR_MT_file_export.remove(_menu_skel_export)
    bpy.types.TOPBAR_MT_file_export.remove(_menu_from_armature)
    bpy.types.TOPBAR_MT_file_export.remove(_menu_anim_export)
    bpy.types.VIEW3D_MT_pose.remove(_menu_prepare_action)
    bpy.types.VIEW3D_MT_pose.remove(_menu_apply_fe_pose)
    bpy.types.DOPESHEET_MT_action.remove(_menu_prepare_action)
    # del bpy.types.Scene.fe_bone_panel_mode


if __name__ == "__main__":
    register()
