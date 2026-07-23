#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
框架ReAct Agent - 轻量级任务规划协调器
只负责制定执行框架，具体操作由主Agent完成
"""

import json
from typing import Dict, Any, List

class FrameworkReActAgent:
    """框架ReAct Agent - 任务分解和协调"""
    
    def __init__(self, base_agent):
        """
        初始化框架Agent
        
        Args:
            base_agent: 基础AIAgent实例
        """
        self.base_agent = base_agent
        self.max_steps = 15  # 最大步数
        self.current_framework = []  # 当前框架
        self.completed_steps = []  # 已完成的步骤
        self._last_planner_context = ""  # 最近一次规划的意图/能力上下文

    def _cancelled(self) -> bool:
        return bool(self.base_agent.is_generation_cancelled())

    def _interrupted(self) -> str:
        return self.base_agent.interrupted_response()

    def _report_workflow_step(
        self,
        key: str,
        step: Dict,
        user_input: str,
        phase: str,
        result: str = "",
    ) -> None:
        """Report a concise structured step; internal planning text stays hidden."""
        from workflow_status import emit_workflow, framework_step_title

        action = step.get("action", "")
        # Search reports its generated queries/pages itself. Playwright reports
        # after resolving placeholder URLs, so its domain is accurate.
        if action in {"search_web", "call_playwright_react", "pass_to_main_agent"}:
            return
        result_text = str(result or "")
        title = framework_step_title(
            action,
            step.get("params", {}),
            phase=phase,
            user_input=user_input,
            result=result_text,
        )
        if title:
            event_phase = "failed" if phase != "active" and any(
                token in result_text for token in ("失败", "无法", "错误", "未找到", "❌")
            ) else phase
            emit_workflow(self.base_agent, key, title, event_phase)

    def _call_plan_llm(self, system: str, user: str, max_tokens: int = 500) -> str:
        from llm_router import chat_completion
        text = chat_completion(
            self.base_agent.config,
            config_key="framework_plan_model",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.7,
            timeout=15,
            task_label="framework_plan",
        )
        return (text or "").strip()

    def _format_capability_hint(self) -> str:
        cfg = self.base_agent.config
        kali_on = bool((cfg.get("kali_bridge") or {}).get("enabled", False))
        hex_on = bool((cfg.get("hexstrike_ai") or {}).get("enabled", False))
        return f"""
【当前能力开关】
- Kali 桥接: {"已启用" if kali_on else "未启用"}
- HexStrike AI: {"已启用" if hex_on else "未启用"}

规划约束（必须遵守）：
- HexStrike 未启用时：禁止 start_hexstrike_ai、use_hexstrike_tool，以及 use_mcp_tool 中 tool_name 为 hexstrike_* / kali_execute。
- Kali 桥接未启用时：禁止 kali_execute 及依赖 Kali 的安全工具。
- 能力未启用但用户有安全测试诉求时：仅 pass_to_main_agent，说明需在设置中开启对应功能。
"""

    def _format_product_glossary_hint(self) -> str:
        return """
【应用内部术语】
- 「识底深湖」= 本程序 MemoryLake 记忆模块，不是域名、服务器或渗透扫描目标。
- 「测试识底深湖 / 本地记忆 / 主题总结 / CTX-LINK / 本地模式」= 应用功能或 LLM 配置测试，不是安全测试。
"""

    def _format_security_intent_hint(self, user_input: str) -> str:
        try:
            intent = self.base_agent.classify_security_intent(user_input)
        except Exception as e:
            print(f"⚠️ 框架规划-安全意图识别失败: {e}")
            return "\n【安全测试意图识别】识别未完成；非明确安全测试时不要安排 HexStrike/Kali。\n"
        if intent is None:
            return "\n【安全测试意图识别】识别未完成；非明确安全测试时不要安排 HexStrike/Kali。\n"
        cfg = self.base_agent.config
        hex_on = bool((cfg.get("hexstrike_ai") or {}).get("enabled", False))
        lines = [f"\n【安全测试意图识别】结果: {intent}"]
        if intent == "not_security":
            lines.append(
                "- 约束: 禁止 HexStrike/Kali/端口扫描/Web 漏洞扫描；"
                "用户测试记忆系统或本地 LLM 时只需 pass_to_main_agent。"
            )
        elif not hex_on:
            lines.append(
                "- 用户有安全测试相关意图，但 HexStrike 未启用："
                "禁止 start_hexstrike_ai 与 hexstrike_*；仅 pass_to_main_agent 说明如何开启。"
            )
        else:
            lines.append(
                "- 可安排 HexStrike/Kali 相关步骤（须先 start_hexstrike_ai，若适用）。"
            )
        return "\n".join(lines) + "\n"

    def _format_website_intent_hint(self, user_input: str) -> str:
        try:
            site = self.base_agent._ai_identify_website_intent(user_input)
        except Exception:
            return ""
        if site:
            return f"""
【网站打开意图识别】用户要打开网站: {site}
- 规划: get_url_from_website_map（params name={site}）+ call_playwright_react + pass_to_main_agent。
- 不要对此次打开请求使用 HexStrike 或 search_web。
"""
        return """
【网站打开意图识别】非打开网站请求（not_website）。
- 不要将用户输入当作 URL/扫描目标；勿因句中出现名称就 search_web 或端口扫描。
"""

    def _format_app_intent_hint(self, user_input: str) -> str:
        try:
            app_result = self.base_agent._ai_identify_app_launch_intent(user_input)
            if app_result and len(app_result) == 2 and app_result[0] == "app_launch" and app_result[1]:
                app_name = app_result[1].strip()
                return f"""
【应用启动意图识别】app_launch | {app_name}
- 打开该应用必须使用 open_application，params: {{"name": "{app_name}"}}。
- 不要使用 get_url_from_website_map 或 call_playwright_react 代替打开本地应用。
"""
        except Exception:
            pass
        return """
【应用启动意图识别】not_app（非打开本地应用）。
"""

    def _build_planner_context(self, user_input: str, search_intent_hint: str = "") -> str:
        """汇总意图与能力信息供框架规划使用（不含读屏；读屏由框架外自动插入）。"""
        parts = [
            self._format_capability_hint(),
            self._format_product_glossary_hint(),
            search_intent_hint or "",
            self._format_security_intent_hint(user_input),
            self._format_website_intent_hint(user_input),
            self._format_app_intent_hint(user_input),
            """
【读屏说明】
- 读屏/截屏/analyze_screen 由框架引擎在规划之外自动处理，你无需也禁止规划 analyze_screen。
- 即使用户可能在看屏幕，也只按其他意图规划；读屏步骤会自动插入（若已开启截图许可）。
""",
        ]
        return "\n".join(p for p in parts if p.strip())
        
    def _check_file_context_needed(self, user_input: str) -> bool:
        """
        检查用户问题是否需要结合文件上下文
        
        Args:
            user_input: 用户输入
            
        Returns:
            是否需要读取文件内容
        """
        try:
            # 检查是否有最近分析的文件
            if not self.base_agent.recent_file_analysis:
                print(f"📂 [文件上下文检查] 未检测到最近分析的文件")
                return False
            if self.base_agent.recent_file_analysis.get("combined"):
                print(f"📂 [文件上下文检查] 组合发送已注入文件内容，跳过重复分析")
                return False
            
            file_info = self.base_agent.recent_file_analysis
            print(f"📂 [文件上下文检查] 检测到最近分析的文件: {file_info['file_name']}")
            print(f"🤔 [文件上下文检查] 判断问题是否与文件相关...")
            
            # 使用AI判断问题是否与文件相关
            judge_prompt = f"""你刚刚分析了一个文件：{file_info['file_name']} ({file_info['file_type']})

现在用户提出了一个问题："{user_input}"

请判断这个问题是否与刚才分析的文件相关。

判断标准：
1. 如果问题明确提到"文件"、"代码"、"刚才"、"这个"等指代刚分析的文件
2. 如果问题询问代码结构、数量统计（如循环数、函数数）
3. 如果问题是对文件内容的追问或延伸讨论
4. 如果问题很简短且像是对上一次分析的追问（如"里边用了几个循环"、"这个文件的功能是什么"）

