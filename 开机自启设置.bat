@echo off
rem Keep this file ASCII-only: cmd parses .bat as GBK on zh-CN Windows,
rem so UTF-8 Chinese here would turn into mojibake.

echo.
echo   ============================================
echo    Danmaku - Enable auto start
echo   ============================================
echo.
echo   The Windows "Startup" folder will open in a moment.
echo.
echo   Drag a SHORTCUT of "danmaku.lnk" (in this folder)
echo   into it to run the danmaku automatically at logon.
echo.
echo   To disable: just delete that shortcut.
echo.
pause

explorer "shell:startup"
exit /b 0
