#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Playwright工具 - 为露尼西亚提供网页导航与交互自动化能力
支持网页搜索、页面导航、点击、输入、上传文件、下拉选择等完整的网页操作
"""

import asyncio
import warnings
import logging
from typing import Dict, List, Any, Optional
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from async_resource_manager import get_resource_manager, close_event_loop

# 抑制所有asyncio相关警告
warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", message=".*coroutine.*was never awaited")
warnings.filterwarnings("ignore", message=".*unclosed.*")
warnings.filterwarnings("ignore", message=".*Event loop is closed.*")

# 抑制asyncio日志
logging.getLogger('asyncio').setLevel(logging.CRITICAL)

import json
import re
from datetime import datetime

# 全局单例实例和事件循环
_global_playwright_tool: Optional['PlaywrightTool'] = None
_global_event_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_thread = None


def get_or_create_event_loop():
    """获取或创建全局事件循环"""
    global _global_event_loop
    
    if _global_event_loop is None or _global_event_loop.is_closed():
        try:
            # 尝试获取当前循环
            _global_event_loop = asyncio.get_event_loop()
        except RuntimeError:
            # 创建新循环
            _global_event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_global_event_loop)
        
        # 注册到资源管理器
        get_resource_manager().register_event_loop(_global_event_loop)
    
    return _global_event_loop


def get_playwright_tool() -> 'PlaywrightTool':
    """获取全局Playwright工具单例"""
    global _global_playwright_tool
    if _global_playwright_tool is None:
        _global_playwright_tool = PlaywrightTool()
    return _global_playwright_tool

class PlaywrightTool:
    """Playwright网页导航与交互自动化工具"""
    
    def __init__(self, headless: bool = True):
        """
        初始化Playwright工具
        
        Args:
            headless: 是否使用无头模式（默认True）
        """
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.playwright = None
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        
        # 注册到资源管理器
        get_resource_manager().register_resource(self)
        
    async def start(self):
        """启动Playwright浏览器"""
        if self.browser is None:
            try:
                self.playwright = await async_playwright().start()
                self.browser = await self.playwright.chromium.launch(
                    headless=self.headless,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-blink-features=AutomationControlled'
                    ]
                )
                self.context = await self.browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                )
                self.page = await self.context.new_page()
                
                # 保存事件循环引用
                try:
                    self._event_loop = asyncio.get_running_loop()
                    get_resource_manager().register_event_loop(self._event_loop)
                except:
                    pass
            except Exception as e:
                print(f"⚠️ Playwright启动失败: {e}")
                raise
    
    async def close(self):
        """关闭Playwright浏览器 - 异步版本"""
        try:
            # 按顺序关闭，避免资源泄漏
            if self.page:
                try:
                    await self.page.close()
                except:
                    pass
                self.page = None
            
            if self.context:
                try:
                    await self.context.close()
                except:
                    pass
                self.context = None
            
            if self.browser:
                try:
                    await self.browser.close()
                except:
                    pass
                self.browser = None
            
            if self.playwright:
                try:
                    await self.playwright.stop()
                except:
                    pass
                self.playwright = None
        except Exception:
            pass
    
    def close_sync(self):
        """关闭Playwright浏览器 - 同步版本，正确清理子进程"""
        if not any([self.page, self.context, self.browser, self.playwright]):
            return  # 已经关闭，无需重复清理
        
        try:
            # 使用全局事件循环
            loop = get_or_create_event_loop()
            
            if loop and not loop.is_closed():
                try:
                    # 直接在循环中执行关闭，不使用create_task
                    loop.run_until_complete(self.close())
                    # 给予时间让子进程完全关闭
                    loop.run_until_complete(asyncio.sleep(0.3))
                except Exception as e:
                    # 静默处理
                    pass
            else:
                # 创建临时循环进行清理
                try:
                    temp_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(temp_loop)
                    try:
                        # 执行清理
                        temp_loop.run_until_complete(self.close())
                        # 给予额外时间让子进程完全关闭
                        temp_loop.run_until_complete(asyncio.sleep(0.3))
                        
                        # 取消所有待处理任务
                        pending = asyncio.all_tasks(temp_loop)
                        for task in pending:
                            task.cancel()
                        if pending:
                            temp_loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    finally:
                        temp_loop.close()
                except:
                    pass
        except Exception:
            pass
        finally:
            # 确保所有引用都被清理
            self.page = None
            self.context = None
            self.browser = None
            self.playwright = None
            self._event_loop = None
    
    async def search_web(self, query: str, search_engine: str = "google", max_results: int = 5) -> Dict[str, Any]:
        """
        使用Playwright进行网页搜索
        
        Args:
            query: 搜索关键词
            search_engine: 搜索引擎（google/bing/baidu）
            max_results: 最大结果数量
            
        Returns:
            搜索结果字典
        """
        try:
            await self.start()
            
            # URL编码查询词 - 直接使用完整问题，不分词
            from urllib.parse import quote
            encoded_query = quote(query)
            print(f"🔍 直接搜索完整问题: {query}")
            
            # 根据搜索引擎选择URL
            search_urls = {
                "google": f"https://www.google.com/search?q={encoded_query}",
                "bing": f"https://www.bing.com/search?q={encoded_query}",
                "baidu": f"https://www.baidu.com/s?wd={encoded_query}"
            }
            
            url = search_urls.get(search_engine, search_urls["bing"])
            print(f"🔍 使用Playwright搜索: {query} (引擎: {search_engine})")
            print(f"🔍 搜索URL: {url}")
            
            # 访问搜索引擎
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self.page.wait_for_timeout(2000)  # 等待页面完全加载
            
            # 提取搜索结果
            results = []
            
            if search_engine == "google":
                results = await self._extract_google_results(max_results)
            elif search_engine == "bing":
                results = await self._extract_bing_results(max_results)
            elif search_engine == "baidu":
                results = await self._extract_baidu_results(max_results)
            
            return {
                "success": True,
                "query": query,
                "search_engine": search_engine,
                "results": results,
                "count": len(results),
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"❌ Playwright搜索失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "query": query,
                "results": []
            }
    
    async def _extract_google_results(self, max_results: int) -> List[Dict[str, str]]:
        """提取Google搜索结果"""
        results = []
        try:
            # Google搜索结果选择器
            search_results = await self.page.query_selector_all('div.g')
            
            for result in search_results[:max_results]:
                try:
                    # 提取标题
                    title_element = await result.query_selector('h3')
                    title = await title_element.inner_text() if title_element else ""
                    
                    # 提取链接
                    link_element = await result.query_selector('a')
                    link = await link_element.get_attribute('href') if link_element else ""
                    
                    # 提取摘要
                    snippet_element = await result.query_selector('div[data-sncf]')
                    if not snippet_element:
                        snippet_element = await result.query_selector('div.VwiC3b')
                    snippet = await snippet_element.inner_text() if snippet_element else ""
                    
                    if title and link:
                        results.append({
                            "title": title.strip(),
                            "url": link.strip(),
                            "snippet": snippet.strip()
                        })
                except Exception as e:
                    continue
                    
        except Exception as e:
            print(f"⚠️ 提取Google结果失败: {e}")
        
        return results
    
    async def _extract_bing_results(self, max_results: int) -> List[Dict[str, str]]:
        """提取Bing搜索结果"""
        results = []
        try:
            search_results = await self.page.query_selector_all('li.b_algo')
            
            for result in search_results[:max_results]:
                try:
                    title_element = await result.query_selector('h2 a')
                    title = await title_element.inner_text() if title_element else ""
                    link = await title_element.get_attribute('href') if title_element else ""
                    
                    snippet_element = await result.query_selector('p')
                    snippet = await snippet_element.inner_text() if snippet_element else ""
                    
                    if title and link:
                        results.append({
                            "title": title.strip(),
                            "url": link.strip(),
                            "snippet": snippet.strip()
                        })
                except Exception as e:
                    continue
                    
        except Exception as e:
            print(f"⚠️ 提取Bing结果失败: {e}")
        
        return results
    
    async def _extract_baidu_results(self, max_results: int) -> List[Dict[str, str]]:
        """提取百度搜索结果"""
        results = []
        try:
            search_results = await self.page.query_selector_all('div.result')
            
            for result in search_results[:max_results]:
                try:
                    title_element = await result.query_selector('h3 a')
                    title = await title_element.inner_text() if title_element else ""
                    link = await title_element.get_attribute('href') if title_element else ""
                    
                    snippet_element = await result.query_selector('div.c-abstract')
                    snippet = await snippet_element.inner_text() if snippet_element else ""
                    
                    if title and link:
                        results.append({
                            "title": title.strip(),
                            "url": link.strip(),
                            "snippet": snippet.strip()
                        })
                except Exception as e:
                    continue
                    
        except Exception as e:
            print(f"⚠️ 提取百度结果失败: {e}")
        
        return results
    
    async def open_url(self, url: str, wait_time: int = 3000) -> Dict[str, Any]:
        """
        打开指定URL
        
        Args:
            url: 目标URL
            wait_time: 等待时间（毫秒）
            
        Returns:
            页面信息字典
        """
        try:
            await self.start()
            
            print(f"🌐 打开网页: {url}")
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self.page.wait_for_timeout(wait_time)
            
            # 获取页面信息
            title = await self.page.title()
            current_url = self.page.url
            content = await self.page.content()
            
            return {
                "success": True,
                "url": url,
                "current_url": current_url,
                "title": title,
                "content_length": len(content),
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"❌ 打开网页失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "url": url
            }
    
    async def click_element(self, selector: str, wait_time: int = 1000) -> Dict[str, Any]:
        """
        点击页面元素
        
        Args:
            selector: CSS选择器
            wait_time: 点击后等待时间（毫秒）
            
        Returns:
            操作结果
        """
        try:
            print(f"👆 点击元素: {selector}")
            await self.page.click(selector)
            await self.page.wait_for_timeout(wait_time)
            
            return {
                "success": True,
                "action": "click",
                "selector": selector
            }
            
        except Exception as e:
            print(f"❌ 点击失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "selector": selector
            }
    
    async def fill_input(self, selector: str, text: str) -> Dict[str, Any]:
        """
        填写输入框
        
        Args:
            selector: CSS选择器
            text: 要填写的文本
            
        Returns:
            操作结果
        """
        try:
            print(f"✍️ 填写输入框: {selector} = {text}")
            await self.page.fill(selector, text)
            
            return {
                "success": True,
                "action": "fill",
                "selector": selector,
                "text": text
            }
            
        except Exception as e:
            print(f"❌ 填写失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "selector": selector
            }
    
    async def get_text(self, selector: str) -> Dict[str, Any]:
        """
        获取元素文本
        
        Args:
            selector: CSS选择器
            
        Returns:
            文本内容
        """
        try:
            element = await self.page.query_selector(selector)
            if element:
                text = await element.inner_text()
                return {
                    "success": True,
                    "selector": selector,
                    "text": text
                }
            else:
                return {
                    "success": False,
                    "error": "Element not found",
                    "selector": selector
                }
                
        except Exception as e:
            print(f"❌ 获取文本失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "selector": selector
            }
    
    async def screenshot(self, filepath: str = "screenshot.png") -> Dict[str, Any]:
        """
        截图
        
        Args:
            filepath: 保存路径
            
        Returns:
            操作结果
        """
        try:
            print(f"📸 截图保存到: {filepath}")
            await self.page.screenshot(path=filepath, full_page=True)
            
            return {
                "success": True,
                "filepath": filepath
            }
            
        except Exception as e:
            print(f"❌ 截图失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def execute_script(self, script: str) -> Dict[str, Any]:
        """
        执行JavaScript脚本
        
        Args:
            script: JavaScript代码
            
        Returns:
            执行结果
        """
        try:
            print(f"⚙️ 执行脚本: {script[:50]}...")
            result = await self.page.evaluate(script)
            
            return {
                "success": True,
                "result": result
            }
            
        except Exception as e:
            print(f"❌ 脚本执行失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def find_and_click(self, selector: str, text: Optional[str] = None) -> Dict[str, Any]:
        """查找并点击元素"""
        try:
            if text:
                # 根据文本内容查找元素
                element = await self.page.get_by_text(text).first
                await element.click()
            else:
                # 根据选择器查找元素
                await self.page.click(selector)
            
            await self.page.wait_for_timeout(1000)  # 等待页面响应
            return {
                "success": True,
                "message": f"成功点击元素: {text or selector}",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"点击元素失败: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }
    
    async def find_and_fill(self, selector: str, text: str, clear: bool = True) -> Dict[str, Any]:
        """查找输入框并填入文本"""
        try:
            if clear:
                await self.page.fill(selector, "")
            await self.page.fill(selector, text)
            await self.page.wait_for_timeout(500)
            return {
                "success": True,
                "message": f"成功填入文本: {text}",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"填入文本失败: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }
    
    async def search_on_page(self, query: str, search_box_selector: str = "input[type='search'], input[name*='search'], input[id*='search'], #search, .search-input") -> Dict[str, Any]:
        """在页面上执行搜索操作"""
        try:
            # 查找搜索框
            search_box = await self.page.query_selector(search_box_selector)
            if not search_box:
                # 尝试常见的搜索框选择器
                common_selectors = [
                    "input[type='search']",
                    "input[name*='search']", 
                    "input[id*='search']",
                    "#search",
                    ".search-input",
                    "input[placeholder*='搜索']",
                    "input[placeholder*='search']"
                ]
                for selector in common_selectors:
                    search_box = await self.page.query_selector(selector)
                    if search_box:
                        search_box_selector = selector
                        break
            
            if not search_box:
                return {
                    "success": False,
                    "error": "未找到搜索框",
                    "timestamp": datetime.now().isoformat()
                }
            
            # 清空并填入搜索内容
            await self.page.fill(search_box_selector, "")
            await self.page.fill(search_box_selector, query)
            
            # 尝试按回车键提交搜索
            await self.page.press(search_box_selector, "Enter")
            await self.page.wait_for_load_state("networkidle")
            
            return {
                "success": True,
                "message": f"成功执行搜索: {query}",
                "search_box_selector": search_box_selector,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"搜索失败: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }
    
    async def get_page_elements(self, selector: str = "*") -> Dict[str, Any]:
        """获取页面元素信息"""
        try:
            elements = await self.page.query_selector_all(selector)
            element_info = []
            
            for element in elements[:20]:  # 限制返回前20个元素
                try:
                    tag_name = await element.evaluate("el => el.tagName")
                    text_content = await element.evaluate("el => el.textContent?.trim() || ''")
                    href = await element.evaluate("el => el.href || ''")
                    element_info.append({
                        "tag": tag_name.lower(),
                        "text": text_content[:100],  # 限制文本长度
                        "href": href,
                        "selector": await element.evaluate("el => el.id ? `#${el.id}` : el.className ? `.${el.className.split(' ')[0]}` : el.tagName.toLowerCase()")
                    })
                except:
                    continue
            
            return {
                "success": True,
                "elements": element_info,
                "count": len(element_info),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"获取页面元素失败: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }
    
    async def scroll_page(self, direction: str = "down", amount: int = 500) -> Dict[str, Any]:
        """滚动页面"""
        try:
            if direction == "down":
                await self.page.evaluate(f"window.scrollBy(0, {amount})")
            elif direction == "up":
                await self.page.evaluate(f"window.scrollBy(0, -{amount})")
            elif direction == "top":
                await self.page.evaluate("window.scrollTo(0, 0)")
            elif direction == "bottom":
                await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            
            await self.page.wait_for_timeout(1000)
            return {
                "success": True,
                "message": f"成功滚动页面: {direction}",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"滚动页面失败: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }
    
    async def _extract_page_content(self, max_length: int = 5000) -> str:
        """提取页面主要内容"""
        try:
            # 移除脚本和样式标签
            await self.page.evaluate("""
                const scripts = document.querySelectorAll('script, style, nav, footer, header');
                scripts.forEach(el => el.remove());
            """)
            
            # 提取文本内容
            content = await self.page.evaluate("""
                () => {
                    const textContent = document.body.innerText || document.body.textContent || '';
                    return textContent.replace(/\\s+/g, ' ').trim();
                }
            """)
            
            # 限制长度
            if len(content) > max_length:
                content = content[:max_length] + "..."
            
            return content
            
        except Exception as e:
            return f"内容提取失败: {str(e)}"


async def _close_headed_browser_entry(entry: dict) -> None:
    try:
        browser = entry.get("browser")
        if browser:
            await browser.close()
    except Exception:
        pass
    try:
        pw = entry.get("playwright")
        if pw:
            await pw.stop()
    except Exception:
        pass


def _close_headed_browsers_sync() -> None:
    """关闭所有有头模式后台浏览器及其事件循环。"""
    global _headed_browsers
    for entry in list(_headed_browsers):
        loop = entry.get("loop")
        if loop is not None and not loop.is_closed():
            try:
                loop.run_until_complete(_close_headed_browser_entry(entry))
            except Exception:
                pass
            close_event_loop(loop)
    _headed_browsers.clear()


def shutdown_playwright_runtime() -> None:
    """
    退出前完整关闭 Playwright 与全局 asyncio 循环（须在 QApplication.quit 之前调用）。
    """
    global _global_event_loop, _global_playwright_tool

    _close_headed_browsers_sync()

    tool = _global_playwright_tool
    if tool is not None:
        try:
            tool.close_sync()
        except Exception:
            pass

    close_event_loop(_global_event_loop)
    _global_event_loop = None
    _global_playwright_tool = None
    try:
        asyncio.set_event_loop(None)
    except Exception:
        pass


# 同步包装函数
def playwright_search(query: str, search_engine: str = "google", max_results: int = 5) -> Dict[str, Any]:
    """同步方式调用Playwright搜索 - 使用全局单例和持久化事件循环"""
    tool = get_playwright_tool()
    loop = get_or_create_event_loop()
    
    try:
        # 检查是否在Qt事件循环中运行
        try:
            running_loop = asyncio.get_running_loop()
            # 如果已经在Qt的事件循环中，使用新线程运行
            import concurrent.futures
            import threading
            
            def run_in_thread():
                # 在新线程中使用全局事件循环
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(tool.search_web(query, search_engine, max_results))
            
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_thread)
                result = future.result(timeout=60)
                return result
        except RuntimeError:
            # 没有运行的事件循环，直接使用全局循环
            result = loop.run_until_complete(tool.search_web(query, search_engine, max_results))
            return result
    except Exception as e:
        return {"success": False, "error": f"搜索失败: {str(e)}"}

# 全局列表，保存有头浏览器实例，防止过早关闭
_headed_browsers = []

def playwright_open_website_headed(url: str, browser_type: str = "chromium", wait_time: int = 3000) -> Dict[str, Any]:
    """
    同步方式以有头模式打开网站（用于网站打开请求）
    
    Args:
        url: 要打开的网址
        browser_type: 浏览器类型 (chromium/firefox/webkit/edge)
        wait_time: 等待时间（毫秒）
    
    Returns:
        执行结果字典
    """
    import threading
    import queue
    
    # 使用队列在线程间传递结果
    result_queue = queue.Queue()
    
    def run_headed_browser_background():
        """在后台线程中运行有头浏览器"""
        headed_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(headed_loop)
        
        async def open_browser_async():
            playwright_instance = None
            browser_instance = None
            
            try:
                playwright_instance = await async_playwright().start()
                
                # 根据浏览器类型选择
                browser_type_lower = browser_type.lower()
                
                if browser_type_lower in ["edge", "msedge", "microsoft edge"]:
                    print(f"🌐 启动 Microsoft Edge 浏览器（有头模式）")
                    browser_instance = await playwright_instance.chromium.launch(
                        headless=False,
                        channel="msedge",
                        args=['--no-sandbox', '--disable-setuid-sandbox']
                    )
                elif browser_type_lower == "firefox":
                    print(f"🌐 启动 Firefox 浏览器（有头模式）")
                    browser_instance = await playwright_instance.firefox.launch(
                        headless=False,
                        args=['--no-sandbox']
                    )
                elif browser_type_lower == "webkit":
                    print(f"🌐 启动 WebKit 浏览器（有头模式）")
                    browser_instance = await playwright_instance.webkit.launch(headless=False)
                elif browser_type_lower in ["chrome", "google chrome"]:
                    print(f"🌐 启动 Google Chrome 浏览器（有头模式）")
                    browser_instance = await playwright_instance.chromium.launch(
                        headless=False,
                        channel="chrome",
                        args=['--no-sandbox', '--disable-setuid-sandbox']
                    )
                else:
                    print(f"🌐 启动 Chromium 浏览器（有头模式）")
                    browser_instance = await playwright_instance.chromium.launch(
                        headless=False,
                        args=['--no-sandbox', '--disable-setuid-sandbox']
                    )
                
                context = await browser_instance.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                )
                page = await context.new_page()
                
                # 打开网址
                await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                
                # 获取页面标题
                title = await page.title()
                
                print(f"✅ 有头模式已打开网站: {url}")
                print(f"📄 页面标题: {title}")
                
                # 发送成功结果到主线程
                result_queue.put({
                    "success": True,
                    "url": url,
                    "title": title,
                    "browser": browser_type
                })
                
                # 保存实例到全局列表，防止垃圾回收
                _headed_browsers.append({
                    'playwright': playwright_instance,
                    'browser': browser_instance,
                    'context': context,
                    'page': page,
                    'loop': headed_loop
                })
                
                print(f"🔒 有头浏览器已保存（共{len(_headed_browsers)}个），保持运行直到用户关闭")
                
                # 无限等待，直到浏览器被用户关闭
                try:
                    await browser_instance.wait_for_event('close', timeout=0)
                    print(f"🚪 用户已关闭浏览器")
                except:
                    pass
                    
            except Exception as e:
                print(f"❌ 有头浏览器错误: {str(e)}")
                result_queue.put({"success": False, "error": f"打开网站失败: {str(e)}"})
                
                # 出错时清理资源
                try:
                    if browser_instance:
                        await browser_instance.close()
                    if playwright_instance:
                        await playwright_instance.stop()
                except:
                    pass
        
        try:
            headed_loop.run_until_complete(open_browser_async())
        except Exception as e:
            print(f"❌ 事件循环错误: {str(e)}")
            if result_queue.empty():
                result_queue.put({"success": False, "error": str(e)})
        finally:
            # 循环结束后才关闭
            try:
                headed_loop.close()
            except:
                pass
    
    # 启动守护线程
    browser_thread = threading.Thread(target=run_headed_browser_background, daemon=True)
    browser_thread.start()
    
    # 等待结果（最多10秒）
    try:
        result = result_queue.get(timeout=10)
        return result
    except queue.Empty:
        return {"success": False, "error": "浏览器启动超时"}

def playwright_open_url(url: str, wait_time: int = 3000) -> Dict[str, Any]:
    """同步方式打开URL - 使用全局单例和持久化事件循环（无头模式）"""
    tool = get_playwright_tool()
    loop = get_or_create_event_loop()
    
    try:
        # 检查是否在Qt事件循环中运行
        try:
            running_loop = asyncio.get_running_loop()
            # 如果已经在Qt的事件循环中，使用新线程运行
            import concurrent.futures
            
            def run_in_thread():
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(tool.open_url(url, wait_time))
            
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_thread)
                result = future.result(timeout=60)
                return result
        except RuntimeError:
            # 没有运行的事件循环，直接使用全局循环
            result = loop.run_until_complete(tool.open_url(url, wait_time))
            return result
    except Exception as e:
        return {"success": False, "error": f"打开页面失败: {str(e)}"}

def playwright_open_website_headed(
    url: str, 
    browser_type: str = "chromium", 
    search_query: str = "",
    mode: str = "launch",
    slow_mo: int = 0,
    cdp_url: str = "http://localhost:9222",
    user_data_dir: str = "",
    actions: List[Dict[str, Any]] = None,
    use_react_agent: bool = False,
    react_task: str = ""
) -> Dict[str, Any]:
    """
    使用Playwright在有头模式（可见浏览器）打开网站，支持后续自动化操作
    
    Args:
        url: 目标URL
        browser_type: 浏览器类型 ("chromium", "firefox", "webkit", "edge", "chrome")
        search_query: 如果提供，将在网站上执行搜索操作
        mode: 启动模式 ("launch"=常规启动, "connect"=连接已有浏览器, "persistent"=持久化上下文)
        slow_mo: 慢速模式延迟（毫秒）
        cdp_url: CDP连接地址（mode="connect"时使用）
        user_data_dir: 用户数据目录（持久化模式使用）
        actions: 打开网页后要执行的操作列表（可选）
    
    Returns:
        {"success": bool, "title": str, "url": str, "error": str, "search_performed": bool}
    """
    async def _open_headed():
        from playwright.async_api import async_playwright
        import os
        from pathlib import Path
        
        try:
            print(f"🔧 playwright_open_website_headed 参数 - mode:{mode}, slow_mo:{slow_mo}, browser:{browser_type}")
            
            playwright = await async_playwright().start()
            browser_type_lower = browser_type.lower() if browser_type else "chromium"
            
            # 初始化变量
            browser = None
            context = None
            page = None
            
            # 选择浏览器引擎
            if browser_type_lower in ["edge", "chrome", "chromium"]:
                browser_engine = playwright.chromium
            elif browser_type_lower == "firefox":
                browser_engine = playwright.firefox
            elif browser_type_lower == "webkit":
                browser_engine = playwright.webkit
            else:
                browser_engine = playwright.chromium
            
            print(f"🔍 判断启动模式 - mode=='{mode}'")
            
            # 模式1：连接已有浏览器
            if mode == "connect":
                print(f"🔌 连接到已运行的浏览器: {cdp_url}")
                browser = await playwright.chromium.connect_over_cdp(cdp_url)
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = context.pages[0] if context.pages else await context.new_page()
            
            # 模式2：持久化上下文（保存登录状态）
            elif mode == "persistent":
                print(f"✅ 进入持久化分支")
                # 使用局部变量避免闭包作用域问题
                data_dir = user_data_dir if user_data_dir else str(Path.home() / ".lunesia" / "browser_data")
                print(f"💾 数据目录: {data_dir}")
                os.makedirs(data_dir, exist_ok=True)
                print(f"💾 数据目录已创建/验证: {data_dir}")
                
                # 持久化上下文的启动参数
                launch_args = {
                    "headless": False,
                    "slow_mo": slow_mo,
                    "viewport": {"width": 1280, "height": 720},
                    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
                
                # 添加浏览器channel
                if browser_type_lower == "edge":
                    launch_args["channel"] = "msedge"
                elif browser_type_lower == "chrome":
                    launch_args["channel"] = "chrome"
                
                context = await browser_engine.launch_persistent_context(
                    data_dir,
                    **launch_args
                )
                page = context.pages[0] if context.pages else await context.new_page()
                browser = None  # 持久化上下文不返回browser对象
            
            # 模式3：常规启动
            else:
                print(f"✅ 进入常规启动分支")
                print(f"🚀 常规启动浏览器")
                launch_args = {
                    "headless": False,
                    "slow_mo": slow_mo
                }
                
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
            
            # 访问URL
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
            
            # 获取页面标题
            title = await page.title()
            print(f"✅ Playwright有头模式打开成功: {title}")
            
            # 🤖 如果启用ReAct Agent，使用智能推理模式
            if use_react_agent and react_task:
                print(f"🤖 启用ReAct推理模式，任务: {react_task}")
                try:
                    # 导入并使用BrowserAutomationAgent
                    from browser_automation_agent import BrowserAutomationAgent
                    
                    # 获取配置（尝试从全局或使用默认配置）
                    try:
                        import json
                        with open("ai_agent_config.json", "r", encoding="utf-8") as f:
                            config = json.load(f)
                    except:
                        config = {}
                    
                    agent = BrowserAutomationAgent(config, page)
                    react_result = await agent.execute_task(react_task)
                    
                    if react_result.get("success"):
                        print(f"✅ ReAct推理任务完成，共执行 {react_result.get('steps')} 步")
                        return {
                            "success": True,
                            "title": await page.title(),
                            "url": page.url,
                            "browser": browser_type_lower,
                            "react_mode": True,
                            "react_steps": react_result.get("steps"),
                            "react_history": react_result.get("history")
                        }
                    else:
                        print(f"⚠️ ReAct推理未完成: {react_result.get('message')}")
                        return {
                            "success": True,  # 网页已打开
                            "title": await page.title(),
                            "url": page.url,
                            "browser": browser_type_lower,
                            "react_mode": True,
                            "react_incomplete": True,
                            "react_message": react_result.get("message"),
                            "react_steps": react_result.get("steps")
                        }
                except Exception as react_error:
                    print(f"❌ ReAct推理失败: {str(react_error)}")
                    # 继续执行原有逻辑
            
            # 🔍 如果有搜索请求，执行自动化搜索
            search_performed = False
            if search_query:
                try:
                    print(f"🔍 开始执行搜索: {search_query}")
                    
                    # 常见搜索框选择器（按优先级）
                    search_selectors = [
                        'input[type="search"]',
                        'input[placeholder*="搜索"]',
                        'input[placeholder*="Search"]',
                        'input[class*="search"]',
                        'input[name*="search"]',
                        'input[id*="search"]',
                        'input[type="text"]',
                        'textarea[placeholder*="搜索"]',
                    ]
                    
                    search_box = None
                    for selector in search_selectors:
                        try:
                            search_box = await page.wait_for_selector(selector, timeout=3000)
                            if search_box:
                                print(f"✅ 找到搜索框: {selector}")
                                break
                        except:
                            continue
                    
                    if search_box:
                        # 清空并输入搜索内容
                        await search_box.click()
                        await search_box.fill(search_query)  # 直接填充，不延迟
                        print(f"✅ 已输入搜索内容: {search_query}")
                        
                        # 按下回车键
                        await search_box.press("Enter")
                        print(f"✅ 已按下回车键，开始搜索")
                        
                        # 等待搜索结果加载
                        await page.wait_for_timeout(2000)
                        search_performed = True
                        print(f"✅ 搜索完成")
                    else:
                        print(f"⚠️ 未找到搜索框，无法执行搜索")
                        
                except Exception as search_error:
                    print(f"⚠️ 搜索执行失败: {str(search_error)}")
            
            # 🎯 执行额外的自动化操作（点击、填写、滚动等）
            actions_performed = []
            if actions:
                try:
                    print(f"🎯 开始执行 {len(actions)} 个自动化操作")
                    for i, action in enumerate(actions):
                        action_type = action.get("type")
                        print(f"  [{i+1}/{len(actions)}] 执行操作: {action_type}")
                        
                        if action_type == "click_text":
                            # 通过文本内容点击元素
                            text = action.get("text", "")
                            clicked = False
                            
                            try:
                                # 等待页面完全加载（增加超时时间）
                                try:
                                    await page.wait_for_load_state("domcontentloaded", timeout=10000)
                                    await page.wait_for_timeout(2000)  # 额外等待动态内容加载
                                except:
                                    print(f"    ⚠️ 页面加载超时，继续尝试点击")
                                
                                # 🎯 针对B站等视频网站的特殊处理
                                # 策略1: 直接点击第一个视频卡片（通过序号）
                                if "第一个" in text or "第1个" in text or "第一" in text:
                                    try:
                                        print(f"    🔍 开始查找第一个视频（过滤直播）")
                                        
                                        # 🎯 B站特殊处理：区分视频和直播
                                        # 方式1: 通过href精确匹配视频链接（排除直播）
                                        try:
                                            # 查找所有包含 /video/ 的链接（这是B站视频特征）
                                            video_links = await page.query_selector_all('a[href*="/video/BV"]')
                                            
                                            if video_links:
                                                print(f"    📹 找到 {len(video_links)} 个视频链接")
                                                # 选择第一个可见的视频
                                                for link in video_links[:5]:  # 只检查前5个
                                                    try:
                                                        is_visible = await link.is_visible()
                                                        if is_visible:
                                                            # 获取视频信息
                                                            href = await link.get_attribute('href')
                                                            print(f"    🎯 找到第一个可见视频: {href[:50]}...")
                                                            
                                                            await link.scroll_into_view_if_needed()
                                                            await page.wait_for_timeout(300)
                                                            await link.click(force=True, timeout=3000)
                                                            print(f"    ✅ 点击成功（视频链接）")
                                                            actions_performed.append({"type": "click", "target": text, "success": True})
                                                            clicked = True
                                                            break
                                                    except:
                                                        continue
                                                
                                                if clicked:
                                                    continue
                                        except Exception as e:
                                            print(f"    ⚠️ 视频链接查找失败: {str(e)}")
                                        
                                        # 方式2: 通用视频卡片选择器（有href属性的才点击）
                                        if not clicked:
                                            video_selectors = [
                                                '.bili-video-card a[href*="/video/"]',  # B站视频卡片内的视频链接
                                                '.video-card a[href*="/video/"]',
                                                'a.bili-video-card[href*="/video/"]',
                                                '[class*="video-card"] a[href*="/video/"]',
                                            ]
                                            
                                            for selector in video_selectors:
                                                try:
                                                    first_video = await page.query_selector(selector)
                                                    if first_video:
                                                        is_visible = await first_video.is_visible()
                                                        if is_visible:
                                                            href = await first_video.get_attribute('href')
                                                            print(f"    🎯 找到视频卡片: {selector}, href={href[:50] if href else 'N/A'}...")
                                                            
                                                            await first_video.scroll_into_view_if_needed()
                                                            await page.wait_for_timeout(500)
                                                            await first_video.click(force=True, timeout=3000)
                                                            print(f"    ✅ 点击成功（视频卡片选择器）: {selector}")
                                                            actions_performed.append({"type": "click", "target": text, "success": True})
                                                            clicked = True
                                                            break
                                                except:
                                                    continue
                                            
                                            if clicked:
                                                continue
                                    except Exception as e:
                                        print(f"    ⚠️ 视频卡片点击失败: {str(e)}")
                                
                                # 策略2: 通用文本匹配（其他情况）
                                if not clicked:
                                    # 方式1: 使用XPath查找包含文本的可点击元素
                                    try:
                                        xpath_selectors = [
                                            f"//a[contains(text(), '{text}')]",
                                            f"//button[contains(text(), '{text}')]",
                                            f"//div[contains(text(), '{text}') and (@role='button' or @onclick)]",
                                            f"//*[contains(text(), '{text}') and (self::a or self::button)]"
                                        ]
                                        
                                        for xpath in xpath_selectors:
                                            try:
                                                element = await page.query_selector(f"xpath={xpath}")
                                                if element:
                                                    await element.scroll_into_view_if_needed()
                                                    await page.wait_for_timeout(300)
                                                    await element.click(force=True, timeout=3000)
                                                    print(f"    ✅ 点击成功（XPath匹配）: {text}")
                                                    actions_performed.append({"type": "click", "target": text, "success": True})
                                                    clicked = True
                                                    break
                                            except:
                                                continue
                                        
                                        if clicked:
                                            continue
                                    except Exception as e:
                                        print(f"    ⚠️ XPath点击失败: {str(e)}")
                                    
                                    # 方式2: 遍历所有可点击元素
                                    try:
                                        elements = await page.query_selector_all('a, button, [role="button"], [onclick]')
                                        for elem in elements:
                                            try:
                                                is_visible = await elem.is_visible()
                                                if not is_visible:
                                                    continue
                                                
                                                elem_text = await elem.inner_text()
                                                if elem_text and (text in elem_text or elem_text in text):
                                                    await elem.scroll_into_view_if_needed()
                                                    await page.wait_for_timeout(300)
                                                    await elem.click(force=True)
                                                    print(f"    ✅ 点击成功（遍历匹配）: {elem_text[:50]}")
                                                    actions_performed.append({"type": "click", "target": text, "success": True})
                                                    clicked = True
                                                    break
                                            except:
                                                continue
                                        
                                        if clicked:
                                            continue
                                    except Exception as e:
                                        print(f"    ⚠️ 遍历点击失败: {str(e)}")
                                
                                # 所有策略都失败
                                if not clicked:
                                    print(f"    ⚠️ 未找到可点击元素: {text}")
                                    actions_performed.append({"type": "click", "target": text, "success": False, "error": "未找到可点击元素"})
                                    
                            except Exception as e:
                                print(f"    ❌ 点击操作异常: {str(e)}")
                                actions_performed.append({"type": "click", "target": text, "success": False, "error": str(e)})
                        
                        elif action_type == "fill":
                            # 填写输入框
                            selector = action.get("selector", "")
                            text = action.get("text", "")
                            try:
                                await page.fill(selector, text, timeout=3000)
                                print(f"    ✅ 填写成功: {selector} = {text}")
                                actions_performed.append({"type": "fill", "target": selector, "success": True})
                            except Exception as e:
                                print(f"    ⚠️ 填写失败: {str(e)}")
                                actions_performed.append({"type": "fill", "target": selector, "success": False, "error": str(e)})
                        
                        elif action_type == "scroll":
                            # 滚动页面
                            direction = action.get("direction", "down")
                            try:
                                if direction == "top":
                                    await page.evaluate("window.scrollTo(0, 0)")
                                elif direction == "bottom":
                                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                                else:
                                    await page.evaluate("window.scrollBy(0, 500)")
                                print(f"    ✅ 滚动成功: {direction}")
                                actions_performed.append({"type": "scroll", "target": direction, "success": True})
                            except Exception as e:
                                print(f"    ⚠️ 滚动失败: {str(e)}")
                                actions_performed.append({"type": "scroll", "target": direction, "success": False, "error": str(e)})
                        
                        # 操作之间稍作等待
                        await page.wait_for_timeout(500)
                    
                    print(f"✅ 自动化操作完成: {len(actions_performed)} 个操作")
                except Exception as actions_error:
                    print(f"⚠️ 自动化操作执行失败: {str(actions_error)}")
            
            if not search_query and not actions:
                print(f"💡 提示：浏览器将保持打开状态，您可以继续执行自动化操作")
            
            # 等待一段时间让用户看到结果
            await page.wait_for_timeout(1000)
            
            # ✅ 核心策略：完成自动化后，立即清理所有 Playwright 资源
            # 但浏览器窗口会关闭，这是 Playwright 的设计限制
            # 
            # 解决方案的权衡：
            # 1. 如果清理资源 → 浏览器关闭 → 用户体验差
            # 2. 如果不清理资源 → 浏览器保持打开 → 程序退出时有异常
            # 
            # 当前选择：不清理（保持浏览器打开），接受退出异常
            # 这些异常不会造成任何问题，只是 Python 的清理警告
            
            print(f"✅ 网站已打开，浏览器保持运行状态")
            print(f"💡 提示：程序退出时可能会有清理警告，这是正常现象（不影响功能）")
            
            return {
                "success": True,
                "title": title,
                "url": url,
                "browser": browser_type_lower,
                "search_performed": search_performed,
                "search_query": search_query if search_performed else "",
                "actions_performed": actions_performed,
                "actions_count": len(actions_performed)
            }
            
        except Exception as e:
            print(f"❌ Playwright打开失败: {str(e)}")
            # 失败时清理已创建的资源
            try:
                if 'context' in locals():
                    await context.close()
                if 'browser' in locals():
                    await browser.close()
                if 'playwright' in locals():
                    await playwright.stop()
            except:
                pass
            return {
                "success": False,
                "error": str(e)
            }
    
    try:
        loop = get_or_create_event_loop()
        
        # 检查是否有Qt事件循环
        try:
            import asyncio
            asyncio.get_running_loop()
            # 有运行中的事件循环，在新线程中运行
            import concurrent.futures
            
            def run_in_thread():
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(_open_headed())
                finally:
                    pass  # 不关闭loop，让浏览器继续运行
            
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_thread)
                result = future.result(timeout=60)
                return result
        except RuntimeError:
            # 没有运行的事件循环，直接运行
            result = loop.run_until_complete(_open_headed())
            return result
    except Exception as e:
        return {"success": False, "error": f"启动失败: {str(e)}"}

def playwright_interact(url: str, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    同步方式执行网页导航与交互操作
    
    Args:
        url: 目标URL
        actions: 操作列表，每个操作包含type和参数
                示例: [{"type": "click", "selector": "button"},
                      {"type": "fill", "selector": "input", "text": "hello"}]
    
    Returns:
        操作结果
    """
    async def _interact():
        tool = get_playwright_tool()
        try:
            await tool.start()
            await tool.open_url(url)
            
            results = []
            for action in actions:
                action_type = action.get("type")
                
                if action_type == "click":
                    result = await tool.click_element(action["selector"])
                elif action_type == "click_text":
                    result = await tool.find_and_click(action.get("selector", ""), action.get("text"))
                elif action_type == "fill":
                    result = await tool.fill_input(action["selector"], action["text"])
                elif action_type == "fill_advanced":
                    result = await tool.find_and_fill(action["selector"], action["text"], action.get("clear", True))
                elif action_type == "search":
                    result = await tool.search_on_page(action["query"], action.get("search_box_selector"))
                elif action_type == "get_text":
                    result = await tool.get_text(action["selector"])
                elif action_type == "get_elements":
                    result = await tool.get_page_elements(action.get("selector", "*"))
                elif action_type == "scroll":
                    result = await tool.scroll_page(action.get("direction", "down"), action.get("amount", 500))
                elif action_type == "screenshot":
                    result = await tool.screenshot(action.get("filepath", "screenshot.png"))
                elif action_type == "execute_script":
                    result = await tool.execute_script(action["script"])
                else:
                    result = {"success": False, "error": f"Unknown action type: {action_type}"}
                
                results.append(result)
            
            return {
                "success": True,
                "url": url,
                "actions": results
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    loop = get_or_create_event_loop()
    return loop.run_until_complete(_interact())

async def _serp_search_in_context(browser, query: str, search_engine: str, max_results: int) -> Dict[str, Any]:
    """在独立 browser context 中执行一次 SERP 检索。"""
    from urllib.parse import quote

    context = await browser.new_context(
        viewport={"width": 1280, "height": 720},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    )
    page = await context.new_page()
    tool = PlaywrightTool()
    tool.page = page
    try:
        encoded = quote(query)
        search_urls = {
            "google": f"https://www.google.com/search?q={encoded}",
            "bing": f"https://www.bing.com/search?q={encoded}",
            "baidu": f"https://www.baidu.com/s?wd={encoded}",
            "duckduckgo": f"https://duckduckgo.com/?q={encoded}",
        }
        engine = (search_engine or "bing").lower()
        if engine == "duckduckgo":
            engine = "bing"
        url = search_urls.get(engine, search_urls["bing"])
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(1500)
        results = []
        if engine == "google":
            results = await tool._extract_google_results(max_results)
        elif engine == "baidu":
            results = await tool._extract_baidu_results(max_results)
        else:
            results = await tool._extract_bing_results(max_results)
        return {"success": True, "query": query, "results": results}
    except Exception as e:
        return {"success": False, "query": query, "error": str(e), "results": []}
    finally:
        try:
            await context.close()
        except Exception:
            pass


async def _playwright_parallel_serp_async(
    queries: List[str],
    search_engine: str = "bing",
    per_query: int = 5,
    timeout_per_query: float = 20.0,
) -> List[Dict[str, Any]]:
    """单 browser 多 context 并行 SERP。"""
    from playwright.async_api import async_playwright

    if not queries:
        return []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:

            async def one(q: str):
                try:
                    return await asyncio.wait_for(
                        _serp_search_in_context(browser, q, search_engine, per_query),
                        timeout=timeout_per_query,
                    )
                except asyncio.TimeoutError:
                    return {
                        "success": False,
                        "query": q,
                        "error": "timeout",
                        "results": [],
                    }
                except Exception as e:
                    return {
                        "success": False,
                        "query": q,
                        "error": str(e),
                        "results": [],
                    }

            return list(await asyncio.gather(*[one(q) for q in queries]))
        finally:
            try:
                await browser.close()
            except Exception:
                pass


def playwright_parallel_serp(
    queries: List[str],
    search_engine: str = "bing",
    per_query: int = 5,
    timeout_per_query: float = 20.0,
) -> List[Dict[str, Any]]:
    """同步：并行 SERP（独立线程内事件循环，避免与 Qt 冲突）。"""
    import concurrent.futures

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                _playwright_parallel_serp_async(
                    queries, search_engine, per_query, timeout_per_query
                )
            )
        finally:
            loop.close()

    try:
        asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_run).result(timeout=max(60, timeout_per_query * len(queries) + 15))
    except RuntimeError:
        return _run()


