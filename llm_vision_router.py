# -*- coding: utf-8 -*-
"""视觉模型路由：按场景 ModelSpec 分发读屏 / 图片 / 视频。"""

from __future__ import annotations

import base64
import concurrent.futures
import mimetypes
import os
from typing import Any, Callable, List, Optional, Tuple

import openai

StreamCallback = Optional[Callable[[str], None]]

from custom_models_store import (
    CAP_VISION,
    find_custom_by_id,
    get_custom_create_kwargs,
    get_vision_dashscope_api_key,
)
from llm_spec import (
    VISION_MODEL_CONFIG_KEYS,
    VISION_MODEL_DEFAULTS,
    ModelSpec,
    dashscope_spec,
    get_config_spec,
)

DASHSCOPE_V1 = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _vision_test_png_b64() -> str:
    """32×32 测试图（DashScope 等要求宽高 > 10）。"""
    import io

    from PIL import Image

    img = Image.new("RGB", (32, 32), color=(200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")

SCENARIO_CONFIG_KEYS = {
    "screen": "vision_screen_model",
    "image": "vision_image_model",
    "video": "vision_video_model",
}


def _mime_for_path(path: str, default: str = "image/jpeg") -> str:
    mt, _ = mimetypes.guess_type(path)
    return mt or default


def _read_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _dashscope_client(config: dict) -> Optional[openai.OpenAI]:
    key = get_vision_dashscope_api_key(config)
    if not key:
        return None
    return openai.OpenAI(api_key=key, base_url=DASHSCOPE_V1)


def _spec_usable(config: dict, spec: ModelSpec) -> bool:
    if spec.backend == "custom":
        if not spec.custom_id:
            return False
        entry = find_custom_by_id(config, spec.custom_id)
        if not entry or not entry.get("enabled", True):
            return False
        caps = entry.get("capabilities") or []
        return CAP_VISION in caps and bool((entry.get("base_url") or "").strip())
    if spec.backend == "dashscope":
        return bool(get_vision_dashscope_api_key(config))
    if spec.backend == "cloud":
        if spec.provider == "openai":
            return bool((config.get("openai_key") or "").strip())
        return bool((config.get("deepseek_key") or "").strip())
    if spec.backend == "ollama":
        ocfg = config.get("ollama") or {}
        return bool(ocfg.get("enabled") and ocfg.get("base_url"))
    if spec.backend == "lmstudio":
        lcfg = config.get("lmstudio") or {}
        return bool(lcfg.get("enabled") and lcfg.get("base_url"))
    return False


def vision_is_configured(config: dict) -> bool:
    for key in VISION_MODEL_CONFIG_KEYS:
        if _spec_usable(config, get_config_spec(config, key)):
            return True
    return False


def _resolve_vision_client(
    config: dict, spec: ModelSpec
) -> Optional[Tuple[openai.OpenAI, str]]:
    if spec.backend == "custom":
        entry = find_custom_by_id(config, spec.custom_id)
        if not entry or not entry.get("enabled", True):
            return None
        caps = entry.get("capabilities") or []
        if CAP_VISION not in caps:
            return None
        base_url = (entry.get("base_url") or "").strip()
        if not base_url:
            return None
        api_key = (entry.get("api_key") or "").strip() or "none"
        model_id = (entry.get("model_id") or spec.model_id or "").strip()
        if not model_id:
            return None
        return openai.OpenAI(api_key=api_key, base_url=base_url), model_id

    if spec.backend == "dashscope":
        client = _dashscope_client(config)
        if not client:
            return None
        return client, spec.model_id

    if spec.backend == "cloud":
        if spec.provider == "openai":
            api_key = (config.get("openai_key") or "").strip()
            if not api_key:
                return None
            return openai.OpenAI(api_key=api_key), spec.model_id
        api_key = (config.get("deepseek_key") or "").strip()
        if not api_key:
            return None
        return openai.OpenAI(
            api_key=api_key, base_url="https://api.deepseek.com/v1"
        ), spec.model_id

    if spec.backend == "ollama":
        ocfg = config.get("ollama") or {}
        base_url = (ocfg.get("base_url") or "http://localhost:11434").rstrip("/")
        api_key = ocfg.get("api_key") or "ollama"
        return openai.OpenAI(api_key=api_key, base_url=f"{base_url}/v1"), spec.model_id

    if spec.backend == "lmstudio":
        lcfg = config.get("lmstudio") or {}
        base_url = (lcfg.get("base_url") or "http://localhost:1234").rstrip("/")
        api_key = lcfg.get("api_key") or "lmstudio"
        return openai.OpenAI(api_key=api_key, base_url=f"{base_url}/v1"), spec.model_id

    return None


def _fallback_dashscope_spec(config_key: str) -> ModelSpec:
    return dashscope_spec(VISION_MODEL_DEFAULTS[config_key])


def _chat_vision_messages(
    client: openai.OpenAI,
    model_id: str,
    messages: list,
    *,
    max_tokens: int = 2000,
    temperature: float = 0.5,
    timeout: float = 300,
    stream_callback: StreamCallback = None,
    custom_create_kwargs: Optional[dict] = None,
) -> str:
    extra = custom_create_kwargs or {}
    if stream_callback is not None:
        try:
            stream = client.chat.completions.create(
                model=model_id,
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
        except Exception as e:
            print(f"⚠️ [视觉] 流式调用失败，回退非流式: {e}")
    resp = client.chat.completions.create(
        model=model_id,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        **extra,
    )
    return (resp.choices[0].message.content or "").strip()


def _chat_vision(
    client: openai.OpenAI,
    model_id: str,
    content: list,
    *,
    max_tokens: int = 2000,
    temperature: float = 0.5,
    timeout: float = 300,
    stream_callback: StreamCallback = None,
    custom_create_kwargs: Optional[dict] = None,
    system_prompt: str = "",
) -> str:
    messages = []
    if system_prompt and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": content})
    return _chat_vision_messages(
        client,
        model_id,
        messages,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        stream_callback=stream_callback,
        custom_create_kwargs=custom_create_kwargs,
    )


def _run_with_fallback(
    config: dict,
    config_key: str,
    content: list,
    *,
    temperature: float = 0.5,
    timeout: float = 300,
    label: str = "视觉",
    stream_callback: StreamCallback = None,
    system_prompt: str = "",
) -> str:
    spec = get_config_spec(config, config_key)
    custom_kwargs = get_custom_create_kwargs(config, spec) if spec.is_custom() else {}
    resolved = _resolve_vision_client(config, spec)
    if resolved:
        client, model_id = resolved
        try:
            print(f"[{label}] {spec.display_name(config)} (backend={spec.backend} model={model_id})")
            return _chat_vision(
                client,
                model_id,
                content,
                temperature=temperature,
                timeout=timeout,
                stream_callback=stream_callback,
                custom_create_kwargs=custom_kwargs,
                system_prompt=system_prompt,
            )
        except Exception as e:
            print(f"⚠️ [{label}] 调用失败 backend={spec.backend} model={model_id}: {e}")
            if spec.backend != "custom" or not config.get(
                "vision_custom_fallback_to_dashscope", True
            ):
                raise
    elif spec.backend == "custom" and not config.get(
        "vision_custom_fallback_to_dashscope", True
    ):
        return "错误：未配置有效的自定义视觉模型"

    fb = _fallback_dashscope_spec(config_key)
    fb_resolved = _resolve_vision_client(config, fb)
    if not fb_resolved:
        return "错误：未配置 DashScope 视觉 API 密钥"
    client, model_id = fb_resolved
    print(f"[{label}] 回退 DashScope {fb.display_name(config)} (model={model_id})")
    return _chat_vision(
        client,
        model_id,
        content,
        temperature=temperature,
        timeout=timeout,
        stream_callback=stream_callback,
        system_prompt=system_prompt,
    )


def analyze_image_file(
    config: dict,
    file_path: str,
    user_question: str = "",
    stream_callback: StreamCallback = None,
    system_prompt: str = "",
) -> str:
    if not os.path.exists(file_path):
        return "错误：文件不存在"
    mime = _mime_for_path(file_path)
    b64 = _read_b64(file_path)
    if user_question:
        prompt = f"请分析这张图片，并回答以下问题：{user_question}"
    else:
        prompt = (
            "请详细分析这张图片的内容，包括图片中的文字、物体、场景、布局等所有可见信息。"
            "以通常精准冷静语气回答，但直接与用户聊天时要用略亲切的语气"
        )
    content = [
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        {"type": "text", "text": prompt},
    ]
    try:
        return _run_with_fallback(
            config,
            "vision_image_model",
            content,
            label="视觉·图片",
            stream_callback=stream_callback,
            system_prompt=system_prompt,
        )
    except Exception as e:
        return f"图片分析失败: {e}"


def _vision_messages_with_context(
    context_text: str,
    user_question: str,
    content_parts: list,
    *,
    system_prompt: str = "",
) -> list:
    user_text = user_question.strip() or "请根据附件内容回答。"
    blocks = []
    if context_text.strip():
        blocks.append(context_text.strip())
    blocks.append(f"【用户问题】\n{user_text}")
    content = list(content_parts)
    content.append({"type": "text", "text": "\n\n".join(blocks)})
    messages = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": content})
    return messages


def _run_vision_messages_with_fallback(
    config: dict,
    config_key: str,
    messages: list,
    *,
    temperature: float = 0.5,
    timeout: float = 300,
    label: str = "视觉",
    stream_callback: StreamCallback = None,
    max_tokens: int = 2000,
) -> str:
    spec = get_config_spec(config, config_key)
    custom_kwargs = get_custom_create_kwargs(config, spec) if spec.is_custom() else {}
    resolved = _resolve_vision_client(config, spec)
    if resolved:
        client, model_id = resolved
        try:
            print(f"[{label}] {spec.display_name(config)} (backend={spec.backend} model={model_id})")
            return _chat_vision_messages(
                client,
                model_id,
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
                stream_callback=stream_callback,
                custom_create_kwargs=custom_kwargs,
            )
        except Exception as e:
            print(f"⚠️ [{label}] 调用失败: {e}")
            if spec.backend != "custom" or not config.get(
                "vision_custom_fallback_to_dashscope", True
            ):
                raise
    fb = _fallback_dashscope_spec(config_key)
    fb_resolved = _resolve_vision_client(config, fb)
    if not fb_resolved:
        return "错误：未配置有效的视觉模型"
    client, model_id = fb_resolved
    print(f"[{label}] 回退 DashScope {fb.display_name(config)} (model={model_id})")
    return _chat_vision_messages(
        client,
        model_id,
        messages,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        stream_callback=stream_callback,
    )


def analyze_images_combined(
    config: dict,
    image_paths: List[str],
    user_question: str = "",
    context_text: str = "",
    file_extract: str = "",
    *,
    batch_mode: str = "single",
    stream_callback: StreamCallback = None,
    system_prompt: str = "",
) -> str:
    if not image_paths:
        return "错误：无图片"
    question = user_question.strip() or "请根据附件内容回答。"
    if file_extract.strip():
        context_text = (context_text + "\n\n【附件文件内容】\n" + file_extract).strip()

    def _image_parts(paths: List[str]) -> list:
        parts = []
        for p in paths:
            mime = _mime_for_path(p)
            b64 = _read_b64(p)
            parts.append(
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
            )
        return parts

    if batch_mode == "single" or len(image_paths) == 1:
        try:
            messages = _vision_messages_with_context(
                context_text,
                question,
                _image_parts(image_paths),
                system_prompt=system_prompt,
            )
            return _run_vision_messages_with_fallback(
                config,
                "vision_image_model",
                messages,
                label="视觉·组合图片",
                stream_callback=stream_callback,
                max_tokens=3000,
            )
        except Exception as e:
            print(f"⚠️ [组合图片] 批量请求失败，改逐张: {e}")
            batch_mode = "sequential"

    summaries: List[str] = []
    for i, p in enumerate(image_paths):
        name = os.path.basename(p)
        sub_q = f"{question}\n（当前为第 {i + 1}/{len(image_paths)} 张图片：{name}）"
        messages = _vision_messages_with_context(
            context_text,
            sub_q,
            _image_parts([p]),
            system_prompt=system_prompt,
        )
        part = _run_vision_messages_with_fallback(
            config,
            "vision_image_model",
            messages,
            label=f"视觉·组合图片 {i + 1}/{len(image_paths)}",
            stream_callback=None,
            max_tokens=2000,
        )
        summaries.append(f"【{name}】\n{part}")

    if len(summaries) == 1:
        result = summaries[0]
        if stream_callback:
            stream_callback(result)
        return result

    merge_prompt = (
        f"{question}\n\n以下是逐张图片的分析，请综合回答：\n\n"
        + "\n\n".join(summaries)
    )
    merge_messages = _vision_messages_with_context(
        context_text, merge_prompt, [], system_prompt=system_prompt
    )
    return _run_vision_messages_with_fallback(
        config,
        "vision_image_model",
        merge_messages,
        label="视觉·组合图片汇总",
        stream_callback=stream_callback,
        max_tokens=3000,
    )


def analyze_video_combined_direct(
    config: dict,
    file_path: str,
    user_question: str = "",
    context_text: str = "",
    file_extract: str = "",
    *,
    stream_callback: StreamCallback = None,
    system_prompt: str = "",
) -> str:
    if not os.path.exists(file_path):
        return "错误：文件不存在"
    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if size_mb > 8:
        return "错误：文件内容过大"
    if file_extract.strip():
        context_text = (context_text + "\n\n【附件文件内容】\n" + file_extract).strip()
    b64 = _read_b64(file_path)
    question = user_question.strip() or "请根据视频内容回答。"
    content_parts = [
        {"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{b64}"}},
    ]
    messages = _vision_messages_with_context(
        context_text, question, content_parts, system_prompt=system_prompt
    )
    return _run_vision_messages_with_fallback(
        config,
        "vision_video_model",
        messages,
        label="视觉·组合视频",
        stream_callback=stream_callback,
        timeout=300,
        max_tokens=3000,
    )


def analyze_screen_image(
    config: dict,
    image_path: str,
    user_question: str = "",
    stream_callback: StreamCallback = None,
    system_prompt: str = "",
) -> str:
    if not os.path.exists(image_path):
        return "错误：截图文件不存在"
    b64 = _read_b64(image_path)
    if user_question:
        prompt = f"这是用户当前的电脑屏幕截图。请根据截图内容回答用户的问题：{user_question}"
    else:
        prompt = (
            "这是用户当前的电脑屏幕截图。请详细描述屏幕上的内容，"
            "包括窗口、文字、图标、布局等所有可见信息。"
        )
    content = [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        {"type": "text", "text": prompt},
    ]
    try:
        return _run_with_fallback(
            config,
            "vision_screen_model",
            content,
            temperature=0.3,
            label="视觉·读屏",
            stream_callback=stream_callback,
            system_prompt=system_prompt,
        )
    except Exception as e:
        return f"屏幕分析失败: {e}"


def _extract_keyframes(
    file_path: str, max_frames: int = 12, max_duration: float = 30.0
) -> List[Tuple[float, Any]]:
    import cv2

    cap = cv2.VideoCapture(file_path)
    if not cap.isOpened():
        return []
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = min(frame_count / fps if fps > 0 else 0, max_duration)
    if duration <= 0:
        cap.release()
        return []
    interval = max(duration / max_frames, 1.0)
    frames: List[Tuple[float, Any]] = []
    t = 0.0
    while t < duration and len(frames) < max_frames:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        if ret:
            frames.append((t, frame))
        t += interval
    cap.release()
    return frames


def _frames_to_multimodal_content(
    frames: List[Tuple[float, Any]], prompt: str
) -> list:
    import cv2
    import io
    from PIL import Image

    content: list = []
    for t, frame in frames:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        fb64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{fb64}"},
            }
        )
    content.append({"type": "text", "text": prompt})
    return content


