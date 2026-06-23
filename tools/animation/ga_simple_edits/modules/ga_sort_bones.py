"""
Reorganize .ga animation files so bones are sorted by bone_id (ascending).
Reorders bones, channel data, and fcurve data in-place.
"""

import struct
import sys
import os
from pathlib import Path


BONE_TABLE_ENTRY_SIZE = 0x10  # bone table entry size
CHANNEL_ENTRY_SIZE = 0x0C  # channel data entry size
FCURVE_ENTRY_SIZE = 4     # fcurve data entry size


def process_ga(path):
    with open(path, 'rb') as f:
        data = bytearray(f.read())

    header_ptr = struct.unpack_from('>I', data, 0)[0]

    if len(data) < 0x30:
        raise ValueError("File too small (no header)")

    header = data[0:48]
    bone_count = struct.unpack_from('>I', data, 0x1C)[0]
    if bone_count == 0:
        return

    bone_table_ptr = struct.unpack_from('>I', data, 0x20)[0]
    channel_data_ptr = struct.unpack_from('>I', data, 0x24)[0]
    fcurve_data_ptr = struct.unpack_from('>I', data, 0x2C)[0]

    # --- Parse bone table ---
    bones = []
    for i in range(bone_count):
        off = bone_table_ptr + i * BONE_TABLE_ENTRY_SIZE
        row_data = struct.unpack_from('>IIII', data, off)
        bones.append(row_data)

    total_channels = max(b[2] + b[3] for b in bones) if bones else 0
    if total_channels == 0:
        return
    # Safety: cap to actual channel data entries present in file
    channel_entries_in_file = (
        fcurve_data_ptr - channel_data_ptr) // CHANNEL_ENTRY_SIZE
    if channel_entries_in_file > 0:
        if channel_entries_in_file < total_channels:
            total_channels = channel_entries_in_file

    # --- Parse channel data ---
    channels = []
    for channel_idx in range(total_channels):
        offset = channel_data_ptr + channel_idx * CHANNEL_ENTRY_SIZE
        fields = struct.unpack_from('>BBBBHHI', data, offset)
        channels.append(list(fields))

    # Determine actual fcurve data extent
    fcurve_end = header_ptr if header_ptr else len(data)
    fcurve_size = fcurve_end - fcurve_data_ptr
    if fcurve_size < 0:
        fcurve_size = 0
    raw_fcurve_data = data[fcurve_data_ptr:fcurve_data_ptr + fcurve_size]

    # --- Group by bone_id ---
    data_dict = {}
    bone_conflicts = []
    row_conflicts = []
    for bone in bones:
        bone_id = bone[0]
        channel_mask = bone[1]
        channel_start = bone[2]
        channel_count = bone[3]
        channel_list = []
        for channel_idx in range(channel_count):
            channel = channels[channel_start + channel_idx]
            fcurve_start = channel[6]
            num_keyframes = channel[5]
            fcurve_off = fcurve_start * FCURVE_ENTRY_SIZE
            fcurve_sz = num_keyframes * FCURVE_ENTRY_SIZE
            fcurve_slice = raw_fcurve_data[fcurve_off:fcurve_off
                                           + fcurve_sz
                                           ] if fcurve_off < len(
                                            raw_fcurve_data
                                            ) else b''
            channel_list.append([channel, fcurve_slice])

        if bone_id in data_dict and channel_mask == 8:
            bone_conflicts.append(bone_id)
            remove_mask, remove_ch_list = data_dict[bone_id]
            # channel, fcurve_slice = remove_ch_list
            row_conflicts.append([remove_mask, remove_ch_list])

        if bone_id in data_dict and channel_mask != 8:
            bone_conflicts.append(bone_id)
            row_conflicts.append([channel_mask, channel_list])
        elif bone_id != 255:
            data_dict[bone_id] = [channel_mask, channel_list]

    sorted_keys = sorted(data_dict.keys())

    # --- Rebuild bone table ---
    new_bone_count = len(sorted_keys)
    new_bones = bytearray(new_bone_count * BONE_TABLE_ENTRY_SIZE)
    channel_idx = 0
    for i, bone_id in enumerate(sorted_keys):
        channel_mask, channel_list = data_dict[bone_id]
        channel_count = len(channel_list)
        print(f"Bone ID {bone_id}: channel count {channel_count}")
        struct.pack_into('>IIII',
                         new_bones,
                         i * BONE_TABLE_ENTRY_SIZE,
                         bone_id,
                         channel_mask,
                         channel_idx,
                         channel_count
                         )
        channel_idx += channel_count

    # --- Rebuild channel data and fcurve data ---
    new_channel_data = bytearray(total_channels * CHANNEL_ENTRY_SIZE)
    new_fcurve_data = bytearray()
    fcurve_map = {}
    cur_fcurve_idx = 0
    channel_idx = 0

    for bone_id in sorted_keys:
        channel_mask, channel_list = data_dict[bone_id]
        for channel, fcurve_slice in channel_list:
            orig_fcurve_start = channel[6]
            if orig_fcurve_start not in fcurve_map:
                fcurve_map[orig_fcurve_start] = cur_fcurve_idx
                new_fcurve_data.extend(fcurve_slice)
                cur_fcurve_idx += channel[5]

            struct.pack_into('>BBBB',
                             new_channel_data,
                             channel_idx * CHANNEL_ENTRY_SIZE,
                             channel[0],
                             channel[1],
                             channel[2],
                             channel[3]
                             )
            struct.pack_into('>HH',
                             new_channel_data,
                             channel_idx * CHANNEL_ENTRY_SIZE + 4,
                             channel[4],
                             channel[5]
                             )
            struct.pack_into('>I',
                             new_channel_data,
                             channel_idx * CHANNEL_ENTRY_SIZE + 8,
                             fcurve_map[orig_fcurve_start]
                             )
            channel_idx += 1

    # --- Replace sections in-place ---
    new_bone_count = struct.pack('>I', new_bone_count)
    # bone_table_ptr = struct.pack('>I', 48)
    # channel_data_ptr = struct.pack('>I', 48 + len(new_bones))
    # fcurve_data_ptr = struct.pack('>I',
    #                               48 + len(new_bones) + len(new_channel_data)
    #                               )

    # new_data_dict = {'header_ptr': data[0:4],
    #                  'game_flag': data[4:8],
    #                  'unknown': data[8:16],
    #                  'loop_flag': data[16:20],
    #                  'start_frame': data[20:24],
    #                  'end_frame': data[24:28],
    #                  'bone_count': new_bone_count,
    #                  'bone_table_ptr': bone_table_ptr,
    #                  'channel_data_ptr': channel_data_ptr,
    #                  'unknown_ptr': data[40:44],
    #                  'fcurve_data_ptr': fcurve_data_ptr,
    #                  'bone_table': new_bones,
    #                  'channel_data': new_channel_data,
    #                  'fcurve_data': new_fcurve_data
    #                 }

    bone_table_size = channel_data_ptr - bone_table_ptr
    channel_data_size = fcurve_data_ptr - channel_data_ptr

    if len(new_bones) < bone_table_size:
        new_bones.extend(b'\x00' * (bone_table_size - len(new_bones)))
    elif len(new_bones) > bone_table_size:
        raise RuntimeError("Bone table data grew unexpectedly")

    if len(new_channel_data) < channel_data_size:
        new_channel_data.extend(
            b'\x00' * (channel_data_size - len(new_channel_data))
            )
    elif len(new_channel_data) > channel_data_size:
        raise RuntimeError("Channel data grew unexpectedly")

    if len(new_fcurve_data) < fcurve_size:
        new_fcurve_data.extend(b'\x00' * (fcurve_size - len(new_fcurve_data)))
    elif len(new_fcurve_data) > fcurve_size:
        raise RuntimeError("fcurve data grew unexpectedly")

    data[0x1C:0x20] = new_bone_count
    data[bone_table_ptr:bone_table_ptr + len(new_bones)] = new_bones
    data[channel_data_ptr:channel_data_ptr
         + len(new_channel_data)] = new_channel_data
    data[fcurve_data_ptr:fcurve_data_ptr
         + len(new_fcurve_data)
         ] = new_fcurve_data

    with open(path, 'wb') as f:
        f.write(data)

    bone_ids = [b[0] for b in bones]
    was_sorted = bone_ids == sorted(bone_ids)
    if was_sorted:
        print(f"  Already sorted: {path}")
    else:
        print(f"  Reorganized: {path}")

    if len(bone_conflicts) > 0:
        path = Path(path)
        bone_conflict_path = path.parent
        if bone_conflict_path.name == "pack":
            bone_conflict_path = bone_conflict_path.parent
        bone_conflict_path = bone_conflict_path.joinpath(
            "Sorted Animation Issues.md")

        num_conflicts = len(bone_conflicts)
        path_stem = path.stem
        text = f"Detected duplicate bone IDs: {bone_conflicts}"

        print(f"WARNING! {num_conflicts} duplicate bone IDs detected "
              f"and not resolved")
        print(text)

        if not bone_conflict_path.is_file():
            with open(bone_conflict_path, 'w') as f:
                f.write("# Conflicting transforms on the same bone\n")
                f.write("- Only one transform can be written per bone ID.\n")
                f.write("- Transforms with only scale transforms "
                        "(channel_mask=0x08) are prioritized.\n")
                f.write("- If no transforms involve only scale, "
                        "the first detected transform is preserved.\n\n")

        with open(bone_conflict_path, 'a') as f:
            f.write(f"## {path_stem}\n")
            f.write(f"{text}\n")
            f.write("Removed data (decimal values):\n")
            f.write("| Bone ID "
                    "| Channel Mask "
                    "| Channel Entry "
                    "| FCurve Dataset "
                    "|\n"
                    )
            f.write("|---------"
                    "|--------------"
                    "|-----------------"
                    "|-------------------"
                    "|\n")
            for index, bone in enumerate(bone_conflicts):
                # [channel_mask, channel_list]
                # channel_list = [channel, fcurve_slice]
                channel_list = row_conflicts[index][1]
                # channel_entries = []
                # fcurve_entries = []
                for entry in channel_list:
                    channel_entry = entry[0]
                    fcurve_entry = entry[1]
                    fcurve_entry = [val[0] for val in
                                    struct.iter_unpack('>H', fcurve_entry)
                                    ]

                    f.write(f"| {bone}"
                            f"| {row_conflicts[index][0]}"
                            f"| `{channel_entry}`"
                            f"| `{fcurve_entry}`"
                            "|\n"
                            )
            f.write("\n")


def find_ga_files(target):
    if os.path.isfile(target):
        return [target] if target.lower().endswith('.ga') else []
    files = []
    for root, dirs, files in os.walk(target):
        for file in files:
            if file.lower().endswith('.ga'):
                files.append(os.path.join(root, file))
    return files


def main():
    args = []
    args = sys.argv[1:]
    if len(args) > 0 and args[0] in ("-h", "--help"):
        print("Usage: python ga-sort-bones.py <animation.ga|folder>")
        print("Purpose: Reorganizes .ga animation files so "
              "bones and associated date are sorted by bone_id (ascending). "
              "Removes duplicate bone data and otherwise only "
              "reorders bone table, channel data, and fcurve data in-place.")
        print("About Input:")
        print("\tIf a .ga file is provided, it will be processed.")
        print("\tIf a folder is provided, all .ga files in the folder "
              "and subfolders will be processed.")
        print()
        return

    if len(sys.argv) < 2:
        print("Usage: python ga-sort-bones.py <animation.ga|folder>")
        print("Use -h or --help for more details.")
        print()
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
