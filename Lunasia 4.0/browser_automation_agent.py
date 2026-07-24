#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
浏览器自动化Agent - 基于ReAct推理循环
支持复杂的多步骤网页操作
"""

import openai
import json
from typing import Dict, Any, List, Optional
from playwright.async_api import Page, Browser, BrowserContext


class BrowserAutomationAgent:
    """
    基于ReAct推理循环的浏览器自动化Agent
    
    架构：
    1. Thought（思考）：分析当前状态，决定下一步操作
    2. Action（行动）：执行具体的浏览器操作
    3. Observation（观察）：获取操作结果
    4. Loop（循环）：继续思考直到任务完成
    """
    
    def __init__(self, config: Dict[str, Any], page: Page):
        """
        初始化浏览器自动化Agent
        
        Args:
            config: 配置字典
            page: Playwright Page对象
        """
        self.config = config
        self.page = page
        self.history: List[Dict[str, str]] = []  # 推理历史
        self.max_steps = 15  # 最大推理步数
        
    async def execute_task(self, user_task: str) -> Dict[str, Any]:
        """
        执行用户任务（ReAct推理循环）
        
        Args:
            user_task: 用户任务描述，如"打开B站并搜索java"
            
        Returns:
            执行结果
        """
        print(f"🤖 [BrowserAgent] 开始执行任务: {user_task}")
        
        self.history = []
        current_url = self.page.url
        
        for step in range(self.max_steps):
            print(f"\n{'='*60}")
            print(f"📍 Step {step + 1}/{self.max_steps}")
            print(f"{'='*60}")
            
            # 1️⃣ Thought（思考）
            thought = await self._think(user_task, current_url)
            print(f"💭 Thought: {thought['reasoning']}")
            
            if thought['is_complete']:
                print(f"✅ 任务完成！")
                return {
                    "success": True,
                    "message": "任务执行成功",
                    "steps": len(self.history),
                    "history": self.history
                }
            
            # 2️⃣ Action（行动）
            action = thought['next_action']
            print(f"🎬 Action: {action['type']} - {action.get('description', '')}")
            
            # 3️⃣ Execute & Observe（执行并观察）
            observation = await self._execute_action(action)
            print(f"👁️ Observation: {observation}")
            
            # 记录到历史
            self.history.append({
                "step": step + 1,
                "thought": thought['reasoning'],
                "action": action,
                "observation": observation
            })
            
            # 更新当前URL
            current_url = self.page.url
            
            # 如果观察到失败，尝试重新思考
            if "失败" in observation or "未找到" in observation:
                print(f"⚠️ 操作遇到问题，将在下一步重新思考策略")
        
        # 达到最大步数仍未完成
        return {
            "success": False,
            "message": f"达到最大推理步数({self.max_steps})，任务未完成",
            "steps": len(self.history),
            "history": self.history
        }
    
    async def _think(self, user_task: str, current_url: str) -> Dict[str, Any]:
        """
        思考下一步应该做什么
        
        Args:
            user_task: 用户任务
            current_url: 当前页面URL
            
        Returns:
            {
                "reasoning": "思考过程",
                "is_complete": bool,
                "next_action": {
                    "type": "navigate/find_element/click/fill/scroll/wait",
                    "target": "操作目标",
                    ...
                }
            }
        """
        try:
            from llm_router import chat_completion, resolve_client

            if not resolve_client(self.config, config_key="webpage_agent_model"):
                print("⚠️ 没有可用模型")
                return {
                    "reasoning": "无可用模型",
                    "is_complete": True,
                    "next_action": {}
                }
            
            # 构建历史记录字符串
            history_str = ""
            for h in self.history[-5:]:  # 只保留最近5步
                history_str += f"\nStep {h['step']}:\n"
                history_str += f"  Thought: {h['thought']}\n"
                history_str += f"  Action: {h['action']}\n"
                history_str += f"  Observation: {h['observation']}\n"
            
            prompt = f"""你是一个浏览器自动化专家，使用ReAct推理模式完成任务。

**用户任务**: {user_task}

**当前状态**:
- 当前URL: {current_url}
- 已执行步数: {len(self.history)}

**历史记录**:
{history_str if history_str else "（暂无历史）"}

**可用操作**:
1. navigate: 导航到URL
   {{"type": "navigate", "url": "https://example.com"}}

