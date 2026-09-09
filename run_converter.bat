@echo off
setlocal
chcp 65001 >nul

set "TOOL_DIR=%~dp0"
set "PYTHONPATH=%TOOL_DIR%src"

where py >nul 2>&1
if %ERRORLEVEL% NEQ 0 goto check_python
py -3 -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if %ERRORLEVEL% EQU 0 goto run_py_launcher

:check_python
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 goto check_codex_python
python -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if %ERRORLEVEL% EQU 0 goto run_python

:check_codex_python
set "CODEX_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%CODEX_PYTHON%" goto python_missing
"%CODEX_PYTHON%" -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if %ERRORLEVEL% EQU 0 goto run_codex_python

:python_missing
echo Error: Python 3 was not found. Please install Python 3.10 or newer. 1>&2
set "EXIT_CODE=2"
goto finish

:run_py_launcher
py -3 -X utf8 -m step_to_acis %*
set "EXIT_CODE=%ERRORLEVEL%"
goto finish

:run_python
python -X utf8 -m step_to_acis %*
set "EXIT_CODE=%ERRORLEVEL%"
goto finish

:run_codex_python
"%CODEX_PYTHON%" -X utf8 -m step_to_acis %*
set "EXIT_CODE=%ERRORLEVEL%"

:finish
if not "%STEP_TO_ACIS_NO_PAUSE%"=="1" pause
exit /b %EXIT_CODE%
