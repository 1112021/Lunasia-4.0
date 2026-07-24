# -*- coding: utf-8 -*-
"""ModelSpec：混合 LLM 统一模型描述与配置迁移。"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple, Union

SpecValue = Union[str, dict, "ModelSpec", None]

# (model_id, provider, thinking) — thinking 为空表示不适用（如 OpenAI）
CLOUD_MODEL_CATALOG: List[Tuple[str, str, str]] = [
    ("deepseek-v4-flash", "deepseek", "disabled"),
    ("deepseek-v4-flash", "deepseek", "enabled"),
    ("deepseek-v4-pro", "deepseek", "enabled"),
    ("gpt-5.6-sol", "openai", ""),
    ("gpt-5.6-terra", "openai", ""),
    ("gpt-5.6-luna", "openai", ""),
]

CLOUD_VISION_CATALOG: List[Tuple[str, str]] = [
    ("gpt-5.6-sol", "openai"),
    ("gpt-5.6-terra", "openai"),
    ("gpt-5.6-luna", "openai"),
]

# 旧云端 model_id → (新 model_id, thinking)
LEGACY_CLOUD_MODEL_MIGRATION: Dict[str, Tuple[str, str]] = {
    "deepseek-chat": ("deepseek-v4-flash", "disabled"),
    "deepseek-coder": ("deepseek-v4-flash", "disabled"),
    "deepseek-reasoner": ("deepseek-v4-flash", "enabled"),
    "gpt-3.5-turbo": ("gpt-5.6-terra", ""),
    "gpt-4-turbo": ("gpt-5.6-terra", ""),
    "gpt-4o": ("gpt-5.6-terra", ""),
    "gpt-4o-mini": ("gpt-5.6-terra", ""),
}

DEFAULT_CLOUD_MODEL_ID = "deepseek-v4-flash"
DEFAULT_CLOUD_THINKING = "disabled"

MODEL_CONFIG_KEYS = (
    "selected_model",
    "memory_summary_model",
    "framework_plan_model",
    "webpage_agent_model",
    "search_intent_model",
    "security_intent_model",
    "ai_query_extraction_model",
    "search_rerank_model",
    "memory_score_agent_model",
    "todo_email_model",
    "cloud_fallback_model",
)

VISION_MODEL_CONFIG_KEYS = (
    "vision_screen_model",
    "vision_image_model",
    "vision_video_model",
)

VISION_DASHSCOPE_PRESETS = (
    "qwen3-omni-flash",
    "qwen-vl-plus",
    "qwen-vl-max",
)

VISION_MODEL_DEFAULTS = {
    "vision_screen_model": "qwen3-omni-flash",
    "vision_image_model": "qwen-vl-plus",
    "vision_video_model": "qwen-vl-plus",
}


@dataclass
class ModelSpec:
    backend: str  # cloud | ollama | lmstudio | custom | dashscope
    provider: str  # deepseek | openai | ollama | lmstudio | custom | dashscope
    model_id: str
    param_size: str = ""
    custom_id: str = ""
    # DeepSeek V4：enabled / disabled；其它后端留空
    thinking: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        if not d.get("param_size"):
            d.pop("param_size", None)
        if not d.get("custom_id"):
            d.pop("custom_id", None)
        if not d.get("thinking"):
            d.pop("thinking", None)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "ModelSpec":
        if not isinstance(data, dict):
            raise ValueError("invalid spec dict")
        thinking = str(data.get("thinking") or "").strip().lower()
        if thinking not in ("", "enabled", "disabled"):
            thinking = ""
        return cls(
            backend=str(data.get("backend") or "cloud"),
            provider=str(data.get("provider") or "deepseek"),
            model_id=str(data.get("model_id") or DEFAULT_CLOUD_MODEL_ID),
            param_size=str(data.get("param_size") or ""),
            custom_id=str(data.get("custom_id") or ""),
            thinking=thinking,
        )

    def is_local(self) -> bool:
        return self.backend in ("ollama", "lmstudio")

    def is_custom(self) -> bool:
        return self.backend == "custom"

    def is_dashscope(self) -> bool:
        return self.backend == "dashscope"

    def platform_label(self) -> str:
        if self.backend == "ollama":
            return "Ollama"
        if self.backend == "lmstudio":
            return "LM Studio"
        if self.backend == "custom":
            return "自定义"
        if self.backend == "dashscope":
            return "DashScope"
        return "云端"

    def display_name(self, config: Optional[dict] = None) -> str:
        if self.backend == "custom":
            if config:
                from custom_models_store import find_custom_by_id, display_name_for_entry

                entry = find_custom_by_id(config, self.custom_id)
                if entry:
                    return display_name_for_entry(entry)
            name = self.model_id
            return f"{name}（自定义）" if name else "自定义模型"

        if self.backend == "cloud":
            return cloud_display_name(self.model_id, self.thinking)

        name = self.model_id
        if self.param_size:
            name = f"{name} {self.param_size}"
        return f"{name}（{self.platform_label()}）"


def cloud_display_name(model_id: str, thinking: str = "") -> str:
    mid = (model_id or "").strip()
    th = (thinking or "").strip().lower()
    friendly = {
        "gpt-5.6-sol": "GPT-5.6 Sol",
        "gpt-5.6-terra": "GPT-5.6 Terra",
        "gpt-5.6-luna": "GPT-5.6 Luna",
        "gpt-5.6": "GPT-5.6 Sol",
    }
    if mid in friendly:
        return friendly[mid]
    if mid.startswith("deepseek-") and th == "disabled":
        return f"{mid}（非思考）"
    if mid.startswith("deepseek-") and th == "enabled":
        return f"{mid}（思考）"
    return mid or DEFAULT_CLOUD_MODEL_ID


def cloud_spec(
    model_id: str,
    config: Optional[dict] = None,
    thinking: str = "",
) -> ModelSpec:
    mid = (model_id or DEFAULT_CLOUD_MODEL_ID).strip()
    th = (thinking or "").strip().lower()
    if th not in ("", "enabled", "disabled"):
        th = ""
    # 未显式指定时：DeepSeek V4 默认非思考（任务模型更稳）
    if not th and mid.startswith("deepseek-v4"):
        th = DEFAULT_CLOUD_THINKING
    provider = _cloud_provider_for_model(mid, config)
    return ModelSpec(
        backend="cloud",
        provider=provider,
        model_id=mid,
        thinking=th if provider == "deepseek" else "",
    )


def dashscope_spec(model_id: str) -> ModelSpec:
    return ModelSpec(backend="dashscope", provider="dashscope", model_id=model_id)


def _cloud_provider_for_model(model_id: str, config: Optional[dict] = None) -> str:
    for mid, prov, _thinking in CLOUD_MODEL_CATALOG:
        if mid == model_id:
            return prov
    for mid, prov in CLOUD_VISION_CATALOG:
        if mid == model_id:
            return prov
    if "gpt" in (model_id or "").lower():
        return "openai"
    return "deepseek"


def migrate_legacy_cloud_model_id(model_id: str) -> Tuple[str, str]:
    """返回 (model_id, thinking)。"""
    mid = (model_id or "").strip()
    if mid in LEGACY_CLOUD_MODEL_MIGRATION:
        return LEGACY_CLOUD_MODEL_MIGRATION[mid]
    return mid, ""


def normalize_spec(value: SpecValue, config: Optional[dict] = None) -> ModelSpec:
    if isinstance(value, ModelSpec):
        return migrate_model_spec(value)

    if isinstance(value, dict):
        return migrate_model_spec(ModelSpec.from_dict(value))

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return cloud_spec(DEFAULT_CLOUD_MODEL_ID, config, DEFAULT_CLOUD_THINKING)
        if text.startswith("{"):
            try:
                return migrate_model_spec(ModelSpec.from_dict(json.loads(text)))
            except (json.JSONDecodeError, ValueError):
                pass
        if "|" in text:
            parts = text.split("|", 2)
            if len(parts) == 3:
                return migrate_model_spec(
                    ModelSpec(
                        backend=parts[0],
                        provider=parts[1],
                        model_id=parts[2],
                    )
                )
        new_id, thinking = migrate_legacy_cloud_model_id(text)
        if thinking or new_id != text:
            return cloud_spec(new_id, config, thinking)
        return cloud_spec(text, config)

    return cloud_spec(DEFAULT_CLOUD_MODEL_ID, config, DEFAULT_CLOUD_THINKING)


def migrate_model_spec(spec: ModelSpec) -> ModelSpec:
    """将旧云端 model_id / 缺省 thinking 规范到当前目录语义。"""
    if spec.backend != "cloud":
        return spec

    new_id, mapped_thinking = migrate_legacy_cloud_model_id(spec.model_id)
    thinking = (spec.thinking or "").strip().lower()
    if mapped_thinking and new_id != spec.model_id:
        thinking = mapped_thinking
    elif mapped_thinking and not thinking:
        thinking = mapped_thinking

    if new_id.startswith("deepseek-v4") and thinking not in ("enabled", "disabled"):
        thinking = DEFAULT_CLOUD_THINKING

    provider = _cloud_provider_for_model(new_id)
    if provider != "deepseek":
        thinking = ""

    return ModelSpec(
        backend="cloud",
        provider=provider,
        model_id=new_id,
        param_size=spec.param_size,
        custom_id=spec.custom_id,
        thinking=thinking,
    )


def get_config_spec(
    config: dict,
    key: str,
    default_model: str = DEFAULT_CLOUD_MODEL_ID,
) -> ModelSpec:
    raw = config.get(key)
    if raw is None:
        return cloud_spec(default_model, config, DEFAULT_CLOUD_THINKING)
    return normalize_spec(raw, config)


def vision_model_label(config: dict, config_key: str) -> str:
    """读屏 / 图片 / 视频 ModelSpec 的显示名（含自定义模型名称）。"""
    return get_config_spec(config, config_key).display_name(config)


def spec_to_combo_data(spec: ModelSpec) -> str:
    return json.dumps(spec.to_dict(), ensure_ascii=False)


def spec_from_combo_data(data: Any, config: Optional[dict] = None) -> ModelSpec:
    if isinstance(data, ModelSpec):
        return migrate_model_spec(data)
    if isinstance(data, dict):
        return migrate_model_spec(ModelSpec.from_dict(data))
    if isinstance(data, str) and data.strip().startswith("{"):
        try:
            return migrate_model_spec(ModelSpec.from_dict(json.loads(data)))
        except (json.JSONDecodeError, ValueError):
            pass
    return normalize_spec(data, config)


def get_spec_create_kwargs(config: dict, spec: Optional[ModelSpec]) -> Dict[str, Any]:
    """合并自定义 api_extra 与 DeepSeek thinking 开关，供 chat.completions.create 使用。"""
    kwargs: Dict[str, Any] = {}
    if not spec:
        return kwargs

    if spec.is_custom():
        from custom_models_store import get_custom_create_kwargs

        kwargs = dict(get_custom_create_kwargs(config, spec) or {})

    if (
        spec.backend == "cloud"
        and spec.provider == "deepseek"
        and spec.thinking in ("enabled", "disabled")
    ):
        extra_body = dict(kwargs.get("extra_body") or {})
        thinking_obj = dict(extra_body.get("thinking") or {})
        thinking_obj["type"] = spec.thinking
        extra_body["thinking"] = thinking_obj
        kwargs["extra_body"] = extra_body

    return kwargs


def message_text_content(message: Any) -> str:
    """提取助手正文；思考模式下 content 可能为空，回退 reasoning_content。"""
    if message is None:
        return ""
    content = getattr(message, "content", None)
    if isinstance(content, str) and content.strip():
        return content.strip()
    reasoning = getattr(message, "reasoning_content", None)
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning.strip()
    return (content or "").strip() if isinstance(content, str) else ""


def migrate_config_llm(config: dict) -> dict:
    """加载/保存前：ModelSpec、framework_plan_model；llm_mode 固定 hybrid。"""
    config["llm_mode"] = "hybrid"

    if "cloud_provider" not in config:
        lp = config.get("llm_provider", "DeepSeek")
        config["cloud_provider"] = lp if lp in ("DeepSeek", "OpenAI") else "DeepSeek"

    if "local_fail_fallback_to_cloud" not in config:
        config["local_fail_fallback_to_cloud"] = False
    if "local_preload_on_startup" not in config:
        config["local_preload_on_startup"] = False
    if "custom_fail_fallback_to_cloud" not in config:
        config["custom_fail_fallback_to_cloud"] = False
    if "vision_custom_fallback_to_dashscope" not in config:
        config["vision_custom_fallback_to_dashscope"] = True
    if "custom_model_on_delete" not in config:
        config["custom_model_on_delete"] = "block_until_reselect"
    if "custom_models" not in config or not isinstance(config.get("custom_models"), list):
        config["custom_models"] = []

    if not config.get("vision_dashscope_api_key"):
        legacy = (config.get("qwen3vl_plus_key") or "").strip()
        if legacy:
            config["vision_dashscope_api_key"] = legacy
    config.setdefault("vision_dashscope_screen_model", "qwen3-omni-flash")
    config.setdefault("vision_dashscope_image_model", "qwen-vl-plus")
    config.setdefault("vision_dashscope_video_model", "qwen-vl-plus")
    _migrate_vision_model_specs(config)
    vkey = (config.get("vision_dashscope_api_key") or "").strip()
    if vkey:
        config["qwen3vl_plus_key"] = vkey

    ollama_url = config.get("ollama_url", "http://localhost:11434")
    if "ollama" not in config or not isinstance(config.get("ollama"), dict):
        config["ollama"] = {
            "enabled": config.get("llm_provider") == "Ollama",
            "base_url": ollama_url,
            "api_key": "",
        }
    else:
        ob = config["ollama"]
        ob.setdefault("enabled", bool(ob.get("base_url")))
        ob.setdefault("base_url", ollama_url)
        ob.setdefault("api_key", "")

    if "lmstudio" not in config or not isinstance(config.get("lmstudio"), dict):
        config["lmstudio"] = {
            "enabled": False,
            "base_url": "http://localhost:1234",
            "api_key": "",
        }
    else:
        lb = config["lmstudio"]
        lb.setdefault("enabled", False)
        lb.setdefault("base_url", "http://localhost:1234")
        lb.setdefault("api_key", "")

    if "cloud_fallback_model" not in config:
        config["cloud_fallback_model"] = cloud_spec(
            DEFAULT_CLOUD_MODEL_ID, config, DEFAULT_CLOUD_THINKING
        ).to_dict()

    if "framework_plan_model" not in config:
        legacy = config.get("search_intent_model", DEFAULT_CLOUD_MODEL_ID)
        config["framework_plan_model"] = normalize_spec(legacy, config).to_dict()

    if "webpage_agent_model" not in config:
        config["webpage_agent_model"] = cloud_spec(
            DEFAULT_CLOUD_MODEL_ID, config, DEFAULT_CLOUD_THINKING
        ).to_dict()

    for key in MODEL_CONFIG_KEYS:
        if key not in config:
            continue
        val = config[key]
        if isinstance(val, str) or val is None:
            mid = val or DEFAULT_CLOUD_MODEL_ID
            config[key] = normalize_spec(mid, config).to_dict()
        elif isinstance(val, dict):
            config[key] = migrate_model_spec(ModelSpec.from_dict(val)).to_dict()

    for key in VISION_MODEL_CONFIG_KEYS:
        raw = config.get(key)
        if isinstance(raw, dict) and raw.get("backend") == "cloud":
            config[key] = migrate_model_spec(ModelSpec.from_dict(raw)).to_dict()

    return config


def _migrate_vision_model_specs(config: dict) -> None:
    """将视觉模型配置统一为 ModelSpec；兼容旧字符串与 vision_model 单条目。"""
    legacy_string_keys = {
        "vision_screen_model": "vision_dashscope_screen_model",
        "vision_image_model": "vision_dashscope_image_model",
        "vision_video_model": "vision_dashscope_video_model",
    }

    old_custom = config.get("vision_model")
    if (
        config.get("vision_model_source") == "custom"
        and isinstance(old_custom, dict)
        and old_custom.get("backend") == "custom"
    ):
        for key in VISION_MODEL_CONFIG_KEYS:
            raw = config.get(key)
            if raw is None or raw == {} or isinstance(raw, str):
                config[key] = dict(old_custom)

    for key in VISION_MODEL_CONFIG_KEYS:
        default_mid = VISION_MODEL_DEFAULTS[key]
        raw = config.get(key)
        if isinstance(raw, dict) and raw.get("backend"):
            if raw.get("backend") == "cloud":
                config[key] = migrate_model_spec(ModelSpec.from_dict(raw)).to_dict()
            continue
        if isinstance(raw, str) and raw.strip():
            text = raw.strip()
            if text in LEGACY_CLOUD_MODEL_MIGRATION or text.startswith("gpt-"):
                new_id, thinking = migrate_legacy_cloud_model_id(text)
                config[key] = cloud_spec(new_id, config, thinking).to_dict()
            else:
                config[key] = dashscope_spec(text).to_dict()
            continue
        leg_key = legacy_string_keys[key]
        leg = config.get(leg_key)
        if isinstance(leg, str) and leg.strip():
            config[key] = dashscope_spec(leg.strip()).to_dict()
        else:
            config[key] = dashscope_spec(default_mid).to_dict()