def _custom_video_path_a(
    client: openai.OpenAI,
    model_id: str,
    file_path: str,
    user_question: str,
    custom_create_kwargs: Optional[dict] = None,
    system_prompt: str = "",
) -> Tuple[bool, str]:
    file_size = os.path.getsize(file_path)
    if file_size > 8 * 1024 * 1024:
        return False, "视频过大，video_url 直传不可用"
    b64 = _read_b64(file_path)
    if user_question:
        prompt = f"请分析这个视频，并回答以下问题：{user_question}"
    else:
        prompt = "请详细分析这个视频的内容。"
    content = [
        {"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{b64}"}},
        {"type": "text", "text": prompt},
    ]
    try:
        return True, _chat_vision(
            client, model_id, content, timeout=300,
            custom_create_kwargs=custom_create_kwargs,
            system_prompt=system_prompt,
        )
    except Exception as e:
        return False, str(e)


def _custom_video_path_b(
    client: openai.OpenAI,
    model_id: str,
    file_path: str,
    user_question: str,
    custom_create_kwargs: Optional[dict] = None,
) -> Tuple[bool, str]:
    frames = _extract_keyframes(file_path, max_frames=12, max_duration=30.0)
    if not frames:
        return False, "无法提取视频关键帧"
    parts: List[str] = []
    for i, (t, _) in enumerate(frames):
        seg_prompt = (
            f"这是视频在 {t:.1f}s 附近的一帧（第 {i + 1}/{len(frames)} 帧）。"
        )
        if user_question:
            seg_prompt += f" 请描述画面并有助于回答：{user_question}"
        else:
            seg_prompt += " 请描述画面中的场景、文字、人物与动作。"
        one_content = _frames_to_multimodal_content([(t, frames[i][1])], seg_prompt)
        try:
            seg_text = _chat_vision(
                client,
                model_id,
                one_content,
                timeout=120,
                custom_create_kwargs=custom_create_kwargs,
            )
            parts.append(f"【{t:.1f}s】\n{seg_text}")
        except Exception as e:
            parts.append(f"【{t:.1f}s】分析失败: {e}")
    if not parts:
        return False, "关键帧分析无结果"
    header = "以下按时间顺序汇总各关键帧分析：\n\n"
    if user_question:
        header = f"以下按时间顺序汇总各关键帧，用于回答问题：{user_question}\n\n"
    return True, header + "\n\n".join(parts)


