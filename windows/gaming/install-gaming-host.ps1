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
$systemSid = "*S-1-5-18"
$adminsSid = "*S-1-5-32-544"
$gamingSid = "*$($localUser.SID.Value)"
$systemIdentity = [Security.Principal.SecurityIdentifier]::new("S-1-5-18")
$adminsIdentity = [Security.Principal.SecurityIdentifier]::new("S-1-5-32-544")

function Set-RestrictedOpenSshAcl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [bool]$IsDirectory
    )

    & takeown.exe /F $Path /A | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Impossibile acquisire l'elemento OpenSSH '$Path'."
    }

    $acl = Get-Acl -LiteralPath $Path
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in @($acl.Access)) {
        [void]$acl.RemoveAccessRuleSpecific($rule)
    }

    if ($IsDirectory) {
        $inheritance = [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor `
            [Security.AccessControl.InheritanceFlags]::ObjectInherit
    } else {
        $inheritance = [Security.AccessControl.InheritanceFlags]::None
    }
    $propagation = [Security.AccessControl.PropagationFlags]::None
    $allow = [Security.AccessControl.AccessControlType]::Allow
    foreach ($identity in @($systemIdentity, $adminsIdentity)) {
        $accessRule = [Security.AccessControl.FileSystemAccessRule]::new(
            $identity,
            [Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            $propagation,
            $allow
        )
        [void]$acl.AddAccessRule($accessRule)
    }
    Set-Acl -LiteralPath $Path -AclObject $acl

    & icacls.exe $Path /setowner $systemSid | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Impossibile assegnare a SYSTEM l'elemento OpenSSH '$Path'."
    }
}

function Set-RestrictedOpenSshTree {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Directory
    )

    Set-RestrictedOpenSshAcl -Path $Directory -IsDirectory $true
    foreach ($item in @(Get-ChildItem -LiteralPath $Directory -Force)) {
        if ($item.PSIsContainer) {
            Set-RestrictedOpenSshTree -Directory $item.FullName
        } else {
            Set-RestrictedOpenSshAcl -Path $item.FullName -IsDirectory $false
        }
    }
}

# A previous interrupted run may already have applied the restrictive final
# ACL to individual files. Take ownership only of this managed directory and
# its four known files, then restore administrative access before overwriting
# them so the installer remains safely idempotent.
& takeown.exe /F $programDir /A | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Impossibile acquisire la directory gestita '$programDir'."
}
& icacls.exe $programDir /inheritance:r /grant:r `
    "${systemSid}:(OI)(CI)F" "${adminsSid}:(OI)(CI)F" "${gamingSid}:(OI)(CI)RX" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Impossibile ripristinare l'accesso alla directory '$programDir'."
}
$managedProgramFiles = @(
    "gaming-power.ps1",
    "gaming-session.ps1",
    "gaming-session.json",
    "session-token"
)
foreach ($managedName in $managedProgramFiles) {
    $managedPath = Join-Path $programDir $managedName
    & takeown.exe /F $managedPath /A 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        & icacls.exe $managedPath /inheritance:r /grant:r `
            "${systemSid}:F" "${adminsSid}:F" "${gamingSid}:RX" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Impossibile recuperare il file gestito '$managedPath'."
        }
    }
    # A failed takeown is expected when an interrupted run did not yet create
    # this particular file. The directory ACL covers newly created files.
}
& icacls.exe $programDir /inheritance:r /grant:r `
    "${systemSid}:(OI)(CI)F" "${adminsSid}:(OI)(CI)F" "${gamingSid}:(OI)(CI)RX" /T | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Impossibile applicare i permessi amministrativi a '$programDir'."
}

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

& icacls.exe $programDir /inheritance:r /grant:r `
    "${systemSid}:(OI)(CI)F" "${adminsSid}:(OI)(CI)F" "${gamingSid}:(OI)(CI)RX" /T | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Impossibile finalizzare i permessi di '$programDir'."
}
& icacls.exe $installedToken /inheritance:r /grant:r `
    "${systemSid}:F" "${adminsSid}:F" "${gamingSid}:R" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Impossibile proteggere il token di sessione installato."
}

