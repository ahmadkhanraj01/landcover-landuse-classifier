@echo off
rem One-time setup on Windows: creates .venv, installs dependencies, downloads the model.
rem PyPI torch on Windows is CPU-only, so torch comes from the PyTorch CUDA index.
rem Change TORCH_INDEX if your NVIDIA driver needs an older CUDA build (see pytorch.org).
cd /d "%~dp0"
if "%TORCH_INDEX%"=="" set TORCH_INDEX=https://download.pytorch.org/whl/cu130

python -m venv .venv || goto :error
.venv\Scripts\python -m pip install --upgrade pip || goto :error
.venv\Scripts\python -m pip install torch --index-url %TORCH_INDEX% || goto :error
.venv\Scripts\python -m pip install -r requirements.txt || goto :error
.venv\Scripts\python -m landclass.download_model || goto :error
if not exist .env copy example.env .env
.venv\Scripts\python -m landclass.hardware
echo Done. Start the UI with run_ui.bat
goto :eof
:error
echo Setup failed.
exit /b 1
