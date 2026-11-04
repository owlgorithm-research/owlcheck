@echo off
rem Keep this file UTF-8 without a BOM and with CRLF endings: cmd runs a BOM as a command
rem and loses labels in LF-only files. chcp 65001 must come before the first non-ASCII line.
chcp 65001 >nul
setlocal EnableExtensions
title OwlCheck setup
cd /d "%~dp0"

echo.
echo     ▄            ▄
echo      ██▄▄▄▄▄▄▄▄██      OwlCheck
echo     █▀   ▀██▀   ▀█     Pre-release checker for Unity, Godot and GameMaker
echo     █  ██ ██ ██  █
echo     ██▄▄▄█  █▄▄▄██     Developed by PΛTTRN
echo      █ ████████ █      Owlgorithm Research
echo      ▀█▄██████▄█▀
echo    ▄▄▄▄▄██▄▄██▄▄▄▄▄
echo.

rem Opening the .bat straight from the zip runs it from a Temp copy with nothing next to it
if not exist "%~dp0requirements-app.txt" goto :not_extracted
echo %~dp0 | find /i "\AppData\Local\Temp\" >nul && goto :not_extracted

set "VENV=%~dp0.venv"
set "VPY=%VENV%\Scripts\python.exe"
set "VPYW=%VENV%\Scripts\pythonw.exe"

:begin
if exist "%VPY%" goto :check_deps

call :find_python
if not defined PY goto :no_python

:create_venv
echo [1/4] Setting up OwlCheck's environment. This only happens the first time...
%PY% -m venv "%VENV%"
if errorlevel 1 goto :fail_venv

:check_deps
"%VPY%" -c "import webview" >nul 2>&1
if not errorlevel 1 goto :check_clr
echo [2/4] Installing what the app needs. This can take a minute or two...
"%VPY%" -m pip install --disable-pip-version-check -q --upgrade pip
"%VPY%" -m pip install --disable-pip-version-check -r requirements-app.txt
if errorlevel 1 goto :fail_pip

:check_clr
"%VPY%" -c "import clr" >nul 2>&1
if errorlevel 1 goto :fail_clr

echo [3/4] Checking the app...
"%VPY%" -c "import sys; sys.path.insert(0, 'app'); import app"
if errorlevel 1 goto :fail_app

rem build_exe.py returns right away when the sources haven't changed
echo [4/4] Checking OwlCheck.exe...
set "OWL_EXE=%~dp0dist\OwlCheck\OwlCheck.exe"
"%VPY%" packaging\build_exe.py
if errorlevel 1 goto :exe_failed
if not exist "%OWL_EXE%" goto :exe_missing
goto :shortcut

:exe_failed
echo.
echo Couldn't build OwlCheck.exe. If OwlCheck is open, close it and run this
echo file again. For now, the app will open through Python.
set "OWL_EXE="
goto :shortcut

:exe_missing
echo.
echo OwlCheck.exe was built, but it's gone from the folder. Your antivirus most
echo likely quarantined it ^(a false positive, common with unsigned apps^).
echo For now, the app will open through Python.
set "OWL_EXE="

