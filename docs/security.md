# Security baseline

## Exposure rules

| Service | Access path | Public Internet |
| --- | --- | --- |
| Public sites | Caddy HTTPS | Yes, port 443 only |
| Vaultwarden | Caddy HTTPS | Yes, port 443 only |
| Nextcloud / photo NAS | Tailscale Serve HTTPS | No |
| Pi-hole DNS | Home LAN and Tailnet | No |
| Pi-hole dashboard | Tailscale Serve HTTPS | No |
| SSH | Tailscale SSH or LAN during setup | No router forwarding |
| PostgreSQL / Redis | Docker internal network | No |

Do not add port forwarding for a service merely to make an app work remotely. Install Tailscale on the client instead.

## Vaultwarden

Vaultwarden is a third-party Bitwarden-compatible server; it is not the official Bitwarden self-hosted product. It is suitable for a personal deployment when treated as a critical service:

1. Use a dedicated `vault.example.com` HTTPS name; do not use an IP address or plain HTTP.
2. Keep `SIGNUPS_ALLOWED=false`. Create the initial account, then enable two-factor authentication on it immediately.
3. Use a long master password which is not stored in the vault itself. Save the recovery information separately.
4. Keep the `/admin` token as an Argon2 hash in `.env`. The `/admin` panel is optional; remove `ADMIN_TOKEN` from the configuration if it is not needed.
5. Verify a restore of the Vaultwarden data before relying on it. A password manager without a restore test is a single point of failure.

## Tailscale and the NAS

Enable MagicDNS and HTTPS in the Tailnet. Use individual identities for each person and revoke a device as soon as it is lost. Once the basic setup is working, create ACLs that allow only your own user/devices to reach `rpi-server:443` and DNS port `53`.

Tailscale Serve is intentionally private. Do not use Tailscale Funnel for Nextcloud, Pi-hole, SSH or administration.

## Pi-hole limits and privacy

Pi-hole blocks DNS requests to known advertising and tracking domains. It cannot remove advertisements delivered by the same host as the desired content, cannot defeat browser-level encrypted DNS if the client bypasses it, and should not be presented as a complete ad blocker. Use browser content blocking in addition for the best result.

The configured upstream resolvers are Quad9. You may change them to another provider or run a local recursive resolver later, but choose intentionally: the upstream DNS provider still sees the domains your network asks for.

## Host maintenance

- Apply Raspberry Pi OS security updates regularly, preferably after a recent backup.
- Review container-image updates and pin the approved digest; do not track `latest` permanently.
- Check `systemctl list-timers`, `docker compose ps`, `tailscale status` and the backup logs monthly.
- Keep the router firmware up to date and disable UPnP automatic port forwarding if it is not needed.
