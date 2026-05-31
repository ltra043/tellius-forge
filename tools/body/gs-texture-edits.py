#!/usr/bin/env python3
"""Standalone GUI tool for editing material indices and render flags in
FE9/FE10 body (.gs) files.

Built with PyQt6.
"""

import sys
import os
import struct
from datetime import datetime
from PyQt6 import QtCore, QtGui, QtWidgets

BASE_OFFSET = 0x20

def _ru4(data, offset):
    return struct.unpack('>I', data[offset:offset+4])[0]

def _ru2(data, offset):
    return struct.unpack('>H', data[offset:offset+2])[0]

def _resolve(raw, ptr):
    if ptr == 0:
        return 0
    return ptr + BASE_OFFSET

def _parse_skeleton(filepath):
    with open(filepath, 'rb') as f:
        raw = f.read()
    string_pool_offset = _ru4(raw, 0x04)
    bone_count = _ru4(raw, 0x08)
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
    bones = [None] * bone_count
    for b in range(bone_count):
        base = 0x10 + b * 0xF4
        name_off = _ru4(raw, base + 0xF0)
        bone_name = string_map.get(name_off, f'bone_{b}')
        bones[b] = bone_name
    return bones

def _parse_body(filepath):
    with open(filepath, 'rb') as f:
        raw = f.read()
    mat_count = _ru2(raw, 0x74)
    vert_count = _ru2(raw, 0x6C)
    norm_count = _ru2(raw, 0x6E)
    uv_count = _ru2(raw, 0x70)
    chunk_count = _ru2(raw, 0x76)
    chunk_off_raw = _ru4(raw, 0x5C)
    chunk_off = _resolve(raw, chunk_off_raw)
    if chunk_off == 0:
        chunk_off_raw = _ru4(raw, 0x60)
        chunk_off = _resolve(raw, chunk_off_raw)
    chunks = []
    total_dl_verts = 0
    total_faces = 0
    for i in range(chunk_count):
        pos = chunk_off + i * 32
        ptr_a_raw = _ru4(raw, pos)
        prim_type = raw[pos + 8]
        render_flags = raw[pos + 9]
        mat_idx = raw[pos + 0x0B]
        gx_attr = raw[pos + 0x10:pos + 0x14]
        dl_raw = _ru4(raw, pos + 0x14)
        dl_size = _ru4(raw, pos + 0x18)
        gx_cache_raw = _ru4(raw, pos + 0x1C)

        dl_addr = _resolve(raw, dl_raw)
        gx_cache_addr = _resolve(raw, gx_cache_raw)

        # Bone palette from GX cache
        bone_ids = []
        if gx_cache_addr and gx_cache_addr < len(raw) and raw[gx_cache_addr] == 0x10:
            palette_count = raw[gx_cache_addr + 1]
            for j in range(palette_count):
                bid = raw[gx_cache_addr + 2 + j]
                if bid < len(raw):
                    bone_ids.append(bid)

        # PtrA fallback (used when chunk has no DL / GX cache)
        ptra_slot = 0
        ptra_bone_name = ''
        ptr_a = _resolve(raw, ptr_a_raw)
        if ptr_a and ptr_a < len(raw):
            ptra_slot = raw[ptr_a + 0x1D]
            name_ptr_raw = _ru4(raw, ptr_a)
            name_ptr = _resolve(raw, name_ptr_raw)
            if name_ptr and name_ptr < len(raw):
                try:
                    end = raw.index(0, name_ptr)
                    ptra_bone_name = raw[name_ptr:end].decode('ascii', errors='replace')
                except ValueError:
                    pass

        # Parse display list for vert/face counts
        dl_verts = 0
        face_count = 0
        if dl_addr and dl_addr < len(raw) and dl_size > 0:
            sb = (render_flags & 2) != 0
            hc = (gx_attr[2] & 0x10) != 0
            hu = (gx_attr[2] & 0x80) != 0
            bpv = 6 + (1 if sb else 0) + (2 if hc else 0) + (2 if hu else 0)

            tp = dl_addr
            te = min(dl_addr + dl_size, len(raw))

            while tp < te:
                if raw[tp] != 0x98:
                    break
                tp += 1
                if tp + 2 > te:
                    break
                slen = _ru2(raw, tp)
                tp += 2
                if slen > 1000:
                    break
                for _ in range(slen):
                    if tp + bpv > te:
                        break
                    tp += bpv
                    dl_verts += 1

            # Face count depends on primitive type
            if prim_type == 0x30:  # triangle list
                face_count = dl_verts // 3
            elif prim_type == 0x38:  # triangle strip
                face_count = dl_verts - 2 if dl_verts >= 3 else 0

        total_dl_verts += dl_verts
        total_faces += face_count

        chunks.append({
            'index': i,
            'prim_type': prim_type,
            'mat_idx': mat_idx,
            'render_flags': render_flags,
            'bone_ids': bone_ids,
            'ptra_slot': ptra_slot,
            'ptra_bone_name': ptra_bone_name,
            'dl_verts': dl_verts,
            'face_count': face_count,
        })
    header_info = {
        'mat_count': mat_count,
        'chunk_count': chunk_count,
        'vert_count': vert_count,
        'norm_count': norm_count,
        'uv_count': uv_count,
        'total_dl_verts': total_dl_verts,
        'total_faces': total_faces,
    }
    return header_info, chunks


