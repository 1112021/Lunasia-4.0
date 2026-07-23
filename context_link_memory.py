# -*- coding: utf-8 -*-
"""
上下文联系及短期记忆轻量化增强系统 v2。
识底深湖存储不变：AI 选取池（时间+语义）→ 向量选取及分数修改智能体 → 与向量检索合并 → 分块注入。
"""

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_SELECT_JSON = {
    "time_scope": "unlimited",
    "calendar_date": "",
    "recent_topic_limit": 60,
    "content_semantic_query": "",
    "sort_order": "newest_first",
    "skip_ai_selection": False,
}

DEFAULT_RANK_JSON = {
    "boosts": [],
    "scoring": {
        "time_direction": "none",
        "time_boost_cap": 0.0,
    },
}


@dataclass
class ContextLinkBundle:
    session_window_text: str
    link_block_text: str
    lake_block_text: str
    log_line: str


def is_context_link_enabled(config: Optional[dict]) -> bool:
    return bool((config or {}).get("context_link_short_term_enabled", False))


def memory_id_for_entry(entry: dict) -> str:
    return f"{entry.get('date', '')}-{entry.get('timestamp', '')}-{entry.get('topic', '')}"


def format_session_window(agent, n: int) -> str:
    convs = getattr(agent, "session_conversations", []) or []
    if not convs:
        return ""
    parts = ["【本场最近对话】"]
    for conv in convs[-max(1, n) :]:
        ts = conv.get("timestamp", "")
        parts.append(f"【{ts}】{conv.get('full_text', '')}")
    return "\n".join(parts)


def _truncate(text: str, max_chars: int) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _format_memory_line(entry: dict, max_chars: int, prefix: str = "") -> str:
    topic = entry.get("topic", "未知主题")
    date = entry.get("date", "")
    ts = entry.get("timestamp", "")
    score = entry.get("total_score", entry.get("relevance_score", 0))
    details = entry.get("conversation_details", "") or ""
    preview = _truncate(details, max_chars)
    line = f"{prefix}【{date} {ts}】[分:{float(score):.3f}] {topic}"
    if preview:
        line += f"\n  对话: {preview}"
    return line


def _short_preview_for_agent(entry: dict, max_chars: int) -> str:
    topic = (entry.get("topic") or "未知")[:60]
    date = entry.get("date", "")
    ts = entry.get("timestamp", "")
    first_line = (entry.get("conversation_details") or "").split("\n")[0]
    preview = _truncate(first_line, max_chars)
    return f"id={memory_id_for_entry(entry)} | {date} {ts} | 主题={topic} | {preview}"


def _parse_agent_json(raw: str, default: dict) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return dict(default)


def _call_llm_json(agent, model, system: str, user: str, max_tokens: int = 800) -> Optional[str]:
    from llm_router import chat_completion

    try:
        return chat_completion(
            agent.config,
            config_key="memory_score_agent_model",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.2,
            timeout=90,
            task_label="ctx_link",
        )
    except Exception as e:
        print(f"⚠️ [CTX-LINK] 智能体调用失败: {e}")
        return None


def _call_selection_agent_step1(
    agent,
    user_input: str,
    current_time: str,
    session_text: str,
    ai_pool_cap: int,
) -> dict:
    """第 1 轮：输出 AI 选取池筛选条件（不用关键词表）。"""
    model = agent.config.get("memory_score_agent_model", "deepseek-v4-flash")
    system = (
        "你是「向量选取及分数修改智能体」第 1 步，只输出 JSON，不要 markdown。"
        "根据用户输入与本场最近对话，设定从识底深湖筛选主题的「AI 选取池」条件。"
        "禁止输出关键词列表或正则；内容相关用 content_semantic_query 写一段可供向量匹配的语义描述。"
        "示例（勿照抄）：问今天第一条→time_scope=calendar_day,sort_order=oldest_first,content_semantic_query空；"
        "问上次聊到哪→time_scope=recent,recent_topic_limit≤池上限,sort_order=newest_first；"
        "问天气但上文聊AI→time_scope=recent,content_semantic_query描述人工智能；"
        "问某景点→content_semantic_query描述该景点,time_scope=unlimited。"
        "与回忆无关（如单纯问明天天气且无上下文指代）→ skip_ai_selection=true。"
        f"recent_topic_limit 不得超过 {ai_pool_cap}。"
    )
    user = f"""当前时间：{current_time}
AI 选取池上限：{ai_pool_cap} 条

用户输入：
{user_input}

本场最近对话：
{session_text or "（无）"}

请输出 JSON：
{{
  "time_scope": "unlimited|calendar_day|recent",
  "calendar_date": "YYYY-MM-DD 或空（calendar_day 时用，默认今天）",
  "recent_topic_limit": 数字,
  "content_semantic_query": "语义描述或空",
  "sort_order": "newest_first|oldest_first|relevance",
  "skip_ai_selection": false
}}
"""
    raw = _call_llm_json(agent, model, system, user, max_tokens=500)
    if raw is None:
        print("⚠️ [CTX-LINK] 第1轮失败，跳过 AI 选取")
        return {"skip_ai_selection": True}
    plan = _parse_agent_json(raw, DEFAULT_SELECT_JSON)
    print(f"🔍 [CTX-LINK] 第1轮选取条件: {json.dumps(plan, ensure_ascii=False)[:200]}")
    return plan


