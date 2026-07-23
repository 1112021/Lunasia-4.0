# -*- coding: utf-8 -*-
"""ModelRegistry：拉取云端 / Ollama / LM Studio 模型列表。"""

from __future__ import annotations

import concurrent.futures
import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from llm_spec import (
    CLOUD_MODEL_CATALOG,
    CLOUD_VISION_CATALOG,
    MODEL_CONFIG_KEYS,
    VISION_DASHSCOPE_PRESETS,
    VISION_MODEL_CONFIG_KEYS,
    ModelSpec,
    get_config_spec,
)
from custom_models_store import (
    CAP_TEXT,
    CAP_VISION,
    custom_spec_from_entry,
    display_name_for_entry,
    find_custom_by_id,
    get_custom_models,
)


class ModelEntry:
    __slots__ = ("spec", "display")

    def __init__(self, spec: ModelSpec, display: str):
        self.spec = spec
        self.display = display


def _http_get_json(
    url: str,
    timeout: float = 2.0,
    headers: Optional[dict] = None,
) -> Any:
    hdrs = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_models_from_json(data: Any) -> List[Tuple[str, str]]:
    """解析 OpenAI / LM Studio v0/v1 多种列表响应格式。"""
    if not isinstance(data, dict):
        return []
    items = data.get("data") or data.get("models") or []
    if not isinstance(items, list):
        return []
    out: List[Tuple[str, str]] = []
    for m in items:
        if not isinstance(m, dict):
            continue
        mid = m.get("id") or m.get("key") or m.get("model")
        if not mid:
            continue
        psize = m.get("params_string") or ""
        if not psize:
            quant = m.get("quantization")
            if isinstance(quant, dict):
                psize = quant.get("name") or ""
            elif isinstance(quant, str):
                psize = quant
        details = m.get("details") or {}
        if isinstance(details, dict) and not psize:
            psize = details.get("parameter_size") or details.get("family") or ""
        out.append((str(mid), str(psize) if psize else ""))
    return out


def fetch_ollama_models(base_url: str) -> List[Tuple[str, str]]:
    base = (base_url or "").rstrip("/")
    out: List[Tuple[str, str]] = []
    try:
        data = _http_get_json(f"{base}/api/tags", timeout=2.0)
        for m in data.get("models") or []:
            name = m.get("name") or m.get("model")
            if not name:
                continue
            size = ""
            details = m.get("details") or {}
            if isinstance(details, dict):
                size = details.get("parameter_size") or details.get("family") or ""
            out.append((name, size))
        if out:
            return out
    except Exception as e:
        print(f"⚠️ [Ollama] /api/tags 失败: {e}")
    try:
        data = _http_get_json(f"{base}/v1/models", timeout=2.0)
        out = _extract_models_from_json(data)
    except Exception as e:
        print(f"⚠️ [Ollama] /v1/models 失败: {e}")
    return out


def fetch_lmstudio_models(base_url: str, api_key: str = "") -> List[Tuple[str, str]]:
    """拉取 LM Studio 模型：优先 v1/v0（含未加载的已下载模型），再试 OpenAI 兼容接口。"""
    base = (base_url or "").rstrip("/")
    headers: dict = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    seen: set = set()
    out: List[Tuple[str, str]] = []

    for path in ("/api/v1/models", "/api/v0/models", "/v1/models"):
        try:
            data = _http_get_json(f"{base}{path}", timeout=2.0, headers=headers or None)
            for mid, psize in _extract_models_from_json(data):
                if mid in seen:
                    continue
                seen.add(mid)
                out.append((mid, psize))
        except Exception as e:
            print(f"⚠️ [LM Studio] {path} 列表失败: {e}")

    return out


def _append_local_entries(
    entries: List[ModelEntry],
    backend: str,
    provider: str,
    models: List[Tuple[str, str]],
) -> None:
    for mid, psize in models:
        spec = ModelSpec(
            backend=backend,
            provider=provider,
            model_id=mid,
            param_size=psize or "",
        )
        entries.append(ModelEntry(spec, spec.display_name()))


def _append_lmstudio_specs_from_config(config: dict, entries: List[ModelEntry]) -> None:
    """配置里已选的 LM Studio 模型在拉取失败时仍出现在下拉中。"""
    seen = {e.spec.model_id for e in entries if e.spec.backend == "lmstudio"}
    for key in MODEL_CONFIG_KEYS:
        spec = get_config_spec(config, key)
        if spec.backend != "lmstudio" or spec.model_id in seen:
            continue
        entries.append(ModelEntry(spec, spec.display_name()))
        seen.add(spec.model_id)


def _append_custom_entries(
    config: dict,
    entries: List[ModelEntry],
    capability: Optional[str] = None,
) -> None:
    seen_ids = {
        e.spec.custom_id for e in entries if e.spec.backend == "custom" and e.spec.custom_id
    }
    for entry in get_custom_models(config):
        if not entry.get("enabled", True):
            continue
        caps = entry.get("capabilities") or []
        if capability == "text" and CAP_TEXT not in caps:
            continue
        if capability == "vision" and CAP_VISION not in caps:
            continue
        if capability is None and CAP_TEXT not in caps:
            continue
        cid = entry.get("id", "")
        if cid in seen_ids:
            continue
        spec = custom_spec_from_entry(entry)
        entries.append(ModelEntry(spec, display_name_for_entry(entry)))
        seen_ids.add(cid)

    for key in MODEL_CONFIG_KEYS + VISION_MODEL_CONFIG_KEYS:
        spec = get_config_spec(config, key)
        if spec.backend != "custom" or not spec.custom_id or spec.custom_id in seen_ids:
            continue
        if capability == "text" and key in VISION_MODEL_CONFIG_KEYS:
            continue
        if capability == "vision" and key in MODEL_CONFIG_KEYS:
            continue
        ent = find_custom_by_id(config, spec.custom_id)
        if ent:
            entries.append(ModelEntry(spec, display_name_for_entry(ent)))
            seen_ids.add(spec.custom_id)


