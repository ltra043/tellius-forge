"""
Reorganize .ga animation files so bones are sorted by bone_id (ascending).
Preserves all data and only reorders bones, metadata, and frame data in-place.
"""

import struct
import sys
import os

BTE = 0x10  # bone table entry size
MTE = 0x0C  # metadata entry size
FDE = 4     # frame data entry size


def process_ga(path):
    with open(path, 'rb') as f:
        data = bytearray(f.read())

    footer_ptr = struct.unpack_from('>I', data, 0)[0]

    if len(data) < 0x30:
        raise ValueError("File too small (no header)")

    bone_count = struct.unpack_from('>I', data, 0x1C)[0]
    if bone_count == 0:
        return

    bone_table_ptr = struct.unpack_from('>I', data, 0x20)[0]
    meta_table_ptr = struct.unpack_from('>I', data, 0x24)[0]
    frame_data_ptr = struct.unpack_from('>I', data, 0x2C)[0]

    # --- Parse bone table ---
    bones = []
    for i in range(bone_count):
        off = bone_table_ptr + i * BTE
        bid, cmask, ms, mc = struct.unpack_from('>IIII', data, off)
        bones.append([bid, cmask, ms, mc])

    total_meta = max(b[2] + b[3] for b in bones) if bones else 0
    if total_meta == 0:
        return
    # Safety: cap to actual metadata entries present in file
    meta_entries_in_file = (frame_data_ptr - meta_table_ptr) // MTE
    if meta_entries_in_file > 0 and meta_entries_in_file < total_meta:
        total_meta = meta_entries_in_file

    # --- Parse metadata table ---
    metas = []
    for i in range(total_meta):
        off = meta_table_ptr + i * MTE
        fields = struct.unpack_from('>BBBBHHI', data, off)
        metas.append(list(fields))

    # Determine actual frame data extent
    fd_end = footer_ptr if footer_ptr else len(data)
    fd_size = fd_end - frame_data_ptr
    if fd_size < 0:
        fd_size = 0
    raw_fd = data[frame_data_ptr:frame_data_ptr + fd_size]

    # --- Group by bone_id ---
    data_dict = {}
    for b in bones:
        bid = b[0]
        meta_start = b[2]
        meta_count = b[3]
        meta_list = []
        for mi in range(meta_count):
            m = metas[meta_start + mi]
            fds = m[6]
            nkf = m[5]
            fd_off = fds * FDE
            fd_sz = nkf * FDE
            fd_slice = raw_fd[fd_off:fd_off + fd_sz] if fd_off < len(raw_fd) else b''
            meta_list.append([m, fd_slice])
        data_dict[bid] = [b[1], meta_list]

    sorted_keys = sorted(data_dict.keys())

    # --- Rebuild bone table ---
    new_bones = bytearray(bone_count * BTE)
    meta_idx = 0
    for i, bid in enumerate(sorted_keys):
        cmask, mlist = data_dict[bid]
        cnt = len(mlist)
        struct.pack_into('>IIII', new_bones, i * BTE, bid, cmask, meta_idx, cnt)
        meta_idx += cnt

    # --- Rebuild metadata and frame data ---
    new_meta = bytearray(total_meta * MTE)
    new_fd = bytearray()
    fd_map = {}
    cur_fd_idx = 0
    mi = 0

    for bid in sorted_keys:
        cmask, mlist = data_dict[bid]
        for m, fd_slice in mlist:
            orig_fds = m[6]
            if orig_fds not in fd_map:
                fd_map[orig_fds] = cur_fd_idx
                new_fd.extend(fd_slice)
                cur_fd_idx += m[5]

            struct.pack_into('>BBBB', new_meta, mi * MTE, m[0], m[1], m[2], m[3])
            struct.pack_into('>HH', new_meta, mi * MTE + 4, m[4], m[5])
            struct.pack_into('>I', new_meta, mi * MTE + 8, fd_map[orig_fds])
            mi += 1

    # --- Replace sections in-place ---
    data[bone_table_ptr:bone_table_ptr + len(new_bones)] = new_bones
    data[meta_table_ptr:meta_table_ptr + len(new_meta)] = new_meta

    if len(new_fd) < fd_size:
        new_fd.extend(b'\x00' * (fd_size - len(new_fd)))
    elif len(new_fd) > fd_size:
        raise RuntimeError("Frame data grew unexpectedly")
    data[frame_data_ptr:frame_data_ptr + len(new_fd)] = new_fd

    with open(path, 'wb') as f:
        f.write(data)

    bone_ids = [b[0] for b in bones]
    was_sorted = bone_ids == sorted(bone_ids)
    if was_sorted:
        print(f"  Already sorted: {path}")
    else:
        print(f"  Reorganized: {path}")


def find_ga_files(target):
    if os.path.isfile(target):
        return [target] if target.lower().endswith('.ga') else []
    files = []
    for root, dirs, fnames in os.walk(target):
        for fn in fnames:
            if fn.lower().endswith('.ga'):
                files.append(os.path.join(root, fn))
    return files


def main():
    if len(sys.argv) < 2:
        print("Usage: Drag & drop .ga file(s) or folder(s) onto this script.")
        print("       All .ga files (including subfolders) will be processed.")
        print()
        input("Press Enter to exit...")
        return

    targets = []
    for arg in sys.argv[1:]:
        targets.extend(find_ga_files(arg))

    if not targets:
        print("No .ga files found.")
        input("Press Enter to exit...")
        return

    ok = 0
    fail = 0
    for fp in targets:
        try:
            process_ga(fp)
            ok += 1
        except Exception as e:
            print(f"  FAIL: {fp}")
            print(f"        {e}")
            fail += 1

    print(f"\nDone. {ok} OK, {fail} failed.")
    input("Press Enter to exit...")


if __name__ == '__main__':
    main()
