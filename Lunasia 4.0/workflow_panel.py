# -*- coding: utf-8 -*-
"""Compact collapsible workflow panel for the chat transcript."""

from __future__ import annotations

from collections import OrderedDict

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class WorkflowPanel(QFrame):
    """Shows short workflow result sentences without timestamps or verbose logs."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._expanded = True
        self._rows = OrderedDict()
        self.setObjectName("workflowPanel")
        self.setStyleSheet(
            "QFrame#workflowPanel { background: transparent; border: none; }"
            "QPushButton#workflowHeader { color: #a6adc8; background: transparent; "
            "border: none; text-align: left; padding: 3px 0px; font-size: 13px; }"
            "QPushButton#workflowHeader:hover { color: #cdd6f4; }"
            "QWidget#workflowBody { background: transparent; border: none; }"
            "QLabel { color: #7f849c; background: transparent; border: none; "
            "font-family: 'Microsoft YaHei UI', sans-serif; font-size: 12px; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 3)
        outer.setSpacing(1)

        self.header_button = QPushButton("处理中…  ▴", self)
        self.header_button.setObjectName("workflowHeader")
        self.header_button.setCursor(Qt.PointingHandCursor)
        self.header_button.clicked.connect(self.toggle)
        outer.addWidget(self.header_button)

        self.body = QWidget(self)
        self.body.setObjectName("workflowBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(12, 0, 0, 2)
        self.body_layout.setSpacing(2)
        outer.addWidget(self.body)

    def update_step(self, key: str, title: str, phase: str = "active") -> None:
        if not key or not title:
            return
        label = self._rows.get(key)
        if label is None:
            label = QLabel(self.body)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._rows[key] = label
            self.body_layout.addWidget(label)
        marker = "○" if phase == "active" else ("×" if phase == "failed" else "●")
        label.setText(f"{marker}  {title}")

    def finish(self, elapsed_seconds: int, auto_collapse: bool = True) -> None:
        seconds = max(1, int(elapsed_seconds))
        self.header_button.setText(f"已处理（用时 {seconds} 秒）  ▴")
        if auto_collapse:
            QTimer.singleShot(400, self.collapse)

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def collapse(self) -> None:
        self.set_expanded(False)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self.body.setVisible(self._expanded)
        text = self.header_button.text()
        if text.endswith(("▴", "▾")):
            text = text[:-1].rstrip()
        self.header_button.setText(f"{text}  {'▴' if self._expanded else '▾'}")
