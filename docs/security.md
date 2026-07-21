# Security baseline

## Exposure rules

| Service | Access path | Public Internet |
| --- | --- | --- |
| Public sites | Caddy HTTPS | Yes, port 443 only |
| Vaultwarden | Caddy HTTPS | Yes, port 443 only |
| n8n editor (mini PC) | Caddy HTTPS + Cloudflare Access | Yes, only after Access policy |
| n8n webhooks (mini PC) | Caddy HTTPS | Only when a workflow needs a public webhook |
| Ollama | Private Docker `automation` network | No |
| Nextcloud / photo NAS | Tailscale Serve HTTPS | No |
| Pi-hole DNS | Home LAN and Tailnet | No |
| Pi-hole dashboard | Tailscale Serve HTTPS | No |
| SSH | Tailscale SSH or LAN during setup | No router forwarding |
| PostgreSQL / Redis | Docker internal network | No |

Do not add port forwarding for a service merely to make an app work remotely. Install Tailscale on the client instead.

## n8n and Ollama

The optional automation stack is intended for the mini PC, not the 4 GB
Raspberry Pi. It has three important boundaries:

1. `n8n.example.com` is the editor and control plane. Publish it through the
   existing Cloudflare Tunnel only after a Cloudflare Access application allows
   just your own identity. n8n's own account password is still required; Access
   is an additional boundary, not a replacement for it.
2. `hooks.example.com` is deliberately separate. Do not create it until a
   workflow genuinely needs an external webhook. Never put the same Access
   policy in front of it, because third-party webhook senders cannot complete an
   interactive Access login. Protect every public workflow with its native
   secret, signature verification, or an explicit authentication step.
3. Ollama has no host port and is attached only to the Docker-internal
   `automation` network. In n8n, its URL is `http://ollama:11434`, never a LAN
   IP or a public URL.

`N8N_ENCRYPTION_KEY` decrypts stored n8n credentials. Generate it once, keep it
in the password manager and encrypted Restic backup, and never replace it on a
running instance. Losing it makes existing API credentials unrecoverable.

## Vaultwarden

Vaultwarden is a third-party Bitwarden-compatible server; it is not the official Bitwarden self-hosted product. It is suitable for a personal deployment when treated as a critical service:

1. Use a dedicated `vault.example.com` HTTPS name; do not use an IP address or plain HTTP.
2. Set `VAULTWARDEN_SIGNUPS_ALLOWED=true` only for the initial account, then change it to `false`, redeploy Vaultwarden, and enable two-factor authentication on the account immediately.
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
