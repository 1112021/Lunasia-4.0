#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Playwright 高级自动化工具
提供完整的浏览器自动化能力，包括：
- 多种浏览器启动模式（launch, persistent_context, connect_over_cdp）
- 完整的元素定位与交互
- 智能等待机制
- 用户数据持久化
"""

import asyncio
import os
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from playwright.async_api import async_playwright, Browser, Page, BrowserContext, Playwright

class PlaywrightAdvanced:
    """增强的 Playwright 自动化工具"""
    
    def __init__(self, user_data_dir: Optional[str] = None):
        """
        初始化高级自动化工具
        
        Args:
            user_data_dir: 用户数据目录（用于保存登录状态、Cookie等）
        """
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.user_data_dir = user_data_dir or str(Path.home() / ".lunesia" / "browser_data")
        
    async def launch_browser(
        self,
        browser_type: str = "chromium",
        headless: bool = False,
        slow_mo: int = 0,
        use_persistent: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        启动浏览器
        
        Args:
            browser_type: 浏览器类型 ("chromium", "firefox", "webkit", "edge", "chrome")
            headless: 是否无头模式
            slow_mo: 慢速模式延迟（毫秒），便于观察自动化过程
            use_persistent: 是否使用持久化上下文（保存登录状态）
            **kwargs: 其他浏览器启动参数
            
        Returns:
            {"success": bool, "message": str}
        """
        try:
            self.playwright = await async_playwright().start()
            
            # 选择浏览器类型
            browser_type_lower = browser_type.lower()
            if browser_type_lower == "edge":
                browser_launcher = self.playwright.chromium
                kwargs["channel"] = "msedge"
            elif browser_type_lower == "chrome":
                browser_launcher = self.playwright.chromium
                kwargs["channel"] = "chrome"
            elif browser_type_lower == "firefox":
                browser_launcher = self.playwright.firefox
            elif browser_type_lower == "webkit":
                browser_launcher = self.playwright.webkit
            else:
                browser_launcher = self.playwright.chromium
            
            # 使用持久化上下文（保存登录状态）
            if use_persistent:
                os.makedirs(self.user_data_dir, exist_ok=True)
                self.context = await browser_launcher.launch_persistent_context(
                    self.user_data_dir,
                    headless=headless,
                    slow_mo=slow_mo,
                    viewport={"width": 1280, "height": 720},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    **kwargs
                )
                self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
                return {
                    "success": True,
                    "message": f"浏览器已启动（持久化模式），用户数据保存在: {self.user_data_dir}"
                }
            else:
                # 普通启动模式
                self.browser = await browser_launcher.launch(
                    headless=headless,
                    slow_mo=slow_mo,
                    **kwargs
                )
                self.context = await self.browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                self.page = await self.context.new_page()
                return {
                    "success": True,
                    "message": "浏览器已启动（普通模式）"
                }
                
        except Exception as e:
            return {
                "success": False,
                "message": f"启动浏览器失败: {str(e)}"
            }
    
    async def connect_to_browser(self, cdp_url: str = "http://localhost:9222") -> Dict[str, Any]:
        """
        连接到已运行的浏览器（通过 CDP）
        
        Args:
            cdp_url: Chrome DevTools Protocol URL
            
        Returns:
            {"success": bool, "message": str}
        """
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.connect_over_cdp(cdp_url)
            self.context = self.browser.contexts[0] if self.browser.contexts else await self.browser.new_context()
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            
            return {
                "success": True,
                "message": f"已连接到浏览器: {cdp_url}"
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"连接浏览器失败: {str(e)}"
            }
    
    async def goto(self, url: str, wait_until: str = "domcontentloaded") -> Dict[str, Any]:
        """
        导航到指定URL
        
        Args:
            url: 目标URL
            wait_until: 等待条件 ("load", "domcontentloaded", "networkidle")
            
        Returns:
            {"success": bool, "title": str, "url": str}
        """
        try:
            await self.page.goto(url, wait_until=wait_until, timeout=30000)
            title = await self.page.title()
            current_url = self.page.url
            
            return {
                "success": True,
                "title": title,
                "url": current_url
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"页面导航失败: {str(e)}"
            }
    
    async def get_title(self) -> str:
        """获取页面标题"""
        return await self.page.title()
    
    async def get_url(self) -> str:
        """获取当前URL"""
        return self.page.url
    
    async def screenshot(self, filepath: str = "screenshot.png", full_page: bool = False) -> Dict[str, Any]:
        """
        截图
        
        Args:
            filepath: 保存路径
            full_page: 是否截取整个页面
            
        Returns:
            {"success": bool, "filepath": str}
        """
        try:
            await self.page.screenshot(path=filepath, full_page=full_page)
            return {
                "success": True,
                "filepath": filepath
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"截图失败: {str(e)}"
            }
    
    async def get_visible_text(self, selector: str = "body") -> str:
        """
        获取可见文本
        
        Args:
            selector: CSS选择器（默认body）
            
        Returns:
            文本内容
        """
        try:
            return await self.page.locator(selector).inner_text()
        except:
            return ""
    
    async def click_by_text(self, text: str, exact: bool = False) -> Dict[str, Any]:
        """
        根据文本点击元素
        
        Args:
            text: 文本内容
            exact: 是否精确匹配
            
        Returns:
            {"success": bool}
        """
        try:
            await self.page.get_by_text(text, exact=exact).click()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": f"点击失败: {str(e)}"}
    
    async def fill_by_placeholder(self, placeholder: str, text: str) -> Dict[str, Any]:
        """
        根据占位符填写输入框
        
        Args:
            placeholder: 占位符文本
            text: 要填写的内容
            
        Returns:
            {"success": bool}
        """
        try:
            await self.page.get_by_placeholder(placeholder).fill(text)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": f"填写失败: {str(e)}"}
    
    async def fill_by_label(self, label: str, text: str) -> Dict[str, Any]:
        """
        根据标签填写输入框
        
        Args:
            label: 标签文本
            text: 要填写的内容
            
        Returns:
            {"success": bool}
        """
        try:
            await self.page.get_by_label(label).fill(text)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": f"填写失败: {str(e)}"}
    
    async def click_by_role(self, role: str, name: Optional[str] = None) -> Dict[str, Any]:
        """
        根据角色点击元素
        
        Args:
            role: 角色类型 ("button", "link", "textbox", etc.)
            name: 可选的名称过滤
            
        Returns:
            {"success": bool}
        """
        try:
            if name:
                await self.page.get_by_role(role, name=name).click()
            else:
                await self.page.get_by_role(role).click()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": f"点击失败: {str(e)}"}
    
    async def click(self, selector: str) -> Dict[str, Any]:
        """
        根据CSS选择器点击元素
        
        Args:
            selector: CSS选择器或XPath
            
        Returns:
            {"success": bool}
        """
        try:
            await self.page.locator(selector).click()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": f"点击失败: {str(e)}"}
    
    async def fill(self, selector: str, text: str) -> Dict[str, Any]:
        """
        根据CSS选择器填写输入框
        
        Args:
            selector: CSS选择器或XPath
            text: 要填写的内容
            
        Returns:
            {"success": bool}
        """
        try:
            await self.page.locator(selector).fill(text)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": f"填写失败: {str(e)}"}
    
    async def press(self, selector: str, key: str) -> Dict[str, Any]:
        """
        按键
        
        Args:
            selector: CSS选择器
            key: 按键名称 ("Enter", "Escape", "ArrowDown", etc.)
            
        Returns:
            {"success": bool}
        """
        try:
            await self.page.locator(selector).press(key)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": f"按键失败: {str(e)}"}
    
    async def check(self, selector: str) -> Dict[str, Any]:
        """勾选复选框"""
        try:
            await self.page.locator(selector).check()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def uncheck(self, selector: str) -> Dict[str, Any]:
        """取消勾选复选框"""
        try:
            await self.page.locator(selector).uncheck()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def upload_file(self, selector: str, filepath: Union[str, List[str]]) -> Dict[str, Any]:
        """
        上传文件
        
        Args:
            selector: 文件输入框选择器
            filepath: 文件路径（字符串或列表）
            
        Returns:
            {"success": bool}
        """
        try:
            if isinstance(filepath, str):
                filepath = [filepath]
            await self.page.locator(selector).set_input_files(filepath)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": f"上传文件失败: {str(e)}"}
    
    async def wait_for_selector(self, selector: str, timeout: int = 30000) -> Dict[str, Any]:
        """
        等待元素出现
        
        Args:
            selector: CSS选择器
            timeout: 超时时间（毫秒）
            
        Returns:
            {"success": bool}
        """
        try:
            await self.page.wait_for_selector(selector, timeout=timeout)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": f"等待元素失败: {str(e)}"}
    
    async def wait_for_timeout(self, timeout: int):
        """固定等待（毫秒）"""
        await self.page.wait_for_timeout(timeout)
    
    async def save_storage_state(self, filepath: str = None) -> Dict[str, Any]:
        """
        保存浏览器状态（Cookie、localStorage等）
        
        Args:
            filepath: 保存路径（默认在用户数据目录）
            
        Returns:
            {"success": bool, "filepath": str}
        """
        try:
            if filepath is None:
                os.makedirs(self.user_data_dir, exist_ok=True)
                filepath = os.path.join(self.user_data_dir, "storage_state.json")
            
            await self.context.storage_state(path=filepath)
            return {
                "success": True,
                "filepath": filepath,
                "message": "浏览器状态已保存"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"保存状态失败: {str(e)}"
            }
    
    async def load_storage_state(self, filepath: str = None) -> Dict[str, Any]:
        """
        加载浏览器状态
        
        Args:
            filepath: 状态文件路径
            
        Returns:
            {"success": bool}
        """
        try:
            if filepath is None:
                filepath = os.path.join(self.user_data_dir, "storage_state.json")
            
            if not os.path.exists(filepath):
                return {
                    "success": False,
                    "error": "状态文件不存在"
                }
            
            # 需要在创建上下文时加载状态
            # 这里只是读取验证
            with open(filepath, 'r', encoding='utf-8') as f:
                state = json.load(f)
            
            return {
                "success": True,
                "message": f"状态文件已验证: {filepath}",
                "note": "请在启动浏览器时使用 storage_state 参数加载"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"加载状态失败: {str(e)}"
            }
    
    async def close(self):
        """关闭浏览器"""
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except:
            pass


# 同步包装函数
def create_playwright_session(
    browser_type: str = "chromium",
    headless: bool = False,
    slow_mo: int = 0,
    use_persistent: bool = False,
    user_data_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    创建 Playwright 会话（同步）
    
    Args:
        browser_type: 浏览器类型
        headless: 是否无头模式
        slow_mo: 慢速模式延迟
        use_persistent: 是否使用持久化上下文
        user_data_dir: 用户数据目录
        
    Returns:
        {"success": bool, "session_id": str, "message": str}
    """
    async def _create():
        tool = PlaywrightAdvanced(user_data_dir=user_data_dir)
        result = await tool.launch_browser(
            browser_type=browser_type,
            headless=headless,
            slow_mo=slow_mo,
            use_persistent=use_persistent
        )
        if result["success"]:
            # 保存会话（简化版，实际需要会话管理）
            result["session_id"] = id(tool)
        return result
    
    try:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_create())
    except:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(_create())

