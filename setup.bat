@echo off
rem One-time setup on Windows: creates .venv and installs dependencies.
cd /d "%~dp0"

python -m venv .venv || goto :error
.venv\Scripts\python -m pip install --upgrade pip || goto :error
.venv\Scripts\python -m pip install -r requirements.txt || goto :error
if not exist .env copy example.env .env
echo Done. Put your MISTRAL_API_KEY in .env, then start the UI with run_ui.bat
goto :eof
:error
echo Setup failed.
exit /b 1
