# Launch Game Screen Translator using the project venv.
# (Minimal stub for now -- phase 7 will expand this with model-presence
# checks, offline env vars, etc. per spec section 11.2/17.)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONPATH = "src"
& "$root\.venv\Scripts\python.exe" -m gametrans
