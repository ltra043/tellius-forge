import sys
import struct
from pathlib import Path


def unpack_pak(pak_path: Path):
    if not pak_path.exists():
        print(f"Error: File '{pak_path}' does not exist")
        return False

    with open(pak_path, 'rb') as f:
        data = f.read()

    if len(data) < 10 or data[:4] != b'pack':
        print(f"Error: '{pak_path}' is not a valid PAK file (missing 'pack' header text)")
        return False

    num_files = struct.unpack('>H', data[4:6])[0]
    print(f"PAK file: {pak_path.name}")
    print(f"Number of files: {num_files}")

    toc_start = 0x08
    toc_entry_size = 16

    toc = []
    for i in range(num_files):
        offset = toc_start + i * toc_entry_size
        col0, col1, col2, col3 = struct.unpack('>IIII', data[offset:offset + 16])
        toc.append({
            'col0': col0,
            'name_ptr': col1,
            'data_ptr': col2,
            'size': col3
        })

    first_file_ptr = min(entry['data_ptr'] for entry in toc)
    pak_info = data[:first_file_ptr]

    output_dir = pak_path.parent.joinpath(f"{pak_path.stem}_unpacked")
    output_dir.mkdir(exist_ok=True)

    pak_info_path = output_dir.joinpath("PAK_Info.bin")
    with open(pak_info_path, 'wb') as f:
        f.write(pak_info)
    print(f"Created: {pak_info_path.name}")

    index_lines = []

    string_pool_start = toc_start + num_files * toc_entry_size

    for i, entry in enumerate(toc):
        name_offset = entry['name_ptr']
        if name_offset >= len(data):
            print(f"Warning: name pointer out of bounds for entry, skipping")
            continue

        name_end = data.find(b'\x00', name_offset)
        if name_end == -1:
            name_end = len(data)
        filename = data[name_offset:name_end].decode('ascii', errors='replace')

        index_lines.append(f"{filename}\t{i}\n")

        data_start = entry['data_ptr']
        data_size = entry['size']

        if data_start + data_size > len(data):
            print(f"Warning: file '{filename}' extends beyond data, truncating")
            data_size = len(data) - data_start

        file_data = data[data_start:data_start + data_size]

        file_path = output_dir.joinpath(filename)
        with open(file_path, 'wb') as f:
            f.write(file_data)
        print(f"Extracted: {filename}")

    index_path = output_dir.joinpath("PAK_Index.txt")
    with open(index_path, 'w', encoding='ascii', newline='\n') as f:
        f.writelines(index_lines)
    print(f"Created: {index_path.name}")

    print(f"\nUnpacked {num_files} files to: {output_dir}")
    return True


def read_index_order(index_path: Path, all_files):
    entries = []
    with open(index_path, 'r', encoding='utf-8', errors='replace') as f:
        for line_num, line in enumerate(f, 1):
            line = line.rstrip('\r\n')
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            if '\t' not in line:
                print(f"Warning: {index_path.name} line {line_num}: no tab separator, skipping")
                continue
            name, idx_text = line.rsplit('\t', 1)
            name = name.strip()
            idx_text = idx_text.strip()
            try:
                idx = int(idx_text)
            except ValueError:
                print(f"Warning: {index_path.name} line {line_num}: '{idx_text}' is not an index, skipping")
                continue
            entries.append((idx, name, line_num))

    if not entries:
        print(f"{index_path.name} has no valid entries; using default order")
        return None

    entries.sort(key=lambda e: (e[0], e[1]))

    by_name = {f.name: f for f in all_files}
    by_lower = {}
    for f in all_files:
        by_lower.setdefault(f.name.lower(), f)

    ordered = []
    used = set()
    seen_idx = set()
    for idx, name, line_num in entries:
        if idx in seen_idx:
            print(f"Warning: {index_path.name} line {line_num}: duplicate index {idx}, sorting by name")
        seen_idx.add(idx)

        f = by_name.get(name)
        if f is None:
            f = by_lower.get(name.lower())
            if f is not None:
                print(f"Warning: {index_path.name} line {line_num}: '{name}' matched '{f.name}' ignoring case")
        if f is None:
            print(f"Warning: {index_path.name} line {line_num}: '{name}' not found among .g/.gs/.ga files, skipping")
            continue
        if f in used:
            print(f"Warning: {index_path.name} line {line_num}: '{f.name}' listed more than once, skipping")
            continue
        used.add(f)
        ordered.append(f)

    unlisted = [f.name for f in all_files if f not in used]
    if unlisted:
        print(f"Warning: not listed in {index_path.name}, skipping: " + ", ".join(sorted(unlisted)))

    return ordered


