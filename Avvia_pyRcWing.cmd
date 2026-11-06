@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python Launcher non trovato. Installa Python 3.11 e seleziona anche Python Launcher.
  pause
  exit /b 1
)

py -3.11 -c "import cadquery, shapely, PIL" >nul 2>nul
if errorlevel 1 (
  echo Installazione delle librerie necessarie per pyRcWing...
  py -3.11 -m pip install --user cadquery shapely==2.2.0 pillow
  if errorlevel 1 (
    echo Installazione non riuscita. Verifica la connessione e che Python 3.11 sia installato.
    pause
    exit /b 1
  )
)

py -3.11 "%~dp0pyRcWing.py"
if errorlevel 1 pause
endlocal