请只回答 "YES" 或 "NO"，不要有其他内容。"""
            
            judge_result = self._call_plan_llm(
                "你是文件上下文判断助手。只回答YES或NO。",
                judge_prompt,
                max_tokens=10,
            ).upper()
            is_related = "YES" in judge_result
            
            if is_related:
                print(f"✅ [文件上下文检查] AI判断：问题与文件 {file_info['file_name']} 相关，需要读取文件内容")
            else:
                print(f"❌ [文件上下文检查] AI判断：问题与文件无关，使用常规处理流程")
            
            return is_related
            
        except Exception as e:
            print(f"⚠️ [文件上下文检查] 判断失败: {e}")
            return False

    def _join_collected_text(self, collected_info: Dict[str, str]) -> str:
        """将框架步骤结果拼接为小写文本，便于一致性判定。"""
        parts = []
        for key in sorted(collected_info.keys()):
            parts.append(str(collected_info.get(key, "")))
        return "\n".join(parts).lower()

    def _has_todo_failure_signal(self, collected_info: Dict[str, str]) -> bool:
        """判断是否存在待办执行失败信号。"""
        text = self._join_collected_text(collected_info)
        failure_markers = [
            "待办意图识别服务暂不可用",
            "未配置默认收件邮箱",
            "修改失败",
            "任务取消失败",
            "执行失败",
            "❌",
            "失败",
            "错误",
            "无法",
        ]
        return any(marker.lower() in text for marker in failure_markers)

    def _has_todo_success_evidence(self, collected_info: Dict[str, str]) -> bool:
        """待办成功必须有 task_id 证据，避免总结阶段幻觉成功。"""
        text = self._join_collected_text(collected_info)
        return ("任务id:" in text) or ("task_" in text)

    def _has_todo_execution_evidence(self, collected_info: Dict[str, str]) -> bool:
        """判断前序步骤是否已实际执行过待办操作（创建/修改/取消等）。"""
        text = self._join_collected_text(collected_info)
        markers = [
            "已设置",
            "已将",
            "替换为",
            "已取消",
            "任务id",
            "task_",
            "新提醒",
            "取消提醒",
            "修改任务成功",
            "创建任务成功",
        ]
        return any(m.lower() in text for m in markers)

    def _check_screen_context_needed(self, user_input: str) -> bool:
        """检查用户是否要求读取当前电脑屏幕（截屏+视觉理解）。使用主 Agent 的 AI 读屏意图识别。截图许可关闭时不触发。"""
        try:
            if not self.base_agent.config.get("screenshot_allowed", True):
                return False
            if not (user_input or "").strip():
                return False
            need_screen = self.base_agent._ai_identify_screen_read_intent(user_input)
            if not need_screen:
                return False
            from llm_vision_router import vision_is_configured

            if not vision_is_configured(self.base_agent.config):
                print("🖥️ [屏幕上下文] AI 识别为读屏意图，但未配置视觉模型，跳过")
                return False
            print("🖥️ [屏幕上下文] AI 识别为读屏意图，将截屏并使用视觉模型分析")
            return True
        except Exception as e:
            print(f"⚠️ [屏幕上下文检查] 判断失败: {e}")
            return False

    def process_combined_command(self, user_input: str, stream_callback=None) -> str:
        """组合发送专用：自动构建框架并执行，跳过 LLM 规划。"""
        from combined_send_handler import build_combined_framework

        self._current_stream_callback = stream_callback
        att = getattr(self.base_agent, "combined_send_payload", None)
        if not att:
            print("❌ [组合发送] 无 combined_send_payload")
            return None

        print("\n" + "=" * 60)
        print("📎 [组合发送] 启动自动框架")
        print("=" * 60)

        framework, hint = build_combined_framework(att, self.base_agent.config)
        self._last_planner_context = hint
        if self._cancelled():
            return self._interrupted()
        if not framework:
            return None

        self.current_framework = framework
        total_steps = len(framework)
        print(f"\n📋 [组合发送框架] 共 {total_steps} 步")
        for i, step in enumerate(framework, 1):
            print(f"  [{i}] {step.get('description', 'N/A')} (action: {step.get('action', 'None')})")
        print("")

        collected_info = {}
        self.completed_steps = []

        for step_idx, step in enumerate(framework, 1):
            if self._cancelled():
                return self._interrupted()
            print(f"\n{'=' * 60}")
            print(f"🎯 [组合发送 {step_idx}/{total_steps}] {step['description']}")
            print(f"{'=' * 60}")
            workflow_key = f"combined:{step_idx}:{step.get('action', '')}"
            self._report_workflow_step(workflow_key, step, user_input, "active")
            result = self._execute_step(step, user_input, collected_info)
            self._report_workflow_step(workflow_key, step, user_input, "done", result)
            if self._cancelled():
                return self._interrupted()
            print(f"✅ [完成] {result[:200]}{'...' if len(result) > 200 else ''}")
            collected_info[f"step_{step_idx}"] = result
            self.completed_steps.append(
                {
                    "step": step_idx,
                    "description": step["description"],
                    "action": step.get("action", ""),
                    "params": step.get("params", {}),
                    "result": result,
                }
            )

        print(f"\n{'=' * 60}")
        print(f"✅ [组合发送完成] 共 {len(self.completed_steps)} 步")
        print(f"{'=' * 60}\n")

        if self.completed_steps:
            last_step = self.completed_steps[-1]
            last_action = last_step.get("action")
            last_params = last_step.get("params", {})
            if last_action in (
                "combined_vision_images",
                "combined_vision_video",
                "analyze_image",
                "analyze_video",
            ) and last_params.get("direct_return", False):
                return last_step.get("result", "")

        return self._generate_final_answer(user_input, collected_info)

    def process_command(self, user_input: str, stream_callback=None) -> str:
        """
        使用框架ReAct模式处理命令
        
        工作流程：
        1. 制定执行框架
        2. 逐步执行框架
        3. 动态调整框架（如果需要）
        4. 返回最终结果
        
        stream_callback: 若提供，在 pass_to_main_agent 时会传给主 Agent，用于流式显示与流式 TTS
        """
        self._current_stream_callback = stream_callback
        print("\n" + "="*60)
        print("🧠 [框架ReAct] 启动任务规划引擎")
        print("="*60)

        # 文件创建请求也交由 ReAct 规划器制定步骤，不再走快路径
        # 🔥 检查是否需要结合文件上下文 / 读屏上下文
        needs_file_context = self._check_file_context_needed(user_input)
        needs_screen_context = self._check_screen_context_needed(user_input)

        # 视频/读屏/只打开网站 等均由 ReAct 规划器制定步骤，不再走快路径
        # 仅安全测试任务仍使用专用框架生成，其余一律由规划模型制定
        if self._is_security_test_task(user_input):
            print("=" * 60)
            print("🔒 [安全测试任务检测] 检测到安全测试请求")
            print(f"📝 用户输入: {user_input}")
            print("🔒 [安全测试任务] 将使用HexStrike AI智能规划")
            print("=" * 60)
            framework = self._create_hexstrike_intelligence_framework(user_input)
            print(f"📋 [框架创建] 已创建HexStrike AI智能规划框架，共 {len(framework)} 步")
            for i, step in enumerate(framework, 1):
                print(f"  [{i}] {step.get('description', 'N/A')} (action: {step.get('action', 'N/A')})")
            print("=" * 60)
        else:
            search_intent_hint = ""
            try:
                from web_search_pipeline import (
                    recognize_web_search_intent,
                    format_intent_hint_for_planner,
                )
                intent = recognize_web_search_intent(
                    self.base_agent,
                    user_input,
                    self.base_agent._get_recent_context(),
                )
                search_intent_hint = format_intent_hint_for_planner(intent)
            except Exception as e:
                print(f"⚠️ 联网意图识别失败: {e}")
            framework = self._plan_framework(user_input, search_intent_hint=search_intent_hint)

        if self._cancelled():
            return self._interrupted()
        
        # 🔥 如果检测到需要文件上下文，即使框架为None也要创建包含analyze_file的框架
        if needs_file_context:
            print("📂 [文件上下文] 检测到需要文件上下文，创建文件分析框架")
            if not framework:
                # 如果框架为None，创建一个只包含文件分析和传递的简单框架
                framework = [
                    {
                        "description": "读取最近分析的文件内容",
                        "action": "analyze_file",
                        "params": {}
                    },
                    {
                        "description": "将文件内容传递给主Agent回答",
                        "action": "pass_to_main_agent",
                        "params": {}
                    }
                ]
            else:
                # 如果框架存在，在开头添加文件分析步骤
                print("📂 [文件上下文] 在框架开头添加文件分析步骤")
                framework = [
                    {
                        "description": "读取最近分析的文件内容",
                        "action": "analyze_file",
                        "params": {}
                    }
                ] + framework

        # 🔥 如果读屏意图识别为需要看屏幕，在框架前插入 analyze_screen
        if needs_screen_context:
            print("🖥️ [屏幕上下文] 检测到读屏意图，在框架前插入截屏分析步骤")
            if not framework:
                framework = [
                    {
                        "description": "截屏并分析当前屏幕内容以回答用户问题",
                        "action": "analyze_screen",
                        "params": {}
                    },
                    {
                        "description": "将屏幕分析结果传递给主Agent回答",
                        "action": "pass_to_main_agent",
                        "params": {}
                    }
                ]
            else:
                framework = [
                    {
                        "description": "截屏并分析当前屏幕内容以回答用户问题",
                        "action": "analyze_screen",
                        "params": {}
                    }
                ] + framework
        
        if not framework:
            print("❌ 无法制定执行框架，使用标准模式")
            return None
        
        self.current_framework = framework
        total_steps = len(framework)
        
        print(f"\n📋 [执行框架] 共 {total_steps} 步")
        for i, step in enumerate(framework, 1):
            print(f"  [{i}] {step.get('description', 'N/A')} (action: {step.get('action', 'None')})")
        print("")
        
        # 逐步执行框架
        collected_info = {}  # 收集的信息
        
        for step_idx, step in enumerate(framework, 1):
            if self._cancelled():
                return self._interrupted()
            print(f"\n{'='*60}")
            print(f"🎯 [第 {step_idx}/{total_steps} 步] {step['description']}")
            print(f"{'='*60}")
            
            # 执行这一步
            workflow_key = f"framework:{step_idx}:{step.get('action', '')}"
            self._report_workflow_step(workflow_key, step, user_input, "active")
            result = self._execute_step(step, user_input, collected_info)
            self._report_workflow_step(workflow_key, step, user_input, "done", result)
            if self._cancelled():
                return self._interrupted()
            
            print(f"✅ [完成] {result[:200]}{'...' if len(result) > 200 else ''}")
            
            # 保存结果
            collected_info[f"step_{step_idx}"] = result
            self.completed_steps.append({
                "step": step_idx,
                "description": step['description'],
                "action": step.get('action', ''),  # 🔥 保存action字段，用于后续判断
                "params": step.get('params', {}),  # 🔥 保存params字段，用于检查direct_return等标记
                "result": result
            })
            
            # 检查是否需要调整框架
            # 🔒 如果HexStrike AI已经规划了攻击链，不再调整其规划步骤，但可以添加其他步骤
            if step_idx < total_steps:
                # 检查已完成步骤中是否有HexStrike AI规划或执行
                has_hexstrike_planning = any(
                    s.get("action") in ["use_hexstrike_intelligence", "execute_hexstrike_attack_chain"]
                    for s in self.completed_steps
                )
                
                if has_hexstrike_planning:
                    # HexStrike AI已经规划过，检查剩余步骤
                    remaining_actions = [s.get("action", "") for s in framework[step_idx:]]
                    print("=" * 60)
                    print("🔒 [框架调整检查] HexStrike AI已规划攻击链")
                    print(f"   已完成步骤: {[s.get('action') for s in self.completed_steps]}")
                    print(f"   剩余步骤: {remaining_actions}")
                    if "pass_to_main_agent" in remaining_actions:
                        # 剩余步骤已经包含传递步骤，不需要调整
                        print("🔒 [框架调整] 剩余步骤已包含传递，跳过框架调整")
                        print("=" * 60)
                    else:
                        print("🔒 [框架调整] 剩余步骤缺少传递步骤，将添加")
                        print("=" * 60)
                        # 只添加传递步骤，不调整HexStrike AI的规划
                        print("🔒 HexStrike AI已规划攻击链，仅添加传递步骤，不调整攻击规划")
                        framework = framework[:step_idx] + framework[step_idx:] + [
                            {
                                "description": "将HexStrike AI规划结果传递给主Agent",
                                "action": "pass_to_main_agent",
                                "params": {}
                            }
                        ]
                        total_steps = len(framework)
                else:
                    # 没有HexStrike AI规划，正常调整
                    should_adjust = self._should_adjust_framework(user_input, collected_info, framework[step_idx:], result)
                    if should_adjust:
                        print(f"\n🔄 [框架调整] 根据当前进展重新规划后续步骤...")
                        new_framework = self._adjust_framework(user_input, collected_info, framework[step_idx:], result)
                        if new_framework:
                            # 更新框架
                            framework = framework[:step_idx] + new_framework
                            total_steps = len(framework)
                            print(f"📋 [新框架] 更新为 {total_steps} 步")
                            for i, s in enumerate(framework[step_idx:], step_idx + 1):
                                print(f"  [{i}] {s['description']}")
        
        # 生成最终回答
        print(f"\n{'='*60}")
        print(f"✅ [框架执行完成] 共完成 {len(self.completed_steps)} 步")
        print(f"{'='*60}\n")
        
        # 🔥 检查最后一步是否是analyze_image且标记为direct_return，如果是则直接返回结果
        if self.completed_steps:
            last_step = self.completed_steps[-1]
            if last_step.get("action") == "analyze_image":
                last_params = last_step.get("params", {})
                if last_params.get("direct_return", False):
                    print("🖼️ [图片分析] 检测到direct_return标记，直接返回图片分析结果")
                    return last_step.get("result", "")
            # 🔥 检查最后一步是否是analyze_video且标记为direct_return，如果是则直接返回结果
            elif last_step.get("action") == "analyze_video":
                last_params = last_step.get("params", {})
                if last_params.get("direct_return", False):
                    print("🎬 [视频分析] 检测到direct_return标记，直接返回视频分析结果")
                    return last_step.get("result", "")
        
        final_answer = self._generate_final_answer(user_input, collected_info)
        return final_answer
    
    def _plan_framework(self, user_input: str, search_intent_hint: str = "") -> List[Dict[str, Any]]:
        """
        制定执行框架
        
        Args:
            user_input: 用户输入
            
        Returns:
            框架列表 [{"description": "步骤描述", "action": "action_type", "params": {...}}]
        """
        planner_context = self._build_planner_context(user_input, search_intent_hint)
        self._last_planner_context = planner_context

        cfg = self.base_agent.config
        from llm_spec import vision_model_label

        image_model = vision_model_label(cfg, "vision_image_model")
        video_model = vision_model_label(cfg, "vision_video_model")

        prompt = f"""你是一个任务规划专家，需要为用户的请求制定执行框架。

