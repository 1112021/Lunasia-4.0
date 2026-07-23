@echo off
chcp 65001 >nul
echo ========================================
echo    露尼西亚 - Edge 调试模式启动器
echo ========================================
echo.
echo 🚀 正在启动 Edge 调试模式...
echo 📡 调试端口: 9222
echo 💾 数据目录: %USERPROFILE%\.lunesia\edge_profile
echo.

REM 创建数据目录
if not exist "%USERPROFILE%\.lunesia\edge_profile" (
    mkdir "%USERPROFILE%\.lunesia\edge_profile"
    echo ✅ 已创建数据目录
)

REM 尝试多个可能的 Edge 路径
set EDGE_PATH=""

if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" (
    set EDGE_PATH="C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
)

if exist "C:\Program Files\Microsoft\Edge\Application\msedge.exe" (
    set EDGE_PATH="C:\Program Files\Microsoft\Edge\Application\msedge.exe"
)

if %EDGE_PATH%=="" (
    echo ❌ 错误：未找到 Microsoft Edge
    echo.
    echo 请检查 Edge 是否已安装在以下位置：
    echo   - C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe
    echo   - C:\Program Files\Microsoft\Edge\Application\msedge.exe
    echo.
    pause
    exit /b 1
)

REM 启动 Edge
echo 📂 Edge 路径: %EDGE_PATH%
echo.
%EDGE_PATH% --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\.lunesia\edge_profile"

REM 等待端口启动
timeout /t 2 /nobreak >nul

echo ✅ Edge 调试模式已启动！
echo.
echo 💡 使用说明：
echo   1. Edge 浏览器已在调试模式下启动
echo   2. 调试端口: http://localhost:9222
echo   3. 现在可以使用露尼西亚了
echo.
echo 🔗 验证连接（可选）：
echo   在浏览器访问: http://localhost:9222/json
echo.
echo ⚠️ 注意：
echo   - 使用完毕后请关闭 Edge 浏览器
echo   - 不要关闭此命令窗口
echo.
pause

