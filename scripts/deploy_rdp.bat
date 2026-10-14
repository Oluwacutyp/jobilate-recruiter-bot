@echo off
REM Jobilate recruiter bot — Windows RDP deploy: venv + install + run.
cd /d "%~dp0.."
if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist .env (
  echo Copying .env.example to .env - EDIT .env with your BOT_TOKEN and ADMIN_CHAT_ID, then re-run.
  copy .env.example .env
  pause
  exit /b 1
)
echo Starting bot...
python run.py