**必须优先服从**下方【意图识别结果】【当前能力开关】【应用内部术语】，不得与它们矛盾。

用户请求：{user_input}
{planner_context}
请分析用户的请求，制定执行框架。

**可用的操作类型：**
1. get_weather - 获取天气信息（直接调用天气API）
2. get_location - 获取位置信息
3. search_web - 搜索网络信息（仅当【联网意图识别】need_search 为 true）
4. analyze_file - 分析最近上传的文件
5. analyze_image - 使用「{image_model}」分析最近上传的图片
6. analyze_video - 使用「{video_model}」分析最近上传的视频
7. open_application - 打开应用程序
8. get_url_from_website_map - 从网站管理或AI知识库获取网站URL
9. call_playwright_react - 调用Playwright ReAct Agent执行网页自动化
10. use_mcp_tool - 使用MCP工具
11. use_hexstrike_tool - 使用HexStrike电子战工具（仅当 HexStrike 已启用且安全意图非 not_security）
12. start_hexstrike_ai - 启动HexStrike AI服务器（仅当 HexStrike 已启用且安全意图非 not_security）
13. delegate_subtask_to_main_agent - 将子任务交给主Agent执行并获取结果，params: {{"subtask": "具体子任务描述"}}
14. pass_to_main_agent - 将信息传递给主Agent（用于最终回答）

