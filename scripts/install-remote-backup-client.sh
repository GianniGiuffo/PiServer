#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo on the mini-PC." >&2
  exit 1
fi

PUBLIC_KEY_FILE=${1:?Usage: sudo bash scripts/install-remote-backup-client.sh <rack-pi.pub> <rack-pi-tailscale-ip>}
RACK_PI_IP=${2:?Usage: sudo bash scripts/install-remote-backup-client.sh <rack-pi.pub> <rack-pi-tailscale-ip>}
if [[ ! -r ${PUBLIC_KEY_FILE} ]]; then
  echo "Cannot read public key: ${PUBLIC_KEY_FILE}" >&2
  exit 1
fi
if [[ ! ${RACK_PI_IP} =~ ^100\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]] ||
   (( 10#${BASH_REMATCH[1]:-0} < 64 || 10#${BASH_REMATCH[1]:-0} > 127 ||
      10#${BASH_REMATCH[2]:-0} > 255 || 10#${BASH_REMATCH[3]:-0} > 255 )); then
  echo "Expected rack-pi's Tailscale IPv4 address in 100.64.0.0/10." >&2
  exit 1
fi

public_key=$(tr -d '\r\n' < "${PUBLIC_KEY_FILE}")
if [[ ! ${public_key} =~ ^(ssh-ed25519|sk-ssh-ed25519@openssh.com)[[:space:]][A-Za-z0-9+/=]+([[:space:]].*)?$ ]]; then
  echo "Only one Ed25519 public key is accepted." >&2
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
backup_command=${REPO_DIR}/scripts/remote-backup.sh
backup_user=pibackup
restricted_shell=/usr/local/sbin/pibackup-shell
chmod 0755 "${backup_command}" "${REPO_DIR}/scripts/backup-photos.sh"

cat > "${restricted_shell}" <<EOF
#!/bin/sh
if [ "\$#" -eq 2 ] && [ "\$1" = "-c" ] &&
   [ "\$2" = "/usr/bin/sudo -n ${backup_command}" ]; then
  exec /usr/bin/sudo -n "${backup_command}"
fi
echo "This account only runs the rack-pi backup entry point." >&2
exit 1
EOF
chown root:root "${restricted_shell}"
chmod 0755 "${restricted_shell}"
grep -qxF "${restricted_shell}" /etc/shells || printf '%s\n' "${restricted_shell}" >> /etc/shells

if ! id "${backup_user}" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/pibackup \
    --shell "${restricted_shell}" "${backup_user}"
fi
usermod --shell "${restricted_shell}" "${backup_user}"

home_dir=$(getent passwd "${backup_user}" | cut -d: -f6)
install -d -m 0755 -o root -g root "${home_dir}" "${home_dir}/.ssh"
authorized_keys=${home_dir}/.ssh/authorized_keys
printf 'from="%s",restrict,command="/usr/bin/sudo -n %s" %s\n' \
  "${RACK_PI_IP}" "${backup_command}" "${public_key}" > "${authorized_keys}"
chown root:root "${authorized_keys}"
chmod 0644 "${authorized_keys}"

sudoers_file=/etc/sudoers.d/pibackup
printf '%s ALL=(root) NOPASSWD: %s\n' \
  "${backup_user}" "${backup_command}" > "${sudoers_file}"
chown root:root "${sudoers_file}"
chmod 0440 "${sudoers_file}"
visudo -cf "${sudoers_file}"

# Tailscale SSH owns tailnet port 22 when enabled. A dedicated OpenSSH port
# keeps that interactive access intact while still enforcing this forced key.
sshd_dropin=/etc/ssh/sshd_config.d/90-pibackup.conf
cat > "${sshd_dropin}" <<'EOF'
Port 22
Port 2222

Match LocalPort 2222
    AllowUsers pibackup
    PubkeyAuthentication yes
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    AuthenticationMethods publickey
    PermitTTY no
    X11Forwarding no
    AllowTcpForwarding no
    PermitTunnel no
    GatewayPorts no

Match all
EOF
chown root:root "${sshd_dropin}"
chmod 0644 "${sshd_dropin}"
sshd -t
systemctl reload ssh

echo "Restricted SSH backup account installed on port 2222 for source ${RACK_PI_IP}."
