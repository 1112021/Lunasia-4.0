# -*- coding: utf-8 -*-
"""本地模型预热与 LM Studio 注入。"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Callable, List, Optional, Set

from llm_spec import MODEL_CONFIG_KEYS, ModelSpec, get_config_spec, normalize_spec


def _collect_lmstudio_specs(config: dict) -> List[ModelSpec]:
    seen: Set[str] = set()
    specs: List[ModelSpec] = []
    for key in MODEL_CONFIG_KEYS:
        spec = get_config_spec(config, key)
        if spec.backend != "lmstudio":
            continue
        k = spec.model_id
        if k in seen:
            continue
        seen.add(k)
        specs.append(spec)
    return specs


def _collect_ollama_specs(config: dict) -> List[ModelSpec]:
    seen: Set[str] = set()
    specs: List[ModelSpec] = []
    for key in MODEL_CONFIG_KEYS:
        spec = get_config_spec(config, key)
        if spec.backend != "ollama":
            continue
        k = spec.model_id
        if k in seen:
            continue
        seen.add(k)
        specs.append(spec)
    return specs


def lmstudio_inject(base_url: str, model_id: str, api_key: str = "") -> bool:
    base = (base_url or "").rstrip("/")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # 尝试 LM Studio load API（部分版本支持）
    for path, body in (
        ("/api/v1/models/load", {"model": model_id}),
        ("/v1/models/load", {"model": model_id}),
    ):
        try:
            req = urllib.request.Request(
                f"{base}{path}",
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                if resp.status in (200, 202):
                    print(f"✅ [LM Studio] 模型已加载: {model_id}")
                    return True
        except Exception:
            pass

    # 回退：极小 chat 触发加载
    try:
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
            "stream": False,
        }
        req = urllib.request.Request(
            f"{base}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            if resp.status == 200:
                print(f"✅ [LM Studio] 预热完成: {model_id}")
                return True
    except Exception as e:
        print(f"⚠️ [LM Studio] 加载/预热失败 {model_id}: {e}")
    return False


def ollama_warmup(base_url: str, model_id: str, api_key: str = "") -> bool:
    base = (base_url or "").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
        "keep_alive": "10m",
        "options": {"num_predict": 1},
    }
    try:
        req = urllib.request.Request(
            f"{base}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            if resp.status == 200:
                print(f"✅ [Ollama] 预热完成: {model_id}")
                return True
    except Exception as e:
        print(f"⚠️ [Ollama] 预热失败 {model_id}: {e}")
    return False


def run_local_startup_tasks(
    config: dict,
    status_callback: Optional[Callable[[str], None]] = None,
) -> None:
    if not config.get("local_preload_on_startup", False):
        return

    ocfg = config.get("ollama") or {}
    lcfg = config.get("lmstudio") or {}
    if not ocfg.get("enabled") and not lcfg.get("enabled"):
        return

    for spec in _collect_lmstudio_specs(config):
        if not lcfg.get("enabled"):
            continue
        msg = f"正在加载 LM Studio 模型 {spec.model_id}…"
        print(f"🔧 {msg}")
        if status_callback:
            status_callback(msg)
        ok = lmstudio_inject(
            lcfg.get("base_url", ""),
            spec.model_id,
            lcfg.get("api_key") or "",
        )
        if status_callback:
            status_callback(
                f"LM Studio {spec.model_id} 已就绪" if ok else f"LM Studio {spec.model_id} 加载失败"
            )

    for spec in _collect_ollama_specs(config):
        if not ocfg.get("enabled"):
            continue
        msg = f"正在预热 Ollama 模型 {spec.model_id}…"
        print(f"🔧 {msg}")
        if status_callback:
            status_callback(msg)
        ok = ollama_warmup(
            ocfg.get("base_url", ""),
            spec.model_id,
            ocfg.get("api_key") or "",
        )
        if status_callback:
            status_callback(
                f"Ollama {spec.model_id} 已就绪" if ok else f"Ollama {spec.model_id} 预热失败"
            )


def schedule_local_startup(config: dict, status_callback: Optional[Callable[[str], None]] = None) -> None:
    t = threading.Thread(
        target=run_local_startup_tasks,
        args=(config, status_callback),
        daemon=True,
    )
    t.start()


def run_lmstudio_reinject_after_settings(config: dict, status_callback: Optional[Callable[[str], None]] = None) -> None:
    lcfg = config.get("lmstudio") or {}
    if not lcfg.get("enabled"):
        return
    specs = _collect_lmstudio_specs(config)
    if not specs:
        return

    def _work():
        for spec in specs:
            lmstudio_inject(
                lcfg.get("base_url", ""),
                spec.model_id,
                lcfg.get("api_key") or "",
            )
        if status_callback:
            status_callback("LM Studio 模型已重新加载")

    threading.Thread(target=_work, daemon=True).start()
