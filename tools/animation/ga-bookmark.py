import struct
import json
import sys
import os

def make_color(r, g, b, a=0xB3):
    return (a << 24) | (b << 16) | (g << 8) | r

# ---- Color List ---- 
# Major sections - pure greys (R=G=B)
grey_light = make_color(156, 156, 156)  # 0xB39C9C9C
grey_dark = make_color(83, 83, 83)      # 0xB3535353

# Rainbow
red = make_color(255, 0, 0)             # red
orange = make_color(255, 131, 0)        # orange
yellow = make_color(199, 204, 41)       # yellow
green = make_color(59, 204, 41)         # green
# blue = make_color(41, 134, 204)         # blue
blue = make_color(41, 78, 204)          # blue
blue_light = make_color(41, 162, 204)   # light blue
# purple = make_color(143, 41, 204)       # purple
purple = make_color(160, 0, 255)    # 0xB3FF00A0  purple
pink = make_color(255, 82, 201)         # pink

# ---- Assign Colors ----
# Major sections - pure greys (R=G=B)
C_HEADER   = grey_dark
C_BONETBL  = grey_light
C_CHANNEL  = grey_dark
C_FCURVE   = grey_light
C_FOOTER1  = grey_light
# C_HEADER   = make_color(78, 78, 78)      # 0xB34E4E4E
# C_BONETBL  = make_color(156, 156, 156)   # 0xB39C9C9C
# C_CHANNEL  = make_color(83, 83, 83)      # 0xB3535353
# C_FCURVE   = make_color(170, 170, 170)   # 0xB3AAAAAA
# C_FOOTER1  = make_color(152, 152, 152)   # 0xB3989898

# Detail sub-bookmark colors (shared FE9/FE10)
C_HDR_PTR   = yellow
C_GAME_ID   = pink
C_START_FR  = green
C_END_FR    = red
C_BONE_CNT  = blue_light
C_BTBL_PTR  = blue
C_CHNL_PTR  = orange
C_FCURVE_PTR = purple
C_FTR_PTR1  = blue

# FE9 Footer Data 1 rainbow (7-color)
FD1_RAINBOW = [red, orange, yellow, green, blue, purple, pink]

# ---- FE10-specific colors (from "fe10 ftr1&2.hexbm") ----
C_FD1_SECTION = grey_dark
C_FD2_SECTION = grey_light
C_PADDING_FE10 = grey_dark

# FE10 Footer Pointer colors
C_FTR_ID_1  = red
C_FTR_PTR_1 = orange
C_FTR_ID_2  = blue_light
C_FTR_PTR_2 = purple
C_FTR_PTR_3 = pink

# FE10 FD1 4-colour entry cycle (yellow, pink, red, orange)
FD1_FE10_CYCLE = [yellow, pink, red, orange]

# FE10 FD1 non-entry colors (exact from reference)
C_FD1_FE10_ENTRIES   = red
C_FD1_FE10_INDEXES   = orange

# FE10 FD2 4-colour entry cycle (medium blue, purple, green, light blue)
# Entries start from cycle[2]; write-up cycles [green, light blue, medium blue, purple]
FD2_FE10_CYCLE = [green, blue_light, blue, purple]

# FE10 FD2 non-entry colors (exact from reference)
C_FD2_FE10_ENTRIES   = green
C_FD2_FE10_INDEXES   = blue_light


def read_u32be(data, offset):
    return struct.unpack(">I", data[offset:offset+4])[0]


def read_u16be(data, offset):
    return struct.unpack(">H", data[offset:offset+2])[0]


_id = 0
def next_id():
    global _id
    _id += 1
    return _id


def bm(name, address, size, color, comment=""):
    return {
        "color": color,
        "comment": comment,
        "highlightVisible": True,
        "id": next_id(),
        "locked": False,
        "name": name,
        "region": {"address": address, "size": size}
    }


def fmt_range(start, size):
    if size == 1:
        return f"0x{start:04X}"
    return f"0x{start:04X} - 0x{start + size - 1:04X}"


