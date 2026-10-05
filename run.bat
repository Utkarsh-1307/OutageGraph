@echo off
rem One-click launcher: sets up the venv if needed, then starts the app.
rem   run.bat          -> start the app
rem   run.bat load     -> reload the graph into Neo4j first, then start the app
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || goto :error
)

if not exist ".env" (
    echo .env not found. Copy .env.example to .env and fill in your Neo4j credentials.
    goto :error
)

echo Checking Neo4j connection...
".venv\Scripts\python.exe" -m src.db || (
    echo Could not connect. Is the Aura instance paused? Resume it at https://console.neo4j.io
    goto :error
)

if /i "%~1"=="load" (
    ".venv\Scripts\python.exe" -m src.load_data || goto :error
)

echo Starting app at http://localhost:8501  (close this window or press Ctrl+C to stop)
start "" /min cmd /c "timeout /t 5 >nul & start http://localhost:8501"
".venv\Scripts\python.exe" -m streamlit run app.py
goto :eof

:error
pause
exit /b 1
