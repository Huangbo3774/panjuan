@echo off
REM PanJuan PaperForge - one-shot self check
REM Switch console to UTF-8 first: our Python tools print Chinese on purpose
REM (sys.stdout.reconfigure(encoding="utf-8")), and cmd's default GBK codepage
REM would render that as mojibake.
chcp 65001 >nul
REM Usage: scripts\check.bat
REM NOTE: keep this file ASCII-only and CRLF. cmd reads .bat with the system ANSI
REM codepage (GBK on zh-CN, CP1252 on Western), so UTF-8 Chinese here turns into
REM garbage bytes that break command parsing.
REM Exit codes: 0 = pass, 1 = fail, 2 = missing local material (skip, not a failure)
cd /d "%~dp0.."

echo.
echo [ 1/18] layout algorithm unit tests
py -3.11 tests\test_layout.py || goto :fail

echo.
echo [ 2/18] extractor unit tests (positive + counter-examples)
py -3.11 tests\test_extractor.py || goto :fail

echo.
echo [ 3/18] grading engine unit tests (PRD F14)
py -3.11 tests\test_grading.py || goto :fail

echo.
echo [ 4/18] SQLite storage round-trip (papers / questions / key / submissions)
py -3.11 tests\test_storage.py || goto :fail

echo.
echo [ 5/18] print formats: A3 spread + question figures + proofread CRUD
py -3.11 tests\test_print_formats.py || goto :fail

echo.
echo [ 6/18] figure cropping regression (two-column / section wall / PDF embed)
py -3.11 tests\test_figures.py || goto :fail

echo.
echo [ 7/18] gate self-check: revert figure rules to old behaviour, tests must go red
py -3.11 tests\break_figures.py || goto :fail

echo.
echo [ 8/18] gate self-check: re-inject fixed extractor defects, tests must go red
py -3.11 tests\break_extractor.py || goto :fail

echo.
echo [ 9/18] gate self-check: re-inject fixed grading defects, tests must go red
py -3.11 tests\break_grading.py || goto :fail

echo.
echo [ 10/18] frontend JS syntax + render check
py -3.11 tests\check_web_js.py || goto :fail

echo.
echo [ 11/18] script encoding (ps1 needs UTF-8 BOM, bat must stay ASCII)
py -3.11 tests\check_script_encoding.py || goto :fail

echo.
echo [12/18] gate self-check: break the web/launcher gates on purpose, they must go red
py -3.11 tests\break_webgate.py || goto :fail

echo.
echo [13/18] real-sample parsing health check
py -3.11 tests\run_parsers.py >nul || goto :fail

echo.
echo [14/18] PRD F11 segmentation accuracy (needs local private samples)
py -3.11 tests\run_f11.py
if errorlevel 1 (
  if errorlevel 2 (
    echo   SKIPPED F11: no var\ocr\lines.json cache on this machine.
    echo   Real student papers are never committed, so this step is optional.
  ) else (
    goto :fail
  )
)

echo.
echo [15/18] mode B/C export renders real marks (offline PDF readback)
py -3.11 tests\test_answer_export.py || goto :fail

echo.
echo [16/18] acceptance F01-F11 over real HTTP
py -3.11 tests\acceptance.py || goto :fail

echo.
echo [17/18] acceptance F12-F18 (proofread / answer / key / grade / print modes)
py -3.11 tests\acceptance_v11.py || goto :fail

echo.
echo [18/18] release names: README must promise a name GitHub can actually serve
py -3.11 tests\check_release_names.py || goto :fail

echo.
echo ===== ALL CHECKS PASSED =====
exit /b 0

:fail
echo.
echo ===== SOME CHECKS FAILED, see output above =====
exit /b 1
