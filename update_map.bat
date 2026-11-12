@echo off
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (python update_map.py) else (py update_map.py)
echo.
pause