注意：analyze_screen（读屏）不在你的职责内，禁止出现在规划中。

       **HexStrike AI（仅当【当前能力开关】HexStrike 已启用 且 【安全测试意图识别】≠ not_security 时适用）：**
       通过 use_mcp_tool 调用 hexstrike_* 或 kali_execute（Kali 桥接也需已启用）。
       常用: hexstrike_port_scan, hexstrike_web_vuln_scan, hexstrike_directory_scan, kali_execute 等。
       使用前通常需 start_hexstrike_ai。

**规划原则：**
1. **步数完全自由**：根据任务复杂度自主决定。
2. **服从意图识别**：
   - 【联网意图识别】need_search=false → 禁止 search_web
   - 【安全测试意图识别】not_security → 禁止一切 HexStrike/Kali/扫描类步骤
   - 【网站打开意图识别】已识别网站名 → 用 open 网站流程，勿 search_web 勿扫描
   - 【应用启动意图识别】app_launch → 用 open_application
   - 测试识底深湖/记忆/本地 LLM → 通常只需 pass_to_main_agent
3. **工具选择**：
   - 简单对话 / 功能测试 → pass_to_main_agent
   - 天气 → get_weather + pass_to_main_agent
   - 普通网页（非安全测试）→ get_url_from_website_map + call_playwright_react + pass_to_main_agent
   - 安全测试（能力已启用且意图匹配）→ HexStrike 相关 + pass_to_main_agent
   - 文件/图片/视频追问 → analyze_* + pass_to_main_agent
   - 信息查询且 need_search=true → search_web + pass_to_main_agent（至多一次 search_web）
4. **最后一步必须是 pass_to_main_agent**
5. **禁止规划 analyze_screen**（读屏由框架外自动处理）

**仅当单一类型且无需工具时可返回 null：**
- 纯代码/文件/对话/推荐/创作类（无复合任务）

**返回格式：** JSON 数组，每项含 description、action、params。只返回 JSON。

请规划执行框架：
"""
        
        # 经 llm_router 调用框架规划模型
        try:
            response = self._call_plan_llm(
                "你是任务规划专家，擅长将复杂任务分解为清晰的执行步骤。",
                prompt,
            )
        except Exception as e:
            print(f"❌ API调用失败: {e}")
            return None
        
        try:
            # 清理响应
            response = response.strip()
            
            # 检查AI是否返回null（表示应该交给主Agent处理）
            if response.lower() in ["null", "none", "空"]:
                print("ℹ️ AI规划模型建议直接交给主Agent处理")
                return None
            
            if response.startswith("```json"):
                response = response[7:]
            if response.startswith("```"):
                response = response[3:]
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()
            
            # 再次检查是否为null
            if response.lower() in ["null", "none", "空"]:
                print("ℹ️ AI规划模型建议直接交给主Agent处理")
                return None
            
            framework = json.loads(response)
            
            # 调试：打印解析后的框架
            print(f"🔍 [调试] AI规划的框架: {json.dumps(framework, ensure_ascii=False, indent=2)}")
            
            # 如果返回空数组，说明不需要框架
            if not framework or len(framework) == 0:
                return None
            
            return framework
            
        except json.JSONDecodeError as e:
            print(f"❌ 框架解析失败: {e}")
            print(f"原始响应: {response[:200]}")
            return None
    
    def _execute_step(self, step: Dict, user_input: str, collected_info: Dict) -> str:
        """
        执行框架中的一步
        
        Args:
            step: 步骤定义
            user_input: 原始用户输入
            collected_info: 已收集的信息
            
        Returns:
            执行结果
        """
        action = step.get("action")
        params = step.get("params", {})
        
        try:
            if action == "get_location":
                location = self.base_agent.location
                return f"位置：{location}"
            
            elif action == "get_url_from_website_map":
                # 从网站管理或AI知识库获取URL
                # 支持多种可能的参数名：name, website, website_name
                site_name = (
                    params.get("name") or 
                    params.get("website") or 
                    params.get("website_name") or 
                    ""
                )
                print(f"    🔍 查找网站URL: {site_name}")
                print(f"    🔍 params内容: {params}")

                # 🔥 优先检查：如果用户输入或site_name中已包含完整URL，直接提取返回
                import re
                # 检查用户输入
                url_pattern = r'https?://[^\s\u4e00-\u9fff]+'  # 匹配http(s)://开头到中文或空格前的URL
                url_match = re.search(url_pattern, user_input)
                if url_match:
                    extracted_url = url_match.group(0)
                    # 移除末尾可能的中文字符
                    extracted_url = re.sub(r'[\u4e00-\u9fff]+$', '', extracted_url)
                    print(f"    ✅ 从用户输入中直接提取URL: {extracted_url}")
                    return f"获取到URL: {extracted_url}"
                
                # 检查site_name参数
                url_match = re.search(url_pattern, site_name)
                if url_match:
                    extracted_url = url_match.group(0)
                    extracted_url = re.sub(r'[\u4e00-\u9fff]+$', '', extracted_url)
                    print(f"    ✅ 从site_name参数中直接提取URL: {extracted_url}")
                    return f"获取到URL: {extracted_url}"

                # 占位/泛化词过滤：避免将"相关社交媒体平台"等占位词当成真实网站
                placeholder_indicators = [
                    "相关社交媒体平台", "相关平台", "相关网站", "某平台", "某网站", "社交平台", "社交媒体平台"
                ]
                if any(ind in site_name for ind in placeholder_indicators):
                    return "❌ 未提供明确网站名称，已跳过获取URL"
                
                # 优先从网站管理中查找
                website_map = self.base_agent.website_map
                url = website_map.get(site_name)
                
                # 如果没有，尝试AI生成
                if not url:
                    print(f"    🤖 网站管理中未找到，尝试AI生成URL...")
                    url = self.base_agent._ai_generate_website_url(site_name)
                    if url:
                        print(f"    ✅ AI成功生成URL: {url}")
                
                if url:
                    return f"获取到URL: {url}"
                else:
                    return f"❌ 无法找到网站 {site_name} 的URL"
            
            elif action == "call_playwright_react":
                # 调用Playwright ReAct Agent执行网页自动化
                url = params.get("url", "")
                # 如果用户是一般信息查询，不需要打开浏览器，直接跳过
                intent_open_keywords = ["打开", "浏览器", "登录", "点击", "网页", "在\n浏览器", "在浏览器", "搜索并打开", "访问", "进入"]
                informational_keywords = ["是谁", "现状", "状态", "被封", "是否", "怎么", "简介", "情况", "了吗", "吗", "介绍", "详细"]
                if any(k in user_input for k in informational_keywords) and not any(k in user_input for k in intent_open_keywords):
                    return "ℹ️ 这是信息查询任务，无需打开网页；已基于搜索给出答案"
                
                print(f"    🔍 原始URL参数: {url}")
                print(f"    🔍 已收集信息: {list(collected_info.keys())}")
                
                # 🔍 智能URL提取（从params或collected_info）
                # 检测占位符：previous、步骤、获取、{{、}}等
                is_placeholder = (
                    not url or 
                    "previous" in url.lower() or
                    "步骤" in url or 
                    "获取" in url or
                    "{{" in url or
                    "}}" in url or
                    not url.startswith("http")
                )
                
                if is_placeholder:
                    # URL是占位符，从已收集信息中提取实际URL
                    print(f"    🔄 检测到占位符，从已收集信息中提取URL...")
                    for key, value in collected_info.items():
                        if "获取到URL:" in str(value):
                            url = value.split("获取到URL:")[1].strip()
                            print(f"    ✅ 从{key}中提取URL: {url}")
                            break
                
                if not url or not url.startswith("http"):
                    print(f"    ❌ 最终URL无效: {url}")
                    return "❌ 未找到有效的网站URL，无法执行"
                
                print(f"    🤖 调用网页打开功能: {url}")
                print(f"    📝 用户任务: {user_input}")
                from workflow_status import emit_workflow, url_host

                target_host = url_host(url)
                emit_workflow(
                    self.base_agent,
                    "playwright:open",
                    f"打开 {target_host} 中",
                    "active",
                )
                
                # 直接调用主Agent的网页打开功能（明确传递user_input参数）
                result = self.base_agent._open_website_wrapper(
                    site_name=url,
                    website_map=None,
                    user_input=user_input
                )
                failed = any(token in str(result) for token in ("失败", "无法", "错误", "❌"))
                emit_workflow(
                    self.base_agent,
                    "playwright:open",
                    f"{'无法打开' if failed else '已打开'} {target_host}",
                    "failed" if failed else "done",
                )
                return result
            
            elif action == "get_weather":
                # 从已收集信息中获取位置
                location_info = collected_info.get("step_1", "")
                city = self.base_agent._extract_city_from_location(location_info)
                if not city:
                    city = self.base_agent._extract_city_from_location(self.base_agent.location)
                
                weather_source = self.base_agent.config.get("weather_source", "高德地图API")
                if weather_source == "高德地图API":
                    from amap_tool import AmapTool
                    amap_key = self.base_agent.config.get("amap_key", "")
                    weather = AmapTool.get_weather(city, amap_key)
                else:
                    heweather_key = self.base_agent.config.get("heweather_key", "")
                    weather = self.base_agent.tools["天气"](city, heweather_key)
                
                return f"天气：{weather}"
            
            elif action == "search_web":
                supplement = params.get("query", "") or ""
                snapshot_parts = []
                for k in sorted(collected_info.keys()):
                    snapshot_parts.append(f"{k}: {str(collected_info[k])[:400]}")
                framework_snapshot = "\n".join(snapshot_parts)
                try:
                    from web_search_pipeline import run_web_search

                    def _status(msg):
                        print(f"🔍 {msg}")
                        try:
                            self.base_agent.response_status_message.emit(msg)
                        except Exception:
                            pass

                    bundle = run_web_search(
                        self.base_agent,
                        user_input,
                        supplement_query=supplement,
                        conversation_context=self.base_agent._get_recent_context(),
                        framework_snapshot=framework_snapshot,
                        force=True,
                        status_callback=_status,
                    )
                    self.base_agent.search_context = bundle.to_context_text()
                    return bundle.short_summary_for_framework()
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    return f"联网检索失败: {e}"
            
            elif action == "analyze_file":
                if self.base_agent.recent_file_analysis:
                    info = self.base_agent.recent_file_analysis
                    # 🔥 返回更详细的文件信息，包括内容摘要，方便主agent结合上下文回答
                    file_context = f"""文件信息：