def parse_fd1_entries(data, fd1_start, fd1_size, filesize, bookmarks, is_fe10):
    if fd1_size < 2:
        return

    fd1_entry_count = data[fd1_start + 1]

    if is_fe10:
        cycle = FD1_FE10_CYCLE
        n_cycle = len(cycle)
        col_entries = C_FD1_FE10_ENTRIES
        col_indexes = C_FD1_FE10_INDEXES
        entry_cycle_start = 0
    else:
        cycle = FD1_RAINBOW
        n_cycle = len(cycle)
        # FE9: #Entries = cycle[0], StartIndexes = cycle[1], entries start from cycle[2]
        col_entries = cycle[0]
        col_indexes = cycle[1]
        entry_cycle_start = 2

    # # Entries
    bookmarks.append(bm(
        f"FD1: # Entries [{fmt_range(fd1_start + 1, 1)}]",
        fd1_start + 1, 1,
        col_entries,
        f"0x{fd1_entry_count:X} entries"
    ))

    # Entry Start Indexes
    idx_list_size = fd1_entry_count * 2
    idx_list_off = fd1_start + 8
    if idx_list_off + idx_list_size <= filesize:
        indices = []
        for i in range(fd1_entry_count):
            idx = read_u16be(data, idx_list_off + i * 2)
            indices.append(f"0x{idx:02x}")

        bookmarks.append(bm(
            f"FD1: Entry Start Indexes [{fmt_range(idx_list_off, idx_list_size)}]",
            idx_list_off, idx_list_size,
            col_indexes,
            "Entries start at:\n" + ", ".join(indices)
        ))

        # Individual entries (size determined by index gaps)
        idx_vals = [int(x, 16) for x in indices]
        for i in range(fd1_entry_count):
            if i >= len(idx_vals):
                break
            entry_off = fd1_start + idx_vals[i]
            if i + 1 < len(idx_vals):
                entry_size = idx_vals[i + 1] - idx_vals[i]
            else:
                entry_size = fd1_size - idx_vals[i]
            if entry_off + entry_size > filesize:
                entry_size = filesize - entry_off
            if entry_size <= 0:
                break

            bookmarks.append(bm(
                f"FD1: Entry {i + 1} [{fmt_range(entry_off, entry_size)}]",
                entry_off, entry_size,
                cycle[(entry_cycle_start + i) % n_cycle]
            ))


