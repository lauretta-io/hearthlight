# Quick smoke check for Settings page APIs (run after: docker compose restart webapp)
param(
    [string]$BaseUrl = "http://localhost:3000/api"
)

$ErrorActionPreference = "Continue"
$checks = @(
    @{ Name = "input-sources"; Path = "/settings/input-sources"; MaxSec = 30 },
    @{ Name = "model-options"; Path = "/model-options"; MaxSec = 90 },
    @{ Name = "model-bindings"; Path = "/model-bindings"; MaxSec = 30 },
    @{ Name = "alert-rule-options"; Path = "/settings/alert-rule-options"; MaxSec = 30 }
)

$failed = 0
foreach ($check in $checks) {
    $url = "$BaseUrl$($check.Path)"
    Write-Host "GET $url"
    $raw = curl.exe -m $check.MaxSec -s -w "`nHTTP_CODE=%{http_code}`n" $url
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  FAIL (curl exit $LASTEXITCODE)" -ForegroundColor Red
        $failed++
        continue
    }
    $lines = $raw -split "`n"
    $codeLine = $lines | Where-Object { $_ -match "^HTTP_CODE=" } | Select-Object -Last 1
    $body = ($lines | Where-Object { $_ -notmatch "^HTTP_CODE=" }) -join "`n"
    if ($codeLine -notmatch "HTTP_CODE=200") {
        Write-Host "  FAIL $codeLine" -ForegroundColor Red
        Write-Host "  $($body.Substring(0, [Math]::Min(120, $body.Length)))"
        $failed++
        continue
    }
    try {
        $null = $body | ConvertFrom-Json
        Write-Host "  OK JSON" -ForegroundColor Green
    } catch {
        Write-Host "  FAIL not JSON: $($body.Substring(0, [Math]::Min(80, $body.Length)))" -ForegroundColor Red
        $failed++
    }
}

if ($failed -gt 0) {
    Write-Host "`n$failed check(s) failed." -ForegroundColor Red
    exit 1
}

Write-Host "`nAll settings API checks passed." -ForegroundColor Green
exit 0
