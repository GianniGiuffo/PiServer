$ErrorActionPreference = "Stop"

# OpenSSH sets SSH_ORIGINAL_COMMAND before invoking the ForceCommand. Reject a
# normal shell, SFTP and every command except the one fixed protocol verb.
if ($env:SSH_ORIGINAL_COMMAND -cne "shutdown") {
    Write-Error "This key only permits the shutdown command."
    exit 126
}

& "$env:SystemRoot\System32\shutdown.exe" /s /t 60 /d p:0:0 /c "PiServer gaming controller"
exit $LASTEXITCODE
