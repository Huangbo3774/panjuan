@echo off
REM 磐卷 PaperForge · 一键跑全部自检
REM 用法: scripts\check.bat
cd /d "%~dp0.."

echo.
echo [1/4] 布局算法单测
py -3.11 tests\test_layout.py || goto :fail

echo.
echo [2/4] 前端 JS 语法与渲染检查
py -3.11 tests\check_web_js.py || goto :fail

echo.
echo [3/4] 真实材料解析体检
py -3.11 tests\run_parsers.py >nul || goto :fail
echo   11 份材料解析完成（明细 tests\parsers-report.json）

echo.
echo [4/4] PRD 验收 F01-F10
py -3.11 tests\acceptance.py || goto :fail

echo.
echo ===== 全部通过 =====
exit /b 0

:fail
echo.
echo ===== 有检查未通过，见上方输出 =====
exit /b 1
