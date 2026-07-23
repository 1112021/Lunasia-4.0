# -*- coding: utf-8 -*-
import sys
import os
import datetime
import threading
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLineEdit, QPushButton, 
                             QLabel, QProgressBar, QSplitter, QGroupBox, 
                             QFormLayout, QStatusBar, QFileDialog, QDialog, QSizePolicy,
                             QMenu, QAction, QSystemTrayIcon, QMessageBox,
                             QScrollArea, QFrame)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QSize, QSettings
from PyQt5.QtGui import QFont, QPixmap, QIcon, QCursor, QColor

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False
    print("⚠️ keyboard 库未安装，全局快捷键功能将不可用")

from config import save_config
from ai_agent import AIAgent
from app_icon import try_set_window_icon, get_application_icon
from ui_dialogs import SettingsDialog, MemoryLakeDialog, MCPToolsDialog
from file_analysis_tool import FileAnalysisTool
from voice_input import record_to_wav, recognize_wav, is_voice_input_available
from combined_attachments import (
    CombinedAttachments,
    MAX_FILES,
    MAX_IMAGES,
    classify_path,
    format_user_chat_line,
    validate_video_for_pending,
)
from chat_code_widgets import (
    ATTACHMENT_MENU_STYLESHEET,
    ChatTextSegment,
    CodeBlockCard,
    ReplyActionBar,
    UserMessageActionBar,
)
from chat_fence_parser import StreamingFenceParser
from workflow_panel import WorkflowPanel