def write_info(dir_path: Path, extra_pad: int = 0):
    valid_exts = ['.g', '.gs', '.ga']

    all_files = []
    for f in dir_path.iterdir():
        if f.is_file() and f.suffix.lower() in valid_exts:
            all_files.append(f)

    sorted_files = None
    index_path = dir_path.joinpath("PAK_Index.txt")
    if index_path.exists():
        sorted_files = read_index_order(index_path, all_files)
        if sorted_files is not None:
            print(f"Using file order from {index_path.name}")
            if not sorted_files:
                print(f"Error: {index_path.name} lists no files that exist in '{dir_path}'")
                return False

    if sorted_files is None:
        gs_files = sorted([f for f in all_files if f.suffix.lower() == '.gs'], key=lambda x: x.name.lower())
        g_files = sorted([f for f in all_files if f.suffix.lower() == '.g'], key=lambda x: x.name.lower())
        ga_files = sorted([f for f in all_files if f.suffix.lower() == '.ga'], key=lambda x: x.name.lower())

        sorted_files = gs_files + g_files + ga_files

    if not sorted_files:
        print(f"Error: No .g, .gs, or .ga files found in '{dir_path}'")
        return False

    num_files = len(sorted_files)
    print(f"Writing PAK_Info.bin for {num_files} files")
    if extra_pad:
        print(f"Extra padding: +{extra_pad} bytes after each file")

    header_size = 8
    toc_size = num_files * 16

    file_entries = []
    string_pool = bytearray()
    for f in sorted_files:
        name_bytes = f.name.encode('ascii')
        name_offset = len(string_pool)
        string_pool.extend(name_bytes)
        string_pool.append(0)
        file_entries.append({
            'name': f.name,
            'path': f,
            'name_offset': name_offset,
            'size': f.stat().st_size
        })

    string_pool_size = len(string_pool)

    pack_info_size = header_size + toc_size + string_pool_size
    remainder = pack_info_size % 0x10
    if remainder != 0:
        pack_info_size += 0x10 - remainder

    print(f"PAK_Info.bin size: {pack_info_size} (0x{pack_info_size:02x})")

    current_ptr = pack_info_size
    for entry in file_entries:
        entry['data_ptr'] = current_ptr
        padded_size = entry['size'] + 4
        if padded_size % 0x10 != 0:
            padded_size += 0x10 - (padded_size % 0x10)
        padded_size += extra_pad
        entry['padded_size'] = padded_size
        current_ptr += padded_size

    output = bytearray()

    output.extend(b'pack')
    output.extend(struct.pack('>H', num_files))
    output.extend(b'\x00\x00')

    string_pool_offset = header_size + toc_size

    for entry in file_entries:
        col0 = 0
        col1 = string_pool_offset + entry['name_offset']
        col2 = entry['data_ptr']
        col3 = entry['size']
        output.extend(struct.pack('>IIII', col0, col1, col2, col3))

    output.extend(string_pool)

    while len(output) < pack_info_size:
        output.append(0)

    pak_info_path = dir_path.joinpath("PAK_Info.bin")
    with open(pak_info_path, 'wb') as f:
        f.write(output)

    print(f"Created: {pak_info_path.name}")
    print(f"First file starts at: {pack_info_size} (0x{pack_info_size:02x})")
    print(f"\nFile offsets:")
    for entry in file_entries:
        print(f"  {entry['name']}: ptr=0x{entry['data_ptr']:02x}, size={entry['size']}, padded={entry['padded_size']}")
    return True