class Ui_MainWindow(object):
    """Auto-generated from gs-texture-edits.ui by pyuic6."""
    def setupUi(self, MainWindow):
        MainWindow.setObjectName("MainWindow")
        MainWindow.resize(610, 572)
        MainWindow.setMinimumSize(QtCore.QSize(0, 0))
        MainWindow.setMaximumSize(QtCore.QSize(610, 1000))
        self.centralwidget = QtWidgets.QWidget(parent=MainWindow)
        self.centralwidget.setMaximumSize(QtCore.QSize(128128, 128128))
        self.centralwidget.setObjectName("centralwidget")
        self.verticalLayout_7 = QtWidgets.QVBoxLayout(self.centralwidget)
        self.verticalLayout_7.setObjectName("verticalLayout_7")
        self.stackedWidget = QtWidgets.QStackedWidget(parent=self.centralwidget)
        self.stackedWidget.setObjectName("stackedWidget")
        self.Start_0 = QtWidgets.QWidget()
        self.Start_0.setObjectName("Start_0")
        self.verticalLayout_2 = QtWidgets.QVBoxLayout(self.Start_0)
        self.verticalLayout_2.setContentsMargins(-1, -1, -1, 9)
        self.verticalLayout_2.setSpacing(9)
        self.verticalLayout_2.setObjectName("verticalLayout_2")
        self.label_0_title = QtWidgets.QLabel(parent=self.Start_0)
        font = QtGui.QFont()
        font.setPointSize(20)
        self.label_0_title.setFont(font)
        self.label_0_title.setObjectName("label_0_title")
        self.verticalLayout_2.addWidget(self.label_0_title)
        self.frame_0_edit = QtWidgets.QFrame(parent=self.Start_0)
        self.frame_0_edit.setObjectName("frame_0_edit")
        self.verticalLayout_6 = QtWidgets.QVBoxLayout(self.frame_0_edit)
        self.verticalLayout_6.setObjectName("verticalLayout_6")
        self.verticalLayout_2.addWidget(self.frame_0_edit)
        self.groupBox_0_paths = QtWidgets.QGroupBox(parent=self.Start_0)
        self.groupBox_0_paths.setObjectName("groupBox_0_paths")
        self.verticalLayout_8 = QtWidgets.QVBoxLayout(self.groupBox_0_paths)
        self.verticalLayout_8.setObjectName("verticalLayout_8")
        self.lineEdit_0_input_body = QtWidgets.QLineEdit(parent=self.groupBox_0_paths)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Minimum)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.lineEdit_0_input_body.sizePolicy().hasHeightForWidth())
        self.lineEdit_0_input_body.setSizePolicy(sizePolicy)
        self.lineEdit_0_input_body.setMinimumSize(QtCore.QSize(391, 34))
        self.lineEdit_0_input_body.setMaximumSize(QtCore.QSize(16777215, 34))
        font = QtGui.QFont()
        font.setPointSize(10)
        font.setBold(False)
        self.lineEdit_0_input_body.setFont(font)
        self.lineEdit_0_input_body.setText("")
        self.lineEdit_0_input_body.setClearButtonEnabled(True)
        self.lineEdit_0_input_body.setObjectName("lineEdit_0_input_body")
        self.verticalLayout_8.addWidget(self.lineEdit_0_input_body)
        self.button_0_input_body = QtWidgets.QPushButton(parent=self.groupBox_0_paths)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.button_0_input_body.sizePolicy().hasHeightForWidth())
        self.button_0_input_body.setSizePolicy(sizePolicy)
        self.button_0_input_body.setMinimumSize(QtCore.QSize(0, 30))
        self.button_0_input_body.setMaximumSize(QtCore.QSize(16777215, 31))
        font = QtGui.QFont()
        font.setPointSize(10)
        font.setBold(False)
        self.button_0_input_body.setFont(font)
        self.button_0_input_body.setObjectName("button_0_input_body")
        self.verticalLayout_8.addWidget(self.button_0_input_body)
        spacerItem = QtWidgets.QSpacerItem(20, 12, QtWidgets.QSizePolicy.Policy.Minimum, QtWidgets.QSizePolicy.Policy.Fixed)
        self.verticalLayout_8.addItem(spacerItem)
        self.lineEdit_0_input_skeleton = QtWidgets.QLineEdit(parent=self.groupBox_0_paths)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Minimum)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.lineEdit_0_input_skeleton.sizePolicy().hasHeightForWidth())
        self.lineEdit_0_input_skeleton.setSizePolicy(sizePolicy)
        self.lineEdit_0_input_skeleton.setMinimumSize(QtCore.QSize(391, 34))
        self.lineEdit_0_input_skeleton.setMaximumSize(QtCore.QSize(16777215, 34))
        font = QtGui.QFont()
        font.setPointSize(10)
        font.setBold(False)
        self.lineEdit_0_input_skeleton.setFont(font)
        self.lineEdit_0_input_skeleton.setClearButtonEnabled(True)
        self.lineEdit_0_input_skeleton.setObjectName("lineEdit_0_input_skeleton")
        self.verticalLayout_8.addWidget(self.lineEdit_0_input_skeleton)
        self.button_0_input_skeleton = QtWidgets.QPushButton(parent=self.groupBox_0_paths)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.button_0_input_skeleton.sizePolicy().hasHeightForWidth())
        self.button_0_input_skeleton.setSizePolicy(sizePolicy)
        self.button_0_input_skeleton.setMinimumSize(QtCore.QSize(0, 30))
        self.button_0_input_skeleton.setMaximumSize(QtCore.QSize(16777215, 31))
        font = QtGui.QFont()
        font.setPointSize(10)
        font.setBold(False)
        self.button_0_input_skeleton.setFont(font)
        self.button_0_input_skeleton.setObjectName("button_0_input_skeleton")
        self.verticalLayout_8.addWidget(self.button_0_input_skeleton)
        self.verticalLayout_2.addWidget(self.groupBox_0_paths)
        spacerItem1 = QtWidgets.QSpacerItem(20, 12, QtWidgets.QSizePolicy.Policy.Minimum, QtWidgets.QSizePolicy.Policy.Fixed)
        self.verticalLayout_2.addItem(spacerItem1)
        self.groupBox = QtWidgets.QGroupBox(parent=self.Start_0)
        self.groupBox.setObjectName("groupBox")
        self.verticalLayout_3 = QtWidgets.QVBoxLayout(self.groupBox)
        self.verticalLayout_3.setObjectName("verticalLayout_3")
        self.radio_1 = QtWidgets.QRadioButton(parent=self.groupBox)
        font = QtGui.QFont()
        font.setPointSize(10)
        self.radio_1.setFont(font)
        self.radio_1.setChecked(True)
        self.radio_1.setObjectName("radio_1")
        self.verticalLayout_3.addWidget(self.radio_1)
        self.radio_2 = QtWidgets.QRadioButton(parent=self.groupBox)
        font = QtGui.QFont()
        font.setPointSize(10)
        self.radio_2.setFont(font)
        self.radio_2.setObjectName("radio_2")
        self.verticalLayout_3.addWidget(self.radio_2)
        self.lineEdit_0_output = QtWidgets.QLineEdit(parent=self.groupBox)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Minimum)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.lineEdit_0_output.sizePolicy().hasHeightForWidth())
        self.lineEdit_0_output.setSizePolicy(sizePolicy)
        self.lineEdit_0_output.setMinimumSize(QtCore.QSize(391, 34))
        self.lineEdit_0_output.setMaximumSize(QtCore.QSize(16777215, 34))
        font = QtGui.QFont()
        font.setPointSize(10)
        font.setBold(False)
        self.lineEdit_0_output.setFont(font)
        self.lineEdit_0_output.setReadOnly(True)
        self.lineEdit_0_output.setClearButtonEnabled(True)
        self.lineEdit_0_output.setObjectName("lineEdit_0_output")
        self.verticalLayout_3.addWidget(self.lineEdit_0_output)
        self.button_0_output = QtWidgets.QPushButton(parent=self.groupBox)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.button_0_output.sizePolicy().hasHeightForWidth())
        self.button_0_output.setSizePolicy(sizePolicy)
        self.button_0_output.setMinimumSize(QtCore.QSize(0, 30))
        self.button_0_output.setMaximumSize(QtCore.QSize(16777215, 31))
        font = QtGui.QFont()
        font.setPointSize(10)
        font.setBold(False)
        self.button_0_output.setFont(font)
        self.button_0_output.setObjectName("button_0_output")
        self.verticalLayout_3.addWidget(self.button_0_output)
        self.verticalLayout_2.addWidget(self.groupBox)
        spacerItem2 = QtWidgets.QSpacerItem(20, 24, QtWidgets.QSizePolicy.Policy.Minimum, QtWidgets.QSizePolicy.Policy.Fixed)
        self.verticalLayout_2.addItem(spacerItem2)
        self.button_0_next = QtWidgets.QPushButton(parent=self.Start_0)
        self.button_0_next.setMinimumSize(QtCore.QSize(0, 30))
        font = QtGui.QFont()
        font.setPointSize(10)
        self.button_0_next.setFont(font)
        self.button_0_next.setObjectName("button_0_next")
        self.verticalLayout_2.addWidget(self.button_0_next)
        self.stackedWidget.addWidget(self.Start_0)
        self.Chunk_1 = QtWidgets.QWidget()
        self.Chunk_1.setObjectName("Chunk_1")
        self.verticalLayout = QtWidgets.QVBoxLayout(self.Chunk_1)
        self.verticalLayout.setContentsMargins(-1, -1, -1, 10)
        self.verticalLayout.setObjectName("verticalLayout")
        self.label_1_title = QtWidgets.QLabel(parent=self.Chunk_1)
        font = QtGui.QFont()
        font.setPointSize(16)
        self.label_1_title.setFont(font)
        self.label_1_title.setObjectName("label_1_title")
        self.verticalLayout.addWidget(self.label_1_title)
        self.frame_1_input = QtWidgets.QFrame(parent=self.Chunk_1)
        self.frame_1_input.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.frame_1_input.setFrameShadow(QtWidgets.QFrame.Shadow.Raised)
        self.frame_1_input.setObjectName("frame_1_input")
        self.verticalLayout_5 = QtWidgets.QVBoxLayout(self.frame_1_input)
        self.verticalLayout_5.setObjectName("verticalLayout_5")
        self.verticalLayout.addWidget(self.frame_1_input)
        self.frame = QtWidgets.QFrame(parent=self.Chunk_1)
        self.frame.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.frame.setFrameShadow(QtWidgets.QFrame.Shadow.Raised)
        self.frame.setObjectName("frame")
        self.horizontalLayout_2 = QtWidgets.QHBoxLayout(self.frame)
        self.horizontalLayout_2.setContentsMargins(36, -1, -1, -1)
        self.horizontalLayout_2.setObjectName("horizontalLayout_2")
        self.label_2 = QtWidgets.QLabel(parent=self.frame)
        font = QtGui.QFont()
        font.setPointSize(10)
        self.label_2.setFont(font)
        self.label_2.setWordWrap(True)
        self.label_2.setObjectName("label_2")
        self.horizontalLayout_2.addWidget(self.label_2)
        self.verticalLayout.addWidget(self.frame)
        self.tableWidget = QtWidgets.QTableWidget(parent=self.Chunk_1)
        self.tableWidget.setMaximumSize(QtCore.QSize(16777215, 16777215))
        self.tableWidget.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self.tableWidget.setAlternatingRowColors(True)
        self.tableWidget.setRowCount(12)
        self.tableWidget.setObjectName("tableWidget")
        self.tableWidget.setColumnCount(4)
        item = QtWidgets.QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(0, item)
        item = QtWidgets.QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(1, item)
        item = QtWidgets.QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(2, item)
        item = QtWidgets.QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(3, item)
        item = QtWidgets.QTableWidgetItem()
        self.tableWidget.setItem(0, 3, item)
        item = QtWidgets.QTableWidgetItem()
        self.tableWidget.setItem(1, 3, item)
        hh = self.tableWidget.horizontalHeader()
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Fixed)
        hh.resizeSection(0, 58)
        hh.resizeSection(1, 58)
        hh.resizeSection(2, 124)
        hh.resizeSection(3, 320)
        self.tableWidget.verticalHeader().setVisible(False)
        self.tableWidget.setWordWrap(True)
        self.tableWidget.verticalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.tableWidget.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked)
        self._edit_delegate = _ColumnEditDelegate(self.tableWidget)
        self.tableWidget.setItemDelegate(self._edit_delegate)
        self.verticalLayout.addWidget(self.tableWidget)
        self.label_1_status = QtWidgets.QLabel(parent=self.Chunk_1)
        self.label_1_status.setMinimumSize(QtCore.QSize(0, 30))
        self.label_1_status.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.label_1_status.setObjectName("label_1_status")
        self.verticalLayout.addWidget(self.label_1_status)
        self.button_1_back = QtWidgets.QPushButton(parent=self.Chunk_1)
        self.button_1_back.setMinimumSize(QtCore.QSize(0, 30))
        font = QtGui.QFont()
        font.setPointSize(10)
        self.button_1_back.setFont(font)
        self.button_1_back.setObjectName("button_1_back")
        self.verticalLayout.addWidget(self.button_1_back)
        self.stackedWidget.addWidget(self.Chunk_1)
        self.verticalLayout_7.addWidget(self.stackedWidget)
        MainWindow.setCentralWidget(self.centralwidget)

        self.retranslateUi(MainWindow)
        self.stackedWidget.setCurrentIndex(0)
        QtCore.QMetaObject.connectSlotsByName(MainWindow)

    def retranslateUi(self, MainWindow):
        _translate = QtCore.QCoreApplication.translate
        MainWindow.setWindowTitle(_translate("MainWindow", "Body (.gs) Edits"))
        self.label_0_title.setText(_translate("MainWindow", "FE9 & FE10 Body (.gs) Texture Edits"))
        self.groupBox_0_paths.setTitle(_translate("MainWindow", "Inputs"))
        self.lineEdit_0_input_body.setToolTip(_translate("MainWindow", "<html><head/><body><p>Choose an output folder.</p></body></html>"))
        self.button_0_input_body.setToolTip(_translate("MainWindow", "<html><head/><body><p>Choose an input body file. Program will try to auto-detect the corresponding skeleton.</p></body></html>"))
        self.button_0_input_body.setText(_translate("MainWindow", "Select Input Body (.gs)"))
        self.lineEdit_0_input_skeleton.setText(_translate("MainWindow", "Program will attempt to auto-detect the coordinating skeleton upon body file selection"))
        self.button_0_input_skeleton.setToolTip(_translate("MainWindow", "<html><head/><body><p>Program will try to detect the corresponding skeleton after a body file is chosen. You may override the automatic selection.</p></body></html>"))
        self.button_0_input_skeleton.setText(_translate("MainWindow", "Select Input Skeleton (.g)"))
        self.groupBox.setTitle(_translate("MainWindow", "Output"))
        self.radio_1.setToolTip(_translate("MainWindow", "<html><head/><body><p>Select this option to make edits in the same file as the input body file.</p></body></html>"))
        self.radio_1.setText(_translate("MainWindow", " Overwrite Input Body File"))
        self.radio_2.setToolTip(_translate("MainWindow", "<html><head/><body><p>Select this option to make edits in a separate .gs file and  preserve the input body file.</p></body></html>"))
        self.radio_2.setText(_translate("MainWindow", " Create New Output Body File"))
        self.button_0_output.setToolTip(_translate("MainWindow", "<html><head/><body><p>Choose an output path to a .gs file. I it does not exist, it will be created. If it does exist, it will be overwritten.</p></body></html>"))
        self.button_0_output.setText(_translate("MainWindow", "Select Output Path (.gs)"))
        self.button_0_next.setText(_translate("MainWindow", "Next"))
        self.label_1_title.setText(_translate("MainWindow", "Chunk Material Info"))
        self.label_2.setText(_translate("MainWindow", "X total Materials available.\n"
"Change material used by a chunk by changing the value in the \"Material\" column"))
        self.tableWidget.setToolTip(_translate("MainWindow", "<html><head/><body><p>Table displaying Chunk Index (decimal), Material Index (decimal), Bone IDs (hexadecimal), and Bone Names</p></body></html>"))
        item = self.tableWidget.horizontalHeaderItem(0)
        item.setText(_translate("MainWindow", "Chunk"))
        item = self.tableWidget.horizontalHeaderItem(1)
        item.setText(_translate("MainWindow", "Material"))
        item = self.tableWidget.horizontalHeaderItem(2)
        item.setText(_translate("MainWindow", "Bone IDs"))
        item = self.tableWidget.horizontalHeaderItem(3)
        item.setText(_translate("MainWindow", "Bone Names"))
        __sortingEnabled = self.tableWidget.isSortingEnabled()
        self.tableWidget.setSortingEnabled(False)
        self.tableWidget.setSortingEnabled(__sortingEnabled)
        self.label_1_status.setText(_translate("MainWindow", "Status: Waiting for input."))
        self.button_1_back.setText(_translate("MainWindow", "Back"))


