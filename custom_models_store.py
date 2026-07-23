# -*- coding: utf-8 -*-
"""自定义 OpenAI 兼容模型条目存储与引用扫描。"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from llm_spec import MODEL_CONFIG_KEYS, VISION_MODEL_CONFIG_KEYS, ModelSpec, dashscope_spec, get_config_spec

# chat.completions.create 允许的自定义扩展键（来自 api_extra 配置）
_API_EXTRA_ALLOWED_KEYS = ("tools", "extra_body", "tool_choice", "parallel_tool_calls")

CAP_TEXT = "text"
CAP_VISION = "vision"

CUSTOM_MODEL_REF_KEYS = tuple(MODEL_CONFIG_KEYS) + VISION_MODEL_CONFIG_KEYS

TASK_LABELS = {
    "selected_model": "主对话模型",
    "memory_summary_model": "识底深湖模型",
    "framework_plan_model": "框架规划模型",
    "todo_email_model": "待办邮件模型",
    "cloud_fallback_model": "云端回退模型",
    "search_rerank_model": "搜索结果重排模型",
    "ai_query_extraction_model": "AI 查询提取模型",
    "search_intent_model": "搜索意图识别模型",
    "security_intent_model": "安全测试意图识别模型",
    "memory_score_agent_model": "向量选取及分数修改模型",
    "vision_screen_model": "读屏模型",
    "vision_image_model": "图片模型",
    "vision_video_model": "视频模型",
}


def normalize_name_key(name: str) -> str:
    return (name or "").strip().casefold()


def mask_api_key(key: str) -> str:
    k = (key or "").strip()
    if len(k) <= 8:
        return "****" if k else ""
    return f"{k[:4]}…{k[-4:]}"


def get_custom_models(config: dict) -> List[dict]:
    raw = config.get("custom_models")
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


def find_custom_by_id(config: dict, custom_id: str) -> Optional[dict]:
    if not custom_id:
        return None
    for e in get_custom_models(config):
        if e.get("id") == custom_id:
            return e
    return None


def find_custom_by_name(config: dict, name: str, exclude_id: str = "") -> Optional[dict]:
    key = normalize_name_key(name)
    if not key:
        return None
    for e in get_custom_models(config):
        if exclude_id and e.get("id") == exclude_id:
            continue
        if normalize_name_key(e.get("name", "")) == key:
            return e
    return None


def normalize_base_url(url: str) -> str:
    return (url or "").strip().rstrip("/")


def _api_extra_raw_text(entry: dict) -> str:
    raw = entry.get("api_extra")
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, (dict, list)):
        try:
            return json.dumps(raw, ensure_ascii=False)
        except (TypeError, ValueError):
            return ""
    return str(raw).strip()


def parse_api_extra(raw: Any) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    将 api_extra 解析为 chat.completions.create 的额外关键字参数。

    - JSON 数组 → tools
    - JSON 对象含 tools / extra_body → 原样提取允许键
    - 其它 JSON 对象 → 整段作为 extra_body（如 DashScope enable_search）
    """
    if raw is None or raw == "" or raw == {}:
        return {}, None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}, None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            return {}, f"API 扩展参数 JSON 无效: {e}"
    elif isinstance(raw, list):
        return {"tools": raw}, None
    elif isinstance(raw, dict):
        parsed = raw
    else:
        return {}, "API 扩展参数格式无效"

    if isinstance(parsed, list):
        return {"tools": parsed}, None
    if not isinstance(parsed, dict):
        return {}, "API 扩展参数须为 JSON 对象或数组"

    if any(k in parsed for k in _API_EXTRA_ALLOWED_KEYS):
        return {k: parsed[k] for k in _API_EXTRA_ALLOWED_KEYS if k in parsed}, None
    return {"extra_body": parsed}, None


def get_custom_create_kwargs(config: dict, spec: Optional[ModelSpec]) -> Dict[str, Any]:
    """自定义模型 spec 对应的 create() 扩展参数；非 custom 或解析失败时返回空 dict。"""
    if not spec or not spec.is_custom():
        return {}
    entry = find_custom_by_id(config, spec.custom_id)
    if not entry:
        return {}
    kwargs, err = parse_api_extra(entry.get("api_extra"))
    if err:
        print(f"⚠️ [自定义模型·{entry.get('name', '')}] {err}")
        return {}
    return kwargs


