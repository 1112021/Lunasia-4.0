#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
独立浏览器启动器
使用 subprocess 启动浏览器作为独立进程，不受 Playwright 生命周期控制
"""

import subprocess
import time
import requests
from pathlib import Path

def launch_browser_detached(browser_type="firefox", debug_port=9222):
    """
    启动独立的浏览器进程（不受父进程控制）
    
    Args:
        browser_type: 浏览器类型 (firefox, chrome, edge)
        debug_port: 调试端口
        
    Returns:
        dict: {"success": bool, "port": int, "pid": int}
    """
    browser_type = browser_type.lower()
    
    # 浏览器可执行文件路径
    browser_paths = {
        "firefox": [
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        ],
        "chrome": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ],
        "edge": [
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ]
    }
    
    # 查找浏览器
    browser_exe = None
    for path in browser_paths.get(browser_type, []):
        if Path(path).exists():
            browser_exe = path
            break
    
    if not browser_exe:
        return {"success": False, "error": f"未找到 {browser_type} 浏览器"}
    
    # 启动参数
    if browser_type == "firefox":
        # Firefox 不支持 CDP，无法用这种方式
        return {"success": False, "error": "Firefox 不支持远程调试协议"}
    else:
        # Chromium 系浏览器
        args = [
            browser_exe,
            f"--remote-debugging-port={debug_port}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
    
    try:
        # 使用 CREATE_NEW_PROCESS_GROUP 让浏览器成为独立进程组
        # 这样父进程退出时，浏览器不会被关闭
        import sys
        if sys.platform == "win32":
            # Windows: 使用 DETACHED_PROCESS
            DETACHED_PROCESS = 0x00000008
            process = subprocess.Popen(
                args,
                creationflags=DETACHED_PROCESS,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        else:
            # Unix: 使用 start_new_session
            process = subprocess.Popen(
                args,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        
        # 等待浏览器启动
        time.sleep(2)
        
        # 验证调试端口是否开放
        try:
            response = requests.get(f"http://localhost:{debug_port}/json", timeout=3)
            if response.status_code == 200:
                print(f"✅ {browser_type} 已作为独立进程启动（PID: {process.pid}，端口: {debug_port}）")
                return {
                    "success": True,
                    "port": debug_port,
                    "pid": process.pid,
                    "browser": browser_type
                }
        except:
            pass
        
        return {"success": False, "error": "浏览器启动但调试端口未开放"}
        
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    # 测试
    result = launch_browser_detached("edge", 9222)
    print(result)

