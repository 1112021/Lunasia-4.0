# -*- coding: utf-8 -*-
"""
露尼西亚AI助手 - 主程序入口
重构后的模块化版本
"""

import sys
import os

# 在导入任何其他模块之前，先设置警告过滤器
import warnings
warnings.simplefilter("ignore", ResourceWarning)
warnings.simplefilter("ignore", RuntimeWarning)
warnings.filterwarnings("ignore")

import atexit
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QFont, QPalette, QColor
from async_resource_manager import cleanup_on_exit

# 设置Windows控制台编码为UTF-8，避免emoji显示错误
if sys.platform == 'win32':
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)  # UTF-8
        # 同时设置Python的标准输出编码
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception as e:
        print(f"Warning: Failed to set console encoding: {e}")

# 运行日志（接管 stdout/stderr，按日写入 logs/）
from file_logging import setup_app_logging, update_app_logging

setup_app_logging()

# 额外的警告抑制
import asyncio
import logging

# Windows: 抑制退出时 asyncio 传输清理触发的 "Event loop is closed"（不影响功能）
if sys.platform == 'win32':
    def _unraisablehook(unraisable):
        try:
            exc_type = getattr(unraisable, 'exc_type', None)
            exc_value = getattr(unraisable, 'exc_value', None)
            if exc_type is RuntimeError and exc_value is not None:
                msg = str(exc_value)
                if 'Event loop is closed' in msg:
                    return  # 静默忽略
        except Exception:
            pass
        sys.__unraisablehook__(unraisable)
    sys.unraisablehook = _unraisablehook

# 设置asyncio日志级别为WARNING，避免过多调试信息
logging.getLogger('asyncio').setLevel(logging.WARNING)
logging.getLogger('playwright').setLevel(logging.WARNING)

# 导入自定义模块
from config import load_config
from main_window import AIAgentApp
from app_icon import try_set_window_icon, apply_windows_taskbar_identity
from app_single_instance import try_activate_existing_instance, SingleInstanceGuard

def main():
    """主程序入口"""
    argv_qt = [a for a in sys.argv if a != "--startup-tray"]
    startup_tray_cli = len(argv_qt) != len(sys.argv)
    # 设置异常处理，避免程序退出时的异常输出
    import signal
    import atexit
    window_holder = [None]

    def cleanup_window_tts():
        window = window_holder[0]
        if window is not None:
            try:
                window.agent.cleanup_tts()
            except Exception:
                pass
    
    def signal_handler(signum, frame):
        """信号处理器，静默退出"""
        cleanup_window_tts()
        cleanup_on_exit()
        sys.exit(0)
    
    # 注册信号处理器和退出清理函数
    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        atexit.register(cleanup_on_exit)
        atexit.register(cleanup_window_tts)
    except Exception:
        pass
    
    apply_windows_taskbar_identity()

    # 创建Qt应用程序
    app = QApplication(argv_qt)
    # 托盘常驻：主窗可隐藏，勿在「关闭设置等对话框」时因 lastWindowClosed 默认 true 而退出整个进程
    app.setQuitOnLastWindowClosed(False)

    if try_activate_existing_instance():
        sys.exit(0)

    instance_guard = SingleInstanceGuard(app)

    try_set_window_icon(app)
    
    # 设置应用程序样式
    app.setStyle("Fusion")
    
    # 创建调色板
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(30, 30, 46))  # 深蓝色背景
    palette.setColor(QPalette.WindowText, QColor(205, 214, 244))  # 浅蓝色文本
    palette.setColor(QPalette.Base, QColor(24, 24, 37))  # 更深的基础色
    palette.setColor(QPalette.AlternateBase, QColor(49, 50, 68))  # 交替基础色
    palette.setColor(QPalette.ToolTipBase, QColor(49, 50, 68))  # 工具提示背景：深色
    palette.setColor(QPalette.ToolTipText, QColor(255, 255, 255))  # 工具提示文字：白字
    palette.setColor(QPalette.Text, QColor(205, 214, 244))  # 文本颜色
    palette.setColor(QPalette.Button, QColor(49, 50, 68))  # 按钮颜色
    palette.setColor(QPalette.ButtonText, QColor(205, 214, 244))  # 按钮文本
    palette.setColor(QPalette.BrightText, QColor(245, 224, 220))  # 亮色文本
    palette.setColor(QPalette.Highlight, QColor(137, 180, 250))  # 高亮色
    palette.setColor(QPalette.HighlightedText, QColor(24, 24, 37))  # 高亮文本
    
    app.setPalette(palette)

    # 设置字体
    font = QFont("Microsoft YaHei UI", 10)
    app.setFont(font)
    
    # 加载配置
    config = load_config()
    update_app_logging(config)

    # 创建主窗口
    window = AIAgentApp(config, startup_argument_tray=startup_tray_cli)
    window_holder[0] = window
    app.aboutToQuit.connect(cleanup_window_tts)
    instance_guard.set_target_window(window)
    # 开机 --startup-tray：不先 show 主窗，首帧再进托盘，避免面板闪一下
    if startup_tray_cli:
        QTimer.singleShot(0, window._apply_cli_startup_tray)
    else:
        window.show()

    # 再次设置调色板与样式表，强制 tooltip 白字（深底白字，保证可读）
    palette = app.palette()
    palette.setColor(QPalette.ToolTipBase, QColor(49, 50, 68))
    palette.setColor(QPalette.ToolTipText, QColor(255, 255, 255))
    app.setPalette(palette)
    app.setStyleSheet(app.styleSheet() + """
        QToolTip {
            background-color: #313244;
            color: #ffffff;
            border: 1px solid #585b70;
            border-radius: 4px;
            padding: 8px 10px;
            font-size: 13px;
        }
    """)

    # 运行应用程序
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()


