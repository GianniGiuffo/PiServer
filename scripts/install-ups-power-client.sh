#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo on the mini PC." >&2
  exit 1
fi

PUBLIC_KEY_FILE=${1:?Usage: install-ups-power-client.sh <minipc-power.pub> <rack-pi-tailscale-ip>}
RACK_PI_IP=${2:?Usage: install-ups-power-client.sh <minipc-power.pub> <rack-pi-tailscale-ip>}
LAN_INTERFACE=${3:-$(ip -4 route show default | awk 'NR == 1 {print $5}')}
[[ -r ${PUBLIC_KEY_FILE} ]] || { echo "Cannot read ${PUBLIC_KEY_FILE}." >&2; exit 1; }
if [[ ! ${RACK_PI_IP} =~ ^100\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]] ||
   (( 10#${BASH_REMATCH[1]:-0} < 64 || 10#${BASH_REMATCH[1]:-0} > 127 ||
      10#${BASH_REMATCH[2]:-0} > 255 || 10#${BASH_REMATCH[3]:-0} > 255 )); then
  echo "Expected rack-pi's Tailscale IPv4 address in 100.64.0.0/10." >&2
  exit 1
fi
public_key=$(tr -d '\r\n' < "${PUBLIC_KEY_FILE}")
[[ ${public_key} =~ ^(ssh-ed25519|sk-ssh-ed25519@openssh.com)[[:space:]][A-Za-z0-9+/=]+([[:space:]].*)?$ ]] || {
  echo "Only one Ed25519 public key is accepted." >&2
  exit 1
}
[[ ${LAN_INTERFACE} =~ ^[A-Za-z0-9_.:-]+$ ]] || { echo "Invalid LAN interface." >&2; exit 1; }
command -v ethtool >/dev/null || {
  echo "Install ethtool on the mini PC before enabling Wake-on-LAN." >&2
  exit 1
}

power_user=pipower
power_command=/usr/local/sbin/rack-minipc-poweroff
restricted_shell=/usr/local/sbin/pipower-shell
cat > "${power_command}" <<'EOF'
#!/bin/sh
exec /usr/bin/systemctl poweroff
EOF
cat > "${restricted_shell}" <<EOF
#!/bin/sh
if [ "\$#" -eq 2 ] && [ "\$1" = "-c" ] && [ "\$2" = "/usr/bin/sudo -n ${power_command}" ]; then
  exec /usr/bin/sudo -n "${power_command}"
fi
echo "This account only powers off the mini PC." >&2
exit 1
EOF
chown root:root "${power_command}" "${restricted_shell}"
chmod 0755 "${power_command}" "${restricted_shell}"
grep -qxF "${restricted_shell}" /etc/shells || printf '%s\n' "${restricted_shell}" >> /etc/shells
if ! id "${power_user}" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/pipower --shell "${restricted_shell}" "${power_user}"
fi
usermod --shell "${restricted_shell}" "${power_user}"
home_dir=$(getent passwd "${power_user}" | cut -d: -f6)
install -d -m 0755 -o root -g root "${home_dir}" "${home_dir}/.ssh"
printf 'from="%s",restrict,command="/usr/bin/sudo -n %s" %s\n' \
  "${RACK_PI_IP}" "${power_command}" "${public_key}" > "${home_dir}/.ssh/authorized_keys"
chown root:root "${home_dir}/.ssh/authorized_keys"
chmod 0644 "${home_dir}/.ssh/authorized_keys"
printf '%s ALL=(root) NOPASSWD: %s\n' "${power_user}" "${power_command}" > /etc/sudoers.d/pipower
chown root:root /etc/sudoers.d/pipower
chmod 0440 /etc/sudoers.d/pipower
visudo -cf /etc/sudoers.d/pipower

cat > /etc/ssh/sshd_config.d/91-pipower.conf <<'EOF'
Port 22
Port 2223

Match LocalPort 2223
    AllowUsers pipower
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
chmod 0644 /etc/ssh/sshd_config.d/91-pipower.conf
sshd -t
systemctl reload ssh
cat > /etc/systemd/system/minipc-wol.service <<EOF
[Unit]
Description=Keep Wake-on-LAN enabled on the mini PC
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/sbin/ethtool -s ${LAN_INTERFACE} wol g
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now minipc-wol.service
ethtool "${LAN_INTERFACE}" | grep -q 'Wake-on: g' || {
  echo "The NIC did not accept Wake-on-LAN; check BIOS and interface name." >&2
  exit 1
}
echo "Restricted UPS shutdown account installed on port 2223; Wake-on-LAN enabled on ${LAN_INTERFACE}."
