@echo off
rem Keep this file ASCII-only: cmd parses .bat as GBK on zh-CN Windows,
rem so UTF-8 Chinese here would turn into mojibake.

echo.
echo   Stopping danmaku...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python' -and $_.CommandLine -like '*danmaku.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
echo   Done.
timeout /t 2 >nul
exit /b 0
