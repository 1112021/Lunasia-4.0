# -*- coding: utf-8 -*-
"""Lightweight transcript widgets used for code-aware chat rendering."""

from __future__ import annotations

import datetime
import html
import os
import re

from PyQt5.QtCore import Qt, QTimer, QRectF
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from combined_attachments import (
    CombinedAttachments,
    MAX_FILES,
    MAX_IMAGES,
    classify_path,
    validate_video_for_pending,
)

ATTACHMENT_MENU_STYLESHEET = """
    QMenu {
        background-color: #313244;
        color: #cdd6f4;
        border: 1px solid #45475a;
        padding: 4px 0;
    }
    QMenu::item {
        padding: 6px 24px 6px 12px;
        color: #cdd6f4;
        background: transparent;
    }
    QMenu::item:selected {
        background-color: #45475a;
        color: #cdd6f4;
    }
"""


_INLINE_CODE = re.compile(r"`([^`\n]+)`")

LANGUAGE_EXTENSIONS = {
    "python": ".py", "py": ".py",
    "javascript": ".js", "js": ".js",
    "typescript": ".ts", "ts": ".ts", "tsx": ".tsx", "jsx": ".jsx",
    "json": ".json", "html": ".html", "css": ".css", "sql": ".sql",
    "bash": ".sh", "shell": ".sh", "sh": ".sh",
    "powershell": ".ps1", "ps1": ".ps1",
    "cpp": ".cpp", "c++": ".cpp", "c": ".c",
    "csharp": ".cs", "cs": ".cs", "java": ".java", "go": ".go",
    "rust": ".rs", "rs": ".rs", "kotlin": ".kt", "swift": ".swift",
    "ruby": ".rb", "rb": ".rb", "php": ".php",
    "yaml": ".yml", "yml": ".yml", "xml": ".xml",
    "markdown": ".md", "md": ".md", "text": ".txt", "txt": ".txt",
}


