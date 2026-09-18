$ErrorActionPreference = "Stop"

# OpenSSH sets SSH_ORIGINAL_COMMAND before invoking the ForceCommand. Reject a
# normal shell, SFTP and every command except the one fixed protocol verb.
if ($env:SSH_ORIGINAL_COMMAND -cne "shutdown") {
    Write-Error "This key only permits the shutdown command."
    exit 126
}

$taskName = "\PiServer-Gaming-Shutdown"
& "$env:SystemRoot\System32\schtasks.exe" /Run /TN $taskName | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Unable to start the protected shutdown task. Re-run install-gaming-host.ps1 as administrator."
    exit $LASTEXITCODE
}

exit 0
