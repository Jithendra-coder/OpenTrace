# OpenTrace -- One-Command Demo
# Runs the full analyze -> migrate -> validate -> status pipeline
# against the built-in ecommerce demo.
#
# Usage (PowerShell):
#   .\demo.ps1

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  OpenTrace V1 -- Full Pipeline Demo" -ForegroundColor White
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

$env:PYTHONIOENCODING = "utf-8"
$env:OPENTRACE_WORKSPACE = "."

# Clean up any previous run
foreach ($dir in @(".opentrace", ".specimpact")) {
    if (Test-Path $dir) {
        Remove-Item -Recurse -Force $dir
        Write-Host "  [cleaned] Previous $dir/ workspace" -ForegroundColor DarkGray
    }
}
Write-Host ""

# Step 1: Analyze
Write-Host "  STEP 1 -- Analyze" -ForegroundColor Yellow
Write-Host "  --------------------------------------------------" -ForegroundColor DarkGray
python -m opentrace.cli.main analyze `
    --old-spec demo/payment_api_v1.yaml `
    --new-spec demo/payment_api_v2.yaml `
    --repo demo/ecommerce `
    --output-dir .
if ($LASTEXITCODE -ne 0) { Write-Host "  FAILED" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  STEP 2 -- Migrate" -ForegroundColor Yellow
Write-Host "  --------------------------------------------------" -ForegroundColor DarkGray
python -m opentrace.cli.main migrate --policy balanced
if ($LASTEXITCODE -ne 0) { Write-Host "  FAILED" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  STEP 3 -- Validate (sandbox)" -ForegroundColor Yellow
Write-Host "  --------------------------------------------------" -ForegroundColor DarkGray
python -m opentrace.cli.main validate
if ($LASTEXITCODE -ne 0) { Write-Host "  FAILED" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  STEP 4 -- Status" -ForegroundColor Yellow
Write-Host "  --------------------------------------------------" -ForegroundColor DarkGray
python -m opentrace.cli.main status

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Demo complete." -ForegroundColor Green
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor White
Write-Host "    opentrace apply              # apply to real files (confirm required)" -ForegroundColor DarkGray
Write-Host "    opentrace pr --dry-run       # preview GitHub PR" -ForegroundColor DarkGray
Write-Host "    uvicorn opentrace.main:app --port 8000   # open dashboard" -ForegroundColor DarkGray
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