def validate_custom_entry(entry: dict, config: dict, exclude_id: str = "") -> Tuple[bool, str]:
    name = (entry.get("name") or "").strip()
    if not name:
        return False, "请填写名称"
    if find_custom_by_name(config, name, exclude_id=exclude_id):
        return False, f"名称「{name}」已存在（不区分大小写）"
    base_url = normalize_base_url(entry.get("base_url", ""))
    if not base_url.startswith(("http://", "https://")):
        return False, "URL 须以 http:// 或 https:// 开头"
    model_id = (entry.get("model_id") or "").strip()
    if not model_id:
        return False, "请填写模型名（model_id）"
    caps = entry.get("capabilities") or []
    if not isinstance(caps, list):
        caps = []
    caps = [c for c in caps if c in (CAP_TEXT, CAP_VISION)]
    if not caps:
        return False, "请至少勾选「文本」或「视觉」之一"
    _, api_err = parse_api_extra(entry.get("api_extra"))
    if api_err:
        return False, api_err
    return True, ""


def new_custom_entry(
    name: str,
    base_url: str,
    model_id: str,
    api_key: str,
    capabilities: List[str],
    enabled: bool = True,
) -> dict:
    caps = [c for c in capabilities if c in (CAP_TEXT, CAP_VISION)]
    return {
        "id": str(uuid.uuid4()),
        "name": name.strip(),
        "base_url": normalize_base_url(base_url),
        "model_id": model_id.strip(),
        "api_key": (api_key or "").strip(),
        "capabilities": caps,
        "enabled": bool(enabled),
        "api_extra": "",
    }


def spec_uses_custom_id(spec_val: Any, custom_id: str) -> bool:
    if not custom_id:
        return False
    try:
        if isinstance(spec_val, dict):
            return (
                spec_val.get("backend") == "custom"
                and spec_val.get("custom_id") == custom_id
            )
        spec = ModelSpec.from_dict(spec_val) if isinstance(spec_val, dict) else None
    except Exception:
        spec = None
    if spec is None:
        try:
            from llm_spec import normalize_spec

            spec = normalize_spec(spec_val)
        except Exception:
            return False
    return spec.backend == "custom" and spec.custom_id == custom_id


def list_references(config: dict, custom_id: str) -> List[Tuple[str, str]]:
    refs: List[Tuple[str, str]] = []
    if not custom_id:
        return refs
    for key in CUSTOM_MODEL_REF_KEYS:
        val = config.get(key)
        if spec_uses_custom_id(val, custom_id):
            refs.append((key, TASK_LABELS.get(key, key)))
    return refs


def can_remove_or_disable(
    config: dict, custom_id: str, *, removing: bool = False
) -> Tuple[bool, str]:
    policy = config.get("custom_model_on_delete", "block_until_reselect")
    refs = list_references(config, custom_id)
    if not refs:
        return True, ""
    labels = "、".join(l[1] for l in refs)
    if policy == "fallback_cloud":
        return True, ""
    action = "删除" if removing else "禁用"
    return (
        False,
        f"无法{action}：以下配置正在使用此条目：{labels}。"
        f"请先在设置中更换后再{action}。",
    )


def apply_fallback_on_delete(config: dict, custom_id: str) -> None:
    if config.get("custom_model_on_delete") != "fallback_cloud":
        return
    from llm_spec import VISION_MODEL_DEFAULTS

    fb = get_config_spec(config, "cloud_fallback_model").to_dict()
    for key in MODEL_CONFIG_KEYS:
        if spec_uses_custom_id(config.get(key), custom_id):
            config[key] = dict(fb)
    for key in VISION_MODEL_CONFIG_KEYS:
        if spec_uses_custom_id(config.get(key), custom_id):
            config[key] = dashscope_spec(VISION_MODEL_DEFAULTS[key]).to_dict()


def get_vision_dashscope_api_key(config: dict) -> str:
    key = (config.get("vision_dashscope_api_key") or "").strip()
    if key:
        return key
    key = (config.get("qwen3vl_plus_key") or "").strip()
    if key:
        return key
    return (config.get("dashscope_key") or "").strip()


def custom_spec_from_entry(entry: dict) -> ModelSpec:
    return ModelSpec(
        backend="custom",
        provider="custom",
        model_id=entry.get("model_id", ""),
        custom_id=entry.get("id", ""),
    )


def display_name_for_entry(entry: dict) -> str:
    return f"{entry.get('name', '未命名')}（{entry.get('model_id', '')}）"
