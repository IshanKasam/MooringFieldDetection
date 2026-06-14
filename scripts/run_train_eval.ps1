$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Log = Join-Path $Root "data\pipeline_run.log"
Set-Location $Root

function Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Add-Content -Path $Log -Value $line -Encoding utf8
}

Log ">>> train"
& $Python -m mooring_fields.cli train 2>&1 | Out-File -FilePath $Log -Append -Encoding utf8
if ($LASTEXITCODE -ne 0) { Log "train FAILED exit $LASTEXITCODE"; exit $LASTEXITCODE }

Log ">>> evaluate"
& $Python -m mooring_fields.cli evaluate 2>&1 | Out-File -FilePath $Log -Append -Encoding utf8
if ($LASTEXITCODE -ne 0) { Log "evaluate FAILED exit $LASTEXITCODE"; exit $LASTEXITCODE }

Log "=== train + evaluate complete ==="
