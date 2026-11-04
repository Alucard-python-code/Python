@echo off
chcp 65001 > nul
echo ====================================================================
echo   UVV Prüfungs-Assistent PRO - GitHub Sync, Setup ^& Desktop-Icon
echo ====================================================================
echo.

:: ⚠️ TRAGE HIER DEINE REALE GITHUB REPO-URL EIN:
set "GITHUB_REPO_URL=https://github.com"

set "PROJECT_DIR=%~dp0tor_pruefung_app"
set "ICON_PATH=%PROJECT_DIR%\app_icon.ico"

:: 1. Prüfen ob Git installiert ist (wichtig für die GitHub-Verbindung)
echo [1/6] Überprüfe Git-Installation...
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [FEHLER] Git ist nicht installiert!
    echo Bitte installieren Sie Git, damit die App Code Updates laden kann.
    echo Download unter: https://git-scm.com
    pause
    exit /b
)

:: 2. Code aus dem GitHub-Repository herunterladen oder aktualisieren
if not exist "%PROJECT_DIR%\main.py" (
    echo [2/6] Klone Repository von GitHub...
    :: Klont den Inhalt direkt in den Ordner tor_pruefung_app
    git clone %GITHUB_REPO_URL% "%PROJECT_DIR%"
) else (
    echo [2/6] Suche nach Updates auf GitHub (git pull)...
    cd /d "%PROJECT_DIR%"
    git pull
    cd /d "%~dp0"
)

:: 3. Prüfen ob Python installiert ist
echo [3/6] Überprüfe Python-Installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [FEHLER] Python ist nicht installiert! Bitte bei der Installation "Add Python to PATH" aktivieren.
    echo Download unter: https://python.org
    pause
    exit /b
)

:: 4. Virtuelle Sandbox-Umgebung einrichten
echo [4/6] Initialisiere virtuelle Sandbox-Umgebung (venv)...
if not exist "%~dp0venv" (
    python -m venv "%~dp0venv"
)
call "%~dp0venv\Scripts\activate.bat"

:: 5. Erforderliche Python-Bibliotheken installieren
echo [5/6] Installiere erforderliche Python-Pakete...
python -m pip install --upgrade pip --quiet
pip install PyQt6 reportlab pillow --quiet

:: 6. Klemmbrett-Icon automatisch herunterladen & per Python zu .ico konvertieren
if not exist "%ICON_PATH%" (
    echo [6/6] Erzeuge Klemmbrett-Icon für Desktop-Verknüpfung...
    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('https://flaticon.com', '%PROJECT_DIR%\temp_icon.png')" >nul 2>&1
    python -c "from PIL import Image; img = Image.open(r'%PROJECT_DIR%\temp_icon.png'); img.save(r'%ICON_PATH%', format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (32, 32)])" >nul 2>&1
    if exist "%PROJECT_DIR%\temp_icon.png" del "%PROJECT_DIR%\temp_icon.png"
)

:: 7. Windows Desktop-Verknüpfung generieren
set "SCRIPT_PATH=%~dp0install_and_start.bat"
powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut(([Environment]::GetFolderPath('Desktop') + '\UVV Prüfungs-Assistent PRO.lnk')); $Shortcut.TargetPath = '%SCRIPT_PATH%'; $Shortcut.IconLocation = '%ICON_PATH%'; $Shortcut.WorkingDirectory = '%~dp0'; $Shortcut.Save()"

echo.
echo ====================================================================
echo   AUTOMATISCHER REPO-SYNC ^& CONFIG ERFOLGREICH!
echo ====================================================================
echo.
echo Starte Anwendung...
cd /d "%PROJECT_DIR%"
python main.py
