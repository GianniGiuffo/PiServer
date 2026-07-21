# Move the server from Raspberry Pi to the Debian mini PC

Keep the Raspberry Pi online until the mini PC has restored data and passed all
checks. The goal is one controlled tunnel switch, not two servers serving
different copies of Vaultwarden or Nextcloud at the same public domain.

## 1. Install the host

Install **Debian stable 64-bit** (no desktop environment) on the mini PC. In
the firmware/BIOS, enable:

- `Restore on AC Power Loss` / `Power On`, so it starts after a power cut;
- Intel virtualisation only if you expect to use virtual machines later;
- boot from the SSD.

Create a non-root administrator account, enable SSH with an SSH key, update
the system, and reserve a LAN address in the router. Use an ext4 SSD mounted at
`/srv` for Docker state. Avoid full-disk encryption if the server must reboot
unattended after a power outage: it would wait for a local unlock password.

Clone this repository and run the portable bootstrap:

```bash
sudo git clone https://github.com/GianniGiuffo/PiServer.git /opt/raspberry-server
sudo chown -R "$USER:$USER" /opt/raspberry-server
cd /opt/raspberry-server
sudo bash scripts/bootstrap.sh
```

The historical paths keep the name `raspberry-server`; this is only a path and
does not limit the configuration to a Raspberry Pi. The bootstrap script
supports both `arm64` and `amd64` Debian-family hosts.

## 2. Restore configuration and state without making it public yet

1. Copy the real `.env` securely from the password manager or the Restic
   snapshot, set mode `0600`, and update only values that genuinely change.
2. Authenticate the mini PC with Tailscale under a **new hostname** and write
   its new `TAILSCALE_FQDN` to `.env`. Do not reuse the Raspberry Pi node.
3. Configure Restic with the same repository and restore a snapshot into a
   temporary directory. Follow [backup-and-restore.md](backup-and-restore.md)
   to copy only the intended application state and restore the Nextcloud SQL
   dump. Move or restore the separate photo/video disk independently.
4. Start every service except Cloudflared while checking the restored state:

```bash
docker compose up -d caddy pihole vaultwarden postgres redis nextcloud nextcloud-cron
docker compose ps
```

Do not start Cloudflared on the new machine yet. A Tunnel token can create
multiple connectors; doing so before the restore is complete could send public
requests to an unfinished second copy.

5. Configure Tailscale Serve on the mini PC and test Nextcloud and the Pi-hole
dashboard through its **new** Tailnet FQDN. The public website and Vaultwarden
must remain served by the Raspberry Pi during this stage.

If n8n/Ollama is desired, complete [n8n-ollama.md](n8n-ollama.md) only after
the base services and Restic backup work on the mini PC.

## 3. Make the controlled public cutover

Take a fresh Restic backup on the Raspberry Pi, stop the Raspberry Pi's
`cloudflared` container, then start Cloudflared on the mini PC:

```bash
# On the Raspberry Pi
cd /opt/raspberry-server
docker compose stop cloudflared

# On the mini PC, after all local checks passed
cd /opt/raspberry-server
docker compose up -d cloudflared
docker compose ps
```

Check the Cloudflare Tunnel dashboard: it should show the mini PC connector as
healthy. Test the public sites and Vaultwarden from a mobile network, then
update the Tailscale global Pi-hole nameserver from the Raspberry Pi Tailnet IP
to the mini PC Tailnet IP. Only after these tests should the Raspberry Pi be
powered down or repurposed.

## 4. Post-migration checks

```bash
systemctl list-timers
docker compose ps
tailscale status
sudo bash scripts/backup.sh
```

Confirm that the website deployment timer still publishes a new Git commit,
Vaultwarden can create and read an item, Nextcloud opens the separate media
disk, Pi-hole resolves DNS, and a Restic snapshot is new. Do not erase the old
Pi data until one successful restore test exists from the mini PC.
