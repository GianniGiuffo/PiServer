[CmdletBinding()]
param(
    [string]$GamingUser = "gaming",

    [Parameter(Mandatory = $true)]
    [ipaddress]$MiniPcTailscaleIp,

    [Parameter(Mandatory = $true)]
    [uri]$ControllerUrl,

    [Parameter(Mandatory = $true)]
    [string]$ControllerPublicKeyPath,

    [Parameter(Mandatory = $true)]
    [string]$SessionTokenFile
)

$ErrorActionPreference = "Stop"
$GamingUser = $GamingUser.ToLowerInvariant()
if ($GamingUser -notmatch '^[a-z0-9_.-]{1,64}$') {
    throw "GamingUser contiene caratteri non supportati."
}
$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($currentIdentity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Eseguire PowerShell come amministratore."
}

$miniPcOctets = $MiniPcTailscaleIp.GetAddressBytes()
if ($miniPcOctets.Length -ne 4 -or $miniPcOctets[0] -ne 100 -or
    $miniPcOctets[1] -lt 64 -or $miniPcOctets[1] -gt 127) {
    throw "MiniPcTailscaleIp deve appartenere a 100.64.0.0/10."
}
if ($ControllerUrl.Scheme -ne "https" -or $ControllerUrl.Port -ne 8455) {
    throw "ControllerUrl deve essere l'URL HTTPS Tailscale Serve sulla porta 8455."
}
if (-not (Test-Path -LiteralPath $ControllerPublicKeyPath -PathType Leaf)) {
    throw "Chiave pubblica del controller non trovata."
}
if (-not (Test-Path -LiteralPath $SessionTokenFile -PathType Leaf)) {
    throw "File del token di sessione non trovato."
}

$publicKey = (Get-Content -LiteralPath $ControllerPublicKeyPath -Raw).Trim()
if ($publicKey -notmatch '^ssh-ed25519\s+[A-Za-z0-9+/=]+(?:\s+.*)?$') {
    throw "La chiave del controller deve essere una singola chiave Ed25519."
}
$sessionToken = (Get-Content -LiteralPath $SessionTokenFile -Raw).Trim()
if ($sessionToken -notmatch '^[A-Za-z0-9_-]{32,}$') {
    throw "Token di sessione non valido."
}

$localUser = Get-LocalUser -Name $GamingUser -ErrorAction Stop
$administrators = Get-LocalGroup -SID "S-1-5-32-544"
$isAdministrator = Get-LocalGroupMember -Group $administrators -ErrorAction Stop |
    Where-Object { $_.SID -eq $localUser.SID }
if ($isAdministrator) {
    throw "L'account '$GamingUser' deve rimanere un utente standard."
}

$profile = Get-CimInstance Win32_UserProfile |
    Where-Object { $_.SID -eq $localUser.SID.Value } |
    Select-Object -First 1
if (-not $profile -or -not (Test-Path -LiteralPath $profile.LocalPath)) {
    throw "Accedere almeno una volta come '$GamingUser' per creare il profilo, poi ripetere."
}

$capability = Get-WindowsCapability -Online -Name "OpenSSH.Server~~~~0.0.1.0"
if ($capability.State -ne "Installed") {
    Add-WindowsCapability -Online -Name "OpenSSH.Server~~~~0.0.1.0" | Out-Null
}

$programDir = Join-Path $env:ProgramData "PiServer"
New-Item -ItemType Directory -Force -Path $programDir | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "gaming-power.ps1") `
    -Destination (Join-Path $programDir "gaming-power.ps1") -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "gaming-session.ps1") `
    -Destination (Join-Path $programDir "gaming-session.ps1") -Force
$installedToken = Join-Path $programDir "session-token"
Set-Content -LiteralPath $installedToken -Value $sessionToken -Encoding ascii -NoNewline
@{
    controllerUrl = $ControllerUrl.AbsoluteUri.TrimEnd("/")
    tokenFile = $installedToken
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $programDir "gaming-session.json") -Encoding utf8

$systemSid = "*S-1-5-18"
$adminsSid = "*S-1-5-32-544"
$gamingSid = "*$($localUser.SID.Value)"
& icacls.exe $programDir /inheritance:r /grant:r `
    "${systemSid}:(OI)(CI)F" "${adminsSid}:(OI)(CI)F" "${gamingSid}:(OI)(CI)RX" /T | Out-Null
& icacls.exe $installedToken /inheritance:r /grant:r `
    "${systemSid}:F" "${adminsSid}:F" "${gamingSid}:R" | Out-Null

