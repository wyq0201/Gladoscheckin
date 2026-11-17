# Failure notifier for the local GLaDOS check-in (PushPlus).
# ASCII only: PowerShell 5.1 mis-decodes UTF-8 without BOM.
#
# Token is NOT stored here. It is read from hw-grow-auto\config.json on the
# same machine, so nothing secret ends up in this git repo.
#
# Usage: notify.ps1 -Code 2 -Log "logs\checkin-20261118.log"

param(
    [int]$Code = 1,
    [string]$Log = ''
)

$ErrorActionPreference = 'Stop'

$Cfg = 'E:\workspace\my_script\hw-grow-auto\config.json'

$token = $null
try {
    $token = (Get-Content -LiteralPath $Cfg -Raw -Encoding UTF8 | ConvertFrom-Json).pushplusToken
} catch {
    Write-Host "[notify] cannot read token from $Cfg : $($_.Exception.Message)"
}

if (-not $token) {
    Write-Host '[notify] no pushplus token, skipped'
    exit 0
}

switch ($Code) {
    2 { $reason = 'NOT LOGGED IN - profile expired, run: node checkin.mjs --login' }
    1 { $reason = 'check-in failed (Cloudflare code=5 or page changed)' }
    default { $reason = "unexpected exit code $Code" }
}

$tail = ''
if ($Log -and (Test-Path -LiteralPath $Log)) {
    $tail = (Get-Content -LiteralPath $Log -Encoding UTF8 -Tail 15) -join "`n"
}

try { Add-Type -AssemblyName System.Web -ErrorAction SilentlyContinue } catch { }
try { $tailHtml = [System.Web.HttpUtility]::HtmlEncode($tail) } catch { $tailHtml = $tail }

$body = @{
    title    = "GLaDOS checkin FAILED (exit $Code)"
    content  = "<b>$reason</b><br><br><pre>$tailHtml</pre>"
    template = 'html'
    token    = $token
}

try {
    $r = Invoke-RestMethod -Uri 'https://www.pushplus.plus/send' -Method Post -Body $body -TimeoutSec 20
    Write-Host "[notify] pushplus code=$($r.code) msg=$($r.msg)"
} catch {
    Write-Host "[notify] push failed: $($_.Exception.Message)"
}

exit 0
