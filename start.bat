@echo off
cd /d "%~dp0"
title Multi-Agent Workbench

:: Find conda activate.bat
set "ACTIVATE="
if exist "%UserProfile%\Miniconda3\Scripts\activate.bat" set "ACTIVATE=%UserProfile%\Miniconda3\Scripts\activate.bat"
if exist "%UserProfile%\miniconda3\Scripts\activate.bat" set "ACTIVATE=%UserProfile%\miniconda3\Scripts\activate.bat"
if exist "%UserProfile%\Anaconda3\Scripts\activate.bat" set "ACTIVATE=%UserProfile%\Anaconda3\Scripts\activate.bat"
if exist "%UserProfile%\anaconda3\Scripts\activate.bat" set "ACTIVATE=%UserProfile%\anaconda3\Scripts\activate.bat"
if exist "C:\ProgramData\Miniconda3\Scripts\activate.bat" set "ACTIVATE=C:\ProgramData\Miniconda3\Scripts\activate.bat"
if exist "C:\ProgramData\Anaconda3\Scripts\activate.bat" set "ACTIVATE=C:\ProgramData\Anaconda3\Scripts\activate.bat"

if "%ACTIVATE%"=="" (
    echo [ERROR] Cannot find conda. Install Miniconda first.
    pause
    exit /b 1
)

:menu
cls
echo ==================================================
echo   Multi-Agent Workbench
echo ==================================================
echo   1. Start Services
echo   2. Stop Services
echo   3. Restart Services
echo   4. Check Status
echo   0. Exit
echo ==================================================
set /p choice="Enter option (0-4): "

if "%choice%"=="1" goto do_start
if "%choice%"=="2" goto do_stop
if "%choice%"=="3" goto do_restart
if "%choice%"=="4" goto do_status
if "%choice%"=="0" goto do_exit
echo Invalid option.
timeout /t 2 >nul
goto menu

:do_start
echo.
echo ==================================================
echo   Starting Services ...
echo ==================================================
if not exist "frontend\node_modules" (
    echo Installing frontend deps first ...
    cd frontend
    call npm install --silent
    cd /d "%~dp0"
)

:: Write backend launcher
> "%TEMP%\maw_be.bat" echo @echo off
>> "%TEMP%\maw_be.bat" echo call "%ACTIVATE%" multiagent
>> "%TEMP%\maw_be.bat" echo cd /d "%~dp0"
>> "%TEMP%\maw_be.bat" echo python server.py

:: Write frontend launcher
> "%TEMP%\maw_fe.bat" echo @echo off
>> "%TEMP%\maw_fe.bat" echo cd /d "%~dp0frontend"
>> "%TEMP%\maw_fe.bat" echo npm run dev

:: Launch hidden (no windows at all)
echo Starting backend (port 9000) ...
powershell -Command "Start-Process '%TEMP%\maw_be.bat' -WindowStyle Hidden"
echo Starting frontend (port 3000) ...
powershell -Command "Start-Process '%TEMP%\maw_fe.bat' -WindowStyle Hidden"

echo.
echo [OK] Services running in background!
echo     Frontend: http://localhost:3000
echo     Backend:  http://localhost:9000/docs
echo.
echo     Use option 2 to stop, option 4 to check status.
echo ==================================================
timeout /t 3 >nul
exit

:do_stop
echo.
echo ==================================================
echo   Stopping Services ...
echo ==================================================
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr LISTENING ^| findstr :9000') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr LISTENING ^| findstr :3000') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr LISTENING ^| findstr :3001') do taskkill /F /PID %%a >nul 2>&1
echo [OK] Stopped.
pause
goto menu

:do_restart
echo.
echo Stopping ...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr LISTENING ^| findstr :9000') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr LISTENING ^| findstr :3000') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr LISTENING ^| findstr :3001') do taskkill /F /PID %%a >nul 2>&1
echo Waiting 3 seconds ...
timeout /t 3 /nobreak >nul
goto do_start

:do_status
echo.
echo ==================================================
echo   Service Status
echo ==================================================
set "be_found=NO"
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr LISTENING ^| findstr :9000') do (
    echo [OK] Backend running on port 9000 (PID %%a)
    set "be_found=YES"
)
if "%be_found%"=="NO" echo [X] Backend not running

set "fe_found=NO"
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr LISTENING ^| findstr :3000') do (
    echo [OK] Frontend running on port 3000 (PID %%a)
    set "fe_found=YES"
)
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr LISTENING ^| findstr :3001') do (
    echo [OK] Frontend running on port 3001 (PID %%a)
    set "fe_found=YES"
)
if "%fe_found%"=="NO" echo [X] Frontend not running
echo ==================================================
pause
goto menu

:do_exit
del /f /q "%TEMP%\maw_be.bat" >nul 2>nul
del /f /q "%TEMP%\maw_fe.bat" >nul 2>nul
exit /b 0