$sshDir = Join-Path $profile.LocalPath ".ssh"
New-Item -ItemType Directory -Force -Path $sshDir | Out-Null
$authorizedKeys = Join-Path $sshDir "authorized_keys"
Set-Content -LiteralPath $authorizedKeys -Value $publicKey -Encoding ascii
& icacls.exe $sshDir /inheritance:r /grant:r `
    "${systemSid}:(OI)(CI)F" "${adminsSid}:(OI)(CI)F" "${gamingSid}:(OI)(CI)F" /T | Out-Null
& icacls.exe $sshDir /setowner $gamingSid /T | Out-Null

$sshdConfig = Join-Path $env:ProgramData "ssh\sshd_config"
$sshd = Join-Path $env:SystemRoot "System32\OpenSSH\sshd.exe"
$beginMarker = "# BEGIN PISERVER GAMING CONTROLLER"
$endMarker = "# END PISERVER GAMING CONTROLLER"
$existing = Get-Content -LiteralPath $sshdConfig -Raw
$pattern = "(?ms)^" + [regex]::Escape($beginMarker) + ".*?^" + [regex]::Escape($endMarker) + "\r?\n?"
$existing = [regex]::Replace($existing, $pattern, "")
$forcedScript = (Join-Path $programDir "gaming-power.ps1").Replace("\", "/")
$block = @"
$beginMarker
Match all
AllowUsers $GamingUser
PubkeyAuthentication yes
PasswordAuthentication no

Match User $GamingUser
    AuthenticationMethods publickey
    ForceCommand powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $forcedScript
    PermitTTY no
    AllowTcpForwarding no
    PermitTunnel no
    GatewayPorts no

Match all
$endMarker
"@
$backup = "$sshdConfig.piserver-backup"
Copy-Item -LiteralPath $sshdConfig -Destination $backup -Force
Set-Content -LiteralPath $sshdConfig -Value ($existing.TrimEnd() + "`r`n`r`n" + $block) -Encoding ascii
& $sshd -t -f $sshdConfig
if ($LASTEXITCODE -ne 0) {
    Copy-Item -LiteralPath $backup -Destination $sshdConfig -Force
    throw "Configurazione OpenSSH non valida; ripristinato il file precedente."
}

Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue |
    Disable-NetFirewallRule
Remove-NetFirewallRule -Name "PiServer-Gaming-Shutdown-SSH" -ErrorAction SilentlyContinue
New-NetFirewallRule -Name "PiServer-Gaming-Shutdown-SSH" `
    -DisplayName "PiServer gaming shutdown from mini PC" -Direction Inbound `
    -Action Allow -Protocol TCP -LocalPort 22 -RemoteAddress $MiniPcTailscaleIp.IPAddressToString `
    -Profile Any | Out-Null

Get-NetFirewallRule -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -like "*Sunshine*" -and $_.Name -notlike "PiServer-*" } |
    Disable-NetFirewallRule
Remove-NetFirewallRule -Name "PiServer-Sunshine-TCP" -ErrorAction SilentlyContinue
Remove-NetFirewallRule -Name "PiServer-Sunshine-UDP" -ErrorAction SilentlyContinue
New-NetFirewallRule -Name "PiServer-Sunshine-TCP" -DisplayName "PiServer Sunshine Tailnet TCP" `
    -Direction Inbound -Action Allow -Protocol TCP -LocalPort 47984,47989,48010 `
    -RemoteAddress "100.64.0.0/10" -Profile Any | Out-Null
New-NetFirewallRule -Name "PiServer-Sunshine-UDP" -DisplayName "PiServer Sunshine Tailnet UDP" `
    -Direction Inbound -Action Allow -Protocol UDP -LocalPort 47998-48000,48002 `
    -RemoteAddress "100.64.0.0/10" -Profile Any | Out-Null

Set-Service -Name sshd -StartupType Automatic
Start-Service -Name sshd
Restart-Service -Name sshd

Write-Host "Configurazione host gaming completata."
Write-Host "Fingerprint da verificare sul mini PC:"
& ssh-keygen.exe -lf (Join-Path $env:ProgramData "ssh\ssh_host_ed25519_key.pub") -E sha256
Write-Host "`nAggiungere ora i callback globali di Sunshine descritti in docs/cloud-gaming.md."