def _build_ai_selection_pool(agent, select_plan: dict, ai_pool_cap: int) -> List[dict]:
    if select_plan.get("skip_ai_selection"):
        return []

    scope = (select_plan.get("time_scope") or "unlimited").lower()
    cal = (select_plan.get("calendar_date") or "").strip()
    try:
        recent_lim = int(select_plan.get("recent_topic_limit") or ai_pool_cap)
    except (TypeError, ValueError):
        recent_lim = ai_pool_cap
    recent_lim = min(max(1, recent_lim), ai_pool_cap)

    semantic_q = (select_plan.get("content_semantic_query") or "").strip()
    sort_order = (select_plan.get("sort_order") or "newest_first").lower()

    pool = agent.memory_lake.query_topics_by_selection(
        time_scope=scope,
        calendar_date=cal,
        recent_topic_limit=recent_lim,
        content_semantic_query=semantic_q,
        sort_order=sort_order,
        max_results=ai_pool_cap,
    )
    for e in pool:
        e["memory_id"] = memory_id_for_entry(e)
        e["_from_ai_pool"] = True
    return pool


def _summaries_for_rank_agent(pool: List[dict], preview_chars: int) -> str:
    lines = []
    for i, m in enumerate(pool, 1):
        lines.append(f"{i}. {_short_preview_for_agent(m, preview_chars)}")
    return "\n".join(lines) if lines else "（无）"


def _call_rank_agent_step2(
    agent,
    user_input: str,
    current_time: str,
    session_text: str,
    pool: List[dict],
    link_slots: int,
    preview_chars: int,
) -> dict:
    """第 2 轮：对 AI 选取池加减分（仅短预览）。"""
    model = agent.config.get("memory_score_agent_model", "deepseek-v4-flash")
    summary = _summaries_for_rank_agent(pool, preview_chars)
    system = (
        "你是「向量选取及分数修改智能体」第 2 步，只输出 JSON。"
        f"用户需要从 AI 选取池中最终保留 {link_slots} 条进入上下文联系。"
        "根据用户要求对下列主题的 memory_id 加减分（boosts.delta 建议 0.1~1.5）。"
        "可设 scoring.time_direction 为 newer_higher 或 older_higher 与 time_boost_cap（0~1.5）。"
        "禁止编造 id；id 必须来自下列列表。"
    )
    user = f"""当前时间：{current_time}

用户输入：
{user_input}

本场最近对话：
{session_text or "（无）"}

AI 选取池（id | 时间 | 主题 | 短预览）：
{summary}

请输出 JSON：
{{
  "boosts": [{{"memory_id": "...", "delta": 0.0}}],
  "scoring": {{
    "time_direction": "none|newer_higher|older_higher",
    "time_boost_cap": 0.0
  }}
}}
"""
    raw = _call_llm_json(agent, model, system, user, max_tokens=1200)
    if raw is None:
        return dict(DEFAULT_RANK_JSON)
    plan = _parse_agent_json(raw, DEFAULT_RANK_JSON)
    print(f"🔍 [CTX-LINK] 第2轮加减分: boosts={len(plan.get('boosts') or [])}")
    return plan