def _custom_analyze_video_parallel(
    config: dict, file_path: str, user_question: str, system_prompt: str = ""
) -> Tuple[bool, str]:
    spec = get_config_spec(config, "vision_video_model")
    if spec.backend != "custom":
        return False, "当前视频模型不是自定义"
    resolved = _resolve_vision_client(config, spec)
    if not resolved:
        return False, "自定义视觉模型不可用"
    client, model_id = resolved
    custom_kwargs = get_custom_create_kwargs(config, spec)

    def run_a():
        return _custom_video_path_a(
            client, model_id, file_path, user_question, custom_kwargs,
            system_prompt=system_prompt,
        )

    def run_b():
        return _custom_video_path_b(
            client, model_id, file_path, user_question, custom_kwargs
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        fa = pool.submit(run_a)
        fb = pool.submit(run_b)
        ok_a, res_a = fa.result()
        ok_b, res_b = fb.result()

    print(
        f"📹 [视觉·视频] 自定义 A={'成功' if ok_a else '失败'} "
        f"B={'成功' if ok_b else '失败'}"
    )
    result_text = res_a if ok_a else (res_b if ok_b else "")
    if result_text:
        return True, result_text
    return False, f"A: {res_a}; B: {res_b}"


def _dashscope_analyze_video_direct(
    config: dict,
    file_path: str,
    user_question: str,
    spec: ModelSpec,
    stream_callback: StreamCallback = None,
    system_prompt: str = "",
) -> Tuple[bool, str]:
    file_size = os.path.getsize(file_path)
    if file_size > 8 * 1024 * 1024:
        return False, f"视频过大（{file_size / 1024 / 1024:.1f}MB），超过直传安全阈值"
    resolved = _resolve_vision_client(config, spec)
    if not resolved:
        return False, "无法连接 DashScope 视觉 API"
    client, model_id = resolved
    b64 = _read_b64(file_path)
    if user_question:
        prompt = f"请分析这个视频，并回答以下问题：{user_question}"
    else:
        prompt = "请详细分析这个视频的内容，包括场景、动作、文字、物体、人物等所有可见信息。"
    content = [
        {"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{b64}"}},
        {"type": "text", "text": prompt},
    ]
    try:
        custom_kwargs = (
            get_custom_create_kwargs(config, spec) if spec.is_custom() else {}
        )
        text = _chat_vision(
            client,
            model_id,
            content,
            timeout=300,
            stream_callback=stream_callback,
            custom_create_kwargs=custom_kwargs,
            system_prompt=system_prompt,
        )
        return True, text
    except Exception as e:
        return False, str(e)


