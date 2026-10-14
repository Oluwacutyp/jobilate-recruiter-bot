# Jobilate recruiter bot — Windows PowerShell run script.
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path .venv)) {
  Write-Host "Creating virtual environment..."
  python -m venv .venv
}
. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
if (-not (Test-Path .env)) {
  Copy-Item .env.example .env
  Write-Host "Created .env from .env.example - edit it with your BOT_TOKEN and ADMIN_CHAT_ID, then re-run."
  exit 1
}
Write-Host "Starting bot..."
python run.py
