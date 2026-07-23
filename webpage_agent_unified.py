#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
统一网页操作Agent - 集成ReAct推理能力
支持从简单的单步操作到复杂的多步推理
"""

import openai
import json
import asyncio
from typing import Dict, Any, Optional, List
from playwright.async_api import Page, Browser, BrowserContext, async_playwright
from utils import open_website


def get_or_create_event_loop():
    """获取或创建事件循环"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("Loop is closed")
        return loop
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


class UnifiedWebpageAgent:
    """
    统一的网页操作Agent
    
    架构特点：
    1. 自动判断任务复杂度
    2. 简单任务：1步ReAct推理即完成
    3. 复杂任务：多步ReAct推理循环
    4. 统一的推理接口，无需两个Agent
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化统一网页操作Agent
        
        Args:
            config: 配置字典
        """
        self.config = config
        self.max_steps = 30  # 最大推理步数（从15增加到30）
        self.history: List[Dict[str, Any]] = []
        self.estimated_remaining_steps = 5  # AI估计的剩余步数
    
    async def execute_webpage_task(
        self,
        user_input: str,
        url: str = "",
        browser_type: str = "edge",
        mode: str = "launch",
        slow_mo: int = 0,
        cdp_url: str = "http://localhost:9222",
        user_data_dir: str = ""
    ) -> Dict[str, Any]:
        """
        执行网页任务（统一入口）
        
        Args:
            user_input: 用户原始输入（如"打开B站并搜索java"）
            url: 目标URL（如果已知）
            browser_type: 浏览器类型
            mode: Playwright模式
            slow_mo: 慢速延迟
            cdp_url: CDP地址
            user_data_dir: 用户数据目录
            
        Returns:
            执行结果
        """
        print(f"🤖 [UnifiedWebpageAgent] 开始执行任务: {user_input}")
        
        # 重置历史
        self.history = []
        
        # 1️⃣ 快速判断：是否为简单的"只打开网站"
        # 注意：如果是connect模式，不降级到系统浏览器，统一在调试浏览器中处理
        if self._is_simple_navigate(user_input) and mode != "connect":
            print(f"📌 [UnifiedWebpageAgent] 检测到简单打开操作，使用系统浏览器")
            result = open_website(url, browser_type)
            return {
                "success": True,
                "message": result,
                "title": url,
                "url": url,
                "mode": "simple_navigate"
            }
        elif self._is_simple_navigate(user_input) and mode == "connect":
            print(f"📌 [UnifiedWebpageAgent] connect模式，在调试浏览器中打开")
        
        # 2️⃣ 需要自动化操作，启动Playwright
        print(f"🤖 [UnifiedWebpageAgent] 检测到自动化需求，启动Playwright")
        
        playwright = None
        browser = None
        context = None
        page = None
        
        try:
            # 启动Playwright并打开页面
            playwright = await async_playwright().start()
            browser_type_lower = browser_type.lower() if browser_type else "chromium"
            
            # 选择浏览器引擎
            if browser_type_lower in ["edge", "chrome", "chromium"]:
                browser_engine = playwright.chromium
            elif browser_type_lower == "firefox":
                browser_engine = playwright.firefox
            elif browser_type_lower == "webkit":
                browser_engine = playwright.webkit
            else:
                browser_engine = playwright.chromium
            
            # 根据模式启动
            if mode == "connect":
                print(f"🔌 连接到已运行的浏览器: {cdp_url}")
                browser = await playwright.chromium.connect_over_cdp(cdp_url)
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                
                # ⚠️ 重要：创建新标签页，避免干扰其他页面
                page = await context.new_page()
                print(f"✅ 已创建新标签页用于自动化操作")
            else:
                print(f"🚀 启动新浏览器")
                launch_args = {"headless": False, "slow_mo": slow_mo}
                if browser_type_lower == "edge":
                    launch_args["channel"] = "msedge"
                elif browser_type_lower == "chrome":
                    launch_args["channel"] = "chrome"
                
                browser = await browser_engine.launch(**launch_args)
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = await context.new_page()
            
            # 3️⃣ 开始ReAct推理循环
            result = await self._react_loop(user_input, url, page)
            
            return result
            
        except Exception as e:
            print(f"❌ [UnifiedWebpageAgent] 执行失败: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "mode": "react_failed"
            }
    
    def _is_simple_navigate(self, user_input: str) -> bool:
        """
        判断是否为简单的打开网站操作（无需自动化）
        
        Args:
            user_input: 用户输入
            
        Returns:
            是否为简单打开
        """
        # 关键词判断
        automation_keywords = ["搜索", "点击", "点开", "点进", "输入", "填写", "滚动", "下拉"]
        
        for keyword in automation_keywords:
            if keyword in user_input:
                return False  # 包含自动化关键词，不是简单打开
        
        return True  # 纯粹的"打开XX"
    
    async def _react_loop(self, user_task: str, initial_url: str, page: Page) -> Dict[str, Any]:
        """
        ReAct推理循环
        
        Args:
            user_task: 用户任务
            initial_url: 初始URL
            page: Playwright Page对象
            
        Returns:
            执行结果
        """
        current_url = initial_url
        
        for step in range(self.max_steps):
            # 显示进度（包含AI估计的剩余步数）
            if self.estimated_remaining_steps > 0:
                progress_info = f"第 {step + 1} 步，预计还需 {self.estimated_remaining_steps} 步"
            else:
                progress_info = f"第 {step + 1} 步（最多{self.max_steps}步）"
            
            print(f"\n{'='*60}")
            print(f"🧠 [露尼西亚推理] {progress_info}")
            print(f"{'='*60}")
            
            # 1️⃣ Thought（思考）
            print(f"💭 [思考中] 正在分析当前状态...")
            thought = await self._think(user_task, page.url if step > 0 else current_url, page)
            print(f"💭 [思考结果] {thought['reasoning']}")
            
            # 更新估计的剩余步数
            if 'estimated_remaining_steps' in thought:
                self.estimated_remaining_steps = thought['estimated_remaining_steps']
                print(f"📊 [进度估计] AI预计还需 {self.estimated_remaining_steps} 步完成")
            
            if thought['is_complete']:
                print(f"\n{'='*60}")
                print(f"✅ [任务完成] 露尼西亚成功完成了所有操作！")
                print(f"📊 [统计] 共执行了 {len(self.history)} 步推理")
                
                # 检查是否有次优方案说明
                reasoning = thought.get('reasoning', '')
                if any(keyword in reasoning for keyword in ['无法精确', '次优方案', '推荐', '无法确认']):
                    print(f"💡 [说明] {reasoning}")
                    message = f"已完成网页操作（{len(self.history)}步推理）。{reasoning}"
                else:
                    message = f"已完成所有网页自动化操作（AI推理{len(self.history)}步）"
                
                print(f"{'='*60}\n")
                return {
                    "success": True,
                    "message": message,
                    "title": await page.title(),
                    "url": page.url,
                    "mode": "react",
                    "steps": len(self.history),
                    "history": self.history,
                    "action_success": True
                }
            
            # 2️⃣ Action（行动）
            action = thought['next_action']
            action_desc = action.get('description', action.get('type', '未知操作'))
            print(f"🎬 [执行操作] {action_desc}")
            
            # 3️⃣ Execute & Observe（执行并观察）
            observation = await self._execute_action(action, page)
            
            # 🔍 检查是否有新标签页打开（点击视频后常见情况）
            context = page.context
            if len(context.pages) > 1:
                # 切换到最新的标签页
                page = context.pages[-1]
                await page.bring_to_front()
                print(f"    🔄 检测到新标签页，已自动切换（共{len(context.pages)}个标签）")
            
            # 根据观察结果显示不同的提示
            if "✅" in observation or "已" in observation:
                print(f"👁️ [观察结果] {observation}")
            elif "⚠️" in observation or "未找到" in observation:
                print(f"⚠️ [观察结果] {observation}")
                print(f"💡 [提示] 露尼西亚将在下一步重新思考策略...")
            else:
                print(f"👁️ [观察结果] {observation}")
            
            # 记录到历史
            self.history.append({
                "step": step + 1,
                "thought": thought['reasoning'],
                "action": action,
                "observation": observation
            })
            
            # 🚨 死循环检测：如果连续5步都是wait操作，强制停止
            if len(self.history) >= 5:
                recent_actions = [h['action'].get('type') for h in self.history[-5:]]
                if recent_actions.count('wait') >= 4:
                    print(f"\n{'='*60}")
                    print(f"⚠️ [死循环检测] 检测到连续多次wait操作")
                    print(f"💡 [提示] AI可能陷入死循环，建议使用get_page_info获取页面信息")
                    print(f"{'='*60}\n")
            
            # 如果观察到严重错误，提前终止
            if "严重错误" in observation or "无法继续" in observation:
                print(f"\n{'='*60}")
                print(f"❌ [任务失败] 遇到无法解决的错误")
                print(f"📊 [统计] 已执行 {len(self.history)} 步")
                print(f"{'='*60}\n")
                return {
                    "success": True,  # 网页已打开，但操作未完成
                    "message": f"已打开网页，但自动化操作遇到问题: {observation}",
                    "title": await page.title(),
                    "url": page.url,
                    "mode": "react",
                    "steps": len(self.history),
                    "history": self.history,
                    "action_success": False,
                    "action_error": observation
                }
        
        # 达到最大步数
        return {
            "success": False,
            "message": f"达到最大推理步数({self.max_steps})，任务未完成",
            "title": await page.title(),
            "url": page.url,
            "mode": "react",
            "steps": len(self.history),
            "history": self.history
        }
    
    async def _think(self, user_task: str, current_url: str, page: Page) -> Dict[str, Any]:
        """
        思考下一步应该做什么
        
        Args:
            user_task: 用户任务
            current_url: 当前URL
            page: Page对象
            
        Returns:
            思考结果
        """
        try:
            from llm_router import chat_completion, resolve_client

            if not resolve_client(self.config, config_key="webpage_agent_model"):
                return {
                    "reasoning": "无可用模型",
                    "is_complete": True,
                    "next_action": {}
                }
            
            # 构建历史记录
            history_str = ""
            for h in self.history[-5:]:
                history_str += f"\nStep {h['step']}:\n"
                history_str += f"  思考: {h['thought']}\n"
                history_str += f"  行动: {h['action'].get('type')} - {h['action'].get('description', '')}\n"
                history_str += f"  观察: {h['observation']}\n"
            
            # 获取页面信息
            try:
                page_title = await page.title()
            except:
                page_title = "未知"
            
            prompt = f"""你是网页自动化专家，使用ReAct推理完成任务。

**用户任务**: {user_task}

**当前状态**:
- 当前URL: {current_url}
- 页面标题: {page_title}
- 已执行步数: {len(self.history)}

**历史记录**:
{history_str if history_str else "（这是第一步）"}

**可用操作**:
1. navigate: 导航到URL
   {{"type": "navigate", "url": "https://example.com", "description": "打开网站"}}

2. click_text: 通过文本点击
   {{"type": "click_text", "text": "登录", "description": "点击登录按钮"}}
   {{"type": "click_text", "text": "第一个视频", "description": "点击第一个视频"}}

3. click_selector: 通过选择器点击
   {{"type": "click_selector", "selector": ".login-btn", "description": "点击登录按钮"}}

4. fill: 填写输入框
   {{"type": "fill", "selector": "input[type='search']", "text": "java", "description": "在搜索框输入java"}}

5. press_key: 按键
   {{"type": "press_key", "selector": "input", "key": "Enter", "description": "按回车提交"}}

6. scroll: 滚动页面
   {{"type": "scroll", "direction": "down", "description": "向下滚动"}}

7. wait: 等待
   {{"type": "wait", "seconds": 2, "description": "等待页面加载"}}

8. get_page_info: 获取页面信息（重要！用于判断任务是否完成）
   {{"type": "get_page_info", "description": "获取当前页面的标题和URL"}}
   返回：当前页面标题、URL等信息，帮助你判断任务状态

9. get_text: 获取元素文本内容
   {{"type": "get_text", "selector": ".view-count", "description": "获取播放量数字"}}
   返回：元素的文本内容，用于判断播放量等信息

**关键推理规则**:
1. **完整分析用户任务**：仔细看用户要求做哪些事（可能有多个步骤）
2. **逐步执行**：一次只做一件事，不要跳步
3. **判断完成**：当用户要求的所有操作都完成后，才设置 is_complete=true
4. **动态步数**：根据任务复杂度自己决定需要几步（1-30步）
5. **错误恢复**：如果操作失败，思考替代方案
6. **⚠️ 严格遵循用户要求**：
   - 如果用户要搜索"java教程"，就搜索"java教程"，不要搜索"emo歌曲"或其他无关内容
   - 如果用户要"播放量最高"，不要简单点击第一个（可能只有100播放量）
   - 必须保证搜索关键词和用户要求完全一致

**多步任务示例**:

任务："打开B站，搜索java教程，点开播放量最高的"
分析：这个任务包含3个子任务：
  ① 确保在B站
  ② 搜索"java教程"（注意：必须搜索"java教程"，不能搜索其他无关内容）
  ③ 点击播放量最高的视频

第1步 - 当前URL: bilibili.com, 历史:无
  思考: "我在B站首页，用户要我搜索java教程，第一步是填写搜索框"
  行动: {{"type": "fill", "selector": "input", "text": "java教程"}}

第2步 - 观察: "已填写java教程"
  思考: "已填写内容，现在按回车提交搜索"
  行动: {{"type": "press_key", "selector": "input", "key": "Enter"}}

第3步 - 观察: "已按下Enter"
  思考: "搜索已提交，等待结果加载"
  行动: {{"type": "wait", "seconds": 2}}

第4步 - 观察: "已等待2秒"
  思考: "搜索结果应该加载了。用户要求'播放量最高'，B站默认是综合排序，我应该点击排序选项改为'播放量排序'，或者至少滚动浏览几个视频，选择播放量明显最高的"
  行动: {{"type": "scroll", "direction": "down", "description": "滚动查看更多视频"}}

第5步 - 观察: "已滚动"
  思考: "现在点击第一个视频。虽然不能保证是播放量最高，但通常综合排序的前几个播放量都很高"
  行动: {{"type": "click_text", "text": "第一个视频"}}

第6步 - 观察: "已点击第一个视频"
  思考: "视频可能正在加载，使用get_page_info确认页面状态"
  行动: {{"type": "get_page_info"}}

第7步 - 观察: "✅ 页面信息 - 标题:「java教程...」, URL: bilibili.com/video/BV..."
  思考: "确认已进入视频页面，所有任务都完成了：✓搜索java教程 ✓点击视频"
  完成: {{"is_complete": true}}

**重要提醒 - 次优方案策略**：
- 搜索时必须填写用户要求的关键词（如"java教程"），不要搜索其他无关内容
- ⚠️ 避免死循环：不要重复执行相同的操作（如连续多次wait、get_page_info）
- 使用 get_page_info 来判断当前页面状态，而不是盲目等待

**🎯 次优方案原则**（重要！避免死循环）：
1. 如果某个特定要求（如"播放量最高"、"评分最高"等）尝试2-3次后仍失败：
   - ✅ 立即接受次优方案（如点击第一个/前几个）
   - ✅ 完成基本任务（搜索+打开内容）
   - ✅ 设置 is_complete=true
   - ✅ 在 reasoning 中诚实说明：
     "无法精确找到XX，但已为您推荐并打开了一个相关内容"

2. ⚠️ 特别注意：
   - 点击视频/链接后，如果get_page_info显示URL未变，可能是：
     a) 新标签页已打开（你在旧标签）
     b) 已成功但页面未刷新
   - 此时不要重复点击！应该：
     a) 使用wait等待页面跳转
     b) 或者直接判断任务完成（采用次优方案）

3. 示例（改进版）：
   任务："打开B站，搜索java教程，点开播放量最高的"
   
   Step N: 尝试播放量排序失败2次
   思考: "播放量排序找不到，采用次优方案：综合排序的第一个视频通常播放量也很高"
   行动: click_text("第一个视频")
   
   Step N+1: 观察: "已点击第一个视频"
   思考: "已点击视频链接，等待页面跳转"
   行动: wait(2秒)
   
   Step N+2: 观察: "已等待2秒"
   思考: "点击后已等待，无论页面是否跳转，基本任务已完成（搜索+点击视频）。采用次优方案。"
   返回: {{
     "is_complete": true, 
     "reasoning": "无法精确确认是否为播放量最高的视频，但已为您搜索并打开了一个java教程视频"
   }}

**返回JSON格式**:
{{
    "reasoning": "我的思考（简洁明了）",
    "is_complete": false,  // 任务是否全部完成
    "estimated_remaining_steps": 3,  // 估计还需要多少步（1-30，可选但建议填写）
    "next_action": {{
        "type": "操作类型",
        "description": "操作描述",
        ...其他参数
    }}
}}

**estimated_remaining_steps说明**:
- 估计还需要多少步完成任务
- 帮助用户了解进度
- 示例：如果你觉得还需要3步就完成，填3

只返回JSON，不要其他内容。
"""
            
            result_text = chat_completion(
                self.config,
                config_key="webpage_agent_model",
                messages=[
                    {"role": "system", "content": "你是网页自动化专家，使用ReAct推理模式逐步完成任务。简单任务1步完成，复杂任务多步完成。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=300,
                temperature=0.1,
                timeout=15,
                task_label="webpage_agent",
            ) or ""
            
            # 清理markdown
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
    
    async def _execute_action(self, action: Dict[str, Any], page: Page) -> str:
        """
        执行具体操作并返回观察结果
        
        Args:
            action: 操作字典
            page: Page对象
            
        Returns:
            观察结果
        """
        action_type = action.get("type", "")
        
        try:
            if action_type == "navigate":
                url = action.get("url", "")
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(1000)
                title = await page.title()
                return f"✅ 已打开 {title}"
            
            elif action_type == "click_text":
                text = action.get("text", "")
                
                # 等待页面加载
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=10000)
                    await page.wait_for_timeout(1500)
                except:
                    pass
                
                # 🎯 特殊处理：第一个视频（针对B站等视频网站）
                if "第一个" in text or "第1个" in text or "第一" in text:
                    # 查找视频链接（排除直播）
                    try:
                        video_links = await page.query_selector_all('a[href*="/video/BV"]')
                        if video_links:
                            for link in video_links[:5]:
                                try:
                                    is_visible = await link.is_visible()
                                    if is_visible:
                                        href = await link.get_attribute('href')
                                        await link.scroll_into_view_if_needed()
                                        await page.wait_for_timeout(300)
                                        
                                        # 点击视频
                                        await link.click(force=True)
                                        await page.wait_for_timeout(1000)  # 等待可能的页面跳转
                                        return f"✅ 已点击第一个视频: {href[:50]}..."
                                except:
                                    continue
                    except:
                        pass
                
                # 通用文本点击
                try:
                    # XPath查找
                    xpath_selectors = [
                        f"//a[contains(text(), '{text}')]",
                        f"//button[contains(text(), '{text}')]",
                        f"//*[contains(text(), '{text}')]"
                    ]
                    
                    for xpath in xpath_selectors:
                        try:
                            element = await page.query_selector(f"xpath={xpath}")
                            if element:
                                is_visible = await element.is_visible()
                                if is_visible:
                                    await element.scroll_into_view_if_needed()
                                    await page.wait_for_timeout(300)
                                    await element.click(force=True)
                                    return f"✅ 已点击「{text}」"
                        except:
                            continue
                except:
                    pass
                
                return f"⚠️ 未找到可点击的「{text}」"
            
            elif action_type == "click_selector":
                selector = action.get("selector", "")
                element = await page.query_selector(selector)
                if element:
                    await element.scroll_into_view_if_needed()
                    await page.wait_for_timeout(300)
                    await element.click()
                    return f"✅ 已点击 {selector}"
                else:
                    return f"⚠️ 未找到 {selector}"
            
            elif action_type == "fill":
                selector = action.get("selector", "")
                text = action.get("text", "")
                
                # 🎯 智能查找输入框（尝试多个选择器）
                selectors_to_try = [
                    selector,  # AI指定的选择器
                    "input",  # 最通用的
                    "input[type='search']",
                    "input[type='text']",
                    "input[class*='search']",
                    "input[placeholder*='搜索']",
                    "input[placeholder*='Search']",
                    "textarea"
                ]
                
                for try_selector in selectors_to_try:
                    try:
                        element = await page.query_selector(try_selector)
                        if element:
                            is_visible = await element.is_visible()
                            if is_visible:
                                await element.scroll_into_view_if_needed()
                                await element.click()
                                await page.wait_for_timeout(200)
                                await element.fill(text)
                                print(f"    ✅ 使用选择器 {try_selector} 成功填写")
                                return f"✅ 已填写「{text}」"
                    except:
                        continue
                
                return f"⚠️ 未找到可用的输入框（尝试了{len(selectors_to_try)}个选择器）"
            
            elif action_type == "press_key":
                selector = action.get("selector", "")
                key = action.get("key", "Enter")
                
                # 智能查找元素（尝试多个选择器）
                selectors_to_try = [
                    selector,
                    "input",  # 最通用的
                    "input[type='search']",
                    "input[type='text']",
                    "textarea"
                ]
                
                for try_selector in selectors_to_try:
                    try:
                        element = await page.query_selector(try_selector)
                        if element:
                            await element.press(key)
                            print(f"    ✅ 使用选择器 {try_selector} 成功按键")
                            return f"✅ 已按下 {key}"
                    except:
                        continue
                
                return f"⚠️ 未找到可按键的元素"
            
            elif action_type == "scroll":
                direction = action.get("direction", "down")
                if direction == "down":
                    await page.evaluate("window.scrollBy(0, 500)")
                elif direction == "up":
                    await page.evaluate("window.scrollBy(0, -500)")
                elif direction == "top":
                    await page.evaluate("window.scrollTo(0, 0)")
                elif direction == "bottom":
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                
                return f"✅ 已滚动: {direction}"
            
            elif action_type == "wait":
                seconds = action.get("seconds", 1)
                await page.wait_for_timeout(int(seconds * 1000))
                return f"✅ 已等待 {seconds} 秒"
            
            elif action_type == "get_page_info":
                # 获取当前页面信息
                try:
                    title = await page.title()
                    url = page.url
                    return f"✅ 页面信息 - 标题:「{title}」, URL: {url}"
                except Exception as e:
                    return f"⚠️ 获取页面信息失败: {str(e)}"
            
            elif action_type == "get_text":
                # 获取元素文本内容
                selector = action.get("selector", "")
                try:
                    element = await page.query_selector(selector)
                    if element:
                        text = await element.inner_text()
                        return f"✅ 元素文本: 「{text}」"
                    else:
                        return f"⚠️ 未找到元素 {selector}"
                except Exception as e:
                    return f"⚠️ 获取文本失败: {str(e)}"
            
            else:
                return f"❌ 未知操作类型: {action_type}"
        
        except Exception as e:
            return f"❌ 操作失败: {str(e)}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 同步调用包装函数（兼容ai_agent.py的同步调用）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def execute_webpage_task_sync(
    config: Dict[str, Any],
    user_input: str,
    url: str = "",
    browser_type: str = "edge",
    mode: str = "launch",
    slow_mo: int = 0,
    cdp_url: str = "http://localhost:9222",
    user_data_dir: str = ""
) -> Dict[str, Any]:
    """
    同步方式执行网页任务（供ai_agent.py调用）
    
    Args:
        config: 配置字典
        user_input: 用户输入
        url: 目标URL
        其他参数同 execute_webpage_task
        
    Returns:
        执行结果
    """
    async def _async_wrapper():
        agent = UnifiedWebpageAgent(config)
        return await agent.execute_webpage_task(
            user_input=user_input,
            url=url,
            browser_type=browser_type,
            mode=mode,
            slow_mo=slow_mo,
            cdp_url=cdp_url,
            user_data_dir=user_data_dir
        )
    
    loop = get_or_create_event_loop()
    return loop.run_until_complete(_async_wrapper())

