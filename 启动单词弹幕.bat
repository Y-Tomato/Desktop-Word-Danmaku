@echo off
rem Keep this file ASCII-only: cmd parses .bat as GBK on zh-CN Windows, so
rem UTF-8 Chinese here would turn into mojibake and START would silently
rem fail to find the script -> double-click does nothing.

set "APP=%~dp0danmaku.py"

rem 1) pythonw.exe on PATH
set "PYW="
for %%P in (pythonw.exe) do set "PYW=%%~$PATH:P"

rem 2) per-user install (uses %LOCALAPPDATA%, so no user name is hardcoded)
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"

rem 3) system-wide install
if not defined PYW if exist "C:\Python312\pythonw.exe" set "PYW=C:\Python312\pythonw.exe"

if not exist "%APP%" goto NOAPP
if not defined PYW goto NOPY

start "" "%PYW%" "%APP%" --run
exit /b 0

:NOPY
echo.
echo   [ERROR] pythonw.exe not found.
echo.
echo   Install Python 3.11+ and tick "Add python.exe to PATH",
echo   or edit the PYW lines in this file to point at your pythonw.exe.
echo.
pause
exit /b 1

:NOAPP
echo.
echo   [ERROR] danmaku.py not found next to this .bat
echo   %APP%
echo.
pause
exit /b 1
