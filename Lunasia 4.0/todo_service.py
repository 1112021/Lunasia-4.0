#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
待办与通讯编排服务
"""

import datetime
import json
import os
import re
from typing import Any, Callable, Dict, List, Optional

from comm_agent import CommAgent
from todo_datetime_parser import parse_create_schedule_llm_first
from todo_intent_agent import TodoIntentAgent
from todo_scheduler import TodoScheduler
from todo_store import TodoStore


def _slug(text: str) -> str:
    x = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5]+", "_", text or "").strip("_")
    return x[:24] if x else "task"


def _extract_event_title(user_input: str) -> str:
    text = user_input or ""
    text = re.sub(r"提醒我|设置提醒|创建提醒|提前\s*\d+\s*(分钟|分|小时|时)|发到\S+@\S+|给我提醒", "", text)
    # 去除“X分钟/小时/天后”这类相对时间短语，避免主题里出现二次时间语义
    text = re.sub(r"\d+\s*(分钟|分|小时|时|天)\s*后", "", text)
    text = re.sub(r"(in|after)\s*\d+\s*(minutes?|mins?|hours?|hrs?|days?)", "", text, flags=re.I)
    text = re.sub(r"今天|明天|后天|上午|下午|晚上|\d{1,2}[:：点]\d{0,2}分?", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ，。,.")
    return text or "待办事项"


class TodoService:
    """待办/通讯能力编排。"""

    def __init__(
        self,
        config: Dict[str, Any],
        llm_client_getter: Callable[[Optional[str]], Any],
        memory_event_callback: Callable[..., None],
    ):
        self.config = config
        self.llm_client_getter = llm_client_getter
        self.intent_agent = TodoIntentAgent(llm_client_getter, self.config)
        db_path = self.config.get("todo_db_path", os.path.join(os.getcwd(), "todo_tasks.db"))
        self.store = TodoStore(db_path)
        poll = int(self.config.get("todo_poll_interval_seconds", 2))
        self.scheduler = TodoScheduler(self._on_timer_trigger, poll_interval_seconds=poll)
        self.comm_agent = CommAgent(self.config, llm_client_getter)
        self.memory_event_callback = memory_event_callback
        self.pending_confirmation: Optional[Dict[str, Any]] = None

        recovered = self.store.recover_interrupted_sending()
        if recovered:
            print(f"🔁 [Todo] 已恢复 {recovered} 个发送中断的提醒任务")

        # 启动时恢复调度
        for task in self.store.list_scheduled():
            self.scheduler.schedule(task["task_id"], task["trigger_time"])

        # 启动时做一轮保留期清理
        retention = int(self.config.get("todo_retention_days", 7))
        self.store.cleanup_expired(retention)

    def shutdown_scheduler(self):
        """彻底退出应用前停止待办轮询线程。"""
        try:
            if getattr(self, "scheduler", None):
                self.scheduler.stop()
        except Exception:
            pass
        try:
            if getattr(self, "store", None):
                self.store.close()
        except Exception:
            pass

    def handle_user_input(self, user_input: str) -> Optional[str]:
        # 处理二次确认
        if self.pending_confirmation:
            return self._handle_confirmation(user_input)

        result = self.intent_agent.detect(user_input)
        intent = result.get("intent", "none")
        slots = result.get("slots", {})

        if intent == "unavailable":
            return "待办意图识别服务暂不可用，请稍后重试或明确描述“创建/修改/取消提醒 + 时间”。"
        if intent == "none":
            return None
        if intent == "cleanup":
            return self._handle_cleanup(slots)
        if intent == "create":
            return self._handle_create(user_input, slots)
        if intent == "modify":
            return self._handle_modify(user_input, slots)
        if intent == "cancel":
            return self._handle_cancel(user_input, slots)
        return None

    def _resolve_timezone(self) -> str:
        return self.config.get("todo_timezone", "") or str(datetime.datetime.now().astimezone().tzinfo or "UTC")

    def _resolve_recipient(self, override_email: str) -> str:
        if override_email:
            return override_email
        return self.config.get("todo_default_email", "").strip()

    def _make_task_id(self, event_title: str) -> str:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"task_{ts}_{_slug(event_title)}"

    def _build_template(self, event_title: str, lead_minutes: int) -> str:
        if lead_minutes >= 60:
            hours = lead_minutes / 60.0
            x = f"{hours:g}小时"
        else:
            x = f"{lead_minutes}分钟"
        return f"【提醒】{x}后：{event_title}"

    def _task_to_summary_line(self, idx: int, task: Dict[str, Any]) -> str:
        return (
            f"{idx}. [{task['task_id']}] {task['event_title']} | 会议:{task['meeting_time']} | "
            f"触发:{task['trigger_time']} | 收件人:{task['recipient_email']}"
        )

    def _ai_select_task_from_scheduled(
        self, action: str, user_input: str, candidates: List[Dict[str, Any]], slots: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        纯 AI 任务选择：仅在 scheduled 候选中决策 selected_task_id。
        规则层只做最终校验，不参与“选谁”。
        """
        model = (
            self.config.get("todo_time_parse_model", "")
            or self.config.get("search_intent_model", "")
            or self.config.get("selected_model", "")
            or None
        )
        result = self.llm_client_getter(model)
        if not result:
            return {"ok": False, "error": "llm_unavailable"}
        client, model = result

        compact_candidates = []
        for t in candidates:
            compact_candidates.append(
                {
                    "task_id": t.get("task_id", ""),
                    "event_title": t.get("event_title", ""),
                    "trigger_time": t.get("trigger_time", ""),
                    "meeting_time": t.get("meeting_time", ""),
                    "recipient_email": t.get("recipient_email", ""),
                }
            )

        action_desc = "modify(修改提醒)" if action == "modify" else "cancel(取消提醒)"
        new_event_hint = (slots.get("new_event") or "").strip()
        user_prompt = (
            "你是待办任务选择器。请在给定候选（均为 scheduled）中，选出最可能被用户提及的任务。\n"
            f"用户原话：{user_input}\n"
            f"动作：{action_desc}\n"
            f"用户已提供的新事件（可能为空）：{new_event_hint}\n\n"
            f"候选任务JSON：{json.dumps(compact_candidates, ensure_ascii=False)}\n\n"
            "只输出JSON，不要解释，不要代码块。格式：\n"
            "{\n"
            '  "selected_task_id": "必须是候选中的task_id，若无法判断则空字符串",\n'
            '  "confidence": 0到1之间的小数,\n'
            '  "new_event": "仅 modify 时填写；若用户已明确新事件，尽量提取；否则空字符串",\n'
            '  "reason": "一句简短理由"\n'
            "}"
        )
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是任务选择器，只输出合法JSON。"},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=320,
                temperature=0.0,
                timeout=20,
            )
            text = (resp.choices[0].message.content or "").strip()
            if "```json" in text:
                text = text.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in text:
                text = text.split("```", 1)[1].split("```", 1)[0].strip()
            data = json.loads(text)
            selected_task_id = str(data.get("selected_task_id", "") or "").strip()
            confidence = float(data.get("confidence", 0.0) or 0.0)
            confidence = max(0.0, min(1.0, confidence))
            new_event = str(data.get("new_event", "") or "").strip()
            reason = str(data.get("reason", "") or "").strip()
            return {
                "ok": True,
                "selected_task_id": selected_task_id,
                "confidence": confidence,
                "new_event": new_event,
                "reason": reason,
                "model": model,
            }
        except Exception as e:
            return {"ok": False, "error": f"llm_exception:{e}"}

    @staticmethod
    def _extract_modify_old_hint(user_input: str) -> str:
        """
        从“把A改为B / 将A改成B”这类句子中提取旧任务提示词 A。
        仅用于 modify 关键字兜底，避免 LLM target_keyword 偶发偏移导致无法命中。
        """
        text = (user_input or "").strip()
        patterns = [
            r"(?:把|将)\s*(.+?)\s*(?:改为|改成|改)\s*.+",
            r"(.+?)\s*(?:改为|改成|改)\s*.+",
        ]
        for p in patterns:
            m = re.match(p, text)
            if not m:
                continue
            hint = (m.group(1) or "").strip(" ，。,.“”\"'`")
            # 去掉提醒口头词，保留核心事件短语
            hint = re.sub(r"^(?:提醒我|提醒|把|将)\s*", "", hint).strip()
            if hint:
                return hint
        return ""

    def _handle_create(self, user_input: str, slots: Dict[str, Any]) -> str:
        timezone_name = self._resolve_timezone()
        default_lead = int(self.config.get("todo_default_lead_minutes", 10))
        min_trigger_seconds = int(self.config.get("todo_min_trigger_seconds", 30))
        parse_model = (
            self.config.get("todo_time_parse_model", "")
            or self.config.get("search_intent_model", "")
            or self.config.get("selected_model", "")
            or None
        )
        parsed = parse_create_schedule_llm_first(
            user_input,
            timezone_name=timezone_name,
            default_lead_minutes=default_lead,
            min_trigger_seconds=min_trigger_seconds,
            llm_client_getter=self.llm_client_getter,
            model=parse_model,
        )
        if not parsed["ok"]:
            return parsed["clarification"]

        recipient_override = slots.get("recipient_override", "")
        recipient = self._resolve_recipient(recipient_override)
        if not recipient:
            return "未配置默认收件邮箱，且本次也没有指定邮箱。请先在设置中配置默认邮箱或在指令中写“发到xxx@xx.com”。"

        event_title = _extract_event_title(user_input)
        task_id = self._make_task_id(event_title)
        lead_minutes = int(parsed["lead_minutes"])
        template = self._build_template(event_title, lead_minutes)
        retention = int(self.config.get("todo_retention_days", 7))
        max_retries = int(self.config.get("todo_retry_max", 3))
        recipient_source = "one_time_override" if recipient_override else "profile"

        task = {
            "task_id": task_id,
            "user_id": "default",
            "event_title": event_title,
            "meeting_time": parsed["meeting_time"].isoformat(timespec="seconds"),
            "trigger_time": parsed["trigger_time"].isoformat(timespec="seconds"),
            "timezone": parsed["timezone"],
            "recipient_email": recipient,
            "recipient_source": recipient_source,
            "email_template": template,
            "status": "scheduled",
            "retry_count": 0,
            "max_retries": max_retries,
            "last_error": "",
            "retain_days_snapshot": retention,
            "meta_json": json.dumps(
                {
                    "lead_minutes": lead_minutes,
                    "intent_time_type": parsed.get("intent_time_type", "unknown"),
                    "delta_minutes": int(parsed.get("delta_minutes", 0) or 0),
                },
                ensure_ascii=False,
            ),
            "lead_minutes": lead_minutes,
            "intent_time_type": parsed.get("intent_time_type", "unknown"),
            "delta_minutes": int(parsed.get("delta_minutes", 0) or 0),
        }
        self.store.create_task(task)
        self.store.add_op_log(task_id, "create", f"创建提醒: {event_title}")
        self.scheduler.schedule(task_id, task["trigger_time"])
        print(
            f"📝 [Todo] 创建任务成功: {task_id} | event={event_title} | trigger={task['trigger_time']} | to={recipient}"
        )
        print(f"🧭 [Todo] 时间解析来源: {parsed.get('parse_source', 'unknown')}")
        self.memory_event_callback("create", task, "创建提醒任务")

        return (
            f"✅ 已设置【{event_title}】提醒（任务ID: {task_id}）\n"
            f"📧 将于 {parsed['trigger_time'].strftime('%Y-%m-%d %H:%M')} 发送邮件至 {recipient}"
        )

    def _handle_modify(self, user_input: str, slots: Dict[str, Any]) -> str:
        scheduled = self.store.list_scheduled()
        if not scheduled:
            return "未找到可修改的待办任务（仅会匹配状态为 scheduled 的任务）。"

        decision = self._ai_select_task_from_scheduled("modify", user_input, scheduled, slots)
        threshold = float(self.config.get("todo_ai_match_threshold", 0.65))
        selected = None
        confidence = 0.0
        reason = ""
        if decision.get("ok"):
            selected_task_id = str(decision.get("selected_task_id", "") or "").strip()
            confidence = float(decision.get("confidence", 0.0) or 0.0)
            reason = str(decision.get("reason", "") or "").strip()
            if selected_task_id:
                for t in scheduled:
                    if t.get("task_id") == selected_task_id:
                        selected = t
                        break
            # AI补全的新事件可作为槽位补充
            ai_new_event = str(decision.get("new_event", "") or "").strip()
            if ai_new_event and not (slots.get("new_event") or "").strip():
                slots = {**slots, "new_event": ai_new_event}
            print(
                f"🧠 [TodoAI] modify 选择结果: selected={selected_task_id or '-'} | "
                f"confidence={confidence:.2f} | threshold={threshold:.2f} | reason={reason}"
            )
            if selected and confidence >= threshold:
                return self._execute_modify_with_task(user_input, slots, selected)

        # 低置信度或无法选择时，进入人工确认
        matched = scheduled
        if len(matched) > 1:
            self.pending_confirmation = {
                "action": "modify",
                "candidates": matched,
                "original_input": user_input,
                "slots": slots,
            }
            lines = ["我找到了多个候选任务，请回复序号或 task_id 确认要修改哪一条："]
            if decision.get("ok"):
                lines.append(
                    f"（AI 当前置信度 {confidence:.2f}，低于阈值 {threshold:.2f}，已转人工确认）"
                )
            for i, task in enumerate(matched, 1):
                lines.append(self._task_to_summary_line(i, task))
            return "\n".join(lines)
        # 仅一条时直接执行（此时 AI 不可用或未给出有效结果）
        return self._execute_modify_with_task(user_input, slots, matched[0])

    def _execute_modify_with_task(self, user_input: str, slots: Dict[str, Any], old_task: Dict[str, Any]) -> str:
        timezone_name = self._resolve_timezone()
        default_lead = int(self.config.get("todo_default_lead_minutes", 10))
        min_trigger_seconds = int(self.config.get("todo_min_trigger_seconds", 30))
        parse_model = (
            self.config.get("todo_time_parse_model", "")
            or self.config.get("search_intent_model", "")
            or self.config.get("selected_model", "")
            or None
        )
        parsed = parse_create_schedule_llm_first(
            user_input,
            timezone_name=timezone_name,
            default_lead_minutes=default_lead,
            min_trigger_seconds=min_trigger_seconds,
            llm_client_getter=self.llm_client_getter,
            model=parse_model,
        )
        if not parsed["ok"]:
            return parsed["clarification"]

        new_event = slots.get("new_event") or _extract_event_title(user_input)
        recipient_override = slots.get("recipient_override", "")
        recipient = recipient_override or old_task["recipient_email"]
        recipient_source = "one_time_override" if recipient_override else old_task.get("recipient_source", "profile")
        lead_minutes = int(parsed["lead_minutes"])
        task_id = self._make_task_id(new_event)
        retention = int(self.config.get("todo_retention_days", 7))
        max_retries = int(self.config.get("todo_retry_max", 3))
        new_task = {
            "task_id": task_id,
            "user_id": "default",
            "event_title": new_event,
            "meeting_time": parsed["meeting_time"].isoformat(timespec="seconds"),
            "trigger_time": parsed["trigger_time"].isoformat(timespec="seconds"),
            "timezone": parsed["timezone"],
            "recipient_email": recipient,
            "recipient_source": recipient_source,
            "email_template": self._build_template(new_event, lead_minutes),
            "status": "scheduled",
            "retry_count": 0,
            "max_retries": max_retries,
            "last_error": "",
            "retain_days_snapshot": retention,
            "meta_json": json.dumps(
                {
                    "lead_minutes": lead_minutes,
                    "intent_time_type": parsed.get("intent_time_type", "unknown"),
                    "delta_minutes": int(parsed.get("delta_minutes", 0) or 0),
                },
                ensure_ascii=False,
            ),
            "lead_minutes": lead_minutes,
            "intent_time_type": parsed.get("intent_time_type", "unknown"),
            "delta_minutes": int(parsed.get("delta_minutes", 0) or 0),
        }

        ok, err = self.store.replace_task_atomic(old_task["task_id"], new_task)
        if not ok:
            return f"修改失败：{err}"

        self.scheduler.unschedule(old_task["task_id"])
        self.scheduler.schedule(task_id, new_task["trigger_time"])
        print(
            f"📝 [Todo] 修改任务成功: old={old_task['task_id']} -> new={task_id} | trigger={new_task['trigger_time']}"
        )
        print(f"🧭 [Todo] 时间解析来源: {parsed.get('parse_source', 'unknown')}")
        self.store.add_op_log(old_task["task_id"], "modify_old_cancel", "修改时取消旧任务")
        self.store.add_op_log(task_id, "modify_new_create", "修改时创建新任务")
        self.memory_event_callback(
            "modify", new_task, f"替换旧任务 {old_task['task_id']}", old_task["task_id"]
        )
        return (
            f"✅ 已将【{old_task['event_title']}】提醒替换为【{new_event}】提醒\n"
            f"📧 新提醒（任务ID: {task_id}）将于 {parsed['trigger_time'].strftime('%Y-%m-%d %H:%M')} 发送至 {recipient}"
        )

    def _handle_cancel(self, user_input: str, slots: Dict[str, Any]) -> str:
        scheduled = self.store.list_scheduled()
        if not scheduled:
            return "未找到可取消的待办任务（仅会匹配状态为 scheduled 的任务）。"

        decision = self._ai_select_task_from_scheduled("cancel", user_input, scheduled, slots)
        threshold = float(self.config.get("todo_ai_match_threshold", 0.65))
        selected = None
        confidence = 0.0
        reason = ""
        if decision.get("ok"):
            selected_task_id = str(decision.get("selected_task_id", "") or "").strip()
            confidence = float(decision.get("confidence", 0.0) or 0.0)
            reason = str(decision.get("reason", "") or "").strip()
            if selected_task_id:
                for t in scheduled:
                    if t.get("task_id") == selected_task_id:
                        selected = t
                        break
            print(
                f"🧠 [TodoAI] cancel 选择结果: selected={selected_task_id or '-'} | "
                f"confidence={confidence:.2f} | threshold={threshold:.2f} | reason={reason}"
            )
            if selected and confidence >= threshold:
                ok = self.store.cancel_task(selected["task_id"])
                if not ok:
                    return "任务取消失败：该任务可能已被触发或已取消。"
                self.scheduler.unschedule(selected["task_id"])
                print(f"📝 [Todo] 取消任务成功: {selected['task_id']}")
                self.store.add_op_log(selected["task_id"], "cancel", "用户取消任务")
                self.memory_event_callback("cancel", selected, "取消提醒任务")
                return f"✅ 已取消【{selected['event_title']}】提醒（任务ID: {selected['task_id']}）"

        matched = scheduled
        if len(matched) > 1:
            self.pending_confirmation = {
                "action": "cancel",
                "candidates": matched,
                "original_input": user_input,
                "slots": slots,
            }
            lines = ["我找到了多个候选任务，请回复序号或 task_id 确认要取消哪一条："]
            if decision.get("ok"):
                lines.append(
                    f"（AI 当前置信度 {confidence:.2f}，低于阈值 {threshold:.2f}，已转人工确认）"
                )
            for i, task in enumerate(matched, 1):
                lines.append(self._task_to_summary_line(i, task))
            return "\n".join(lines)

        task = matched[0]
        ok = self.store.cancel_task(task["task_id"])
        if not ok:
            return "任务取消失败：该任务可能已被触发或已取消。"
        self.scheduler.unschedule(task["task_id"])
        print(f"📝 [Todo] 取消任务成功: {task['task_id']}")
        self.store.add_op_log(task["task_id"], "cancel", "用户取消任务")
        self.memory_event_callback("cancel", task, "取消提醒任务")
        return f"✅ 已取消【{task['event_title']}】提醒（任务ID: {task['task_id']}）"

    def _handle_cleanup(self, slots: Dict[str, Any]) -> str:
        mode = slots.get("cleanup_mode", "all")
        retention = int(self.config.get("todo_retention_days", 7))
        deleted = self.store.manual_cleanup(mode, retention)
        mode_desc = {"all": "过期已完成任务", "failed": "失败任务", "sent": "已发送任务", "cancelled": "已取消任务"}.get(mode, mode)
        return f"✅ 已清理 {deleted} 条{mode_desc}。"

    def _handle_confirmation(self, user_input: str) -> str:
        if not self.pending_confirmation:
            return None
        text = (user_input or "").strip()
        if text.lower() in ("取消", "cancel", "算了"):
            self.pending_confirmation = None
            return "已取消本次待办确认操作。"

        data = self.pending_confirmation
        candidates = data["candidates"]
        selected = None
        if text.isdigit():
            idx = int(text)
            if 1 <= idx <= len(candidates):
                selected = candidates[idx - 1]
        else:
            for task in candidates:
                if task["task_id"] == text:
                    selected = task
                    break

        if not selected:
            lines = ["未识别到有效选择，请回复序号或 task_id："]
            for i, task in enumerate(candidates, 1):
                lines.append(self._task_to_summary_line(i, task))
            return "\n".join(lines)

        self.pending_confirmation = None
        if data["action"] == "cancel":
            ok = self.store.cancel_task(selected["task_id"])
            if not ok:
                return "任务取消失败：该任务可能已被触发或已取消。"
            self.scheduler.unschedule(selected["task_id"])
            print(f"📝 [Todo] 二次确认后取消任务: {selected['task_id']}")
            self.store.add_op_log(selected["task_id"], "cancel", "用户二次确认后取消任务")
            self.memory_event_callback("cancel", selected, "二次确认后取消提醒任务")
            return f"✅ 已取消【{selected['event_title']}】提醒（任务ID: {selected['task_id']}）"

        if data["action"] == "modify":
            return self._execute_modify_with_task(data["original_input"], data["slots"], selected)

        return "未识别的确认操作。"

    def _on_timer_trigger(self, task_id: str) -> None:
        """
        定时触发入口：
        - 幂等检查 scheduled->sending
        - 发送成功标 sent
        - 失败按 30/120/300 秒重试，超限标 failed
        """
        task = self.store.get_task(task_id)
        if not task:
            print(f"⚠️ [Todo] 触发任务不存在: {task_id}")
            return
        if not self.store.try_mark_sending(task_id):
            print(f"ℹ️ [Todo] 跳过触发（非scheduled或已被处理）: {task_id}")
            return

        task = self.store.get_task(task_id) or task
        meta = {}
        try:
            meta = json.loads(task.get("meta_json", "") or "{}")
        except Exception:
            meta = {}
        lead_match = re.search(r'"lead_minutes"\s*:\s*(\d+)', task.get("meta_json", ""))
        task["lead_minutes"] = int(meta.get("lead_minutes", lead_match.group(1) if lead_match else 10))
        task["intent_time_type"] = str(meta.get("intent_time_type", task.get("intent_time_type", "unknown")))
        task["delta_minutes"] = int(meta.get("delta_minutes", task.get("delta_minutes", 0)) or 0)
        print(
            f"📨 [Todo] 开始发送提醒邮件: {task_id} | event={task.get('event_title', '')} | to={task.get('recipient_email', '')}"
        )

        try:
            ok, msg = self.comm_agent.send_task_email(task)
        except Exception as e:
            ok, msg = False, f"邮件发送线程异常: {e}"
            print(f"❌ [Todo] 邮件发送线程异常，转入重试: {task_id} | error={e}")
        if ok:
            self.store.mark_sent(task_id)
            self.store.add_op_log(task_id, "send_success", "定时发送成功")
            print(f"✅ [Todo] 邮件发送成功: {task_id}")
            self.memory_event_callback("send_success", task, "提醒邮件发送成功")
            return

        # 失败重试
        retries = [30, 120, 300]
        current_retry = int(task.get("retry_count", 0))
        delay = retries[min(current_retry, len(retries) - 1)]
        updated = self.store.requeue_with_retry(task_id, msg, delay)
        if not updated:
            print(f"⚠️ [Todo] 重试排队失败（任务不存在）: {task_id}")
            return
        if updated["status"] == "failed":
            self.store.add_op_log(task_id, "send_failed", msg)
            print(f"❌ [Todo] 邮件发送失败且达到重试上限: {task_id} | error={msg}")
            self.memory_event_callback("send_failed", updated, msg)
            return
        self.store.add_op_log(task_id, "retry", f"{msg}，将在{delay}秒后重试")
        self.scheduler.schedule(task_id, updated["trigger_time"])
        print(f"🔁 [Todo] 邮件发送失败，{delay}秒后重试: {task_id} | error={msg}")

