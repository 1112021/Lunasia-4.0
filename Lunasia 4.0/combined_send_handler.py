# -*- coding: utf-8 -*-
"""组合发送：路由、框架步骤与视觉/主 Agent 执行。"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from agent_context_bundle import context_info_to_prompt_blocks, prepare_context_bundle
from combined_attachments import (
    CombinedAttachments,
    extract_files_text,
    format_planner_attachment_hint,
    register_recent_on_agent,
    video_needs_segmentation,
)
from llm_vision_router import analyze_images_combined, analyze_video_combined_direct

StreamCallback = Optional[Callable[[str], None]]


def prepare_combined_context_text(agent, user_text: str) -> str:
    bundle = prepare_context_bundle(agent, user_text)
    return context_info_to_prompt_blocks(bundle, agent)


def get_file_extract(agent) -> str:
    att = getattr(agent, "combined_send_payload", None)
    if not att or not att.has_files():
        return ""
    cached = getattr(agent, "_combined_file_extract", "")
    if cached:
        return cached
    return extract_files_text(att.file_paths, agent.config)


def run_combined_vision_images(
    agent,
    att: CombinedAttachments,
    *,
    stream_callback: StreamCallback = None,
) -> str:
    file_extract = get_file_extract(agent)
    context_text = prepare_combined_context_text(agent, att.user_text)
    batch_mode = att.image_batch_mode(agent.config)
    agent.pause_local_tts_for_vision()
    try:
        result = analyze_images_combined(
            agent.config,
            att.image_paths,
            user_question=att.user_text,
            context_text=context_text,
            file_extract=file_extract,
            batch_mode=batch_mode,
            system_prompt=agent.get_main_system_prompt(),
            stream_callback=stream_callback,
        )
    finally:
        agent.resume_local_tts_after_vision()
    if agent.recent_image_analysis:
        agent.recent_image_analysis["analysis"] = result
    return result


def run_combined_vision_video_direct(
    agent,
    att: CombinedAttachments,
    *,
    stream_callback: StreamCallback = None,
) -> str:
    file_extract = get_file_extract(agent)
    context_text = prepare_combined_context_text(agent, att.user_text)
    agent.pause_local_tts_for_vision()
    try:
        result = analyze_video_combined_direct(
            agent.config,
            att.video_paths[0],
            user_question=att.user_text,
            context_text=context_text,
            file_extract=file_extract,
            system_prompt=agent.get_main_system_prompt(),
            stream_callback=stream_callback,
        )
    finally:
        agent.resume_local_tts_after_vision()
    if agent.recent_video_analysis:
        agent.recent_video_analysis["analysis"] = result
    return result


def run_combined_video_segment(
    agent,
    att: CombinedAttachments,
    *,
    stream_callback: StreamCallback = None,
) -> str:
    """分段视觉分析视频；中间关键帧结果只交给主 Agent 整合。"""
    # 此步骤之后必然会执行 pass_to_main_agent。若把视觉模型的逐帧原始
    # 输出流式推到 UI，随后主 Agent 的最终总结会被拼到同一条助手回复中。
    # 因此这里刻意不传 stream_callback；仅最终整合阶段允许流式显示。
    result = agent.process_video(
        att.video_paths[0],
        att.user_text,
        stream_callback=None,
    )
    if "[SEGMENTED_VIDEO_ANALYSIS]" in result:
        result = result.replace("[SEGMENTED_VIDEO_ANALYSIS]\n", "").replace(
            "[SEGMENTED_VIDEO_ANALYSIS]", ""
        )
    if agent.recent_video_analysis:
        agent.recent_video_analysis["analysis"] = result
        agent.recent_video_analysis["is_segmented"] = True
    return result


def build_combined_framework(
    att: CombinedAttachments, config: dict
) -> Tuple[List[Dict[str, Any]], str]:
    hint = format_planner_attachment_hint(att, config)
    steps: List[Dict[str, Any]] = []

    if att.has_images():
        steps.append(
            {
                "description": "组合发送：视觉分析图片并回答",
                "action": "combined_vision_images",
                "params": {
                    "direct_return": True,
                    "target": os.path.basename(att.image_paths[0])
                    + (f" 等 {len(att.image_paths)} 张图片" if len(att.image_paths) > 1 else ""),
                },
            }
        )
    elif att.has_video():
        seg, _ = video_needs_segmentation(att.video_paths[0])
        if seg:
            steps.append(
                {
                    "description": "组合发送：分段分析视频",
                    "action": "combined_video_segment",
                    "params": {"target": os.path.basename(att.video_paths[0])},
                }
            )
            steps.append(
                {
                    "description": "主 Agent 整合视频分段与附件文件",
                    "action": "pass_to_main_agent",
                    "params": {},
                }
            )
        else:
            steps.append(
                {
                    "description": "组合发送：视觉分析视频并回答",
                    "action": "combined_vision_video",
                    "params": {
                        "direct_return": True,
                        "target": os.path.basename(att.video_paths[0]),
                    },
                }
            )
    elif att.has_files():
        steps.append(
            {
                "description": "组合发送：主 Agent 根据文件内容回答",
                "action": "pass_to_main_agent",
                "params": {},
            }
        )
    return steps, hint


def setup_combined_payload(agent, att: CombinedAttachments) -> str:
    """提取文件、注册 recent_*，返回聊天展示行。"""
    file_extract = (
        extract_files_text(att.file_paths, agent.config) if att.has_files() else ""
    )
    register_recent_on_agent(agent, att, file_extract)
    agent.combined_send_payload = att
    agent._combined_file_extract = file_extract
    from combined_attachments import format_user_chat_line

    return format_user_chat_line(att.user_text, att)
