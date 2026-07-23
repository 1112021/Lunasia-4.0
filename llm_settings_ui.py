# -*- coding: utf-8 -*-
"""设置页：统一模型下拉与 ModelSpec 读写。"""

from __future__ import annotations

import json
from typing import List, Optional

from PyQt5.QtWidgets import QComboBox

from llm_model_registry import (
    ModelEntry,
    build_registry_entries,
    build_vision_registry_entries,
    find_entry_for_spec,
)
from llm_spec import (
    DEFAULT_CLOUD_MODEL_ID,
    MODEL_CONFIG_KEYS,
    VISION_MODEL_CONFIG_KEYS,
    ModelSpec,
    get_config_spec,
    spec_from_combo_data,
    spec_to_combo_data,
)


def populate_model_combo(
    combo: QComboBox,
    config: dict,
    config_key: str,
    entries: Optional[List[ModelEntry]] = None,
) -> None:
    current = get_config_spec(config, config_key)
    if entries is None:
        entries = build_registry_entries(config)
    combo.blockSignals(True)
    combo.clear()
    if not entries:
        combo.addItem(
            "deepseek-v4-flash（非思考）",
            spec_to_combo_data(
                get_config_spec(config, config_key, DEFAULT_CLOUD_MODEL_ID)
            ),
        )
    else:
        for e in entries:
            combo.addItem(e.display, spec_to_combo_data(e.spec))
    idx = _find_combo_index(combo, current, entries)
    combo.setCurrentIndex(max(0, idx))
    combo.blockSignals(False)


def _find_combo_index(combo: QComboBox, spec: ModelSpec, entries: List[ModelEntry]) -> int:
    target = spec_to_combo_data(spec)
    for i in range(combo.count()):
        data = combo.itemData(i)
        if data == target:
            return i
        try:
            parsed = spec_from_combo_data(data)
            if spec.backend == "custom":
                if parsed.backend == "custom" and parsed.custom_id == spec.custom_id:
                    return i
            elif parsed.model_id == spec.model_id and parsed.backend == spec.backend:
                if spec.backend == "cloud":
                    if parsed.provider == spec.provider and (
                        parsed.thinking or ""
                    ) == (spec.thinking or ""):
                        return i
                else:
                    return i
        except Exception:
            pass
    hit = find_entry_for_spec(entries, spec)
    if hit:
        td = spec_to_combo_data(hit.spec)
        for i in range(combo.count()):
            if combo.itemData(i) == td:
                return i
    return 0


def read_model_combo(combo: QComboBox, config: dict) -> dict:
    idx = combo.currentIndex()
    if idx < 0:
        return get_config_spec(config, "selected_model").to_dict()
    data = combo.itemData(idx)
    if data:
        return spec_from_combo_data(data, config).to_dict()
    text = combo.currentText()
    from llm_spec import normalize_spec
    return normalize_spec(text, config).to_dict()


def refresh_all_model_combos(config: dict, combo_map: dict) -> None:
    """只拉取一次本地/云端列表，填充所有任务下拉（含文本能力自定义模型）。"""
    entries = build_registry_entries(config, capability="text")
    for key, combo in combo_map.items():
        if combo is not None and key in MODEL_CONFIG_KEYS:
            populate_model_combo(combo, config, key, entries=entries)


def refresh_vision_model_combos(config: dict, combo_map: dict) -> None:
    """填充读屏 / 图片 / 视频模型下拉（DashScope + 本地 + vision 自定义）。"""
    entries = build_vision_registry_entries(config)
    for key, combo in combo_map.items():
        if combo is not None and key in VISION_MODEL_CONFIG_KEYS:
            populate_model_combo(combo, config, key, entries=entries)
