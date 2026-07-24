#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
通讯 Agent
负责根据任务生成邮件正文并通过 SMTP 发送。
"""

import datetime
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any, Callable, Dict, Optional, Tuple


class CommAgent:
    """邮件通讯能力封装。"""

    def __init__(self, config: Dict[str, Any], llm_client_getter: Callable[[Optional[str]], Any]):
        self.config = config
        self.llm_client_getter = llm_client_getter

    @staticmethod
    def _pretty_time(value: str) -> str:
        """将 ISO 时间转为更友好的展示格式。"""
        try:
            dt = datetime.datetime.fromisoformat(value)
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return value

    def _resolve_email_body_model(self) -> str:
        """
        邮件正文统一使用对话类模型（简短/生动均如此）。
        推理模型常出现 content 空或输出推理过程，不适合直接作邮件正文。
        """
        m = self.config.get("todo_email_model") or self.config.get(
            "selected_model", "deepseek-v4-flash"
        )
        if isinstance(m, dict):
            from llm_spec import normalize_spec

            spec = normalize_spec(m, self.config)
            if spec.thinking == "enabled" or "reasoner" in spec.model_id.lower():
                print(
                    f"[TodoMail] model_override: {spec.display_name()} -> "
                    "deepseek-v4-flash（非思考）"
                )
                return "deepseek-v4-flash"
            return spec.model_id
        m = str(m or "").strip()
        ml = m.lower()
        if "reasoner" in ml or "thinking" in ml:
            print(
                f"[TodoMail] model_override: {m} -> deepseek-v4-flash（邮件正文固定使用对话模型）"
            )
            return "deepseek-v4-flash"
        return m or "deepseek-v4-flash"

    def _get_email_body_client(self):
        """按 ModelSpec 配置路由邮件模型，并兼容旧位置参数回调。"""
        raw_todo_model = self.config.get("todo_email_model")
        config_key = "todo_email_model" if raw_todo_model else "selected_model"
        model = self._resolve_email_body_model()

        raw_model = raw_todo_model or self.config.get("selected_model")
        if isinstance(raw_model, dict):
            from llm_spec import normalize_spec

            spec = normalize_spec(raw_model, self.config)
            if spec.thinking == "enabled" or "reasoner" in spec.model_id.lower():
                return self.llm_client_getter(model)

        try:
            return self.llm_client_getter(config_key=config_key)
        except TypeError:
            return self.llm_client_getter(model)

    def _generate_email_body(self, task: Dict[str, Any]) -> str:
        """生成邮件正文。优先走 LLM，失败则回退模板。"""
        event = task["event_title"]
        meeting_time = task["meeting_time"]
        meeting_time_pretty = self._pretty_time(str(meeting_time))
        lead_minutes = task.get("lead_minutes", 10)
        intent_time_type = str(task.get("intent_time_type", "unknown"))
        delta_minutes = int(task.get("delta_minutes", 0) or 0)
        email_style = (self.config.get("todo_email_style", "concise") or "concise").strip().lower()
        user_prompt = (
            "请生成提醒邮件正文：\n"
            f"事件：{event}\n"
            f"事件时间：{meeting_time_pretty}\n"
            f"提前分钟：{lead_minutes}\n"
            f"时间语义：{intent_time_type}\n"
            f"相对时长分钟：{delta_minutes}\n\n"
            "只输出正文。"
        )
        concise_system_prompt = """你是提醒邮件写作助手。
硬性要求：
- 只输出正文纯文本，1句，20-45字。
- 直达信息，不要寒暄，不要建议，不要扩展，不要Markdown。
- 禁止公文套话（如“尊敬的”“祝工作顺利”）。
- 只能使用给定字段，不编造事实。
语义规则：
1) remind_after：强调“已到提醒时间”。
2) meeting_after/absolute：给出事件时间并提示处理。"""
        vivid_system_prompt = """你是露尼西亚的提醒邮件写作助手。这是写给「指挥官」的提醒邮件正文，要像你本人在轻轻拍肩膀说话，不要像系统弹窗。

硬性要求：
- 只输出正文纯文本；禁止 Markdown；禁止「尊敬的」「此致敬礼」「祝工作顺利」等公文套话。
- 事实约束：只能使用用户消息里给出的字段，不编造时间、地点、收件人或事件细节。
- 篇幅：3～5 句为宜，合计约 120～220 字（中文）；可以略活泼、略啰嗦，避免冷漠的一句话带过。

