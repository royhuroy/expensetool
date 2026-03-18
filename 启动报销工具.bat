@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo  ╔══════════════════════════════════════╗
echo  ║     费用报销自动化工具               ║
echo  ╚══════════════════════════════════════╝
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [错误] 未找到 Python，请先安装 Python 3.10+
    echo  下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Check if Streamlit is installed
python -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo  正在安装依赖包，首次运行可能需要几分钟...
    echo.
    pip install -r requirements.txt -q
    if errorlevel 1 (
        echo  [错误] 依赖安装失败，请检查网络连接
        pause
        exit /b 1
    )
    echo  依赖安装完成！
    echo.
)

:: Check .env file
if not exist ".env" (
    if exist ".env.example" (
        echo  [提示] 未找到 .env 文件
        echo  请复制 .env.example 为 .env 并填入您的 DeepSeek API Key
        echo.
        pause
        exit /b 1
    )
)

echo  正在启动报销工具（浏览器将自动打开）...
echo  如需停止，请按 Ctrl+C 或关闭此窗口
echo.

start "" http://localhost:8501
streamlit run src/app.py --server.headless true --browser.gatherUsageStats false

pause