async def _playwright_browse_multiple_async(urls: List[str], max_content_length: int = 5000) -> Dict[str, Any]:
    """浏览多个网页并提取内容"""
    tool = get_playwright_tool()
    try:
        await tool.start()
        
        results = []
        
        for i, url in enumerate(urls):
            try:
                print(f"📄 浏览页面 {i+1}/{len(urls)}: {url}")
                
                # 访问页面
                await tool.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await tool.page.wait_for_timeout(3000)  # 等待页面加载
                
                # 提取页面内容
                content = await tool._extract_page_content(max_content_length)
                
                # 提取页面标题
                title = await tool.page.title()
                
                results.append({
                    "url": url,
                    "title": title,
                    "content": content,
                    "success": True
                })
                
                # 添加延迟避免被阻止
                if i < len(urls) - 1:
                    await tool.page.wait_for_timeout(2000)
                    
            except Exception as e:
                print(f"⚠️ 浏览页面失败 {url}: {e}")
                results.append({
                    "url": url,
                    "title": "页面加载失败",
                    "content": f"页面加载失败: {str(e)}",
                    "success": False
                })
        
        return {
            "success": True,
            "results": results,
            "count": len(results),
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "results": []
        }

def playwright_browse_multiple(urls: List[str], max_content_length: int = 5000) -> Dict[str, Any]:
    """同步方式调用多页面浏览 - 使用持久化事件循环"""
    loop = get_or_create_event_loop()
    
    try:
        # 检查是否在Qt事件循环中运行
        try:
            running_loop = asyncio.get_running_loop()
            # 使用新线程运行
            import concurrent.futures
            
            def run_in_thread():
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(_playwright_browse_multiple_async(urls, max_content_length))
            
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_thread)
                return future.result(timeout=120)
        except RuntimeError:
            # 直接使用全局循环
            return loop.run_until_complete(_playwright_browse_multiple_async(urls, max_content_length))
    except Exception as e:
        return {"success": False, "error": str(e), "results": []}

