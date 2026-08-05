@echo off
if "%~1"=="__child" goto :child
cmd /c "%~f0" __child %* <NUL
goto :eof

:child
shift
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0warranty-windows.ps1" %1 %2 %3 %4 %5 %6 %7 %8 %9
exit /b %ERRORLEVEL%
