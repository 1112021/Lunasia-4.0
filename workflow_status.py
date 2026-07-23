# -*- coding: utf-8 -*-
"""Structured, concise workflow status helpers shared by agents and UI."""

from __future__ import annotations

import re
from urllib.parse import urlparse


INTERNAL_ACTIONS = {
    "",
    "pass_to_main_agent",
    "get_location",
    "search_web",  # The search pipeline reports more accurate query/page objects.
}


def shorten(value: object, limit: int = 22) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + "…"


def url_host(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not text.startswith(("http://", "https://")):
        return shorten(text)
    try:
        return urlparse(text).netloc or shorten(text)
    except Exception:
        return shorten(text)


def emit_workflow(agent, key: str, title: str, phase: str = "active") -> None:
    """Emit a workflow event when a UI callback has been attached."""
    callback = getattr(agent, "workflow_event_callback", None)
    if not callable(callback) or not title:
        return
    try:
        callback(str(key), shorten(title, 42), str(phase))
    except Exception:
        pass


def _first_param(params: dict, *names: str) -> str:
    for name in names:
        value = params.get(name)
        if value:
            return str(value)
    return ""


def framework_step_title(
    action: str,
    params: dict,
    *,
    phase: str,
    user_input: str = "",
    result: str = "",
) -> str:
    """Map framework internals to short, object-bearing user-facing sentences."""
    if action in INTERNAL_ACTIONS:
        return ""

    active = phase == "active"
    failed = bool(re.search(r"(失败|无法|错误|未找到|❌)", result or ""))
    if failed and not active:
        prefix = "处理失败"
    else:
        prefix = ""

    if action == "get_url_from_website_map":
        target = _first_param(params, "name", "website", "website_name") or "网站"
        return (
            f"查找 {shorten(target)} 地址中"
            if active
            else (f"{prefix}：{shorten(target)}" if failed else f"已找到 {shorten(target)} 地址")
        )

    if action in {"open_application"}:
        target = _first_param(params, "name", "application_name", "app", "app_name") or "应用"
        return (
            f"打开 {shorten(target)} 中"
            if active
            else (f"无法打开 {shorten(target)}" if failed else f"已打开 {shorten(target)}")
        )

    if action in {"open_website", "call_playwright_react"}:
        target = _first_param(params, "url", "name", "website") or ""
        target = url_host(target)
        if not target:
            return ""
        return (
            f"打开 {target} 中"
            if active
            else (f"无法打开 {target}" if failed else f"已打开 {target}")
        )

    if action == "get_weather":
        target = _first_param(params, "city", "location") or shorten(user_input, 16)
        return (
            f"查询 {target} 天气中"
            if active
            else (f"天气查询失败：{target}" if failed else f"已查询 {target} 天气")
        )

    if action in {"analyze_image", "combined_vision_images"}:
        target = shorten(_first_param(params, "target", "name") or "图片")
        return (
            f"分析 {target} 中"
            if active
            else (f"分析 {target} 失败" if failed else f"已分析 {target}")
        )
    if action == "analyze_screen":
        return "查看屏幕中" if active else ("查看屏幕失败" if failed else "已查看屏幕")
    if action in {"analyze_video", "combined_vision_video", "combined_video_segment"}:
        target = shorten(_first_param(params, "target", "name") or "视频")
        return (
            f"分析 {target} 中"
            if active
            else (f"分析 {target} 失败" if failed else f"已分析 {target}")
        )
    if action in {"analyze_file", "combined_extract_files"}:
        target = shorten(_first_param(params, "target", "name") or "附件")
        return (
            f"分析 {target} 中"
            if active
            else (f"分析 {target} 失败" if failed else f"已分析 {target}")
        )

    if action.startswith(("use_hexstrike", "execute_hexstrike", "start_hexstrike", "kali_")):
        return "执行安全检测中" if active else ("安全检测失败" if failed else "已完成安全检测")
    if action == "use_mcp_tool":
        target = _first_param(params, "tool_name") or "工具"
        return (
            f"运行 {shorten(target)} 中"
            if active
            else (f"{shorten(target)} 运行失败" if failed else f"已运行 {shorten(target)}")
        )
    return ""
