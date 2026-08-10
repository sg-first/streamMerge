# -*- coding: utf-8 -*-
import sys
import os
import re

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QTextEdit, QGroupBox, QMessageBox, QCheckBox, QAbstractItemView, QComboBox
)
from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtGui import QFont

from GUI.Color import QSLauncherColor
from GUI.LogWidget import QSLogWidget
from P4Utils.P4Base import P4CLIRunner

from tapdutil import FindChildrenIDs

class P4InterchangesTool(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("P4 Interchanges Merge Tool")
        self.setMinimumSize(900, 700)
        self.resize(1100, 800)

        self.cli_runner = P4CLIRunner()
        self.changelists = []

        self.settings = QSettings("P4InterchangesTool", "P4InterchangesTool")
        self._load_settings()

        self._init_ui()
        self._init_connections()

        # 启动后自动执行：先拉取 workspace、branch 列表填充下拉框，再刷新未合并cl列表
        QTimer.singleShot(0, lambda: (self.refresh_workspaces(), self.refresh_branches(), self.refresh_list()))

    def _load_settings(self):
        self.saved_src = self.settings.value("src_branch", "//PGAME_Stream/develop/...")
        self.saved_tgt = self.settings.value("tgt_branch", "//PGAME_Stream/main/...")
        self.saved_port = self.settings.value("p4_port", "world.p4.woa.com:8666")
        self.saved_workspace = self.settings.value("p4_client", "")
        self.auto_submit = self.settings.value("auto_submit", False, type=bool)
        self.saved_ext_filter = self.settings.value("ext_filter", "")
        self.saved_ext_filter_enabled = self.settings.value("ext_filter_enabled", False, type=bool)
        self.saved_story_id = self.settings.value("story_id", "")

    def _save_settings(self):
        self.settings.setValue("src_branch", self.input_src.currentText())
        self.settings.setValue("tgt_branch", self.input_tgt.currentText())
        self.settings.setValue("p4_port", self.input_port.text())
        self.settings.setValue("p4_client", self.input_client.currentText())
        self.settings.setValue("auto_submit", self.check_auto_submit.isChecked())
        self.settings.setValue("ext_filter", self.input_ext_filter.text())
        self.settings.setValue("ext_filter_enabled", self.check_ext_filter.isChecked())
        self.settings.setValue("story_id", self.input_story_filter.text())

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)

        # ==================== P4 配置区 ====================
        # 用于填写 P4 连接信息，以及 source / target 分支路径。
        config_group = QGroupBox("P4 Configuration")
        config_layout = QVBoxLayout(config_group)

        # 第一行：P4 端口 + 当前工作区（workspace）。
        port_layout = QHBoxLayout()
        port_layout.addWidget(QLabel("P4 Port:"))
        self.input_port = QLineEdit(self.saved_port)
        self.input_port.setFixedWidth(250) # 固定宽度避免抢占后续 Workspace 下拉框的空间
        port_layout.addWidget(self.input_port)
        port_layout.addWidget(QLabel("Workspace:"))
        # 工作区（client/workspace）下拉框：可编辑，既能从下拉列表选，也能手输。
        # 列表内容由 btn_refresh_workspaces 触发 refresh_workspaces() 从 P4 拉取所有 workspace 填充。
        self.input_client = QComboBox()
        self.input_client.setEditable(True)
        self.input_client.setPlaceholderText("Workspace name")
        self.input_client.setCurrentText(self.saved_workspace)  # 默认填入上次保存的工作区
        port_layout.addWidget(self.input_client, stretch=1)  # stretch=1 让下拉框占满剩余空间，从而把端口输入框压紧、紧贴其标签左侧
        # 刷新按钮：点击后调用 refresh_workspaces() 从 P4 服务端拉取所有 workspace 列表。
        self.btn_refresh_workspaces = QPushButton("Refresh Workspaces")
        port_layout.addWidget(self.btn_refresh_workspaces)
        config_layout.addLayout(port_layout)

        # 第二行：源分支下拉框（可编辑，列表由 p4 streams 拉取填充）
        branch_layout = QHBoxLayout()
        branch_layout.addWidget(QLabel("Source Branch:"))
        self.input_src = QComboBox()
        self.input_src.setEditable(True)
        self.input_src.setCurrentText(self.saved_src)  # 默认填入上次保存的源分支
        branch_layout.addWidget(self.input_src, stretch=1)  # 下拉框占满剩余空间
        config_layout.addLayout(branch_layout)

        # 第三行：目标分支下拉框（可编辑，列表由 p4 streams 拉取填充）
        branch_layout2 = QHBoxLayout()
        branch_layout2.addWidget(QLabel("Target Branch:"))
        self.input_tgt = QComboBox()
        self.input_tgt.setEditable(True)
        self.input_tgt.setCurrentText(self.saved_tgt)  # 默认填入上次保存的目标分支
        branch_layout2.addWidget(self.input_tgt, stretch=1)  # 下拉框占满剩余空间
        config_layout.addLayout(branch_layout2)

        # 第四行：刷新分支按钮（单独一行）。点击调用 refresh_branches() 从 P4 拉取所有 stream，同时填充源/目标两个下拉框。
        refresh_stream_layout = QHBoxLayout()
        self.btn_refresh_branches = QPushButton("Refresh Branches")
        self.btn_refresh_branches.setMinimumHeight(32)
        refresh_stream_layout.addWidget(self.btn_refresh_branches)
        refresh_stream_layout.addStretch(1)  # 按钮靠左，右侧留空
        config_layout.addLayout(refresh_stream_layout)

        main_layout.addWidget(config_group)

        # ==================== 待合并列表区 ====================
        # 这块区域负责展示 interchanges 查出来的 changelist 列表。
        list_group = QGroupBox("Pending Interchanges")
        list_layout = QVBoxLayout(list_group)

        # 列表上方按钮区：刷新列表、全选、全不选、按当前用户选择、按描述关键字过滤。
        btn_layout = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh List")
        self.btn_refresh.setMinimumHeight(32)
        self.btn_select_all = QPushButton("Select All")
        self.btn_select_all.setMinimumHeight(32)
        self.btn_deselect_all = QPushButton("Deselect All")
        self.btn_deselect_all.setMinimumHeight(32)
        self.btn_select_mine = QPushButton("Filter by Mine")
        self.btn_select_mine.setMinimumHeight(32)
        self.input_desc_filter = QLineEdit()
        self.input_desc_filter.setPlaceholderText("Description contains...")
        self.input_desc_filter.setMinimumHeight(32)
        self.input_desc_filter.setMinimumWidth(220)
        self.btn_filter_desc = QPushButton("Filter by Desc")
        self.btn_filter_desc.setMinimumHeight(32)
        btn_layout.addWidget(self.btn_refresh)
        btn_layout.addWidget(self.btn_select_all)
        btn_layout.addWidget(self.btn_deselect_all)
        btn_layout.addWidget(self.btn_select_mine)
        btn_layout.addWidget(self.input_desc_filter)
        btn_layout.addWidget(self.btn_filter_desc)
        btn_layout.addStretch()
        list_layout.addLayout(btn_layout)

        # 第二行按钮区：按 TAPD 需求单过滤。
        # 输入父需求 story id，先用 tapd 接口递归查出所有子需求 id，
        # 再用 "story=<childStoryId>" 作为关键字去匹配 CL 描述。
        story_layout = QHBoxLayout()
        self.input_story_filter = QLineEdit(self.saved_story_id)
        self.input_story_filter.setPlaceholderText("TAPD story id (parent), e.g. 135577985")
        self.input_story_filter.setMinimumHeight(32)
        self.input_story_filter.setMinimumWidth(220)
        self.btn_filter_story = QPushButton("Filter By Story")
        self.btn_filter_story.setMinimumHeight(32)
        story_layout.addWidget(QLabel("Story ID:"))
        story_layout.addWidget(self.input_story_filter)
        story_layout.addWidget(self.btn_filter_story)
        story_layout.addStretch()
        list_layout.addLayout(story_layout)

        # 列表表头：这里只是视觉上的表头，用来提示下面每一列分别是什么字段（fix:现在不会跟着滚动条走，要修复一下）
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(8, 2, 8, 2)
        header_layout.setSpacing(10)

        # 预留给每行最左侧 checkbox 的宽度，让表头和内容列对齐。
        header_layout.addSpacing(24)

        header_cl = QLabel("CL")
        header_cl.setFixedWidth(110)
        header_layout.addWidget(header_cl)

        header_user = QLabel("User")
        header_user.setFixedWidth(180)
        header_layout.addWidget(header_user)

        header_date = QLabel("Date")
        header_date.setFixedWidth(110)
        header_layout.addWidget(header_date)

        # 描述列不固定宽度，默认吃掉剩余空间。
        header_desc = QLabel("Description")
        header_layout.addWidget(header_desc)

        list_layout.addWidget(header_widget)

        # 真正承载 changelist 数据的list控件
        # 每一项会通过 setItemWidget 塞入自定义行控件，表现得像一个简易表格。
        self.cl_list = QListWidget()
        self.cl_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.cl_list.setAlternatingRowColors(True)
        self.cl_list.setMinimumHeight(250)
        list_layout.addWidget(self.cl_list)

        main_layout.addWidget(list_group)

        # ==================== 合并操作区 ====================
        merge_group = QGroupBox("Merge Options")
        merge_layout = QVBoxLayout(merge_group)

        # 第一行：后缀过滤行：勾选后，merge 时只把指定后缀的文件放进 pending 列表。
        ext_filter_layout = QHBoxLayout()
        self.check_ext_filter = QCheckBox("Filter by Extension")
        self.check_ext_filter.setChecked(self.saved_ext_filter_enabled)
        ext_filter_layout.addWidget(self.check_ext_filter)
        self.input_ext_filter = QLineEdit(self.saved_ext_filter)
        self.input_ext_filter.setPlaceholderText("e.g. .cpp,.h,.py (comma separated)")
        ext_filter_layout.addWidget(self.input_ext_filter)
        ext_filter_layout.addStretch()
        merge_layout.addLayout(ext_filter_layout)

        # 第二行：自动提交选项 + 合并/停止按钮
        merge_btn_layout = QHBoxLayout()

        # 自动提交选项：勾选后 merge 完成且无冲突时会尝试直接 submit。
        self.check_auto_submit = QCheckBox("Auto Submit")
        self.check_auto_submit.setChecked(self.auto_submit)
        self.check_auto_submit.setVisible(False)  # 隐藏UI
        merge_btn_layout.addWidget(self.check_auto_submit)
        
        merge_btn_layout.addStretch()

        # 执行合并按钮：对当前勾选的 changelist 发起 merge。
        self.btn_merge = QPushButton("Merge Selected")
        self.btn_merge.setMinimumHeight(40)
        self.btn_merge.setMinimumWidth(150)
        self.btn_merge.setStyleSheet(f"background-color: {QSLauncherColor.LightGreen}; font-weight: bold;")
        merge_btn_layout.addWidget(self.btn_merge)

        merge_layout.addLayout(merge_btn_layout)

        main_layout.addWidget(merge_group)

        # ==================== 日志区 ====================
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QSLogWidget()
        log_layout.addWidget(self.log_text)
        main_layout.addWidget(log_group)

    def _init_connections(self):
        self.btn_refresh.clicked.connect(self.refresh_list)
        self.btn_select_all.clicked.connect(self.select_all)
        self.btn_deselect_all.clicked.connect(self.deselect_all)
        self.btn_select_mine.clicked.connect(self.select_mine)
        self.btn_filter_desc.clicked.connect(self.filter_by_description)
        self.input_desc_filter.returnPressed.connect(self.filter_by_description)
        self.btn_filter_story.clicked.connect(self.filter_by_story)
        self.input_story_filter.returnPressed.connect(self.filter_by_story)
        self.input_story_filter.textChanged.connect(lambda: self._save_settings())
        self.check_ext_filter.stateChanged.connect(lambda: self._save_settings())
        self.input_ext_filter.textChanged.connect(lambda: self._save_settings())
        self.btn_merge.clicked.connect(self.start_merge)
        self.input_port.textChanged.connect(lambda: self._save_settings())
        self.input_client.editTextChanged.connect(lambda: self._save_settings())
        self.btn_refresh_workspaces.clicked.connect(self.refresh_workspaces)
        self.input_src.editTextChanged.connect(lambda: self._save_settings())
        self.input_tgt.editTextChanged.connect(lambda: self._save_settings())
        self.btn_refresh_branches.clicked.connect(self.refresh_branches)
        self.check_auto_submit.stateChanged.connect(lambda: self._save_settings())

    def log(self, text: str, color: str = QSLauncherColor.White):
        self.log_text.log(text, color)

    def _update_p4_info(self):
        port = self.input_port.text().strip()
        client = self.input_client.currentText().strip()
        self.cli_runner.set_p4info(port=port, client=client)

    # 从 P4 拉取「当前用户可在本机使用」的 workspace（client）并填充下拉框
    # 逻辑对齐 P4V：Host 字段为空（可在任意机器使用）或 Host 等于本机名时保留。
    def refresh_workspaces(self):
        self._update_p4_info()

        # 先通过 p4 info 取当前登录用户名与本机名
        user = ""
        hostname = ""
        info_out, info_err = self.cli_runner.block_exec(
            "info",
            [],
            [],
            timeout=30,
        )
        if not info_err:
            for line in info_out:
                line = line.strip()
                low = line.lower()
                if low.startswith("user name:"):
                    user = line.split(":", 1)[1].strip()
                elif low.startswith("client host:"):
                    hostname = line.split(":", 1)[1].strip()

        if not user:
            self.log("Cannot determine current P4 user, aborting workspace refresh.",
                     QSLauncherColor.YellowWarning)
            return False

        # 使用 tagged output 一次性拉取所有 workspace 的 Host 字段，避免逐个执行 p4 client -o。
        out, err = self.cli_runner.block_exec(
            "-ztag clients",
            ["-u", user],
            [],
            timeout=30,
        )
        if err:
            err_text = '\n'.join(err)
            self.log(f"Failed to fetch workspaces: {err_text}", QSLauncherColor.YellowWarning)
            return False

        # tagged 输出示例：... client WS_NAME / ... Host HOST_NAME。
        # 新的 ... client 行表示一个 workspace 记录的开始。
        tag_pattern = re.compile(r"^\.\.\.\s+(\S+)(?:\s+(.*))?$")
        workspaces = []
        current_workspace = None
        for line in out:
            match = tag_pattern.match(line.strip())
            if not match:
                continue
            field = match.group(1)
            value = (match.group(2) or "").strip()
            if field.lower() == "client":
                if current_workspace is not None:
                    workspaces.append(current_workspace)
                current_workspace = {"name": value, "host": ""}
            elif current_workspace is not None and field.lower() == "host":
                current_workspace["host"] = value
        if current_workspace is not None:
            workspaces.append(current_workspace)

        if not workspaces:
            self.log("No workspaces found on P4 server.", QSLauncherColor.YellowWarning)
            return False

        # Host 为空 → 可在任意机器使用；Host 匹配本机名 → 锁定到本机
        usable_names = []
        for workspace in workspaces:
            ws_host = workspace["host"]
            if not ws_host or ws_host.lower() == hostname.lower():
                usable_names.append(workspace["name"])

        if not usable_names:
            self.log("No usable workspaces found for this computer.", QSLauncherColor.YellowWarning)
            return False

        current = self.input_client.currentText()
        self.input_client.clear()
        self.input_client.addItems(usable_names)
        # 优先恢复刷新前选中的 workspace；若新列表里找不到（例如手输的自定义名不在其中），
        # 则默认选中拉取到的第一个 workspace，保证下拉框始终有一个有效选择。
        idx = self.input_client.findText(current)
        self.input_client.setCurrentIndex(idx if idx >= 0 else 0)

        self.log(
            f"Loaded {len(usable_names)} workspace(s) for user '{user}' usable on this computer.",
            QSLauncherColor.GreenSuccess,
        )

        return True

    # 从 P4 拉取所有 stream（返回 //depot/... 形式的 stream 路径）并填充源/目标分支下拉框
    def refresh_branches(self):
        self._update_p4_info()
        out, err = self.cli_runner.block_exec(
            "streams",
            [],
            [],
            timeout=30,
        )
        if err:
            err_text = '\n'.join(err)
            self.log(f"Failed to fetch streams: {err_text}", QSLauncherColor.YellowWarning)
            return

        names = []
        for line in out:
            line = line.strip()
            # 默认输出格式: Stream //depot/xxx <type> ...
            if line.startswith("Stream "):
                parts = line.split()
                if len(parts) >= 2:
                    stream_path = parts[1]
                    # 只保留属于 //PGAME_Stream/ 的 stream
                    if "//PGAME_Stream/" in stream_path:
                        names.append(stream_path)

        if not names:
            self.log("No streams found on P4 server.", QSLauncherColor.YellowWarning)
            return

        # 源/目标两个下拉框共用同一份 stream 列表；
        # 优先保留刷新前各自的选择，找不到则默认选中第一个，保证下拉框始终有有效选择。
        for combo in (self.input_src, self.input_tgt):
            current = combo.currentText()
            combo.clear()
            combo.addItems(names)
            idx = combo.findText(current)
            combo.setCurrentIndex(idx if idx >= 0 else 0)

        self.log(f"Loaded {len(names)} stream(s) from P4.", QSLauncherColor.GreenSuccess)

    # 获取干净的stream路径
    def _normalize_stream_path(self, branch_path: str) -> str:
        stream_path = branch_path.strip().strip('"')
        if not stream_path:
            return ""

        if '@' in stream_path:
            stream_path = stream_path.split('@', 1)[0]
        if '#' in stream_path:
            stream_path = stream_path.split('#', 1)[0]
        if stream_path.endswith('/...'):
            stream_path = stream_path[:-4]
        elif stream_path.endswith('...'):
            stream_path = stream_path[:-3]

        return stream_path.rstrip('/')

    # 因为直接通过stream名读取过滤目录配置了，所以这个函数暂时用不上
    def _parse_stream_paths(self, output: list) -> list:
        """
        解析 p4 stream -o 输出的 Paths 段，返回格式：
        [
            {'type': 'share', 'path': '...'},
            {'type': 'isolate', 'path': 'TKGame/...'},
            ...
        ]
        """
        path_list = []
        in_paths_section = False

        for raw_line in output:
            line = raw_line.rstrip()
            stripped = line.strip()

            if not in_paths_section:
                if stripped == 'Paths:':
                    in_paths_section = True
                continue

            if not stripped:
                continue

            if not raw_line.startswith('\t') and raw_line == stripped and stripped.endswith(':'):
                break

            if stripped.startswith('##'):
                continue

            parts = stripped.split(None, 1)
            if len(parts) == 2:
                path_type = parts[0]  # share / isolate / import / exclude
                path_val = parts[1].strip()
                path_list.append({'type': path_type, 'path': path_val})
            else:
                path_list.append({'type': 'unknown', 'path': stripped})

        return path_list

    # 因为直接通过stream名读取过滤目录配置了，所以这个函数暂时用不上
    def get_stream_paths(self, branch_path: str) -> list:
        stream_path = self._normalize_stream_path(branch_path)
        if not stream_path:
            self.log('Skip fetching stream paths: branch path is empty.', QSLauncherColor.YellowWarning)
            return []

        out, err = self.cli_runner.block_exec(
            'stream',
            ['-o'],
            [f'"{stream_path}"'],
            timeout=60
        )

        if err:
            err_text = '\n'.join(err)
            self.log(f'Failed to fetch paths for {stream_path}: {err_text}', QSLauncherColor.YellowWarning)
            return []

        path_list = self._parse_stream_paths(out)

        if path_list:
            self.log(f'Paths for {stream_path} ({len(path_list)}):', QSLauncherColor.BlueInfo)
            for item in path_list:
                self.log(f'  {item["type"]}: {item["path"]}', QSLauncherColor.Gray)
        else:
            self.log(f'No paths found for {stream_path}.', QSLauncherColor.YellowWarning)

        return path_list

    # 因为直接通过stream名读取过滤目录配置了，所以这个函数暂时用不上
    def _build_exclude_paths(self, src_branch: str, src_paths: list) -> list:
        """
        根据 src_paths 里的 isolate 条目，构造要排除的完整路径列表。
        src_branch: 源分支路径，如 '//PGAME_Stream/develop/...'
        src_paths: [{type: 'isolate', path: 'TKGame/...'}, ...]
        返回: ['//PGAME_Stream/develop/TKGame/...', ...]
        """
        base = self._normalize_stream_path(src_branch)
        exclude_list = []

        for item in src_paths:
            if item['type'] == 'isolate':
                rel_path = item['path']
                full_path = f"{base}/{rel_path}"
                exclude_list.append(full_path)

        return exclude_list

    # 查找所有待合并的changelist
    def refresh_list(self):
        self._update_p4_info()
        src = self.input_src.currentText().strip()
        tgt = self.input_tgt.currentText().strip()

        if not src or not tgt:
            QMessageBox.warning(self, "Warning", "Please enter both source and target branch paths.")
            return

        src_stream = self._normalize_stream_path(src)
        tgt_stream = self._normalize_stream_path(tgt)

        self.btn_refresh.setEnabled(False)
        self.log(f"Fetching interchanges by stream from {src_stream} to parent {tgt_stream}...", QSLauncherColor.BlueInfo)

        def fetch_task():
            result = self.cli_runner.block_exec(
                "interchanges",
                ["-l", "-S", f'"{src_stream}"', "-P", f'"{tgt_stream}"'],
                []
            )
            out, err = result

            if err:
                err_text = '\n'.join(err).lower()
                if 'no such file' in err_text or 'no such stream' in err_text:
                    self.log(f"Error: {err}", QSLauncherColor.RedError)
                    return []

            return self._parse_interchanges(out)

        def on_fetch_done(result):
            self.changelists = result
            self._update_list_widget(self.changelists) # 更新到UI
            self.btn_refresh.setEnabled(True)
            if len(self.changelists) > 0:
                self.log(f"Found {len(self.changelists)} pending changelist(s)", QSLauncherColor.GreenSuccess)
            else:
                self.log("No pending interchanges found", QSLauncherColor.YellowWarning)

        on_fetch_done(fetch_task())

    def _parse_interchanges(self, output: list) -> list:
        """
        解析 p4 interchanges -l 命令输出
        
        输入格式示例：
        Change 12345 on 2024/01/15 by user1@workspace *pending*
            Fix login bug
            
            Added new authentication method
            
        Change 12346 on 2024/01/16 by user2@workspace *pending*
            Add new feature
        
        返回：ChangeListInfo 列表
        """
        changelists = []
        if not output:
            return changelists

        current_cl = None # 当前正在读的ChangeListInfo对象
        description_lines = [] # 该对象的submit description文本（可能是多行所以用这个）

        for line in output:
            line = line.strip()
            # 每个 changelist 以 "Change " 开头的行表示新 changelist 的开始
            if line.startswith("Change "):
                # 如果已有 changelist，保存其submit description
                if current_cl:
                    current_cl.description = ' '.join(description_lines).strip()
                    changelists.append(current_cl)

                # 解析 Change 行：Change <cl_number> on <date> by <user>...
                parts = line.split()
                cl_number = parts[1] if len(parts) > 1 else ""

                user = ""
                date = ""
                # 遍历 parts 查找 'by' 和 'on' 关键字提取用户和日期
                for i, part in enumerate(parts):
                    if part == "by" and i + 1 < len(parts):
                        raw_user = parts[i + 1].strip('*').strip()  # 例如 user@workspace
                        user = raw_user.split('@', 1)[0]
                    if part == "on" and i + 1 < len(parts):
                        date = parts[i + 1]

                # 创建新的 ChangeListInfo 对象
                current_cl = ChangeListInfo(cl_number, "", user, date)
                description_lines = []  # 重置描述行列表
            elif current_cl and line:
                # 非 Change 开头的行是 changelist 的描述内容
                description_lines.append(line)

        # 保存最后一个 changelist
        if current_cl:
            current_cl.description = ' '.join(description_lines).strip()
            changelists.append(current_cl)

        return changelists

    def _create_cl_row_widget(self, cl):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(8, 4, 8, 4)
        row_layout.setSpacing(10)

        check_box = QCheckBox()
        check_box.setObjectName("clCheckBox")
        check_box.setToolTip(f"Select CL {cl.cl_number}")
        check_box.setFixedWidth(20)
        row_layout.addWidget(check_box)

        cl_label = QLabel(f"CL {cl.cl_number}")
        cl_label.setFixedWidth(110)
        cl_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row_layout.addWidget(cl_label)

        user_label = QLabel(cl.user)
        user_label.setFixedWidth(180)
        user_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row_layout.addWidget(user_label)

        date_label = QLabel(cl.date)
        date_label.setFixedWidth(110)
        date_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row_layout.addWidget(date_label)

        desc_text = cl.description if cl.description else "<No Description>"
        desc_label = QLabel(desc_text)
        desc_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # desc_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        desc_label.setToolTip(f"CL: {cl.cl_number}\nUser: {cl.user}\nDate: {cl.date}\nDescription: {cl.description}")
        row_layout.addWidget(desc_label)

        return row_widget

    def _update_list_widget(self, changelists: list):
        self.cl_list.clear()

        for i, cl in enumerate(changelists):
            item = QListWidgetItem()
            item.setData(0x0100, cl.cl_number)

            row_widget = self._create_cl_row_widget(cl)
            item.setSizeHint(row_widget.sizeHint())

            self.cl_list.addItem(item)
            self.cl_list.setItemWidget(item, row_widget)

    def _get_item_checkbox(self, item: QListWidgetItem):
        row_widget = self.cl_list.itemWidget(item)
        if row_widget is None:
            return None
        return row_widget.findChild(QCheckBox, "clCheckBox")

    def _get_checkbox_by_index(self, index: int):
        item = self.cl_list.item(index)
        if item is None:
            return None
        return self._get_item_checkbox(item)

    def _set_item_checked(self, index: int, checked: bool):
        check_box = self._get_checkbox_by_index(index)
        if check_box is not None:
            check_box.setChecked(checked)

    def _is_item_checked(self, index: int) -> bool:
        check_box = self._get_checkbox_by_index(index)
        return check_box is not None and check_box.isChecked()

    def _get_current_p4_user(self) -> str:
        self._update_p4_info()
        out, err = self.cli_runner.block_exec("info", [], [], timeout=30)

        if err:
            err_text = '\n'.join(err)
            self.log(f"Failed to get current p4 user: {err_text}", QSLauncherColor.YellowWarning)
            return ""

        for line in out:
            stripped = line.strip()
            lower_line = stripped.lower()
            if lower_line.startswith("user name:"):
                return stripped.split(':', 1)[1].strip()
            if lower_line.startswith("user:"):
                return stripped.split(':', 1)[1].strip()

        self.log("Unable to parse current p4 user from 'p4 info'.", QSLauncherColor.YellowWarning)
        return ""

    def select_mine(self):
        if not self.changelists:
            QMessageBox.information(self, "Info", "No changelists in list. Please refresh first.")
            return

        current_user = self._get_current_p4_user().strip()
        if not current_user:
            QMessageBox.warning(self, "Warning", "Cannot get current p4 user. Please check P4 config/login.")
            return

        filtered_changelists = [cl for cl in self.changelists if cl.user.strip() == current_user]
        self._update_list_widget(filtered_changelists)

        self.log(f"Filter Mine: user={current_user}, show {len(filtered_changelists)} changelist(s).", QSLauncherColor.BlueInfo)

    def _filter_by_desc_keywords(self, keywords: list) -> tuple:
        """
        按关键字匹配 CL 描述：命中任意一个关键字即保留，
        结果保持 self.changelists 的原顺序且不重复。
        返回 (命中的 CL 列表, {关键字: 命中数})。
        """
        hit_counts = {k: 0 for k in keywords}

        filtered_changelists = []
        matched_cl_numbers = set()

        for cl in self.changelists:
            desc = cl.description or ""
            for k in keywords:
                if k not in desc:
                    continue
                hit_counts[k] += 1
                if cl.cl_number not in matched_cl_numbers:
                    matched_cl_numbers.add(cl.cl_number)
                    filtered_changelists.append(cl)

        return filtered_changelists, hit_counts

    def filter_by_description(self):
        keyword = self.input_desc_filter.text().strip()
        if not keyword:
            self.log("Description filter is empty, showing all changelists.", QSLauncherColor.YellowWarning)
            return

        filtered_changelists, _ = self._filter_by_desc_keywords([keyword])
        self._update_list_widget(filtered_changelists)

        self.log(f"Filter by Desc: keyword='{keyword}', show {len(filtered_changelists)} changelist(s).", QSLauncherColor.BlueInfo)

    def filter_by_story(self):
        """
        按 TAPD 需求单过滤：
        1. 用输入的父 story id 调 FindChildrenIDs 递归查出所有子需求（含自身）；
        2. 对每个 story id 用 "story=<id>" 作为关键字去匹配 CL 描述；
        3. 命中任意一个关键字的 CL 都会保留（保持原有列表顺序、不重复）。
        """
        if not self.changelists:
            QMessageBox.information(self, "Info", "No changelists in list. Please refresh first.")
            return

        story_id = self.input_story_filter.text().strip()
        if not story_id:
            self.log("Story id is empty, skip story filter.", QSLauncherColor.YellowWarning)
            return

        self.btn_filter_story.setEnabled(False)
        self.log(f"Fetching child stories of story {story_id} from TAPD...", QSLauncherColor.BlueInfo)

        try:
            story_ids = FindChildrenIDs(story_id)
        except Exception as e:
            self.log(f"Failed to fetch child stories of {story_id}: {e}", QSLauncherColor.RedError)
            QMessageBox.warning(self, "Warning", f"Failed to fetch child stories:\n{e}")
            return
        finally:
            self.btn_filter_story.setEnabled(True)

        if not story_ids:
            self.log(f"No story found for id {story_id}.", QSLauncherColor.YellowWarning)
        else:
            self.log(f"Found {len(story_ids)} story(ies) (including itself): {', '.join(story_ids)}",
                    QSLauncherColor.BlueInfo)

        # 每个 story 对应一个 "story=<id>" 关键字，复用描述关键字匹配
        keywords = [f"story={sid}" for sid in story_ids]
        filtered_changelists, hit_counts = self._filter_by_desc_keywords(keywords)
        for keyword in keywords:
            self.log(f"  {keyword}: {hit_counts.get(keyword, 0)} changelist(s) matched.", QSLauncherColor.Gray)

        self._update_list_widget(filtered_changelists)
        self.log(f"Filter Story: root story={story_id}, show {len(filtered_changelists)} changelist(s).",
                 QSLauncherColor.BlueInfo)

    def _parse_ext_filter(self) -> list:
        """将后缀输入框的逗号分隔文本解析成小写后缀集合，如 ['.cpp', '.h']。"""
        text = self.input_ext_filter.text().strip()
        if not text:
            return []
        exts = []
        for part in text.split(','):
            p = part.strip().lower()
            if not p:
                continue
            if not p.startswith('.'):
                p = '.' + p
            exts.append(p)
        return exts

    def _get_cl_matching_files(self, cl_number: str, exts: list,
                                src_stream: str, tgt_stream: str) -> list:
        """
        取指定 CL 中、后缀在 exts 内的文件，并映射成目标分支的 depot 路径列表
        （带 @cl,@cl 修订范围）。
        通过 p4 files @=<cl> 取该 CL 涉及的文件，解析 depot 路径后缀进行筛选。
        """
        out, err = self.cli_runner.block_exec(
            "files",
            [],
            [f"@={cl_number}"],
            timeout=60
        )
        if err:
            # 取不到文件信息时，返回空列表
            self.log(f"Cannot read files for CL {cl_number}: {err}",
                     QSLauncherColor.YellowWarning)
            return []

        src_prefix = src_stream.rstrip('/') + '/'
        tgt_prefix = tgt_stream.rstrip('/') + '/'

        matched = []
        for line in out:
            # p4 files 输出形如: //depot/.../foo.cpp#3 edit
            path = line.split('#', 1)[0].strip()
            ext = os.path.splitext(path)[1].lower()
            if ext not in exts:
                continue

            # 只处理源 stream 下的文件，并把前缀替换成目标 stream。
            if not path.startswith(src_prefix):
                self.log(f"  Skip file not under source stream: {path}",
                         QSLauncherColor.Gray)
            else:
                target_path = tgt_prefix + path[len(src_prefix):]
                # 携带 @cl,@cl 限定为本次 CL 的修订，确保只 merge 该 CL 改动的版本。
                matched.append(f"{target_path}@{cl_number},@{cl_number}")
        return matched

    def select_all(self):
        for i in range(self.cl_list.count()):
            self._set_item_checked(i, True)

    def deselect_all(self):
        for i in range(self.cl_list.count()):
            self._set_item_checked(i, False)

    def get_selected_cls(self) -> list:
        selected = []
        for i in range(self.cl_list.count()):
            if self._is_item_checked(i):
                item = self.cl_list.item(i)
                cl_number = item.data(0x0100)
                selected.append(cl_number)
        return sorted(selected, key=lambda x: int(x) if x.isdigit() else 0) # cl号从小到大排序

    def start_merge(self):
        selected_cls = self.get_selected_cls()

        if not selected_cls:
            QMessageBox.warning(self, "Warning", "Please select at least one changelist to merge.")
            return

        src = self.input_src.currentText().strip()
        tgt = self.input_tgt.currentText().strip()
        auto_submit = self.check_auto_submit.isChecked()

        reply = QMessageBox.question(
            self,
            "Confirm Merge",
            f"Merge {len(selected_cls)} changelist(s) from:\n{src}\nto:\n{tgt}\n\nAuto submit: {'Yes' if auto_submit else 'No'}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        self._update_p4_info()
        self.btn_merge.setEnabled(False)
        self.btn_refresh.setEnabled(False)

        self.log("=" * 60, QSLauncherColor.DarkYellow)
        self.log(f"Starting serial merge of {len(selected_cls)} changelist(s)", QSLauncherColor.LightGreen)
        self.log("=" * 60, QSLauncherColor.DarkYellow)

        # 串行执行：将待合并 CL 放入队列，逐个处理，前一个完成后再处理下一个
        self._merge_queue = list(selected_cls)
        self._merge_src = src
        self._merge_tgt = tgt
        self._merge_auto_submit = auto_submit
        self._merge_success = 0
        self._merge_fail = 0

        self._run_next_merge()

    def _run_next_merge(self):
        """串行处理队列中的下一个 changelist。"""
        if not self._merge_queue:
            self._finish_merge()
            return

        cl = self._merge_queue.pop(0)
        self.log("")
        self.log(f"=== Processing CL {cl} ===", QSLauncherColor.BlueInfo)

        result = self._merge_single_cl(
            cl, self._merge_src, self._merge_tgt, self._merge_auto_submit
        )

        if result:
            self._merge_success += 1
            self.log(f"CL {cl} merged successfully!", QSLauncherColor.GreenSuccess)
        else:
            self._merge_fail += 1
            self.log(f"CL {cl} merge failed!", QSLauncherColor.RedError)
            self._finish_merge()
            return

        # 处理下一个：通过 QTimer 让出事件循环，保证 UI 可响应
        QTimer.singleShot(0, self._run_next_merge)

    def _finish_merge(self):
        self.btn_merge.setEnabled(True)
        self.btn_refresh.setEnabled(True)
        self.log("")
        self.log("=" * 60, QSLauncherColor.DarkYellow)
        self.log("Merge process completed.", QSLauncherColor.LightGreen)
        self.log("=" * 60, QSLauncherColor.DarkYellow)
        # 完成弹窗
        msg = (
            f"Merge process completed.\n\n"
            f"Success: {self._merge_success}  Failed: {self._merge_fail}\n\n"
            f"Please switch to the target branch's workspace to verify the result:\n"
            f"{self._merge_tgt}"
        )
        QMessageBox.information(self, "Merge Complete", msg)

    def _merge_single_cl(self, cl: str, src: str, tgt: str, auto_submit: bool) -> bool:
        self.log(f"Merging CL {cl} from {src} to {tgt}...", QSLauncherColor.Gray)

        src_stream = self._normalize_stream_path(src)
        tgt_stream = self._normalize_stream_path(tgt)

        # 后缀过滤：勾选且填写了后缀时，只 merge 指定后缀的文件，其余文件不进入 pending 列表。
        if self.check_ext_filter.isChecked():
            exts = self._parse_ext_filter()
            if exts:
                file_args = self._get_cl_matching_files(cl, exts, src_stream, tgt_stream)
                if not file_args:
                    self.log(f"CL {cl}: no files with extension {exts}, skip merge.",
                             QSLauncherColor.YellowWarning)
                    return True
                self.log(f"CL {cl}: {len(file_args)} file(s) with extension {exts} will be merged.",
                         QSLauncherColor.BlueInfo)
            else:
                # 勾选了但未填写后缀，退化为整 CL 合并。
                file_args = [f"@{cl},@{cl}"]
        else:
            file_args = [f"@{cl},@{cl}"]

        out, err = self.cli_runner.block_exec(
            "merge",
            ["-F", "-Af", "-S", f'"{src_stream}"', "-P", f'"{tgt_stream}"'],
            file_args,
            timeout=120
        )

        merge_output = '\n'.join(out + err)
        if 'already integrated' in merge_output or 'already committed' in merge_output:
            self.log(f"CL {cl}: {merge_output}", QSLauncherColor.YellowWarning)
            return True
        elif 'no such file' in merge_output:
            # # depot 路径不存在（写错了或没权限）
            self.log(f"CL {cl} failed: {merge_output}", QSLauncherColor.RedError)
            return False
        elif 'no file(s)' in merge_output or 'nothing to merge' in merge_output or 'nothing to copy' in merge_output:
            # 路径存在，但该 CL 的改动在目标侧已存在或无需合并
            self.log(f"CL {cl}: {merge_output}", QSLauncherColor.YellowWarning)
            return True
        elif 'must use a stream view' in merge_output.lower():
            self.log(f"CL {cl} failed: {merge_output}", QSLauncherColor.RedError)
            return False
        elif 'a revision range cannot be used here' in merge_output.lower():
            self.log(f"CL {cl} failed: {merge_output}", QSLauncherColor.RedError)
            return False
        else:
            self.log(f"CL {cl}: {merge_output}", QSLauncherColor.GreenSuccess)

        self.log("Resolving files...", QSLauncherColor.Gray)
        out, err = self.cli_runner.block_exec(
            "resolve",
            ["-am"],
            [],
            timeout=300
        )

        if err:
            err_text = '\n'.join(err)
            if 'conflicting' in err_text.lower() or 'resolve skipped' in err_text.lower():
                self.log("Conflicts detected! Manual resolve required.", QSLauncherColor.YellowWarning)
                self.log("Please resolve conflicts in P4V or run 'p4 resolve' manually.", QSLauncherColor.YellowWarning)
                return False

        if not auto_submit:
            self.log(f"CL {cl} integrated. Please submit manually in P4V.", QSLauncherColor.LightGreen)
            return True

        self.log("Submitting...", QSLauncherColor.Gray)
        out, err = self.cli_runner.block_exec(
            "submit",
            ["-d", f'"Merge CL {cl} from {src} to {tgt}"'],
            [],
            timeout=300
        )

        # 合并 stdout + stderr 统一判断提交结果
        submit_output = '\n'.join(out + err)
        if 'submitted' in submit_output:
            self.log(f"CL {cl} submitted successfully.", QSLauncherColor.GreenSuccess)
            return True
        elif 'no files to submit' in submit_output:
            self.log(f"CL {cl}: {submit_output}", QSLauncherColor.YellowWarning)
            return True
        else:
            self.log(f"Submit failed: {submit_output}", QSLauncherColor.RedError)
            return False

    def closeEvent(self, event):
        self._save_settings()
        event.accept()


class ChangeListInfo:
    def __init__(self, cl_number: str, description: str = "", user: str = "", date: str = ""):
        self.cl_number = cl_number
        self.description = description
        self.user = user
        self.date = date


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = P4InterchangesTool()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