def parse_fd2_entries(data, fd2_start, fd2_size, filesize, bookmarks):
    if fd2_size < 2:
        return

    fd2_entry_count = data[fd2_start + 1]
    cycle = FD2_FE10_CYCLE
    n_cycle = len(cycle)

    # # Entries
    bookmarks.append(bm(
        f"FD2: # Entries [{fmt_range(fd2_start + 1, 1)}]",
        fd2_start + 1, 1,
        C_FD2_FE10_ENTRIES,
        f"0x{fd2_entry_count:X} entries"
    ))

    # Entry Start Indexes
    idx_list_size = fd2_entry_count * 2
    idx_list_off = fd2_start + 8
    if idx_list_off + idx_list_size <= filesize:
        indices = []
        for i in range(fd2_entry_count):
            idx = read_u16be(data, idx_list_off + i * 2)
            indices.append(f"0x{idx:02x}")

        bookmarks.append(bm(
            f"FD2: Entry Start Indexes [{fmt_range(idx_list_off, idx_list_size)}]",
            idx_list_off, idx_list_size,
            C_FD2_FE10_INDEXES,
            "Entries start at:\n" + ", ".join(indices)
        ))

        # Individual entries
        for i in range(fd2_entry_count):
            if i >= len(indices):
                break
            entry_off = fd2_start + int(indices[i], 16)
            if entry_off >= filesize:
                break

            # FD2 entry structure:
            # [num_frames(2)] [bone_id(2)] [frame(2) visible(2)]*N + padding to 4
            num_frames = read_u16be(data, entry_off)
            bone_id = read_u16be(data, entry_off + 2)
            entry_data_size = 4 + num_frames * 4
            padded = ((entry_data_size + 3) // 4) * 4

            if entry_off + padded > filesize:
                padded = filesize - entry_off

            # Build comment
            comment_lines = []
            comment_lines.append(f"[+0x1] | # frames = 0x{num_frames:02X}")
            comment_lines.append(f"[+0x3] | bone_id = 0x{bone_id:02X}")
            for k in range(num_frames):
                frm = read_u16be(data, entry_off + 4 + k * 4)
                vis = read_u16be(data, entry_off + 6 + k * 4)
                comment_lines.append(f"\n[+0x{4 + k*4:02X}] | frame{k} = 0x{frm:x}")
                comment_lines.append(f"[+0x{6 + k*4:02X}] | scale{k} = 0x{vis:x}")

            bookmarks.append(bm(
                f"FD2: Entry {i + 1} [{fmt_range(entry_off, padded)}]",
                entry_off, padded,
                cycle[(2 + i) % n_cycle],
                "\n".join(comment_lines)
            ))


def handle_fe9_footer(data, filesize, hdr_ptr, bookmarks):
    footer_ptr1 = read_u32be(data, hdr_ptr)

    # Footer Pointer 1
    bookmarks.append(bm(
        f"Footer Pointer 1 [{fmt_range(hdr_ptr, 4)}]",
        hdr_ptr, 4, C_FTR_PTR1
    ))

    # Padding (0x24 bytes)
    if hdr_ptr + 4 + 0x24 <= filesize:
        bookmarks.append(bm(
            f"Padding [{fmt_range(hdr_ptr + 4, 0x24)}]",
            hdr_ptr + 4, 0x24, C_HEADER,
            "0x24 bytes padding\n"
            "Always present in FE9 if Footer Data is present\n"
            "Appears between Footer Pointer 1 and Footer Data 1"
        ))

    # FD1
    fd1_start = footer_ptr1
    fd1_size = filesize - fd1_start
    if fd1_size > 0:
        bookmarks.append(bm(
            f"Footer Data 1 (FD1) [{fmt_range(fd1_start, fd1_size)}]",
            fd1_start, fd1_size, C_FOOTER1,
            f"Effect and Timing Data.\nTotal 0x{fd1_size:X} bytes"
        ))
        parse_fd1_entries(data, fd1_start, fd1_size, filesize, bookmarks, is_fe10=False)


def handle_fe10_footer(data, filesize, hdr_ptr, bookmarks):
    # In FE10, hdr_ptr points to 0x0c bytes before EOF
    last_4 = read_u32be(data, filesize - 4)

    if last_4 == 0:
        # One section only: 0x0c-byte footer pointer block at hdr_ptr
        ftr_id = read_u32be(data, hdr_ptr)
        ftr_ptr = read_u32be(data, hdr_ptr + 4)

        is_fd1 = (ftr_id == 0x05)
        section_name = "FD1" if is_fd1 else "FD2"
        id_color = C_FTR_ID_1 if is_fd1 else C_FTR_ID_2
        ptr_color = C_FTR_PTR_1 if is_fd1 else C_FTR_PTR_2

        # ftr_ID
        bookmarks.append(bm(
            f"ftr_ID [{fmt_range(hdr_ptr, 4)}]",
            hdr_ptr, 4, id_color,
            f"value = 0x{ftr_id:02X}"
        ))

        # ftr_ptr
        bookmarks.append(bm(
            f"ftr_ptr [{fmt_range(hdr_ptr + 4, 4)}]",
            hdr_ptr + 4, 4, ptr_color,
            f"Points to {section_name}"
        ))

        # 0x00 padding
        bookmarks.append(bm(
            f"Padding [{fmt_range(hdr_ptr + 8, 4)}]",
            hdr_ptr + 8, 4, C_PADDING_FE10
        ))

        # FD section
        fd_start = ftr_ptr
        fd_size = hdr_ptr - fd_start
        if fd_size > 0:
            section_color = C_FD1_SECTION if is_fd1 else C_FD2_SECTION
            bookmarks.append(bm(
                f"Footer Data 1 (FD1) [{fmt_range(fd_start, fd_size)}]"
                if is_fd1 else
                f"Footer Data 2 (FD2) [{fmt_range(fd_start, fd_size)}]",
                fd_start, fd_size, section_color,
                f"Total 0x{fd_size:X} bytes"
            ))

            if is_fd1:
                parse_fd1_entries(data, fd_start, fd_size, filesize, bookmarks, is_fe10=True)
            else:
                parse_fd2_entries(data, fd_start, fd_size, filesize, bookmarks)

    else:
        # Both sections: 0x18-byte footer pointer block
        # Layout: [ftr_ID_1][ftr_ptr_1][0x00][ftr_ID_2][ftr_ptr_2][ftr_ptr_3]
        # hdr_ptr points to ftr_ID_2 (the middle of the block)
        ftr_id_1_off = hdr_ptr - 0x0c

        ftr_id_1 = read_u32be(data, ftr_id_1_off)
        ftr_ptr_1 = read_u32be(data, ftr_id_1_off + 4)
        ftr_id_2 = read_u32be(data, hdr_ptr)
        ftr_ptr_2 = read_u32be(data, hdr_ptr + 4)
        ftr_ptr_3 = read_u32be(data, hdr_ptr + 8)

        # FD1
        fd1_start = ftr_ptr_1
        fd1_size = ftr_ptr_2 - fd1_start
        if fd1_size > 0:
            bookmarks.append(bm(
                f"Footer Data 1 (FD1) [{fmt_range(fd1_start, fd1_size)}]",
                fd1_start, fd1_size, C_FD1_SECTION,
                f"Effect and Timing Data.\nTotal 0x{fd1_size:X} bytes"
            ))
            parse_fd1_entries(data, fd1_start, fd1_size, filesize, bookmarks, is_fe10=True)

        # FD2
        fd2_start = ftr_ptr_2
        fd2_end = ftr_id_1_off
        fd2_size = fd2_end - fd2_start
        if fd2_size > 0:
            bookmarks.append(bm(
                f"Footer Data 2 (FD2) [{fmt_range(fd2_start, fd2_size)}]",
                fd2_start, fd2_size, C_FD2_SECTION,
                f"Hides bones for part/all of animation.\nTotal 0x{fd2_size:X} bytes"
            ))
            parse_fd2_entries(data, fd2_start, fd2_size, filesize, bookmarks)

        # Padding between FD2 end and ftr_ID_1
        if fd2_size > 0:
            pad_start = fd2_start + fd2_size
            pad_end = ftr_id_1_off
            pad_size = pad_end - pad_start
            if pad_size > 0:
                bookmarks.append(bm(
                    f"Padding [{fmt_range(pad_start, pad_size)}]",
                    pad_start, pad_size, C_PADDING_FE10,
                    "Pad Footer Data (1 or 2) until 4-byte aligned"
                ))

        # Footer pointer block bookmarks
        bookmarks.append(bm(
            f"ftr_ID_1 [{fmt_range(ftr_id_1_off, 4)}]",
            ftr_id_1_off, 4, C_FTR_ID_1,
            f"value = 0x{ftr_id_1:02X}; pointer_type = 1\n\n"
            "ID Types:\n1: value = 0x5\n2: value = 0x0"
        ))
        bookmarks.append(bm(
            f"ftr_ptr_1 [{fmt_range(ftr_id_1_off + 4, 4)}]",
            ftr_id_1_off + 4, 4, C_FTR_PTR_1,
            "4 bytes after ftr_ID_1\nPoints to Footer Data 1 (FD1)"
        ))

        # 0x00 padding between ptr_1 and ftr_ID_2
        pad2_start = ftr_id_1_off + 8
        pad2_size = 4
        bookmarks.append(bm(
            f"Padding [{fmt_range(pad2_start, pad2_size)}]",
            pad2_start, pad2_size, C_PADDING_FE10
        ))

        bookmarks.append(bm(
            f"ftr_ID_2 [{fmt_range(hdr_ptr, 4)}]",
            hdr_ptr, 4, C_FTR_ID_2,
            f"value = 0x{ftr_id_2:02X}; pointer_type = 2\n\n"
            "ID Types:\n1: value = 0x5\n2: value = 0x0"
        ))
        bookmarks.append(bm(
            f"ftr_ptr_2 [{fmt_range(hdr_ptr + 4, 4)}]",
            hdr_ptr + 4, 4, C_FTR_PTR_2,
            "4 bytes after ftr_ID_2\nPoints to Footer Data 2 (FD2)"
        ))
        bookmarks.append(bm(
            f"ftr_ptr_3 [{fmt_range(hdr_ptr + 8, 4)}]",
            hdr_ptr + 8, 4, C_FTR_PTR_3,
            "Last 4 bytes of file IF first 4 bytes (header pointer) is nonzero.\n\n"
            "If ftr_ptr_3 is nonzero, it points to ftr_ID_1 and\n"
            "both Footer Data 1 and 2 are present in the file.\n\n"
            "If ftr_ptr_3 is zero, there is only one Footer Data # section."
        ))


def process_ga(filepath, out_path):
    with open(filepath, "rb") as f:
        data = f.read()

    filesize = len(data)

    # ---- Parse header (big endian) ----
    hdr_ptr     = read_u32be(data, 0x00)
    start_frame = read_u32be(data, 0x14)
    end_frame   = read_u32be(data, 0x18)
    bone_count  = read_u32be(data, 0x1C)
    bone_tbl    = read_u32be(data, 0x20)
    chnl_ptr    = read_u32be(data, 0x24)
    fcurve_ptr   = read_u32be(data, 0x2C)

    game_flag = data[0x08]
    is_fe10 = (game_flag == 1)

    bookmarks = []

    # ---- Header ----
    bookmarks.append(bm(f"File Info [0x00 - 0x2F]", 0x00, 0x30,
                        C_HEADER, "Header section"))

    hdr_comment = "Pointer to footer pointer(s) (0 = no footer)"
    if is_fe10:
        hdr_comment += "\n\nIn FE10 animations, points to 0x0c bytes before EOF"
    bookmarks.append(bm(f"hdr_ptr [{fmt_range(0x00, 4)}]", 0x00, 4,
                        C_HDR_PTR, hdr_comment))
    bookmarks.append(bm(f"Game ID [{fmt_range(0x08, 1)}]", 0x08, 1,
                        C_GAME_ID, "0x00 for FE9, 0x01 for FE10"))
    bookmarks.append(bm(f"Start Frame [{fmt_range(0x14, 4)}]", 0x14, 4,
                        C_START_FR))
    bookmarks.append(bm(f"End Frame [{fmt_range(0x18, 4)}]", 0x18, 4,
                        C_END_FR))
    bookmarks.append(bm(f"# Bones [{fmt_range(0x1C, 4)}]", 0x1C, 4,
                        C_BONE_CNT, f"Bone table has 0x{bone_count:X} rows"))
    bookmarks.append(bm(f"Bone Table Ptr [{fmt_range(0x20, 4)}]", 0x20, 4,
                        C_BTBL_PTR))
    bookmarks.append(bm(f"Channel Data Ptr [{fmt_range(0x24, 4)}]", 0x24, 4,
                        C_CHNL_PTR))
    bookmarks.append(bm(f"F-Curve Data Ptr [{fmt_range(0x2C, 4)}]", 0x2C, 4,
                        C_FCURVE_PTR))

    # ---- Bone Table ----
    bt_size = bone_count * 0x10
    bookmarks.append(bm(
        f"Bone Table [{fmt_range(bone_tbl, bt_size)}]",
        bone_tbl, bt_size, C_BONETBL,
        f"{bone_count} entries, {bt_size} bytes\n"
        f"0x{bone_count:X} entries, 0x{bt_size:X} bytes"
    ))

    # ---- Bone Table column bookmarks (second row, index 1) ----
    if bone_count > 1:
        bt_row = bone_tbl + 0x10
        bookmarks.append(bm(
            f"Bone Table: Bone ID [{fmt_range(bt_row, 4)}]",
            bt_row, 4, blue_light,
            "Column 1, Row 2 (Count starts at 1)\n"
            "- Identifies a bone from the associated skeleton to transform\n"
            "- Bone ID matches the index of the bone record data (starts at 0)\n"
            "- Bone ID matches index of bone name in string pool (ignoring the first \"[unknown]\")"
        ))
        bookmarks.append(bm(
            f"Bone Table: Transform Type [{fmt_range(bt_row + 4, 4)}]",
            bt_row + 4, 4, blue,
            "Column 2, Row 2 (Count starts at 1)\n"
            "Key:\n0x08 - Scale\n0x10 - Rotation\n0x20 - Location\n\n"
            "Value that informs what kind of transform(s) a bone undergoes\n"
            "If more than one type, add the values together."
        ))
        bookmarks.append(bm(
            f"Bone Table: Channel Start Index [{fmt_range(bt_row + 8, 4)}]",
            bt_row + 8, 4, blue_light,
            "Column 3, Row 2 (Count starts at 1)\n"
            "- Start entry index of associated data in Channel Data.\n"
            "- If value = 0x06, the associated channel data starts at entry 0x6. \n"
            "- Each channel entry is 0x0c bytes long."
        ))
        bookmarks.append(bm(
            f"Bone Table: # Channels [{fmt_range(bt_row + 0x0C, 4)}]",
            bt_row + 0x0C, 4, blue,
            "Column 4, Row 2 (Count starts at 1)\n"
            "- # Channel entries in Channel Data.\n"
            "- If value = 0x03, the associated channel data has 0x03 entries. \n"
            "- Each channel entry is 0x0c bytes long."
        ))

    # ---- Channel Data ----
    chnl_size = fcurve_ptr - chnl_ptr
    chnl_count = chnl_size // 0x0C
    bookmarks.append(bm(
        f"Channel Data [{fmt_range(chnl_ptr, chnl_size)}]",
        chnl_ptr, chnl_size, C_CHANNEL,
        f"{chnl_count} entries, {chnl_size} bytes\n"
        f"0x{chnl_count:X} entries, 0x{chnl_size:X} bytes"
    ))

    # ---- Channel Data detail bookmarks (entry 0x01 = index 1) ----
    if chnl_count > 1:
        chnl_e1 = chnl_ptr + 0x0C
        bookmarks.append(bm(
            f"Chnl Data: Entry 0x01 [{fmt_range(chnl_e1, 0x0C)}]",
            chnl_e1, 0x0C, orange,
            "Indexes start at value = 0x00\n"
            "This is entry 0x01, or the second entry.\n"
            "Each Channel Data entry is 0x0c bytes long.\n"
            "See bookmarks for next entry (Entry 0x02) for more detailed breakdown"
        ))
    if chnl_count > 2:
        chnl_e2 = chnl_ptr + 0x18
        bookmarks.append(bm(
            f"Chnl Data: Channel Type [{fmt_range(chnl_e2 + 1, 1)}]",
            chnl_e2 + 1, 1, yellow,
            "uint8\n3 transforms x 3 axes = 9 channel types\n\n"
            "0x0: Scale X\n0x1: Scale Y\n0x2: Scale Z\n"
            "0x3: Rotation X\n0x4: Rotation Y\n0x5: Rotation Z\n"
            "0x6: Location X\n0x7: Location Y\n0x8: Location Z\n\n"
            "Channel entries for the same bone are organized by ascending Channel Type"
        ))
        bookmarks.append(bm(
            f"Chnl Data: Conversion Factor [{fmt_range(chnl_e2 + 2, 1)}]",
            chnl_e2 + 2, 1, pink,
            "Used to convert f-curve y-values to meaningful game units (like degrees for rotation)\n"
            "Unknown how to determine what value should be used. Preserve from existing animations when editing."
        ))
        bookmarks.append(bm(
            f"Chnl Data: End Frame [{fmt_range(chnl_e2 + 5, 1)}]",
            chnl_e2 + 5, 1, yellow,
            "Value of the last keyframe of the f-curve\n\n"
            "Often matches the first or last frame of the overall animation"
        ))
        bookmarks.append(bm(
            f"Chnl Data: # Keyframes [{fmt_range(chnl_e2 + 7, 1)}]",
            chnl_e2 + 7, 1, pink,
            "# keyframes in the associated f-curve"
        ))
        bookmarks.append(bm(
            f"Chnl Data: F-Curve Start Index [{fmt_range(chnl_e2 + 8, 4)}]",
            chnl_e2 + 8, 4, yellow,
            "Tells what entry index in F-Curve Data this channel's f-curve starts at.\n"
            "Each keyframe in F-Curve Data has a 4-byte entry."
        ))

    # ---- F-Curve Data (always computed from last channel data entry) ----
    last_chnl_off = chnl_ptr + (chnl_count - 1) * 0x0C
    last_fd_start = read_u32be(data, last_chnl_off + 0x08)
    last_kf_count = read_u16be(data, last_chnl_off + 0x06)
    total_kf = last_fd_start + last_kf_count
    fd_size = total_kf * 4
    bookmarks.append(bm(
        f"F-Curve Data [{fmt_range(fcurve_ptr, fd_size)}]",
        fcurve_ptr, fd_size, C_FCURVE,
        f"0x{total_kf:X} entries (keyframes), 0x{chnl_count:X} F-curves, 0x{fd_size:X} bytes\n"
        "Each entry is 4 bytes. 2 byte keyframe, 2 byte transform value.\n"
        "An F-curve grouping is made of variable # of entries, according to Channel Data."
    ))

    # ---- F-Curve Data detail bookmark (F-Curve 0x01 = second F-Curve) ----
    if chnl_count > 1:
        chnl_e1 = chnl_ptr + 0x0C
        fc_start_idx = read_u32be(data, chnl_e1 + 0x08)
        fc_kf_count = read_u16be(data, chnl_e1 + 0x06)
        fc_entry_start = fcurve_ptr + fc_start_idx * 4
        fc_entry_size = fc_kf_count * 4
        if fc_entry_start + fc_entry_size <= filesize and fc_entry_size > 0:
            first_kf_val = read_u16be(data, fc_entry_start)
            last_kf_val = read_u16be(data, fc_entry_start + (fc_kf_count - 1) * 4)
            bookmarks.append(bm(
                f"FC Data: F-Curve 0x01 [{fmt_range(fc_entry_start, fc_entry_size)}]",
                fc_entry_start, fc_entry_size, purple,
                f"This is the set of (frame, value) pairings for the f-curve "
                f"associated with Channel Entry 0x01\n"
                f"Start Index: 0x{fc_start_idx:X}\n"
                f"# Keyframes: 0x{fc_kf_count:X}\n"
                f"First Keyframe Value: 0x{first_kf_val:X}\n"
                f"Last Keyframe Value: 0x{last_kf_val:X}"
            ))

    # ---- Footer ----
    if hdr_ptr != 0:
        if is_fe10:
            handle_fe10_footer(data, filesize, hdr_ptr, bookmarks)
        else:
            handle_fe9_footer(data, filesize, hdr_ptr, bookmarks)

    # ---- Output ----
    output = {"bookmarks": bookmarks}
    with open(out_path, "w") as f:
        json.dump(output, f, indent=4)

    print(f"Wrote {len(bookmarks)} bookmarks to {out_path}")
    print(f"  Header:     0x00 - 0x2F")
    print(f"  Bone Table: {fmt_range(bone_tbl, bt_size)}  ({bone_count} entries)")
    print(f"  Channel:    {fmt_range(chnl_ptr, chnl_size)}  ({chnl_count} entries)")
    print(f"  F-Curve:    {fmt_range(fcurve_ptr, fd_size)}  ({total_kf} keyframes)")
    if hdr_ptr != 0:
        print(f"  Game:       {'FE10' if is_fe10 else 'FE9'}")


def main():
    args = sys.argv[1:]

    if len(args) == 0 or args[0] == "-o":
        print("Usage: py ga_bookmark.py <animation.ga|folder> [-o output.hexbm|output_folder]")
        sys.exit(1)

    input_path = args[0]
    output_arg = None
    if len(args) >= 3 and args[1] == "-o":
        output_arg = args[2]

    if os.path.isfile(input_path):
        if output_arg is None:
            output_arg = os.path.splitext(input_path)[0] + ".hexbm"
        process_ga(input_path, output_arg)

    elif os.path.isdir(input_path):
        if output_arg is None:
            folder_name = os.path.basename(os.path.normpath(input_path))
            output_arg = os.path.join(input_path, f"{folder_name} bookmarks")

        ga_files = []
        for root, dirs, files in os.walk(input_path):
            for f in files:
                if f.lower().endswith('.ga'):
                    ga_files.append(os.path.join(root, f))

        if not ga_files:
            print(f"No .ga files found in {input_path}")
            sys.exit(1)

        os.makedirs(output_arg, exist_ok=True)

        for ga_path in ga_files:
            rel_path = os.path.relpath(ga_path, input_path)
            out_name = os.path.splitext(rel_path)[0] + ".hexbm"
            out_path = os.path.join(output_arg, out_name)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            process_ga(ga_path, out_path)

    else:
        print(f"Error: path not found: {input_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