def analyze_video_file(
    config: dict,
    file_path: str,
    user_question: str = "",
    stream_callback: StreamCallback = None,
    system_prompt: str = "",
) -> str:
    if not os.path.exists(file_path):
        return "错误：文件不存在"

    spec = get_config_spec(config, "vision_video_model")
    if spec.backend == "custom":
        ok, text = _custom_analyze_video_parallel(
            config, file_path, user_question, system_prompt=system_prompt
        )
        if ok:
            if stream_callback:
                stream_callback(text)
            return text
        print(f"⚠️ [视觉·视频] 自定义双路径均失败: {text}")
        if not config.get("vision_custom_fallback_to_dashscope", True):
            return f"视频分析失败: {text}"
        spec = _fallback_dashscope_spec("vision_video_model")

    ok, text = _dashscope_analyze_video_direct(
        config, file_path, user_question, spec,
        stream_callback=stream_callback, system_prompt=system_prompt,
    )
    if ok:
        return text
    if spec.backend != "custom" and spec.backend != "dashscope":
        return f"视频分析失败: {text}"
    return f"视频分析失败: {text}"


def is_dashscope_video_spec(config: dict) -> bool:
    spec = get_config_spec(config, "vision_video_model")
    return spec.backend == "dashscope"


def test_custom_vision(entry: dict) -> Tuple[bool, str]:
    base_url = (entry.get("base_url") or "").strip()
    model_id = (entry.get("model_id") or "").strip()
    if not base_url or not model_id:
        return False, "URL 或模型名为空"
    api_key = (entry.get("api_key") or "").strip() or "none"
    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    content = [
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{_vision_test_png_b64()}"},
        },
        {"type": "text", "text": "回复 OK"},
    ]
    try:
        text = _chat_vision(client, model_id, content, max_tokens=16, timeout=60)
        return True, text or "OK"
    except Exception as e:
        return False, str(e)


def test_custom_text(entry: dict) -> Tuple[bool, str]:
    base_url = (entry.get("base_url") or "").strip()
    model_id = (entry.get("model_id") or "").strip()
    if not base_url or not model_id:
        return False, "URL 或模型名为空"
    api_key = (entry.get("api_key") or "").strip() or "none"
    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    try:
        resp = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": "回复 OK"}],
            max_tokens=16,
            timeout=60,
        )
        text = (resp.choices[0].message.content or "").strip()
        return True, text or "OK"
    except Exception as e:
        return False, str(e)
