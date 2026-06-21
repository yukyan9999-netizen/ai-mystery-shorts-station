$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$dashboard = Join-Path $root "src\dashboard.py"
$stdout = Join-Path $root "logs\dashboard.out.log"
$stderr = Join-Path $root "logs\dashboard.err.log"
$url = "http://127.0.0.1:8765"

if (-not (Test-Path -LiteralPath $python)) {
    throw "가상환경을 찾을 수 없습니다: $python"
}

$healthy = $false
try {
    $response = Invoke-RestMethod -Uri "$url/health" -TimeoutSec 2
    $healthy = $response.status -eq "ok"
} catch {
    $healthy = $false
}

if (-not $healthy) {
    Start-Process `
        -FilePath $python `
        -ArgumentList $dashboard `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr

    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 300
        try {
            $response = Invoke-RestMethod -Uri "$url/health" -TimeoutSec 2
            if ($response.status -eq "ok") {
                $healthy = $true
                break
            }
        } catch {
            $healthy = $false
        }
    }
}

if (-not $healthy) {
    throw "관제실 서버를 시작하지 못했습니다. logs\dashboard.err.log를 확인하세요."
}

Start-Process $url

