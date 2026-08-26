param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("start", "stop")]
    [string]$Action
)

$ErrorActionPreference = "Stop"
$configPath = Join-Path $env:ProgramData "PiServer\gaming-session.json"

try {
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    $token = (Get-Content -LiteralPath $config.tokenFile -Raw).Trim()
    $headers = @{ Authorization = "Bearer $token" }
    Invoke-RestMethod -Method Post -Uri "$($config.controllerUrl)/api/session/$Action" `
        -Headers $headers -TimeoutSec 10 | Out-Null
} catch {
    # A controller outage must never prevent Sunshine from starting a stream.
    # Safe failure means automatic shutdown stays disabled or delayed; manual
    # shutdown remains available from the control page.
    Write-Warning "PiServer session notification failed: $($_.Exception.Message)"
}

exit 0
