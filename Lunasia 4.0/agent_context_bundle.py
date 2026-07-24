# -*- coding: utf-8 -*-
"""主 Agent 与组合发送/视觉路径共用的上下文准备（记忆、联网）。"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

StreamCallback = Optional[Callable[[str], None]]


def prepare_context_bundle(
    agent,
    user_input: str,
    *,
    skip_memory_recall: bool = False,
) -> Dict[str, Any]:
    """
    与 _generate_response_with_context 前置逻辑一致：
    回忆 + 联网检索，返回可拼进 prompt 的 context_info。
    """
    context_info: Dict[str, Any] = {
        "current_time": agent._get_current_time(),
    }
    if getattr(agent, "location", None):
        context_info["user_location"] = agent.location

    if not skip_memory_recall:
        try:
            from context_link_memory import (
                build_context_link_memory_bundle,
                is_context_link_enabled,
            )
        except ImportError:
            is_context_link_enabled = lambda c: False  # type: ignore
            build_context_link_memory_bundle = None  # type: ignore

        if is_context_link_enabled(agent.config) and build_context_link_memory_bundle:
            ct = context_info.get("current_time") or agent._get_current_time()
            bundle = build_context_link_memory_bundle(agent, user_input, ct)
            if bundle.link_block_text:
                context_info["context_link_block"] = bundle.link_block_text
            if bundle.lake_block_text:
                context_info["memory_context"] = bundle.lake_block_text
            context_info["_context_link_session_window"] = bundle.session_window_text
        else:
            relevant = agent._intelligent_memory_recall(user_input)
            if relevant:
                context_info["memory_context"] = relevant

    if agent.config.get("enable_web_search", False):
        try:
            from web_search_pipeline import recognize_web_search_intent, run_web_search

            intent = recognize_web_search_intent(
                agent, user_input, agent._get_recent_context()
            )
            if intent.get("need_search"):
                print(f"🔍 [组合发送] 联网检索: {intent.get('reason', '')}")

                def _status(msg):
                    print(f"🔍 {msg}")
                    try:
                        agent.response_status_message.emit(msg)
                    except Exception:
                        pass

                bundle = run_web_search(
                    agent,
                    user_input,
                    conversation_context=agent._get_recent_context(),
                    status_callback=_status,
                )
                if bundle.context_text:
                    context_info["search_info"] = bundle.context_text
                    print(f"📊 [组合发送] 检索上下文长度: {len(bundle.context_text)}")
            else:
                print(f"🔍 [组合发送] 跳过联网: {intent.get('reason', '')}")
        except Exception as e:
            print(f"⚠️ [组合发送] 联网失败: {e}")

    return context_info


def context_info_to_prompt_blocks(context_info: dict, agent) -> str:
    """将 context_info 转为可嵌入视觉/文本 prompt 的文本块。"""
    parts = []
    if context_info.get("current_time"):
        parts.append(f"当前时间：{context_info['current_time']}")
    if context_info.get("user_location"):
        parts.append(f"用户位置：{context_info['user_location']}")
    if context_info.get("memory_context"):
        parts.append(f"【识底深湖相关回忆】\n{context_info['memory_context']}")
    if context_info.get("context_link_block"):
        parts.append(f"【上下文联系】\n{context_info['context_link_block']}")
    window = context_info.get("_context_link_session_window")
    if window:
        parts.append(f"【近期会话】\n{window}")
    elif not context_info.get("context_link_block"):
        try:
            recent = agent._get_recent_context()
            if recent:
                parts.append(f"【近期会话】\n{recent}")
        except Exception:
            pass
    if context_info.get("search_info"):
        parts.append(f"【网络搜索信息】\n{context_info['search_info']}")
    return "\n\n".join(parts)
