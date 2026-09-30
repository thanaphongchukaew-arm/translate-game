# One-time model download (spec section 11.2): fetches exactly the files
# listed in models/MANIFEST.json, verifying sha256 after each download.
# Idempotent -- skips a file whose hash already matches. Requires internet
# ONLY for this script; the app itself never downloads anything at runtime
# (HF_HUB_OFFLINE=1 / TRANSFORMERS_OFFLINE=1 are set by scripts/run.ps1).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Get-Sha256Upper($path) {
    (Get-FileHash -Algorithm SHA256 $path).Hash.ToUpper()
}

$manifest = Get-Content "models\MANIFEST.json" -Raw | ConvertFrom-Json

# facebook/nllb-200-distilled-600M's own tokenizer files don't have a
# single-file source_url in the manifest generation (they came from a
# snapshot_download call) -- list them explicitly here alongside the
# manifest-driven downloads.
$extraTokenizerFiles = @(
    @{ File = "fast/nllb200-600m-int8/tokenizer/tokenizer_config.json"; Url = "https://huggingface.co/facebook/nllb-200-distilled-600M/resolve/main/tokenizer_config.json" }
    @{ File = "fast/nllb200-600m-int8/tokenizer/special_tokens_map.json"; Url = "https://huggingface.co/facebook/nllb-200-distilled-600M/resolve/main/special_tokens_map.json" }
)

$totalBytes = 0
$downloaded = 0
$skipped = 0
$failed = 0

foreach ($entry in $manifest.models) {
    $destPath = Join-Path "models" $entry.file
    $destDir = Split-Path -Parent $destPath
    if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Force -Path $destDir | Out-Null }

    if (Test-Path $destPath) {
        $existingHash = Get-Sha256Upper $destPath
        if ($existingHash -eq $entry.sha256.ToUpper()) {
            Write-Host "ข้าม (มีอยู่แล้ว, hash ตรง): $($entry.file)"
            $skipped++
            continue
        }
        Write-Host "hash ไม่ตรง จะดาวน์โหลดใหม่: $($entry.file)" -ForegroundColor Yellow
    }

    Write-Host "ดาวน์โหลด: $($entry.file) จาก $($entry.source_url)"
    try {
        Invoke-WebRequest -Uri $entry.source_url -OutFile $destPath -UseBasicParsing
    } catch {
        Write-Host "ดาวน์โหลดล้มเหลว: $($entry.file) - $_" -ForegroundColor Red
        $failed++
        continue
    }

    $actualHash = Get-Sha256Upper $destPath
    if ($actualHash -ne $entry.sha256.ToUpper()) {
        Write-Host "คำเตือน: hash ของไฟล์ที่ดาวน์โหลดไม่ตรงกับ MANIFEST! ($($entry.file))" -ForegroundColor Red
        Write-Host "  คาดหวัง: $($entry.sha256)"
        Write-Host "  ได้จริง:  $actualHash"
        Remove-Item $destPath -Force
        $failed++
        continue
    }
    Write-Host "ดาวน์โหลดสำเร็จและตรวจ hash ผ่าน: $($entry.file)" -ForegroundColor Green
    $downloaded++
}

foreach ($extra in $extraTokenizerFiles) {
    $destPath = Join-Path "models" $extra.File
    if (Test-Path $destPath) {
        Write-Host "ข้าม (มีอยู่แล้ว): $($extra.File)"
        continue
    }
    Write-Host "ดาวน์โหลด (ไฟล์เสริม tokenizer): $($extra.File)"
    try {
        Invoke-WebRequest -Uri $extra.Url -OutFile $destPath -UseBasicParsing
        Write-Host "สำเร็จ: $($extra.File)" -ForegroundColor Green
    } catch {
        Write-Host "ดาวน์โหลดล้มเหลว (ไม่ร้ายแรง): $($extra.File) - $_" -ForegroundColor Yellow
    }
}

Write-Host "`n=== สรุป ===" -ForegroundColor Cyan
Write-Host "ดาวน์โหลดใหม่: $downloaded | ข้าม (มีอยู่แล้ว): $skipped | ล้มเหลว: $failed"
if ($failed -gt 0) {
    Write-Host "มีไฟล์ดาวน์โหลดล้มเหลว โปรดลองรันสคริปต์นี้ใหม่อีกครั้ง" -ForegroundColor Red
    exit 1
}
Write-Host "ตรวจสอบทั้งหมดด้วย: python tools\verify_models.py" -ForegroundColor Green
