# -*- coding: utf-8 -*-
"""应用窗口图标：优先 icon.ico（Windows 任务栏更稳），其次 PNG。"""
import os
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QPixmap

_CACHED_ICON = None


def _project_root():
    return os.path.dirname(os.path.abspath(__file__))


def _icon_paths():
    root = _project_root()
    # .ico 优先：Windows 在 setWindowFlags 重建 HWND 后，壳层对 ico 的 HICON 绑定更可靠
    return [
        os.path.join(root, "icon.ico"),
        os.path.join(root, "icon_2048.png"),
        os.path.join(root, "assets", "icon_2048.png"),
    ]


def apply_windows_taskbar_identity():
    """
    须在创建 QApplication 之前调用。
    为 python.exe 托管的进程固定 AppUserModelID，避免任务栏白板图标 / 分组错乱。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Lucinia.Lunasia.DesktopAI.1"
        )
    except Exception:
        pass


def get_application_icon():
    """
    返回应用图标。优先 icon.ico，其次 icon_2048.png。
    找不到则返回空 QIcon。
    """
    global _CACHED_ICON
    if _CACHED_ICON is not None:
        return _CACHED_ICON

    for path in _icon_paths():
        if not os.path.isfile(path):
            continue
        lower = path.lower()
        if lower.endswith(".ico"):
            _CACHED_ICON = QIcon(path)
            return _CACHED_ICON
        pix = QPixmap(path)
        if pix.isNull():
            continue
        icon = QIcon()
        for size in (16, 20, 24, 32, 40, 48, 64, 96, 128, 256):
            icon.addPixmap(
                pix.scaled(
                    size,
                    size,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
        _CACHED_ICON = icon
        return _CACHED_ICON

    _CACHED_ICON = QIcon()
    return _CACHED_ICON


def try_set_window_icon(widget):
    """对 QMainWindow、QDialog、QApplication 等调用 setWindowIcon（有图标时）。"""
    icon = get_application_icon()
    if not icon.isNull():
        widget.setWindowIcon(icon)
