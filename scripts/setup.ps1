# Setup script for the Meeting Agent (Windows).
# Requires Python 3.10+.

python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\pip install -e ".[dev]"

Write-Host ""
Write-Host "Setup complete. Activate with: .\.venv\Scripts\Activate.ps1"
Write-Host "Run tests with: pytest"
Write-Host "Start agent with: python -m app.main"
