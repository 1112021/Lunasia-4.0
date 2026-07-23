@echo off
chcp 65001 >nul
title 露尼西亚AI助手 - 快速启动
cd /d "%~dp0"

:: 快速检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 错误：未找到Python
    echo 请使用"启动露尼西亚.bat"进行完整检查和安装
    pause
    exit /b 1
)

:: 快速检查项目目录
if not exist "main.py" (
    echo ❌ 错误：未找到main.py文件
    echo 请确保在露尼西亚项目目录中运行此脚本
    pause
    exit /b 1
)

:: 快速检查可选的本地 F5-TTS 环境
if not exist "tools\f5tts_env\Scripts\python.exe" (
    echo ⚠️ 未安装 F5-TTS 独立环境；本地语音合成不可用
    echo    请运行"启动露尼西亚.bat"或 tools\setup_f5tts.ps1
) else (
    "tools\f5tts_env\Scripts\python.exe" -c "import torch, f5_tts, soundfile, scipy" >nul 2>&1
    if errorlevel 1 (
        echo ⚠️ F5-TTS 环境校验失败；建议使用完整版启动脚本修复
    )
)

echo 🚀 启动露尼西亚AI助手...
python main.py

if errorlevel 1 (
    echo.
    echo ❌ 启动失败，请检查：
    echo 1. Python环境是否正确
    echo 2. 依赖包是否已安装
    echo 3. 配置文件是否正确
    echo.
    echo 💡 提示：使用"启动露尼西亚.bat"可自动检查并修复问题
    pause
)
