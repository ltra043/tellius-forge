#!/usr/bin/env python3
"""Quick parser and analyzer for FE9/FE10 skeleton files (.g extension).
Drag a .g file onto this script to generate a markdown report.
"""

import sys
import os
import math
import struct


FIRST_BONE_OFFSET = 0x10  # 16 bytes
BONE_STRIDE = 0xF4        # 244 bytes


def ru4(data, offset):
    return struct.unpack('>I', data[offset:offset+4])[0]

def ri4(data, offset):
    return struct.unpack('>i', data[offset:offset+4])[0]

def rf4(data, offset):
    return struct.unpack('>f', data[offset:offset+4])[0]


def _mat3_identity():
    return [[1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0]]

def _mat3_mul(A, B):
    return [[sum(A[r][k] * B[k][c] for k in range(3)) for c in range(3)] for r in range(3)]

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
    return _mat3_mul(_rot_z(deg_xyz[2]),
                     _mat3_mul(_rot_y(deg_xyz[1]), _rot_x(deg_xyz[0])))


def is_class_b(bone_flags):
    return bone_flags in (0x0026, 0x0066)


def parse_skeleton(filepath):
    with open(filepath, 'rb') as f:
        raw = f.read()

    string_pool_offset = ru4(raw, 0x04)
    bone_count = ru4(raw, 0x08)

    # Parse string pool
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
        base = FIRST_BONE_OFFSET + b * BONE_STRIDE

        parent_raw = ri4(raw, base + 0)
        bone_flags = ru4(raw, base + 12)

        px88 = rf4(raw, base + 88)
        py88 = rf4(raw, base + 92)
        pz88 = rf4(raw, base + 96)

        prot_x = rf4(raw, base + 100)
        prot_y = rf4(raw, base + 104)
        prot_z = rf4(raw, base + 108)

        px112 = rf4(raw, base + 112)
        py112 = rf4(raw, base + 116)
        pz112 = rf4(raw, base + 120)

        name_off = ru4(raw, base + BONE_STRIDE - 4)
        name = string_map.get(name_off, f'bone_{b}')
        parent_idx = parent_raw if parent_raw >= 0 else None

        bones.append({
            'index': b,
            'name': name,
            'parent_idx': parent_idx,
            'bone_flags': bone_flags,
            'p88': (px88, py88, pz88),
            'p100': (prot_x, prot_y, prot_z),
            'p112': (px112, py112, pz112),
        })

    # Compute true world positions (rotation-aware accumulation)
    def has_b_ancestor(idx):
        par = bones[idx]['parent_idx']
        while par is not None:
            if is_class_b(bones[par]['bone_flags']):
                return True
            par = bones[par]['parent_idx']
        return False

    b_chain_pos = {}
    b_chain_rot = {}
    true_world = {}

    for b in bones:
        idx = b['index']
        flags = b['bone_flags']
        par = b['parent_idx']
        deg = b['p100']
        local_R = _local_rotation(deg) if any(abs(d) > 1e-6 for d in deg) else _mat3_identity()

        if par is None:
            true_world[idx] = b['p112']
            continue

        if not is_class_b(flags) and not has_b_ancestor(idx):
            true_world[idx] = b['p112']
            continue

        if is_class_b(flags):
            pw = b_chain_pos.get(par, (0.0, 0.0, 0.0))
            pR = b_chain_rot.get(par, _mat3_identity())
            rt = _apply_rot(pR, b['p88'])
            wx, wy, wz = pw[0]+rt[0], pw[1]+rt[1], pw[2]+rt[2]
            b_chain_pos[idx] = (wx, wy, wz)
            b_chain_rot[idx] = _mat3_mul(pR, local_R)
            true_world[idx] = (wx, wy, wz)
            continue

        # Class A with B ancestor
        nb_pos = (0.0, 0.0, 0.0)
        nb_rot = _mat3_identity()
        anc = par
        while anc is not None:
            if is_class_b(bones[anc]['bone_flags']):
                nb_pos = b_chain_pos.get(anc, (0.0, 0.0, 0.0))
                nb_rot = b_chain_rot.get(anc, _mat3_identity())
                break
            anc = bones[anc]['parent_idx']
        rt = _apply_rot(nb_rot, b['p112'])
        wx, wy, wz = nb_pos[0]+rt[0], nb_pos[1]+rt[1], nb_pos[2]+rt[2]
        true_world[idx] = (wx, wy, wz)

    return bones, true_world, bone_count


def generate_report(filepath, bones, true_world, bone_count):
    stem = os.path.splitext(os.path.basename(filepath))[0]

    if stem == 'skeleton':
        # Get grandparent folder name
        parent_dir = os.path.dirname(filepath)
        grandparent_dir = os.path.dirname(parent_dir)
        grandparent_name = os.path.basename(grandparent_dir)
        report_name = f"{grandparent_name}-skeleton_analysis"
    else:
        report_name = f"{stem}-skeleton_analysis"

    lines = []
    lines.append(report_name)
    lines.append('')
    lines.append(f"bone_count = {bone_count} (0x{bone_count:X})")
    lines.append('')

    # Table header
    lines.append('| Bone ID | Name | Parent ID | Flags | World Position (X, Y, Z) | Transloc (X, Y, Z) | Transrot (X, Y, Z) |')
    lines.append('|---------|------|-----------|-------|---------------------------|--------------------|--------------------|')

    for b in bones:
        idx = b['index']
        name = b['name']
        parent_idx = b['parent_idx']
        flags = b['bone_flags']
        wp = true_world[idx]
        tl = b['p88']
        tr = b['p100']

        safe_name = name.replace('|', '→')

        bone_id_str = f"{idx} (0x{idx:X})"
        parent_str = f"{parent_idx} (0x{parent_idx:X})" if parent_idx is not None else "None"

        wp_str = f"({wp[0]:.6f}, {wp[1]:.6f}, {wp[2]:.6f})"
        tl_str = f"({tl[0]:.6f}, {tl[1]:.6f}, {tl[2]:.6f})"
        tr_str = f"({tr[0]:.6f}, {tr[1]:.6f}, {tr[2]:.6f})"

        lines.append(f"| {bone_id_str} | `{safe_name}` | {parent_str} | 0x{flags:04X} | {wp_str} | {tl_str} | {tr_str} |")

    return '\n'.join(lines), report_name


def main():
    if len(sys.argv) < 2:
        print("Drag a .g skeleton file onto this script.")
        try:
            input("Press Enter to exit...")
        except (EOFError, KeyboardInterrupt):
            pass
        return

    filepath = sys.argv[1]

    if not filepath.lower().endswith('.g'):
        print("Input file must be a skeleton file from FE9 or FE10 (.g extension type)")
        try:
            input("Press Enter to exit...")
        except (EOFError, KeyboardInterrupt):
            pass
        return

    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        try:
            input("Press Enter to exit...")
        except (EOFError, KeyboardInterrupt):
            pass
        return

    print(f"Parsing: {filepath}")
    bones, true_world, bone_count = parse_skeleton(filepath)
    report, report_name = generate_report(filepath, bones, true_world, bone_count)

    output_path = os.path.join(os.path.dirname(filepath), f"{report_name}.md")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"Report written to: {output_path}")
    print(f"Total bones: {bone_count} (0x{bone_count:X})")
    try:
        input("Press Enter to exit...")
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == '__main__':
    main()
