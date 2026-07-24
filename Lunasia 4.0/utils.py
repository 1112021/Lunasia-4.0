# -*- coding: utf-8 -*-
"""
工具函数模块
包含系统工具、辅助函数和通用功能
"""

import os
import winreg
import requests
import subprocess
import webbrowser

def scan_windows_apps():
    """扫描Windows注册应用"""
    app_map = {}

    try:
        # 扫描开始菜单快捷方式
        start_menu_paths = [
            os.path.join(os.environ['APPDATA'], 'Microsoft', 'Windows', 'Start Menu', 'Programs'),
            os.path.join(os.environ['ProgramData'], 'Microsoft', 'Windows', 'Start Menu', 'Programs')
        ]

        for path in start_menu_paths:
            for root, _, files in os.walk(path):
                for file in files:
                    if file.lower().endswith('.lnk'):
                        app_name = os.path.splitext(file)[0]
                        app_path = os.path.join(root, file)
                        app_map[app_name] = app_path
    except Exception as e:
        print(f"扫描开始菜单快捷方式失败: {str(e)}")

    try:
        # 扫描注册表中的应用
        reg_paths = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
            r"SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\App Paths"
        ]

        for path in reg_paths:
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
                i = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        subkey = winreg.OpenKey(key, subkey_name)
                        try:
                            app_path, _ = winreg.QueryValueEx(subkey, "")
                            if app_path and os.path.exists(app_path):
                                app_name = os.path.splitext(subkey_name)[0]
                                app_map[app_name] = app_path
                        finally:
                            winreg.CloseKey(subkey)
                        i += 1
                    except OSError:
                        break
            except:
                continue
    except Exception as e:
        print(f"扫描注册表应用失败: {str(e)}")

    return app_map

def get_location():
    """获取地理位置"""
    try:
        response = requests.get('https://ipinfo.io/json')
        data = response.json()
        city = data.get('city', '未知城市')
        region = data.get('region', '未知地区')
        country = data.get('country', '未知国家')
        return f"{country}, {region}, {city}"
    except:
        return "未知位置"

def open_website(url, browser_name=""):
    """打开网站，支持指定浏览器"""
    try:
        if browser_name:
            # 尝试使用指定浏览器
            browser_paths = {
                "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                "firefox": r"C:\Program Files\Mozilla Firefox\firefox.exe",
                "edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                "ie": r"C:\Program Files\Internet Explorer\iexplore.exe"
            }
            
            if browser_name.lower() in browser_paths:
                browser_path = browser_paths[browser_name.lower()]
                if os.path.exists(browser_path):
                    subprocess.Popen([browser_path, url])
                    return f"已使用{browser_name}打开网站: {url}"
        
        # 使用默认浏览器
        webbrowser.open(url)
        return f"已打开网站: {url}"
    except Exception as e:
        return f"打开网站失败: {str(e)}"

def open_application(app_path):
    """打开应用程序
    
    使用subprocess + PowerShell/cmd的方式启动，避免os.startfile导致的进程崩溃问题
    """
    try:
        print(f"🚀 [utils.open_application] 尝试启动: {app_path}")
        print(f"🔍 [utils.open_application] 文件是否存在: {os.path.exists(app_path)}")
        
        import subprocess
        
        app_name = os.path.splitext(os.path.basename(app_path))[0]
        
        # 方法1: 使用PowerShell的Invoke-Item（最稳定的方式）
        try:
            print(f"🔄 [utils.open_application] 方法1: 使用PowerShell Invoke-Item")
            # Invoke-Item 是PowerShell中最接近双击文件的命令
            ps_command = f'Invoke-Item -Path "{app_path}"'
            
            # 使用Popen而非run，避免等待程序结束
            process = subprocess.Popen(
                ['powershell', '-WindowStyle', 'Hidden', '-Command', ps_command],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL
            )
            
            # 等待一小段时间检查是否立即失败
            import time
            time.sleep(0.5)
            
            if process.poll() is None or process.returncode == 0:
                print(f"✅ [utils.open_application] PowerShell Invoke-Item成功: {app_name}")
                return f"已启动应用程序: {app_name}"
            else:
                stderr = process.stderr.read().decode('utf-8', errors='ignore') if process.stderr else ""
                print(f"⚠️ [utils.open_application] Invoke-Item失败，返回码: {process.returncode}")
                if stderr:
                    print(f"⚠️ [utils.open_application] stderr: {stderr[:200]}")
                # 继续尝试下一个方法
        except Exception as e1:
            print(f"⚠️ [utils.open_application] PowerShell Invoke-Item异常: {e1}")
        
        # 方法2: 使用explorer.exe直接打开（Windows资源管理器）
        try:
            print(f"🔄 [utils.open_application] 方法2: 使用explorer.exe")
            subprocess.Popen(['explorer', app_path],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           stdin=subprocess.DEVNULL)
            
            print(f"✅ [utils.open_application] explorer.exe成功: {app_name}")
            return f"已启动应用程序: {app_name}"
        except Exception as e2:
            print(f"⚠️ [utils.open_application] explorer.exe失败: {e2}")
        
        # 方法3: 使用cmd start命令（最后的fallback）
        try:
            print(f"🔄 [utils.open_application] 方法3: 使用cmd start")
            # 使用Popen而非run，避免阻塞
            subprocess.Popen(
                ['cmd', '/c', 'start', '', app_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                shell=False
            )
            
            print(f"✅ [utils.open_application] cmd start成功: {app_name}")
            return f"已启动应用程序: {app_name}"
        except Exception as e3:
            print(f"❌ [utils.open_application] cmd start失败: {e3}")
            raise e3
        
    except Exception as e:
        print(f"❌ [utils.open_application] 所有方法都失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return f"无法启动应用程序: {str(e)}"

def search_web(query, search_engine="baidu", browser_name=""):
    """搜索网页，支持指定搜索引擎和浏览器"""
    try:
        search_engines = {
            "baidu": f"https://www.baidu.com/s?wd={query}",
            "google": f"https://www.google.com/search?q={query}",
            "bing": f"https://www.bing.com/search?q={query}",
            "sogou": f"https://www.sogou.com/web?query={query}"
        }
        
        if search_engine.lower() in search_engines:
            search_url = search_engines[search_engine.lower()]
        else:
            search_url = search_engines["baidu"]  # 默认使用百度
        
        # 使用指定浏览器打开搜索页面
        return open_website(search_url, browser_name)
        
    except Exception as e:
        return f"搜索失败: {str(e)}"
