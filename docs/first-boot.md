# First boot and deployment

Follow these steps in order. Commands in this document run on the Raspberry Pi, not on the Windows computer used to edit this repository.

## 1. Prepare the hardware and operating system

Use Raspberry Pi Imager to install **Raspberry Pi OS Lite 64-bit** onto an SSD. This is particularly important on a Raspberry Pi 4 with 4 GB RAM: do not place Docker, databases, or Nextcloud data on a microSD card. In the Imager advanced settings:

- set a unique hostname, for example `rpi-server`;
- create a named non-root administrator user;
- add your SSH public key and disable password-based SSH login;
- configure Wi-Fi only if Ethernet is impossible.

At the router, reserve a fixed LAN address for the Pi. Mount the SSD persistently at `/srv` with `ext4`; do not use NTFS for Docker or Nextcloud state. Update the base system before continuing:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

## 2. Clone configuration and install the host dependencies

Replace `YOUR_ACCOUNT` and run:

```bash
sudo git clone https://github.com/YOUR_ACCOUNT/raspberry-server.git /opt/raspberry-server
sudo chown -R "$USER:$USER" /opt/raspberry-server
cd /opt/raspberry-server
sudo bash scripts/bootstrap.sh
```

The bootstrap script installs Docker Engine/Compose, Tailscale, Restic and the two systemd timers. Log out and back in before using `docker` without `sudo`.

## 3. Join the private network

Authenticate the Pi on Tailscale, then note its name and Tailnet IP:

```bash
sudo tailscale up --ssh --hostname=rpi-server
tailscale status
tailscale ip -4
tailscale status --json | jq -r '.Self.DNSName'
```

Install Tailscale on the phone, laptop and tablet that should reach the NAS. In the Tailnet DNS settings, add the IP returned by `tailscale ip -4` as a global nameserver, and enable the override option only if you want every DNS query made while connected to Tailscale to pass through Pi-hole.

For the home LAN, set the Pi's *LAN* address as the DNS server offered by the router's DHCP service. Do **not** use Pi-hole as the DHCP server initially, and do not forward `53/tcp` or `53/udp` at the router.

## 4. Create runtime configuration and secrets

```bash
cd /opt/raspberry-server
cp .env.example .env
chmod 600 .env
nano .env
```

Fill every `CHANGE_ME` value. Use unique random values, for example:

```bash
openssl rand -base64 48
```

Set `TAILSCALE_FQDN` to the value printed above, without a trailing dot. For the optional Vaultwarden admin page, generate an Argon2 hash interactively and place the complete resulting hash in `VAULTWARDEN_ADMIN_TOKEN`, enclosed in single quotes (the `$` characters are significant):

```bash
docker run --rm -it vaultwarden/server:latest /vaultwarden hash
```

Keep a second copy of the secret values in your password manager. Do not put `.env` in GitHub, in an issue, or in a GitHub Actions secret intended for website builds.

Before deploying, replace the image tags in `.env` with immutable multi-architecture manifest digests. Record a reviewed digest in Git (for example in a future `images.lock.env`) before upgrading it. This makes an OS rebuild repeat the same application versions instead of silently using a newer tag.

## 5. Make only public services public

At your DNS provider, create records for `SITE_1_DOMAIN`, `SITE_2_DOMAIN` and `VAULTWARDEN_DOMAIN` pointing to the public IP of the home connection. Forward only `80/tcp` and `443/tcp` from the router to the Pi's fixed LAN address. If available, forward `443/udp` too for HTTP/3.

If your provider uses CGNAT, public DNS records cannot directly reach the Pi. Do not work around that by exposing random management ports. Keep Tailscale for private access and use either a reverse tunnel service or a small VPS as the public HTTPS edge.

## 6. Start and verify the stack

```bash
cd /opt/raspberry-server
docker compose config --quiet
docker compose pull
docker compose up -d
docker compose ps
sudo bash scripts/configure-tailscale-serve.sh
tailscale serve status
```

Open the Tailnet HTTPS address in a browser. Its root is Nextcloud and `https://YOUR-TAILSCALE-FQDN/admin/` is the Pi-hole dashboard. Both remain inaccessible from the public Internet. The two sites and Vaultwarden become reachable after public DNS has propagated and Caddy has obtained certificates.

Complete initial Nextcloud setup only through its Tailnet URL. Create a normal daily user after the initial administrator account; use the desktop/mobile Nextcloud clients for large photo and video uploads.

On this 4 GB Pi, keep Nextcloud lean: do not enable Office integration, AI/photo-recognition apps or server-side video transcoding. Configure the mobile client to upload original media; use a device capable of playing the original video codec.

## 7. Configure the two static-site deployments

The system timer polls every minute after boot. It only runs code chosen in these administrator-owned files, so configure them before enabling the timer:

```bash
sudo install -m 0640 -o root -g "$USER" \
  config/sites/site-1.env.example /etc/raspberry-server/sites/site-1.env
sudo install -m 0640 -o root -g "$USER" \
  config/sites/site-2.env.example /etc/raspberry-server/sites/site-2.env
sudo nano /etc/raspberry-server/sites/site-1.env
sudo nano /etc/raspberry-server/sites/site-2.env
sudo systemctl enable --now site-deploy.timer
sudo systemctl start site-deploy.service
sudo journalctl -u site-deploy.service -n 100 --no-pager
```

`BUILD_IMAGE`, `BUILD_COMMAND` and `PUBLISH_DIR` must match each site. The examples fit a Node static site that writes to `dist`; a Hugo site might use `BUILD_IMAGE=klakegg/hugo:ext-alpine` and `BUILD_COMMAND=hugo --minify`, with `PUBLISH_DIR=public`.

For a private GitHub repository, create one read-only deploy key for the Pi and add its **public** half in the repository's *Deploy keys*. Store the private half at `~/.ssh/id_ed25519` for the Linux user running the timer, mode `0600`, and add GitHub's verified SSH host key to `~/.ssh/known_hosts`. Do not give the key write access.

## 8. Configure encrypted backups before adding important data

Complete [backup-and-restore.md](backup-and-restore.md), run one backup manually, and test restoring a non-sensitive file. Only then enable the nightly timer:

```bash
sudo systemctl enable --now backup.timer
sudo systemctl start backup.service
sudo journalctl -u backup.service -n 100 --no-pager
```
