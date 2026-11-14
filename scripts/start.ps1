$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
docker compose up --build --detach
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
