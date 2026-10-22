#!/usr/bin/env bash
# Apply the NFSv4-only boundary documented in docs/media-nfs-tailscale.md.
set -euo pipefail
[[ ${EUID} -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
TAIL_IP=$(tailscale ip -4)
[[ ${TAIL_IP} =~ ^100\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo 'Expected one connected Tailscale IPv4 address.' >&2; exit 1;
}
mountpoint -q /srv/media
systemctl is-active --quiet tailscaled.service
if findmnt -rn -t nfs,nfs4 -o OPTIONS | grep -Eq '(^|,)vers=(2|3)(,|$)'; then
  echo 'An outgoing mount still requires NFSv2/v3; migrate it first.' >&2; exit 1;
fi
BACKUP_DIR=$(mktemp -d /root/nfs-security-before-XXXXXXXX)
chmod 0700 "${BACKUP_DIR}"
for file in /etc/nfs.conf.d/90-piserver-tailscale.conf \
  /etc/systemd/system/nfs-server.service.d/tailscale.conf \
  /etc/systemd/system/rpcbind.socket.d/loopback.conf \
  /etc/systemd/system/nfs-mountd.service.d/v4-only.conf; do
  if [[ -e ${file} ]]; then cp --parents -a "${file}" "${BACKUP_DIR}/"; fi
done
systemctl is-enabled rpc-statd.service > "${BACKUP_DIR}/rpc-statd-state.txt" 2>&1 || true
install -d -m 0755 /etc/nfs.conf.d /etc/systemd/system/nfs-mountd.service.d \
  /etc/systemd/system/nfs-server.service.d /etc/systemd/system/rpcbind.socket.d
cat > /etc/nfs.conf.d/90-piserver-tailscale.conf <<EOF
[nfsd]
host = ${TAIL_IP}
port = 2049
tcp = yes
udp = no
vers3 = no
vers4 = yes
vers4.0 = no
vers4.1 = yes
vers4.2 = yes
rdma = no
EOF
cat > /etc/systemd/system/nfs-server.service.d/tailscale.conf <<EOF
[Unit]
Requires=tailscaled.service
After=tailscaled.service srv-media.mount
RequiresMountsFor=/srv/media
BindsTo=srv-media.mount

[Service]
ExecStartPre=/usr/bin/mountpoint -q /srv/media
ExecStartPre=/usr/bin/timeout 60 /usr/bin/bash -c 'until /usr/bin/tailscale ip -4 2>/dev/null | /usr/bin/grep -Fxq ${TAIL_IP}; do /usr/bin/sleep 1; done'
EOF
# NFSv4 clients use TCP 2049 directly. Keep auxiliary RPC discovery local.
cat > /etc/systemd/system/rpcbind.socket.d/loopback.conf <<'EOF'
[Socket]
ListenStream=
ListenDatagram=
ListenStream=/run/rpcbind.sock
ListenStream=127.0.0.1:111
ListenStream=[::1]:111
ListenDatagram=127.0.0.1:111
ListenDatagram=[::1]:111
EOF
cat > /etc/systemd/system/nfs-mountd.service.d/v4-only.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/sbin/rpc.mountd --no-nfs-version 2 --no-nfs-version 3
EOF
# All existing mounts were checked above; NFSv4 manages locks itself.
systemctl mask --now rpc-statd.service
systemctl daemon-reload
systemctl stop nfs-server.service rpcbind.service rpcbind.socket
systemctl start rpcbind.socket rpcbind.service nfs-server.service
LISTENERS=$(ss -H -lnt '( sport = :2049 )' | awk '{print $4}')
[[ ${LISTENERS} == "${TAIL_IP}:2049" ]] || {
  echo "Unexpected NFS listener: ${LISTENERS}" >&2; exit 1;
}
grep -Eq '(^| )-3( |$)' /proc/fs/nfsd/versions
grep -Eq '(^| )-4\.0( |$)' /proc/fs/nfsd/versions
ss -lntup '( sport = :2049 or sport = :111 )'
cat /proc/fs/nfsd/versions
echo "Previous overrides saved in ${BACKUP_DIR}."