def build_registry_entries(
    config: dict, capability: Optional[str] = None
) -> List[ModelEntry]:
    entries: List[ModelEntry] = []

    for model_id, prov, thinking in CLOUD_MODEL_CATALOG:
        spec = ModelSpec(
            backend="cloud",
            provider=prov,
            model_id=model_id,
            thinking=thinking,
        )
        entries.append(ModelEntry(spec, spec.display_name()))

    ocfg = config.get("ollama") or {}
    lcfg = config.get("lmstudio") or {}
    futures: dict = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        if ocfg.get("enabled") and ocfg.get("base_url"):
            futures["ollama"] = pool.submit(
                fetch_ollama_models, ocfg.get("base_url", "")
            )
        if lcfg.get("enabled") and lcfg.get("base_url"):
            futures["lmstudio"] = pool.submit(
                fetch_lmstudio_models,
                lcfg.get("base_url", ""),
                lcfg.get("api_key") or "",
            )

        if "ollama" in futures:
            try:
                _append_local_entries(
                    entries, "ollama", "ollama", futures["ollama"].result(timeout=3)
                )
            except Exception as e:
                print(f"⚠️ [Ollama] 模型列表获取超时或失败: {e}")

        if "lmstudio" in futures:
            try:
                lm_models = futures["lmstudio"].result(timeout=3)
                _append_local_entries(entries, "lmstudio", "lmstudio", lm_models)
                if not lm_models:
                    print(
                        "ℹ️ [LM Studio] 未拉取到模型；请确认 LM Studio 已启动且本地 Server 已开启。"
                        "若已下载模型仍为空，可在 LM Studio 中先加载任意模型后再点「刷新模型列表」。"
                    )
            except Exception as e:
                print(f"⚠️ [LM Studio] 模型列表获取超时或失败: {e}")

    if lcfg.get("enabled"):
        _append_lmstudio_specs_from_config(config, entries)

    _append_custom_entries(config, entries, capability=capability)

    return entries


def _append_vision_specs_from_config(config: dict, entries: List[ModelEntry]) -> None:
    """配置里已选但不在预设列表中的视觉模型仍出现在下拉中。"""
    for key in VISION_MODEL_CONFIG_KEYS:
        spec = get_config_spec(config, key)
        if find_entry_for_spec(entries, spec):
            continue
        if spec.backend == "dashscope":
            display = f"{spec.model_id}（DashScope）"
        elif spec.backend == "custom":
            ent = find_custom_by_id(config, spec.custom_id)
            display = display_name_for_entry(ent) if ent else spec.display_name(config)
        else:
            display = spec.display_name(config)
        entries.append(ModelEntry(spec, display))


def build_vision_registry_entries(config: dict) -> List[ModelEntry]:
    """视觉任务下拉：DashScope 预设 + 多模态云端 + 本地 + vision 自定义。"""
    entries: List[ModelEntry] = []

    for mid in VISION_DASHSCOPE_PRESETS:
        spec = ModelSpec(backend="dashscope", provider="dashscope", model_id=mid)
        entries.append(ModelEntry(spec, f"{mid}（DashScope）"))

    for model_id, prov in CLOUD_VISION_CATALOG:
        spec = ModelSpec(backend="cloud", provider=prov, model_id=model_id)
        entries.append(ModelEntry(spec, spec.display_name()))

    ocfg = config.get("ollama") or {}
    lcfg = config.get("lmstudio") or {}
    futures: dict = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        if ocfg.get("enabled") and ocfg.get("base_url"):
            futures["ollama"] = pool.submit(
                fetch_ollama_models, ocfg.get("base_url", "")
            )
        if lcfg.get("enabled") and lcfg.get("base_url"):
            futures["lmstudio"] = pool.submit(
                fetch_lmstudio_models,
                lcfg.get("base_url", ""),
                lcfg.get("api_key") or "",
            )

        if "ollama" in futures:
            try:
                _append_local_entries(
                    entries, "ollama", "ollama", futures["ollama"].result(timeout=3)
                )
            except Exception as e:
                print(f"⚠️ [Ollama] 模型列表获取超时或失败: {e}")

        if "lmstudio" in futures:
            try:
                lm_models = futures["lmstudio"].result(timeout=3)
                _append_local_entries(entries, "lmstudio", "lmstudio", lm_models)
            except Exception as e:
                print(f"⚠️ [LM Studio] 模型列表获取超时或失败: {e}")

    _append_custom_entries(config, entries, capability="vision")
    _append_vision_specs_from_config(config, entries)

    return entries


def find_entry_for_spec(entries: List[ModelEntry], spec: ModelSpec) -> Optional[ModelEntry]:
    if spec.backend == "custom":
        for e in entries:
            if e.spec.backend == "custom" and e.spec.custom_id == spec.custom_id:
                return e
        return None
    for e in entries:
        s = e.spec
        if s.backend == spec.backend and s.model_id == spec.model_id:
            if spec.backend == "cloud" and s.provider != spec.provider:
                continue
            if spec.backend == "cloud" and (s.thinking or "") != (spec.thinking or ""):
                continue
            return e
    return None
