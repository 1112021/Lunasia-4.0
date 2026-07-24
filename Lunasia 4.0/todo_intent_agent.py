#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
待办意图识别模块（纯 LLM 版）
"""

import json
from typing import Any, Callable, Dict, Optional, Tuple


class TodoIntentAgent:
    """待办意图识别（严格无关键词后备）。"""

    def __init__(
        self,
        llm_client_getter: Callable[[Optional[str]], Optional[Tuple[Any, str]]],
        config: Dict[str, Any],
    ):
        self.llm_client_getter = llm_client_getter
        self.config = config

    def detect(self, user_input: str) -> Dict[str, Any]:
        model = (self.config.get("search_intent_model", "") or "").strip() or None
        result = self.llm_client_getter(model)
        if not result:
            return {
                "intent": "unavailable",
                "slots": {},
                "error": "待办意图识别服务暂不可用（LLM不可用）",
            }
        client, model = result

        prompt = f"""请识别用户是否属于“待办提醒/邮件通讯”相关意图。
用户输入：{user_input}

输出要求：只返回 JSON，不要其他文本。
字段：
{{
  "intent": "create|modify|cancel|cleanup|none",
  "recipient_override": "可选，用户本次指定的收件邮箱，没有就空字符串",
  "target_keyword": "可选，修改/取消时用于匹配旧任务的关键描述",
  "new_event": "可选，修改时的新事件描述",
  "cleanup_mode": "all|sent|cancelled|failed（仅 cleanup 有效）"
}}

规则：
1) 严格只做意图分类，不要杜撰时间。
2) “10分钟后提醒我开会”属于 create。
3) “提醒我10分钟后开会”属于 create。
4) “把10点会议改成陪客户”属于 modify。
5) “取消10点会议提醒”属于 cancel。
6) “清理提醒/清理失败提醒/清理已发送提醒/清理已取消提醒”属于 cleanup。
7) 与待办提醒无关（如天气、闲聊、代码问题）返回 none。
"""
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是待办意图识别助手，只输出JSON。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=220,
                temperature=0.0,
                timeout=20,
            )
            text = resp.choices[0].message.content.strip()
            if "```json" in text:
                text = text.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in text:
                text = text.split("```", 1)[1].split("```", 1)[0].strip()
            data = json.loads(text)
            intent = data.get("intent", "none")
            if intent not in ("create", "modify", "cancel", "cleanup", "none"):
                intent = "none"
            return {
                "intent": intent,
                "slots": {
                    "recipient_override": (data.get("recipient_override") or "").strip(),
                    "target_keyword": (data.get("target_keyword") or "").strip(),
                    "new_event": (data.get("new_event") or "").strip(),
                    "cleanup_mode": (data.get("cleanup_mode") or "all").strip().lower(),
                },
            }
        except Exception as e:
            return {
                "intent": "unavailable",
                "slots": {},
                "error": f"待办意图识别失败: {e}",
            }

