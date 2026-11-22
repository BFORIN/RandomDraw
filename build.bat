@echo off
rem ============================================================
rem  RandomDraw - Windows 一键打包脚本
rem  用法：双击运行，或在项目目录执行 build.bat
rem  依赖：Python 3 + PyInstaller（pip install pyinstaller）
rem  产物：dist\RandomDraw.exe，并分发到 %USERPROFILE%\Public\
rem  注：config.json 由程序首次运行自动生成，不随包复制
rem ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ==^> [1/4] 检查 Python ...
where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (
    where python >nul 2>nul
    if !errorlevel!==0 (set "PY=python") else (
        echo [错误] 未找到 Python，请先安装 Python 3 并加入 PATH
        exit /b 1
    )
)

echo ==^> [2/4] 检查 PyInstaller ...
%PY% -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo [错误] 未安装 PyInstaller，请先执行：%PY% -m pip install pyinstaller
    exit /b 1
)

echo ==^> [3/4] 打包 RandomDraw.exe（PyInstaller onefile/windowed）...
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name RandomDraw random_draw.py
if errorlevel 1 (
    echo [错误] PyInstaller 打包失败
    exit /b 1
)
if not exist dist\RandomDraw.exe (
    echo [错误] 未生成 dist\RandomDraw.exe
    exit /b 1
)

echo ==^> [4/4] 分发到 Public（config.json 由程序首次运行自动生成）...
if not exist "%USERPROFILE%\Public" mkdir "%USERPROFILE%\Public"
copy /y dist\RandomDraw.exe "%USERPROFILE%\Public\" >nul
if errorlevel 1 (
    echo [错误] 复制到 Public 失败
    exit /b 1
)

echo.
echo [OK] 打包并分发完成
echo     产物：%USERPROFILE%\Public\RandomDraw.exe
endlocal