- 文件名：{info['file_name']}
- 文件类型：{info['file_type']}
- 文件摘要：{info.get('summary', '')}
- 文件分析：{info.get('analysis', '')}
"""
                    # 如果是代码文件，添加统计信息
                    if 'CODE_' in info.get('file_type', ''):
                        metadata = info.get('metadata', {})
                        structure = metadata.get('structure', {})
                        metrics = metadata.get('metrics', {})
                        
                        if metrics:
                            file_context += f"\n代码统计：\n"
                            if_count = metrics.get('if_count', metrics.get('if_statements', 0))
                            for_count = metrics.get('for_count', metrics.get('for_loops', 0))
                            while_count = metrics.get('while_count', metrics.get('while_loops', 0))
                            total_loops = for_count + while_count
                            file_context += f"- if语句：{if_count} 个\n"
                            file_context += f"- for循环：{for_count} 个\n"
                            file_context += f"- while循环：{while_count} 个\n"
                            file_context += f"- 循环总数：{total_loops} 个\n"
                            file_context += f"- 总行数：{metrics.get('total_lines', 0)} 行\n"
                        
                        if structure:
                            if structure.get('classes'):
                                file_context += f"- 类定义：{len(structure['classes'])} 个\n"
                            if structure.get('functions'):
                                file_context += f"- 函数/方法：{len(structure['functions'])} 个\n"
                    
                    # 添加部分文件内容（如果不太长）
                    content = info.get('content', '')
                    if content and len(content) < 5000:
                        file_context += f"\n文件内容（部分）：\n{content[:5000]}"
                    elif content:
                        file_context += f"\n文件内容（前5000字符）：\n{content[:5000]}..."
                    
                    return file_context
                return "❌ 无文件上下文"
            
            elif action == "analyze_image":
                if (
                    self.base_agent.recent_image_analysis
                    and self.base_agent.recent_image_analysis.get("combined")
                ):
                    return "组合发送轮次：请使用 combined_vision_images，勿重复 analyze_image"
                if self.base_agent.recent_image_analysis:
                    image_info = self.base_agent.recent_image_analysis
                    user_question = params.get("user_question", "")
                    direct_return = params.get("direct_return", False)

                    from llm_spec import vision_model_label

                    image_model = vision_model_label(
                        self.base_agent.config, "vision_image_model"
                    )
                    print(
                        f"🖼️ [图片分析] 使用 {image_model} 分析图片: {image_info['image_name']}"
                    )
                    if direct_return:
                        print("🖼️ [图片分析] 标记为直接返回模式，将直接返回结果")
                    
                    # 调用process_image方法，传入用户问题
                    sc = getattr(self, '_current_stream_callback', None)
                    result = self.base_agent.process_image(
                        image_info['image_path'], user_question, stream_callback=sc
                    )
                    
                    # 更新图片分析上下文
                    self.base_agent.recent_image_analysis['analysis'] = result
                    
                    # 如果标记为直接返回，直接返回结果（不添加前缀）
                    if direct_return:
                        return result
                    else:
                        return f"图片分析结果：\n{result}"
                return "❌ 无图片上下文"

            elif action == "combined_vision_images":
                att = getattr(self.base_agent, "combined_send_payload", None)
                if not att or not att.has_images():
                    return "❌ 组合发送无图片"
                sc = getattr(self, "_current_stream_callback", None)
                from combined_send_handler import run_combined_vision_images

                result = run_combined_vision_images(
                    self.base_agent, att, stream_callback=sc
                )
                direct_return = params.get("direct_return", False)
                if direct_return:
                    return result
                return f"图片分析结果：\n{result}"

            elif action == "combined_vision_video":
                att = getattr(self.base_agent, "combined_send_payload", None)
                if not att or not att.has_video():
                    return "❌ 组合发送无视频"
                sc = getattr(self, "_current_stream_callback", None)
                from combined_send_handler import run_combined_vision_video_direct

                result = run_combined_vision_video_direct(
                    self.base_agent, att, stream_callback=sc
                )
                direct_return = params.get("direct_return", False)
                if direct_return:
                    return result
                return f"视频分析结果：\n{result}"

            elif action == "combined_video_segment":
                att = getattr(self.base_agent, "combined_send_payload", None)
                if not att or not att.has_video():
                    return "❌ 组合发送无视频"
                sc = getattr(self, "_current_stream_callback", None)
                from combined_send_handler import run_combined_video_segment

                result = run_combined_video_segment(
                    self.base_agent, att, stream_callback=sc
                )
                file_extract = getattr(self.base_agent, "_combined_file_extract", "")
                if file_extract.strip():
                    result = (
                        result
                        + f"\n\n【附件文件内容（供整合）】\n{file_extract.strip()}"
                    )
                return result

            elif action == "analyze_screen":
                user_question = params.get("user_question", user_input)
                from llm_spec import vision_model_label

                screen_model = vision_model_label(
                    self.base_agent.config, "vision_screen_model"
                )
                print(f"🖥️ [屏幕分析] 截屏并使用 {screen_model} 分析...")
                sc = getattr(self, '_current_stream_callback', None)
                result = self.base_agent.analyze_screen(user_question, stream_callback=sc)
                return f"屏幕分析结果：\n{result}"
            
            elif action == "analyze_video":
                if (
                    self.base_agent.recent_video_analysis
                    and self.base_agent.recent_video_analysis.get("combined")
                ):
                    return "组合发送轮次：请使用 combined_vision_video，勿重复 analyze_video"
                if self.base_agent.recent_video_analysis:
                    video_info = self.base_agent.recent_video_analysis
                    user_question = params.get("user_question", "")
                    direct_return = params.get("direct_return", False)

                    from llm_spec import vision_model_label

                    video_model = vision_model_label(
                        self.base_agent.config, "vision_video_model"
                    )
                    print(
                        f"🎬 [视频分析] 使用 {video_model} 分析视频: {video_info['video_name']}"
                    )
                    if direct_return:
                        print("🎬 [视频分析] 标记为直接返回模式，将直接返回结果")
                    
                    # 调用process_video方法，传入用户问题
                    sc = getattr(self, '_current_stream_callback', None)
                    result = self.base_agent.process_video(
                        video_info['video_path'], user_question, stream_callback=sc
                    )
                    
                    # 更新视频分析上下文
                    self.base_agent.recent_video_analysis['analysis'] = result
                    
                    # 🔥 检查是否是分段分析结果，只有分段分析才需要主agent整合
                    is_segmented = video_info.get('is_segmented', False) or "[SEGMENTED_VIDEO_ANALYSIS]" in result
                    
                    if is_segmented:
                        print("🎬 [视频分析] 检测到分段分析结果，将传递给主agent整合")
                        # 分段分析结果需要主agent整合，不直接返回
                        direct_return = False
                        # 移除标记，保留内容
                        if "[SEGMENTED_VIDEO_ANALYSIS]\n" in result:
                            result = result.replace("[SEGMENTED_VIDEO_ANALYSIS]\n", "")
                    
                    # 如果标记为直接返回且不是分段分析，直接返回结果
                    if direct_return and not is_segmented:
                        return result
                    else:
                        return f"视频分析结果：\n{result}"
                return "❌ 无视频上下文"
            
            elif action == "open_application":
                # 兼容多种参数名：name, application_name, app, app_name
                app_name = (
                    params.get("name") or
                    params.get("application_name") or
                    params.get("app") or
                    params.get("app_name") or
                    ""
                )
                return self.base_agent._open_application(app_name)
            
            elif action == "open_website":
                site_name = params.get("name", "")
                return self.base_agent._open_website_wrapper(site_name, user_input)
            
            elif action == "use_mcp_tool":
                # 使用MCP工具（包括HexStrike工具）
                tool_name = params.get("tool_name", "")
                tool_params = params.get("params", {})
                
                if not tool_name:
                    return "❌ 未指定MCP工具名称"
                
                result = self.base_agent.mcp_tools.execute_mcp_command(tool_name, **tool_params)
                return result
            
            elif action == "use_hexstrike_tool":
                # 使用HexStrike电子战工具（通过MCP工具调用）
                tool_name = params.get("tool_name", "")
                tool_params = params.get("params", {})
                
                if not tool_name:
                    return "❌ 未指定HexStrike工具名称"
                
                # HexStrike工具通过MCP工具调用
                result = self.base_agent.mcp_tools.execute_mcp_command(tool_name, **tool_params)
                return result
            
            elif action == "use_hexstrike_intelligence":
                # 使用HexStrike AI智能规划（让HexStrike AI自己规划攻击链）
                intelligence_type = params.get("intelligence_type", "create-attack-chain")
                target = params.get("target", "")
                objective = params.get("objective", None)
                
                if not target:
                    return "❌ 未指定目标"
                
                print(f"    🧠 正在使用HexStrike AI智能规划（类型: {intelligence_type}）...")
                try:
                    mcp_server = self.base_agent.mcp_tools.server
                    
                    if not hasattr(mcp_server, 'hexstrike_mcp_client') or not mcp_server.hexstrike_mcp_client:
                        return "❌ HexStrike AI客户端未初始化，请先启动服务器"
                    
                    # 根据类型调用不同的智能端点
                    if intelligence_type == "analyze-target":
                        result = mcp_server.hexstrike_analyze_target(target, params.get("analysis_type", "comprehensive"))
                    elif intelligence_type == "smart-scan":
                        result = mcp_server.hexstrike_smart_scan(target, params.get("scan_type", "comprehensive"))
                    elif intelligence_type == "create-attack-chain":
                        result = mcp_server.hexstrike_create_attack_chain(target, objective)
                    elif intelligence_type == "comprehensive-assessment":
                        result = mcp_server.hexstrike_comprehensive_assessment(target)
                    else:
                        return f"❌ 未知的智能规划类型: {intelligence_type}"
                    
                    return result
                except Exception as e:
                    import traceback
                    return f"❌ HexStrike AI智能规划失败: {str(e)}\n{traceback.format_exc()[:200]}"
            
            elif action == "execute_hexstrike_attack_chain":
                # 执行HexStrike AI攻击链（规划并执行，返回执行报告）
                target = params.get("target", "")
                objective = params.get("objective", None)
                
                print("=" * 60)
                print("🎯 [HexStrike AI执行] 开始执行攻击链")
                print(f"   📍 目标: {target}")
                print(f"   📝 任务描述: {objective[:100] if objective else 'N/A'}...")
                print("=" * 60)
                
                if not target:
                    print("❌ [HexStrike AI执行] 未指定目标")
                    return "❌ 未指定目标"
                
                print(f"    🚀 [步骤1] 调用HexStrike AI的execute_attack_chain方法...")
                print(f"    📋 [步骤1] 该方法将：")
                print(f"        1. 调用create-attack-chain进行规划")
                print(f"        2. 根据规划结果执行攻击链")
                print(f"        3. 返回执行报告")
                try:
                    mcp_server = self.base_agent.mcp_tools.server
                    
                    if not hasattr(mcp_server, 'hexstrike_mcp_client') or not mcp_server.hexstrike_mcp_client:
                        return "❌ HexStrike AI客户端未初始化，请先启动服务器"
                    
                    # 执行攻击链（会自动规划并执行）
                    result = mcp_server.hexstrike_execute_attack_chain(target, objective)
                    return result
                except Exception as e:
                    import traceback
                    return f"❌ HexStrike AI执行攻击链失败: {str(e)}\n{traceback.format_exc()[:200]}"
            
            elif action == "start_hexstrike_ai":
                # 启动HexStrike AI服务器
                print("=" * 60)
                print("🚀 [HexStrike AI启动] 开始启动HexStrike AI服务器...")
                try:
                    # 通过MCP服务器访问HexStrike AI客户端
                    mcp_server = self.base_agent.mcp_tools.server
                    
                    if not hasattr(mcp_server, 'hexstrike_mcp_client'):
                        return "❌ HexStrike AI客户端未初始化，请在ai_agent_config.json中配置hexstrike_ai"
                    
                    # 检查是否已运行
                    if mcp_server.hexstrike_mcp_client:
                        if mcp_server.hexstrike_mcp_client.is_available():
                            return "✅ HexStrike AI服务器已在运行"
                        else:
                            # 尝试重新连接
                            mcp_server.hexstrike_mcp_client._ensure_server_running()
                            if mcp_server.hexstrike_mcp_client.is_available():
                                return "✅ HexStrike AI服务器已启动"
                            else:
                                return "❌ HexStrike AI服务器启动失败，请检查配置和服务器路径"
                    else:
                        # 重新初始化
                        mcp_server._init_hexstrike_ai()
                        if mcp_server.hexstrike_mcp_client and mcp_server.hexstrike_mcp_client.is_available():
                            return "✅ HexStrike AI服务器已启动并连接成功"
                        else:
                            return "❌ HexStrike AI未配置或启动失败，请在ai_agent_config.json中配置hexstrike_ai（enabled: true, server_path: 服务器脚本路径）"
                except Exception as e:
                    import traceback
                    error_detail = traceback.format_exc()
                    return f"❌ 启动HexStrike AI服务器失败: {str(e)}\n详情: {error_detail}"

            elif action == "delegate_subtask_to_main_agent":
                # 将子任务交给主Agent执行，获取结果后继续框架后续步骤
                subtask = params.get("subtask", user_input)
                if not subtask or not str(subtask).strip():
                    return "❌ 未指定子任务内容"
                # 待办提醒类任务优先传递用户原句，避免改写污染时间语义与事件标题
                subtask_text = str(subtask).strip()
                is_todo_request = any(x in subtask_text for x in ["提醒", "休息提醒", "定时提醒"]) or "remind" in subtask_text.lower()
                if is_todo_request:
                    subtask = user_input
                print(f"📤 [子任务委托] 交给主Agent执行: {subtask[:60]}...")
                result = self.base_agent.process_command(
                    str(subtask).strip(),
                    skip_framework=True,
                    suppress_tool_routing=False,
                    skip_memory_save=is_todo_request
                )
                return result or "子任务已执行，无返回内容"
            
            elif action == "pass_to_main_agent":
                # 将结果交给主Agent生成最终回答：复用主Agent系统提示与流程
                print(f"    🔄 将框架执行结果传递给主Agent总结...")

                # 结果一致性守卫：若前序步骤已明确失败，直接返回失败结果，避免总结阶段“误报成功”
                if collected_info and self._has_todo_failure_signal(collected_info):
                    print("    🛡️ 检测到前序步骤失败，跳过总结生成，直接返回失败结果")
                    latest = str(collected_info.get(sorted(collected_info.keys())[-1], "")).strip()
                    return latest or "待办任务执行失败，请根据上一步错误信息修正后重试。"

                # 为避免重复联网搜索：组合发送整合步仍需联网；常规框架则临时关闭
                combined_active = bool(
                    getattr(self.base_agent, "combined_send_payload", None)
                )
                original_search_flag = self.base_agent.config.get("enable_web_search", False)
                if not combined_active:
                    self.base_agent.config["enable_web_search"] = False
                try:
                    # 直接调用主Agent的对话处理流程，并显式跳过框架以避免死循环。
                    # 默认抑制工具路由，避免重复打开浏览器/应用；
                    # 但待办/提醒类请求必须放开工具路由，确保真正执行 TodoService（创建/修改/取消）。
                    todo_keywords = [
                        "待办", "提醒", "改为", "修改提醒", "取消提醒", "删除提醒",
                        "分钟后", "小时后", "发到", "task_", "todo", "remind",
                    ]
                    lower_user_input = str(user_input or "").lower()
                    is_todo_request = any(k.lower() in lower_user_input for k in todo_keywords)
                    allow_tool_routing = is_todo_request
                    # 幂等保护：若前序步骤已有待办执行证据，pass_to_main_agent 只负责总结，不再二次执行工具路由。
                    if allow_tool_routing and collected_info and self._has_todo_execution_evidence(collected_info):
                        allow_tool_routing = False
                        print("    🛡️ 检测到前序已执行待办操作，pass_to_main_agent 仅总结，跳过二次工具执行")
                    suppress_tool_routing = not allow_tool_routing
                    if allow_tool_routing:
                        print("    🗓️ 检测到待办/提醒请求，pass_to_main_agent 放开工具路由以执行真实任务")
                    regenerating = bool(
                        getattr(self.base_agent, "_regeneration_mode", False)
                    )
                    skip_nested_history = combined_active or regenerating
                    skip_nested_memory = (
                        combined_active or is_todo_request or regenerating
                    )
                    if collected_info:
                        # 将所有步骤结果汇总，每步最多2000字符
                        context_parts = []
                        for idx, key in enumerate(sorted(collected_info.keys())):
                            step_result = collected_info[key]
                            # 限制每步长度，避免上下文过长
                            max_length = 2000 if len(collected_info) > 1 else 5000  # 单步任务可以更长
                            if len(step_result) > max_length:
                                step_result = step_result[:max_length] + "..."
                            context_parts.append(f"【步骤 {idx+1}】\n{step_result}")
                        
                        full_context = "\n\n".join(context_parts)
                        self.base_agent.framework_context = f"框架执行结果：\n{full_context}"
                        print(f"📋 [传递上下文] 已将 {len(collected_info)} 步结果传递给主Agent（总长度: {len(full_context)} 字符）")
                    
                    final_answer = self.base_agent.process_command(
                        user_input,
                        skip_framework=True,
                        suppress_tool_routing=suppress_tool_routing,
                        skip_memory_save=skip_nested_memory,
                        skip_history_append=skip_nested_history,
                        stream_callback=getattr(self, "_current_stream_callback", None),
                    )
                    # 结果一致性守卫：待办场景无 task_id 证据时，不允许返回“已设置成功”类文案
                    if collected_info:
                        lower_answer = str(final_answer or "").lower()
                        success_claim = any(x in lower_answer for x in ["已设置", "设置提醒", "已为您设置", "设置成功"])
                        if success_claim and not self._has_todo_success_evidence(collected_info):
                            print("    🛡️ 检测到无证据成功文案，回退为执行结果原文")
                            latest = str(collected_info.get(sorted(collected_info.keys())[-1], "")).strip()
                            if latest:
                                return latest
                    return final_answer
                finally:
                    if not combined_active:
                        self.base_agent.config["enable_web_search"] = original_search_flag
            
            else:
                return f"未知操作：{action}"
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"执行失败：{str(e)}"
    
    def _should_adjust_framework(self, user_input: str, collected_info: Dict, remaining_steps: List, current_step_result: str = "") -> bool:
        """
        判断是否需要调整框架
        
        Args:
            user_input: 用户输入
            collected_info: 已收集的信息
            remaining_steps: 剩余步骤
            current_step_result: 当前步骤的执行结果
            
        Returns:
            是否需要调整
        """
        # 🔒 如果HexStrike AI已经规划或执行了攻击链，不允许调整其规划步骤
        has_hexstrike_planning = any(
            s.get("action") in ["use_hexstrike_intelligence", "execute_hexstrike_attack_chain"]
            for s in self.completed_steps
        )
        if has_hexstrike_planning:
            # HexStrike AI已规划或执行，不允许调整
            return False
        
        # 检查最后一步是否失败
        if self.completed_steps:
            last_result = self.completed_steps[-1].get("result", "")
            # 如果最后一步失败（包含"失败"、"错误"等关键词），需要调整
            if any(keyword in last_result for keyword in ["失败", "错误", "❌", "无法", "不存在"]):
                return True
        
        # 如果已完成步骤超过5步，检查一次
        if len(self.completed_steps) == 5:
            return True
        return False
    
    def _adjust_framework(self, user_input: str, collected_info: Dict, remaining_steps: List, current_step_result: str = "") -> List[Dict]:
        """
        调整执行框架
        
        Args:
            user_input: 用户输入
            collected_info: 已收集的信息
            remaining_steps: 原剩余步骤
            current_step_result: 当前步骤的执行结果
            
        Returns:
            新的步骤列表
        """
        # 🔒 如果HexStrike AI已经规划或执行了攻击链，不允许调整其规划步骤
        has_hexstrike_planning = any(
            s.get("action") in ["use_hexstrike_intelligence", "execute_hexstrike_attack_chain"]
            for s in self.completed_steps
        )
        if has_hexstrike_planning:
            # HexStrike AI已规划或执行，不允许调整，只返回原剩余步骤
            return remaining_steps
        
        # 检查已完成步骤中是否有HexStrike AI规划
        has_hexstrike_planning = any(
            s.get("action") == "use_hexstrike_intelligence" 
            for s in self.completed_steps
        )
        
        if has_hexstrike_planning:
            # HexStrike AI已经规划过，只允许添加传递步骤，不允许调整攻击步骤
            # 如果剩余步骤中已经有pass_to_main_agent，就不需要调整
            if any(s.get("action") == "pass_to_main_agent" for s in remaining_steps):
                return remaining_steps  # 不调整，保持原样
            else:
                # 只添加传递步骤，不调整其他步骤
                return remaining_steps + [
                    {
                        "description": "将HexStrike AI规划结果传递给主Agent",
                        "action": "pass_to_main_agent",
                        "params": {}
                    }
                ]
        prompt = f"""你是任务规划专家，需要根据当前进展调整执行框架。

