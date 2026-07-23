# -*- coding: utf-8 -*-
"""统一 LLM 路由：云端 / Ollama / LM Studio + 可选 fallback。"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import openai

StreamCallback = Optional[Callable[[str], None]]

from llm_spec import (
    DEFAULT_CLOUD_MODEL_ID,
    ModelSpec,
    get_config_spec,
    get_spec_create_kwargs,
    message_text_content,
    normalize_spec,
)

StatusCallback = Optional[Callable[[str], None]]

# 由 AIAgent / MainWindow 注入
_global_status_callback: StatusCallback = None


def set_llm_status_callback(cb: StatusCallback) -> None:
    global _global_status_callback
    _global_status_callback = cb


def _notify_status(msg: str) -> None:
    if _global_status_callback:
        try:
            _global_status_callback(msg)
        except Exception:
            pass


def get_client_for_spec(config: dict, spec: ModelSpec) -> Optional[Tuple[Any, str]]:
    if spec.backend == "cloud":
        if spec.provider == "openai":
            api_key = config.get("openai_key", "")
            if not api_key:
                print("⚠️ OpenAI API 密钥未配置")
                return None
            client = openai.OpenAI(api_key=api_key)
            return client, spec.model_id
        api_key = config.get("deepseek_key", "")
        if not api_key:
            print("⚠️ DeepSeek API 密钥未配置")
            return None
        client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1",
        )
        return client, spec.model_id

    if spec.backend == "ollama":
        ocfg = config.get("ollama") or {}
        base_url = (ocfg.get("base_url") or "http://localhost:11434").rstrip("/")
        api_key = ocfg.get("api_key") or "ollama"
        client = openai.OpenAI(api_key=api_key, base_url=f"{base_url}/v1")
        return client, spec.model_id

    if spec.backend == "lmstudio":
        lcfg = config.get("lmstudio") or {}
        base_url = (lcfg.get("base_url") or "http://localhost:1234").rstrip("/")
        api_key = lcfg.get("api_key") or "lmstudio"
        client = openai.OpenAI(api_key=api_key, base_url=f"{base_url}/v1")
        return client, spec.model_id

    if spec.backend == "custom":
        from custom_models_store import find_custom_by_id

        entry = find_custom_by_id(config, spec.custom_id)
        if not entry or not entry.get("enabled", True):
            print("⚠️ 自定义模型未找到或已禁用")
            return None
        base_url = (entry.get("base_url") or "").strip()
        if not base_url:
            print("⚠️ 自定义模型 base_url 为空")
            return None
        api_key = (entry.get("api_key") or "").strip() or "none"
        model_id = (entry.get("model_id") or spec.model_id or "").strip()
        if not model_id:
            print("⚠️ 自定义模型 model_id 为空")
            return None
        client = openai.OpenAI(api_key=api_key, base_url=base_url)
        return client, model_id

    print(f"⚠️ 未知 backend: {spec.backend}")
    return None


def resolve_client(
    config: dict,
    *,
    config_key: Optional[str] = None,
    spec: Optional[ModelSpec] = None,
    legacy_model: Optional[str] = None,
) -> Optional[Tuple[Any, str, ModelSpec]]:
    if spec is None:
        if config_key:
            spec = get_config_spec(config, config_key)
        elif legacy_model is not None:
            spec = normalize_spec(legacy_model, config)
        else:
            spec = get_config_spec(config, "selected_model")

    result = get_client_for_spec(config, spec)
    if not result:
        return None
    client, model_id = result
    return client, model_id, spec


def _fallback_cloud_spec(config: dict) -> ModelSpec:
    return get_config_spec(
        config, "cloud_fallback_model", default_model=DEFAULT_CLOUD_MODEL_ID
    )


def chat_completion(
    config: dict,
    *,
    config_key: Optional[str] = None,
    spec: Optional[ModelSpec] = None,
    legacy_model: Optional[str] = None,
    messages: List[dict],
    max_tokens: int = 1024,
    temperature: float = 0.2,
    timeout: float = 120,
    task_label: str = "",
    stream_callback: StreamCallback = None,
) -> Optional[str]:
    resolved = resolve_client(
        config,
        config_key=config_key,
        spec=spec,
        legacy_model=legacy_model,
    )
    if not resolved:
        return None
    client, model_id, used_spec = resolved

    def _call(c, mid, s: ModelSpec, *, use_stream: bool = False) -> str:
        extra = get_spec_create_kwargs(config, s)
        if use_stream and stream_callback is not None:
            stream = c.chat.completions.create(
                model=mid,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
                stream=True,
                **extra,
            )
            accumulated = ""
            for chunk in stream:
                cancel_event = getattr(stream_callback, "_cancel_event", None)
                if cancel_event is not None and cancel_event.is_set():
                    close = getattr(stream, "close", None)
                    if callable(close):
                        close()
                    break
                if chunk.choices and len(chunk.choices) > 0:
                    delta = getattr(chunk.choices[0], "delta", None)
                    if delta and getattr(delta, "content", None):
                        accumulated += delta.content
                        stream_callback(accumulated)
            return accumulated.strip()
        resp = c.chat.completions.create(
            model=mid,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            **extra,
        )
        return message_text_content(resp.choices[0].message)

    try:
        text = _call(
            client, model_id, used_spec, use_stream=stream_callback is not None
        )
        print(
            f"[LLM] task={task_label or config_key or '-'} "
            f"backend={used_spec.backend} model={model_id} fallback=0"
        )
        return text
    except Exception as e:
        print(
            f"⚠️ [LLM] 调用失败 task={task_label or config_key} "
            f"backend={used_spec.backend} model={model_id}: {e}"
        )
        use_local_fb = used_spec.is_local() and config.get(
            "local_fail_fallback_to_cloud", False
        )
        use_custom_fb = used_spec.is_custom() and config.get(
            "custom_fail_fallback_to_cloud", False
        )
        if not use_local_fb and not use_custom_fb:
            raise

        fb = _fallback_cloud_spec(config)
        fb_client = get_client_for_spec(config, fb)
        if not fb_client:
            raise
        fc, fmid = fb_client
        label = task_label or config_key or "任务"
        msg = f"{label} 本地模型不可用，已回退云端"
        print(f"⚠️ [LLM] {msg}")
        _notify_status(msg)
        text = _call(fc, fmid, fb, use_stream=stream_callback is not None)
        print(
            f"[LLM] task={task_label or config_key} backend=cloud model={fmid} fallback=1"
        )
        return text


def get_llm_client_legacy(
    config: dict,
    model: Optional[str] = None,
    config_key: Optional[str] = None,
    legacy_model: Optional[str] = None,
) -> Optional[Tuple[Any, str]]:
    """兼容 AIAgent._get_llm_client 返回 (client, model_id)。"""
    lm = legacy_model if legacy_model is not None else model
    resolved = resolve_client(config, config_key=config_key, legacy_model=lm)
    if not resolved:
        return None
    client, model_id, _ = resolved
    return client, model_id


def chat_completion_create(
    config: dict,
    *,
    config_key: Optional[str] = None,
    legacy_model: Optional[str] = None,
    messages: List[dict],
    max_tokens: int = 1024,
    temperature: float = 0.2,
    timeout: float = 120,
    task_label: str = "",
):
    """返回完整 response 对象；含 fallback。"""
    resolved = resolve_client(
        config,
        config_key=config_key,
        legacy_model=legacy_model,
    )
    if not resolved:
        return None
    client, model_id, used_spec = resolved

    def _create(c, mid, s: ModelSpec):
        extra = get_spec_create_kwargs(config, s)
        return c.chat.completions.create(
            model=mid,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            **extra,
        )

    try:
        return _create(client, model_id, used_spec)
    except Exception as e:
        use_local_fb = used_spec.is_local() and config.get(
            "local_fail_fallback_to_cloud", False
        )
        use_custom_fb = used_spec.is_custom() and config.get(
            "custom_fail_fallback_to_cloud", False
        )
        if not use_local_fb and not use_custom_fb:
            raise
        fb = _fallback_cloud_spec(config)
        fb_client = get_client_for_spec(config, fb)
        if not fb_client:
            raise
        fc, fmid = fb_client
        label = task_label or config_key or "任务"
        _notify_status(f"{label} 本地模型不可用，已回退云端")
        print(f"⚠️ [LLM] fallback cloud after error: {e}")
        return _create(fc, fmid, fb)
