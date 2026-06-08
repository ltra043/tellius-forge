"""GUI tool for making simple edits to FE9/FE10 animation (.ga) files.

Built with PyQt6.
"""

from pathlib import Path
import sys
from PyQt6.uic import loadUi
from PyQt6.QtWidgets import (QApplication, QMainWindow, QStackedWidget,
                             QMessageBox, QFileDialog)
# from PyQt6.QtGui import QStandardItemModel
from datetime import datetime
import struct
from modules.ga_sort_bones import find_ga_files, process_ga


# resource_path.reset(relative_path)
# return base_path.joinpath(relative_path)
def resource_path(relative_path):
    """ Redirect referenced paths
    Redirects the paths of external files referenced by this script.
    Wrap all filenames with the function resource_path()

    Modified to use pathlib instead of os.
        os version from https://stackoverflow.com/questions/31836104

    :param relative_path: Path
    :return: os.path.join(base_path, relative_path): Path
    """
    try:
        base_path = sys._MEIPASS2
    except Exception:
        # base_path = os.path.abspath(".")
        base_path = Path(__file__).parent
        base_path = base_path.resolve()

    # return os.path.join(base_path, relative_path)
    return base_path.joinpath(relative_path)


assets_path = Path(resource_path('assets'))
asset_ui = assets_path.joinpath('ga_simple_edits.ui')