class _ColumnEditDelegate(QtWidgets.QStyledItemDelegate):
    """Only column 1 (Material) gets an editor; all other columns read-only."""
    def createEditor(self, parent, option, index):
        if index.column() == 1:
            return super().createEditor(parent, option, index)
        return None


class BodyEditWindow(QtWidgets.QMainWindow):
    """Standalone window wrapping the auto-generated UI."""
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        # Insert "Publish (.gs)" button above the status label on page 1
        chunk_layout = self.ui.Chunk_1.layout()
        status_idx = chunk_layout.indexOf(self.ui.label_1_status)
        self.button_1_run = QtWidgets.QPushButton("Publish (.gs)")
        self.button_1_run.setObjectName("button_1_run")
        self.button_1_run.setMinimumSize(0, 30)
        f = self.button_1_run.font(); f.setPointSize(10); self.button_1_run.setFont(f)
        self.button_1_run.setToolTip(
            "Write changes in the table's material index to "
            "a body (.gs) file."
        )
        chunk_layout.insertWidget(status_idx, self.button_1_run)

        self._connect_signals()

    def _connect_signals(self):
        ui = self.ui
        ui.button_0_next.clicked.connect(self._next_clicked)
        ui.button_1_back.clicked.connect(
            lambda: ui.stackedWidget.setCurrentIndex(0)
        )
        ui.button_0_input_body.clicked.connect(self._pick_body)
        ui.button_0_input_skeleton.clicked.connect(self._pick_skeleton)
        ui.button_0_output.clicked.connect(self._pick_output)

        ui.radio_1.toggled.connect(self._on_output_mode)
        ui.radio_2.toggled.connect(self._on_output_mode)

        self.button_1_run.clicked.connect(self._publish)

        ui.lineEdit_0_input_body.editingFinished.connect(self._auto_skeleton)

    def _auto_skeleton(self):
        body_path = self.ui.lineEdit_0_input_body.text().strip()
        if not body_path:
            return
        dirpath = os.path.dirname(body_path)
        stem = os.path.splitext(os.path.basename(body_path))[0]
        # First: look for <same_name>.g
        candidate = os.path.join(dirpath, stem + '.g')
        if os.path.exists(candidate):
            self.ui.lineEdit_0_input_skeleton.setText(candidate)
        else:
            # Fallback: look for skeleton.g in the same directory
            fallback = os.path.join(dirpath, 'skeleton.g')
            if os.path.exists(fallback):
                self.ui.lineEdit_0_input_skeleton.setText(fallback)

        # If overwrite mode, copy body path to output
        if self.ui.radio_1.isChecked():
            self.ui.lineEdit_0_output.setText(body_path)

    def _on_output_mode(self, checked):
        if not checked:
            return
        sender = self.sender()
        if sender is self.ui.radio_1:
            self.ui.lineEdit_0_output.setText(self.ui.lineEdit_0_input_body.text())
            self.ui.lineEdit_0_output.setReadOnly(True)
        elif sender is self.ui.radio_2:
            self.ui.lineEdit_0_output.setReadOnly(False)

    def _pick_body(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Body File", 
            "",
            "Body files (*.gs);;All files (*)")
        if path:
            self.ui.lineEdit_0_input_body.setText(path)

    def _pick_skeleton(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Skeleton File", "", "Skeleton files (*.g);;All files (*)")
        if path:
            self.ui.lineEdit_0_input_skeleton.setText(path)

    def _pick_output(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Select Output Path", "", "Body files (*.gs);;All files (*)")
        if path:
            self.ui.lineEdit_0_output.setText(path)

    def _next_clicked(self):
        ui = self.ui

        # Copy body path to output when overwrite mode is active
        if ui.radio_1.isChecked():
            ui.lineEdit_0_output.setText(ui.lineEdit_0_input_body.text())

        body_path = ui.lineEdit_0_input_body.text()
        if not body_path or not os.path.exists(body_path):
            ui.label_1_status.setText("Status: Body file not found.")
            return

        # Derive model name from body path
        stem = os.path.splitext(os.path.basename(body_path))[0]
        if stem == 'body':
            parent_dir = os.path.dirname(body_path)
            grandparent_dir = os.path.dirname(parent_dir)
            model_name = os.path.basename(grandparent_dir)
        else:
            model_name = stem

        # Parse skeleton
        skeleton_path = ui.lineEdit_0_input_skeleton.text()
        skeleton_bones = None
        if skeleton_path and os.path.exists(skeleton_path):
            try:
                skeleton_bones = _parse_skeleton(skeleton_path)
            except Exception:
                pass

        # Parse body
        try:
            header, chunks = _parse_body(body_path)
        except Exception as e:
            ui.label_1_status.setText(f"Status: Error reading body file: {e}")
            return

        # Set page title
        ui.label_1_title.setText(f"{model_name}: Chunk Material Info")

        # Update info label
        ui.label_2.setText(
            f"{header['mat_count']} total Materials available. "
            f"{list(range(header['mat_count']))}\n"
            'Change material used by a chunk by changing the value '
            'in the "Material" column'
        )

        # Reset table
        ui.tableWidget.setRowCount(0)
        ui.tableWidget.setRowCount(len(chunks))

        for ch in chunks:
            row = ch['index']

            # Chunk index (read-only)
            item_chunk = QtWidgets.QTableWidgetItem(str(row))
            item_chunk.setFlags(item_chunk.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            ui.tableWidget.setItem(row, 0, item_chunk)

            # Material index (editable)
            item_mat = QtWidgets.QTableWidgetItem(str(ch['mat_idx']))
            ui.tableWidget.setItem(row, 1, item_mat)

            # Bone IDs (read-only) — fall back to PtrA slot when no GX cache
            if ch['bone_ids']:
                display_ids = ch['bone_ids']
            else:
                display_ids = [ch['ptra_slot']]
            ids_str = ', '.join(str(b) for b in display_ids)
            item_ids = QtWidgets.QTableWidgetItem(ids_str)
            item_ids.setFlags(item_ids.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            ui.tableWidget.setItem(row, 2, item_ids)

            # Bone names (read-only)
            names = []
            for bid in display_ids:
                if skeleton_bones and bid < len(skeleton_bones) and skeleton_bones[bid]:
                    name = skeleton_bones[bid].replace('|', '\u2192')
                elif ch['ptra_bone_name'] and not ch['bone_ids']:
                    name = ch['ptra_bone_name'].replace('|', '\u2192')
                else:
                    name = f'b{bid}'
                names.append(name)
            names_str = ', '.join(names) if names else '-'
            item_names = QtWidgets.QTableWidgetItem(names_str)
            item_names.setFlags(item_names.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            ui.tableWidget.setItem(row, 3, item_names)

        # Store parsed data for publish + report
        self._body_header = header
        self._body_chunks = chunks
        self._body_skeleton_bones = skeleton_bones

        ui.label_1_status.setText("Status: Loaded.")
        ui.stackedWidget.setCurrentIndex(1)

    def _publish(self):
        ui = self.ui

        input_path = ui.lineEdit_0_input_body.text().strip()
        output_path = ui.lineEdit_0_output.text().strip()
        if not input_path or not os.path.exists(input_path):
            ui.label_1_status.setText("Status: Input body file not found.")
            return
        if not output_path:
            ui.label_1_status.setText("Status: No output path specified.")
            return

        try:
            with open(input_path, 'rb') as f:
                raw = bytearray(f.read())
        except Exception as e:
            ui.label_1_status.setText(f"Status: Error reading input: {e}")
            return

        # Locate chunk table
        chunk_off_raw = _ru4(raw, 0x5C)
        chunk_off = _resolve(raw, chunk_off_raw)
        if chunk_off == 0:
            chunk_off_raw = _ru4(raw, 0x60)
            chunk_off = _resolve(raw, chunk_off_raw)
        if chunk_off == 0:
            ui.label_1_status.setText("Status: Could not locate chunk table.")
            return

        chunk_count = _ru2(raw, 0x76)

        # Read current mat values from table, compute render_flags
        new_mats = []
        for row in range(chunk_count):
            item = ui.tableWidget.item(row, 1)
            try:
                mat = int(item.text()) if item and item.text() else 0
            except ValueError:
                mat = 0
            new_mats.append(mat)

        # Apply changes chunk by chunk
        prev_mat = None
        for i in range(chunk_count):
            pos = chunk_off + i * 32
            mat_idx = new_mats[i]

            # Write mat_idx
            raw[pos + 0x0B] = mat_idx & 0xFF

            # Compute render_flags
            orig_render = raw[pos + 9]
            if prev_mat is None or mat_idx != prev_mat:
                # Leader: bits 2-3 = 00, preserve sb (bit 1) and use_cb (bit 0)
                new_render = orig_render & 0xF3
            else:
                # Follower: bits 2-3 = 11, preserve sb/use_cb
                new_render = (orig_render & 0xF3) | 0x0C
            raw[pos + 9] = new_render
            prev_mat = mat_idx

        # Write output .gs
        try:
            with open(output_path, 'wb') as f:
                f.write(raw)
        except Exception as e:
            ui.label_1_status.setText(f"Status: Error writing output: {e}")
            return

        ts = datetime.now().strftime('%H:%M:%S')
        ui.label_1_status.setText(f"Status: Published to {os.path.basename(output_path)} at {ts}")

        # ── Item E: Write markdown report ──────────────────────────────
        out_dir = os.path.dirname(output_path) or '.'
        md_name = os.path.splitext(os.path.basename(output_path))[0]
        md_path = os.path.join(out_dir, f"{md_name} - body_analysis.md")

        # Compute per-chunk stats from stored _body_data (or re-parse)
        chunks_info = getattr(self, '_body_chunks', None)
        header_info = getattr(self, '_body_header', None)
        skeleton_bones = getattr(self, '_body_skeleton_bones', None)
        if chunks_info is None or header_info is None:
            try:
                header_info, chunks_info = _parse_body(input_path)
            except Exception:
                header_info = None

        md_lines = []
        md_lines.append(f"# {md_name} - body_analysis")
        md_lines.append('')
        md_lines.append('## Overall Stats')
        md_lines.append('')
        md_lines.append('| Metric | Value |')
        md_lines.append('|--------|-------|')
        if header_info:
            md_lines.append(f'| Vertices (unique) | {header_info["vert_count"]} |')
            md_lines.append(f'| Normals | {header_info["norm_count"]} |')
            md_lines.append(f'| UVs | {header_info["uv_count"]} |')
            md_lines.append(f'| Total DL verts | {header_info["total_dl_verts"]} |')
        md_lines.append(f'| Materials | {header_info["mat_count"] if header_info else "?"} |')
        md_lines.append(f'| Chunks | {chunk_count} |')
        total_faces = 0
        for ch in (chunks_info or []):
            total_faces += ch.get('face_count', 0)
        md_lines.append(f'| Faces (sum) | {total_faces} |')
        md_lines.append('')

        md_lines.append('## Chunk Analysis')
        md_lines.append('')
        md_lines.append('| # | Mat | Render | Bone IDs | Bone Names | Verts | Faces |')
        md_lines.append('|---|-----|--------|----------|------------|-------|-------|')

        for i in range(chunk_count):
            ch = chunks_info[i] if chunks_info and i < len(chunks_info) else None

            # Current mat from table
            mat_str = str(new_mats[i])

            # Current render_flag written
            pos = chunk_off + i * 32
            render_flag = raw[pos + 9]
            render_str = f'0x{render_flag:02X}'

            # Bone info
            if ch:
                if ch['bone_ids']:
                    display_ids = ch['bone_ids']
                else:
                    display_ids = [ch['ptra_slot']]
                ids_str = ', '.join(str(b) for b in display_ids)
                names = []
                for bid in display_ids:
                    if skeleton_bones and bid < len(skeleton_bones) and skeleton_bones[bid]:
                        name = skeleton_bones[bid].replace('|', '\u2192')
                    elif ch['ptra_bone_name'] and not ch['bone_ids']:
                        name = ch['ptra_bone_name'].replace('|', '\u2192')
                    else:
                        name = f'b{bid}'
                    names.append(name)
                names_str = ', '.join(names)
                v_str = str(ch.get('dl_verts', '?'))
                f_str = str(ch.get('face_count', '?'))
            else:
                ids_str = '?'
                names_str = '?'
                v_str = '?'
                f_str = '?'

            # Wrap in backticks to prevent italicization from underscores
            names_md = f'`{names_str}`'
            if len(names_md) > 72:
                names_md = names_md[:69] + '...`'

            md_lines.append(
                f'| {i} | {mat_str} | {render_str} | {ids_str} | {names_md} | {v_str} | {f_str} |'
            )

        with open(md_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(md_lines) + '\n')


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = BodyEditWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
