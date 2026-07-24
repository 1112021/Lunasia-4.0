#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CDP调试端口辅助工具
用于检测和启动浏览器调试模式
"""

import requests
import subprocess
import time
import os
from pathlib import Path

def check_cdp_connection(cdp_url: str = "http://localhost:9222", timeout: int = 2) -> bool:
    """
    检查CDP调试端口是否可用
    
    Args:
        cdp_url: CDP地址
        timeout: 超时时间（秒）
        
    Returns:
        bool: 端口可用返回True，否则返回False
    """
    try:
        test_url = f"{cdp_url}/json"
        response = requests.get(test_url, timeout=timeout)
        return response.status_code == 200
    except:
        return False


def get_browser_path(browser_type: str) -> str:
    """
    获取浏览器可执行文件路径
    
    Args:
        browser_type: 浏览器类型 (edge, chrome, chromium)
        
    Returns:
        str: 浏览器路径，未找到返回空字符串
    """
    browser_type = browser_type.lower()
    
    browser_paths = {
        "edge": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ],
        "chrome": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ],
        "chromium": [
            r"C:\Program Files\Chromium\Application\chrome.exe",
            r"C:\Program Files (x86)\Chromium\Application\chrome.exe",
        ]
    }
    
    # 如果是其他名称，尝试作为edge处理
    paths = browser_paths.get(browser_type, browser_paths.get("edge", []))
    
    for path in paths:
        if os.path.exists(path):
            return path
    
    return ""


def start_browser_debug_mode(
    browser_type: str = "edge",
    debug_port: int = 9222,
    user_data_dir: str = ""
) -> dict:
    """
    启动浏览器调试模式
    
    Args:
        browser_type: 浏览器类型
        debug_port: 调试端口
        user_data_dir: 用户数据目录
        
    Returns:
        dict: {"success": bool, "message": str}
    """
    # 获取浏览器路径
    browser_path = get_browser_path(browser_type)
    if not browser_path:
        return {
            "success": False,
            "message": f"未找到 {browser_type} 浏览器"
        }
    
    # Firefox不支持CDP
    if browser_type.lower() == "firefox":
        return {
            "success": False,
            "message": "Firefox 不支持 CDP 调试模式"
        }
    
    # 设置用户数据目录
    if not user_data_dir:
        user_data_dir = str(Path.home() / ".lunesia" / f"{browser_type}_debug_profile")
    
    # 创建数据目录
    os.makedirs(user_data_dir, exist_ok=True)
    
    # 启动参数
    args = [
        browser_path,
        f"--remote-debugging-port={debug_port}",
        f"--user-data-dir={user_data_dir}"
    ]
    
    try:
        # Windows: 使用 DETACHED_PROCESS 让浏览器独立运行
        import sys
        if sys.platform == "win32":
            DETACHED_PROCESS = 0x00000008
            subprocess.Popen(
                args,
                creationflags=DETACHED_PROCESS,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        else:
            # Unix: 使用 start_new_session
            subprocess.Popen(
                args,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        
        # 等待浏览器启动
        print(f"[CDP] 等待 {browser_type} 启动调试模式...")
        for i in range(10):  # 最多等待5秒
            time.sleep(0.5)
            if check_cdp_connection(f"http://localhost:{debug_port}"):
                print(f"[CDP] {browser_type} 调试模式已启动（端口: {debug_port}）")
                return {
                    "success": True,
                    "message": f"{browser_type} 调试模式已启动"
                }
        
        # 超时
        return {
            "success": False,
            "message": f"{browser_type} 启动超时，但进程已创建"
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"启动失败: {str(e)}"
        }


def ensure_cdp_connection(
    cdp_url: str = "http://localhost:9222",
    browser_type: str = "edge",
    user_data_dir: str = ""
) -> dict:
    """
    确保CDP连接可用，如果不可用则自动启动浏览器
    
    Args:
        cdp_url: CDP地址
        browser_type: 浏览器类型
        user_data_dir: 用户数据目录
        
    Returns:
        dict: {"success": bool, "message": str, "auto_started": bool}
    """
    # 提取端口号
    try:
        port = int(cdp_url.split(":")[-1].rstrip("/"))
    except:
        port = 9222
    
    # 检查连接
    if check_cdp_connection(cdp_url):
        return {
            "success": True,
            "message": "CDP连接已就绪",
            "auto_started": False
        }
    
    # 连接不可用，尝试启动浏览器
    print(f"[CDP] 端口 {port} 未开启，尝试自动启动 {browser_type}...")
    
    result = start_browser_debug_mode(browser_type, port, user_data_dir)
    
    if result["success"]:
        return {
            "success": True,
            "message": f"已自动启动 {browser_type} 调试模式",
            "auto_started": True
        }
    else:
        return {
            "success": False,
            "message": f"无法启动调试模式: {result['message']}",
            "auto_started": False
        }


if __name__ == "__main__":
    # 测试
    print("测试CDP辅助工具")
    print("=" * 50)
    
    # 测试1: 检查连接
    print("\n1. 检查CDP连接...")
    is_connected = check_cdp_connection()
    print(f"   结果: {'已连接' if is_connected else '未连接'}")
    
    # 测试2: 确保连接（会自动启动）
    print("\n2. 确保CDP连接...")
    result = ensure_cdp_connection(browser_type="edge")
    print(f"   成功: {result['success']}")
    print(f"   消息: {result['message']}")
    print(f"   自动启动: {result['auto_started']}")
    
    print("\n" + "=" * 50)

