@echo off
chcp 65001 >nul
title 露尼西亚AI助手
cd /d "%~dp0"

echo.
echo ========================================
echo           露尼西亚AI助手
echo ========================================
echo.

:: 检查Python是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 错误：未找到Python，请先安装Python 3.8或更高版本
    echo.
    echo 下载地址：https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 显示Python版本
echo ✅ Python版本：
python --version

:: 检查是否在项目目录
if not exist "main.py" (
    echo ❌ 错误：未找到main.py文件
    echo 请确保在露尼西亚项目目录中运行此脚本
    pause
    exit /b 1
)

:: 安装依赖包
echo.
echo 📦 正在安装依赖包...
echo.
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ⚠️ 警告：部分依赖安装可能失败，但将继续尝试启动程序
    echo.
) else (
    echo.
    echo ✅ 依赖安装完成
    echo.
)

:: 检查并安装本地 F5-TTS Sidecar 环境
if not exist "tools\f5tts_env\Scripts\python.exe" (
    echo.
    echo 🎤 未检测到 F5-TTS 独立环境，正在创建（首次下载体积较大）...
    powershell -NoProfile -ExecutionPolicy Bypass -File "tools\setup_f5tts.ps1"
    if errorlevel 1 (
        echo ⚠️ F5-TTS 环境安装失败；云端 TTS 和其他功能仍可使用
    )
) else (
    "tools\f5tts_env\Scripts\python.exe" -c "import torch, f5_tts, soundfile, scipy; print('✅ F5-TTS 环境可用，CUDA:', torch.cuda.is_available())"
    if errorlevel 1 (
        echo ⚠️ F5-TTS 环境损坏，请执行：
        echo powershell -ExecutionPolicy Bypass -File tools\setup_f5tts.ps1 -Rebuild
    )
)

:: 空参考文稿自动识别需要 FFmpeg CLI；Sidecar 会自动定位 WinGet 安装目录
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo.
    echo 🎞️ 未在当前 PATH 找到 FFmpeg，正在尝试通过 winget 安装...
    winget install --id Gyan.FFmpeg --exact --accept-package-agreements --accept-source-agreements --disable-interactivity
    if errorlevel 1 (
        echo ⚠️ FFmpeg 自动安装失败；请手动安装后重启程序
    )
)

:: 启动露尼西亚
echo 🚀 正在启动露尼西亚AI助手...
echo.
python main.py

:: 如果程序异常退出，显示错误信息
if errorlevel 1 (
    echo.
    echo ❌ 程序异常退出，错误代码：%errorlevel%
    echo.
    echo 可能的解决方案：
    echo 1. 检查配置文件是否正确
    echo 2. 重新安装依赖包
    echo    pip install -r requirements.txt
    echo 3. 如果遇到DuckDuckGo搜索错误
    echo    pip install ddgs
    echo 4. 如果遇到PyTorch DLL错误
    echo    安装 Visual C++ Redistributable
    echo    或重新安装 PyTorch: pip install torch --force-reinstall
    echo 5. 检查API密钥配置
    echo.
)

echo.
echo 按任意键退出...
pause >nul
