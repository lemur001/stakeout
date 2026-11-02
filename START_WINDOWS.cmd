@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python 3.12 or 3.13 is required. Install Python with the Windows launcher, then run this file again.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo.
echo Opening the local app server. Keep this window open.
echo Visit the address printed below. The default is http://127.0.0.1:8080
.venv\Scripts\python.exe run.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo Startup failed. Read the error above. See README.md for setup and port-conflict instructions.
pause
exit /b 1