class ChatTextSegment(QLabel):
    """Borderless normal transcript text with a small inline-code treatment."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._raw_text = ""
        self.setWordWrap(True)
        self.setTextFormat(Qt.RichText)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setStyleSheet(
            "QLabel { color: #cdd6f4; background: transparent; border: none; "
            "font-family: 'Microsoft YaHei UI', sans-serif; font-size: 14px; "
            "padding: 0px; margin: 0px; }"
        )

    @property
    def raw_text(self) -> str:
        return self._raw_text

    def append_text(self, text: str) -> None:
        if text:
            self._raw_text += text
            self._refresh()

    def retract(self, count: int) -> None:
        if count > 0:
            self._raw_text = self._raw_text[:-count]
            self._refresh()

    def _refresh(self) -> None:
        # 每条消息现在是独立的无框文本组件。原 QTextEdit 的末尾换行
        # 在这里若转换成 <br> 会多渲染一个空白行，因此仅显示时隐藏它。
        display_text = (
            self._raw_text[:-1] if self._raw_text.endswith("\n") else self._raw_text
        )
        escaped = html.escape(display_text)
        escaped = _INLINE_CODE.sub(
            lambda m: (
                "<span style=\"font-family: Consolas, 'Cascadia Mono', monospace; "
                "background:#313244; color:#f5c2e7; padding:1px 3px;\">"
                f"{m.group(1)}</span>"
            ),
            escaped,
        )
        self.setText(escaped.replace("\n", "<br>"))


class _LineIconButton(QPushButton):
    """Small dependency-free copy/pencil icon button."""

    def __init__(self, kind: str, parent=None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(28, 26)
        self.setText("")
        self.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 0; }"
            "QPushButton:hover:enabled { background: #313244; border-radius: 5px; }"
            "QPushButton:disabled { background: transparent; }"
        )

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor("#a6adc8" if self.isEnabled() else "#585b70")
        pen = QPen(color, 1.4)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        if self.kind == "copy":
            painter.drawRoundedRect(QRectF(9, 7, 10, 10), 2, 2)
            painter.drawRoundedRect(QRectF(6, 10, 10, 10), 2, 2)
        elif self.kind == "edit":
            painter.drawLine(7, 18, 17, 8)
            painter.drawLine(9, 20, 19, 10)
            painter.drawLine(7, 18, 9, 20)
            painter.drawLine(17, 8, 19, 10)
        else:
            painter.drawArc(QRectF(7, 7, 14, 14), 35 * 16, 290 * 16)
            painter.drawLine(20, 7, 20, 12)
            painter.drawLine(20, 7, 15, 7)
        painter.end()


class UserMessageActionBar(QWidget):
    """Copy and edit controls shown under one user message."""

    _ATTACH_INVALID_MSG = {
        "invalid": "文件不存在或无法读取。",
        "mutual": "图片与视频不能同时添加，请先删除其中一类。",
        "limit": "已达附件数量上限。",
        "dup": "该附件已添加。",
    }

    def __init__(
        self,
        user_text: str,
        *,
        image_paths=None,
        video_paths=None,
        file_paths=None,
        on_submit=None,
        on_edit_open=None,
        on_edit_close=None,
        edit_enabled: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._user_text = user_text or ""
        self._orig_images = list(image_paths or [])
        self._orig_video = (video_paths or [None])[0] if video_paths else None
        self._orig_files = list(file_paths or [])
        self._edit_images: list[str] = []
        self._edit_video: str | None = None
        self._edit_files: list[str] = []
        self._on_submit = on_submit
        self._on_edit_open = on_edit_open
        self._on_edit_close = on_edit_close
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self.setStyleSheet(
            "QWidget { background: transparent; border: none; }"
            "QPushButton { color: #a6adc8; background: transparent; border: none; "
            "border-radius: 5px; padding: 3px 10px; }"
            "QPushButton:hover:enabled { background: #313244; color: #cdd6f4; }"
            "QPushButton:disabled { color: #585b70; }"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 4)
        outer.setSpacing(4)

        self.actions = QWidget(self)
        action_layout = QHBoxLayout(self.actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(1)
        self.copy_button = _LineIconButton("copy", self.actions)
        self.copy_button.setToolTip("复制发送内容")
        self.copy_button.clicked.connect(self.copy_user_text)
        self.edit_button = _LineIconButton("edit", self.actions)
        self.edit_button.setToolTip("修改并重新发送")
        self.edit_button.setEnabled(bool(edit_enabled and on_submit is not None))
        self.edit_button.clicked.connect(self.open_editor)
        action_layout.addWidget(self.copy_button)
        action_layout.addWidget(self.edit_button)
        action_layout.addStretch(1)
        outer.addWidget(self.actions)

        self.editor_panel = QFrame(self)
        self.editor_panel.setObjectName("userEditPanel")
        self.editor_panel.setMinimumWidth(410)
        self.editor_panel.setMaximumWidth(620)
        self.editor_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.editor_panel.setStyleSheet(
            "QFrame#userEditPanel { background: #1e1e2e; border: 1px solid #89b4fa; "
            "border-radius: 15px; }"
            "QPlainTextEdit { color: #cdd6f4; background: transparent; border: none; "
            "padding: 3px 7px; font-size: 14px; }"
            "QLabel { color: #7f849c; background: transparent; border: none; }"
            "QPushButton { border: 1px solid #45475a; border-radius: 12px; "
            "padding: 5px 14px; background: transparent; color: #cdd6f4; }"
            "QPushButton:hover:enabled { background: #313244; }"
            "QPushButton#editSend { background: #89b4fa; color: #1e1e2e; "
            "border-color: #89b4fa; }"
            "QPushButton#editSend:disabled { background: #585b70; color: #a6adc8; }"
            "QPushButton#editAdd { min-width: 28px; max-width: 28px; padding: 0; "
            "border-radius: 8px; font-size: 16px; font-weight: bold; }"
            "QScrollArea { background: transparent; border: none; }"
        )
        panel_layout = QVBoxLayout(self.editor_panel)
        panel_layout.setContentsMargins(10, 8, 8, 8)
        panel_layout.setSpacing(6)

        self.attach_row = QHBoxLayout()
        self.attach_row.setSpacing(6)
        self.attach_scroll = QScrollArea(self.editor_panel)
        self.attach_scroll.setWidgetResizable(True)
        self.attach_scroll.setFixedHeight(56)
        self.attach_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.attach_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.attach_cards_host = QWidget()
        self.attach_cards_host.setStyleSheet("background: transparent;")
        self.attach_cards_layout = QHBoxLayout(self.attach_cards_host)
        self.attach_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.attach_cards_layout.setSpacing(8)
        self.attach_cards_layout.addStretch(1)
        self.attach_scroll.setWidget(self.attach_cards_host)
        self.add_attach_btn = QPushButton("+", self.editor_panel)
        self.add_attach_btn.setObjectName("editAdd")
        self.add_attach_btn.setFixedSize(28, 28)
        self.add_attach_btn.setToolTip("添加或更换附件")
        self.add_attach_btn.clicked.connect(self._show_add_attachment_menu)
        panel_layout.addLayout(self.attach_row)

        self.editor = QPlainTextEdit(self.editor_panel)
        self.editor.setPlainText(self._user_text)
        self.editor.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel_layout.addWidget(self.editor)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("取消", self.editor_panel)
        cancel_button.clicked.connect(self.close_editor)
        self.send_button = QPushButton("发送", self.editor_panel)
        self.send_button.setObjectName("editSend")
        self.send_button.clicked.connect(self.submit_edit)
        button_row.addWidget(cancel_button)
        button_row.addWidget(self.send_button)
        panel_layout.addLayout(button_row)

        self.editor.textChanged.connect(self._sync_send_enabled)
        self.editor.textChanged.connect(self._adjust_editor_height)
        outer.addWidget(self.editor_panel)
        self.editor_panel.hide()
        self._adjust_editor_height()
        self._sync_send_enabled()

    def set_edit_enabled(self, enabled: bool) -> None:
        self.edit_button.setEnabled(bool(enabled and self._on_submit is not None))

    def copy_user_text(self) -> None:
        QApplication.clipboard().setText(self._user_text)
        self.copy_button.setToolTip("已复制")
        QTimer.singleShot(
            1200, lambda: self.copy_button.setToolTip("复制发送内容")
        )

    def _reset_edit_attachments(self) -> None:
        self._edit_images = list(self._orig_images)
        self._edit_video = self._orig_video
        self._edit_files = list(self._orig_files)
        self._rebuild_attachment_strip()

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

    def _make_attachment_card(self, path: str, kind: str, on_remove) -> QFrame:
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lstrip(".").upper() or "文件"
        missing = not os.path.isfile(path)
        size_text = "" if missing else self._format_file_size(path)

        card = QFrame()
        card.setFixedSize(190, 52)
        card.setToolTip(name + ("（文件不存在）" if missing else ""))
        border = "#f38ba8" if missing else "#45475a"
        card.setStyleSheet(
            f"QFrame {{ background-color: #313244; border: 1px solid {border}; "
            "border-radius: 10px; }"
        )

        row = QHBoxLayout(card)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(8)

        icon = QLabel()
        icon.setFixedSize(36, 36)
        icon.setAlignment(Qt.AlignCenter)
        if kind == "image" and not missing:
            pix = QPixmap(path)
            if not pix.isNull():
                icon.setPixmap(
                    pix.scaled(
                        36, 36, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
                    )
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
        name_label.setStyleSheet(
            "color: #cdd6f4; font-size: 12px; border: none; background: transparent;"
        )
        fm = name_label.fontMetrics()
        name_label.setText(fm.elidedText(name, Qt.ElideMiddle, 110))
        if missing:
            meta = "文件不存在"
        elif kind == "image":
            meta = "图片 · " + size_text if size_text else "图片"
        elif kind == "video":
            meta = "视频 · " + size_text if size_text else "视频"
        else:
            meta = f"{ext} · {size_text}" if size_text else ext
        meta_label = QLabel(meta)
        meta_label.setStyleSheet(
            "color: #7f849c; font-size: 10px; border: none; background: transparent;"
        )
        if missing:
            meta_label.setStyleSheet(
                "color: #f38ba8; font-size: 10px; border: none; background: transparent;"
            )
        text_col.addWidget(name_label)
        text_col.addWidget(meta_label)
        row.addLayout(text_col, 1)

        close_btn = QPushButton("×", card)
        close_btn.setFixedSize(18, 18)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton { background-color: rgba(30,30,46,0.85); color: #cdd6f4;"
            " border: 1px solid #585b70; border-radius: 9px; font-size: 12px; "
            "font-weight: bold; padding: 0; }"
            "QPushButton:hover { background-color: #f38ba8; color: #1e1e2e; }"
        )
        close_btn.clicked.connect(lambda: on_remove(path))
        close_btn.move(card.width() - 20, 3)
        close_btn.raise_()
        return card

    def _rebuild_attachment_strip(self) -> None:
        while self.attach_cards_layout.count() > 1:
            item = self.attach_cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        has_any = False
        for path in self._edit_images:
            card = self._make_attachment_card(path, "image", self._remove_edit_image)
            self.attach_cards_layout.insertWidget(
                self.attach_cards_layout.count() - 1, card
            )
            has_any = True
        if self._edit_video:
            card = self._make_attachment_card(
                self._edit_video, "video", lambda _p: self._remove_edit_video()
            )
            self.attach_cards_layout.insertWidget(
                self.attach_cards_layout.count() - 1, card
            )
            has_any = True
        for path in self._edit_files:
            card = self._make_attachment_card(path, "file", self._remove_edit_file)
            self.attach_cards_layout.insertWidget(
                self.attach_cards_layout.count() - 1, card
            )
            has_any = True

        self.attach_scroll.setVisible(has_any)
        self._layout_attach_row(has_any)
        self._sync_send_enabled()

    def _layout_attach_row(self, has_attachments: bool) -> None:
        """无附件时 + 在左上角；有附件时在附件条右侧。"""
        while self.attach_row.count():
            self.attach_row.takeAt(0)
        if has_attachments:
            self.attach_row.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.attach_row.addWidget(self.attach_scroll, 1)
            self.attach_row.addWidget(self.add_attach_btn, 0, Qt.AlignTop)
        else:
            self.attach_row.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            self.attach_row.addWidget(
                self.add_attach_btn, 0, Qt.AlignLeft | Qt.AlignTop
            )
            self.attach_row.addStretch(1)

    def _remove_edit_image(self, path: str) -> None:
        if path in self._edit_images:
            self._edit_images.remove(path)
        self._rebuild_attachment_strip()

    def _remove_edit_video(self) -> None:
        self._edit_video = None
        self._rebuild_attachment_strip()

    def _remove_edit_file(self, path: str) -> None:
        if path in self._edit_files:
            self._edit_files.remove(path)
        self._rebuild_attachment_strip()

    def _try_add_edit_one(self, path: str, kind: str) -> str:
        if not path or not os.path.isfile(path):
            return "invalid"
        if kind == "image":
            if self._edit_video:
                return "mutual"
            if len(self._edit_images) >= MAX_IMAGES:
                return "limit"
            if path in self._edit_images:
                return "dup"
            self._edit_images.append(path)
        elif kind == "video":
            if self._edit_images:
                return "mutual"
            if self._edit_video:
                return "limit"
            ok, _msg = validate_video_for_pending(path)
            if not ok:
                return "invalid"
            self._edit_video = path
        elif kind == "file":
            if len(self._edit_files) >= MAX_FILES:
                return "limit"
            if path in self._edit_files:
                return "dup"
            self._edit_files.append(path)
        else:
            return "invalid"
        return "ok"

    def _warn_attachment_status(self, status: str) -> None:
        if status == "dup":
            return
        QMessageBox.warning(
            self,
            "附件",
            self._ATTACH_INVALID_MSG.get(status, "无法添加该附件。"),
        )

    def _show_add_attachment_menu(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(ATTACHMENT_MENU_STYLESHEET)
        if not self._edit_video and len(self._edit_images) < MAX_IMAGES:
            image_action = menu.addAction("📷 添加图片")
            image_action.triggered.connect(self._pick_edit_images)
        if not self._edit_images and not self._edit_video:
            video_action = menu.addAction("🎬 添加视频")
            video_action.triggered.connect(self._pick_edit_video)
        if len(self._edit_files) < MAX_FILES:
            file_action = menu.addAction("📄 添加文件")
            file_action.triggered.connect(self._pick_edit_files)
        if not menu.actions():
            QMessageBox.information(
                self, "附件", "当前附件已达上限或类型互斥，请先删除后再添加。"
            )
            return
        menu.exec_(self.add_attach_btn.mapToGlobal(self.add_attach_btn.rect().bottomLeft()))

    def _pick_edit_images(self) -> None:
        if self._edit_video:
            QMessageBox.warning(
                self, "附件", "已添加视频，不能与图片同时添加。请先删除视频。"
            )
            return
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择图片（可多选）",
            "",
            "图片文件 (*.jpg *.jpeg *.png *.gif *.bmp *.tiff *.webp)",
        )
        added = 0
        for path in file_paths:
            if classify_path(path) != "image":
                continue
            status = self._try_add_edit_one(path, "image")
            if status == "ok":
                added += 1
            elif status == "limit":
                self._warn_attachment_status(status)
                break
            elif status != "dup":
                self._warn_attachment_status(status)
        if added:
            self._rebuild_attachment_strip()

    def _pick_edit_video(self) -> None:
        if self._edit_images:
            QMessageBox.warning(
                self, "附件", "已添加图片，不能与视频同时添加。请先删除图片。"
            )
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择视频",
            "",
            "视频文件 (*.mp4 *.avi *.mov *.mkv *.flv *.wmv *.webm *.m4v *.3gp)",
        )
        if file_path and classify_path(file_path) == "video":
            status = self._try_add_edit_one(file_path, "video")
            if status == "ok":
                self._rebuild_attachment_strip()
            elif status != "dup":
                self._warn_attachment_status(status)

    def _pick_edit_files(self) -> None:
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择文件（可多选）",
            "",
            "支持的文件 (*.pdf *.csv *.xlsx *.xls *.docx *.doc *.py *.java *.js *.jsx "
            "*.ts *.tsx *.cpp *.c *.h *.go *.rs);;所有文件 (*.*)",
        )
        if not file_paths:
            return
        added = 0
        unsupported = 0
        for path in file_paths:
            if classify_path(path) != "file":
                unsupported += 1
                continue
            status = self._try_add_edit_one(path, "file")
            if status == "ok":
                added += 1
            elif status == "limit":
                self._warn_attachment_status(status)
                break
            elif status != "dup":
                self._warn_attachment_status(status)
        if added:
            self._rebuild_attachment_strip()
        if unsupported:
            QMessageBox.warning(
                self,
                "附件",
                f"{unsupported} 个文件类型暂不支持，已跳过（请选择文档或代码文件）。",
            )

    def _build_edit_attachments(self) -> CombinedAttachments:
        return CombinedAttachments(
            image_paths=list(self._edit_images),
            video_paths=[self._edit_video] if self._edit_video else [],
            file_paths=list(self._edit_files),
        )

    def _has_edit_attachments(self) -> bool:
        return bool(
            self._edit_images or self._edit_video or self._edit_files
        )

    def open_editor(self) -> None:
        if not self.edit_button.isEnabled():
            return
        self.editor.setPlainText(self._user_text)
        self._reset_edit_attachments()
        self.actions.hide()
        self.editor_panel.show()
        self.edit_button.setEnabled(False)
        if self._on_edit_open:
            self._on_edit_open(self)
        self.editor.setFocus()
        cursor = self.editor.textCursor()
        cursor.movePosition(cursor.End)
        self.editor.setTextCursor(cursor)

    def close_editor(self) -> None:
        self.editor_panel.hide()
        self.actions.show()
        self.edit_button.setEnabled(self._on_submit is not None)
        if self._on_edit_close:
            self._on_edit_close(self)

    def submit_edit(self) -> None:
        if not self.send_button.isEnabled() or self._on_submit is None:
            return
        text = self.editor.toPlainText().strip()
        attachments = self._build_edit_attachments()
        if not text and attachments.is_empty():
            return
        missing = [
            os.path.basename(path)
            for path in (
                list(attachments.image_paths)
                + list(attachments.video_paths)
                + list(attachments.file_paths)
            )
            if not os.path.isfile(path)
        ]
        if missing:
            QMessageBox.warning(
                self,
                "附件",
                "以下附件不存在或无法读取，请删除或重新选择：\n"
                + "、".join(missing),
            )
            return
        self.editor_panel.hide()
        if self._on_edit_close:
            self._on_edit_close(self)
        self._on_submit(text, attachments)

    def _sync_send_enabled(self) -> None:
        has_content = bool(self.editor.toPlainText().strip())
        self.send_button.setEnabled(has_content or self._has_edit_attachments())

    def _adjust_editor_height(self) -> None:
        """Keep short edits input-sized; grow vertically for wrapped long text."""
        document_height = int(self.editor.document().size().height())
        height = max(32, min(150, document_height + 10))
        self.editor.setFixedHeight(height)


class ReplyActionBar(QWidget):
    """Actions shown below one completed assistant reply."""

    def __init__(
        self,
        reply_text: str,
        on_regenerate=None,
        *,
        regenerate_enabled: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._reply_text = reply_text or ""
        self._on_regenerate = on_regenerate
        self._copy_cooling_down = False
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self.setStyleSheet(
            "QWidget { background: transparent; border: none; }"
            "QPushButton { color: #a6adc8; background: transparent; border: none; "
            "padding: 0px; border-radius: 5px; }"
            "QPushButton:hover:enabled { color: #cdd6f4; background: #313244; }"
            "QPushButton:disabled { color: #585b70; background: transparent; }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 4)
        layout.setSpacing(2)

        self.copy_button = _LineIconButton("copy", self)
        self.copy_button.setToolTip("复制这条回复")
        self.copy_button.clicked.connect(self.copy_reply)
        layout.addWidget(self.copy_button)

        self.regenerate_button = _LineIconButton("refresh", self)
        self.regenerate_button.setToolTip("重新生成最新回复")
        self.regenerate_button.setEnabled(
            bool(regenerate_enabled and on_regenerate is not None)
        )
        self.regenerate_button.clicked.connect(self._regenerate)
        layout.addWidget(self.regenerate_button)
        layout.addStretch(1)

    def set_regenerate_enabled(self, enabled: bool) -> None:
        self.regenerate_button.setEnabled(
            bool(enabled and self._on_regenerate is not None)
        )

    def copy_reply(self) -> None:
        if self._copy_cooling_down:
            return
        QApplication.clipboard().setText(self._reply_text)
        self._copy_cooling_down = True
        self.copy_button.setToolTip("已复制")
        self.copy_button.setEnabled(False)

        def reset() -> None:
            self._copy_cooling_down = False
            self.copy_button.setToolTip("复制这条回复")
            self.copy_button.setEnabled(True)

        QTimer.singleShot(1500, reset)

    def _regenerate(self) -> None:
        if self._on_regenerate is not None:
            self._on_regenerate()


class CodeBlockCard(QFrame):
    """A streaming-friendly code block with copy and save-as actions."""

    def __init__(self, language: str = "text", parent=None) -> None:
        super().__init__(parent)
        self.language = language or "text"
        self._copy_cooling_down = False
        self.setObjectName("codeBlockCard")
        self.setStyleSheet(
            "QFrame#codeBlockCard { background: #181825; border: 1px solid #45475a; "
            "border-radius: 7px; }"
            "QLabel { color: #bac2de; background: transparent; border: none; }"
            "QPushButton { color: #cdd6f4; background: transparent; border: none; "
            "padding: 3px 7px; border-radius: 4px; }"
            "QPushButton:hover:enabled { background: #313244; }"
            "QPushButton:disabled { color: #6c7086; }"
            "QPlainTextEdit { background: #11111b; color: #cdd6f4; border: none; "
            "border-bottom-left-radius: 7px; border-bottom-right-radius: 7px; "
            "padding: 8px; selection-background-color: #585b70; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget(self)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 5, 6, 5)
        header_layout.setSpacing(4)
        self.language_label = QLabel(self.language, header)
        self.language_label.setStyleSheet("font-family: Consolas, 'Cascadia Mono', monospace; color: #a6adc8;")
        self.status_label = QLabel("接收中…", header)
        self.status_label.setStyleSheet("color: #6c7086; font-size: 12px;")
        header_layout.addWidget(self.language_label)
        header_layout.addWidget(self.status_label)
        header_layout.addStretch(1)

        self.copy_button = QPushButton("复制", header)
        self.download_button = QPushButton("下载", header)
        self.copy_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.copy_button.clicked.connect(self.copy_code)
        self.download_button.clicked.connect(self.download_code)
        header_layout.addWidget(self.copy_button)
        header_layout.addWidget(self.download_button)
        outer.addWidget(header)

        self.editor = QPlainTextEdit(self)
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(10)
        self.editor.setFont(font)
        outer.addWidget(self.editor)
        self._adjust_editor_height()

    def append_code(self, text: str) -> None:
        if not text:
            return
        cursor = self.editor.textCursor()
        cursor.movePosition(cursor.End)
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
        self._adjust_editor_height()
        self.editor.verticalScrollBar().setValue(self.editor.verticalScrollBar().maximum())

    def retract(self, count: int) -> None:
        if count <= 0:
            return
        content = self.editor.toPlainText()
        self.editor.setPlainText(content[:-count])
        cursor = self.editor.textCursor()
        cursor.movePosition(cursor.End)
        self.editor.setTextCursor(cursor)
        self._adjust_editor_height()

    def _adjust_editor_height(self) -> None:
        """Grow until roughly sixteen lines, then leave scrolling internal."""
        lines = max(3, min(16, self.editor.document().blockCount()))
        height = lines * self.editor.fontMetrics().lineSpacing() + 18
        self.editor.setFixedHeight(height)

    def complete(self) -> None:
        self.status_label.hide()
        self.copy_button.setEnabled(True)
        self.download_button.setEnabled(True)

    def copy_code(self) -> None:
        if self._copy_cooling_down:
            return
        QApplication.clipboard().setText(self.editor.toPlainText())
        self._copy_cooling_down = True
        self.copy_button.setText("已复制 ✓")
        self.copy_button.setEnabled(False)

        def reset() -> None:
            self._copy_cooling_down = False
            self.copy_button.setText("复制")
            self.copy_button.setEnabled(True)

        QTimer.singleShot(1500, reset)

    def download_code(self) -> None:
        extension = LANGUAGE_EXTENSIONS.get(self.language.lower(), ".txt")
        default_name = f"code_{datetime.datetime.now().strftime('%H%M%S')}{extension}"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存代码",
            default_name,
            f"{self.language.upper()} 文件 (*{extension});;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as file:
                file.write(self.editor.toPlainText())
        except OSError as exc:
            self.status_label.setText(f"保存失败：{exc}")
            self.status_label.show()
