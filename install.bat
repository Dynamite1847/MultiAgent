@echo off
cd /d "%~dp0"
title Multi-Agent Workbench Installer

echo ==================================================
echo   Multi-Agent Workbench Installer
echo ==================================================
echo.

set "CONDA_DIR=%UserProfile%\Miniconda3"
set "NODE_DIR=%UserProfile%\NodeJS\node-v20.11.1-win-x64"

echo [DEBUG] UserProfile = %UserProfile%
echo [DEBUG] CONDA_DIR   = %CONDA_DIR%
echo [DEBUG] NODE_DIR    = %NODE_DIR%
echo.

:: ==================================================
:: STEP 1: Conda
:: ==================================================
echo [1/4] Checking Conda ...
where conda >nul 2>nul
if not errorlevel 1 (
    echo       Conda found globally. OK.
    goto step2
)
if exist "%CONDA_DIR%\condabin\conda.bat" (
    echo       Conda found at %CONDA_DIR%. OK.
    set "PATH=%CONDA_DIR%\condabin;%CONDA_DIR%\Scripts;%CONDA_DIR%\Library\bin;%PATH%"
    goto step2
)

echo       Conda not found. Downloading Miniconda ...
echo       URL: mirrors.tuna.tsinghua.edu.cn
echo       This may take a few minutes. Please wait ...
powershell -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri 'https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/Miniconda3-latest-Windows-x86_64.exe' -OutFile 'miniconda_installer.exe'"
if not exist "miniconda_installer.exe" (
    echo [FAIL] Download failed. Check your internet connection.
    goto theend
)
echo       Download OK. Installing silently (2-3 min) ...
start /wait "" "miniconda_installer.exe" /InstallationType=JustMe /RegisterPython=0 /AddToPath=0 /S /D=%CONDA_DIR%
del /f /q miniconda_installer.exe >nul 2>nul
if not exist "%CONDA_DIR%\condabin\conda.bat" (
    echo [FAIL] Miniconda install failed.
    goto theend
)
set "PATH=%CONDA_DIR%\condabin;%CONDA_DIR%\Scripts;%CONDA_DIR%\Library\bin;%PATH%"
echo [OK]  Miniconda installed.

:step2
:: ==================================================
:: STEP 2: Node.js
:: ==================================================
echo.
echo [2/4] Checking Node.js ...
where npm >nul 2>nul
if not errorlevel 1 (
    echo       Node.js found globally. OK.
    goto step3
)
if exist "%NODE_DIR%\npm.cmd" (
    echo       Node.js found at %NODE_DIR%. OK.
    set "PATH=%NODE_DIR%;%PATH%"
    goto step3
)

echo       Node.js not found. Downloading ...
echo       URL: mirrors.tuna.tsinghua.edu.cn
echo       Please wait ...
powershell -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri 'https://mirrors.tuna.tsinghua.edu.cn/nodejs-release/v20.11.1/node-v20.11.1-win-x64.zip' -OutFile 'node.zip'"
if not exist "node.zip" (
    echo [FAIL] Download failed. Check your internet connection.
    goto theend
)
echo       Extracting ...
if not exist "%UserProfile%\NodeJS" mkdir "%UserProfile%\NodeJS"
powershell -ExecutionPolicy Bypass -Command "Expand-Archive -Path 'node.zip' -DestinationPath '%UserProfile%\NodeJS' -Force"
del /f /q node.zip >nul 2>nul
if not exist "%NODE_DIR%\npm.cmd" (
    echo [FAIL] Node.js extract failed.
    goto theend
)
set "PATH=%NODE_DIR%;%PATH%"
echo [OK]  Node.js ready.

:step3
:: ==================================================
:: STEP 3: Python backend
:: ==================================================
echo.
echo [3/4] Setting up Python backend ...
echo       Checking if conda env 'multiagent' exists ...
call conda info --envs > "%TEMP%\maw_check.txt" 2>nul
findstr /C:"multiagent" "%TEMP%\maw_check.txt" >nul 2>nul
if not errorlevel 1 (
    echo       Env 'multiagent' already exists. Skipping creation.
    goto step3pip
)
del /f /q "%TEMP%\maw_check.txt" >nul 2>nul

echo       Creating conda env 'multiagent' (Python 3.10) ...
call conda create -n multiagent python=3.10 -y
if errorlevel 1 (
    echo [FAIL] Conda env creation failed.
    goto theend
)

:step3pip
del /f /q "%TEMP%\maw_check.txt" >nul 2>nul
echo       Installing Python dependencies ...
call conda run -n multiagent pip install -i "https://pypi.tuna.tsinghua.edu.cn/simple" --trusted-host pypi.tuna.tsinghua.edu.cn -r requirements.txt
if errorlevel 1 (
    echo [FAIL] pip install failed.
    goto theend
)
echo [OK]  Backend ready.

:: ==================================================
:: STEP 4: Frontend
:: ==================================================
echo.
echo [4/4] Setting up frontend ...
cd frontend
call npm install --registry="https://registry.npmmirror.com"
if errorlevel 1 (
    echo [FAIL] npm install failed.
    cd /d "%~dp0"
    goto theend
)
cd /d "%~dp0"
echo [OK]  Frontend ready.

:: ==================================================
:: Encrypt .env
:: ==================================================
echo.
if not exist ".env" goto skip_encrypt
echo [Extra] Encrypting .env ...
call conda run -n multiagent python -m core.secure_env encrypt
if not exist ".env.enc" (
    echo [WARN] Encryption failed. .env kept as-is.
    goto install_done
)
echo [OK]  Encrypted. Removing plaintext .env ...
del /f /q .env
goto install_done

:skip_encrypt
if exist ".env.enc" (
    echo [Info] .env.enc already exists.
) else (
    echo [Info] No .env file found. Skipping.
)

:install_done
echo.
echo ==================================================
echo   ALL DONE! Run start.bat to launch.
echo ==================================================

:theend
echo.
echo Press any key to close ...
pause >nul
