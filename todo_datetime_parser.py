#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
待办时间解析模块
支持中英时间表达、相对时间与智能兜底提前量。
"""

import datetime
import json
import re
from typing import Any, Callable, Dict, Optional, Tuple


def _get_local_timezone_name() -> str:
    """获取系统本地时区名称，失败时回退 UTC。"""
    try:
        tz = datetime.datetime.now().astimezone().tzinfo
        if tz is not None:
            name = str(tz)
            return name if name else "UTC"
    except Exception:
        pass
    return "UTC"


def _parse_lead_minutes(user_input: str, default_lead_minutes: int) -> int:
    """
    解析“提前X分钟/小时”。
    未指定时默认提前10分钟。
    """
    text = user_input or ""
    m = re.search(r"提前\s*(\d+)\s*(分钟|分|小时|时)", text)
    if not m:
        m = re.search(r"(\d+)\s*(minutes?|mins?|hours?|hrs?)\s*before", text, flags=re.I)
    if not m:
        return int(default_lead_minutes)
    num = int(m.group(1))
    unit = m.group(2)
    if unit in ("小时", "时") or unit.lower().startswith(("hour", "hr")):
        return num * 60
    return num


def _parse_relative_delta_minutes(text: str) -> Optional[int]:
    """
    解析 "10分钟后/in 10 minutes/after 2 hours" 等相对时长。
    返回分钟数。
    """
    # 中文：10分钟后 / 2小时后 / 1天后
    m = re.search(r"(\d+)\s*(分钟|分|小时|时|天)\s*后", text)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit in ("分钟", "分"):
            return n
        if unit in ("小时", "时"):
            return n * 60
        if unit == "天":
            return n * 24 * 60

    # 英文：in 10 minutes / after 2 hours / in 1 day
    m = re.search(r"(?:in|after)\s*(\d+)\s*(minutes?|mins?|hours?|hrs?|days?)", text, flags=re.I)
    if m:
        n = int(m.group(1))
        u = m.group(2).lower()
        if u.startswith(("minute", "min")):
            return n
        if u.startswith(("hour", "hr")):
            return n * 60
        if u.startswith("day"):
            return n * 24 * 60

    return None


def _parse_relative_weekday(text: str, now: datetime.datetime) -> Optional[datetime.datetime]:
    """解析英文 next monday 3pm / tomorrow at 10:30。"""
    t = text.lower()
    # tomorrow at 10:30
    m = re.search(r"(today|tomorrow|day after tomorrow)\s*(?:at)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if m:
        day_word = m.group(1)
        hour = int(m.group(2))
        minute = int(m.group(3) or 0)
        ampm = (m.group(4) or "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        day_offset = 0
        if day_word == "tomorrow":
            day_offset = 1
        elif day_word == "day after tomorrow":
            day_offset = 2
        target = now + datetime.timedelta(days=day_offset)
        return target.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # next monday 3pm
    m = re.search(r"next\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if m:
        wd_map = {
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6,
        }
        target_wd = wd_map[m.group(1)]
        hour = int(m.group(2))
        minute = int(m.group(3) or 0)
        ampm = (m.group(4) or "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        days_ahead = (target_wd - now.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        target = now + datetime.timedelta(days=days_ahead)
        return target.replace(hour=hour, minute=minute, second=0, microsecond=0)

    return None


def _parse_event_time(user_input: str, now: datetime.datetime) -> Optional[datetime.datetime]:
    """
    解析会议/事件发生时间。
    支持：
    - YYYY-MM-DD HH:MM
    - 今天/明天/后天 + 上午/下午/晚上 + X点(半|X分)
    - 今天/明天/后天 + HH:MM
    """
    text = user_input or ""

    # 1) 显式日期时间：2026-04-10 10:30 或 2026/04/10 10:30
    m = re.search(
        r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})\s+(\d{1,2})[:：点](\d{1,2})?",
        text,
    )
    if m:
        year = int(m.group(1))
        month = int(m.group(2))
        day = int(m.group(3))
        hour = int(m.group(4))
        minute = int(m.group(5) or 0)
        return now.replace(year=year, month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)

    # 2) 相对日期 + 时分
    day_offset = None
    if "后天" in text:
        day_offset = 2
    elif "明天" in text:
        day_offset = 1
    elif "今天" in text:
        day_offset = 0

    # “上午10点”“下午3点半”“晚上8点20”
    hm = re.search(r"(上午|中午|下午|晚上)?\s*(\d{1,2})\s*点(?:\s*(半|(\d{1,2})\s*分?))?", text)
    if hm and day_offset is not None:
        period = hm.group(1) or ""
        hour = int(hm.group(2))
        minute = 0
        if hm.group(3) == "半":
            minute = 30
        elif hm.group(4):
            minute = int(hm.group(4))

        if period in ("下午", "晚上") and hour < 12:
            hour += 12
        elif period == "中午" and hour < 11:
            hour += 12

        target_day = now + datetime.timedelta(days=day_offset)
        return target_day.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # 3) 相对日期 + HH:MM
    hm2 = re.search(r"(\d{1,2})[:：](\d{2})", text)
    if hm2 and day_offset is not None:
        hour = int(hm2.group(1))
        minute = int(hm2.group(2))
        target_day = now + datetime.timedelta(days=day_offset)
        return target_day.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # 4) 英文 today/tomorrow/next monday
    eng_dt = _parse_relative_weekday(text, now)
    if eng_dt:
        return eng_dt

    return None


def _relative_kind(text: str) -> str:
    """
    区分两类相对语义：
    - remind_after: 10分钟后提醒我开会 / remind me in 10 minutes ...
    - meeting_after: 提醒我10分钟后开会 / remind me to have meeting in 10 minutes
    """
    t = (text or "").lower()
    if re.search(r"\d+\s*(分钟|分|小时|时|天)\s*后\s*提醒", text):
        return "remind_after"
    if re.search(r"(in|after)\s*\d+\s*(minutes?|mins?|hours?|hrs?|days?)\s*remind me", t):
        return "remind_after"

    if re.search(r"提醒我\s*\d+\s*(分钟|分|小时|时|天)\s*后", text):
        return "meeting_after"
    if re.search(r"remind me.*(in|after)\s*\d+\s*(minutes?|mins?|hours?|hrs?|days?)", t):
        return "meeting_after"
    return "unknown"


def parse_create_schedule(
    user_input: str,
    timezone_name: Optional[str] = None,
    default_lead_minutes: int = 10,
    min_trigger_seconds: int = 30,
) -> Dict[str, Any]:
    """
    解析创建提醒所需时间字段。
    返回:
    {
      "ok": bool,
      "meeting_time": datetime|None,
      "trigger_time": datetime|None,
      "lead_minutes": int,
      "timezone": str,
      "clarification": str|None
    }
    """
    tz_name = timezone_name or _get_local_timezone_name()
    now = datetime.datetime.now().astimezone()

    lead_minutes = _parse_lead_minutes(user_input, default_lead_minutes=default_lead_minutes)

    # 先看是否是“相对时间”表达
    rel_minutes = _parse_relative_delta_minutes(user_input)
    rel_kind = _relative_kind(user_input)

    if rel_minutes is not None and rel_kind == "remind_after":
        trigger_time = now + datetime.timedelta(minutes=rel_minutes)
        meeting_time = trigger_time  # 该表达是“X分钟后提醒”，会议时间未知时与触发时间一致
        if (trigger_time - now).total_seconds() < min_trigger_seconds:
            return {
                "ok": False,
                "meeting_time": meeting_time,
                "trigger_time": trigger_time,
                "lead_minutes": 0,
                "timezone": tz_name,
                "clarification": f"触发时间太近了，请至少设置 {min_trigger_seconds} 秒后的提醒。",
            }
        return {
            "ok": True,
            "meeting_time": meeting_time,
            "trigger_time": trigger_time,
            "lead_minutes": 0,
            "timezone": tz_name,
            "clarification": None,
        }

    if rel_minutes is not None and rel_kind == "meeting_after":
        meeting_time = now + datetime.timedelta(minutes=rel_minutes)
    else:
        meeting_time = _parse_event_time(user_input, now)
    if meeting_time is None:
        return {
            "ok": False,
            "meeting_time": None,
            "trigger_time": None,
            "lead_minutes": lead_minutes,
            "timezone": tz_name,
            "clarification": "我还没识别出具体时间。请用类似“明天上午10点”或“2026-04-10 10:00”的格式再说一次。",
        }

    trigger_time = meeting_time - datetime.timedelta(minutes=lead_minutes)

    # 智能兜底：若触发太近，自动把提前量压到间隔的一半（>=1 分钟）
    if (trigger_time - now).total_seconds() < min_trigger_seconds:
        total_gap_minutes = max(1, int((meeting_time - now).total_seconds() // 60))
        fallback_lead = max(1, min(lead_minutes, total_gap_minutes // 2))
        trigger_time = meeting_time - datetime.timedelta(minutes=fallback_lead)
        lead_minutes = fallback_lead

    if (trigger_time - now).total_seconds() < min_trigger_seconds:
        return {
            "ok": False,
            "meeting_time": meeting_time,
            "trigger_time": trigger_time,
            "lead_minutes": lead_minutes,
            "timezone": tz_name,
            "clarification": f"提醒触发时间太近或已过期（最小触发阈值 {min_trigger_seconds} 秒）。请提供更晚的时间。",
        }

    return {
        "ok": True,
        "meeting_time": meeting_time,
        "trigger_time": trigger_time,
        "lead_minutes": lead_minutes,
        "timezone": tz_name,
        "parse_source": "fallback_rule",
        "clarification": None,
    }


def _extract_json_block(text: str) -> str:
    x = (text or "").strip()
    if "```json" in x:
        return x.split("```json", 1)[1].split("```", 1)[0].strip()
    if "```" in x:
        return x.split("```", 1)[1].split("```", 1)[0].strip()
    return x


def _finalize_schedule(
    now: datetime.datetime,
    meeting_time: datetime.datetime,
    lead_minutes: int,
    tz_name: str,
    min_trigger_seconds: int,
    intent_time_type: str = "absolute",
    delta_minutes: int = 0,
) -> Dict[str, Any]:
    trigger_time = meeting_time - datetime.timedelta(minutes=lead_minutes)
    if (trigger_time - now).total_seconds() < min_trigger_seconds:
        total_gap_minutes = max(1, int((meeting_time - now).total_seconds() // 60))
        fallback_lead = max(1, min(lead_minutes, total_gap_minutes // 2))
        trigger_time = meeting_time - datetime.timedelta(minutes=fallback_lead)
        lead_minutes = fallback_lead

    if (trigger_time - now).total_seconds() < min_trigger_seconds:
        return {
            "ok": False,
            "meeting_time": meeting_time,
            "trigger_time": trigger_time,
            "lead_minutes": lead_minutes,
            "timezone": tz_name,
            "intent_time_type": intent_time_type,
            "delta_minutes": int(delta_minutes),
            "parse_source": "llm",
            "clarification": f"提醒触发时间太近或已过期（最小触发阈值 {min_trigger_seconds} 秒）。请提供更晚的时间。",
        }

    return {
        "ok": True,
        "meeting_time": meeting_time,
        "trigger_time": trigger_time,
        "lead_minutes": lead_minutes,
        "timezone": tz_name,
        "intent_time_type": intent_time_type,
        "delta_minutes": int(delta_minutes),
        "parse_source": "llm",
        "clarification": None,
    }


def parse_create_schedule_llm_first(
    user_input: str,
    timezone_name: Optional[str],
    default_lead_minutes: int,
    min_trigger_seconds: int,
    llm_client_getter: Callable[[Optional[str]], Optional[Tuple[Any, str]]],
    model: Optional[str] = None,
    min_confidence: float = 0.7,
) -> Dict[str, Any]:
    """
    LLM 主解析 + 规则备用：
    1) 优先让 LLM 输出结构化时间结果
    2) 结果不可信或失败时回退 parse_create_schedule
    """
    tz_name = timezone_name or _get_local_timezone_name()
    now = datetime.datetime.now().astimezone()
    default_lead = int(default_lead_minutes)

    try:
        result = llm_client_getter(model)
        if not result:
            raise RuntimeError("llm unavailable")
        client, model_name = result
        prompt = f"""你是时间解析器。请把用户提醒语句解析为严格 JSON（不要Markdown）。
