$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
    py -3.11 -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    $apiKey = [Convert]::ToHexString($bytes).ToLowerInvariant()
    (Get-Content .env) -replace "replace-with-a-long-random-value", $apiKey | Set-Content .env
    Write-Host "Created .env with a random APP_API_KEY. Keep it secret."
}

& .\.venv\Scripts\python.exe -m pytest
Write-Host "Setup complete. Run: .\scripts\run.ps1"

