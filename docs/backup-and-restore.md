# Backup and restore

## What is protected

The backup script takes an encrypted Restic snapshot of:

- the runtime `.env` file (domains and secrets);
- Pi-hole configuration, Vaultwarden data, Nextcloud configuration/custom apps and Caddy state from `DATA_DIR`;
- a PostgreSQL dump made while Nextcloud is in maintenance mode.

Vaultwarden is stopped briefly so its SQLite database is copied consistently. Nextcloud is in maintenance mode for the duration of the snapshot. PostgreSQL's live data directory is intentionally not copied; the dump is the consistent restore source. Redis is only a cache and is not backed up. Nextcloud's `data` directory, containing photos and videos on a separate disk, is deliberately excluded. The backup is not complete until it exists outside the Pi and can be restored.

## Configure Restic

Choose an off-device Restic repository. The following is a generic local-disk example; substitute an S3-compatible endpoint or an SSH/SFTP repository if preferred.

### Local USB disk

Format and mount the chosen USB disk as ext4 before continuing. Add it to `/etc/fstab` by UUID with the `nofail` option so the Pi can still boot if the disk is disconnected. Use a dedicated mount point, for example `/mnt/rpi-backup`. Before formatting, always verify the device name with `lsblk`; formatting erases that whole device.

The backup service checks the mount point before it does anything. It will fail safely if the USB disk is absent instead of writing the repository into the Pi's root filesystem.

```bash
sudo install -d -m 0700 /etc/restic
sudo sh -c 'umask 077; openssl rand -base64 48 > /etc/restic/password'
sudo tee /etc/raspberry-server/backup.env >/dev/null <<'EOF'
RESTIC_REPOSITORY=/mnt/rpi-backup/restic-rpi-server
RESTIC_PASSWORD_FILE=/etc/restic/password
RESTIC_MOUNTPOINT=/mnt/rpi-backup
EOF
sudo chmod 600 /etc/raspberry-server/backup.env
sudo RESTIC_REPOSITORY=/mnt/offsite-backup/restic-rpi-server \
  RESTIC_PASSWORD_FILE=/etc/restic/password restic init
```

The external disk must be mounted before this configuration is used. With `RESTIC_MOUNTPOINT` set, the script refuses to run if that disk is absent, preventing a backup from being written accidentally to the Pi's root filesystem. A disk permanently connected to the same Pi does not protect against theft, fire, electrical damage or accidental deletion; keep at least one encrypted copy elsewhere.

Run the first backup and inspect it:

```bash
cd /opt/raspberry-server
sudo bash scripts/backup.sh
sudo RESTIC_REPOSITORY=/mnt/rpi-backup/restic-rpi-server \
  RESTIC_PASSWORD_FILE=/etc/restic/password restic snapshots
sudo systemctl enable --now backup.timer
systemctl list-timers backup.timer
```

The system timer retains seven daily, four weekly and twelve monthly snapshots. Adjust the retention policy in `scripts/backup.sh` only after deciding how much storage is available.

Keep a copy of `/etc/restic/password` outside this Pi and outside the repository itself. Without it, the encrypted snapshots cannot be recovered.

## Restore after a failed OS or SSD

1. Install Raspberry Pi OS Lite 64-bit on a new disk, mount the data SSD at `/srv`, and clone this repository again to `/opt/raspberry-server`.
2. Run `sudo bash scripts/bootstrap.sh`, authenticate Tailscale, and recreate the network/router conditions from [first-boot.md](first-boot.md). Do **not** start the containers yet.
3. Recreate `/etc/restic/password` from the password manager, write `backup.env`, and verify that `restic snapshots` lists the expected backup.
4. Restore into a clean temporary directory first, inspect it, then copy the contents back to `/opt/raspberry-server` and `/srv/raspberry-server` with correct ownership. For a full recovery, stop Docker before overwriting state:

```bash
sudo systemctl stop docker
mkdir -p /tmp/rpi-restore
sudo RESTIC_REPOSITORY=/mnt/rpi-backup/restic-rpi-server \
  RESTIC_PASSWORD_FILE=/etc/restic/password \
  restic restore latest --target /tmp/rpi-restore
# Inspect /tmp/rpi-restore before copying data into the live paths.
sudo systemctl start docker
```

5. Copy the restored `.env` to `/opt/raspberry-server/.env` (mode `0600`) and the restored Pi-hole, Vaultwarden, Nextcloud configuration/custom-apps and Caddy directories to `/srv/raspberry-server/data`. Restore PostgreSQL only from the captured `nextcloud.sql` file from that same snapshot; do not mix a database dump from one snapshot with files from another. Nextcloud's excluded `data` directory must be restored separately from the photo/video disk backup.
6. Run `docker compose config --quiet`, then `docker compose up -d`, reapply Tailscale Serve, and verify login, photos and a Vaultwarden entry before declaring the recovery complete.

Practice restoring an unimportant test file now. A written restore procedure that has never been exercised is only a hypothesis.