**必须继续遵守**下列规划上下文（意图识别与能力开关），禁止与它们矛盾；禁止新增 analyze_screen（读屏由框架外自动处理）。

{getattr(self, "_last_planner_context", "") or self._format_capability_hint()}

原始用户请求：{user_input}

已完成的步骤：
{self._format_completed_steps()}

已收集的信息：
{json.dumps(collected_info, ensure_ascii=False, indent=2)}

原计划的剩余步骤：
{json.dumps(remaining_steps, ensure_ascii=False, indent=2)}

若某步失败因 HexStrike/Kali 未启用或工具不存在，应改为 pass_to_main_agent 说明原因，勿重复安排相同失败步骤。
返回 JSON 数组（description、action、params）。若无需调整，返回原剩余步骤。
"""
        
        try:
            response = self._call_plan_llm(
                "你是任务规划专家，根据进展调整执行计划。",
                prompt,
            )
        except Exception as e:
            print(f"❌ API调用失败: {e}")
            return remaining_steps
        
        try:
            response = response.strip()
            if response.startswith("```json"):
                response = response[7:]
            if response.startswith("```"):
                response = response[3:]
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()
            
            return json.loads(response)
        except:
            return remaining_steps
    
    def _format_completed_steps(self) -> str:
        """格式化已完成的步骤"""
        if not self.completed_steps:
            return "（暂无）"
        
        lines = []
        for step in self.completed_steps:
            lines.append(f"[第 {step['step']} 步] {step['description']}")
        return "\n".join(lines)
    
    def _generate_final_answer(self, user_input: str, collected_info: Dict) -> str:
        """
        生成最终答案 - 框架Agent只负责协调，不负责回答
        
        Args:
            user_input: 用户输入
            collected_info: 收集的所有信息
            
        Returns:
            最终回答
        """
        # 检查最后一步是否已经是回答或传递给主Agent
        if self.completed_steps:
            last_step = self.completed_steps[-1]
            last_action = last_step.get("action", "")  # 🔥 改为检查action而非description
            
            # 🔥 如果最后一步的action是pass_to_main_agent，说明已经调用过主Agent
            if last_action == "pass_to_main_agent":
                # 最后一步已经完成回答，直接返回
                print("✅ 最后一步已是pass_to_main_agent，直接返回结果，不再重复调用")
                return last_step["result"]
        
            # 兼容旧的检查方式
            last_description = last_step.get("description", "").lower()
            if any(keyword in last_description for keyword in ["answer", "回答", "主agent", "传递"]):
                print("✅ 最后一步包含回答关键词，直接返回结果")
                return last_step["result"]
        
        # 如果最后一步不是pass_to_main_agent，强制调用主Agent处理
        print("⚠️ 框架未以pass_to_main_agent结束，强制调用主Agent处理")
        
        # 将框架执行结果注入到主Agent的上下文中
        context_summary = "\n\n".join([
            f"【步骤 {step['step']}】{step['description']}\n{step['result'][:500]}" 
            for step in self.completed_steps
        ])
        
        self.base_agent.framework_context = f"框架执行结果：\n{context_summary}"
        
        # 调用主Agent，让它基于框架执行结果生成回答
        return self.base_agent.process_command(user_input, skip_framework=True, suppress_tool_routing=True)
    
    def _is_security_test_task(self, user_input: str) -> bool:
        """
        检测是否是安全测试任务（不依赖关键词，直接判断）
        
        Args:
            user_input: 用户输入
            
        Returns:
            是否是安全测试任务
        """
        # 不依赖关键词，直接检查是否有HexStrike AI可用
        # 如果有HexStrike AI可用，且用户输入包含目标（URL、IP、域名），就认为是安全测试任务
        try:
            mcp_server = self.base_agent.mcp_tools.server
            if not hasattr(mcp_server, 'hexstrike_mcp_client') or not mcp_server.hexstrike_mcp_client:
                return False
            
            # 检查是否包含目标（URL、IP、域名）
            import re
            url_pattern = r'https?://[^\s]+'
            ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
            domain_pattern = r'\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}\b'
            
            has_target = (
                re.search(url_pattern, user_input) or
                re.search(ip_pattern, user_input) or
                re.search(domain_pattern, user_input)
            )
            
            # 如果包含目标，且HexStrike AI可用，就认为是安全测试任务
            return has_target and mcp_server.hexstrike_mcp_client.is_available()
        except:
            return False
    
    def _create_hexstrike_intelligence_framework(self, user_input: str) -> List[Dict[str, Any]]:
        """
        创建使用HexStrike AI智能规划的框架（直接传递用户请求，不依赖关键词）
        
        Args:
            user_input: 用户输入
            
        Returns:
            框架列表
        """
        print("🔍 [目标提取] 开始从用户输入中提取目标...")
        # 从用户输入中提取目标（URL、IP或域名），保留中文部分并翻译成英文
        import re
        
        # 先提取完整目标（包括中文部分）
        # URL模式：匹配http(s)://开头，到空格或行尾
        url_pattern = r'https?://[^\s]+'
        ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
        domain_pattern = r'\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}\b'
        
        target = None
        url_match = re.search(url_pattern, user_input)
        if url_match:
            # 提取完整URL（包括后面的中文）
            url_start = url_match.start()
            # 找到URL后的中文部分（直到遇到空格或标点）
            url_end = url_match.end()
            # 继续匹配后面的中文字符和标点
            remaining = user_input[url_end:]
            chinese_part = ""
            for char in remaining:
                if char.isspace():
                    break
                if '\u4e00' <= char <= '\u9fff' or char in '，。！？、；：':
                    chinese_part += char
            target = user_input[url_start:url_end] + chinese_part
        else:
            ip_match = re.search(ip_pattern, user_input)
            if ip_match:
                target = ip_match.group(0)
            else:
                domain_match = re.search(domain_pattern, user_input)
                if domain_match:
                    target = domain_match.group(0)
        
        # 如果没有找到明确目标，将整个用户输入作为目标
        if not target:
            target = user_input
            print(f"⚠️ [目标提取] 未找到明确目标，使用整个用户输入作为目标")
        else:
            print(f"✅ [目标提取] 已提取目标: {target}")
        
        # 构建objective，如果目标包含中文，在objective中说明需要翻译
        # 让HexStrike AI自己处理翻译（通过提示词）
        if re.search(r'[\u4e00-\u9fff]', target):
            # 目标包含中文，在objective中说明需要翻译目标中的中文部分
            objective = f"{user_input}\n\nNote: The target contains Chinese characters. Please translate the Chinese part to English while keeping URLs/IPs/domains unchanged. For example, if the target is 'https://example.com的HTML源码', translate it to 'https://example.com HTML source code'."
            print(f"🌐 [目标处理] 目标包含中文，已添加翻译说明")
        else:
            objective = user_input
        
        print(f"📋 [框架构建] 构建HexStrike AI智能规划框架...")
        print(f"   - 目标: {target}")
        print(f"   - 任务描述: {objective[:100]}...")
        
        # 直接使用 execute-attack-chain，让HexStrike AI规划并执行攻击链，然后返回执行报告
        # 将用户输入作为objective传递给HexStrike AI，让它理解任务意图
        framework = [
            {
                "description": "启动HexStrike AI服务器",
                "action": "start_hexstrike_ai",
                "params": {}
            },
            {
                "description": "使用HexStrike AI执行攻击链（规划并执行，返回执行报告）",
                "action": "execute_hexstrike_attack_chain",
                "params": {
                    "target": target,  # 保留原始目标（包含中文）
                    "objective": objective  # 在objective中说明需要翻译
                }
            },
            {
                "description": "将HexStrike AI执行报告传递给主Agent",
                "action": "pass_to_main_agent",
                "params": {}
            }
        ]
        
        return framework


# 被直接运行时仅做加载测试，不启动 GUI
if __name__ == "__main__":
    print("框架ReAct Agent模块加载成功")
    print("请运行 main.py 启动露尼西亚助手。")