2. find_element: 查找页面元素（用于验证）
   {{"type": "find_element", "selector": "input[type='search']", "description": "搜索框"}}

3. click: 点击元素
   {{"type": "click", "text": "登录"}}  # 通过文本查找
   {{"type": "click", "selector": ".login-btn"}}  # 通过选择器

4. fill: 填写输入框
   {{"type": "fill", "selector": "input[type='search']", "text": "java"}}

5. scroll: 滚动页面
   {{"type": "scroll", "direction": "down"}}

6. wait: 等待页面加载
   {{"type": "wait", "seconds": 2}}

**思考规则**:
1. 分析当前状态和任务目标
2. 判断任务是否已完成
3. 如果未完成，决定下一步最合适的操作
4. 一次只执行一个操作

**返回JSON格式**:
{{
    "reasoning": "思考过程（中文）",
    "is_complete": false,
    "next_action": {{
        "type": "操作类型",
        ...其他参数
    }}
}}

如果任务已完成，返回:
{{
    "reasoning": "任务已完成",
    "is_complete": true,
    "next_action": {{}}
}}

只返回JSON，不要其他内容。
"""
            
            result_text = chat_completion(
                self.config,
                config_key="webpage_agent_model",
                messages=[
                    {"role": "system", "content": "你是一个浏览器自动化专家，使用ReAct推理模式逐步完成任务。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=300,
                temperature=0.1,
                timeout=15,
                task_label="browser_automation",
            ) or ""
            
            # 清理markdown代码块
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()
            
            result = json.loads(result_text)
            return result
            
        except Exception as e:
            print(f"❌ 思考失败: {str(e)}")
            return {
                "reasoning": f"思考失败: {str(e)}",
                "is_complete": True,
                "next_action": {}
            }
    
    async def _execute_action(self, action: Dict[str, Any]) -> str:
        """
        执行具体操作并返回观察结果
        
        Args:
            action: 操作字典
            
        Returns:
            观察结果字符串
        """
        action_type = action.get("type", "")
        
        try:
            if action_type == "navigate":
                url = action.get("url", "")
                await self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await self.page.wait_for_timeout(1000)
                return f"已导航到 {url}"
            
            elif action_type == "find_element":
                selector = action.get("selector", "")
                element = await self.page.query_selector(selector)
                if element:
                    is_visible = await element.is_visible()
                    return f"找到元素 {selector}，可见性: {is_visible}"
                else:
                    return f"未找到元素 {selector}"
            
            elif action_type == "click":
                # 支持通过文本或选择器点击
                text = action.get("text")
                selector = action.get("selector")
                
                if text:
                    # 通过文本查找
                    element = await self.page.get_by_text(text).first
                    if element:
                        await element.scroll_into_view_if_needed()
                        await self.page.wait_for_timeout(300)
                        await element.click(force=True)
                        return f"已点击「{text}」"
                    else:
                        return f"未找到包含文本「{text}」的元素"
                
                elif selector:
                    element = await self.page.query_selector(selector)
                    if element:
                        await element.scroll_into_view_if_needed()
                        await self.page.wait_for_timeout(300)
                        await element.click()
                        return f"已点击元素 {selector}"
                    else:
                        return f"未找到元素 {selector}"
                
                return "点击操作缺少text或selector参数"
            
            elif action_type == "fill":
                selector = action.get("selector", "")
                text = action.get("text", "")
                
                element = await self.page.query_selector(selector)
                if element:
                    await element.scroll_into_view_if_needed()
                    await element.fill(text)
                    return f"已在 {selector} 填写「{text}」"
                else:
                    return f"未找到输入框 {selector}"
            
            elif action_type == "scroll":
                direction = action.get("direction", "down")
                if direction == "down":
                    await self.page.evaluate("window.scrollBy(0, 500)")
                elif direction == "up":
                    await self.page.evaluate("window.scrollBy(0, -500)")
                elif direction == "top":
                    await self.page.evaluate("window.scrollTo(0, 0)")
                elif direction == "bottom":
                    await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                
                return f"已滚动: {direction}"
            
            elif action_type == "wait":
                seconds = action.get("seconds", 1)
                await self.page.wait_for_timeout(int(seconds * 1000))
                return f"已等待 {seconds} 秒"
            
            else:
                return f"未知操作类型: {action_type}"
        
        except Exception as e:
            return f"操作失败: {str(e)}"