class MainWindow(QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()
        loadUi(asset_ui, self)
        self.stackedWidget.setCurrentWidget(self.Start_0)

        self.directory = "."
        # self.selectModel = QStandardItemModel()
        # self.selected = []

        # navigation buttons
        self.button_0_next.clicked.connect(lambda: goto_next(self))
        self.button_1_back.clicked.connect(lambda: goto_0(self))
        self.button_2_back.clicked.connect(lambda: goto_0(self))
        self.button_3_back.clicked.connect(lambda: goto_0(self))

        # Start_0 buttons
        self.button_0_input.clicked.connect(lambda: select_input(self))
        self.button_0_output.clicked.connect(lambda: select_output(self))

        # Run buttons
        self.button_1_run.clicked.connect(lambda: run_1_invis(self))
        self.button_2_run.clicked.connect(lambda: run_2_swap(self))
        self.button_3_run.clicked.connect(lambda: run_3_shift(self))

        # Radio buttons
        self.radio_4.toggled.connect(lambda: select_4(self))


def goto_next(self):
    """ Confirm valid input & output selection
        - Check if input and output are existing directories and that
          neither field is empty.
        - Reset config variables in case data remains from previous use.
    """
    directory_dict = directory(self)    # create output dirs if they DNE
    print('\nRunning navigate.goto_next() ...')
    if directory_dict is None:
        QMessageBox.warning(self, "Warning",
                            'Please enter a valid output path')
        return None

    input_dir, output_dir, input_pack, output_pack, input_file = (
        list(directory_dict.values())
    )
    # if self.radio_4.isChecked():
    #     input_dir, output_dir, input_pack, output_pack, input_file = (
    #         list(directory_dict.values())
    #     )
    # else:
    #     input_dir, output_dir, input_pack, output_pack, input_file = (
    #         list(directory_dict.values())
    #     )
    input_len = len(self.lineEdit_0_input.text())
    output_len = len(self.lineEdit_0_output.text())
    len_0_check = input_len * output_len
    # len_0_check == 0 if at least one field is empty

    if not input_dir.exists():
        QMessageBox.warning(self, "Warning", 'Please enter a valid input path')
        return None
    # elif not input_pack.exists():
        # QMessageBox.warning(
        #     self,
        #     "Warning",
        #     'Please decompress pack.cmp using Lumina to continue'
        # )
        # return None

    if len_0_check == 0 and not self.radio_4.isChecked():
        QMessageBox.warning(
            self,
            "Warning",
            'Please enter a valid output path'
        )
        return None

    if self.radio_1.isChecked():
        self.stackedWidget.setCurrentWidget(self.Invis_1)
        return directory_dict
    elif self.radio_2.isChecked():
        self.stackedWidget.setCurrentWidget(self.Swap_2)
        return directory_dict
    elif self.radio_3.isChecked():
        self.stackedWidget.setCurrentWidget(self.Shift_3)
        return directory_dict
    elif self.radio_4.isChecked():
        print("Running organize edit ...")
        run_4_organize(self, directory_dict)
    else:
        QMessageBox.warning(self, "Warning", 'Please select an edit type')
        return None


def goto_0(self):
    self.stackedWidget.setCurrentWidget(self.Start_0)
    textEdits = [
        self.lineEdit_1_bone_ids,
        self.lineEdit_2_bone_orig,
        self.lineEdit_2_bone_new,
        self.lineEdit_3_bone_id,
        self.lineEdit_3_bone_delta,
    ]
    for textEdit in textEdits:
        textEdit.clear()

    status_labels = [self.label_1_status, self.label_2_status,
                     self.label_3_status]
    for status_label in status_labels:
        status_label.setText('Status: Waiting for input.')

    directory_dict = directory(self)
    input_dir, output_dir, input_pack, output_pack, _ = list(
        directory_dict.values()
        )
    clean_pack(self)


def select_4(self):
    print("Running select_4(self) ...")
    if self.radio_4.isChecked():
        self.lineEdit_0_output.setEnabled(False)
        self.button_0_output.setEnabled(False)
        self.button_0_input.setText("Select Input File or Folder")
        self.button_0_output.setText(
            "Output will overwrite input for this edit"
            )
        self.button_0_next.setText("Run Organize Edit")
        self.lineEdit_0_input.setToolTip(
            "Choose an input .ga file or a folder containing .ga files"
            )
        self.lineEdit_0_output.setToolTip(
            "Output will overwrite input for this edit"
            )

    if not self.radio_4.isChecked():
        self.lineEdit_0_output.setEnabled(True)
        self.button_0_output.setEnabled(True)
        self.button_0_input.setText("Select Input Folder")
        self.button_0_output.setText("Select Output Folder")
        self.button_0_next.setText("Next")
        self.lineEdit_0_input.setToolTip(
            "Choose an input ymu model folder containing animations"
            )
        self.lineEdit_0_output.setToolTip(
            "Choose an output folder to place edited animations"
            )


# select_input(self)      return: None
def select_input(self):
    print('\nRunning start.select_input() ...')

    if self.radio_4.isChecked():
        self.directory, _ = QFileDialog.getOpenFileName(
            None,
            "Select Input File or Folder",
            filter="GA Files (*.ga)"
        )

    else:
        self.directory = QFileDialog.getExistingDirectory(
            None,
            "Select Input Directory"
        )

    if self.directory:
        # If a folder was selected (not cancelled),
        # update lineEdit to selected directory
        input_dir = Path(self.directory)
        self.lineEdit_0_input.setText(str(input_dir))
    else:
        # If a folder selection was cancelled, use the last input
        last_input = self.lineEdit_0_input.text()
        print('No selection was made. Reusing the last input:')
        print(last_input)
        print('')
        self.lineEdit_0_input.setText(last_input)


# select_output(self)      return: None
def select_output(self):
    print('\nRunning start.select_output() ...')
    self.directory = QFileDialog.getExistingDirectory(
        None,
        "Select Output Directory"
    )
    if self.directory:
        # If a folder was selected (not cancelled),
        # update lineEdit to selected directory
        output_dir = Path(self.directory)
        self.lineEdit_0_output.setText(str(output_dir))
    else:
        # If a folder selection was cancelled, use the last output
        last_output = self.lineEdit_0_output.text()
        print('No selection was made. Reusing the last input ', last_output)
        print('')
        self.lineEdit_0_output.setText(last_output)


def directory(self):
    # input_dir = Path(input('What is the path to the input directory? '))
    # output_dir = Path(input('\nWhat is the path to the output directory? '))
    input_dir = Path(self.lineEdit_0_input.text())
    input_file = ""
    if self.radio_4.isChecked():
        if input_dir.is_file():
            input_file = input_dir
            input_dir = Path(input_dir.parent)
        output_dir = input_dir
    else:
        output_dir = Path(self.lineEdit_0_output.text())
    input_pack = input_dir.joinpath('pack')
    output_pack = output_dir.joinpath('pack')

    if not input_dir.exists():
        print('\nThe input directory does not exist')
        return None
    try:
        if not output_dir.exists():
            output_dir.mkdir()
        if not output_pack.exists():
            output_pack.mkdir()
        if not input_pack.exists():
            input_pack.mkdir()
    except FileNotFoundError:
        return None

    directory_dict = {
        'input_dir': input_dir,
        'output_dir': output_dir,
        'input_pack': input_pack,
        'output_pack': output_pack,
        'input_file': input_file
    }

    return directory_dict


def choose_edit_type(num_retries=3):
    for attempt_num in range(num_retries):
        while True:
            try:
                prompt = ('\nTypes of Edits:'
                          '\n 1: Make additional bones invisible'
                          '\n 2: Replace the bone in an existing transform'
                          '\n 3: Shift bone IDs after adding/deleting bones'
                          '\n 4: Organize data by bone ID (ascending)'
                          '\nWhich of these edits would you like to make?: ')
                edit_type = int(input(prompt))
                if 1 <= edit_type <= 4:
                    print(f'edit_type = {edit_type}')
                    return edit_type
                else:
                    print("Please enter a number between 1 and 4.")
            except ValueError as error:
                if attempt_num < num_retries - 1:
                    print('\nPlease enter integer values only.')
                else:
                    print('\nYou reached the max number of input attempts (3).'
                          '\nRun the script again to start over')
                    raise error


def input_bone_count(num_retries=3):
    for attempt_num in range(num_retries):
        try:
            add_invis_count = int(
                input('\nHow many bones would you like to make invisible? ')
                )
            print(f'add_invis_count = {add_invis_count}')
            bone_ids = []
            for bone_num in range(add_invis_count):
                bone_id = input(
                    f'\nEnter the bone ID (hex) of the bone you want to make '
                    f'invisible ({bone_num+1}/{add_invis_count}): 0x')
                bone_ids.append(bone_id)
            return bone_ids
        except ValueError as error:
            if attempt_num < num_retries - 1:
                print('\nPlease enter integer values only.')
            else:
                print('\nYou reached the max number of input attempts (3).'
                      '\nRun the script again to start over')
                raise error


def input_bone_swap():
    bone_id_old = input('\nWhat is the old bone ID in hex? 0x')
    bone_id_new = input('\nWhat is the new bone ID in hex? 0x')
    print(f'Redirecting transforms from bone_id_old: 0x{bone_id_old} to'
          f'bone_id_new: 0x{bone_id_new}'
          )
    bone_ids = {'bone_id_old': bone_id_old, 'bone_id_new': bone_id_new}
    return bone_ids


# read_ga(ga_file)    return: data_dict, misc_dict
def read_ga(ga_file):
    print(f'\nReading {ga_file.name}')
    data_dict = {}
    with open(Path(ga_file), "rb") as SOURCE:
        '''Find & Store File Pointers'''
        data = SOURCE.read()
        total_size = len(data)
        hdr_ptr = data[0:4]
        meta_ptr = int.from_bytes(data[36:40], "big")
        frame_ptr = int.from_bytes(data[44:48], "big")
        first_frame = int.from_bytes(data[20:24], "big")
        last_frame = int.from_bytes(data[24:28], "big")
        row_count = int.from_bytes(data[31:32], "big")
        table_size = row_count * 16

        '''Store source data'''
        SOURCE.seek(0)
        file_info = SOURCE.read(48)
        table_data = SOURCE.read(table_size)
        unused_table_data = SOURCE.read(meta_ptr-(48+table_size))
        # meta_size = int(table_data[-5],16)*12
        meta_data = SOURCE.read(frame_ptr - meta_ptr)
        # meta_data =  SOURCE.read(meta_size)
        # unused_meta_data = SOURCE.read(
        #     frame_ptr-meta_size-table_size-len(unused_table_data)
        #     )
        # file_info = bytearray(file_info)

        '''Create dictionary'''
        data_dict['file_info'] = file_info
        data_dict['table_data'] = table_data
        data_dict['invis_table_bytes'] = bytearray([])
        # data_dict['unused_table_data'] = unused_table_data
        data_dict['meta_data'] = meta_data
        data_dict['invis_meta_bytes'] = bytearray([])
        # data_dict['unused_meta_data'] = unused_meta_data
        data_dict['frame_data'] = bytearray([])
        data_dict['invis_frame_bytes'] = bytearray([])
        # data_dict['unused_frame_data'] = unused_frame_data
        data_dict['ftr_ptr_1'] = bytearray([])
        data_dict['ftr_data_1'] = bytearray([])
        ftr_ptr_1 = bytearray([])
        ftr_data_1 = bytearray([])

        ''''Read and store data if source has no footer data'''
        hdr_ptr = int.from_bytes(hdr_ptr, "big")
        ftr_type = -1
        if hdr_ptr == 0:
            ftr_type = 0
            frame_data = SOURCE.read()
            data_dict['frame_data'] = frame_data

        '''Store data if only Footer Data 1 is present'''
        ftr_ID = -1  # no footer data if ftr_type == 0
        data = bytearray(data)
        game_src = 10
        if int.from_bytes(data[8:9], "big") == 0:
            game_src = 9

        if ftr_type != 0:
            SOURCE.seek(hdr_ptr)
            ftr_ID = int.from_bytes(SOURCE.read(4), "big")
            if game_src == 9:
                ftr_type = 1
                ftr_ptr_1 = ftr_ID
                ftr_ptr_1: bytes = bytes.fromhex(hex(ftr_ptr_1)[2:].zfill(8))

                SOURCE.read(36)
                ftr_data_1 = SOURCE.read()
                frame_data = data[frame_ptr:hdr_ptr]

        if ftr_ID == 5:
            ftr_type = 1
            ftr_ptr_1_bytes = SOURCE.read(4)
            ftr_ptr_1 = int.from_bytes(ftr_ptr_1_bytes, "big")

            frame_data = data[frame_ptr:ftr_ptr_1]
            ftr_data_1 = data[ftr_ptr_1:hdr_ptr]
            ftr_ptr_1: int = ftr_ptr_1 + 40
            ftr_ptr_1: bytes = bytes.fromhex(hex(ftr_ptr_1)[2:].zfill(8))

        # Determine if Footer Data 2 is present
        elif ftr_ID == 0:
            ftr_ptr_2 = SOURCE.read(4)
            ftr_ptr_2 = int.from_bytes(ftr_ptr_2, "big")
            ftr_ptr_3 = SOURCE.read(4)
            ftr_ptr_3 = int.from_bytes(ftr_ptr_3, "big")

            if ftr_ptr_3 == 0:  # only Footer Data 2 is present
                ftr_type = 2
                ftr_2_size = hdr_ptr - ftr_ptr_2
                frame_data = data[frame_ptr:ftr_ptr_2]
            else:  # Both Footer Data 1 and Footer Data 2 present
                ftr_type = 3
                ftr_2_size = ftr_ptr_3 - ftr_ptr_2
                SOURCE.seek(hdr_ptr - 8)
                ftr_ptr_1_bytes = SOURCE.read(4)
                ftr_ptr_1 = int.from_bytes(ftr_ptr_1_bytes, "big")
                SOURCE.seek(ftr_ptr_1)
                ftr_data_1 = data[ftr_ptr_1:ftr_ptr_2]
                frame_data = data[frame_ptr:ftr_ptr_1]
            SOURCE.seek(ftr_ptr_2)
            ftr_data_2 = SOURCE.read(ftr_2_size)

        '''Determine variables for adding new table data'''
        SOURCE.seek(48 + row_count * 16 - 5)
        last_meta = int.from_bytes(SOURCE.read(1), "big")
        next_meta = last_meta + int.from_bytes(SOURCE.read(4), "big")
        # print(f'last_meta: int = {last_meta}, next_meta: int = {next_meta}')

        '''Determine variables for adding new meta data'''
        SOURCE.seek(meta_ptr + next_meta * 12 - 5)
        last_frame_count = int.from_bytes(SOURCE.read(1), "big")
        last_frame_start = int.from_bytes(SOURCE.read(4), "big")
        next_frame_start = last_frame_start + last_frame_count
        next_frame_start = hex(next_frame_start)
        next_frame_start = bytes.fromhex(next_frame_start[2:].zfill(8))

        data_dict['frame_data'] = frame_data
        data_dict['ftr_ptr_1'] = ftr_ptr_1
        data_dict['ftr_data_1'] = ftr_data_1

        # Store raw footer data and original sizes
        frame_end = frame_ptr + len(frame_data)
        if frame_end < total_size:
            data_dict['raw_footer'] = data[frame_end:]
        else:
            data_dict['raw_footer'] = bytearray([])
        data_dict['orig_hdr_ptr'] = int.from_bytes(data[0:4], "big")
        data_dict['orig_frame_ptr'] = frame_ptr
        data_dict['orig_frame_size'] = len(frame_data)
        data_dict['orig_data_end'] = frame_ptr + len(frame_data)
        misc_dict = {'ftr_type': ftr_type, 'next_meta': next_meta,
                     'next_frame_start': next_frame_start,
                     'game_flag': data[8]}

    return data_dict, misc_dict


def edit_invis(ga_file, data_dict: dict, misc_dict: dict, bone_ids: list):
    print(f'Editing {ga_file.name} to make more bones invisible')

    invis_table_bytes = bytearray([])
    invis_meta_bytes = bytearray([])
    invis_frame_bytes = bytearray([])

    ftr_type = misc_dict['ftr_type']
    next_meta = misc_dict['next_meta']
    next_frame_start = misc_dict['next_frame_start']
    next_frame_start_int = int.from_bytes(next_frame_start, "big")

    file_info = data_dict['file_info']
    row_count = int.from_bytes(file_info[28:32], "big")
    add_invis_count = len(bone_ids)
    row_count_new = row_count + add_invis_count
    print(f'row_count: {row_count}; row_count_new: {row_count_new}')
    # hdr_ptr_old = file_info[0:4]
    # meta_ptr_old = file_info[36:40]
    # frame_ptr_old = file_info[44:48]

    '''Add data for making a bone invisible'''
    for bone in bone_ids:
        bone = int(bone, 16)
        invis_table_bytes.extend(
            bytearray([0, 0, 0, bone,
                       0, 0, 0, 8,
                       0, 0, 0, next_meta,
                       0, 0, 0, 3]))
        next_meta += 3
        for r in range(3):
            invis_meta_bytes += (
                bytearray([0, r, 15, 0, 0, 0, 0, 1]) + next_frame_start
                )
            invis_frame_bytes.extend([0, 0, 0, 0])
            next_frame_start_int += 1
            next_frame_start = bytes.fromhex(
                hex(next_frame_start_int)[2:].zfill(8)
                )

    '''Update Pointers & File Info'''
    table_data = data_dict['table_data']
    # unused_table_data = data_dict['unused_table_data']
    meta_data = data_dict['meta_data']
    frame_data = data_dict['frame_data']

    # meta_ptr = len(file_info + table_data
    #                + invis_table_bytes + unused_table_data)
    meta_ptr = len(file_info + table_data + invis_table_bytes)
    frame_ptr = meta_ptr + len(meta_data + invis_meta_bytes)
    table_rows = int(len(table_data + invis_table_bytes) / 16)
    file_info = bytearray(file_info)

    if ftr_type == 3 or ftr_type == 1:
        hdr_ptr = frame_ptr + len(frame_data + invis_frame_bytes)
        ftr_ptr_1_int = hdr_ptr + 40
        ftr_ptr_1: bytes = bytes.fromhex(hex(ftr_ptr_1_int)[2:].zfill(8))
    elif ftr_type == 0 or ftr_type == 2:
        hdr_ptr = 0
        ftr_ptr_1: bytearray = bytearray([])

    hdr_ptr = bytes.fromhex(hex(hdr_ptr)[2:].zfill(8))
    meta_ptr = bytes.fromhex(hex(meta_ptr)[2:].zfill(8))
    frame_ptr = bytes.fromhex(hex(frame_ptr)[2:].zfill(8))
    table_rows = bytes.fromhex(hex(table_rows)[2:].zfill(8))

    file_info[0:4] = hdr_ptr
    file_info[28:32] = table_rows
    file_info[36:40] = meta_ptr
    file_info[44:48] = frame_ptr

    data_dict['file_info'] = file_info
    data_dict['invis_table_bytes'] = invis_table_bytes
    data_dict['invis_meta_bytes'] = invis_meta_bytes
    data_dict['invis_frame_bytes'] = invis_frame_bytes
    data_dict['ftr_ptr_1'] = ftr_ptr_1

    # --- FE10 handling: update raw_footer pointers, merge invis data ---
    is_fe10 = misc_dict.get('game_flag', 0) == 1
    if is_fe10 and ftr_type in (1, 2, 3):
        raw_footer = data_dict.get('raw_footer', bytearray([]))
        if len(raw_footer) > 0:
            # Merge invis additions into base keys
            combined_table = table_data + invis_table_bytes
            combined_meta = meta_data + invis_meta_bytes
            combined_frame = frame_data + invis_frame_bytes
            data_dict['table_data'] = combined_table
            data_dict['meta_data'] = combined_meta
            data_dict['frame_data'] = combined_frame

            # Recalculate pointers for FE10
            fe10_meta_ptr = 48 + len(combined_table)
            fe10_frame_ptr = fe10_meta_ptr + len(combined_meta)
            total_frame_size = len(combined_frame)
            new_data_end = fe10_frame_ptr + total_frame_size

            # hdr_ptr = EOF - 0x0c
            fe10_hdr_ptr = new_data_end + len(raw_footer) - 0x0c
            file_info[0:4] = struct.pack(">I", fe10_hdr_ptr)
            file_info[36:40] = struct.pack(">I", fe10_meta_ptr)
            file_info[44:48] = struct.pack(">I", fe10_frame_ptr)

            # Update raw_footer internal pointers by delta
            orig_data_end = data_dict.get(
                'orig_data_end',
                (data_dict.get('orig_frame_ptr', 0)
                 + data_dict.get('orig_frame_size', 0)
                 )
                )
            delta = new_data_end - orig_data_end

            if delta != 0:
                raw_footer = bytearray(raw_footer)
                footer_block_size = 0x18 if ftr_type == 3 else 0x0c
                if ftr_type in (1, 2, 3):
                    ptr_off = len(raw_footer) - footer_block_size + 4
                    if ptr_off + 4 <= len(raw_footer):
                        old_val = struct.unpack(">I",
                                                raw_footer[ptr_off:ptr_off+4]
                                                )[0]
                        raw_footer[ptr_off:ptr_off+4] = struct.pack(
                            ">I", old_val + delta
                            )
                if ftr_type == 3 and len(raw_footer) >= 0x0c:
                    ptr_2_off = len(raw_footer) - 0x0c + 4
                    old_val = struct.unpack(
                        ">I", raw_footer[ptr_2_off:ptr_2_off+4]
                        )[0]
                    raw_footer[ptr_2_off:ptr_2_off+4] = struct.pack(
                        ">I", old_val + delta
                        )
                    ptr_3_off = len(raw_footer) - 0x0c + 8
                    old_val = struct.unpack(
                        ">I", raw_footer[ptr_3_off:ptr_3_off+4]
                        )[0]
                    raw_footer[ptr_3_off:ptr_3_off+4] = struct.pack(
                        ">I", old_val + delta
                        )

                data_dict['raw_footer'] = raw_footer

            # Update tracking so write_ga uses the raw_footer path
            data_dict['orig_frame_size'] = total_frame_size
            data_dict['orig_data_end'] = new_data_end
            # Clear invis_* keys to suppress legacy path in write_ga
            data_dict['invis_table_bytes'] = bytearray([])
            data_dict['invis_meta_bytes'] = bytearray([])
            data_dict['invis_frame_bytes'] = bytearray([])

    # print(f'hdr_ptr_old: {hdr_ptr_old}, hdr_ptr: {hdr_ptr}')
    # print(f'meta_ptr_old: {hdr_ptr_old}, meta_ptr: {meta_ptr}')
    # print(f'frame_ptr_old: {hdr_ptr_old}, frame_ptr: {frame_ptr}')
    return data_dict


def edit_swap(ga_file, data_dict: dict, bone_ids: dict):
    print(f'Editing {ga_file.name} to swap bones')
    table_data = bytearray(data_dict['table_data'])
    row_count = int(len(table_data) / 16)
    int_count = row_count * 4
    table_data_ints = list(struct.unpack(f'>{int_count}I', table_data))

    bone_id_old, bone_id_new = list(bone_ids.values())
    bone_id_old = int(bone_id_old, 16)
    bone_id_new = int(bone_id_new, 16)

    for row in range(row_count):
        bone_int_pos = row * 4
        if table_data_ints[bone_int_pos] == bone_id_old:
            table_data_ints[bone_int_pos] = bone_id_new

    table_data = struct.pack(f'>{int_count}I', *table_data_ints)
    data_dict['table_data'] = table_data

    return data_dict


def edit_shift(self, ga_file, data_dict: dict, misc_dict: dict):
    print(f'Editing {ga_file.name} to shift bone IDs')

    bone_id_min = int(self.lineEdit_3_bone_id.text(), 16)
    bone_delta = int(self.lineEdit_3_bone_delta.text())

    if self.radio3_add.isChecked():
        # Add mode: only shift bone IDs, no structural changes
        table_data = bytearray(data_dict['table_data'])
        row_count = len(table_data) // 16
        int_count = row_count * 4
        table_data_ints = list(struct.unpack(f'>{int_count}I', table_data))
        for row in range(row_count):
            bone_int_pos = row * 4
            if table_data_ints[bone_int_pos] >= bone_id_min:
                table_data_ints[bone_int_pos] += bone_delta
        data_dict['table_data'] = struct.pack(
            f'>{int_count}I', *table_data_ints
            )
        return data_dict

    # --- Minus mode: fully remove bones and reindex ---
    bone_id_max = bone_id_min + bone_delta - 1
    bone_ids_to_remove = set(range(bone_id_min, bone_id_max + 1))

    file_info = bytearray(data_dict['file_info'])
    table_data = bytearray(data_dict['table_data'])
    meta_data = bytearray(data_dict['meta_data'])
    frame_data = bytearray(data_dict['frame_data'])
    raw_footer = data_dict.get('raw_footer', bytearray([]))

    # Parse bone table
    row_count = len(table_data) // 16
    table_rows = []
    for i in range(row_count):
        off = i * 16
        bone_id = struct.unpack(">I", table_data[off:off+4])[0]
        channel_mask = struct.unpack(">I", table_data[off+4:off+8])[0]
        meta_start = struct.unpack(">I", table_data[off+8:off+12])[0]
        meta_count = struct.unpack(">I", table_data[off+12:off+16])[0]
        table_rows.append([bone_id, channel_mask, meta_start, meta_count])

    # Identify meta entries to remove
    meta_indices_to_remove = set()
    for row in table_rows:
        bone_id, _, meta_start, meta_count = row
        if bone_id in bone_ids_to_remove:
            for j in range(meta_count):
                meta_indices_to_remove.add(meta_start + j)

    # Rebuild bone table
    new_table_data = bytearray()
    new_meta_start = 0
    for row in table_rows:
        bone_id, channel_mask, meta_start, meta_count = row
        if bone_id in bone_ids_to_remove:
            continue
        if bone_id > bone_id_max:
            bone_id -= bone_delta
        new_table_data.extend(struct.pack(">IIII",
                                          bone_id,
                                          channel_mask,
                                          new_meta_start,
                                          meta_count
                                          ))
        new_meta_start += meta_count

    # Rebuild meta_data and frame_data
    new_meta_data = bytearray()
    new_frame_data = bytearray()
    new_fd_counter = 0

    meta_count_total = len(meta_data) // 12
    for i in range(meta_count_total):
        if i in meta_indices_to_remove:
            continue

        off = i * 12
        ch_type = meta_data[off + 1]
        scale = meta_data[off + 2]
        last_frame = struct.unpack(">H", meta_data[off+4:off+6])[0]
        kf_count = struct.unpack(">H", meta_data[off+6:off+8])[0]
        orig_fd_start = struct.unpack(">I", meta_data[off+8:off+12])[0]

        # Copy frame data
        frame_start = orig_fd_start * 4
        frame_end = (orig_fd_start + kf_count) * 4
        if frame_end <= len(frame_data):
            new_frame_data.extend(frame_data[frame_start:frame_end])

        # Build new meta entry with recalculated fd_start
        new_entry = bytearray(12)
        new_entry[0] = 0
        new_entry[1] = ch_type
        new_entry[2] = scale
        new_entry[3] = 0
        new_entry[4:6] = struct.pack(">H", last_frame)
        new_entry[6:8] = struct.pack(">H", kf_count)
        new_entry[8:12] = struct.pack(">I", new_fd_counter)
        new_meta_data.extend(new_entry)

        new_fd_counter += kf_count

    # --- Recalculate pointers ---
    meta_ptr = 48 + len(new_table_data)
    frame_ptr = meta_ptr + len(new_meta_data)

    is_fe10 = misc_dict.get('game_flag', 0) == 1

    if len(raw_footer) > 0:
        if is_fe10:
            hdr_ptr = frame_ptr + len(new_frame_data) + len(raw_footer) - 0x0c
        else:
            hdr_ptr = frame_ptr + len(new_frame_data)
    else:
        hdr_ptr = 0

    # Update file_info
    new_row_count = len(new_table_data) // 16
    file_info[0:4] = struct.pack(">I", hdr_ptr)
    file_info[28:32] = struct.pack(">I", new_row_count)
    file_info[36:40] = struct.pack(">I", meta_ptr)
    file_info[44:48] = struct.pack(">I", frame_ptr)

    new_data_end = frame_ptr + len(new_frame_data)

    # --- Update raw_footer internal pointers by delta ---
    if len(raw_footer) > 0:
        orig_data_end = data_dict.get(
            'orig_data_end',
            (data_dict.get('orig_frame_ptr', 0)
             + data_dict.get('orig_frame_size', 0)
             )
            )
        delta = new_data_end - orig_data_end

        if delta != 0:
            raw_footer = bytearray(raw_footer)
            if not is_fe10:
                # FE9: ftr_ptr_1 at raw_footer[0:4]
                old_val = struct.unpack(">I", raw_footer[0:4])[0]
                raw_footer[0:4] = struct.pack(">I", old_val + delta)
            else:
                ftr_type = misc_dict['ftr_type']
                footer_block_size = 0x18 if ftr_type == 3 else 0x0c
                if ftr_type in (1, 2, 3):
                    ptr_off = len(raw_footer) - footer_block_size + 4
                    if ptr_off + 4 <= len(raw_footer):
                        old_val = struct.unpack(
                            ">I", raw_footer[ptr_off:ptr_off+4]
                            )[0]
                        raw_footer[ptr_off:ptr_off+4] = struct.pack(
                            ">I", old_val + delta
                            )
                if ftr_type == 3 and len(raw_footer) >= 0x0c:
                    ptr_2_off = len(raw_footer) - 0x0c + 4
                    old_val = struct.unpack(
                        ">I", raw_footer[ptr_2_off:ptr_2_off+4]
                        )[0]
                    raw_footer[ptr_2_off:ptr_2_off+4] = struct.pack(
                        ">I", old_val + delta
                        )
                    ptr_3_off = len(raw_footer) - 0x0c + 8
                    old_val = struct.unpack(
                        ">I", raw_footer[ptr_3_off:ptr_3_off+4]
                        )[0]
                    raw_footer[ptr_3_off:ptr_3_off+4] = struct.pack(
                        ">I", old_val + delta
                        )

            data_dict['raw_footer'] = raw_footer

    # --- Update data_dict ---
    data_dict['file_info'] = file_info
    data_dict['table_data'] = new_table_data
    data_dict['meta_data'] = new_meta_data
    data_dict['frame_data'] = new_frame_data
    data_dict['orig_frame_size'] = len(new_frame_data)
    data_dict['orig_data_end'] = new_data_end

    # Update misc_dict
    misc_dict['next_meta'] = new_meta_start
    if len(new_meta_data) >= 12:
        last_entry = new_meta_data[-12:]
        last_kf_count = struct.unpack(">H", last_entry[6:8])[0]
        last_fd_start = struct.unpack(">I", last_entry[8:12])[0]
        misc_dict['next_frame_start'] = struct.pack(
            ">I", last_fd_start + last_kf_count
            )

    # Keep ftr_ptr_1 for backward compat (FE9 convention)
    if not is_fe10 and len(raw_footer) > 0:
        data_dict['ftr_ptr_1'] = struct.pack(">I", hdr_ptr + 40)

    return data_dict


def write_ga(ga_file, data_dict: dict, misc_dict: dict, output_folder: Path):
    name_parts = ga_file.name.split('_')
    output_name = f'{name_parts[-2]}_{name_parts[-1]}'
    output_path = output_folder.joinpath(output_name)
    print(f'Writing {output_name}')

    ftr_type = misc_dict['ftr_type']
    raw_footer = data_dict.get('raw_footer', bytearray([]))
    frame_data = data_dict['frame_data']
    orig_frame_size = data_dict.get('orig_frame_size', -1)
    # Invis additions stored in separate keys by edit_invis — detect them
    has_invis = any(len(data_dict.get(k, bytearray([]))) > 0
                    for k in ('invis_table_bytes',
                              'invis_meta_bytes',
                              'invis_frame_bytes'
                              ))

    with open(Path(output_path), "wb+") as DEST:
        if (
            len(raw_footer) > 0
            and len(frame_data) == orig_frame_size
            and not has_invis
        ):
            # Raw footer path: byte-for-byte footer preservation
            DEST.write(data_dict['file_info'])
            DEST.write(data_dict['table_data'])
            DEST.write(data_dict['meta_data'])
            DEST.write(frame_data)
            DEST.write(raw_footer)
        else:
            # Legacy path (used by edit_invis, or files without footer)
            DEST.write(data_dict['file_info'])
            DEST.write(data_dict['table_data'])
            DEST.write(data_dict.get('invis_table_bytes', bytearray([])))
            DEST.write(data_dict['meta_data'])
            DEST.write(data_dict.get('invis_meta_bytes', bytearray([])))
            DEST.write(frame_data)
            DEST.write(data_dict.get('invis_frame_bytes', bytearray([])))
            ftr_ptr_1 = data_dict.get('ftr_ptr_1', bytearray([]))
            DEST.write(ftr_ptr_1)
            if ftr_type == 1 or ftr_type == 3:
                DEST.write(bytearray([0] * 36))
                DEST.write(data_dict.get('ftr_data_1', bytearray([])))


def run_1_invis(self):
    print('Running Invis_1 Edits ...')
    directory_dict = directory(self)
    input_dir, output_dir, input_pack, output_pack, input_file = list(
        directory_dict.values()
        )

    bone_ids = self.lineEdit_1_bone_ids.text()
    bone_ids = bone_ids.split()

    input_paths = [file for file in input_dir.iterdir()
                   if file.suffix == '.ga']
    for path in input_pack.iterdir():
        if path.suffix == '.ga':
            input_paths.append(path)

    for ga_file in input_paths:
        data_dict, misc_dict = read_ga(ga_file)
        data_dict = edit_invis(ga_file, data_dict, misc_dict, bone_ids)

        if ga_file.parent.name == 'pack':
            write_ga(ga_file, data_dict, misc_dict, output_pack)
        else:
            write_ga(ga_file, data_dict, misc_dict, output_dir)

    set_status(self)
    clean_pack(self)

    # print(f'len(data_dict) = {len(data_dict)}')
    # data_values = list(data_dict.values())
    # data_keys = list(data_dict.keys())
    # for i in range(len(data_dict)):
    #     print(f'{data_keys[i]} length: {len(data_values[i])}')


def run_2_swap(self):
    print('Running Swap_2 Edits ...')
    directory_dict = directory(self)
    input_dir, output_dir, input_pack, output_pack, input_file = list(
        directory_dict.values()
        )

    bone_id_old = self.lineEdit_2_bone_orig.text()
    bone_id_new = self.lineEdit_2_bone_new.text()
    bone_ids = {'bone_id_old': bone_id_old, 'bone_id_new': bone_id_new}

    input_paths = [file for file in input_dir.iterdir()
                   if file.suffix == '.ga'
                   ]
    for path in input_pack.iterdir():
        if path.suffix == '.ga':
            input_paths.append(path)

    for ga_file in input_paths:
        data_dict, misc_dict = read_ga(ga_file)
        data_dict = edit_swap(ga_file, data_dict, bone_ids)

        if ga_file.parent.name == 'pack':
            write_ga(ga_file, data_dict, misc_dict, output_pack)
        else:
            write_ga(ga_file, data_dict, misc_dict, output_dir)

    set_status(self)
    clean_pack(self)

    # print(f'len(data_dict) = {len(data_dict)}')
    # data_values = list(data_dict.values())
    # data_keys = list(data_dict.keys())
    # for i in range(len(data_dict)):
    #     print(f'{data_keys[i]} length: {len(data_values[i])}')


def run_3_shift(self):
    print('Running Shift_3 Edits ...')
    directory_dict = directory(self)
    input_dir, output_dir, input_pack, output_pack, input_file = list(
        directory_dict.values()
        )

    input_paths = [file for file in input_dir.iterdir()
                   if file.suffix == '.ga'
                   ]
    for path in input_pack.iterdir():
        if path.suffix == '.ga':
            input_paths.append(path)

    for ga_file in input_paths:
        data_dict, misc_dict = read_ga(ga_file)
        data_dict = edit_shift(self, ga_file, data_dict, misc_dict)

        if ga_file.parent.name == 'pack':
            write_ga(ga_file, data_dict, misc_dict, output_pack)
        else:
            write_ga(ga_file, data_dict, misc_dict, output_dir)

    set_status(self)
    clean_pack(self)


def run_4_organize(self, directory_dict):
    print('Running Organize_4 Edits ...')
    input_dir, output_dir, input_pack, output_pack, input_file = list(
        directory_dict.values()
        )

    if len(str(input_file)) > 0:
        input_path = str(input_file)
    else:
        input_path = str(input_dir)

    targets = []
    targets.extend(find_ga_files(input_path))

    if not targets:
        print("No .ga files found.")
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
    # set_status(self)
    clean_pack(self)


def set_status(self):
    current_datetime = datetime.now().strftime("%H:%M:%S")
    status_labels = [self.label_1_status,
                     self.label_2_status,
                     self.label_3_status
                     ]
    for status_label in status_labels:
        status_label.setText(
            f'Finished writing files at time {current_datetime}'
            )
    print('Completed writing files!')


def clean_pack(self):
    directory_dict = directory(self)
    input_dir, output_dir, input_pack, output_pack, input_file = list(
        directory_dict.values()
        )

    if not any(input_pack.iterdir()):
        input_pack.rmdir()
    if not any(output_pack.iterdir()):
        output_pack.rmdir()


def show_help():
    print("Launch GUI for simple editing of .ga animation files.")
    print("Current editing options include:")
    print("\t1. Make additional bones invisible.")
    print("\t2. Replace the bone in an existing transformation")
    print("\t3. Fix bone IDs after adding/deleting skeleton bones.")
    print()


def main():
    directory_dict = directory()
    input_dir, output_dir, input_pack, output_pack, input_file = list(
        directory_dict.values()
        )
    if directory_dict:
        edit_type = choose_edit_type()
        input_paths = [file for file in input_dir.iterdir()
                       if file.suffix == '.ga'
                       ]
        for path in input_pack.iterdir():
            if path.suffix == '.ga':
                input_paths.append(path)

        if edit_type == 1:      # Edit: Make additional bones invisible
            bone_ids = input_bone_count()
            for ga_file in input_paths:
                data_dict, misc_dict = read_ga(ga_file)
                data_dict = edit_invis(ga_file, data_dict, misc_dict, bone_ids)

                if ga_file.parent.name == 'pack':
                    write_ga(ga_file, data_dict, misc_dict, output_pack)
                else:
                    write_ga(ga_file, data_dict, misc_dict, output_dir)

                # print(f'len(data_dict) = {len(data_dict)}')
                # data_values = list(data_dict.values())
                # data_keys = list(data_dict.keys())
                # for i in range(len(data_dict)):
                #     print(f'{data_keys[i]} length: {len(data_values[i])}')

        elif edit_type == 2:    # Replace the bone in an existing transform
            bone_ids = input_bone_swap()
            for ga_file in input_paths:
                data_dict, misc_dict = read_ga(ga_file)
                data_dict = edit_swap(ga_file, data_dict, bone_ids)

                if ga_file.parent.name == 'pack':
                    write_ga(ga_file, data_dict, misc_dict, output_pack)
                else:
                    write_ga(ga_file, data_dict, misc_dict, output_dir)

                # print(f'len(data_dict) = {len(data_dict)}')
                # data_values = list(data_dict.values())
                # data_keys = list(data_dict.keys())
                # for i in range(len(data_dict)):
                #     pri
    print('\nTask Complete!')


def main_ui():
    args = sys.argv[1:]
    if len(args) != 0:
        if args[0] in ("-h", "--help"):
            show_help()
            sys.exit(0 if args and args[0] in ("-h", "--help") else 1)

    app = QApplication(sys.argv)
    main_window = MainWindow()
    widget = QStackedWidget()
    widget.addWidget(main_window)
    widget.setGeometry(300, 100, 580, 480)
    widget.show()
    exit(app.exec())


if __name__ == '__main__':
    # main()
    main_ui()