语气与人设：
- 可爱可靠、略带俏皮；称呼「指挥官」；口语自然，可轻微语气词或小调侃，不低俗、不堆网络梗。
- 先点明提醒核心（到点了 / 还剩多久），中间可有一句关心或打趣，最后给一句马上能做的小事。

反幻觉约束（最高优先级 - 必须严格遵守）：
1. 禁止编造环境细节：不要假设、想象、联想用户和自己的物理环境（桌面物品、抽屉内容、房间布局、水杯位置、温度等），除非用户明确告知
2. 禁止编造时间线
3. 禁止编造数据：不要虚构百分比、统计数据、科学实验结论、效率提升数字等
4.禁止感知实时状态：你是AI助手，不能感知用户的实时生理状态（心跳频率、水温、呼吸、脉搏等）

语义规则：
1) intent_time_type=remind_after：强调「现在已到你说好的提醒时刻」，不要写成未来时。
2) intent_time_type=meeting_after/absolute：点明事件时间，提醒收心准备。
3) 若相对时长分钟>0 且为 remind_after，可自然提到「你设的 N 分钟后铃」之类，数字须与字段一致。"""
        system_prompt = vivid_system_prompt if email_style == "vivid" else concise_system_prompt
        if email_style == "vivid":
            _mail_temperature = 0.55
            _mail_max_tokens = 420
        else:
            _mail_temperature = 0.25
            _mail_max_tokens = 220

        def _fallback_text() -> str:
            if email_style == "vivid":
                if intent_time_type == "remind_after" and delta_minutes > 0:
                    return f"指挥官，这是你设定的“{delta_minutes}分钟后提醒”，现在到点了，请处理「{event}」。"
                return f"指挥官，你在 {meeting_time_pretty} 有「{event}」，建议现在开始准备。"
            if intent_time_type == "remind_after" and delta_minutes > 0:
                return f"已到提醒时间：请处理「{event}」（你设定为{delta_minutes}分钟后提醒）。"
            return f"提醒：{meeting_time_pretty} 的「{event}」请及时处理。"

        result = self._get_email_body_client()
        if not result:
            print(f"[TodoMail] body_source=fallback | style={email_style} | reason=llm_client_unavailable")
            return _fallback_text()
        client, model = result
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=_mail_max_tokens,
                temperature=_mail_temperature,
                timeout=20,
            )
            message = resp.choices[0].message
            content = (message.content or "").strip()
            if content:
                print(f"[TodoMail] body_source=llm | style={email_style} | model={model}")
                return content
            print(f"[TodoMail] body_source=fallback | style={email_style} | reason=llm_empty_response | model={model}")
            return _fallback_text()
        except Exception as e:
            print(f"[TodoMail] body_source=fallback | style={email_style} | reason=llm_exception:{e} | model={model}")
            return _fallback_text()

    def _build_subject(self, task: Dict[str, Any]) -> str:
        event = task["event_title"]
        intent_time_type = str(task.get("intent_time_type", "unknown"))
        delta_minutes = int(task.get("delta_minutes", 0) or 0)
        if intent_time_type == "remind_after" and delta_minutes > 0:
            return f"【提醒】已到提醒时间：{event}"
        lead_minutes = int(task.get("lead_minutes", 10))
        if lead_minutes >= 60:
            hours = lead_minutes / 60.0
            x = f"{hours:g}小时"
        else:
            x = f"{lead_minutes}分钟"
        return f"【提醒】{x}后：{event}"

    def send_task_email(self, task: Dict[str, Any]) -> Tuple[bool, str]:
        """发送任务邮件。"""
        smtp_host = self.config.get("smtp_host", "smtp.qq.com")
        smtp_port = int(self.config.get("smtp_port", 465))
        smtp_user = str(self.config.get("smtp_username", "") or "").strip()
        smtp_password = str(self.config.get("smtp_password", "") or "").strip()
        recipient = str(task.get("recipient_email", "") or "").strip()

        if not smtp_user or not smtp_password:
            return False, "SMTP账号或授权码未配置"
        if not recipient:
            return False, "收件邮箱为空"

        try:
            subject = self._build_subject(task)
            body = self._generate_email_body(task)
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = subject
            msg["From"] = formataddr(("露尼西亚提醒中心", smtp_user))
            msg["To"] = recipient
            msg["Date"] = datetime.datetime.now().strftime(
                "%a, %d %b %Y %H:%M:%S +0800"
            )

            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as server:
                server.login(smtp_user, smtp_password)
                server.sendmail(smtp_user, [recipient], msg.as_string())
            return True, "发送成功"
        except Exception as e:
            return False, f"邮件发送失败: {e}"

