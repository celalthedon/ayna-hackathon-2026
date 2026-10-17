param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$python = 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\ayna-hackathon-2026\notebooks\citypilot-env\Scripts\python.exe'
$env:CITYPILOT_ARTIFACT_DIR = 'C:\Users\celal\OneDrive\Desktop\ayna-hackathon-2026\ayna-hackathon-2026\outputs\c4_model_alpha_20261017_155941_581069'
$env:CITYPILOT_CONFIG_DIR = Join-Path $repo 'supplements\m_services_v1\config'
& $python -I -B -X utf8 -m uvicorn citypilot.api:create_app --factory --app-dir "$repo\src" --host 127.0.0.1 --port $Port --workers 1
if ($LASTEXITCODE -ne 0) { throw "CITYPILOT exited with code $LASTEXITCODE" }
