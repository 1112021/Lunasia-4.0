# -*- coding: utf-8 -*-
"""
异步资源管理器
用于正确清理所有异步资源，避免退出时的警告信息
"""

import asyncio
import warnings
from typing import List, Optional


def close_event_loop(loop: Optional[asyncio.AbstractEventLoop]) -> None:
    """安全关闭事件循环，取消待处理任务并释放 Proactor 管道。"""
    if loop is None or loop.is_closed():
        return
    try:
        if hasattr(asyncio, "all_tasks"):
            pending = asyncio.all_tasks(loop)
        else:
            pending = asyncio.Task.all_tasks(loop)
        for task in pending:
            try:
                task.cancel()
            except Exception:
                pass
        if pending:
            try:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            except Exception:
                pass
        try:
            loop.run_until_complete(asyncio.sleep(0.1))
        except Exception:
            pass
        try:
            if hasattr(loop, "shutdown_asyncgens"):
                loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()
    except Exception:
        pass


class AsyncResourceManager:
    """异步资源管理器 - 统一管理所有异步资源的生命周期"""
    
    def __init__(self):
        self.resources: List = []
        self.event_loops: List[asyncio.AbstractEventLoop] = []
        self._cleanup_in_progress = False
        self._finalized = False
        
        # 抑制资源警告
        warnings.filterwarnings("ignore", category=ResourceWarning)
        warnings.filterwarnings("ignore", message=".*unclosed.*")
    
    def register_resource(self, resource):
        """注册需要清理的资源"""
        if resource not in self.resources:
            self.resources.append(resource)
    
    def register_event_loop(self, loop: asyncio.AbstractEventLoop):
        """注册事件循环"""
        if loop not in self.event_loops:
            self.event_loops.append(loop)
    
    def cleanup_all(self):
        """清理所有资源（运行期调用；退出请用 finalize_shutdown）。"""
        if self._cleanup_in_progress or self._finalized:
            return
        
        self._cleanup_in_progress = True
        
        try:
            # 不打印开始信息，保持静默
            
            # 1. 清理所有注册的资源
            for resource in self.resources:
                try:
                    if hasattr(resource, 'close_sync') and callable(resource.close_sync):
                        # 优先使用同步关闭方法
                        resource.close_sync()
                    elif hasattr(resource, 'close') and callable(resource.close):
                        if asyncio.iscoroutinefunction(resource.close):
                            # 异步close方法
                            try:
                                # 尝试获取运行中的事件循环
                                try:
                                    loop = asyncio.get_running_loop()
                                except RuntimeError:
                                    loop = None
                                
                                if loop and not loop.is_closed():
                                    # 在运行中的循环创建任务
                                    asyncio.create_task(resource.close())
                                else:
                                    # 退出阶段不应再创建新循环（由 finalize_shutdown 处理）
                                    pass
                            except:
                                pass
                        else:
                            # 同步close方法
                            resource.close()
                except Exception:
                    # 静默处理清理错误
                    pass
            
            # 2. 清理所有事件循环
            for loop in list(self.event_loops):
                close_event_loop(loop)
            
            # 静默完成，不打印
            
        except Exception:
            # 静默处理任何清理错误
            pass
        finally:
            self._cleanup_in_progress = False

    def finalize_shutdown(self):
        """程序退出：仅关闭已注册事件循环，不再 new_event_loop 或重复 close_sync。"""
        if self._finalized or self._cleanup_in_progress:
            return
        self._cleanup_in_progress = True
        try:
            self._finalized = True
            for loop in list(self.event_loops):
                close_event_loop(loop)
            self.event_loops.clear()
            self.resources.clear()
        except Exception:
            pass
        finally:
            self._cleanup_in_progress = False
    
    def _cancel_all_tasks(self, loop: asyncio.AbstractEventLoop):
        """取消事件循环中的所有任务"""
        try:
            # 获取所有待处理的任务
            if hasattr(asyncio, 'all_tasks'):
                pending = asyncio.all_tasks(loop)
            else:
                pending = asyncio.Task.all_tasks(loop)
            
            # 取消所有任务
            for task in pending:
                try:
                    task.cancel()
                except:
                    pass
            
            # 等待所有任务完成取消
            if pending:
                try:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except:
                    pass
                    
        except Exception as e:
            # 静默处理
            pass
    
    def __del__(self):
        """析构时确保清理"""
        if not self._cleanup_in_progress:
            self.cleanup_all()


# 全局资源管理器实例
_global_resource_manager: Optional[AsyncResourceManager] = None


def get_resource_manager() -> AsyncResourceManager:
    """获取全局资源管理器"""
    global _global_resource_manager
    if _global_resource_manager is None:
        _global_resource_manager = AsyncResourceManager()
    return _global_resource_manager


def finalize_async_shutdown():
    """退出前由主窗口调用：关闭 asyncio 循环后不再重复清理。"""
    global _global_resource_manager
    if _global_resource_manager is None:
        return
    _global_resource_manager.finalize_shutdown()
    _global_resource_manager = None


def cleanup_on_exit():
    """程序退出时的清理函数（atexit；若已 finalize 则跳过）。"""
    global _global_resource_manager
    if _global_resource_manager is None:
        return
    if getattr(_global_resource_manager, "_finalized", False):
        _global_resource_manager = None
        return
    _global_resource_manager.cleanup_all()
    _global_resource_manager = None

