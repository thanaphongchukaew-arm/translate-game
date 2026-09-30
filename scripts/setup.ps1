# One-time setup: create the venv, install pinned dependencies, and
# report the GPU/hardware path (spec section 4/11.2).
# Does NOT download models -- run download_models.ps1 separately.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "=== Game Screen Translator: setup ===" -ForegroundColor Cyan

if (-not (Test-Path ".venv")) {
    Write-Host "สร้าง virtual environment..."
    python -m venv .venv
} else {
    Write-Host "พบ .venv อยู่แล้ว ข้ามการสร้างใหม่"
}

$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --upgrade pip --quiet

Write-Host "ติดตั้งไลบรารีตาม requirements.lock..."
& $py -m pip install -r requirements.lock --quiet

# onnxruntime / onnxruntime-gpu / onnxruntime-directml must never coexist
# (spec section 4 caveat) -- requirements.lock pins exactly one, but if a
# previous manual install left another variant behind, warn about it.
$ortVariants = & $py -m pip list --format=freeze 2>$null | Select-String -Pattern "^onnxruntime"
if (($ortVariants | Measure-Object).Count -gt 1) {
    Write-Host "คำเตือน: พบ onnxruntime หลายตัวติดตั้งพร้อมกัน อาจชนกัน:" -ForegroundColor Yellow
    $ortVariants | ForEach-Object { Write-Host "  $_" }
}

Write-Host "`n=== ตรวจสอบฮาร์ดแวร์ ===" -ForegroundColor Cyan
& $py -c @"
import sys
print('Python:', sys.version.split()[0])
try:
    import ctranslate2
    print('CTranslate2 CUDA devices:', ctranslate2.get_cuda_device_count())
except Exception as e:
    print('CTranslate2: ไม่พร้อมใช้งาน (' + str(e) + ')')
try:
    import onnxruntime as ort
    print('onnxruntime providers:', ort.get_available_providers())
except Exception as e:
    print('onnxruntime: ไม่พร้อมใช้งาน (' + str(e) + ')')
"@

Write-Host "`nติดตั้งเสร็จแล้ว ต่อไปรัน: scripts\download_models.ps1" -ForegroundColor Green
