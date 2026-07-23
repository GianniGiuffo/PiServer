# First boot and deployment

Follow these steps in order. Commands in this document run on the Raspberry Pi, not on the Windows computer used to edit this repository. When the mini PC arrives, use [minipc-migration.md](minipc-migration.md) rather than applying this Raspberry-Pi-specific guide verbatim.

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
# The Pi is the future DNS server, so it must keep using the router's DNS while
# Pi-hole is not running. This does not disable MagicDNS for the Tailnet.
sudo tailscale set --accept-dns=false
```

Install Tailscale on the phone, laptop and tablet that should reach the NAS. Remote DNS is configured later, after Pi-hole has started successfully.

Do **not** configure the Pi-hole IP as a Tailscale global nameserver yet: Pi-hole is not running until step 6, and enabling a DNS override before then can prevent Tailnet devices from resolving any public name. Keep MagicDNS enabled; it is independent of Pi-hole and provides names such as `rpi-server.your-tailnet.ts.net`.

`tailscale set --accept-dns=false` applies only to the Raspberry Pi. It prevents the future DNS server from using its own Tailnet DNS configuration and avoids a bootstrap DNS loop. Other Tailnet devices continue to use MagicDNS and, later, the Pi-hole global nameserver.

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

Set `TAILSCALE_FQDN` to the value printed above, without a trailing dot. For the optional Vaultwarden `/admin` page, create a new long, random **admin password** now. It is not the Bitwarden master password you will create later for your vault.

```bash
docker run --rm -it vaultwarden/server:latest /vaultwarden hash
```

The command asks you to type the new admin password twice, then prints one long line beginning with `$argon2id$`. Copy that whole output into `.env` like this, preserving the single quotes:

```dotenv
VAULTWARDEN_ADMIN_TOKEN='$argon2id$...the-entire-output...'
```

When you later visit `/admin`, log in with the password you typed into the command, **not** with the displayed `$argon2id...` hash. Store the password in your password manager. Keep a second copy of the other secret values there too. Do not put `.env` in GitHub, in an issue, or in a GitHub Actions secret intended for website builds.

For this first deployment, leave the `*_IMAGE` lines in `.env` unchanged. After the server works and its backup is tested, we can pin the images to reviewed immutable digests before future upgrades.

## 5. Publish public hostnames through Cloudflare Tunnel

This connection uses CGNAT, so router port forwarding cannot work. Follow [cloudflare-tunnel.md](cloudflare-tunnel.md) to move DNS safely to Cloudflare, create the tunnel, add its token to `.env`, and publish the root site, second site and Vaultwarden hostnames. Do not create any router port-forwarding rule.

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

Open the Tailnet HTTPS address in a browser. Its root is Nextcloud and `https://YOUR-TAILSCALE-FQDN/admin/` is the Pi-hole dashboard. The private static site uses the dedicated tailnet-only address `https://YOUR-TAILSCALE-FQDN:8443/`, with its private section at `/private/`. On the public domain, `/private/` redirects to an informational page while every private document URL still returns `404`. These services remain inaccessible from the public Internet. The two public sites and Vaultwarden become reachable after the Cloudflare Tunnel routes are active.

Only after the Pi-hole dashboard works, configure remote DNS in a browser on the Tailscale admin console:

1. Open `https://login.tailscale.com/admin/dns` and leave **MagicDNS enabled**.
2. Under **Nameservers**, choose **Add nameserver** > **Custom** and enter the Pi's Tailnet IPv4 address returned earlier by `tailscale ip -4` (normally `100.x.y.z`). Save it as a global nameserver.
3. Enable **Override local DNS** only if you want every connected Tailscale device to use Pi-hole for all its DNS while remote. Leave it off if you only want MagicDNS and prefer each device's local DNS.

The Tailscale phone app does not create Tailnet-wide DNS settings; it receives them from this browser-based admin console. With the app connected, it will use the selected setting automatically. Do not forward port 53 on the router.

For the home LAN, now set the Pi's *LAN* address as the DNS server offered by the router's DHCP service. Do **not** use Pi-hole as the DHCP server initially.

Complete initial Nextcloud setup only through its Tailnet URL. Create a normal daily user after the initial administrator account; use the desktop/mobile Nextcloud clients for large photo and video uploads.

On this 4 GB Pi, keep Nextcloud lean: do not enable Office integration, AI/photo-recognition apps or server-side video transcoding. Configure the mobile client to upload original media; use a device capable of playing the original video codec.

For Vaultwarden, `VAULTWARDEN_SIGNUPS_ALLOWED=true` permits the one initial registration. Open `https://VAULTWARDEN_DOMAIN`, create your account with a unique master password, and enable two-factor authentication. Then immediately close registration:

```bash
cd /opt/raspberry-server
nano .env
# change VAULTWARDEN_SIGNUPS_ALLOWED=true to VAULTWARDEN_SIGNUPS_ALLOWED=false
docker compose up -d vaultwarden
```

## 7. Configure the static-site deployments

The system timer polls every minute after boot. It only runs code chosen in these administrator-owned files, so configure them before enabling the timer:

Build the image required by the first Hugo/Tailwind site, then configure and deploy it:

```bash
cd /opt/raspberry-server
docker build --tag raspberry-server/hugo-builder:0.163.3 \
  --file docker/hugo-builder.Dockerfile docker
sudo install -m 0640 -o root -g "$USER" \
  config/sites/site-1.env.example /etc/raspberry-server/sites/site-1.env
sudo systemctl enable --now site-deploy.timer
sudo systemctl start site-deploy.service
sudo journalctl -u site-deploy.service -n 100 --no-pager
```

The first site's template already contains its public GitHub repository, branch and Hugo build command. The deployment service checks GitHub every minute, but only builds when a new commit exists. Its output becomes the active Caddy site atomically.

Do not create `/etc/raspberry-server/sites/site-2.env` until the second site exists. The timer skips an unconfigured site. When it does, copy `config/sites/site-2.env.example` and set `REPOSITORY`, `BRANCH`, `BUILD_IMAGE`, `BUILD_COMMAND` and `PUBLISH_DIR` for that project.

For a private GitHub repository, create one read-only deploy key for the Pi and add its **public** half in the repository's *Deploy keys*. Store the private half at `~/.ssh/id_ed25519` for the Linux user running the timer, mode `0600`, and add GitHub's verified SSH host key to `~/.ssh/known_hosts`. Do not give the key write access.

## 8. Configure encrypted backups before adding important data

Complete [backup-and-restore.md](backup-and-restore.md), run one backup manually, and test restoring a non-sensitive file. Only then enable the nightly timer:

```bash
sudo systemctl enable --now backup.timer
sudo systemctl start backup.service
sudo journalctl -u backup.service -n 100 --no-pager
```
