#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Playwright 模式快速切换工具
"""

import json
import sys
import os

CONFIG_FILE = "ai_agent_config.json"

def load_config():
    """加载配置文件"""
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_config(config):
    """保存配置文件"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def show_current_config(config):
    """显示当前配置"""
    print("\n" + "=" * 60)
    print("  当前 Playwright 配置")
    print("=" * 60)
    print()
    print(f"  浏览器:         {config.get('default_browser', 'chromium')}")
    print(f"  模式:           {config.get('playwright_mode', 'launch')}")
    print(f"  持久化:         {config.get('playwright_persistent', False)}")
    print(f"  慢速模式:       {config.get('playwright_slow_mo', 0)} ms")
    print(f"  CDP地址:        {config.get('playwright_cdp_url', 'http://localhost:9222')}")
    print(f"  用户数据目录:   {config.get('playwright_user_data_dir', '(未设置)')}")
    print()
    print("=" * 60)
    print()

def switch_mode():
    """切换模式"""
    config = load_config()
    
    print("\n" + "=" * 60)
    print("  Playwright 模式切换工具")
    print("=" * 60)
    print()
    print("请选择模式:")
    print()
    print("  [1] Launch 模式（快速启动，不保存状态）")
    print("      - 自动启动新浏览器")
    print("      - 每次都是干净状态")
    print("      - 推荐日常使用")
    print()
    print("  [2] Persistent 模式（保存登录状态）")
    print("      - 自动启动浏览器")
    print("      - 保存 Cookie、登录状态")
    print("      - 推荐需要登录的网站")
    print()
    print("  [3] Connect 模式（调试专用）")
    print("      - 连接已运行的浏览器")
    print("      - 可实时观察操作")
    print("      - 需要手动启动调试浏览器")
    print()
    print("  [4] 显示当前配置")
    print("  [0] 退出")
    print()
    
    choice = input("请输入选项 [0-4]: ").strip()
    
    if choice == "1":
        # Launch 模式
        config["playwright_mode"] = "launch"
        config["playwright_persistent"] = False
        config["playwright_slow_mo"] = 0
        print("\n[OK] 已切换到 Launch 模式（快速启动）")
        print("     - 自动启动浏览器")
        print("     - 不保存状态")
        print("     - 无需额外操作")
        
    elif choice == "2":
        # Persistent 模式
        config["playwright_mode"] = "launch"
        config["playwright_persistent"] = True
        
        # 询问用户数据目录
        print()
        default_dir = os.path.expanduser("~/.lunesia/browser_data")
        user_dir = input(f"用户数据目录 (回车使用默认: {default_dir}): ").strip()
        config["playwright_user_data_dir"] = user_dir if user_dir else default_dir
        
        print("\n[OK] 已切换到 Persistent 模式（保存状态）")
        print("     - 自动启动浏览器")
        print("     - 保存登录状态")
        print(f"     - 数据目录: {config['playwright_user_data_dir']}")
        
    elif choice == "3":
        # Connect 模式
        config["playwright_mode"] = "connect"
        
        # 询问是否需要慢速模式
        print()
        slow_mo = input("慢速模式延迟 (ms, 回车跳过): ").strip()
        if slow_mo.isdigit():
            config["playwright_slow_mo"] = int(slow_mo)
        
        # 询问 CDP 地址
        cdp = input("CDP 地址 (回车使用默认: http://localhost:9222): ").strip()
        if cdp:
            config["playwright_cdp_url"] = cdp
        
        print("\n[OK] 已切换到 Connect 模式（调试专用）")
        print("     - 需要手动启动调试浏览器")
        print(f"     - CDP 地址: {config['playwright_cdp_url']}")
        print()
        print("[!] 使用前请先启动调试浏览器:")
        print("     1. 运行: start_edge_debug.bat")
        print("     2. 或手动: msedge.exe --remote-debugging-port=9222")
        print("     3. 验证: python test_edge_connection.py")
        
    elif choice == "4":
        show_current_config(config)
        return
        
    elif choice == "0":
        print("\n再见！")
        return
        
    else:
        print("\n[ERROR] 无效选项")
        return
    
    # 保存配置
    save_config(config)
    print()
    print("[OK] 配置已保存到", CONFIG_FILE)
    print()
    
    # 显示新配置
    show_current_config(config)
    
    print("\n[!] 请重启露尼西亚以使配置生效")
    print()

if __name__ == "__main__":
    try:
        switch_mode()
    except KeyboardInterrupt:
        print("\n\n用户取消操作")
    except Exception as e:
        print(f"\n[ERROR] {str(e)}")
        sys.exit(1)

