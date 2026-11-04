@echo off
chcp 65001 >nul
setlocal EnableExtensions
title OwlCheck installer
cd /d "%~dp0.."

echo.
echo    OwlCheck - building the Windows installer
echo    ------------------------------------------
echo.

if not exist ".venv\Scripts\python.exe" goto :no_venv

:build
".venv\Scripts\python.exe" packaging\build_exe.py --installer
if errorlevel 3 goto :no_inno
if errorlevel 1 goto :failed
echo.
echo The installer is in the dist folder. Opening it...
start "" "%CD%\dist"
goto :end

:no_venv
echo Run "Install OwlCheck.bat" first: it sets up Python and builds OwlCheck.exe.
goto :end

:no_inno
echo.
echo Inno Setup is needed to build the installer. It's free and only needed once.
where winget >nul 2>&1
if errorlevel 1 goto :manual
choice /c YN /m "Install Inno Setup now with winget"
if errorlevel 2 goto :manual
winget install -e --id JRSoftware.InnoSetup --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto :manual
echo.
goto :build

:manual
echo Download Inno Setup from https://jrsoftware.org/isdl.php , install it and run this file again.
goto :end

:failed
echo.
echo Building the installer failed. Copy the messages above into a bug report.

:end
echo.
pause
