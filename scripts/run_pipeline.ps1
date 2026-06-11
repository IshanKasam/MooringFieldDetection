# Run remaining pipeline steps: prelabel -> train -> evaluate
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Log = Join-Path $Root "data\pipeline_run.log"

function Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Add-Content -Path $Log -Value $line
    Write-Output $line
}

Log "=== pipeline start ==="

if (-not $env:SKIP_PRELABEL) {
    Log ">>> prelabel"
    & $Python -m mooring_fields.cli prelabel 2>&1 | Tee-Object -FilePath $Log -Append
    if ($LASTEXITCODE -ne 0) { Log "prelabel FAILED exit $LASTEXITCODE"; exit $LASTEXITCODE }
}

Log ">>> train (prelabels, no human review)"
& $Python -m mooring_fields.cli train 2>&1 | Tee-Object -FilePath $Log -Append -Encoding utf8
if ($LASTEXITCODE -ne 0) { Log "train FAILED exit $LASTEXITCODE"; exit $LASTEXITCODE }

Log ">>> evaluate"
& $Python -m mooring_fields.cli evaluate 2>&1 | Tee-Object -FilePath $Log -Append -Encoding utf8
if ($LASTEXITCODE -ne 0) { Log "evaluate FAILED exit $LASTEXITCODE"; exit $LASTEXITCODE }

Log "=== pipeline complete ==="
