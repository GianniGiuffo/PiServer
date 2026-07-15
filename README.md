# Raspberry Pi 4 (4 GB) home server

This repository is the reproducible configuration for a Raspberry Pi 4 with 4 GB RAM that provides:

- a private remote network using **Tailscale** (WireGuard-based);
- network-wide DNS blocking through **Pi-hole**, on the home LAN and Tailnet;
- **Vaultwarden**, a Bitwarden-compatible self-hosted server, under its own public HTTPS name;
- two public static websites served by Caddy, refreshed automatically from GitHub;
- a private photo/video cloud using **Nextcloud**, reachable only through Tailscale.

It is intentionally designed so that Caddy has no host ports and receives public web traffic only through an outbound Cloudflare Tunnel. Pi-hole DNS stays private to the LAN/Tailnet; Nextcloud and the Pi-hole dashboard are bound to loopback and exposed privately by Tailscale Serve.

> [!NOTE]
> A Pi 4 with 4 GB is sufficient for this personal, low-traffic setup when the application state is on an SSD. Do not add video transcoding, AI photo recognition, Collabora/OnlyOffice, or other heavy services. Keep one or two simultaneous Nextcloud users in mind; direct playback is fine when the client supports the original video format.

> [!IMPORTANT]
> GitHub must contain configuration and documentation, **not** passwords, Vaultwarden data, databases, photos, videos, TLS certificates, or backups. The application state lives on the SSD and is backed up, encrypted, with Restic. Without a tested off-device backup, an OS rebuild is not a recovery plan.

## Architecture

```text
Internet ── Cloudflare HTTPS ── outbound tunnel ── Caddy ── static site 1 / static site 2 / Vaultwarden

Home LAN + Tailnet ── DNS :53 ── Pi-hole ── upstream resolvers
Tailnet only ── Tailscale Serve (HTTPS) ── Nextcloud + Pi-hole dashboard

SSD ── Nextcloud files, PostgreSQL, Vaultwarden, Pi-hole, Caddy certificates
                         │
                    Restic encrypted backup (off-device)
```

## What you need before deploying

1. A Raspberry Pi OS Lite **64-bit** installation on an SSD (not a microSD for this workload), with SSH enabled and a non-root user.
2. A fixed DHCP lease for the Pi in the router; an external SSD in `ext4`, mounted persistently at `/srv`.
3. A Cloudflare account and the existing domain added to it. This deployment uses Cloudflare Tunnel, so it also works behind CGNAT and does not expose router ports. See [docs/cloudflare-tunnel.md](docs/cloudflare-tunnel.md).
4. A Tailscale account and the Tailscale app installed on every device that should access the NAS, Pi-hole dashboard, or administration remotely.
5. An off-device Restic repository (another disk stored elsewhere, S3-compatible storage, or a backup host) and its encryption password stored in your password manager.

## First deployment

The complete, ordered procedure is in [docs/first-boot.md](docs/first-boot.md). The short version, to run on the Pi, is:

```bash
git clone https://github.com/YOUR_ACCOUNT/raspberry-server.git /opt/raspberry-server
cd /opt/raspberry-server
sudo bash ./scripts/bootstrap.sh
cp .env.example .env
chmod 600 .env
# edit .env with real domains and secrets
docker compose config --quiet
docker compose up -d
sudo ./scripts/configure-tailscale-serve.sh
```

Do not run the sample command until `docs/first-boot.md` is complete: the script installs packages and creates the runtime directories.

## Two different kinds of “automatic update”

- The two **websites** are pulled and built every minute by a systemd timer. This needs no inbound webhook, no open SSH port and no GitHub runner with control of the Pi. Configure the two source repositories in `config/sites/`.
- **Container image updates** are deliberately manual and reviewed. Pin images to digests after verifying them, back up first, then run `docker compose pull && docker compose up -d`. Automatic unreviewed upgrades of a password manager or a NAS are not a good default.

## Security boundaries

- Never expose port `53`, PostgreSQL, Redis, SMB, SSH or the Pi-hole dashboard to the public Internet. With the tunnel configuration, do not create router forwards for `80` or `443` either.
- Enable two-factor authentication in Vaultwarden before putting credentials in it. Enable registration only for the initial account, then set `VAULTWARDEN_SIGNUPS_ALLOWED=false` in `.env` and redeploy Vaultwarden.
- Give every Tailnet device a personal account; do not share the account. Restrict access with Tailnet ACLs if more people join.
- Pi-hole blocks DNS-known advertising and tracking domains. It cannot reliably remove ads served from the same domain as the content (notably many YouTube/social ads), and a device that bypasses your DNS or uses encrypted DNS can evade it.

See [docs/security.md](docs/security.md) and [docs/backup-and-restore.md](docs/backup-and-restore.md) before storing important data.