def pack_directory(dir_path: Path):
    pak_info_path = dir_path.joinpath("PAK_Info.bin")
    if not pak_info_path.exists():
        print(f"Error: PAK_Info.bin not found in '{dir_path}'")
        return False

    with open(pak_info_path, 'rb') as f:
        pak_info_data = f.read()

    if len(pak_info_data) < 10 or pak_info_data[:4] != b'pack':
        print(f"Error: PAK_Info.bin is not valid")
        return False

    num_files = struct.unpack('>H', pak_info_data[4:6])[0]
    print(f"Packing directory: {dir_path.name}")
    print(f"Number of files: {num_files}")

    toc_start = 0x08
    toc_entry_size = 16

    toc = []
    for i in range(num_files):
        offset = toc_start + i * toc_entry_size
        col0, col1, col2, col3 = struct.unpack('>IIII', pak_info_data[offset:offset + 16])
        name_offset = col1
        name_end = pak_info_data.find(b'\x00', name_offset)
        if name_end == -1:
            name_end = len(pak_info_data)
        filename = pak_info_data[name_offset:name_end].decode('ascii', errors='replace')
        toc.append({
            'filename': filename,
            'data_ptr': col2,
            'size': col3
        })

    max_ptr = max(entry['data_ptr'] + entry['size'] for entry in toc)
    pak_info_len = len(pak_info_data)

    file_data_list = []
    for entry in toc:
        file_path = dir_path.joinpath(entry['filename'])
        if not file_path.exists():
            print(f"Warning: File '{entry['filename']}' not found, skipping")
            file_data = b''
        else:
            with open(file_path, 'rb') as f:
                file_data = f.read()
            print(f"Added: {entry['filename']}")
        file_data_list.append((entry['data_ptr'], file_data))

    output_data = bytearray(pak_info_data)

    current_end = len(output_data)

    for data_ptr, file_data in file_data_list:
        if data_ptr > len(output_data):
            padding_needed = data_ptr - len(output_data)
            output_data.extend(b'\x00' * padding_needed)
        elif data_ptr < len(output_data):
            print(f"Warning: data_ptr {data_ptr} overlaps with existing data")
            continue
        output_data.extend(file_data)

    output_data.extend(b'\x00\x00\x00\x00')

    remainder = len(output_data) % 0x10
    if remainder != 0:
        padding_needed = 0x10 - remainder
        output_data.extend(b'\x00' * padding_needed)

    # pak_path = dir_path.parent / f"{dir_path.stem}.pak"
    dir_parent = dir_path.parent
    output_name = dir_path.stem
    dir_stem_split = output_name.split("_")
    if dir_stem_split[len(dir_stem_split)-1] == "unpacked":
        output_name = dir_path.stem[:-9]
    pak_path = dir_parent.joinpath(f"{output_name}.pak")
    with open(pak_path, 'wb') as f:
        f.write(output_data)

    print(f"\nCreated: {pak_path.name} ({len(output_data)} bytes)")
    return True


def main():
    if len(sys.argv) < 3:
        print("Usage: python tellius_pak.py <unpack|pack|write_info> <path>")
        print("  unpack <file.pak>      - Extract files from PAK archive")
        print("  pack <directory>       - Create PAK archive from directory")
        print("  write_info <directory> [pad16] - Write PAK_Info.bin from asset files")
        print("      pad16 adds 16 extra bytes of padding between files")
        print("      uses PAK_Index.txt file order when present")
        sys.exit(1)

    command = sys.argv[1].lower()
    path = Path(sys.argv[2])

    if command == 'unpack':
        if not path.is_file():
            print(f"Error: '{path}' is not a file")
            sys.exit(1)
        success = unpack_pak(path)
    elif command == 'pack':
        if not path.is_dir():
            print(f"Error: '{path}' is not a directory")
            sys.exit(1)
        success = pack_directory(path)
    elif command == 'write_info':
        if not path.is_dir():
            print(f"Error: '{path}' is not a directory")
            sys.exit(1)
        extra_pad = 0
        if len(sys.argv) > 3:
            if sys.argv[3].lower() == 'pad16':
                extra_pad = 0x10
            else:
                print(f"Error: Unknown write_info option '{sys.argv[3]}'. Use 'pad16'")
                sys.exit(1)
        success = write_info(path, extra_pad)
    else:
        print(f"Error: Unknown command '{command}'. Use 'unpack', 'pack', or 'write_info'")
        sys.exit(1)

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