当前时间 now_iso: {now.isoformat(timespec="seconds")}
时区 timezone: {tz_name}
默认提前分钟 default_lead_minutes: {default_lead}

用户输入: {user_input}

返回字段（必须完整）:
{{
  "ok": true/false,
  "intent_time_type": "remind_after|meeting_after|absolute|unknown",
  "meeting_time_iso": "ISO8601，可空字符串",
  "delta_minutes": 整数，可为0,
  "lead_minutes": 整数，可为0,
  "timezone": "{tz_name}",
  "confidence": 0到1小数,
  "reason": "简短说明"
}}

语义规则:
1) “10分钟后提醒我开会” => remind_after（触发时间=now+10分钟）
2) “提醒我10分钟后开会” => meeting_after（会议时间=now+10分钟，触发=会议-lead）
3) 明确日期时间 => absolute（meeting_time_iso 必填）
4) 无法确定返回 ok=false 且 intent_time_type=unknown
"""
        resp = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "你是严格 JSON 的时间解析器。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=320,
            temperature=0.0,
            timeout=20,
        )
        raw = resp.choices[0].message.content
        data = json.loads(_extract_json_block(raw))

        if not bool(data.get("ok", False)):
            raise ValueError("llm parse not ok")
        confidence = float(data.get("confidence", 0.0) or 0.0)
        if confidence < float(min_confidence):
            raise ValueError("llm confidence too low")

        kind = (data.get("intent_time_type") or "unknown").strip().lower()
        lead_minutes = int(data.get("lead_minutes", default_lead) or default_lead)
        lead_minutes = max(0, lead_minutes)

        if kind == "remind_after":
            delta = int(data.get("delta_minutes", 0) or 0)
            if delta <= 0:
                raise ValueError("invalid delta for remind_after")
            trigger_time = now + datetime.timedelta(minutes=delta)
            meeting_time = trigger_time
            if (trigger_time - now).total_seconds() < min_trigger_seconds:
                raise ValueError("trigger too close for remind_after")
            return {
                "ok": True,
                "meeting_time": meeting_time,
                "trigger_time": trigger_time,
                "lead_minutes": 0,
                "timezone": tz_name,
                "intent_time_type": "remind_after",
                "delta_minutes": delta,
                "parse_source": "llm",
                "clarification": None,
            }

        if kind == "meeting_after":
            delta = int(data.get("delta_minutes", 0) or 0)
            if delta <= 0:
                raise ValueError("invalid delta for meeting_after")
            meeting_time = now + datetime.timedelta(minutes=delta)
            return _finalize_schedule(
                now,
                meeting_time,
                lead_minutes,
                tz_name,
                int(min_trigger_seconds),
                intent_time_type="meeting_after",
                delta_minutes=delta,
            )

        if kind == "absolute":
            meeting_time_iso = (data.get("meeting_time_iso") or "").strip()
            if not meeting_time_iso:
                raise ValueError("missing meeting_time_iso")
            meeting_time = datetime.datetime.fromisoformat(meeting_time_iso)
            if meeting_time.tzinfo is None:
                meeting_time = meeting_time.replace(tzinfo=now.tzinfo)
            return _finalize_schedule(
                now,
                meeting_time,
                lead_minutes,
                tz_name,
                int(min_trigger_seconds),
                intent_time_type="absolute",
                delta_minutes=0,
            )

        raise ValueError("unknown kind")
    except Exception:
        fallback = parse_create_schedule(
            user_input,
            timezone_name=tz_name,
            default_lead_minutes=default_lead,
            min_trigger_seconds=int(min_trigger_seconds),
        )
        fallback["intent_time_type"] = "unknown"
        fallback["delta_minutes"] = 0
        fallback["parse_source"] = "fallback_rule"
        return fallback

