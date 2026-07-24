# -*- coding: utf-8 -*-
"""自定义 OpenAI 兼容模型管理对话框。"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from custom_models_store import (
    CAP_TEXT,
    CAP_VISION,
    _api_extra_raw_text,
    apply_fallback_on_delete,
    can_remove_or_disable,
    find_custom_by_id,
    get_custom_models,
    mask_api_key,
    new_custom_entry,
    normalize_base_url,
    validate_custom_entry,
)
from llm_vision_router import test_custom_text, test_custom_vision


class CustomModelEditDialog(QDialog):
    def __init__(self, config: dict, entry: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.config = config
        self.entry = dict(entry) if entry else None
        self.result_entry = None
        self.setWindowTitle("编辑自定义模型" if entry else "添加自定义模型")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("显示名称（唯一，不区分大小写）")
        form.addRow("名称:", self.name_edit)

        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText(
            "完整 base_url，含 /v1，如 https://api.example.com/v1"
        )
        form.addRow("API URL:", self.base_url_edit)

        self.model_id_edit = QLineEdit()
        self.model_id_edit.setPlaceholderText("模型 ID，如 gpt-5.6-terra 或 deepseek-v4-flash")
        form.addRow("模型名:", self.model_id_edit)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("留空表示不修改已有密钥")
        form.addRow("API 密钥:", self.api_key_edit)

        self.api_extra_edit = QPlainTextEdit()
        self.api_extra_edit.setPlaceholderText(
            '可选。JSON 对象或数组，留空表示不传。\n'
            '示例（DashScope 联网）：\n'
            '{"extra_body":{"enable_search":true,"search_options":{"search_strategy":"agent"}}}'
        )
        self.api_extra_edit.setMaximumHeight(100)
        form.addRow("API 扩展:", self.api_extra_edit)

        cap_row = QHBoxLayout()
        self.text_cb = QCheckBox("文本")
        self.vision_cb = QCheckBox("视觉")
        cap_row.addWidget(self.text_cb)
        cap_row.addWidget(self.vision_cb)
        cap_row.addStretch()
        form.addRow("能力:", cap_row)

        self.enabled_cb = QCheckBox("启用")
        self.enabled_cb.setChecked(True)
        form.addRow("", self.enabled_cb)

        layout.addLayout(form)

        test_row = QHBoxLayout()
        self.test_text_btn = QPushButton("测试文本")
        self.test_vision_btn = QPushButton("测试视觉")
        test_row.addWidget(self.test_text_btn)
        test_row.addWidget(self.test_vision_btn)
        test_row.addStretch()
        layout.addLayout(test_row)

        self.test_text_btn.clicked.connect(self._on_test_text)
        self.test_vision_btn.clicked.connect(self._on_test_vision)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if self.entry:
            self.name_edit.setText(self.entry.get("name", ""))
            self.base_url_edit.setText(self.entry.get("base_url", ""))
            self.model_id_edit.setText(self.entry.get("model_id", ""))
            masked = mask_api_key(self.entry.get("api_key", ""))
            if masked:
                self.api_key_edit.setPlaceholderText(f"当前: {masked}（留空不修改）")
            caps = self.entry.get("capabilities") or []
            self.text_cb.setChecked(CAP_TEXT in caps)
            self.vision_cb.setChecked(CAP_VISION in caps)
            self.enabled_cb.setChecked(bool(self.entry.get("enabled", True)))
            extra_text = _api_extra_raw_text(self.entry)
            if extra_text:
                self.api_extra_edit.setPlainText(extra_text)

    def _draft_entry(self) -> dict:
        caps = []
        if self.text_cb.isChecked():
            caps.append(CAP_TEXT)
        if self.vision_cb.isChecked():
            caps.append(CAP_VISION)
        api_extra = self.api_extra_edit.toPlainText().strip()
        if self.entry:
            out = dict(self.entry)
            out.update(
                {
                    "name": self.name_edit.text().strip(),
                    "base_url": normalize_base_url(self.base_url_edit.text()),
                    "model_id": self.model_id_edit.text().strip(),
                    "capabilities": caps,
                    "enabled": self.enabled_cb.isChecked(),
                    "api_extra": api_extra,
                }
            )
            new_key = self.api_key_edit.text().strip()
            if new_key:
                out["api_key"] = new_key
            return out
        entry = new_custom_entry(
            self.name_edit.text(),
            self.base_url_edit.text(),
            self.model_id_edit.text(),
            self.api_key_edit.text(),
            caps,
            enabled=self.enabled_cb.isChecked(),
        )
        entry["api_extra"] = api_extra
        return entry

    def _on_test_text(self):
        entry = self._draft_entry()
        ok, msg = test_custom_text(entry)
        if ok:
            QMessageBox.information(self, "测试成功", f"文本测试通过：{msg}")
        else:
            QMessageBox.warning(self, "测试失败", msg)

    def _on_test_vision(self):
        if not self.vision_cb.isChecked():
            QMessageBox.warning(self, "提示", "请先勾选「视觉」能力")
            return
        entry = self._draft_entry()
        ok, msg = test_custom_vision(entry)
        if ok:
            QMessageBox.information(self, "测试成功", f"视觉测试通过：{msg}")
        else:
            QMessageBox.warning(self, "测试失败", msg)

    def _on_accept(self):
        entry = self._draft_entry()
        exclude = entry.get("id", "") if self.entry else ""
        ok, err = validate_custom_entry(entry, self.config, exclude_id=exclude)
        if not ok:
            QMessageBox.warning(self, "校验失败", err)
            return
        if self.entry and not self.enabled_cb.isChecked():
            allowed, msg = can_remove_or_disable(
                self.config, entry.get("id", ""), removing=False
            )
            if not allowed:
                QMessageBox.warning(self, "无法禁用", msg)
                return
        self.result_entry = entry
        self.accept()


class CustomModelsDialog(QDialog):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("自定义模型管理")
        self.setMinimumSize(720, 360)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "添加 OpenAI 兼容端点。URL 请填写完整 base_url（含 /v1）。"
            "名称唯一（不区分大小写）。"
            "可在「API 扩展」中填写 JSON（如 DashScope 联网 enable_search、内置 tools），留空则不传。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["名称", "模型名", "URL", "能力", "API 密钥", "扩展", "启用"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("添加")
        self.edit_btn = QPushButton("编辑")
        self.del_btn = QPushButton("删除")
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.edit_btn)
        btn_row.addWidget(self.del_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self.add_btn.clicked.connect(self._on_add)
        self.edit_btn.clicked.connect(self._on_edit)
        self.del_btn.clicked.connect(self._on_delete)

        self._reload_table()

    def _reload_table(self):
        rows = get_custom_models(self.config)
        self.table.setRowCount(len(rows))
        for i, e in enumerate(rows):
            caps = e.get("capabilities") or []
            cap_parts = []
            if CAP_TEXT in caps:
                cap_parts.append("文本")
            if CAP_VISION in caps:
                cap_parts.append("视觉")
            cap_text = "/".join(cap_parts)
            self.table.setItem(i, 0, QTableWidgetItem(e.get("name", "")))
            self.table.setItem(i, 1, QTableWidgetItem(e.get("model_id", "")))
            self.table.setItem(i, 2, QTableWidgetItem(e.get("base_url", "")))
            self.table.setItem(i, 3, QTableWidgetItem(cap_text))
            self.table.setItem(i, 4, QTableWidgetItem(mask_api_key(e.get("api_key", ""))))
            extra_text = _api_extra_raw_text(e)
            self.table.setItem(i, 5, QTableWidgetItem("有" if extra_text else ""))
            en_item = QTableWidgetItem("是" if e.get("enabled", True) else "否")
            en_item.setData(Qt.UserRole, e.get("id"))
            self.table.setItem(i, 6, en_item)

    def _selected_id(self) -> str:
        row = self.table.currentRow()
        if row < 0:
            return ""
        item = self.table.item(row, 6)
        return item.data(Qt.UserRole) if item else ""

    def _on_add(self):
        dlg = CustomModelEditDialog(self.config, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            models = get_custom_models(self.config)
            models.append(dlg.result_entry)
            self.config["custom_models"] = models
            self._reload_table()

    def _on_edit(self):
        cid = self._selected_id()
        if not cid:
            QMessageBox.information(self, "提示", "请先选择一行")
            return
        entry = find_custom_by_id(self.config, cid)
        if not entry:
            return
        dlg = CustomModelEditDialog(self.config, entry=entry, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            models = get_custom_models(self.config)
            for i, e in enumerate(models):
                if e.get("id") == cid:
                    models[i] = dlg.result_entry
                    break
            self.config["custom_models"] = models
            self._reload_table()

    def _on_delete(self):
        cid = self._selected_id()
        if not cid:
            QMessageBox.information(self, "提示", "请先选择一行")
            return
        allowed, msg = can_remove_or_disable(self.config, cid, removing=True)
        if not allowed:
            QMessageBox.warning(self, "无法删除", msg)
            return
        entry = find_custom_by_id(self.config, cid)
        name = entry.get("name", "") if entry else cid
        if (
            QMessageBox.question(
                self,
                "确认删除",
                f"确定删除自定义模型「{name}」？",
                QMessageBox.Yes | QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        apply_fallback_on_delete(self.config, cid)
        self.config["custom_models"] = [
            e for e in get_custom_models(self.config) if e.get("id") != cid
        ]
        self._reload_table()