def _timestamp_to_datetime(entry: dict, now: datetime.datetime) -> datetime.datetime:
    date_s = entry.get("date") or now.strftime("%Y-%m-%d")
    ts_s = entry.get("timestamp") or "00:00:00"
    try:
        return datetime.datetime.strptime(f"{date_s} {ts_s}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            return datetime.datetime.strptime(date_s, "%Y-%m-%d")
        except ValueError:
            return now


def _apply_rank_scores(pool: List[dict], rank_plan: dict, now: datetime.datetime) -> List[dict]:
    boost_map = {}
    for b in rank_plan.get("boosts") or []:
        if isinstance(b, dict) and b.get("memory_id"):
            try:
                boost_map[b["memory_id"]] = float(b.get("delta", 0))
            except (TypeError, ValueError):
                pass

    scoring = rank_plan.get("scoring") or {}
    time_dir = (scoring.get("time_direction") or "none").lower()
    time_cap = float(scoring.get("time_boost_cap", 0.0) or 0.0)
    hours_span = 24.0
    ts_scores = [ _get_timestamp_score_safe(e) for e in pool ]
    t_min = min(ts_scores) if ts_scores else 0
    t_max = max(ts_scores) if ts_scores else 1
    span = max(1.0, t_max - t_min)

    for entry in pool:
        base = float(entry.get("relevance_score", 0.25))
        mid = memory_id_for_entry(entry)
        adj = boost_map.get(mid, 0.0)
        if time_dir in ("newer_higher", "older_higher") and time_cap > 0:
            ts = _get_timestamp_score_safe(entry)
            frac = (ts - t_min) / span
            if time_dir == "newer_higher":
                adj += time_cap * frac
            else:
                adj += time_cap * (1.0 - frac)
        entry["total_score"] = base + adj

    pool.sort(key=lambda x: -x.get("total_score", 0))
    return pool


def _get_timestamp_score_safe(entry: dict) -> float:
    date_s = entry.get("date", "")
    ts_s = entry.get("timestamp", "00:00:00")
    try:
        dt = datetime.datetime.strptime(f"{date_s} {ts_s}", "%Y-%m-%d %H:%M:%S")
        return dt.timestamp()
    except ValueError:
        return 0.0


def _pick_link_entries(ai_pool: List[dict], link_slots: int) -> List[dict]:
    if not ai_pool:
        return []
    if len(ai_pool) <= link_slots:
        return list(ai_pool)
    return list(ai_pool[:link_slots])


def _merge_vector_and_pick_lake(
    agent,
    user_input: str,
    vector_list: List[dict],
    link_ids: set,
    lake_cap: int,
) -> Tuple[List[dict], int]:
    """向量检索结果去重（去掉与联系块重复的，重复时保留联系块）后取深湖条数，不足则弱相关补全。"""
    lake_candidates: List[dict] = []
    seen = set(link_ids)

    for e in vector_list:
        mid = memory_id_for_entry(e)
        if mid in seen:
            continue
        seen.add(mid)
        cpy = e.copy()
        cpy["memory_id"] = mid
        cpy["total_score"] = float(cpy.get("relevance_score", 0))
        lake_candidates.append(cpy)

    lake_candidates.sort(key=lambda x: -x.get("total_score", 0))
    lake_entries = lake_candidates[:lake_cap]

    weak_fill_count = 0
    if len(lake_entries) < lake_cap and hasattr(agent, "_recall_weak_recent_fill"):
        need = lake_cap - len(lake_entries)
        weak = agent._recall_weak_recent_fill(user_input, need, lake_entries)
        weak_seen = {memory_id_for_entry(x) for x in lake_entries} | link_ids
        for w in weak:
            mid = memory_id_for_entry(w)
            if mid not in weak_seen:
                weak_seen.add(mid)
                w["total_score"] = w.get("relevance_score", 0.08)
                lake_entries.append(w)
                weak_fill_count += 1
            if len(lake_entries) >= lake_cap:
                break

    return lake_entries, weak_fill_count


def build_context_link_memory_bundle(agent, user_input: str, current_time: str) -> ContextLinkBundle:
    cfg = agent.config
    n = int(cfg.get("session_context_rounds", 15))
    link_slots = int(cfg.get("context_link_agent_slots", cfg.get("memory_recall_final_k", 15)))
    lake_cap = int(cfg.get("max_memory_recall", 12))
    ai_pool_cap = int(cfg.get("memory_recall_ai_pool_cap", 60))
    vector_pool = int(cfg.get("memory_recall_candidate_pool", 25))
    snippet_max = int(cfg.get("context_link_snippet_max_chars", 400))
    preview_chars = int(cfg.get("context_link_agent_preview_chars", 100))

    session_text = format_session_window(agent, n)

    # --- AI 选取通路 ---
    select_plan = _call_selection_agent_step1(
        agent, user_input, current_time, session_text, ai_pool_cap
    )
    ai_pool = _build_ai_selection_pool(agent, select_plan, ai_pool_cap)

    if len(ai_pool) > link_slots:
        rank_plan = _call_rank_agent_step2(
            agent,
            user_input,
            current_time,
            session_text,
            ai_pool,
            link_slots,
            preview_chars,
        )
        ai_pool = _apply_rank_scores(ai_pool, rank_plan, datetime.datetime.now())

    link_entries = _pick_link_entries(ai_pool, link_slots)
    link_ids = {memory_id_for_entry(e) for e in link_entries}

    # --- 识底深湖向量通路 ---
    vector_list = agent.memory_lake.search_relevant_memories(
        user_input, max_results=vector_pool
    )
    for entry in vector_list:
        entry["memory_id"] = memory_id_for_entry(entry)

    lake_entries, weak_fill_count = _merge_vector_and_pick_lake(
        agent, user_input, vector_list, link_ids, lake_cap
    )

    link_parts = []
    if link_entries:
        link_parts.append("【上下文联系补全】")
        for e in link_entries:
            link_parts.append(_format_memory_line(e, snippet_max, prefix="[联系] "))

    lake_parts = []
    if lake_entries:
        lake_parts.append("【识底深湖回忆】")
        for e in lake_entries:
            lake_parts.append(_format_memory_line(e, snippet_max))

    log_line = (
        f"[CTX-LINK v2] N={n} ai_pool={len(ai_pool)} link_cap={link_slots} "
        f"final_link={len(link_entries)} vector_pool={vector_pool} lake_cap={lake_cap} "
        f"final_lake={len(lake_entries)} weak_fill={weak_fill_count}"
    )
    print(log_line)

    return ContextLinkBundle(
        session_window_text=session_text,
        link_block_text="\n".join(link_parts),
        lake_block_text="\n".join(lake_parts),
        log_line=log_line,
    )