class AIAgentApp(QMainWindow):
    """露尼西亚AI助手主窗口"""

    @staticmethod
    def _request_app_quit():
        """结束 Qt 事件循环；在 async/Playwright 收尾完成后再 quit（略延迟便于释放子进程管道）。"""
        app = QApplication.instance()
        if app is None:
            return

        def _do():
            a = QApplication.instance()
            if a is not None:
                a.quit()

        QTimer.singleShot(75, _do)

    # 定义信号
    response_ready = pyqtSignal(str)
    response_stream_chunk = pyqtSignal(str)  # 流式显示：每次为当前累积的完整内容
    voice_result_ready = pyqtSignal(str, str)  # (text, error_message) 从语音识别线程发到主线程
    response_status_message = pyqtSignal(str)  # 读屏等场景的即时状态提示（如「正在截屏并查看屏幕…」）
    workflow_step_received = pyqtSignal(str, str, str)  # key, concise title, phase
    security_timeout_extend = pyqtSignal()  # UI 安全门命中后于主线程延长超时
    user_notice = pyqtSignal(str)
    
    def __init__(self, config, startup_argument_tray=False):
        super().__init__()
        try_set_window_icon(self)
        self.config = config
        self._startup_argument_tray = bool(startup_argument_tray)
        self.agent = AIAgent(config)
        self.agent.on_screen_analyze_start = lambda: self.response_status_message.emit("正在截屏并查看屏幕…")

        from llm_router import set_llm_status_callback
        from llm_local_service import schedule_local_startup

        def _llm_status(msg: str) -> None:
            QTimer.singleShot(0, lambda m=msg: self.statusBar().showMessage(m, 8000))

        set_llm_status_callback(_llm_status)
        schedule_local_startup(config, _llm_status)
        
        # 初始化文件分析工具
        self.file_analyzer = FileAnalysisTool(config)
        
        # 设置首次介绍标记
        self.first_introduction_given = False
        self.waiting_for_first_response = False
        
        # 初始化UI
        self.init_ui()
        
        # 应用窗口透明度设置
        self.apply_transparency()
        
        # 连接信号
        self.response_ready.connect(self.update_ui_with_response)
        self.response_stream_chunk.connect(self._on_stream_chunk)
        self.voice_result_ready.connect(self._apply_voice_result)
        self.response_status_message.connect(self._on_response_status_message)
        self.workflow_step_received.connect(self._on_workflow_step)
        self.security_timeout_extend.connect(self._on_security_timeout_extend)
        self.user_notice.connect(
            lambda message: self.statusBar().showMessage(message, 10000)
        )
        self.agent.workflow_event_callback = (
            lambda key, title, phase: self.workflow_step_received.emit(key, title, phase)
        )
        self._ui_security_gate_active = False
        self._workflow_panel = None
        self._workflow_started_at = None
        self._workflow_insert_index = None
        # 流式显示状态（主线程）
        self._streaming_active = False
        self._streaming_renderer = None
        self._streaming_seen_content = ""
        # 流式刷新节流：合并高频 chunk，减轻主线程压力
        self._stream_pending_content = ""
        self._stream_flush_scheduled = False
        
        # 任意占用 AIAgent 的后台任务单飞（聊天/上传分析等互斥，避免多线程竞态与 UI 信号积压）
        self._agent_busy = False
        self._active_turn_widgets = None
        self._active_request = None
        self._latest_turn = None
        self._latest_action_bar = None
        self._latest_user_turn = None
        self._latest_user_action_bar = None
        self._editing_user_widget = None
        self._edit_restart_pending = None
        self._stop_requested = False

        # 组合发送：待发送附件
        self._pending_images = []
        self._pending_video = None
        self._pending_files = []
        
        # 启动状态更新定时器
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(1000)  # 每秒更新一次状态
        
        # 设置全局快捷键
        self.setup_global_shortcuts()
        
        self._force_quit = False
        self._in_tray = False
        self._tray_icon = None
        self._tray_menu = None
        self._normal_window_flags = None
        self._setup_system_tray()
        self._restore_window_geometry_from_settings()
        
        # 检查是否是第一次运行，如果是则进行自我介绍
        self.check_first_run_and_introduce()
        # --startup-tray 时由 main.py 在首帧调度 _apply_cli_startup_tray，避免先 show() 再托盘导致闪窗

    def _apply_cli_startup_tray(self):
        """命令行 --startup-tray：开机进托盘（托盘不可用时再显示主窗口）。"""
        try:
            if not QSystemTrayIcon.isSystemTrayAvailable() or self._tray_icon is None:
                self.show()
                return
            self._hide_to_tray()
        except Exception as e:
            print(f"⚠️ 开机进托盘失败: {e}")
            try:
                self.show()
            except Exception:
                pass

    def raise_from_second_instance(self):
        """第二实例请求：置顶/从托盘恢复主窗口。"""
        try:
            if getattr(self, "_in_tray", False):
                self._show_from_tray()
            else:
                if self.isMinimized():
                    self.showNormal()
                if not self.isVisible():
                    self.show()
                self.raise_()
                self.activateWindow()
            if hasattr(self, "input_edit"):
                self.input_edit.setFocus()
        except Exception as e:
            print(f"⚠️ 激活主窗口失败: {e}")

    def _stop_active_progress_timers(self):
        """停止进度与超时定时器（须在主线程调用）。"""
        pt = getattr(self, "progress_timer", None)
        if pt is not None:
            try:
                pt.stop()
            except Exception:
                pass
        tt = getattr(self, "timeout_timer", None)
        if tt is not None:
            try:
                tt.stop()
            except Exception:
                pass
    
    def _try_begin_agent_work(self):
        """若当前无占用 Agent 的任务则占用并返回 True，否则返回 False。"""
        if getattr(self, "_agent_busy", False):
            return False
        self._agent_busy = True
        return True

    def _set_generation_button(self, generating: bool):
        if not hasattr(self, "send_btn"):
            return
        self.send_btn.setEnabled(True)
        self.send_btn.setText("停止" if generating else "发送")
        self.send_btn.setToolTip("停止生成" if generating else "发送消息")
        self.send_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #f38ba8;
                color: #1e1e2e;
                border-radius: 15px;
                padding: 10px 16px;
                font-weight: bold;
                min-height: 20px;
            }
            QPushButton:hover:enabled { background-color: #eba0ac; }
            QPushButton:disabled { background-color: #7f5563; color: #cdd6f4; }
            """
            if generating
            else """
            QPushButton {
                background-color: #89b4fa;
                color: #1e1e2e;
                border-radius: 15px;
                padding: 10px 20px;
                font-weight: bold;
                min-height: 20px;
            }
            QPushButton:hover { background-color: #74c7ec; }
            """
        )
        if generating:
            # “停止”暂不绑定快捷键；只响应明确的按钮点击。
            self.send_btn.setShortcut("")
        elif self.config.get("send_key_mode", "Ctrl+Enter") == "Enter":
            self.send_btn.setShortcut("Return")
        else:
            self.send_btn.setShortcut("Ctrl+Return")

    def _on_send_button_clicked(self):
        if getattr(self, "_agent_busy", False):
            self.stop_generation()
        else:
            self.send_message()

    def stop_generation(self):
        """Cooperatively stop output and skip framework work not yet started."""
        if not getattr(self, "_agent_busy", False) or self._stop_requested:
            return
        self._stop_requested = True
        self.agent.cancel_generation()
        self.send_btn.setEnabled(False)
        self.progress_bar.setFormat("正在停止…")
        self.statusBar().showMessage(
            "已请求停止；当前正在执行的工具结束后将跳过后续任务。", 5000
        )
    
    def apply_transparency(self):
        """应用窗口透明度设置"""
        try:
            transparency = self.config.get("window_transparency", 100)
            if transparency < 100:
                # 将百分比转换为0-1之间的值
                opacity = transparency / 100.0
                self.setWindowOpacity(opacity)
                print(f"✅ 窗口透明度已设置为 {transparency}%")
            else:
                # 100%表示完全不透明
                self.setWindowOpacity(1.0)
        except Exception as e:
            print(f"⚠️ 设置窗口透明度失败: {str(e)}")
    
    def update_transparency(self, value):
        """实时更新窗口透明度（用于设置对话框的实时预览）"""
        try:
            if value < 100:
                # 将百分比转换为0-1之间的值
                opacity = value / 100.0
                self.setWindowOpacity(opacity)
            else:
                # 100%表示完全不透明
                self.setWindowOpacity(1.0)
        except Exception as e:
            print(f"⚠️ 实时更新透明度失败: {str(e)}")

    def init_ui(self):
        """初始化用户界面"""
        self.setWindowTitle("露尼西亚AI助手")
        # 增加一点点高度和宽度，让按钮对齐并保持比例
        # 原来：1300x800，现在：1350x850
        # 聊天区域：1000px，右侧区域：350px，高度增加50px
        window_width = 1350  # 增加50px宽度，主要给聊天区域
        window_height = 850  # 增加50px高度，让按钮向下移动对齐
        
        self.setGeometry(100, 100, window_width, window_height)
        
        # 设置窗口尺寸策略，固定大小不可拖拽
        from PyQt5.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedSize(window_width, window_height)  # 固定窗口大小
        
        # 设置窗口样式（含全局 QToolTip：深底白字，保证可读）
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e2e;
                color: #cdd6f4;
            }
            QToolTip {
                background-color: #313244;
                color: #ffffff;
                border: 1px solid #585b70;
                border-radius: 4px;
                padding: 8px 10px;
                font-size: 13px;
            }
        """)
        
        # 创建中央部件
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # 聊天区域 (占用3/4宽度)
        chat_widget = QWidget()
        chat_widget.setStyleSheet("background-color: #1e1e2e; border-radius: 10px;")
        chat_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        chat_layout = QVBoxLayout()
        chat_layout.setSpacing(10)
        chat_layout.setContentsMargins(10, 10, 10, 10)
        
        # 连续聊天记录。普通文字保持无框；仅代码围栏会插入独立代码卡片。
        self.chat_history = QScrollArea()
        self.chat_history.setWidgetResizable(True)
        self.chat_history.setFrameShape(QFrame.NoFrame)
        self.chat_history.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chat_history.setStyleSheet(
            "QScrollArea { background-color: #1e1e2e; border: none; }"
            "QScrollBar:vertical { background: #1e1e2e; width: 10px; }"
            "QScrollBar::handle:vertical { background: #45475a; border-radius: 5px; min-height: 24px; }"
        )
        self.chat_transcript = QWidget()
        self.chat_transcript.setStyleSheet("background-color: #1e1e2e;")
        self.chat_transcript_layout = QVBoxLayout(self.chat_transcript)
        self.chat_transcript_layout.setContentsMargins(10, 10, 10, 10)
        # 保持原 QTextEdit 连续文本的对话间距；代码卡本身不额外拉开上下文本。
        self.chat_transcript_layout.setSpacing(0)
        self.chat_transcript_layout.addStretch(1)
        self.chat_history.setWidget(self.chat_transcript)
        
        # 输入区域（待发送附件条 + 单行输入）
        input_column = QVBoxLayout()
        input_column.setSpacing(6)

        # 待发送附件条：DeepSeek 风格卡片（可横向滚动，单项删除）
        self.pending_strip = QWidget()
        pending_outer = QHBoxLayout(self.pending_strip)
        pending_outer.setContentsMargins(4, 0, 4, 0)
        pending_outer.setSpacing(6)

        self.pending_scroll = QScrollArea()
        self.pending_scroll.setWidgetResizable(True)
        self.pending_scroll.setFrameShape(QFrame.NoFrame)
        self.pending_scroll.setFixedHeight(64)
        self.pending_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.pending_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.pending_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self.pending_cards_host = QWidget()
        self.pending_cards_host.setStyleSheet("background: transparent;")
        self.pending_cards_layout = QHBoxLayout(self.pending_cards_host)
        self.pending_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.pending_cards_layout.setSpacing(8)
        self.pending_cards_layout.addStretch(1)
        self.pending_scroll.setWidget(self.pending_cards_host)

        self.clear_pending_btn = QPushButton("清空")
        self.clear_pending_btn.setFixedHeight(24)
        self.clear_pending_btn.clicked.connect(self._clear_pending_attachments)
        self.clear_pending_btn.setStyleSheet(
            "QPushButton { background-color: #45475a; color: #cdd6f4; border-radius: 8px; padding: 2px 10px; }"
            "QPushButton:hover { background-color: #585b70; }"
        )
        pending_outer.addWidget(self.pending_scroll, 1)
        pending_outer.addWidget(self.clear_pending_btn, 0, Qt.AlignBottom)
        self.pending_strip.setVisible(False)

        input_layout = QHBoxLayout()
        input_layout.setSpacing(10)
        
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("输入消息...")
        self.input_edit.returnPressed.connect(self.send_message_shortcut)
        self.input_edit.setStyleSheet("""
            QLineEdit {
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 15px;
                padding: 10px 15px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 2px solid #89b4fa;
            }
        """)

        # 语音输入按钮（长按录音，松开识别）：默认无背景，录音时填充颜色
        self._voice_stop_event = None
        self._voice_record_thread = None
        self._mic_btn_style_idle = """
            QPushButton {
                background-color: #ffffff;
                color: #1e1e1e;
                border: 1px solid #45475a;
                border-radius: 15px;
                padding: 8px 12px;
                font-weight: bold;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: rgba(166, 227, 161, 0.5);
                border: 1px solid #585b70;
            }
        """
        self._mic_btn_style_active = """
            QPushButton {
                background-color: #a6e3a1;
                color: #1e1e1e;
                border-radius: 15px;
                padding: 8px 12px;
                font-weight: bold;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #94e2d5;
            }
        """
        self.mic_btn = QPushButton()
        mic_icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "mic_icon.png")
        if os.path.isfile(mic_icon_path):
            self.mic_btn.setIcon(QIcon(mic_icon_path))
            self.mic_btn.setIconSize(QSize(24, 24))
        else:
            self.mic_btn.setText("🎤")
        self.mic_btn.setToolTip("长按录音，松开后识别为文字（需配置语音识别 API 密钥）")
        self.mic_btn.pressed.connect(self._on_voice_pressed)
        self.mic_btn.released.connect(self._on_voice_released)
        self.mic_btn.setStyleSheet(self._mic_btn_style_idle)

        # 文件上传按钮
        upload_btn = QPushButton("➕")
        upload_btn.setToolTip("上传文件")
        upload_btn.clicked.connect(self.show_upload_menu)
        upload_btn.setStyleSheet("""
            QPushButton {
                background-color: #f9e2af;
                color: #1e1e1e;
                border-radius: 15px;
                padding: 8px 12px;
                font-weight: bold;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #e7d19e;
            }
        """)

        self.send_btn = QPushButton("发送")
        # 根据配置设置快捷键
        send_key_mode = self.config.get("send_key_mode", "Ctrl+Enter")
        if send_key_mode == "Enter":
            self.send_btn.setShortcut("Return")
        else:
            self.send_btn.setShortcut("Ctrl+Return")
        self.send_btn.clicked.connect(self._on_send_button_clicked)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #89b4fa;
                color: #1e1e1e;
                border-radius: 15px;
                padding: 10px 20px;
                font-weight: bold;
                min-height: 20px;
            }
            QPushButton:hover {
                background-color: #74c7ec;
            }
        """)

        # 添加进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #45475a;
                border-radius: 5px;
                text-align: center;
                background-color: #313244;
                color: #cdd6f4;
            }
            QProgressBar::chunk {
                background-color: #89b4fa;
                border-radius: 3px;
            }
        """)

        # 创建水平布局，让输入元素与右侧按钮对齐
        input_container = QHBoxLayout()
        input_container.setSpacing(10)
        
        input_container.addWidget(self.input_edit)
        input_container.addWidget(self.mic_btn)
        input_container.addWidget(upload_btn)
        input_container.addWidget(self.send_btn)
        input_container.addWidget(self.progress_bar)

        input_column.addStretch(1)
        input_column.addWidget(self.pending_strip)
        input_column.addLayout(input_container)

        chat_layout.addWidget(self.chat_history, 3)
        chat_layout.addStretch()  # 添加弹性空间，让输入区域向下移动
        chat_layout.addLayout(input_column, 0)
        chat_widget.setLayout(chat_layout)

        # 右侧预留区域 (占用1/4宽度，用于Live2D)
        right_widget = QWidget()
        right_widget.setStyleSheet("background-color: #1e1e2e; border-radius: 10px;")
        right_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        right_layout = QVBoxLayout()
        right_layout.setSpacing(5)  # 进一步减少间距，让半身像更接近状态栏
        right_layout.setContentsMargins(10, 8, 10, 8)  # 减少上下边距，让按钮更接近底部
        right_layout.addStretch()  # 添加弹性空间，让按钮推到底部

        # 状态信息
        status_group = QGroupBox("")
        status_group.setStyleSheet("""
            QGroupBox {
                color: #cdd6f4;
                font-size: 10px;
                border: 1px solid #45475a;
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
                padding-bottom: 10px;
                max-width: 320px;
                min-width: 320px;
                min-height: 120px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 4px 8px;
                background-color: #1e1e2e !important;
                font-size: 12px !important;
                font-weight: bold !important;
                color: #ffffff !important;
                font-family: "Microsoft YaHei", "SimHei", sans-serif !important;
                border: 1px solid #1e1e2e !important;
                border-radius: 3px !important;
                margin-top: 3px !important;
                margin-bottom: 3px !important;
            }
        """)
        status_layout = QFormLayout()
        status_layout.setVerticalSpacing(12)  # 进一步增加垂直间距，配合更大的字体
        status_layout.setHorizontalSpacing(8)  # 增加水平间距，配合更大的字体
        
        # 设置标签样式
        status_layout.setLabelAlignment(Qt.AlignRight)

        # 创建标签样式
        label_style = "color: #cdd6f4; font-size: 14px; font-weight: bold; font-family: 'Microsoft YaHei', 'SimHei', sans-serif;"
        value_style = "color: #a6e3a1; font-size: 14px; font-weight: bold; font-family: 'Microsoft YaHei', 'SimHei', sans-serif;"
        
        # 当前模型
        model_label = QLabel("当前模型:")
        model_label.setStyleSheet(label_style)
        model_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        from llm_spec import get_config_spec
        _main_spec = get_config_spec(self.config, "selected_model", "deepseek-v4-flash")
        self.ai_model = QLabel(_main_spec.display_name())
        self.ai_model.setStyleSheet(value_style)
        status_layout.addRow(model_label, self.ai_model)

        # 记忆系统
        memory_label = QLabel("记忆系统:")
        memory_label.setStyleSheet(label_style)
        memory_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.ai_memory = QLabel("识底深湖")
        self.ai_memory.setStyleSheet(value_style)
        status_layout.addRow(memory_label, self.ai_memory)

        # 预加载应用
        apps_label = QLabel(" 预载应用:")  # 在开头添加一个空格，向右移动一个字节
        apps_label.setStyleSheet(label_style)
        apps_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)  # 确保右对齐和垂直居中
        self.ai_apps = QLabel(f"{getattr(self.agent, 'app_count', 0)}")
        self.ai_apps.setStyleSheet(value_style)
        status_layout.addRow(apps_label, self.ai_apps)

        # 登录位置
        location_label = QLabel("登录位置:")
        location_label.setStyleSheet(label_style)
        location_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.ai_location = QLabel(getattr(self.agent, 'location', '未知'))
        self.ai_location.setStyleSheet(value_style)
        status_layout.addRow(location_label, self.ai_location)

        # 当前时间
        time_label = QLabel("当前时间:")
        time_label.setStyleSheet(label_style)
        time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.ai_time = QLabel("同步中...")
        self.ai_time.setStyleSheet(value_style)
        status_layout.addRow(time_label, self.ai_time)
        
        # 启动时间同步
        self.sync_time()

        status_group.setLayout(status_layout)


        # 露尼西亚半身像区域
        live2d_label = QLabel()
        live2d_label.setAlignment(Qt.AlignCenter)
        live2d_label.setScaledContents(False)  # 不自动缩放，保持原始比例
        live2d_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)  # 固定尺寸，防止拉伸
        live2d_label.setStyleSheet("""
            QLabel {
                background-color: #1e1e2e;
                border: 2px solid #89b4fa;
                border-radius: 15px;
                padding: 5px;
            }
        """)
        
        # 加载露尼西亚图片
        try:
            pixmap = QPixmap("Lunesia.png")
            if not pixmap.isNull():
                # 重新计算适合增加高度后的9:16比例尺寸
                # 系统状态栏宽度固定为320px，露尼西亚图片宽度也要320px
                # 窗口高度增加到900px，为Live2D区域提供更多垂直空间
                # 为了保持9:16比例，高度 = 320*(16/9) = 569px
                target_width = 320
                target_height = int(target_width * 16 / 9)  # 569px
                
                # 缩放图片到目标尺寸，保持宽高比
                scaled_pixmap = pixmap.scaled(target_width, target_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                live2d_label.setPixmap(scaled_pixmap)
                
                # 设置固定尺寸，确保不与其他元素重合
                live2d_label.setFixedSize(target_width, target_height)  # 使用固定尺寸，防止挤压其他元素
                print(f"✅ 成功加载露尼西亚半身像，尺寸: {target_width}x{target_height}")
            else:
                print("❌ 无法加载Lunesia.png图片")
                live2d_label.setText("图片加载失败")
                live2d_label.setStyleSheet("""
                    QLabel {
                        background-color: #1e1e2e;
                        color: #cdd6f4;
                        border: 2px solid #f38ba8;
                        border-radius: 15px;
                        font-size: 18px;
                        padding: 20px;
                    }
                """)
        except Exception as e:
            print(f"❌ 加载图片时出错: {e}")
            live2d_label.setText("图片加载失败")
            live2d_label.setStyleSheet("""
                QLabel {
                    background-color: #1e1e2e;
                    color: #cdd6f4;
                    border: 2px solid #f38ba8;
                    border-radius: 15px;
                    font-size: 18px;
                    padding: 20px;
                }
            """)

        # 按钮区域
        button_layout = QHBoxLayout()

        # 设置按钮
        settings_btn = QPushButton("设置")
        settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #f9e2af;
                color: #1e1e1e;
                border-radius: 10px;
                padding: 10px 15px;
                font-weight: bold;
                min-height: 20px;
            }
            QPushButton:hover {
                background-color: #e7d19e;
            }
        """)
        settings_btn.clicked.connect(self.open_settings)
        
        # 识底深湖按钮
        memory_btn = QPushButton("识底深湖")
        memory_btn.setStyleSheet("""
            QPushButton {
                background-color: #cba6f7;
                color: #1e1e1e;
                border-radius: 10px;
                padding: 10px 15px;
                font-weight: bold;
                min-height: 20px;
            }
            QPushButton:hover {
                background-color: #b4befe;
            }
        """)
        memory_btn.clicked.connect(self.open_memory_lake)
        
        # MCP工具按钮
        mcp_btn = QPushButton("MCP工具")
        mcp_btn.setStyleSheet("""
            QPushButton {
                background-color: #a6e3a1;
                color: #1e1e1e;
                border-radius: 10px;
                padding: 10px 15px;
                font-weight: bold;
                min-height: 20px;
            }
            QPushButton:hover {
                background-color: #94e2d5;
            }
        """)
        mcp_btn.clicked.connect(self.open_mcp_tools)

        button_layout.addWidget(settings_btn)
        button_layout.addWidget(memory_btn)
        button_layout.addWidget(mcp_btn)

        right_layout.addWidget(status_group)
        right_layout.addWidget(live2d_label)  # 移除stretch参数，让图片按实际尺寸显示
        right_layout.addLayout(button_layout)
        right_widget.setLayout(right_layout)

        # 添加分割器
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(chat_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([1000, 350])  # 增加聊天区域宽度，右侧保持不变
        # 禁用分割器拖拽功能
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(0)
        # 设置分割器保持等比例缩放
        splitter.setStretchFactor(0, 1)  # 聊天区域可拉伸
        splitter.setStretchFactor(1, 0)  # 右侧区域固定比例

        main_layout.addWidget(splitter)
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

        # 添加状态栏
        self.statusBar().showMessage("就绪")
        
        # 显示启动欢迎信息
        location = getattr(self.agent, 'location', '未知')
        app_count = getattr(self.agent, 'app_count', 0)
        self.add_message("系统", f"登录地址：{location}，预载应用：{app_count}个")

    def _append_transcript_widget(self, widget):
        """在连续聊天记录末尾插入一个无气泡包装的内容块。"""
        self.chat_transcript_layout.insertWidget(
            max(0, self.chat_transcript_layout.count() - 1), widget
        )
        active_widgets = getattr(self, "_active_turn_widgets", None)
        if active_widgets is not None:
            active_widgets.append(widget)
        self._scroll_chat_to_bottom()

    def _scroll_chat_to_bottom(self):
        scrollbar = self.chat_history.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _begin_workflow_turn(self):
        """Prepare a workflow slot without showing an empty panel for plain chat."""
        self._active_turn_widgets = []
        self._workflow_panel = None
        self._workflow_closed = False
        self._workflow_started_at = time.monotonic()
        self._workflow_insert_index = max(
            0, self.chat_transcript_layout.count() - 1
        )

    def _on_workflow_step(self, key: str, title: str, phase: str):
        """Create/update this reply's compact workflow panel on the UI thread."""
        # 正文已开始后，工作流面板已完成；忽略异步收尾阶段迟到的
        # “done”事件，避免在同一条回复下再生成一块“已处理”面板。
        if (
            not self._agent_busy
            or not title
            or getattr(self, "_workflow_closed", False)
        ):
            return
        if self._workflow_panel is None:
            panel = WorkflowPanel(self.chat_transcript)
            insert_at = self._workflow_insert_index
            if insert_at is None:
                insert_at = max(0, self.chat_transcript_layout.count() - 1)
            self.chat_transcript_layout.insertWidget(insert_at, panel)
            if self._active_turn_widgets is not None:
                self._active_turn_widgets.append(panel)
            self._workflow_panel = panel
        self._workflow_panel.update_step(key, title, phase)
        self._scroll_chat_to_bottom()

    def _finish_workflow_turn(self):
        panel = self._workflow_panel
        if panel is not None:
            started = self._workflow_started_at or time.monotonic()
            # 用已过整秒而不是四舍五入，避免视觉上比消息开始时间多 1 秒。
            elapsed = int(time.monotonic() - started)
            panel.finish(
                elapsed,
                auto_collapse=bool(
                    self.config.get("workflow_auto_collapse", True)
                ),
            )
        self._workflow_panel = None
        self._workflow_closed = True
        self._workflow_started_at = None
        self._workflow_insert_index = None

    def _new_text_segment(self):
        segment = ChatTextSegment(self.chat_transcript)
        self._append_transcript_widget(segment)
        return segment

    def _start_assistant_renderer(self):
        """创建一次露尼西亚回复的增量 Markdown 渲染器。"""
        renderer = {
            "text_segment": self._new_text_segment(),
            "code_card": None,
        }
        renderer["text_segment"].append_text(
            f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 露尼西亚: "
        )
        # 工作流的“已处理”表示工具/推理阶段已经结束；流式正文后续
        # 仍可能持续生成，但不应继续计入该面板的用时。
        self._finish_workflow_turn()

        def on_text(text):
            if renderer["text_segment"] is None:
                renderer["text_segment"] = self._new_text_segment()
            renderer["text_segment"].append_text(text)
            self._scroll_chat_to_bottom()

        def on_retract_text(count):
            segment = renderer["text_segment"]
            if segment is not None:
                segment.retract(count)

        def on_code_start(language):
            card = CodeBlockCard(language, self.chat_transcript)
            renderer["code_card"] = card
            renderer["text_segment"] = None
            self._append_transcript_widget(card)

        def on_code(text):
            card = renderer["code_card"]
            if card is not None:
                card.append_code(text)
                self._scroll_chat_to_bottom()

        def on_retract_code(count):
            card = renderer["code_card"]
            if card is not None:
                card.retract(count)

        def on_code_end():
            card = renderer["code_card"]
            if card is not None:
                card.complete()
            renderer["code_card"] = None
            renderer["text_segment"] = None
            self._scroll_chat_to_bottom()

        renderer["parser"] = StreamingFenceParser(
            on_text=on_text,
            on_retract_text=on_retract_text,
            on_code_start=on_code_start,
            on_code=on_code,
            on_retract_code=on_retract_code,
            on_code_end=on_code_end,
        )
        return renderer

    def _add_assistant_message(self, message):
        """用与流式相同的解析器渲染完整的露尼西亚回复。"""
        renderer = self._start_assistant_renderer()
        renderer["parser"].feed(message)
        renderer["parser"].finish()
        self._scroll_chat_to_bottom()

    def _add_reply_action_bar(self, response):
        if self._latest_action_bar is not None:
            self._latest_action_bar.set_regenerate_enabled(False)
        bar = ReplyActionBar(
            response,
            on_regenerate=self.regenerate_latest_response,
            regenerate_enabled=True,
            parent=self.chat_transcript,
        )
        self._append_transcript_widget(bar)
        self._latest_action_bar = bar
        return bar

    @staticmethod
    def _attachment_names(attachments):
        if attachments is None:
            return []
        return [
            os.path.basename(path)
            for path in (
                list(attachments.image_paths)
                + list(attachments.video_paths)
                + list(attachments.file_paths)
            )
        ]

    @staticmethod
    def _clone_attachments(attachments, user_text=None):
        return CombinedAttachments(
            image_paths=list(attachments.image_paths),
            video_paths=list(attachments.video_paths),
            file_paths=list(attachments.file_paths),
            user_text=(
                attachments.user_text if user_text is None else user_text
            ),
        )

    def _on_user_editor_opened(self, widget):
        self._editing_user_widget = widget
        turn = self._latest_user_turn
        if turn is not None:
            original_message = (turn.get("widgets") or [None])[0]
            if original_message is not None:
                original_message.hide()
        self.input_edit.setEnabled(False)

    def _on_user_editor_closed(self, widget):
        if self._editing_user_widget is widget:
            self._editing_user_widget = None
            turn = self._latest_user_turn
            if turn is not None:
                original_message = (turn.get("widgets") or [None])[0]
                if original_message is not None:
                    original_message.show()
            self.input_edit.setEnabled(True)

    def _add_user_message(self, request, *, edit_enabled=True):
        if self._latest_user_action_bar is not None:
            self._latest_user_action_bar.set_edit_enabled(False)
        segment = self._new_text_segment()
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        segment.append_text(
            f"[{timestamp}] 指挥官: {request['user_input']}\n"
        )
        attachments = request.get("attachments")
        bar = UserMessageActionBar(
            request.get("raw_user_text", ""),
            image_paths=list(attachments.image_paths) if attachments else [],
            video_paths=list(attachments.video_paths) if attachments else [],
            file_paths=list(attachments.file_paths) if attachments else [],
            on_submit=self.submit_latest_user_edit,
            on_edit_open=self._on_user_editor_opened,
            on_edit_close=self._on_user_editor_closed,
            edit_enabled=edit_enabled,
            parent=self.chat_transcript,
        )
        self._append_transcript_widget(bar)
        self._latest_user_action_bar = bar
        self._latest_user_turn = {
            "request": request,
            "widgets": [segment, bar],
        }
        return self._latest_user_turn

    def _remove_transcript_widgets(self, widgets):
        for widget in widgets or []:
            try:
                self.chat_transcript_layout.removeWidget(widget)
                widget.setParent(None)
                widget.deleteLater()
            except RuntimeError:
                pass
        self._scroll_chat_to_bottom()

    def add_message(self, sender, message):
        """添加消息到聊天记录；代码卡只对露尼西亚回复生效。"""
        if sender == "露尼西亚":
            self._add_assistant_message(message)
            return
        segment = self._new_text_segment()
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        segment.append_text(f"[{timestamp}] {sender}: {message}\n")
        self._scroll_chat_to_bottom()
    

    def show_upload_menu(self):
        """显示文件上传选择菜单"""
        menu = QMenu(self)
        menu.setStyleSheet(ATTACHMENT_MENU_STYLESHEET)

        if not self._pending_video and len(self._pending_images) < MAX_IMAGES:
            image_action = QAction("📷 添加图片", self)
            image_action.triggered.connect(self.add_pending_image)
            menu.addAction(image_action)

        if not self._pending_images and not self._pending_video:
            video_action = QAction("🎬 添加视频", self)
            video_action.triggered.connect(self.add_pending_video)
            menu.addAction(video_action)

        if len(self._pending_files) < MAX_FILES:
            file_action = QAction("📄 添加文件", self)
            file_action.triggered.connect(self.add_pending_file)
            menu.addAction(file_action)

        if not menu.actions():
            self.statusBar().showMessage("当前附件已达上限或类型互斥，请先清空后再添加。", 4000)
            return

        button = self.sender()
        menu.exec_(button.mapToGlobal(button.rect().bottomLeft()))
    
    def _begin_upload_stream(self):
        """上传分析路径：与聊天一致，启用流式显示时初始化状态。"""
        if self.config.get("enable_stream_display", False):
            self._streaming_active = True
            self._streaming_renderer = None
            self._streaming_seen_content = ""
            self._stream_pending_content = ""
            self._stream_flush_scheduled = False

    def _make_stream_callback(self):
        """返回流式 chunk 回调（工作线程安全），未启用时返回 None。"""
        if not self.config.get("enable_stream_display", False):
            return None

        def on_chunk(text):
            self.response_stream_chunk.emit(text)

        return on_chunk

    @staticmethod
    def _format_file_size(path: str) -> str:
        try:
            size = os.path.getsize(path)
        except OSError:
            return ""
        if size < 1024:
            return f"{size}B"
        if size < 1024 * 1024:
            return f"{size / 1024:.2f}KB"
        return f"{size / (1024 * 1024):.2f}MB"

    def _make_attachment_card(self, path: str, kind: str, on_remove) -> QWidget:
        """构建单个附件卡片（图标 + 文件名 + 类型/大小 + 右上角 ×）。"""
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lstrip(".").upper() or "文件"
        size_text = self._format_file_size(path)

        card = QFrame()
        card.setFixedSize(190, 52)
        card.setToolTip(name)
        card.setStyleSheet(
            "QFrame { background-color: #313244; border: 1px solid #45475a; border-radius: 10px; }"
        )

        row = QHBoxLayout(card)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(8)

        icon = QLabel()
        icon.setFixedSize(36, 36)
        icon.setAlignment(Qt.AlignCenter)
        if kind == "image":
            pix = QPixmap(path)
            if not pix.isNull():
                icon.setPixmap(
                    pix.scaled(36, 36, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                )
                icon.setStyleSheet("border-radius: 6px;")
            else:
                icon.setText("🖼️")
        elif kind == "video":
            icon.setText("🎬")
            icon.setStyleSheet("font-size: 22px;")
        else:
            icon.setText("📄")
            icon.setStyleSheet("font-size: 22px;")
        row.addWidget(icon, 0)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        name_label = QLabel(name)
        name_label.setStyleSheet("color: #cdd6f4; font-size: 12px; border: none; background: transparent;")
        fm = name_label.fontMetrics()
        name_label.setText(fm.elidedText(name, Qt.ElideMiddle, 110))
        meta = f"{ext} · {size_text}" if size_text else ext
        if kind == "image":
            meta = "图片 · " + size_text if size_text else "图片"
        elif kind == "video":
            meta = "视频 · " + size_text if size_text else "视频"
        meta_label = QLabel(meta)
        meta_label.setStyleSheet("color: #7f849c; font-size: 10px; border: none; background: transparent;")
        text_col.addWidget(name_label)
        text_col.addWidget(meta_label)
        row.addLayout(text_col, 1)

        close_btn = QPushButton("×", card)
        close_btn.setFixedSize(18, 18)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton { background-color: rgba(30,30,46,0.85); color: #cdd6f4;"
            " border: 1px solid #585b70; border-radius: 9px; font-size: 12px; font-weight: bold; padding: 0; }"
            "QPushButton:hover { background-color: #f38ba8; color: #1e1e2e; }"
        )
        close_btn.clicked.connect(lambda: on_remove(path))
        close_btn.move(card.width() - 20, 3)
        close_btn.raise_()
        return card

    def _rebuild_pending_ui(self):
        # 清空旧卡片（保留末尾 stretch）
        while self.pending_cards_layout.count() > 1:
            item = self.pending_cards_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        has_any = False
        for p in self._pending_images:
            card = self._make_attachment_card(p, "image", self._remove_pending_image)
            self.pending_cards_layout.insertWidget(
                self.pending_cards_layout.count() - 1, card
            )
            has_any = True
        if self._pending_video:
            card = self._make_attachment_card(
                self._pending_video, "video", lambda _p: self._remove_pending_video()
            )
            self.pending_cards_layout.insertWidget(
                self.pending_cards_layout.count() - 1, card
            )
            has_any = True
        for p in self._pending_files:
            card = self._make_attachment_card(p, "file", self._remove_pending_file)
            self.pending_cards_layout.insertWidget(
                self.pending_cards_layout.count() - 1, card
            )
            has_any = True

        self.pending_strip.setVisible(has_any)

    def _remove_pending_image(self, path: str):
        if path in self._pending_images:
            self._pending_images.remove(path)
        self._rebuild_pending_ui()

    def _remove_pending_video(self):
        self._pending_video = None
        self._rebuild_pending_ui()

    def _remove_pending_file(self, path: str):
        if path in self._pending_files:
            self._pending_files.remove(path)
        self._rebuild_pending_ui()

    def _clear_pending_attachments(self):
        self._pending_images = []
        self._pending_video = None
        self._pending_files = []
        self._rebuild_pending_ui()

    def _build_pending_attachments(self, user_text: str) -> CombinedAttachments:
        return CombinedAttachments(
            image_paths=list(self._pending_images),
            video_paths=[self._pending_video] if self._pending_video else [],
            file_paths=list(self._pending_files),
            user_text=user_text,
        )

    def _try_add_one(self, path: str, kind: str) -> str:
        """静默添加单个附件，返回状态码：ok | limit | dup | invalid | mutual。不弹窗、不刷新 UI。"""
        if not path or not os.path.isfile(path):
            return "invalid"
        if kind == "image":
            if self._pending_video:
                return "mutual"
            if len(self._pending_images) >= MAX_IMAGES:
                return "limit"
            if path in self._pending_images:
                return "dup"
            self._pending_images.append(path)
        elif kind == "video":
            if self._pending_images:
                return "mutual"
            if self._pending_video:
                return "limit"
            ok, _msg = validate_video_for_pending(path)
            if not ok:
                return "invalid"
            self._pending_video = path
        elif kind == "file":
            if len(self._pending_files) >= MAX_FILES:
                return "limit"
            if path in self._pending_files:
                return "dup"
            self._pending_files.append(path)
        else:
            return "invalid"
        return "ok"

    def _add_pending_path(self, path: str, kind: str) -> bool:
        status = self._try_add_one(path, kind)
        if status == "ok":
            self._rebuild_pending_ui()
            self.statusBar().showMessage(f"已添加待发送附件: {os.path.basename(path)}", 3000)
            return True
        messages = {
            "invalid": "文件不存在或无法读取。",
            "mutual": "图片与视频不能同时添加，请先清空附件。",
            "limit": "已达附件数量上限。",
            "dup": "该附件已添加。",
        }
        if status != "dup":
            QMessageBox.warning(self, "附件", messages.get(status, "无法添加该附件。"))
        return False

    def _add_pending_batch(self, paths: list, kind: str):
        """批量添加，超限/重复/无效统一汇总提示一次。"""
        added = 0
        limit_hit = False
        invalid = 0
        dup = 0
        for p in paths:
            status = self._try_add_one(p, kind)
            if status == "ok":
                added += 1
            elif status == "limit":
                limit_hit = True
                break  # 已达上限，后续无需再试
            elif status == "invalid":
                invalid += 1
            elif status == "dup":
                dup += 1
            elif status == "mutual":
                limit_hit = True
                break
        if added:
            self._rebuild_pending_ui()

        notes = []
        if limit_hit:
            notes.append("已达上限，部分未添加")
        if dup:
            notes.append(f"{dup} 个重复已跳过")
        if invalid:
            notes.append(f"{invalid} 个无效已跳过")
        if added and not notes:
            self.statusBar().showMessage(f"已添加 {added} 个附件", 3000)
        elif notes:
            summary = f"已添加 {added} 个附件；" + "，".join(notes) + "。"
            QMessageBox.warning(self, "附件", summary)

    def add_pending_image(self):
        if self._pending_video:
            QMessageBox.warning(self, "附件", "已添加视频，不能与图片同时添加。请先清空附件。")
            return
        if len(self._pending_images) >= MAX_IMAGES:
            QMessageBox.warning(self, "附件", f"最多添加 {MAX_IMAGES} 张图片。")
            return
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择图片（可多选）",
            "",
            "图片文件 (*.jpg *.jpeg *.png *.gif *.bmp *.tiff *.webp)",
        )
        images = [p for p in file_paths if classify_path(p) == "image"]
        if images:
            self._add_pending_batch(images, "image")

    def add_pending_video(self):
        if self._pending_images:
            QMessageBox.warning(self, "附件", "已添加图片，不能与视频同时添加。请先清空附件。")
            return
        if self._pending_video:
            QMessageBox.warning(self, "附件", "只能添加 1 个视频。")
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择视频",
            "",
            "视频文件 (*.mp4 *.avi *.mov *.mkv *.flv *.wmv *.webm *.m4v *.3gp)",
        )
        if file_path and classify_path(file_path) == "video":
            self._add_pending_path(file_path, "video")

    def add_pending_file(self):
        if len(self._pending_files) >= MAX_FILES:
            QMessageBox.warning(self, "附件", f"最多添加 {MAX_FILES} 个文件。")
            return
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择文件（可多选）",
            "",
            "支持的文件 (*.pdf *.csv *.xlsx *.xls *.docx *.doc *.py *.java *.js *.jsx *.ts *.tsx *.cpp *.c *.h *.go *.rs);;所有文件 (*.*)",
        )
        if not file_paths:
            return
        files = [p for p in file_paths if classify_path(p) == "file"]
        unsupported = len(file_paths) - len(files)
        if files:
            self._add_pending_batch(files, "file")
        if unsupported:
            QMessageBox.warning(
                self, "附件", f"{unsupported} 个文件类型暂不支持，已跳过（请选择文档或代码文件）。"
            )

    def _voice_worker(self, stop_event):
        """后台：录音 → 识别 → 主线程更新输入框"""
        text, err = "", None
        wav_path = None
        try:
            print("[语音] 后台线程已启动", flush=True)
            wav_path, rec_err = record_to_wav(stop_event)
            print("[语音] 录音已结束, rec_err=%s" % (rec_err or "无"), flush=True)
            if rec_err:
                self.voice_result_ready.emit("", rec_err)
                return
            api_key = self.config.get("dashscope_key", "").strip() or None
            print("[语音] 开始调用识别 API...", flush=True)
            text, asr_err = recognize_wav(wav_path, api_key=api_key)
            err = asr_err
            print("[语音] 识别 API 返回, text_len=%s, err=%s" % (len(text or ""), err or "无"), flush=True)
        except Exception as e:
            err = "识别过程异常: " + str(e)
            print("[语音] 异常: %s" % e, flush=True)
        finally:
            try:
                if wav_path and os.path.isfile(wav_path):
                    os.unlink(wav_path)
            except Exception:
                pass
        t, e = text or "", err
        print("[语音] 已通过信号通知主线程更新 UI", flush=True)
        self.voice_result_ready.emit(t, e)

    def _apply_voice_result(self, text, error_message):
        """在主线程中把语音识别结果写入输入框或提示错误"""
        print("[语音] _apply_voice_result 被调用, error_message=%s" % (error_message or "无"), flush=True)
        self._voice_record_thread = None
        if hasattr(self, 'mic_btn') and self.mic_btn:
            self.mic_btn.setStyleSheet(self._mic_btn_style_idle)
        if error_message:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "语音识别", error_message)
            print(f"⚠️ 语音识别失败: {error_message}")
            return
        if text:
            cur = self.input_edit.text()
            self.input_edit.setText((cur + " " + text).strip() if cur else text)
            print(f"✅ 语音识别结果: {text[:50]}{'...' if len(text) > 50 else ''}")
            if self.config.get("voice_auto_send", False):
                self.send_message()
        else:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, "语音识别", "未识别到语音或录音过短，请长按麦克风说话后松开重试。")
            print("ℹ️ 语音识别结果为空")

    def _on_voice_pressed(self):
        """按下麦克风：开始录音（后台线程阻塞直到 release 触发 stop_event）"""
        if not is_voice_input_available():
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "语音输入",
                "语音输入不可用：请安装 pyaudio 与 dashscope，并在设置中配置语音识别 API 密钥。"
            )
            return
        if self._voice_record_thread and self._voice_record_thread.is_alive():
            return
        if hasattr(self, 'mic_btn') and self.mic_btn:
            self.mic_btn.setStyleSheet(self._mic_btn_style_active)
        self._voice_stop_event = threading.Event()
        self._voice_record_thread = threading.Thread(
            target=self._voice_worker,
            args=(self._voice_stop_event,),
            daemon=True,
        )
        self._voice_record_thread.start()

    def _on_voice_released(self):
        """松开麦克风：停止录音，后台线程会完成识别并更新输入框"""
        if self._voice_stop_event:
            self._voice_stop_event.set()
        if hasattr(self, 'mic_btn') and self.mic_btn:
            self.mic_btn.setStyleSheet(self._mic_btn_style_idle)

    def send_message(self):
        """发送消息（文本 + 待发送附件）"""
        user_input = self.input_edit.text().strip()
        has_pending = bool(
            self._pending_images or self._pending_video or self._pending_files
        )
        if not user_input and not has_pending:
            return
        
        if not self._try_begin_agent_work():
            self.statusBar().showMessage("请等待当前任务完成后再发送。", 4000)
            return

        self.agent.reset_generation_cancel()
        self._stop_requested = False
        self._set_generation_button(True)
        if self._latest_action_bar is not None:
            self._latest_action_bar.set_regenerate_enabled(False)
            self._latest_action_bar = None
        self._latest_turn = None
        self._stop_active_progress_timers()

        att = self._build_pending_attachments(user_input)
        chat_line = format_user_chat_line(user_input, att)
        attachment_copy = self._clone_attachments(att)
        self._active_request = {
            "user_input": chat_line,
            "raw_user_text": user_input,
            "attachments": attachment_copy,
        }
        self._add_user_message(self._active_request, edit_enabled=True)
        self._begin_workflow_turn()
        self.input_edit.clear()
        self._clear_pending_attachments()

        has_attachments = not att.is_empty()
        progress_label = "处理附件中..." if has_attachments else "处理中... 0%"
        timeout_ms = 600000 if att.has_video() else 240000

        # 显示进度条
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(progress_label)

        # 启动进度条更新定时器
        self.progress_timer = QTimer()
        self.progress_timer.timeout.connect(self.update_progress)
        self.progress_timer.start(30)  # 每30毫秒更新一次，更平滑
        self.progress_value = 0
        
        # 添加超时保护，防止进度条无限卡住
        self.timeout_timer = QTimer()
        self.timeout_timer.timeout.connect(self.handle_timeout)
        
        self._ui_security_gate_active = False
        self.timeout_timer.start(timeout_ms)

        # 流式显示：与安全门解耦，仅看配置
        if self.config.get("enable_stream_display", False):
            self._streaming_active = True
            self._streaming_renderer = None
            self._streaming_seen_content = ""
            self._stream_pending_content = ""
            self._stream_flush_scheduled = False

        if has_attachments:
            threading.Thread(
                target=self.process_combined_response,
                args=(att,),
                daemon=True,
            ).start()
        else:
            threading.Thread(target=self.process_ai_response, args=(user_input,), daemon=True).start()

    def process_combined_response(self, att: CombinedAttachments):
        """后台线程：组合发送"""
        try:
            print(f"📎 开始组合发送: images={len(att.image_paths)} video={len(att.video_paths)} files={len(att.file_paths)}")
            if att.file_paths:
                from workflow_status import emit_workflow, shorten

                file_target = shorten(os.path.basename(att.file_paths[0]), 20)
                if len(att.file_paths) > 1:
                    file_target += f" 等 {len(att.file_paths)} 个附件"
                emit_workflow(
                    self.agent,
                    "attachment:files",
                    f"分析 {file_target} 中",
                    "active",
                )
            if att.user_text.strip():
                self._resolve_ui_security_gate(att.user_text.strip())
            stream_callback = None
            if self.config.get("enable_stream_display", False):
                def on_chunk(text):
                    self.response_stream_chunk.emit(text)
                stream_callback = on_chunk
            response = self.agent.process_combined_send(att, stream_callback=stream_callback)
            if att.file_paths:
                emit_workflow(
                    self.agent,
                    "attachment:files",
                    f"已分析 {file_target}",
                    "done",
                )
            self.response_ready.emit(response)
        except Exception as e:
            print(f"❌ 组合发送错误: {e}")
            if att.file_paths:
                try:
                    emit_workflow(
                        self.agent,
                        "attachment:files",
                        f"分析 {file_target} 失败",
                        "failed",
                    )
                except Exception:
                    pass
            self.response_ready.emit(f"抱歉，组合发送时出现问题：{e}")

    def _reset_stream_ui_for_replacement(self):
        self._streaming_active = False
        self._streaming_renderer = None
        self._streaming_seen_content = ""
        self._stream_pending_content = ""
        self._stream_flush_scheduled = False
        self._workflow_panel = None
        self._workflow_closed = True
        self._workflow_started_at = None
        self._workflow_insert_index = None

    def submit_latest_user_edit(self, new_text, new_attachments=None):
        """Apply an inline edit to the latest user turn and rerun that turn."""
        user_turn = self._latest_user_turn
        if not user_turn:
            return
        old_request = user_turn["request"]
        old_attachments = old_request["attachments"]
        if new_attachments is None:
            new_attachments = self._clone_attachments(
                old_attachments, user_text=new_text.strip()
            )
        else:
            new_attachments = CombinedAttachments(
                image_paths=list(new_attachments.image_paths),
                video_paths=list(new_attachments.video_paths),
                file_paths=list(new_attachments.file_paths),
                user_text=new_text.strip(),
            )
        if not new_text.strip() and new_attachments.is_empty():
            self.statusBar().showMessage("发送内容不能为空。", 4000)
            return
        new_request = {
            "raw_user_text": new_text.strip(),
            "attachments": new_attachments,
            "user_input": format_user_chat_line(new_text.strip(), new_attachments),
        }
        was_busy = bool(self._agent_busy)
        old_response = None
        if (
            not was_busy
            and self._latest_turn is not None
            and self._latest_turn.get("request") is old_request
        ):
            old_response = self._latest_turn.get("response", "")

        self._remove_transcript_widgets(user_turn.get("widgets", []))
        if was_busy:
            self._remove_transcript_widgets(self._active_turn_widgets or [])
        elif self._latest_turn is not None:
            self._remove_transcript_widgets(
                self._latest_turn.get("widgets", [])
            )

        self._active_turn_widgets = None
        self._latest_turn = None
        self._latest_action_bar = None
        self._latest_user_action_bar = None
        self._latest_user_turn = None
        self._reset_stream_ui_for_replacement()
        self._add_user_message(new_request, edit_enabled=not was_busy)

        if was_busy:
            self._edit_restart_pending = {
                "old_request": old_request,
                "new_request": new_request,
            }
            # 等待当前工具自然返回时关闭旧轮超时计时器，避免超时信号
            # 抢先触发新轮，造成两个线程同时占用同一个 Agent。
            self._stop_active_progress_timers()
            self.agent.cancel_generation()
            self._stop_requested = True
            self.send_btn.setEnabled(False)
            self.progress_bar.setFormat("正在应用修改…")
            self.statusBar().showMessage(
                "当前工具步骤结束后，将按修改后的内容重新生成。", 6000
            )
            return

        self._start_edited_regeneration(
            old_request, old_response or "", new_request
        )

    def _start_edited_regeneration(
        self, old_request, old_response, new_request
    ):
        if not self._try_begin_agent_work():
            return
        self.agent.reset_generation_cancel()
        self._stop_requested = False
        self._set_generation_button(True)
        self._stop_active_progress_timers()
        self._active_request = new_request
        self._begin_workflow_turn()
        if self._latest_user_action_bar is not None:
            self._latest_user_action_bar.set_edit_enabled(True)

        attachments = new_request["attachments"]
        has_attachments = not attachments.is_empty()
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(
            "重新处理附件中..." if has_attachments else "重新生成中... 0%"
        )
        self.progress_value = 0
        self.progress_timer = QTimer()
        self.progress_timer.timeout.connect(self.update_progress)
        self.progress_timer.start(30)
        self.timeout_timer = QTimer()
        self.timeout_timer.timeout.connect(self.handle_timeout)
        self.timeout_timer.start(
            600000 if has_attachments and attachments.has_video() else 240000
        )
        if self.config.get("enable_stream_display", False):
            self._streaming_active = True
            self._streaming_renderer = None
            self._streaming_seen_content = ""
            self._stream_pending_content = ""
            self._stream_flush_scheduled = False

        threading.Thread(
            target=self.process_edited_response,
            args=(old_request, old_response, new_request),
            daemon=True,
        ).start()

    def process_edited_response(
        self, old_request, old_response, new_request
    ):
        try:
            stream_callback = None
            if self.config.get("enable_stream_display", False):
                def on_chunk(text):
                    self.response_stream_chunk.emit(text)
                stream_callback = on_chunk
            response = self.agent.regenerate_edited_turn(
                old_request["user_input"],
                old_response,
                new_request["user_input"],
                attachments=new_request["attachments"],
                stream_callback=stream_callback,
            )
            notice = self.agent.last_regeneration_memory_notice
            if notice:
                self.user_notice.emit(notice)
            self.response_ready.emit(response)
        except Exception as exc:
            print(f"❌ 修改后重新生成失败: {exc}")
            self.response_ready.emit(f"抱歉，修改后重新生成时出现问题：{exc}")

    def regenerate_latest_response(self):
        """Replace only the newest assistant reply."""
        turn = self._latest_turn
        if not turn or getattr(self, "_agent_busy", False):
            return
        if not self._try_begin_agent_work():
            return

        self.agent.reset_generation_cancel()
        self._stop_requested = False
        self._set_generation_button(True)
        self._stop_active_progress_timers()

        old_response = turn["response"]
        request = turn["request"]
        self._remove_transcript_widgets(turn.get("widgets", []))
        self._latest_action_bar = None
        self._latest_turn = None
        self._active_request = request
        self._begin_workflow_turn()

        attachments = request.get("attachments")
        has_attachments = bool(attachments and not attachments.is_empty())
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(
            "重新处理附件中..." if has_attachments else "重新生成中... 0%"
        )
        self.progress_value = 0
        self.progress_timer = QTimer()
        self.progress_timer.timeout.connect(self.update_progress)
        self.progress_timer.start(30)
        self.timeout_timer = QTimer()
        self.timeout_timer.timeout.connect(self.handle_timeout)
        self.timeout_timer.start(
            600000 if has_attachments and attachments.has_video() else 240000
        )

        if self.config.get("enable_stream_display", False):
            self._streaming_active = True
            self._streaming_renderer = None
            self._streaming_seen_content = ""
            self._stream_pending_content = ""
            self._stream_flush_scheduled = False

        threading.Thread(
            target=self.process_regenerated_response,
            args=(request, old_response),
            daemon=True,
        ).start()

    def process_regenerated_response(self, request, old_response):
        try:
            stream_callback = None
            if self.config.get("enable_stream_display", False):
                def on_chunk(text):
                    self.response_stream_chunk.emit(text)
                stream_callback = on_chunk

            attachments = request.get("attachments")
            response = self.agent.regenerate_last_response(
                request["user_input"],
                old_response,
                attachments=attachments,
                stream_callback=stream_callback,
            )
            notice = self.agent.last_regeneration_memory_notice
            if notice:
                self.user_notice.emit(notice)
            self.response_ready.emit(response)
        except Exception as exc:
            print(f"❌ 重新生成失败: {exc}")
            self.response_ready.emit(f"抱歉，重新生成时出现问题：{exc}")

    def send_message_shortcut(self):
        """快捷键发送消息"""
        send_key_mode = self.config.get("send_key_mode", "Ctrl+Enter")
        
        if send_key_mode == "Enter":
            # Enter模式：直接发送
            self.send_message()
        else:
            # Ctrl+Enter模式：需要按住Ctrl
            if QApplication.keyboardModifiers() & Qt.ControlModifier:
                self.send_message()

    def _kali_bridge_enabled(self) -> bool:
        kali = self.config.get("kali_bridge") or {}
        return bool(kali.get("enabled", False))

    def _resolve_ui_security_gate(self, user_input: str) -> bool:
        """UI 安全门：Kali 未启用不调 API；失败按非安全处理。"""
        if not self._kali_bridge_enabled():
            return False

        intent = self.agent.classify_security_intent(user_input)
        if intent is None:
            print("⚠️ 安全测试意图识别失败，按非安全请求继续")
            return False

        if intent != "not_security":
            print(f"🔒 检测到安全测试请求（{intent}），设置600秒超时")
            self._ui_security_gate_active = True
            self.security_timeout_extend.emit()
            return True

        return False

    def _on_security_timeout_extend(self):
        """主线程：安全门命中后延长超时。"""
        if hasattr(self, "timeout_timer") and self.timeout_timer is not None:
            self.timeout_timer.stop()
            self.timeout_timer.start(600000)

    def process_ai_response(self, user_input):
        """处理AI响应"""
        try:
            print(f"🔄 开始处理AI响应: {user_input}")

            self._resolve_ui_security_gate(user_input)

            stream_callback = None
            if self.config.get("enable_stream_display", False):
                accumulated = [""]

                def on_chunk(text):
                    accumulated[0] = text
                    self.response_stream_chunk.emit(text)

                stream_callback = on_chunk

            response = self.agent.process_command(
                user_input, self.waiting_for_first_response, stream_callback=stream_callback
            )

            if self.waiting_for_first_response:
                self.waiting_for_first_response = False

            log_tag = "安全测试" if self._ui_security_gate_active else "AI"
            print(f"✅ {log_tag}响应获取成功: {response[:50]}...")

            if not response or response.strip() == "":
                response = "抱歉，我没有理解您的意思，请重新表述一下。"

            print(f"📡 发送信号: {response[:50]}...")
            self.response_ready.emit(response)

        except Exception as e:
            print(f"❌ AI响应处理错误: {str(e)}")
            error_response = f"抱歉，处理您的请求时出现了问题：{str(e)}"
            self.response_ready.emit(error_response)

    def update_progress(self):
        """更新进度条"""
        if hasattr(self, 'progress_value'):
            # 检查是否是图片分析
            is_image_analysis = "分析图片中" in self.progress_bar.format()
            
            if is_image_analysis:
                # 图片分析使用更慢的进度增长
                if self.progress_value < 20:
                    self.progress_value += 0.5  # 前20%很慢增长
                elif self.progress_value < 50:
                    self.progress_value += 0.3  # 中间30%极慢增长
                elif self.progress_value < 80:
                    self.progress_value += 0.2  # 后30%极慢增长
                else:
                    self.progress_value = 80  # 最多到80%，留20%给完成时
            else:
                # 普通对话使用正常进度增长
                if self.progress_value < 30:
                    self.progress_value += 2  # 前30%快速增长
                elif self.progress_value < 70:
                    self.progress_value += 1  # 中间40%中等速度
                elif self.progress_value < 85:
                    self.progress_value += 0.5  # 后15%慢速增长
                else:
                    self.progress_value = 85  # 最多到85%，留15%给完成时
            
            self.progress_bar.setValue(int(self.progress_value))
            current_format = self.progress_bar.format()
            if "分析图片中" in current_format:
                self.progress_bar.setFormat(f"分析图片中... {int(self.progress_value)}%")
            else:
                self.progress_bar.setFormat(f"处理中... {int(self.progress_value)}%")

    def _on_response_status_message(self, message: str):
        """读屏等场景：收到即时状态提示时更新进度条文案"""
        if hasattr(self, 'progress_bar') and message:
            self.progress_bar.setFormat(message)

    def _on_stream_chunk(self, content):
        """流式显示：合并高频 chunk，按累积文本差分增量渲染。"""
        if not getattr(self, '_streaming_active', False):
            return
        self._stream_pending_content = content
        if getattr(self, '_stream_flush_scheduled', False):
            return
        self._stream_flush_scheduled = True
        QTimer.singleShot(45, self._flush_stream_chunk_to_chat)

    def _flush_stream_chunk_to_chat(self):
        """将待显示的流式内容增量写入文本段或代码卡。"""
        self._stream_flush_scheduled = False
        if not getattr(self, '_streaming_active', False):
            return
        content = getattr(self, '_stream_pending_content', '')
        if self._streaming_renderer is None:
            self._streaming_renderer = self._start_assistant_renderer()
            self._streaming_seen_content = ""

        previous = self._streaming_seen_content
        if content.startswith(previous):
            delta = content[len(previous):]
            next_seen = content
        elif previous.startswith(content):
            # 节流下可能拿到比上次更早的累积快照；无需重复渲染。
            return
        else:
            # 兼容少数服务端直接回传 delta 的情况。
            delta = content
            next_seen = previous + content
        if delta:
            self._streaming_renderer["parser"].feed(delta)
            self._streaming_seen_content = next_seen
            self._scroll_chat_to_bottom()

    def _continue_pending_edit_after_old_response(self, old_response):
        pending = self._edit_restart_pending
        self._edit_restart_pending = None
        self._stop_active_progress_timers()
        self._reset_stream_ui_for_replacement()
        self._active_request = None
        self._active_turn_widgets = None
        self._agent_busy = False
        self._stop_requested = False
        self._set_generation_button(False)
        if pending is not None:
            self._start_edited_regeneration(
                pending["old_request"],
                str(old_response or ""),
                pending["new_request"],
            )

    def update_ui_with_response(self, response):
        """在主线程中更新UI"""
        if self._edit_restart_pending is not None:
            # 旧任务仅负责完成当前工具步并落下可替换的旧会话记录；
            # 它的最终/打断文本不再进入 UI，随后启动编辑后的新请求。
            self._continue_pending_edit_after_old_response(response)
            return
        try:
            print(f"🔄 开始更新UI: {response[:50]}...")
            print(f"🔄 完整消息: {response}")
            
            # 停止所有定时器
            if hasattr(self, 'progress_timer'):
                self.progress_timer.stop()
            if hasattr(self, 'timeout_timer'):
                self.timeout_timer.stop()
            
            # 立即完成进度条
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("完成")
            
            if getattr(self, '_streaming_active', False):
                pending = getattr(self, '_stream_pending_content', '')
                if pending:
                    self._flush_stream_chunk_to_chat()
                if self._streaming_renderer is not None:
                    # response_ready 可能早于最后一次流式 UI 刷新；补齐尾部。
                    if response.startswith(self._streaming_seen_content):
                        self._streaming_renderer["parser"].feed(
                            response[len(self._streaming_seen_content):]
                        )
                    self._streaming_renderer["parser"].finish()
                    self._scroll_chat_to_bottom()
                else:
                    self.add_message("露尼西亚", response)
                self._streaming_active = False
                self._streaming_renderer = None
                self._streaming_seen_content = ""
                self._stream_pending_content = ""
                self._stream_flush_scheduled = False
            else:
                print(f"📝 添加消息到聊天历史: 露尼西亚 - {response[:50]}...")
                self.add_message("露尼西亚", response)

            self._finish_workflow_turn()
            if self._active_request is not None:
                self._add_reply_action_bar(response)
                self._latest_turn = {
                    "response": response,
                    "request": self._active_request,
                    "widgets": list(self._active_turn_widgets or []),
                }
            self._active_turn_widgets = None
            self._active_request = None
            
            QTimer.singleShot(800, lambda: self.progress_bar.setVisible(False))
        finally:
            self._agent_busy = False
            self._stop_requested = False
            self._set_generation_button(False)

    def handle_timeout(self):
        """处理超时"""
        print("⏰ 处理超时")
        
        # 停止安全测试进度更新
        self.stop_security_progress_update()
        
        # 检查是否是图片分析
        is_image_analysis = "分析图片中" in self.progress_bar.format()
        
        is_security_test = getattr(self, "_ui_security_gate_active", False)

        if is_image_analysis:
            timeout_message = "抱歉，图片分析时间过长，请稍后重试。如果图片较大或内容复杂，可能需要更长时间处理。"
        elif is_security_test:
            timeout_message = "安全测试时间过长，请稍后重试。深度安全测试需要更多时间来完成。"
        else:
            timeout_message = "抱歉，处理时间过长，请重试。"
        
        self.response_ready.emit(timeout_message)


    def start_security_progress_update(self):
        """启动安全测试进度更新"""
        self.security_progress_timer = QTimer()
        self.security_progress_timer.timeout.connect(self.update_security_progress)
        self.security_progress_timer.start(5000)  # 每5秒更新一次
        self.security_progress_step = 0
    
    def update_security_progress(self):
        """更新安全测试进度"""
        self.security_progress_step += 1
        
        progress_messages = [
            "🔍 正在进行端口扫描...",
            "🌐 正在分析Web服务...",
            "🔍 正在执行漏洞扫描...",
            "💉 正在测试SQL注入...",
            "🔐 正在尝试暴力破解...",
            "📊 正在生成安全报告...",
            "✅ 安全测试即将完成..."
        ]
        
        if self.security_progress_step < len(progress_messages):
            message = progress_messages[self.security_progress_step - 1]
            self.progress_bar.setFormat(message)
            print(f"🔒 安全测试进度: {message}")
        else:
            # 循环显示进度消息
            message = progress_messages[(self.security_progress_step - 1) % len(progress_messages)]
            self.progress_bar.setFormat(message)
            print(f"🔒 安全测试进度: {message}")
        
        # 更新进度条值
        progress_value = min(90, self.security_progress_step * 10)
        self.progress_bar.setValue(progress_value)
    
    def stop_security_progress_update(self):
        """停止安全测试进度更新"""
        if hasattr(self, 'security_progress_timer'):
            self.security_progress_timer.stop()
            self.security_progress_timer = None
    def _on_settings_accepted(self):
        """设置窗口点击确定后的处理（非模态时调用）"""
        try:
            self.agent.update_tts_config(self.config)
            print("✅ TTS配置已更新")
        except Exception as e:
            print(f"⚠️ TTS配置更新失败: {str(e)}")
        try:
            self.agent.memory_lake.sync_config(self.config)
        except Exception as e:
            print(f"⚠️ 识底深湖配置同步失败: {str(e)}")
        from llm_spec import get_config_spec
        if hasattr(self, "ai_model"):
            self.ai_model.setText(get_config_spec(self.config, "selected_model").display_name())
        self.apply_transparency()
        self.reload_global_shortcuts()

    def open_settings(self):
        """打开设置窗口（独立窗口，任务栏单独显示）"""
        settings_dialog = SettingsDialog(self.config, None, self.update_transparency)
        settings_dialog.accepted.connect(self._on_settings_accepted)
        settings_dialog.setAttribute(Qt.WA_DeleteOnClose)
        settings_dialog.setWindowFlags(settings_dialog.windowFlags() | Qt.Window)
        self._settings_dialog = settings_dialog  # 保持引用，避免被回收
        settings_dialog.show()

    def open_memory_lake(self):
        """打开识底深湖窗口（独立窗口，任务栏单独显示）"""
        memory_dialog = MemoryLakeDialog(self.agent.memory_lake, None)
        memory_dialog.setAttribute(Qt.WA_DeleteOnClose)
        memory_dialog.setWindowFlags(memory_dialog.windowFlags() | Qt.Window)
        self._memory_lake_dialog = memory_dialog  # 保持引用，避免被回收
        memory_dialog.show()

    def open_mcp_tools(self):
        """打开MCP工具窗口（独立窗口，任务栏单独显示）"""
        mcp_dialog = MCPToolsDialog(self.agent.mcp_tools, None)
        mcp_dialog.setAttribute(Qt.WA_DeleteOnClose)
        mcp_dialog.setWindowFlags(mcp_dialog.windowFlags() | Qt.Window)
        self._mcp_dialog = mcp_dialog  # 保持引用，避免被回收
        mcp_dialog.show()

    def sync_time(self):
        """同步网络时间"""
        try:
            import requests
            response = requests.get('http://worldtimeapi.org/api/timezone/Asia/Shanghai', timeout=5)
            data = response.json()
            current_time = datetime.datetime.fromisoformat(data['datetime'].replace('Z', '+00:00'))
            time_str = current_time.strftime("%H:%M:%S")
            self.ai_time.setText(time_str)
        except:
            # 如果网络时间同步失败，使用本地时间
            self.ai_time.setText(datetime.datetime.now().strftime("%H:%M:%S"))

    def update_status(self):
        """更新状态"""
        # 更新记忆系统状态
        mem_status = "开发者模式" if getattr(self.agent, 'developer_mode', False) else "正常"
        self.ai_memory.setText(mem_status)

        # 更新时间（每5秒同步一次网络时间）
        if hasattr(self, 'time_sync_counter'):
            self.time_sync_counter += 1
        else:
            self.time_sync_counter = 0
        
        if self.time_sync_counter % 5 == 0:  # 每5次更新同步一次网络时间
            self.sync_time()
        else:
            # 使用本地时间更新
            current_time = datetime.datetime.now()
            time_str = current_time.strftime("%H:%M:%S")
            self.ai_time.setText(time_str)

        # 更新状态栏
        time_str = self.ai_time.text()
        from llm_spec import get_config_spec
        _model_label = get_config_spec(self.config, "selected_model", "deepseek-v4-flash").display_name()
        self.statusBar().showMessage(
            f"就绪 | 模型: {_model_label} | 记忆系统: {mem_status} | {time_str}")

    def _voice_shortcut_hook(self, event):
        """键盘 hook：语音快捷键按下/松开时等同于麦克风按钮（需在主线程执行 UI）"""
        if not getattr(self, '_voice_shortcut_key', None):
            return
        try:
            name = getattr(event, 'name', None) or getattr(event, 'scan_code', '')
            name_lower = str(name).lower()
            event_type = getattr(event, 'event_type', 'down')
            if name_lower != self._voice_shortcut_key:
                return
            if event_type == 'down':
                mods = getattr(self, '_voice_shortcut_modifiers', [])
                if mods and not all(keyboard.is_pressed(m) for m in mods):
                    return
                QTimer.singleShot(0, self._on_voice_pressed)
            else:
                QTimer.singleShot(0, self._on_voice_released)
        except Exception:
            pass

    def setup_global_shortcuts(self):
        """设置全局快捷键（使用 keyboard 库）"""
        if not KEYBOARD_AVAILABLE:
            print("⚠️ keyboard 库不可用，全局快捷键功能已禁用")
            return

        # 移除之前的语音快捷键 hook（若存在）
        if getattr(self, '_voice_hook_callback', None) is not None:
            try:
                keyboard.unhook(self._voice_hook_callback)
            except Exception:
                pass
            self._voice_hook_callback = None
        self._voice_shortcut_key = None
        self._voice_shortcut_modifiers = []

        try:
            # 设置窗口呼出快捷键
            show_window_key = self.config.get("show_window_key_sequence", "ctrl+shift+l")
            keyboard.add_hotkey(show_window_key, self.show_and_activate_window)
            print(f"✅ 窗口呼出快捷键已设置: {show_window_key}")
            
            # 设置发送消息的全局快捷键（可选，因为输入框已经有快捷键了）
            send_key_sequence = self.config.get("send_key_sequence", "ctrl+enter")
            if send_key_sequence and send_key_sequence != "enter":
                try:
                    keyboard.add_hotkey(send_key_sequence, self.send_message_global)
                    print(f"✅ 发送消息全局快捷键已设置: {send_key_sequence}")
                except Exception as e:
                    print(f"⚠️ 设置发送消息全局快捷键失败: {str(e)}")

            # 语音输入快捷键（按住说话，松开结束）
            voice_seq = (self.config.get("voice_input_key_sequence") or "").strip().lower()
            if voice_seq:
                parts = [p.strip() for p in voice_seq.split("+") if p.strip()]
                if parts:
                    self._voice_shortcut_key = parts[-1]
                    self._voice_shortcut_modifiers = parts[:-1]
                    self._voice_hook_callback = self._voice_shortcut_hook
                    keyboard.hook(self._voice_hook_callback)
                    print(f"✅ 语音输入快捷键已设置: {voice_seq}（按住说话，松开结束）")

            # 打断TTS快捷键
            if getattr(self, '_tts_stop_hotkey_handler', None) is not None:
                try:
                    self._tts_stop_hotkey_handler.remove()
                except Exception:
                    pass
                self._tts_stop_hotkey_handler = None
            tts_stop_seq = (self.config.get("tts_stop_key_sequence") or "").strip().lower()
            if tts_stop_seq:
                try:
                    self._tts_stop_hotkey_handler = keyboard.add_hotkey(tts_stop_seq, self._on_tts_stop_global)
                    print(f"✅ 打断TTS快捷键已设置: {tts_stop_seq}")
                except Exception as e:
                    print(f"⚠️ 设置打断TTS快捷键失败: {str(e)}")

            # 截图许可开关快捷键
            if getattr(self, '_screenshot_toggle_hotkey_handler', None) is not None:
                try:
                    self._screenshot_toggle_hotkey_handler.remove()
                except Exception:
                    pass
                self._screenshot_toggle_hotkey_handler = None
            screenshot_toggle_seq = (self.config.get("screenshot_toggle_key_sequence") or "").strip().lower()
            if screenshot_toggle_seq:
                try:
                    self._screenshot_toggle_hotkey_handler = keyboard.add_hotkey(screenshot_toggle_seq, self._on_screenshot_toggle_global)
                    print(f"✅ 截图许可开关快捷键已设置: {screenshot_toggle_seq}")
                except Exception as e:
                    print(f"⚠️ 设置截图许可开关快捷键失败: {str(e)}")
        except Exception as e:
            print(f"⚠️ 设置全局快捷键失败: {str(e)}")
    
    def show_and_activate_window(self):
        """显示并激活窗口（用于快捷键呼出）"""
        # keyboard 库的回调在后台线程中执行，需要使用 QTimer 将操作调度到主线程
        try:
            # 使用 QTimer.singleShot(0, ...) 将操作排队到主线程的事件循环
            QTimer.singleShot(0, self._show_and_activate_window_main_thread)
        except Exception as e:
            print(f"⚠️ 调度窗口呼出操作失败: {str(e)}")
    
    def _show_and_activate_window_main_thread(self):
        """在主线程中显示并激活窗口"""
        try:
            if getattr(self, "_in_tray", False):
                self._show_from_tray()
                return
            if self.isMinimized():
                # 如果窗口最小化，恢复并显示
                self.showNormal()
            elif not self.isVisible():
                # 如果窗口隐藏，显示
                self.show()
            
            # 激活窗口并置于最前
            self.activateWindow()
            self.raise_()
            
            # 将焦点设置到输入框
            if hasattr(self, 'input_edit'):
                self.input_edit.setFocus()
            
            print("✅ 窗口已呼出并激活")
        except Exception as e:
            print(f"⚠️ 呼出窗口失败: {str(e)}")
    
    def _on_tts_stop_global(self):
        """全局快捷键打断TTS（keyboard 在后台线程调用，需调度到主线程）"""
        try:
            QTimer.singleShot(0, self._on_tts_stop_main_thread)
        except Exception as e:
            print(f"⚠️ 调度打断TTS操作失败: {str(e)}")

    def _on_tts_stop_main_thread(self):
        """在主线程中停止TTS播放"""
        try:
            if hasattr(self, 'agent') and self.agent is not None:
                self.agent.stop_tts()
                print("🛑 已打断TTS播放")
        except Exception as e:
            print(f"⚠️ 打断TTS失败: {str(e)}")

    def send_message_global(self):
        """全局快捷键发送消息（仅在窗口可见时有效）"""
        # keyboard 库的回调在后台线程中执行，需要使用 QTimer 将操作调度到主线程
        try:
            # 使用 QTimer.singleShot(0, ...) 将操作排队到主线程的事件循环
            QTimer.singleShot(0, self._send_message_global_main_thread)
        except Exception as e:
            print(f"⚠️ 调度全局发送消息操作失败: {str(e)}")
    
    def _send_message_global_main_thread(self):
        """在主线程中发送消息"""
        try:
            if self.isVisible() and not self.isMinimized():
                # 只有当窗口可见且未最小化时才发送消息
                self.send_message()
        except Exception as e:
            print(f"⚠️ 全局快捷键发送消息失败: {str(e)}")

    def _on_screenshot_toggle_global(self):
        """全局快捷键：开关截图许可（keyboard 在后台线程调用，需调度到主线程）"""
        try:
            QTimer.singleShot(0, self._on_screenshot_toggle_main_thread)
        except Exception as e:
            print(f"⚠️ 调度截图许可开关失败: {str(e)}")

    def _on_screenshot_toggle_main_thread(self):
        """在主线程中切换截图许可并保存、提示"""
        try:
            self.config["screenshot_allowed"] = not self.config.get("screenshot_allowed", True)
            save_config(self.config)
            status = "已开启" if self.config["screenshot_allowed"] else "已关闭"
            msg = f"截图许可: {status}"
            self.statusBar().showMessage(msg)
            if hasattr(self, "response_status_message"):
                self.response_status_message.emit(msg)
            print(f"🖥️ {msg}")
        except Exception as e:
            print(f"⚠️ 切换截图许可失败: {str(e)}")
    
    def reload_global_shortcuts(self):
        """重新加载全局快捷键（用于设置更改后）"""
        if not KEYBOARD_AVAILABLE:
            return
        try:
            # 先移除语音 hook（unhook_all_hotkeys 不会移除 hook）
            if getattr(self, '_voice_hook_callback', None) is not None:
                try:
                    keyboard.unhook(self._voice_hook_callback)
                except Exception:
                    pass
                self._voice_hook_callback = None
            # 清除所有已注册的热键
            keyboard.unhook_all_hotkeys()
            # 重新设置
            self.setup_global_shortcuts()
            print("✅ 全局快捷键已重新加载")
        except Exception as e:
            print(f"⚠️ 重新加载全局快捷键失败: {str(e)}")

    def _tear_down_global_shortcuts(self):
        """卸掉全局快捷键与语音 hook（进托盘或彻底退出时）。"""
        if not KEYBOARD_AVAILABLE:
            return
        try:
            if getattr(self, "_voice_hook_callback", None) is not None:
                try:
                    keyboard.unhook(self._voice_hook_callback)
                except Exception:
                    pass
                self._voice_hook_callback = None
            keyboard.unhook_all_hotkeys()
            try:
                keyboard.unhook_all()
            except Exception:
                pass
            print("✅ 全局快捷键已清理")
        except Exception as e:
            print(f"⚠️ 清理全局快捷键失败: {str(e)}")

    def _save_window_geometry_to_settings(self):
        try:
            s = QSettings("Lucinia", "LuciniaAI")
            s.setValue("main_window_geometry", self.saveGeometry())
        except Exception:
            pass

    def _restore_window_geometry_from_settings(self):
        try:
            s = QSettings("Lucinia", "LuciniaAI")
            geom = s.value("main_window_geometry")
            if geom:
                self.restoreGeometry(geom)
        except Exception:
            pass

    def _setup_system_tray(self):
        """创建托盘图标与菜单（可用时）；关闭到托盘后再显示。"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("⚠️ 系统托盘不可用，关闭到托盘功能将不可用")
            return
        self._tray_icon = QSystemTrayIcon(self)
        ic = get_application_icon()
        if not ic.isNull():
            self._tray_icon.setIcon(ic)
        else:
            pm = QPixmap(16, 16)
            pm.fill(QColor("#89b4fa"))
            self._tray_icon.setIcon(QIcon(pm))
        self._tray_menu = QMenu(self)
        act_open = QAction("打开", self)
        act_open.triggered.connect(self._show_from_tray)
        act_quit = QAction("关闭（彻底退出）", self)
        act_quit.triggered.connect(self._quit_application_from_tray)
        self._tray_menu.addAction(act_open)
        self._tray_menu.addAction(act_quit)
        # 不设 setContextMenu，避免与 activated 重复弹菜单；左/右键统一在 _on_tray_icon_activated 处理
        self._tray_icon.activated.connect(self._on_tray_icon_activated)
        self._tray_icon.setToolTip("露尼西亚AI助手")
        if self.config.get("close_main_window_action", "exit") == "tray":
            self._tray_icon.show()

    def _on_tray_icon_activated(self, reason):
        """左键/右键均弹出菜单；双击直接打开主窗口。"""
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_from_tray()
            return
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.Context):
            if self._tray_menu:
                self._tray_menu.popup(QCursor.pos())

    def _close_app_child_dialogs(self):
        """进托盘前关闭设置/识底深湖/MCP 等独立对话框。"""
        for name in ("_settings_dialog", "_memory_lake_dialog", "_mcp_dialog"):
            w = getattr(self, name, None)
            if w is not None:
                try:
                    if w.isVisible():
                        w.close()
                except Exception:
                    pass
        app = QApplication.instance()
        if app:
            for w in app.topLevelWidgets():
                if w is self:
                    continue
                if isinstance(w, QDialog) and w.isVisible():
                    try:
                        w.close()
                    except Exception:
                        pass

    def _hide_to_tray(self):
        """关闭到托盘：暂离保存、任务栏不保留主窗口按钮。"""
        if getattr(self, "_in_tray", False):
            return
        self._close_app_child_dialogs()
        self.save_unsaved_conversations_silent()
        self._save_window_geometry_to_settings()
        if not self.config.get("tray_keep_global_shortcuts", False):
            self._tear_down_global_shortcuts()
        if self._tray_icon:
            self._tray_icon.show()
        self.hide()
        # 保证存回的是「带 Qt.Window、无 Qt.Tool」的普通顶层窗，避免仅 Tool 导致关对话框即 quit
        nf = (self.windowFlags() | Qt.Window) & ~Qt.Tool
        self._normal_window_flags = nf
        self.setWindowFlags(nf | Qt.Tool)
        self.hide()
        self._in_tray = True
        if self._tray_icon:
            self._tray_icon.show()
            QTimer.singleShot(0, lambda: self._tray_icon and self._tray_icon.show())

    def _show_from_tray(self):
        """从托盘恢复主窗口并置顶、恢复快捷键与几何。"""
        if not getattr(self, "_in_tray", False):
            if not self.isVisible():
                self.show()
            self.raise_()
            self.activateWindow()
            if hasattr(self, "input_edit"):
                self.input_edit.setFocus()
            return
        nf = self._normal_window_flags
        if nf is None:
            nf = (self.windowFlags() | Qt.Window) & ~Qt.Tool
        else:
            nf = (nf | Qt.Window) & ~Qt.Tool
        self._in_tray = False
        if self._tray_icon and self.config.get("close_main_window_action", "exit") != "tray":
            self._tray_icon.hide()
        self.setWindowFlags(nf)
        self._restore_window_geometry_from_settings()
        self.show()
        # setWindowFlags 会重建原生窗口，须重新设置图标，否则任务栏易变为默认白纸图标
        try_set_window_icon(self)
        app_inst = QApplication.instance()
        if app_inst is not None:
            try_set_window_icon(app_inst)
        self.raise_()
        self.activateWindow()
        # 下一事件循环再绑一次图标，壳层有时在 HWND 就绪后才刷新任务栏
        def _reapply_icons():
            try_set_window_icon(self)
            inst = QApplication.instance()
            if inst is not None:
                try_set_window_icon(inst)
        QTimer.singleShot(0, _reapply_icons)
        try:
            self.reload_global_shortcuts()
        except Exception:
            if KEYBOARD_AVAILABLE:
                self.setup_global_shortcuts()
        if hasattr(self, "input_edit"):
            self.input_edit.setFocus()

    def _quit_application_from_tray(self):
        """托盘菜单：彻底退出。"""
        try:
            if self._tray_menu:
                self._tray_menu.hide()
        except Exception:
            pass
        self._force_quit = True
        self._in_tray = False
        if self._tray_icon:
            self._tray_icon.hide()
        if self._normal_window_flags is not None:
            try:
                self.setWindowFlags(self._normal_window_flags)
            except Exception:
                pass
        self.close()

    def _perform_full_exit(self, event):
        """真正退出：保存、停待办轮询、清理资源。"""
        try:
            if getattr(self, "_tray_icon", None):
                self._tray_icon.hide()
            self._save_window_geometry_to_settings()
            self._tear_down_global_shortcuts()
            self.save_unsaved_conversations_silent()
            if getattr(self.agent, "todo_service", None):
                self.agent.todo_service.shutdown_scheduler()
            self.cleanup_ai_agent_resources()
            self._shutdown_async_before_quit()
            try:
                self.statusBar().showMessage("正在保存会话记录...")
            except Exception:
                pass
            event.accept()
        except Exception:
            event.accept()
        # setQuitOnLastWindowClosed(False) 时，仅 accept 关闭主窗不会结束事件循环，须显式退出进程
        self._request_app_quit()

    def closeEvent(self, event):
        """关闭主窗口：按设置进入托盘或彻底退出。"""
        try:
            if getattr(self, "_force_quit", False):
                self._perform_full_exit(event)
                return
            if self.config.get("close_main_window_action", "exit") == "tray":
                if (
                    not QSystemTrayIcon.isSystemTrayAvailable()
                    or self._tray_icon is None
                ):
                    QMessageBox.warning(
                        self,
                        "系统托盘",
                        "当前环境不可用系统托盘，将直接退出程序。",
                    )
                    self._perform_full_exit(event)
                    return
                event.ignore()
                self._hide_to_tray()
                return
            self._perform_full_exit(event)
        except Exception:
            event.accept()
            self._request_app_quit()

    def save_unsaved_conversations_silent(self):
        """静默保存未保存的会话记录到识底深湖（无终端输出）"""
        try:
            # 检查开发者模式，如果开启则不保存
            if getattr(self.agent, 'developer_mode', False):
                return
            
            # 获取当前会话中的对话记录
            session_conversations = getattr(self.agent, 'session_conversations', [])
            
            # 🔥 修复：同时检查 memory_lake.current_conversation 中未保存的对话
            memory_conversations = getattr(self.agent.memory_lake, 'current_conversation', [])
            
            # 合并两个来源的对话记录
            all_conversations = []
            
            # 从 session_conversations 添加
            for conv in session_conversations:
                if not conv.get('saved', False):
                    all_conversations.append({
                        'user_input': conv.get('user_input', ''),
                        'ai_response': conv.get('ai_response', ''),
                        'source': 'session'
                    })
            
            # 从 memory_lake.current_conversation 添加（可能不在 session_conversations 中）
            for conv in memory_conversations:
                user_input = conv.get('user_input', '')
                ai_response = conv.get('ai_response', '')
                # 检查是否已经在 session_conversations 中
                found_in_session = False
                for session_conv in session_conversations:
                    if (session_conv.get('user_input') == user_input and 
                        session_conv.get('ai_response') == ai_response):
                        found_in_session = True
                        break
                if not found_in_session:
                    all_conversations.append({
                        'user_input': user_input,
                        'ai_response': ai_response,
                        'source': 'memory_lake'
                    })
            
            if not all_conversations:
                # 如果所有对话都已保存，但 memory_lake.current_conversation 还有内容，直接保存
                if memory_conversations:
                    topic = self.agent.memory_lake.summarize_and_save_topic(force_save=True)
                    if topic:
                        print(f"💾 退出时保存了 {len(memory_conversations)} 条对话到识底深湖，主题: {topic}")
                return
            
            # 🚀 修复：遍历未保存的对话记录，将它们添加到记忆系统中
            for conv in all_conversations:
                user_input = conv.get('user_input', '')
                ai_response = conv.get('ai_response', '')
                
                if user_input and ai_response:
                    # 如果已经在 memory_lake.current_conversation 中，跳过添加
                    already_in_memory = False
                    for mem_conv in memory_conversations:
                        if (mem_conv.get('user_input') == user_input and 
                            mem_conv.get('ai_response') == ai_response):
                            already_in_memory = True
                            break
                    
                    if not already_in_memory:
                        # 添加到记忆系统的当前会话中
                        self.agent.memory_lake.add_conversation(user_input, ai_response, self.agent.developer_mode, self.agent._mark_conversation_as_saved)
            
            # 🚀 修复：强制保存当前会话（即使不足3条）
            if self.agent.memory_lake.current_conversation:
                topic = self.agent.memory_lake.summarize_and_save_topic(force_save=True)
                if topic:
                    # 🚀 修复：在成功保存后，标记所有对话为已保存
                    for conv in all_conversations:
                        if conv.get('source') == 'session':
                            # 在 session_conversations 中找到并标记
                            for session_conv in session_conversations:
                                if (session_conv.get('user_input') == conv.get('user_input') and 
                                    session_conv.get('ai_response') == conv.get('ai_response')):
                                    session_conv['saved'] = True
                                    break
                else:
                    # 🚀 修复：即使保存失败，也标记为已保存，避免重复尝试
                    for conv in all_conversations:
                        if conv.get('source') == 'session':
                            for session_conv in session_conversations:
                                if (session_conv.get('user_input') == conv.get('user_input') and 
                                    session_conv.get('ai_response') == conv.get('ai_response')):
                                    session_conv['saved'] = True
                                    break
            
            # 🚀 修复：不清空session_conversations，只标记为已保存
            # 这样可以避免重复保存，同时保留对话历史
            
        except Exception as e:
            # 静默处理异常，避免终端输出
            pass
    
    def _shutdown_async_before_quit(self):
        """退出前阻塞关闭 Playwright/asyncio，须在 QApplication.quit 之前完成。"""
        try:
            from playwright_tool import shutdown_playwright_runtime
            from async_resource_manager import finalize_async_shutdown

            pw = getattr(self.agent, "playwright_tool", None)
            if pw is not None:
                try:
                    pw.close_sync()
                except Exception:
                    pass
            shutdown_playwright_runtime()
            finalize_async_shutdown()
        except Exception:
            pass

    def cleanup_ai_agent_resources(self):
        """清理 AI Agent 同步资源（async 已在 _shutdown_async_before_quit 中处理）。"""
        try:
            if hasattr(self.agent, "cleanup_tts"):
                self.agent.cleanup_tts()
        except Exception:
            pass
    
    def check_first_run_and_introduce(self):
        """检查是否是第一次运行，如果是则进行自我介绍；检查迁移状态"""
        try:
            # 优先检查是否有待迁移的记忆数据
            migration_status = self.agent.memory_lake.get_migration_status()
            if migration_status:
                old_count = migration_status["old_memory_count"]
                current_count = migration_status["current_memory_count"]
                
                migration_message = f"指挥官，我检测到旧版本的记忆文件，其中包含 {old_count} 条历史记忆。"
                migration_message += f"当前系统中有 {current_count} 条记忆。\n\n"
                migration_message += "是否将旧记忆迁移到新的智能回忆系统中？"
                migration_message += "迁移后您将获得更精准的记忆检索和四维度智能回忆功能。\n\n"
                migration_message += "请回答'是'或'否'。"
                
                # 主动发送迁移询问消息
                self.add_message("露尼西亚", migration_message)
                return
            
            # 检查记忆系统中的记忆条数
            memory_stats = self.agent.memory_lake.get_memory_stats()
            total_topics = memory_stats.get("total_topics", 0)
            
            # 如果记忆条数为0，说明是第一次运行
            if total_topics == 0:
                # 生成自我介绍内容
                introduction = self.generate_introduction()
                
                # 将自我介绍添加到聊天历史
                self.add_message("露尼西亚", introduction)
                
                # 将自我介绍添加到AI代理的会话记录中，标记为系统消息
                self.agent._add_session_conversation("系统", introduction)
                # 🎯 立即标记系统消息为已保存，避免退出时重复保存
                self.agent._mark_conversation_as_saved("系统", introduction)
                
                # 设置首次介绍标记
                self.first_introduction_given = True
                self.waiting_for_first_response = True
                
        except Exception as e:
            print(f"⚠️ 启动检查失败: {e}")
    
    def generate_introduction(self):
        """生成露尼西亚的自我介绍"""
        current_time = datetime.datetime.now()
        time_str = current_time.strftime("%H:%M")
        
        introduction = f"""（轻轻整理了一下衣服）指挥官，您好！我是露尼西亚，威廉的姐姐。

很高兴见到您！作为您的AI助手，我具备以下能力：
• 智能对话和问题解答
• 天气查询和实时信息
• 音乐推荐和文件管理
• 编程代码生成和帮助
• 多语言交流和翻译
• 记忆系统"识底深湖"

现在时间是 {time_str}，我已经准备好为您服务了。请告诉我您需要什么帮助吧！

（对了，如果您想了解我的更多功能，可以直接问我"你能做什么"哦~）"""
        
        return introduction