$sshDir = Join-Path $profile.LocalPath ".ssh"
New-Item -ItemType Directory -Force -Path $sshDir | Out-Null
& takeown.exe /F $sshDir /A | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Impossibile acquisire la cartella SSH gestita '$sshDir'."
}
& icacls.exe $sshDir /inheritance:r /grant:r `
    "${systemSid}:(OI)(CI)F" "${adminsSid}:(OI)(CI)F" "${gamingSid}:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Impossibile ripristinare l'accesso alla cartella SSH di '$GamingUser'."
}
$authorizedKeys = Join-Path $sshDir "authorized_keys"
& takeown.exe /F $authorizedKeys /A 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    & icacls.exe $authorizedKeys /inheritance:r /grant:r `
        "${systemSid}:F" "${adminsSid}:F" "${gamingSid}:F" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Impossibile recuperare '$authorizedKeys'."
    }
}
Set-Content -LiteralPath $authorizedKeys -Value $publicKey -Encoding ascii
& icacls.exe $sshDir /inheritance:r /grant:r `
    "${systemSid}:(OI)(CI)F" "${adminsSid}:(OI)(CI)F" "${gamingSid}:(OI)(CI)F" /T | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Impossibile proteggere la cartella SSH di '$GamingUser'."
}
& icacls.exe $sshDir /setowner $gamingSid /T | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Impossibile assegnare la cartella SSH a '$GamingUser'."
}

$sshProgramData = Join-Path $env:ProgramData "ssh"
New-Item -ItemType Directory -Force -Path $sshProgramData | Out-Null
$sshdConfig = Join-Path $sshProgramData "sshd_config"
$sshdConfigDefault = Join-Path $env:SystemRoot "System32\OpenSSH\sshd_config_default"
$sshd = Join-Path $env:SystemRoot "System32\OpenSSH\sshd.exe"
$sshKeygen = Join-Path $env:SystemRoot "System32\OpenSSH\ssh-keygen.exe"
if (-not (Test-Path -LiteralPath $sshdConfig -PathType Leaf)) {
    if (-not (Test-Path -LiteralPath $sshdConfigDefault -PathType Leaf)) {
        throw "Template OpenSSH sshd_config_default non trovato."
    }
    Copy-Item -LiteralPath $sshdConfigDefault -Destination $sshdConfig
}
& $sshKeygen -A
if ($LASTEXITCODE -ne 0) {
    throw "Generazione delle host key OpenSSH fallita."
}
$ed25519HostKey = Join-Path $sshProgramData "ssh_host_ed25519_key.pub"
if (-not (Test-Path -LiteralPath $ed25519HostKey -PathType Leaf)) {
    throw "Host key Ed25519 OpenSSH non generata."
}

# Le versioni recenti di OpenSSH per Windows rifiutano di avviarsi se la
# directory ProgramData\ssh (compresa l'eventuale sottodirectory logs) oppure
# una host key è accessibile da identità diverse da SYSTEM e Administrators.
# ssh-keygen protegge normalmente le chiavi nuove, ma una directory ereditata o
# un precedente avvio fallito può lasciare ACL incompatibili. Ripariamo l'intero
# albero OpenSSH, che è gestito dal servizio, e impostiamo SYSTEM come owner.
# Directory e file richiedono regole distinte: una ACE (OI)(CI) applicata
# direttamente a un file è solo ereditaria e non concede accesso al file stesso.
Set-RestrictedOpenSshTree -Directory $sshProgramData

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
$sshdService = Get-Service -Name sshd -ErrorAction Stop
try {
    if ($sshdService.Status -eq "Running") {
        Restart-Service -Name sshd
    } else {
        Start-Service -Name sshd
    }
} catch {
    $serviceDetails = & sc.exe queryex sshd | Out-String
    throw "Avvio di sshd fallito dopo la convalida della configurazione.`n$serviceDetails"
}
$sshdService = Get-Service -Name sshd
if ($sshdService.Status -ne "Running" -or $sshdService.StartType -ne "Automatic") {
    throw "Il servizio sshd non è attivo con avvio automatico."
}

Write-Host "Configurazione host gaming completata."
Write-Host "Fingerprint da verificare sul mini PC:"
& ssh-keygen.exe -lf $ed25519HostKey -E sha256
Write-Host "`nAggiungere ora i callback globali di Sunshine descritti in docs/cloud-gaming.md."