:shortcut
if defined OWL_EXE (
  set "OWL_TARGET=%OWL_EXE%"
  set "OWL_SCRIPT="
  set "OWL_ICON=%OWL_EXE%"
) else (
  set "OWL_TARGET=%VPYW%"
  set "OWL_SCRIPT=%~dp0app\app.py"
  set "OWL_ICON=%~dp0app\assets\icon.ico"
)
set "OWL_DIR=%~dp0"
if exist "%VENV%\shortcuts-asked" goto :shortcut_update
echo.> "%VENV%\shortcuts-asked"
echo.
choice /c YN /m "Add OwlCheck shortcuts to the desktop and the Start menu"
if errorlevel 2 goto :launch
set "OWL_MODE=create"
call :write_shortcuts
if errorlevel 1 (echo Couldn't create the shortcuts. You can always open OwlCheck with this file.) else (echo "OwlCheck" shortcuts added to the desktop and the Start menu.)
goto :launch

:shortcut_update
rem Ask only once, but keep existing shortcuts pointing at the .exe (or back at Python)
set "OWL_MODE=update"
call :write_shortcuts

:launch
echo.
echo Opening OwlCheck...
if defined OWL_EXE goto :launch_exe
start "" "%VPYW%" "%~dp0app\app.py"
timeout /t 3 >nul
exit /b 0

:launch_exe
start "" "%OWL_EXE%"
rem If the .exe dies on startup (often antivirus), fall back to Python and point at the log
timeout /t 8 >nul
tasklist /fi "imagename eq OwlCheck.exe" 2>nul | find /i "OwlCheck.exe" >nul
if not errorlevel 1 exit /b 0
echo.
echo OwlCheck.exe closed right after opening. What happened is logged in:
echo   %~dp0dist\OwlCheck\owlcheck-log.txt
echo Please send that file along with your bug report. Meanwhile, the app will open through Python.
start "" "%VPYW%" "%~dp0app\app.py"
echo.
pause
exit /b 0

rem OWL_MODE=update only rewrites shortcuts that already exist
:write_shortcuts
powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; $a=''; if($env:OWL_SCRIPT){$a=[char]34+$env:OWL_SCRIPT+[char]34}; foreach($d in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'))){ $f=Join-Path $d 'OwlCheck.lnk'; if($env:OWL_MODE -eq 'update' -and -not (Test-Path -LiteralPath $f)){continue}; $s=$w.CreateShortcut($f); $s.TargetPath=$env:OWL_TARGET; $s.Arguments=$a; $s.WorkingDirectory=$env:OWL_DIR; $s.IconLocation=$env:OWL_ICON; $s.Save() }"
exit /b %errorlevel%

rem 3.12 first: it's the version pythonnet is known to work with
:find_python
set "PY="
for %%V in (3.12 3.13 3.11 3.10) do (
  if not defined PY py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
)
if defined PY exit /b 0
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
  set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  exit /b 0
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1 && set "PY=python"
exit /b 0

rem Errors. Each one tells the user what to do next.
:not_extracted
echo It looks like you opened this file from inside the .zip.
echo Extract the zip first: right-click it, choose "Extract All...",
echo then open this file from the extracted folder.
goto :end_pause

:no_python
echo Python isn't installed on this computer.
call :install_python
if errorlevel 1 goto :end_pause
call :find_python
if not defined PY goto :python_installed_restart
goto :create_venv

:python_installed_restart
echo Python was installed, but Windows doesn't see it in this window yet.
echo Close this window and open this file again.
goto :end_pause

:fail_clr
echo.
echo The piece that connects the app to Windows ^(pythonnet^) didn't work with
echo this Python version. The safest version is Python 3.12.
call :install_python
if errorlevel 1 goto :end_pause
echo Rebuilding the environment with Python 3.12...
rmdir /s /q "%VENV%"
goto :begin

:fail_venv
echo Couldn't set up the environment with the Python that was found ^(%PY%^).
echo Install Python 3.12 from python.org and try again.
goto :end_pause

:fail_pip
echo.
echo Installing the dependencies failed. Check your internet connection and try again.
echo If it keeps failing, copy the messages above into a bug report.
goto :end_pause

:fail_app
echo.
echo The app couldn't start. Copy the messages above into a bug report.
goto :end_pause

:install_python
where winget >nul 2>&1
if errorlevel 1 goto :manual_python
echo.
choice /c YN /m "Install Python 3.12 now with winget, Windows' official installer"
if errorlevel 2 goto :manual_python
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto :manual_python
exit /b 0

:manual_python
echo.
echo Install Python 3.12 from https://www.python.org/downloads/windows/
echo and tick "Add python.exe to PATH" on the first screen. Then open this file again.
exit /b 1

:end_pause
echo.
pause
exit /b 1
